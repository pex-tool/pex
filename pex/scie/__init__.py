# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
from argparse import Namespace, _ActionsContainer

from pex.argparse import HandleBoolAction
from pex.compatibility import urlparse
from pex.dist_metadata import NamedEntryPoint
from pex.fetcher import URLFetcher
from pex.orderedset import OrderedSet
from pex.pep_440 import Version
from pex.scie import science
from pex.scie.model import (
    BusyBoxEntryPoints,
    ConsoleScriptsManifest,
    File,
    InterpreterDistribution,
    PlatformNamingStyle,
    Provider,
    ScieConfiguration,
    ScieInfo,
    ScieOptions,
    SciePlatform,
    ScieStyle,
    Url,
)
from pex.scie.science import SCIENCE_RELEASES_URL, SCIENCE_REQUIREMENT
from pex.typing import TYPE_CHECKING, cast
from pex.variables import ENV, Variables

if TYPE_CHECKING:
    from typing import Iterator, List, Optional, Text, Tuple, Union

__all__ = (
    "InterpreterDistribution",
    "Provider",
    "ScieConfiguration",
    "ScieInfo",
    "ScieOptions",
    "SciePlatform",
    "ScieStyle",
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
            "compatible portable CPython or PyPy interpreter as appropriate. Note that only "
            "Python>=3.8 is supported. If you'd like to explicitly control the target platforms or "
            "the exact portable CPython selected, see `--scie-platform`, `--scie-pbs-release` and "
            "`--scie-python-version`. Specifying `--scie {lazy}` will fetch the portable CPython "
            "interpreter just in time on first boot of the PEX scie on a given machine if needed. "
            "The URL(s) to fetch the portable CPython interpreter from can be customized by "
            "exporting the PEX_BOOTSTRAP_URLS environment variable pointing to a json file with "
            'the format: `{{"ptex": {{<file name 1>: <url>, ...}}}}` where the file names should '
            "match those found via `SCIE=inspect <the PEX scie> | jq .ptex` with appropriate "
            "replacement URLs. Specifying `--scie {eager}` will embed the portable CPython "
            "interpreter in your PEX scie making for a larger file, but requiring no internet "
            "access to boot. If you have customization needs not addressed by the Pex `--scie*` "
            "options, consider using `science` to build your scies (which is what Pex uses behind "
            "the scenes); see: https://science.scie.app.".format(
                lazy=ScieStyle.LAZY, eager=ScieStyle.EAGER
            )
        ),
    )
    parser.add_argument(
        "--scie-only",
        "--no-scie-only",
        "--pex-and-scie",
        dest="scie_only",
        default=False,
        type=bool,
        action=HandleBoolAction,
        help=(
            "Only output a scie. By default, both a PEX and a scie are output unless the "
            "`-o` / `--output-file` specified has no '.pex' extension or a platform suffix is "
            "included (see `--scie-name-platform`)."
        ),
    )
    parser.add_argument(
        "--scie-name-style",
        dest="naming_style",
        default=None,
        type=PlatformNamingStyle.for_value,
        choices=PlatformNamingStyle.values(),
        help=(
            "Control how the `-o` / --output-file` translates to a scie name. By default ("
            "`--scie-name-style dynamic`), the platform is used as a file suffix only when needed "
            "for disambiguation when targeting a local platform. Specifying "
            "`--scie-name-style platform-file-suffix` forces the scie target platform name to be "
            "added as a suffix of the output filename; e.g.: `-o app` would produce a scie named "
            "app-linux-x86_64 assuming the scie targets that platform. Specifying "
            "`--scie-name-style platform-parent-dir` places the scie in a sub-directory with the "
            "name of the platform it targets; e.g.: `-o app` would produce a scie at "
            "`macos-aarch64/app` assuming the scie targets that platform."
        ),
    )
    parser.add_argument(
        "--scie-busybox",
        dest="scie_busybox",
        type=str,
        default=[],
        action="append",
        help=(
            "Make the PEX scie a BusyBox over the specified entry points. The entry points can "
            "either be console scripts or entry point specifiers. To select all console scripts in "
            "all distributions contained in the PEX, use `@`. To just pick all the console scripts "
            "from a particular project name's distributions in the PEX, use `@<project name>`; "
            "e.g.: `@ansible-core`. To exclude all the console scripts from a project, prefix with "
            "a `!`; e.g.: `@,!@ansible-core` selects all console scripts except those provided by "
            "the `ansible-core` project. To select an individual console script, just use its name "
            "or prefix the name with `!` to exclude that individual console script. To specify an "
            "arbitrary entry point in a module contained within one of the distributions in the "
            "PEX, use a string of the form `<name>=<module>(:<function>)`; e.g.: "
            "'run-baz=foo.bar:baz' to execute the `baz` function in the `foo.bar` module as the "
            "entry point named `run-baz`. Multiple entry points can be specified at once using a "
            "comma-separated list or the option can be specified multiple times. A BusyBox scie "
            "has no default entrypoint; instead, when run, it inspects argv0; if that matches one "
            "of its embedded entry points, it runs that entry point; if not, it lists all "
            "available entrypoints for you to pick from. To run a given entry point, you specify "
            "it as the first argument and all other arguments after that are forwarded to that "
            "entry point. BusyBox PEX scies allow you to install all their contained entry points "
            "into a given directory. For more information, run `SCIE=help <your PEX scie>` and "
            "review the `install` command help."
        ),
    )
    parser.add_argument(
        "--scie-busybox-pex-entrypoint-env-passthrough",
        "--no-scie-busybox-pex-entrypoint-env-passthrough",
        dest="scie_busybox_pex_entrypoint_env_passthrough",
        default=False,
        type=bool,
        action=HandleBoolAction,
        help=(
            "When creating a busybox, allow overriding the primary entrypoint at runtime via "
            "PEX_INTERPRETER, PEX_SCRIPT and PEX_MODULE. Note that when using --venv this adds "
            "modest startup overhead on the order of 10ms."
        ),
    )
    parser.add_argument(
        "--scie-platform",
        dest="scie_platforms",
        default=[],
        action="append",
        type=SciePlatform.parse,
        choices=[
            platform
            for platform in SciePlatform.values()
            if platform not in (SciePlatform.WINDOWS_AARCH64, SciePlatform.WINDOWS_X86_64)
        ],
        help=(
            "The platform to produce the native PEX scie executable for. Can be specified multiple "
            "times. You can use a value of 'current' to select the current platform. If left "
            "unspecified, the platforms implied by the targets selected to build the PEX with are "
            "used. Those targets are influenced by the current interpreter running Pex as well as "
            "use of `--python`, `--interpreter-constraint`, `--platform` or `--complete-platform` "
            "options. Note that, in general, `--scie-platform` should only be used to select a "
            "subset of the platforms implied by the targets selected via other options."
        ),
    )
    parser.add_argument(
        "--scie-pbs-release",
        dest="scie_pbs_release",
        default=None,
        type=str,
        help=(
            "The Python Standalone Builds release to use when a CPython interpreter distribution "
            "is needed for the PEX scie. Currently, releases are dates of the form YYYYMMDD, "
            "e.g.: '20240713'. See their GitHub releases page at"
            "https://github.com/astral-sh/python-build-standalone/releases to discover available "
            "releases. If left unspecified the latest release is used. N.B.: The latest lookup is "
            "cached for 5 days. To force a fresh lookup you can remove the cache at "
            "<USER CACHE DIR>/science/downloads."
        ),
    )
    parser.add_argument(
        "--scie-pypy-release",
        dest="scie_pypy_release",
        default=None,
        type=str,
        help=(
            "The PyPy release to use when a PyPy interpreter distribution is needed for the PEX "
            "scie. Currently, stable releases are of the form `v<major>.<minor>.<patch>`, "
            "e.g.: 'v7.3.16'. See their download page at https://pypy.org/download.html for the "
            "latest release and https://downloads.python.org/pypy/ to discover all available "
            "releases. If left unspecified, the latest release is used. N.B.: The latest lookup is "
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
            "https://github.com/astral-sh/python-build-standalone/releases if you wish to pin down "
            "to the patch level."
        ),
    )
    parser.add_argument(
        "--scie-pbs-stripped",
        "--no-scie-pbs-stripped",
        dest="scie_pbs_stripped",
        default=False,
        type=bool,
        action=HandleBoolAction,
        help=(
            "Should the Python Standalone Builds CPython distributions used be stripped of debug "
            "symbols or not. For Linux and Windows particularly, the stripped distributions are "
            "less than half the size of the distributions that ship with debug symbols."
        ),
    )
    parser.add_argument(
        "--scie-hash-alg",
        dest="scie_hash_algorithms",
        default=[],
        action="append",
        type=str,
        help=(
            "Output a checksum file for each scie generated that is compatible with the shasum "
            "family of tools. For each unique --scie-hash-alg specified, a sibling file to each "
            "scie executable will be generated with the same stem as that scie file and hash "
            "algorithm name suffix. The file will contain the hex fingerprint of the scie "
            "executable using that algorithm to hash it. Supported algorithms include at least "
            "md5, sha1, sha256, sha384 and sha512. For the complete list of supported hash "
            "algorithms, see the science tool --hash documentation here: "
            "https://science.scie.app/cli.html#science-lift-build."
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
    # type: (ScieOptions) -> Text

    args = ["--scie", str(options.style)]  # type: List[Text]
    if options.naming_style:
        args.append("--scie-name-style")
        args.append(str(options.naming_style))
    if options.scie_only:
        args.append("--scie-only")
    if options.busybox_entrypoints:
        args.append("--scie-busybox")
        entrypoints = list(options.busybox_entrypoints.console_scripts_manifest.iter_specs())
        entrypoints.extend(map(str, options.busybox_entrypoints.ad_hoc_entry_points))
        args.append(",".join(entrypoints))
    if options.busybox_pex_entrypoint_env_passthrough:
        args.append("--scie-busybox-pex-entrypoint-env-passthrough")
    for platform in options.platforms:
        args.append("--scie-platform")
        args.append(str(platform))
    if options.pbs_release:
        args.append("--scie-pbs-release")
        args.append(options.pbs_release)
    if options.pypy_release:
        args.append("--scie-pypy-release")
        args.append(options.pypy_release)
    if options.python_version:
        args.append("--scie-python-version")
        args.append(".".join(map(str, options.python_version)))
    if options.pbs_stripped:
        args.append("--scie-pbs-stripped")
    for hash_algorithm in options.hash_algorithms:
        args.append("--scie-hash-alg")
        args.append(hash_algorithm)
    if options.science_binary:
        args.append("--scie-science-binary")
        args.append(options.science_binary)
    return " ".join(args)


def extract_options(options):
    # type: (Namespace) -> Optional[ScieOptions]

    if not options.scie_style:
        return None

    entry_points = None
    if options.scie_busybox:
        eps = []  # type: List[str]
        for value in options.scie_busybox:
            eps.extend(ep.strip() for ep in value.split(","))

        console_scripts_manifest = ConsoleScriptsManifest()
        ad_hoc_entry_points = []  # type: List[NamedEntryPoint]
        bad_entry_points = []  # type: List[str]
        for ep in eps:
            csm = ConsoleScriptsManifest.try_parse(ep)
            if csm:
                console_scripts_manifest = console_scripts_manifest.merge(csm)
            else:
                try:
                    ad_hoc_entry_point = NamedEntryPoint.parse(ep)
                except ValueError:
                    bad_entry_points.append(ep)
                else:
                    ad_hoc_entry_points.append(ad_hoc_entry_point)

        if bad_entry_points:
            raise ValueError(
                "The following --scie-busybox entry point specifications were not understood:\n"
                "{bad_entry_points}".format(bad_entry_points="\n".join(bad_entry_points))
            )
        entry_points = BusyBoxEntryPoints(
            console_scripts_manifest=console_scripts_manifest,
            ad_hoc_entry_points=tuple(ad_hoc_entry_points),
        )

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
                "  https://github.com/astral-sh/python-build-standalone/releases".format(
                    python_version=options.scie_python_version
                )
            )

    science_binary = None  # type: Optional[Union[File, Url]]
    if options.scie_science_binary:
        url_info = urlparse.urlparse(options.scie_science_binary)
        if not url_info.scheme and url_info.path and os.path.isfile(url_info.path):
            science_binary = File(os.path.abspath(url_info.path))
        else:
            science_binary = Url(options.scie_science_binary)

    return ScieOptions(
        style=options.scie_style,
        naming_style=options.naming_style,
        scie_only=options.scie_only,
        busybox_entrypoints=entry_points,
        busybox_pex_entrypoint_env_passthrough=options.scie_busybox_pex_entrypoint_env_passthrough,
        platforms=tuple(OrderedSet(options.scie_platforms)),
        pbs_release=options.scie_pbs_release,
        pypy_release=options.scie_pypy_release,
        python_version=python_version,
        pbs_stripped=options.scie_pbs_stripped,
        hash_algorithms=tuple(options.scie_hash_algorithms),
        science_binary=science_binary,
    )


def build(
    configuration,  # type: ScieConfiguration
    pex_file,  # type: str
    url_fetcher=None,  # type: Optional[URLFetcher]
    env=ENV,  # type: Variables
):
    # type: (...) -> Iterator[ScieInfo]

    return science.build(configuration, pex_file, url_fetcher=url_fetcher, env=env)
