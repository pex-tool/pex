#!/usr/bin/env python3

import subprocess
import sys
from pathlib import Path

import httpx

VIRTUALENV_16_7_12_RELEASE_SHA = "fdfec65ff031997503fb409f365ee3aeb4c2c89f"


def find_repo_root() -> Path:
    return Path(
        subprocess.run(
            args=["git", "rev-parse", "--show-toplevel"],
            text=True,
            stdout=subprocess.PIPE,
            check=True,
        ).stdout.strip()
    )


def main() -> None:
    out_path = find_repo_root() / "pex/venv/virtualenv_16.7.12_py"
    with httpx.stream(
        "GET",
        f"https://raw.githubusercontent.com/pypa/virtualenv/"
        f"{VIRTUALENV_16_7_12_RELEASE_SHA}/virtualenv.py",
    ) as response, out_path.open("wb") as out_fp:
        for chunk in response.iter_bytes():
            out_fp.write(chunk)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
