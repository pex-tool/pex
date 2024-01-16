#!/usr/bin/env python3

import hashlib
import io
import os
import subprocess
import sys
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser
from email.parser import Parser
from enum import Enum, unique
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path, PurePath
from typing import Optional, Tuple, cast

DIST_DIR = Path("dist")


def build_pex_pex(output_file: PurePath, verbosity: int = 0) -> None:
    # NB: We do not include the subprocess extra (which would be spelled: `.[subprocess]`) since we
    # would then produce a pex that would not be consumable by all python interpreters otherwise
    # meeting `python_requires`; ie: we'd need to then come up with a deploy environment / deploy
    # tooling, that built subprocess32 for linux cp27m, cp27mu, pypy, ... etc. Even with all the
    # work expended to do this, we'd still miss some platform someone wanted to run the Pex PEX on.
    # As such, we just ship unadorned Pex which is pure-python and universal. Any user wanting the
    # extra is encouraged to build a Pex PEX for their particular platform themselves.
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
        "--include-tools",
        "-o",
        str(output_file),
        "-c",
        "pex",
        pex_requirement,
    ]
    subprocess.run(args, check=True)


def describe_rev() -> str:
    if not os.path.isdir(".git") and os.path.isfile("PKG-INFO"):
        # We're being build from an unpacked sdist.
        with open("PKG-INFO") as fp:
            return Parser().parse(fp).get("Version", "Unknown Version")

    git_describe = subprocess.run(
        ["git", "describe"], check=True, stdout=subprocess.PIPE, encoding="utf-8"
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
class Format(Enum):
    SDIST = "sdist"
    WHEEL = "wheel"

    def __str__(self) -> str:
        return cast(str, self.value)

    def build_arg(self) -> str:
        return f"--{self.value}"


def build_pex_dists(dist_fmt: Format, *additional_dist_fmts: Format, verbose: bool = False) -> None:
    output = None if verbose else subprocess.DEVNULL
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--outdir",
            str(DIST_DIR),
            *[fmt.build_arg() for fmt in [dist_fmt, *additional_dist_fmts]],
        ],
        stdout=output,
        stderr=output,
        check=True,
    )


def main(
    *additional_dist_formats: Format,
    verbosity: int = 0,
    pex_output_file: Optional[Path] = DIST_DIR / "pex",
    serve: bool = False
) -> None:
    if pex_output_file:
        print(f"Building Pex PEX to `{pex_output_file}` ...")
        build_pex_pex(pex_output_file, verbosity)

        rev = describe_rev()
        sha256, size = describe_file(pex_output_file)
        print(f"Built Pex PEX @ {rev}:")
        print(f"sha256: {sha256}")
        print(f"  size: {size}")

    if additional_dist_formats:
        print(
            f"Building additional distribution formats to `{DIST_DIR}`: "
            f'{", ".join(f"{i + 1}.) {fmt}" for i, fmt in enumerate(additional_dist_formats))} ...'
        )
        build_pex_dists(
            additional_dist_formats[0], *additional_dist_formats[1:], verbose=verbosity > 0
        )
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
        "--no-pex",
        default=False,
        action="store_true",
        help="Do not build the Pex PEX.",
    )
    parser.add_argument(
        "--pex-output-file",
        default=DIST_DIR / "pex",
        type=Path,
        help="Build the Pex PEX at this path.",
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
        pex_output_file=None if args.no_pex else args.pex_output_file,
        serve=args.serve
    )
