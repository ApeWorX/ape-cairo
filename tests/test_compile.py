from pathlib import Path
import pytest
from ape.exceptions import CompilerError


def test_compile_projects(compiler, project):
    source_files = [f for f in project.contracts_folder.iterdir() if f.is_file()]
    try:
        compiler.compile(contract_filepaths=source_files, base_path=project.contracts_folder)
        assert True, "Compilation succeeded."
    except Exception as e:
        assert False, f"Compilation failed: {e}"
