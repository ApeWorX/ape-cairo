import json
import re
import shutil
import subprocess
from collections.abc import Iterable, Iterator
from distutils.errors import CompileError
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import toml
import tomli
from ape.api.compiler import CompilerAPI
from ape.api.config import PluginConfig
from ape.exceptions import CompilerError
from ape.logging import logger
from ape.managers.project import ProjectManager
from ape.utils.misc import cached_property
from ape.utils.os import get_relative_path
from ape.version import version
from eth_utils import to_hex
from ethpm_types import ContractType
from semantic_version import Version  # type: ignore

TARGET_DIR = ".build/target"
STARKNET_SCARB = "scarb"


class CairoConfig(PluginConfig):
    pass


class CairoCompiler(CompilerAPI):
    _scarb_bin: str = None
    _versions: dict = {}

    @property
    def name(self) -> str:
        return "cairo"

    def _run_scarb_command(self, *args) -> Tuple[bytes, bytes]:
        popen = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return popen.communicate()

    @property
    def scarb_bin(self) -> str:
        if self._scarb_bin is None:
            scarb_bin = shutil.which(STARKNET_SCARB)
            if not scarb_bin:
                raise CompileError(
                    "Scarb binary is not found. \
                    Please ensure that Scarb is installed and available in your PATH."
                )
            else:
                self._scarb_bin = scarb_bin
                args = [self.scarb_bin, "--json", "--version"]
                stdout, stderr = self._run_scarb_command(*args)
                if stderr:
                    raise CompileError(f"The Scarb command is not executable: {stderr}")

                versions = {}

                # Parse Scarb version
                scarb_match = re.search(r"scarb (\S+)", stdout)
                versions["scarb"] = scarb_match.group(1) if scarb_match else None

                # Parse Cairo version
                cairo_match = re.search(r"cairo: (\S+)", stdout)
                versions["cairo"] = cairo_match.group(1) if cairo_match else None

                # Parse Sierra version
                sierra_match = re.search(r"sierra: (\S+)", stdout)
                versions["sierra"] = sierra_match.group(1) if sierra_match else None

                self._versions = versions

        return self._scarb_bin

    @property
    def scarb_bin_version(self):
        return self._versions["scarb"]

    @property
    def scarb_cairo_version(self):
        return self._versions["cairo"]

    @property
    def scarb_sierra_version(self):
        return self._versions["sierra"]

    def get_versions(self, all_paths: Iterable[Path]) -> set[str]:  # type: ignore[empty-body]
        """
        Retrieve the set of available compiler versions for this plugin to compile ``all_paths``.

        Args:
            all_paths (Iterable[pathlib.Path]): The list of paths.

        Returns:
            set[str]: A set of available compiler versions.
        """

        return {self.scarb_cairo_version}

    def get_compiler_settings(  # type: ignore[empty-body]
        self,
        contract_filepaths: Iterable[Path],
        project: Optional["ProjectManager"] = None,
        **overrides,
    ) -> dict[Version, dict]:
        """
        Get a mapping of the settings that would be used to compile each of the sources
        by the compiler version number.

        Args:
            contract_filepaths (Iterable[pathlib.Path]): The list of paths.
            project (Optional[:class:`~ape.managers.project.ProjectManager`]): Optionally provide
              the project containing the base paths and full source set. Defaults to the local
              project. Dependencies will change this value to their respective projects.
            **overrides: Settings overrides.

        Returns:
            dict[Version, dict]: A dict of compiler settings by compiler version.
        """
        return {}

    @cached_property
    def _ape_version(self) -> Version:
        return Version(version.split(".dev")[0].strip())

    def _scarb_output_format(self, process: subprocess.Popen) -> None:
        message_types: Dict[str, Callable] = {
            "error": logger.error,
            "info": logger.info,
            "diagnostic": logger.debug,
            "warn": logger.warning,
        }
        status_message_types: Dict[str, Callable] = {
            "compiling": logger.info,
            "checking": logger.info,
            "finished": logger.info,
        }

        def process_json_output(output: Dict[str, any]) -> None:
            type_mes = output.get("type")
            status_mes = output.get("status")
            message = output.get("message", "No message provided")

            if status_mes:
                status_message_types.get(status_mes, logger.info)(
                    f"{status_mes.upper()}: {message}"
                )

            if type_mes:
                message_types.get(type_mes, logger.debug)(message)

            for key, value in output.items():
                if key not in ["type", "message", "status"]:
                    logger.debug(f"{key}: {value}")

        def read_stream(stream) -> str:
            return stream.readline().strip() if stream else ""

        try:
            while True:
                output_line = read_stream(process.stdout)
                error_line = read_stream(process.stderr)

                if output_line:
                    try:
                        output_json = json.loads(output_line)
                        process_json_output(output_json)
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse JSON: {output_line}")

                if error_line:
                    raise CompilerError(f"Failed to compile contracts: {error_line}")

                if not output_line and not error_line and process.poll() is not None:
                    break

        finally:
            process.communicate()

    def _scarb_communicate(self, *args) -> subprocess.Popen:
        popen = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
        )
        return popen

    def _read_scarb_manifest(self, scarb_manifest_path: Path) -> Dict:
        with open(scarb_manifest_path, "rb") as f:
            toml_data = tomli.load(f)
        return toml_data

    def _scarb_compile(
        self,
        contract_filepaths: Iterable[Path],
        project: Optional[ProjectManager] = None,
        settings: Optional[dict] = None,
        scarb_manifest_path: Optional[dict] = None,
    ):
        pm = project or self.local_project
        profile = "dev"
        logger.info(f"Compiling contracts for project: {pm.path}")

        with open(scarb_manifest_path, "r") as f:
            manifest = toml.load(f)

        if "target" not in manifest:
            manifest["target"] = {}

        if "starknet-contract" not in manifest["target"]:
            logger.warning("[[target.starknet-contract]] not found, adding it automatically.")
            manifest["target"]["starknet-contract"] = [{}]

        starknet_contract = manifest["target"]["starknet-contract"][0]

        # Check and update options
        options_to_check = {"casm": True, "sierra": True, "casm-add-pythonic-hints": True}

        for option, default_value in options_to_check.items():
            if option not in starknet_contract or not starknet_contract[option]:
                logger.warning(f"{option} is disabled. Enabling automatically.")
                starknet_contract[option] = default_value

        # Write updated manifest back to file
        with open(scarb_manifest_path, "w") as f:
            toml.dump(manifest, f)

        args = [
            self.scarb_bin,
            "--json",
            "--profile",
            profile,
            "--manifest-path",
            scarb_manifest_path,
            "--target-dir",
            Path(f"{pm.path}/{TARGET_DIR}"),
            "build",
        ]
        self._scarb_output_format(self._scarb_communicate(*args))
        scarb_artifacts_dir = Path(f"{pm.path}/{TARGET_DIR}/{profile}")

        if not scarb_artifacts_dir.exists():
            raise CompilerError(
                f"Scarb build directory not found at: {scarb_artifacts_dir}. \
                    Please verify the build process."
            )

        contracts = []
        for file_path in scarb_artifacts_dir.glob("*.starknet_artifacts.json"):
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

                sierra_and_casm_artifacts = all(value is None for value in artifacts.values())
                if sierra_and_casm_artifacts:
                    logger.warning(
                        "Both Sierra and CASM Starknet contract targets have been disabled. "
                        + f"Scarb is not produced anything for package {package_name}."
                    )
                    continue

                casm_artifact = None
                sierra_artifact = None
                if artifacts.get("casm", None):
                    casm_path = Path(scarb_artifacts_dir / artifacts["casm"])
                    if not casm_path.exists():
                        raise CompileError(
                            f"CASM is enabled but artifact is not found: {casm_path}. Check the build process."
                        )
                    casm_text = casm_path.read_text()
                    casm_artifact = json.loads(casm_text)

                if artifacts.get("sierra", None):
                    sierra_path = Path(scarb_artifacts_dir / artifacts["sierra"])
                    if not sierra_path.exists():
                        raise CompileError(
                            f"Sierra is enabled but artifact is not found: {sierra_path}. \
                                Check the build process."
                        )
                    sierra_text = sierra_path.read_text()
                    sierra_artifact = json.loads(sierra_text)

                runtime_bytecode = {"bytecode": to_hex(text=str(casm_text))}
                deployment_bytecode = {"bytecode": to_hex(text=str(sierra_text))}
                contract_type_instance = ContractType(
                    abi=sierra_artifact["abi"] if sierra_artifact else None,
                    contractName=contract_name,
                    sourceId=package_id,
                    deploymentBytecode=deployment_bytecode,
                    runtimeBytecode=runtime_bytecode,
                )
                contracts.append(contract_type_instance)
        logger.info(f"Compiled {len(contracts)} contracts.")
        logger.info(f"contracts: {contracts}")
        return contracts

    def _compile(
        self,
        contract_filepaths: Iterable[Path],
        project: Optional[ProjectManager] = None,
        settings: Optional[dict] = None,
    ):
        pm = project or self.local_project
        scarb_manifest_path = Path(f"{pm.path}/Scarb.toml")

        if not Path.exists(scarb_manifest_path):
            pass

        return self._scarb_compile(contract_filepaths, pm, settings, scarb_manifest_path)

    def compile(
        self,
        contract_filepaths: Iterable[Path],
        project: Optional["ProjectManager"],
        settings: Optional[dict] = None,
    ) -> Iterator[ContractType]:
        """
        Compile the given source files. All compiler plugins must implement this function.

        Args:
            contract_filepaths (Iterable[pathlib.Path]): A list of source file paths to compile.
            project (Optional[:class:`~ape.managers.project.ProjectManager`]): Optionally provide
              the project containing the base paths and full source set. Defaults to the local
              project. Dependencies will change this value to their respective projects.
            settings (Optional[dict]): Adhoc compiler settings.

        Returns:
            list[:class:`~ape.type.contract.ContractType`]
        """
        pm = project or self.local_project

        # (0.4.0): If compiling a project outside the cwd (such as a dependency),
        # we are forced to use absolute paths.
        use_absolute_paths = pm.path != Path.cwd()

        self.compiler_settings = {**self.compiler_settings, **(settings or {})}
        contract_types: list[ContractType] = []
        config = self.get_config(pm)
        paths = [p for p in contract_filepaths]  # Handles generator.
        source_ids = [f"{get_relative_path(p.absolute(), pm.path)}" for p in paths]

        filepaths = [pm.path / src_id for src_id in source_ids]
        contract_types = self._compile(filepaths, project=pm, settings=settings)
        compilers = pm.manifest.compilers

        pm.update_manifest(compilers=compilers)
        return contract_types
