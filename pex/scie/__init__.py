# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
from argparse import Namespace, _ActionsContainer

from pex.compatibility import urlparse
from pex.fetcher import URLFetcher
from pex.orderedset import OrderedSet
from pex.pep_440 import Version
from pex.scie import science
from pex.scie.model import (
    ScieConfiguration,
    ScieInfo,
    ScieOptions,
    SciePlatform,
    ScieStyle,
    ScieTarget,
)
from pex.scie.science import SCIENCE_RELEASES_URL, SCIENCE_REQUIREMENT
from pex.typing import TYPE_CHECKING, cast
from pex.variables import ENV, Variables

if TYPE_CHECKING:
    from typing import Iterator, Optional, Tuple, Union


__all__ = (
    "ScieConfiguration",
    "ScieInfo",
    "SciePlatform",
    "ScieStyle",
    "ScieTarget",
    "build",
    "extract_options",
    "register_options",
    "render_options",
)


def register_options(parser):
    # type: (_ActionsContainer) -> None

    parser.add_argument(
        "--scie",
        "--par",
        dest="scie_style",
        default=None,
        type=ScieStyle.for_value,
        choices=ScieStyle.values(),
        help=(
            "Create one or more native executable scies from your PEX that include a portable "
            "CPython interpreter along with your PEX making for a truly hermetic PEX that can run "
            "on machines with no Python installed at all. If your PEX has multiple targets, "
            "whether `--platform`s, `--complete-platform`s or local interpreters in any "
            "combination, then one PEX scie will be made for each platform, selecting the latest "
            "compatible portable CPython interpreter. Note that only CPython>=3.8 is supported. If "
            "you'd like to explicitly control the target platforms or the exact portable CPython "
            "selected, see `--scie-platform`, `--scie-pbs-release` and `--scie-python-version`. "
            "Specifying `--scie {lazy}` will fetch the portable CPython interpreter just in time "
            "on first boot of the PEX scie on a given machine if needed. The URL(s) to fetch the "
            "portable CPython interpreter from can be customized by exporting the "
            "PEX_BOOTSTRAP_URLS environment variable pointing to a json file with the format: "
            '`{{"ptex": {{<file name 1>: <url>, ...}}}}` where the file names should match those '
            "found via `SCIE=inspect <the PEX scie> | jq .ptex` with appropriate replacement URLs. "
            "Specifying `--scie {eager}` will embed the portable CPython interpreter in your PEX "
            "scie making for a larger file, but requiring no internet access to boot. If you have "
            "customization needs not addressed by the Pex `--scie*` options, consider using "
            "`science` to build your scies (which is what Pex uses behind the scenes); see: "
            "https://science.scie.app.".format(lazy=ScieStyle.LAZY, eager=ScieStyle.EAGER)
        ),
    )
    parser.add_argument(
        "--scie-platform",
        dest="scie_platforms",
        default=[],
        action="append",
        type=SciePlatform.for_value,
        choices=SciePlatform.values(),
        help=(
            "The platform to produce the native PEX scie executable for. Can be specified multiple "
            "times."
        ),
    )
    parser.add_argument(
        "--scie-pbs-release",
        dest="scie_pbs_release",
        default=None,
        type=str,
        help=(
            "The Python Standalone Builds release to use. Currently releases are dates of the form "
            "YYYYMMDD, e.g.: '20240713'. See their GitHub releases page at "
            "https://github.com/indygreg/python-build-standalone/releases to discover available "
            "releases. If left unspecified the latest release is used. N.B.: The latest lookup is "
            "cached for 5 days. To force a fresh lookup you can remove the cache at "
            "<USER CACHE DIR>/science/downloads."
        ),
    )
    parser.add_argument(
        "--scie-python-version",
        dest="scie_python_version",
        default=None,
        type=Version,
        help=(
            "The portable CPython version to select. Can be either in `<major>.<minor>` form; "
            "e.g.: '3.11', or else fully specified as `<major>.<minor>.<patch>`; e.g.: '3.11.3'. "
            "If you don't specify this option, Pex will do its best to guess appropriate portable "
            "CPython versions. N.B.: Python Standalone Builds does not provide all patch versions; "
            "so you should check their releases at "
            "https://github.com/indygreg/python-build-standalone/releases if you wish to pin down "
            "to the patch level."
        ),
    )
    parser.add_argument(
        "--scie-science-binary",
        dest="scie_science_binary",
        default=None,
        type=str,
        help=(
            "The file path of a `science` binary or a URL to use to fetch the `science` binary "
            "when there is no `science` on the PATH with a version matching {science_requirement}. "
            "Pex uses the official `science` releases at {science_releases_url} by default.".format(
                science_requirement=SCIENCE_REQUIREMENT, science_releases_url=SCIENCE_RELEASES_URL
            )
        ),
    )


def render_options(options):
    # type: (ScieOptions) -> str

    args = ["--scie", str(options.style)]
    for platform in options.platforms:
        args.append("--scie-platform")
        args.append(str(platform))
    if options.pbs_release:
        args.append("--scie-pbs-release")
        args.append(options.pbs_release)
    if options.python_version:
        args.append("--scie-python-version")
        args.append(".".join(map(str, options.python_version)))
    if options.science_binary_url:
        args.append("--scie-science-binary")
        args.append(options.science_binary_url)
    return " ".join(args)


def extract_options(options):
    # type: (Namespace) -> Optional[ScieOptions]

    if not options.scie_style:
        return None

    python_version = None  # type: Optional[Union[Tuple[int, int], Tuple[int, int, int]]]
    if options.scie_python_version:
        if (
            not options.scie_python_version.parsed_version.release
            or len(options.scie_python_version.parsed_version.release) < 2
        ):
            raise ValueError(
                "Invalid Python version: '{python_version}'.\n"
                "Must be in the form `<major>.<minor>` or `<major>.<minor>.<patch>`".format(
                    python_version=options.scie_python_version
                )
            )
        python_version = cast(
            "Union[Tuple[int, int], Tuple[int, int, int]]",
            options.scie_python_version.parsed_version.release,
        )
        if python_version < (3, 8):
            raise ValueError(
                "Invalid Python version: '{python_version}'.\n"
                "Scies are built using Python Standalone Builds which only supports Python >=3.8.\n"
                "To find supported Python versions, you can browse the releases here:\n"
                "  https://github.com/indygreg/python-build-standalone/releases".format(
                    python_version=options.scie_python_version
                )
            )

    science_binary_url = options.scie_science_binary
    if science_binary_url:
        url_info = urlparse.urlparse(options.scie_science_binary)
        if not url_info.scheme and url_info.path and os.path.isfile(url_info.path):
            science_binary_url = "file://{path}".format(path=os.path.abspath(url_info.path))

    return ScieOptions(
        style=options.scie_style,
        platforms=tuple(OrderedSet(options.scie_platforms)),
        pbs_release=options.scie_pbs_release,
        python_version=python_version,
        science_binary_url=science_binary_url,
    )


def build(
    configuration,  # type: ScieConfiguration
    pex_file,  # type: str
    url_fetcher=None,  # type: Optional[URLFetcher]
    env=ENV,  # type: Variables
):
    # type: (...) -> Iterator[ScieInfo]

    return science.build(configuration, pex_file, url_fetcher=url_fetcher, env=env)
