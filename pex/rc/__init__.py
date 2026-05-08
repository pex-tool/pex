# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
from argparse import Namespace, _ActionsContainer

from pex.argparse import HandleBoolAction
from pex.compatibility import urlparse
from pex.fetcher import URLFetcher
from pex.orderedset import OrderedSet
from pex.rc import pexrc
from pex.rc.model import CompressionMethod, File, NativeRuntimeConfiguration, Url
from pex.rc.pexrc import PEXRC_RELEASES_URL, PEXRC_REQUIREMENT
from pex.sysconfig import SysPlatform
from pex.typing import TYPE_CHECKING
from pex.variables import ENV, Variables

if TYPE_CHECKING:
    from typing import List, Optional, Text, Union


def register_options(parser):
    # type: (_ActionsContainer) -> None
    parser.add_argument(
        "--rc",
        "--no-rc",
        "--pexrc",
        "--no-pexrc",
        "--native-runtime",
        "--no-native-runtime",
        dest="native_runtime",
        default=False,
        type=bool,
        action=HandleBoolAction,
        help=(
            "Build the PEX with a native runtime. If the PEX contains native wheels, the "
            "appropriate native runtimes will be used. If the PEX only contains pure-Python "
            "wheels, then all available native runtimes will be included in the PEX. This may be "
            "un-necessary and bloat the PEX file. To restrict the native runtimes to just the "
            "platforms you deploy to, specify one or more `--pexrc-platform`s."
        ),
    )
    parser.add_argument(
        "-Z",
        "--compression-method",
        type=CompressionMethod.for_value,
        choices=CompressionMethod.values(),
        default=None,
        dest="compression_method",
        help=(
            "When building a native PEX, by default all user code and wheels are re-compressed "
            "using zstd. You can opt out by using this option to select the standard deflated zip "
            "compression method."
        ),
    )
    parser.add_argument(
        "--compression-level",
        type=int,
        default=None,
        dest="compression_level",
        help=(
            "Native PEX re-compression uses default compression levels for zstd and deflated. To "
            "request more or less aggressive compression, you can set this value. The range of "
            "values accepted depend on the compression method. For zstd, you can use -7 (least)"
            "to 22 (most) with the default being 3. Consult zstd documentation for more "
            "information on tradeoffs entailed. For deflated, you can use 0 (no compression) to 9 "
            "(most) with the default being 6."
        ),
    )
    parser.add_argument(
        "--pexrc-platform",
        dest="pexrc_platforms",
        default=[],
        action="append",
        type=SysPlatform.parse,
        choices=SysPlatform.values(),
        help=(
            "The platforms to inject native runtimes for. By default, all available native "
            "runtimes will be included in the PEX, but specifying one or more platforms will cap "
            "the total number used. If it can be determined that less will be needed, then just "
            "that subset of the specified platforms will be used."
        ),
    )
    parser.add_argument(
        "--pexrc-binary",
        dest="pexrc_binary",
        default=None,
        type=str,
        help=(
            "The file path of a `pexrc` binary or a URL to use to fetch the `pexrc` binary "
            "when there is no `pexrc` on the PATH with a version matching {pexrc_requirement}. "
            "Pex uses the official `pexrc` releases at {pexrc_releases_url} by default.".format(
                pexrc_requirement=PEXRC_REQUIREMENT, pexrc_releases_url=PEXRC_RELEASES_URL
            )
        ),
    )


def extract_configuration(
    options,  # type: Namespace
    max_jobs,  # type: Optional[int]
):
    # type: (...) -> Optional[NativeRuntimeConfiguration]

    if not options.native_runtime:
        return None

    pexrc_binary = None  # type: Optional[Union[File, Url]]
    if options.pexrc_binary:
        url_info = urlparse.urlparse(options.pexrc_binary)
        if not url_info.scheme and url_info.path and os.path.isfile(url_info.path):
            pexrc_binary = File(os.path.abspath(url_info.path))
        else:
            pexrc_binary = Url(options.pexrc_binary)

    return NativeRuntimeConfiguration(
        max_jobs=max_jobs,
        compression_method=options.compression_method,
        compression_level=options.compression_level,
        platforms=tuple(OrderedSet(options.pexrc_platforms)),
        pexrc_binary=pexrc_binary,
    )


def render_options(options):
    # type: (NativeRuntimeConfiguration) -> Text

    args = ["--native-runtime"]  # type: List[Text]
    if options.compression_method:
        args.append("--compression-method")
        args.append(options.compression_method.value)
    if options.compression_level:
        args.append("--compression-level")
        args.append(str(options.compression_level))
    for platform in options.platforms:
        args.append("--pexrc-platform")
        args.append(str(platform))
    if options.pexrc_binary:
        args.append("--pexrc-binary")
        args.append(options.pexrc_binary)
    return " ".join(args)


def inject(
    configuration,  # type: NativeRuntimeConfiguration
    pex_file,  # type: str
    url_fetcher=None,  # type: Optional[URLFetcher]
    env=ENV,  # type: Variables
):
    # type: (...) -> None

    pexrc.inject(configuration, pex_file, url_fetcher=url_fetcher, env=env)
