# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import logging
from argparse import Namespace, _ActionsContainer
from textwrap import dedent

from pex import docs
from pex.commands.command import try_open_file
from pex.docs.server import SERVER_NAME, LaunchError, LaunchResult
from pex.docs.server import launch as launch_docs_server
from pex.result import Error, try_
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


logger = logging.getLogger(__name__)


def register_open_options(parser):
    # type: (_ActionsContainer) -> None
    parser.add_argument(
        "--browser",
        dest="browser",
        default=None,
        help="The browser to use to open docs with. Defaults to the system default opener.",
    )


@attr.s(frozen=True)
class HtmlDocsConfig(object):
    @classmethod
    def from_options(
        cls,
        options,  # type: Namespace
        fallback_url=None,  # type: Optional[str]
    ):
        # type: (...) -> HtmlDocsConfig
        return cls(browser=options.browser, fallback_url=fallback_url)

    browser = attr.ib(default=None)  # type: Optional[str]
    fallback_url = attr.ib(default=None)  # type: Optional[str]


# PEX in ascii-hex rotated left 1 character and trailing 0 dropped:
# E    X    P
# 0x45 0x58 0x50
#
# This is a currently unassigned port in the 1024-49151 user port registration range.
# This value plays by the loose rules and satisfies the criteria of being unlikely to be in use.
# We have no intention of registering with IANA tough!
STANDARD_PORT = 45585


def serve_html_docs(
    open_browser=False,  # type: bool
    config=HtmlDocsConfig(),  # type: HtmlDocsConfig
):
    # type: (...) -> Union[LaunchResult, Error]
    html_docs = docs.root(doc_type="html")
    if not html_docs:
        return Error(
            dedent(
                """\
                This Pex distribution does not include embedded docs.

                You can find the latest docs here:
                HTML: https://docs.pex-tool.org
                 PDF: https://github.com/pex-tool/pex/releases/latest/download/pex.pdf
                """
            ).rstrip()
        )

    try:
        result = launch_docs_server(html_docs, port=STANDARD_PORT)
    except LaunchError:
        try:
            result = launch_docs_server(html_docs, port=0)
        except LaunchError as e:
            with open(e.log) as fp:
                for line in fp:
                    logger.log(logging.ERROR, line.rstrip())
            return Error("Failed to launch {server}.".format(server=SERVER_NAME))

    if open_browser:
        try_(
            try_open_file(result.server_info.url, open_program=config.browser, suppress_stderr=True)
        )

    return result
