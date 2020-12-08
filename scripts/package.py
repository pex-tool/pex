#!/usr/bin/env python3

import hashlib
import io
import os
import subprocess
import sys
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser
from enum import Enum, unique
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path, PurePath
from typing import Tuple

import pytoml as toml

PROJECT_METADATA = Path("pyproject.toml")
DIST_DIR = Path("dist")


def python_requires() -> str:
    project_metadata = toml.loads(PROJECT_METADATA.read_text())
    return project_metadata["tool"]["flit"]["metadata"]["requires-python"].strip()


def build_pex_pex(output_file: PurePath, local: bool = False, verbosity: int = 0) -> None:
    # NB: We do not include the subprocess extra (which would be spelled: `.[subprocess]`) since we
    # would then produce a pex that would not be consumable by all python interpreters otherwise
    # meeting `python_requires`; ie: we'd need to then come up with a deploy environment / deploy
    # tooling, that built subprocess32 for linux cp27m, cp27mu, pypy, ... etc. Even with all the work
    # expended to do this, we'd still miss some platform someone wanted to run the Pex PEX on. As
    # such, we just ship unadorned Pex which is pure-python and universal. Any user wanting the extra
    # is encouraged to build a Pex PEX for their particular platform themselves.
    pex_requirement = "."

    args = [
        sys.executable,
        "-m",
        "pex",
        *["-v" for _ in range(verbosity)],
        "--disable-cache",
        "--no-build",
        "--no-compile",
        "--no-use-system-time",
        "--python-shebang",
        "/usr/bin/env python",
        "--no-strip-pex-env",
        "--unzip",
        "--include-tools",
        "-o",
        str(output_file),
        "-c",
        "pex",
        pex_requirement,
    ]
    if not local:
        args.extend(["--interpreter-constraint", python_requires()])
    subprocess.run(args, check=True)


def describe_git_rev() -> str:
    git_describe = subprocess.run(
        ["git", "describe"], check=True, capture_output=True, encoding="utf-8"
    )
    return git_describe.stdout.strip()


def describe_file(path: Path) -> Tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(io.DEFAULT_BUFFER_SIZE), b""):
            hasher.update(chunk)
            size += len(chunk)

    return hasher.hexdigest(), size


@unique
class Format(str, Enum):
    SDIST = "sdist"
    WHEEL = "wheel"

    __repr__ = __str__ = lambda self: self.value


def build_pex_dists(dist_fmt: Format, *additional_dist_fmts: Format, verbose: bool = False) -> None:
    output = None if verbose else subprocess.DEVNULL
    subprocess.run(
        ["flit", "build", *[f"--format={fmt}" for fmt in [dist_fmt, *additional_dist_fmts]]],
        stdout=output,
        stderr=output,
    )


def main(
    *additional_dist_formats: Format, verbosity: int = 0, local: bool = False, serve: bool = False
) -> None:
    pex_output_file = DIST_DIR / "pex"
    print(f"Building Pex PEX to `{pex_output_file}` ...")
    build_pex_pex(pex_output_file, local, verbosity)

    git_rev = describe_git_rev()
    sha256, size = describe_file(pex_output_file)
    print(f"Built Pex PEX @ {git_rev}:")
    print(f"sha256: {sha256}")
    print(f"  size: {size}")

    if additional_dist_formats:
        print(
            f"Building additional distribution formats to `{DIST_DIR}`: "
            f'{", ".join(f"{i + 1}.) {fmt}" for i, fmt in enumerate(additional_dist_formats))} ...'
        )
        build_pex_dists(*additional_dist_formats, verbose=verbosity > 0)
        print("Built:")
        for root, _, files in os.walk(DIST_DIR):
            root_path = Path(root)
            for f in files:
                dist_path = root_path / f
                if dist_path != pex_output_file:
                    print(f"  {dist_path}")

    if serve:
        server = HTTPServer(("", 0), SimpleHTTPRequestHandler)
        host, port = server.server_address

        print(f"Serving Pex distributions from `{DIST_DIR}` at http://{host}:{port} ...")

        os.chdir(DIST_DIR)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print(f"Server shut down in response to keyboard interrupt.")


if __name__ == "__main__":
    if not PROJECT_METADATA.is_file():
        print("This script must be run from the root of the Pex repo.", file=sys.stderr)
        sys.exit(1)

    parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        "-v", dest="verbosity", action="count", default=0, help="Increase output verbosity level."
    )
    parser.add_argument(
        "--additional-format",
        dest="additional_formats",
        choices=list(Format),
        type=Format,
        action="append",
        help="Package Pex in additional formats.",
    )
    parser.add_argument(
        "--local",
        default=False,
        action="store_true",
        help="Build Pex PEX with just a single local interpreter.",
    )
    parser.add_argument(
        "--serve",
        default=False,
        action="store_true",
        help="After packaging Pex serve up the packages over HTTP.",
    )
    args = parser.parse_args()

    main(
        *(args.additional_formats or ()),
        verbosity=args.verbosity,
        local=args.local,
        serve=args.serve
    )
