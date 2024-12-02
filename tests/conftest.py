import shutil
from pathlib import Path
from tempfile import mkdtemp

import ape
import pytest

# NOTE: Ensure that we don't use local paths for these
ape.config.DATA_FOLDER = Path(mkdtemp()).resolve()
ape.config.PROJECT_FOLDER = Path(mkdtemp()).resolve()

PROJECTS_DIRECTORY = Path(__file__).parent / "projects"
PROJECT_DIRECTORIES = [d for d in PROJECTS_DIRECTORY.iterdir() if d.is_dir()]


@pytest.fixture(params=PROJECT_DIRECTORIES, scope="module")
def project_directory(request):
    return request.param


@pytest.fixture(scope="module")
def config():
    return ape.config


@pytest.fixture(scope="module")
def project(config, project_directory):
    caches = [
        project_directory / ".build",
        project_directory / ".cache",
        project_directory / "Scarb.lock",
        project_directory / "contracts" / ".cache",
        project_directory / "src" / ".cache",
    ]
    for cache in caches:
        if cache.exists() and cache.is_dir():
            shutil.rmtree(cache)

    # Instead of config.using_project(), use ape.Project
    project = ape.Project(project_directory)
    yield project

    # Clean up
    if project.path / "_cache" and (project.path / "_cache").is_dir():
        shutil.rmtree(project.path / "_cache")


@pytest.fixture(scope="module")
def compiler():
    return ape.compilers.registered_compilers[".cairo"]
