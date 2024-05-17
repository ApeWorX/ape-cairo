import json
import re
import shutil
import subprocess
from distutils.errors import CompileError
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple, cast

import tomli
from ape.api import CompilerAPI, DependencyAPI, PluginConfig
from ape.exceptions import CompilerError
from ape.logging import logger
from ape.managers.project.dependency import GithubDependency, LocalDependency, NpmDependency
from ape.utils import get_relative_path
from eth_utils import to_hex
from ethpm_types import ContractType
from semantic_version import Version  # type: ignore

from ape_cairo._utils import _communicate, _run

TARGET_DIR = ".build/target"
STARKNET_SCARB = "scarb"
STARKNET_COMPILE = "starknet-compile"
STARKNET_SIERRA_COMPILE = "starknet-sierra-compile"


class CairoConfig(PluginConfig):
    dependencies: Dict[str, DependencyAPI] = {}
    scarb_manifest: Optional[str] = None
    cairo_manifest: Optional[str] = None
    package_manifest: Optional[str] = None


class CairoCompiler(CompilerAPI):
    @property
    def name(self) -> str:
        return "cairo"

    @property
    def config(self) -> CairoConfig:
        return cast(CairoConfig, self.config_manager.get_config(self.name))

    @property
    def scarb_manifest_path(self) -> Optional[Path]:
        if not self.config.scarb_manifest:
            return None

        return Path(self.config.scarb_manifest).expanduser().resolve()

    @property
    def cairo_manifest_path(self) -> Optional[Path]:
        if not self.config.cairo_manifest:
            return None

        return Path(self.config.cairo_manifest).expanduser().resolve()

    @property
    def package_manifest_path(self) -> Optional[Path]:
        if not self.config.package_manifest:
            return None

        return Path(self.config.package_manifest).expanduser().resolve()

    @property
    def _scarb_base_path(self) -> Path:
        if self.scarb_manifest_path is None:
            raise ValueError("Scarb manifest is None")
        return self.scarb_manifest_path.parent

    @property
    def _scarb_build_dir(self) -> Path:
        return self._scarb_base_path / TARGET_DIR

    @property
    def _cairo_build_dir(self) -> Path:
        return self.project_manager.local_project.path / TARGET_DIR

    def get_compiler_settings(
        self, contract_filepaths: List[Path], base_path: Optional[Path] = None
    ) -> Dict[Version, Dict]:
        settings: Dict[Version, Dict] = {}
        for version in self.get_versions(contract_filepaths):
            if version in settings:
                continue

            settings[version] = {}

        return settings

    def get_versions(self, all_paths: Sequence[Path]) -> Set[str]:
        if not all_paths:
            return set()
        return {"2.6.3"}

    def _cairo_process_output_format(self, process: subprocess.Popen) -> None:
        is_error = False
        try:
            # Function to process individual lines from stderr
            def process_debug_line(line: str):
                nonlocal is_error
                patterns = {
                    "error:": logger.error,
                    "warning:": logger.warning,
                    "debug": logger.debug,
                }
                for keyword, log_func in patterns.items():
                    if re.search(keyword, line, re.IGNORECASE):
                        # Extract message following the keyword and log it
                        message = re.split(keyword, line, flags=re.IGNORECASE)[1].strip()
                        log_func(message)
                        if keyword == "error:":
                            is_error = True
                        return True
                return False

            # Read and process lines until process terminates
            while True:
                output_line = process.stdout.readline().strip() if process.stdout else ""
                if output_line:
                    logger.info(output_line)

                debug_line = process.stderr.readline().strip() if process.stderr else ""
                if debug_line and not process_debug_line(debug_line):
                    logger.debug(debug_line)

                if output_line == "" and debug_line == "" and process.poll() is not None:
                    break

        finally:
            process.communicate()

        if is_error:
            raise CompileError("Failed to compile contracts.")

    def _cairo_compile_single_file(
        self,
        contract_filepaths: Sequence[Path],
        bins: Tuple[List[str], List[str]],
        base_path: Optional[Path] = None,
    ) -> List[ContractType]:
        contract_types = []
        starknet_compile_bin, sierra_compile_bin = bins

        contract_filepath = contract_filepaths[0]
        args = [*starknet_compile_bin, "--allow-warnings", "--replace-ids"]
        args.extend(["--single-file"])

        source_id = str(
            get_relative_path(
                contract_filepath,
                base_path if base_path else self.project_manager.local_project.path,
            )
        )
        contract_file_name = contract_filepath.stem
        target_sierra_name = f"{contract_file_name}.contract_class.json"
        sierra_path = self._cairo_build_dir / target_sierra_name
        sierra_artifact = None

        args.extend([str(contract_filepath), str(sierra_path)])
        process = _communicate(*args)
        self._cairo_process_output_format(process)

        if not sierra_path.exists():
            raise CompileError(
                f"Sierra artifact not found at: {sierra_path}. Please verify the build process."
            )

        else:
            logger.info(f"Generated Sierra artifact: {target_sierra_name}.")

            sierra_artifact = sierra_path.read_text()

        target_casm_name = f"{contract_file_name}.compiled_contract_class.json"
        casm_path = self._cairo_build_dir / target_casm_name
        casm_artifact = None

        args = [*sierra_compile_bin, str(sierra_path), str(casm_path), "--add-pythonic-hints"]
        process = _communicate(*args)
        self._cairo_process_output_format(process)

        if not casm_path.exists():
            raise CompileError(
                f"CASM artifact not found at: {casm_path}. Please verify the build process."
            )

        else:
            logger.info(f"Generated CASM artifact: {target_casm_name}.")

            casm_artifact = casm_path.read_text()

        contract_type_instance = ContractType(
            abi=json.loads(sierra_artifact)["abi"],
            contractName=contract_file_name,
            sourceId=source_id,
            runtimeBytecode={"bytecode": to_hex(text=str(casm_artifact))},
            deploymentBytecode={"bytecode": to_hex(text=str(casm_artifact))},
        )

        contract_types.append(contract_type_instance)
        return contract_types

    def _parse_contract_files(self, process: subprocess.Popen) -> List[str]:
        package_contracts = []
        is_valid_line = False
        is_error = False
        try:
            while True:
                output_line = process.stdout.readline().strip() if process.stdout else ""
                debug_line = process.stderr.readline().strip() if process.stderr else ""
                if debug_line:
                    if re.search(
                        r"Use --contract-path to specify which to compile.",
                        debug_line,
                        re.IGNORECASE,
                    ):
                        is_valid_line = False
                        break

                    if re.search(
                        r"More than one contract found in the main crate", debug_line, re.IGNORECASE
                    ):
                        is_valid_line = True
                        continue

                    if re.search(r"error:", debug_line, re.IGNORECASE):
                        message = re.split(r"error:", debug_line, flags=re.IGNORECASE)[1].strip()
                        logger.error(message)
                        is_error = True
                        continue

                    if re.search(r"warning:", debug_line, re.IGNORECASE):
                        message = re.split(r"warning:", debug_line, flags=re.IGNORECASE)[1].strip()
                        logger.warning(message)
                        continue

                    if is_valid_line:
                        package_contracts.append(debug_line)

                # End of process
                if output_line == "" and debug_line == "" and process.poll() is not None:
                    break
        finally:
            # Ensure no output is lost if an exception is raised
            _ = process.communicate()

        if is_error:
            raise CompileError("Failed to compile contracts.")
        return package_contracts

    def _handle_contract_name_collision(
        self, package_contracts: List[str]
    ) -> Dict[str, Dict[str, str]]:
        contract_names: Dict[str, Dict[str, str]] = {}

        for package_contract in package_contracts:
            contract_name = package_contract.split("::")[-1]
            contract_relative_file_path = f"{Path('/'.join(package_contract.split('::')))}.cairo"

            source_id = contract_relative_file_path
            if contract_name in contract_names:
                prev_contract = contract_names[contract_name]
                parts1 = prev_contract["package_contract"].split("::")
                parts2 = package_contract.split("::")

                common_path_index = 0
                for part1, part2 in zip(parts1[::-1], parts2[::-1]):
                    if part1 != part2:
                        break
                    common_path_index += 1

                formatted_path1 = parts1[-common_path_index:] if common_path_index else parts1
                formatted_path2 = parts2[-common_path_index:] if common_path_index else parts2

                del contract_names[contract_name]
                contract_names["_".join(formatted_path1)] = prev_contract
                contract_names["_".join(formatted_path2)] = {
                    "source_id": source_id,
                    "package_contract": package_contract,
                }

            else:
                contract_names[contract_name] = {
                    "source_id": source_id,
                    "package_contract": package_contract,
                }
        return contract_names

    def _cairo_compile_multiple_files(
        self,
        contract_filepaths: Sequence[Path],
        bins: Tuple[List[str], List[str]],
        base_path: Optional[Path] = None,
    ) -> List[ContractType]:
        contract_types = []
        starknet_compile_bin, sierra_compile_bin = bins

        if not self.package_manifest_path or not self.package_manifest_path.exists():
            logger.warning("Package manifest file not found.")
            package_directory = self.project_manager.local_project.path

        else:
            logger.info(f"Using package manifest file: {self.package_manifest_path}.")
            package_directory = self.package_manifest_path.parent

        # dummy process to get contract files that starknet-compile will find
        args = [*starknet_compile_bin, "--allow-warnings", "--replace-ids", package_directory]
        process = _communicate(*args)
        package_contracts = self._parse_contract_files(process)

        logger.debug(f"Crate package contracts: {package_contracts}")
        contract_names = self._handle_contract_name_collision(package_contracts)

        for contract_name, package_contract_item in contract_names.items():
            source_id = package_contract_item["source_id"]
            package_contract = package_contract_item["package_contract"]

            target_sierra_name = f"{contract_name}.contract_class.json"
            sierra_path = self._cairo_build_dir / target_sierra_name
            sierra_artifact = None
            args = [
                *starknet_compile_bin,
                "--allow-warnings",
                "--replace-ids",
                "--contract-path",
                package_contract,
                package_directory,
                sierra_path,
            ]

            process = _communicate(*args)
            self._cairo_process_output_format(process)

            if not sierra_path.exists():
                raise CompileError(
                    f"Sierra artifact not found at: {sierra_path}. Please verify the build process."
                )

            else:
                logger.info(f"Generated Sierra artifact: {target_sierra_name}.")

                sierra_artifact = sierra_path.read_text()

            target_casm_name = f"{contract_name}.compiled_contract_class.json"
            casm_path = self._cairo_build_dir / target_casm_name
            casm_artifact = None

            args = [*sierra_compile_bin, sierra_path, casm_path]
            process = _communicate(*args)
            self._cairo_process_output_format(process)

            if not casm_path.exists():
                raise CompileError(
                    f"CASM artifact not found at: {casm_path}. Please verify the build process."
                )

            else:
                logger.info(f"Generated CASM artifact: {target_casm_name}.")

                casm_artifact = casm_path.read_text()

            contract_type_instance = ContractType(
                abi=json.loads(sierra_artifact)["abi"],
                contractName=contract_name,  # source_id is
                sourceId=source_id,
                runtimeBytecode={"bytecode": to_hex(text=str(casm_artifact))},
                deploymentBytecode={"bytecode": to_hex(text=str(casm_artifact))},
            )

            contract_types.append(contract_type_instance)
        return contract_types

    def cairo_compile(
        self, contract_filepaths: Sequence[Path], base_path: Optional[Path] = None
    ) -> List[ContractType]:
        self._cairo_build_dir.mkdir(exist_ok=True)
        _bins = self._get_cairo_bins()
        self.load_cairo_dependencies()
        contract_types = []
        if len(contract_filepaths) == 1:
            logger.debug("Found a single contract file.")

            contract_types = self._cairo_compile_single_file(
                contract_filepaths,
                _bins,
                base_path,
            )
        else:
            logger.debug("Found multiple contract files.")
            if (
                self.package_manifest_path and not self.package_manifest_path.exists()
            ):  # path that toml file exist
                raise CompileError(
                    f"Package manifest file not found at: {self.package_manifest_path}."
                )
            contract_types = self._cairo_compile_multiple_files(
                contract_filepaths, _bins, base_path
            )

        return contract_types

    def _get_cairo_bins(self) -> Tuple[List[str], List[str]]:
        starknet_compile_bin = self._which(STARKNET_COMPILE)
        args = [*starknet_compile_bin, "--version"]
        logger.debug(args)
        result, err = _run(*args)
        output_text = result.decode("utf8")
        debug_text = err.decode("utf8")
        if err:  # starknet-compile and starknet-sierra-compile
            # and outputs some info as error even though it is not an error!
            if "error:" in debug_text.lower():
                raise CompileError(
                    f"Failed to retrieve the version of starknet-compile: {debug_text}"
                )

            else:
                logger.debug(debug_text)

        version_string = output_text.strip()
        logger.info(f"Using version: {version_string}")

        sierra_compile_bin = self._which(STARKNET_SIERRA_COMPILE)
        args = [*sierra_compile_bin, "--version"]
        result, err = _run(*args)
        output_text = result.decode("utf8")
        debug_text = err.decode("utf8")
        if err:
            if "error:" in debug_text.lower():
                raise CompileError(
                    f"Failed to retrieve the version of starknet-compile: {debug_text}"
                )
            else:
                logger.debug(debug_text)

        version_string = output_text.strip()
        logger.info(f"Using version: {version_string}")
        return starknet_compile_bin, sierra_compile_bin

    def _which(self, bin_name: str) -> List[str]:
        if self.cairo_manifest_path is not None:
            return [
                "cargo",
                "run",
                "--bin",
                bin_name,
                "--manifest-path",
                self.cairo_manifest_path.as_posix(),
                "--",
            ]

        _bin = shutil.which(bin_name)
        if not _bin:
            raise CompilerError(
                f"`{STARKNET_COMPILE}` binary required in $PATH prior to compiling."
            )

        return [_bin]

    def _get_scarb_bin(self) -> str:
        scarb_bin = shutil.which(STARKNET_SCARB)
        if scarb_bin is not None:
            args = [scarb_bin, "--json", "--version"]
            result, err = _run(*args)
            output_text = result.decode("utf8")
            err_text = err.decode("utf8")
            if err:
                raise CompileError(f"The Scarb command is not executable: {err_text}")

            else:
                version_string = output_text.strip().replace("\n", ", ")
                logger.info(f"Using following versions: {version_string}")
        else:
            raise CompileError(
                "Scarb is not found. \
                Please install Scarb from https://github.com/software-mansion/scarb"
            )

        return scarb_bin

    def _read_manifest(self):
        if not self.scarb_manifest_path:
            raise CompileError("Scarb manifest file is not found in the current directory.")

        with open(self.scarb_manifest_path, "rb") as f:
            toml_dict = tomli.load(f)
        return toml_dict

    def _check_starknet_target(self, manifest: Dict) -> Dict:
        targets = {"starknet": False}

        if not manifest.get("target", None):
            logger.warning(
                "No target found in the Scarb manifest file. \
                    The package will not be built as Starknet contracts. \
                        If you intend to build for Starknet, \
                            please add [[target.starknet-contract]] to the Scarb manifest file."
            )

            return targets

        if not manifest["target"].get("starknet-contract", None):
            logger.warning(
                "starknet-contract target not found in the Scarb manifest file. \
                    Therefore, the package will not be built as Starknet contracts. \
                        If you intend to build for Starknet, \
                            please add [[target.starknet-contract]] to the Scarb manifest file."
            )

            return targets
        else:
            targets["starknet"] = True
        return targets

    def _scarb_output_format(self, process: subprocess.Popen) -> None:
        try:
            while True:
                output_line = process.stdout.readline().strip() if process.stdout else ""
                if output_line:
                    output_json = json.loads(output_line.strip())

                    if output_json.get("type") == "error":
                        logger.error(output_json.get("message", "Unknown error occurred."))
                        raise CompilerError("Failed to compile contracts.")

                    elif output_json.get("type") == "info":
                        logger.info(output_json.get("message", "Unknown info message."))

                    elif output_json.get("type") == "warning":
                        logger.warning(output_json.get("message", "Unknown warning message."))

                    else:
                        logger.debug(output_json.get("message", "Unknown message."))

                    # Handling specific status messages
                    if output_json.get("status"):
                        message = output_json.get("message", "Unknown error occurred.")
                        logger.debug(f"{output_json.get('status')}: {message}")

                error_line = process.stderr.readline().strip() if process.stderr else ""
                if error_line:
                    raise CompilerError("Failed to compile contracts.")

                # End of process
                if output_line == "" and error_line == "" and process.poll() is not None:
                    break

        finally:
            # Ensure no output is lost if an exception is raised
            _ = process.communicate()

    def load_scarb_dependencies(self, scarb_bin: str, manifest, base_path: Optional[Path] = None):
        ape_deps = self.project_manager.dependencies
        logger.warning("Using only Scarb to manage dependencies is highly recommended.")
        if ape_deps and ape_deps:
            for dep_name, dep_dict in ape_deps.items():
                args = [scarb_bin, "--json", "--manifest-path", self.scarb_manifest_path, "add"]
                if len(dep_dict) > 1:
                    raise CompilerError(f"Multiple versions found for dependency '{dep_name}'.")

                dep = list(dep_dict.values())[0]
                version = dep.version_id
                if isinstance(dep, GithubDependency):
                    logger.info("Github dependency found.")
                    github = dep.github
                    url = f"https://github.com/{github.strip('/')}"
                    args.extend([dep_name, "--git", url])
                    if version:
                        args.extend(["--rev", version])
                    process = _communicate(*args)
                    self._scarb_output_format(process)

                elif isinstance(dep, LocalDependency):
                    local_path = dep.local
                    args.extend([dep_name, "--path", local_path])
                    process = _communicate(*args)
                    self._scarb_output_format(process)

                elif isinstance(dep, NpmDependency):
                    logger.warning(
                        f"Scarb does not support NPM dependencies yet \
                            so {dep_name} will be ignored."
                    )
                    continue

    def load_cairo_dependencies(self, base_path: Optional[Path] = None):
        deps = self.project_manager.dependencies
        if deps:
            logger.warning(
                "Since this project is not using Scarb, \
                    dependency management is not supported through Ape."
            )
        return

    def _scarb_compile(
        self, contract_filepaths: Sequence[Path], base_path: Optional[Path] = None
    ) -> List[ContractType]:
        scarb_bin = self._get_scarb_bin()
        manifest = self._read_manifest()
        self.load_scarb_dependencies(scarb_bin, manifest, base_path)
        targets = self._check_starknet_target(manifest)
        profile = "dev"

        args = [
            scarb_bin,
            "--json",
            "--manifest-path",
            self.scarb_manifest_path,
            "--target-dir",
            TARGET_DIR,
            "build",
        ]
        process = _communicate(*args)
        self._scarb_output_format(process)

        scarb_artifacts_dir = self._scarb_build_dir / profile

        if not scarb_artifacts_dir.exists():
            raise CompilerError(
                f"Scarb build directory not found at: {scarb_artifacts_dir}. \
                    Please verify the build process."
            )

        contracts = []
        if targets["starknet"]:
            for file_path in scarb_artifacts_dir.glob("*.starknet_artifacts.json"):
                # Check if it's a file and not a directory
                if not file_path.is_file():
                    continue

                starknet_artifact = json.loads(file_path.read_text())

                for contract in starknet_artifact["contracts"]:
                    package_name = contract["package_name"]
                    package_id = contract["id"]
                    contract_name = contract["contract_name"]

                    artifacts = contract.get("artifacts", None)
                    if not artifacts:
                        logger.warning(f"Artifacts not found in the Starknet contract: {contract}.")

                        continue

                    all_artifacts_null = all(value is None for value in artifacts.values())
                    if all_artifacts_null:
                        logger.warning(
                            f"Both Sierra and CASM Starknet contract targets have been disabled. \
                                Scarb will not produce anything for package {package_name}."
                        )

                        continue

                    casm_artifact = None
                    sierra_artifact = (
                        None  # but we can assume that sierra is always present in the artifact
                    )
                    if artifacts.get("casm", None):
                        casm_path = scarb_artifacts_dir / artifacts["casm"]
                        if not casm_path.exists():
                            raise CompileError(
                                f"CASM artifact not found: {casm_path}. Check the build process."
                            )
                        casm_artifact = casm_path.read_text()
                    else:
                        logger.warning(
                            f"To enable the production of the CASM artifact for {contract_name}, \
                                please add 'casm=true' under [[target.starknet-contract.casm]] \
                                    in the Scarb manifest file, as it is currently disabled."
                        )

                    if artifacts.get("sierra", None):
                        # Sierra is always generated if the starknet target is present
                        sierra_path = scarb_artifacts_dir / artifacts["sierra"]
                        if not sierra_path.exists():
                            raise CompileError(
                                f"Sierra artifact not found: {sierra_path}. \
                                    Check the build process."
                            )
                        sierra_artifact = sierra_path.read_text()

                    if casm_artifact and sierra_artifact is not None:
                        contract_type_instance = ContractType(
                            abi=json.loads(sierra_artifact)["abi"],
                            contractName=contract_name,
                            sourceId=package_id,
                            runtimeBytecode={"bytecode": to_hex(text=str(casm_artifact))},
                            deploymentBytecode={"bytecode": to_hex(text=str(casm_artifact))},
                        )
                    else:
                        if sierra_artifact is None:
                            raise CompileError("Sierra artifact is None. Check the build process.")

                        contract_type_instance = ContractType(
                            abi=json.loads(sierra_artifact)["abi"],
                            contractName=contract_name,
                            sourceId=package_id,
                            runtimeBytecode={"bytecode": to_hex(text=str(sierra_artifact))},
                        )

                    contracts.append(contract_type_instance)
        else:
            logger.warning(
                "Since starknet-contract target is not found in the Scarb manifest file, \
                    no Starknet contract will be compiled."
            )

        logger.debug(f"Contracts: {contracts}")
        return contracts

    def compile(
        self, contract_filepaths: Sequence[Path], base_path: Optional[Path]
    ) -> List[ContractType]:
        logger.debug(f"Cache path: {self.project_manager.local_project._cache_folder}")
        logger.debug(f"Project path: {self.project_manager.local_project.path}")
        logger.debug(f"Base path: {base_path}")

        if self.scarb_manifest_path and self.scarb_manifest_path.name == "Scarb.toml":
            if Path.exists(self.scarb_manifest_path):
                logger.debug(
                    f"Using Scarb to compile contracts \
                        based on the manifest file: {self.scarb_manifest_path}."
                )

                contracts = self._scarb_compile(contract_filepaths, base_path)
                return contracts
            else:
                logger.debug(
                    f"Scarb manifest file is not found \
                        at the specified path: {self.scarb_manifest_path}. \
                            Falling back to starknet-compile."
                )

                contracts = self.cairo_compile(contract_filepaths, base_path)
                return contracts
        else:
            logger.debug("Using starknet-compile.")
            contracts = self.cairo_compile(contract_filepaths, base_path)
            if contracts:
                logger.info(f"Check out the {TARGET_DIR} directory for the compiled artifacts.")
            return contracts
