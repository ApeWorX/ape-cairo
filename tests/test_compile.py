def test_compile_projects(compiler, project):
    source_files = [f for f in project.contracts_folder.iterdir() if f.is_file()]
    try:
        # Pass project instead of base_path
        compiler.compile(contract_filepaths=source_files, project=project)
        assert True, "Compilation succeeded."
    except Exception as e:
        assert False, f"Compilation failed: {e}"
