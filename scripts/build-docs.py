#!/usr/bin/env python3

from __future__ import annotations

import argparse
import atexit
import os.path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from enum import Enum
from pathlib import Path, PurePath
from typing import Iterable, Optional
from urllib.parse import unquote, urlparse

import httpx

PEX_DEV_DIR = Path("~/.pex_dev").expanduser()

PAGEFIND_NAME = "pagefind"
PAGEFIND_VERSION = "1.0.4"


class Platform(Enum):
    Linux_aarch64 = "aarch64-unknown-linux-musl"
    Linux_x86_64 = "x86_64-unknown-linux-musl"
    Macos_aarch64 = "aarch64-apple-darwin"
    Macos_x86_64 = "x86_64-apple-darwin"
    Windows_x86_64 = "x86_64-pc-windows-msvc"

    @classmethod
    def parse(cls, value: str) -> Platform:
        return Platform.current() if "current" == value else Platform(value)

    @classmethod
    def current(cls) -> Platform:
        system = platform.system().lower()
        machine = platform.machine().lower()
        if system == "linux":
            if machine in ("aarch64", "arm64"):
                return cls.Linux_aarch64
            elif machine in ("amd64", "x86_64"):
                return cls.Linux_x86_64
        elif system == "darwin":
            if machine in ("aarch64", "arm64"):
                return cls.Macos_aarch64
            elif machine in ("amd64", "x86_64"):
                return cls.Macos_x86_64
        elif system == "windows" and machine in ("amd64", "x86_64"):
            return cls.Windows_x86_64

        raise ValueError(
            "The current operating system / machine pair is not supported for building docs!: "
            f"{system} / {machine}"
        )

    @property
    def extension(self):
        return ".exe" if self is self.Windows_x86_64 else ""

    def binary_name(self, binary_name: str) -> str:
        return f"{binary_name}{self.extension}"


CURRENT_PLATFORM = Platform.current()


def target_triple() -> str:
    return CURRENT_PLATFORM.value


def pagefind_executable() -> str:
    return CURRENT_PLATFORM.binary_name(
        binary_name="{name}-{version}".format(name=PAGEFIND_NAME, version=PAGEFIND_VERSION)
    )


def ensure_pagefind() -> PurePath:
    pagefind_exe = pagefind_executable()
    pagefind_exe_path = PEX_DEV_DIR / pagefind_exe
    if pagefind_exe_path.is_file() and os.access(pagefind_exe_path, os.R_OK | os.X_OK):
        return pagefind_exe_path

    tmp_dir = PEX_DEV_DIR / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    download_dir = Path(tempfile.mktemp(prefix="download-pagefind.", dir=tmp_dir))
    atexit.register(shutil.rmtree, str(download_dir), ignore_errors=True)

    tarball_url = (
        f"https://github.com/CloudCannon/pagefind/releases/download/v{PAGEFIND_VERSION}/"
        f"{PAGEFIND_NAME}-v{PAGEFIND_VERSION}-{target_triple()}.tar.gz"
    )
    out_path = download_dir / PurePath(unquote(urlparse(tarball_url).path)).name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", tarball_url, follow_redirects=True) as response, out_path.open(
        "wb"
    ) as out_fp:
        for chunk in response.iter_bytes():
            out_fp.write(chunk)
    with tarfile.open(out_path) as tf:
        tf.extract(PAGEFIND_NAME, path=str(download_dir))
    (download_dir / PAGEFIND_NAME).rename(pagefind_exe_path)

    return pagefind_exe_path


def execute_pagefind(args: Iterable[str]) -> None:
    subprocess.run(args=[str(ensure_pagefind()), *args], check=True)


def execute_sphinx_build(out_base_dir: Path, builder: str, out_dir: Optional[str] = None) -> Path:
    gen_dir = (out_base_dir / (out_dir or builder)).absolute()
    shutil.rmtree(gen_dir, ignore_errors=True)
    subprocess.run(
        args=[sys.executable, "-m", "sphinx", "-b", builder, "-aEW", "docs", str(gen_dir)],
        check=True,
    )
    return gen_dir


def main(
    out_dir: Path,
    linkcheck: bool = False,
    pdf: bool = False,
    html: bool = True,
    clean_html: bool = False,
    serve: bool = False,
) -> None:
    static_dynamic_dir = (Path("docs") / "_static_dynamic").absolute()

    def clean_static_dynmaic_dir() -> None:
        shutil.rmtree(static_dynamic_dir, ignore_errors=True)

    clean_static_dynmaic_dir()
    static_dynamic_dir.mkdir(parents=True, exist_ok=True)
    atexit.register(clean_static_dynmaic_dir)

    if linkcheck:
        execute_sphinx_build(out_dir, "linkcheck")

    if pdf:
        pdf_dir = execute_sphinx_build(out_dir, "simplepdf", out_dir="pdf")
        (static_dynamic_dir / "pex.pdf").symlink_to(pdf_dir / "pex.pdf")

    if html:
        html_dir = execute_sphinx_build(out_dir, "html")
        if clean_html:
            shutil.rmtree(html_dir / ".doctrees", ignore_errors=True)
            (html_dir / ".buildinfo").unlink(missing_ok=True)
            (html_dir / "objects.inv").unlink(missing_ok=True)

        page_find_args = ["--site", str(html_dir), "--output-subdir", "_pagefind"]
        if serve:
            page_find_args.append("--serve")
        execute_pagefind(page_find_args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--linkcheck", action="store_true")
    parser.add_argument("--pdf", action="store_true")
    parser.add_argument("--no-html", action="store_true")
    parser.add_argument("--clean-html", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("out_dir", type=Path, default=Path("dist") / "docs", nargs="?")
    options = parser.parse_args()
    try:
        main(
            out_dir=options.out_dir,
            linkcheck=options.linkcheck,
            pdf=options.pdf,
            html=not options.no_html,
            clean_html=options.clean_html,
            serve=options.serve,
        )
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
