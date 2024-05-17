import subprocess
from enum import Enum
from typing import Tuple


class Extension(Enum):
    CAIRO = ".cairo"


def _run(*args) -> Tuple[bytes, bytes]:
    popen = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return popen.communicate()


def _communicate(*args) -> subprocess.Popen:
    popen = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,  # Line buffered
    )
    return popen
