# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.cli.command import BuildTimeCommand
from pex.docs.command import HtmlDocsConfig, register_open_options, serve_html_docs, server
from pex.result import Ok, Result, try_


class Docs(BuildTimeCommand):
    """Interact with the Pex documentation.

    With no arguments, ensures a local documentation server is running and then opens a browser
    to view the local docs.
    """

    @classmethod
    def add_extra_arguments(cls, parser):
        register_open_options(parser)
        parser.add_argument(
            "--no-open",
            dest="open",
            default=True,
            action="store_false",
            help="Don't open the docs; just ensure the docs server is running and print its info.",
        )
        kill_or_info = parser.add_mutually_exclusive_group()
        kill_or_info.add_argument(
            "-k",
            "--kill-server",
            dest="kill_server",
            default=False,
            action="store_true",
            help="Shut down the {server} if it is running.".format(server=server.name),
        )
        kill_or_info.add_argument(
            "--server-info",
            dest="server_info",
            default=False,
            action="store_true",
            help="Print information about the status of the {server}.".format(server=server.name),
        )

    def run(self):
        # type: () -> Result

        if self.options.server_info:
            pidfile = server.pidfile()
            if pidfile and pidfile.alive():
                return Ok(
                    "{server} serving {info}".format(server=server.name, info=pidfile.server_info)
                )
            return Ok("No {server} is running.".format(server=server.name))

        if self.options.kill_server:
            server_info = server.shutdown()
            if server_info:
                return Ok("Shut down {server} {info}".format(server=server.name, info=server_info))
            return Ok("No {server} was running.".format(server=server.name))

        launch_result = try_(
            serve_html_docs(
                open_browser=self.options.open, config=HtmlDocsConfig.from_options(self.options)
            )
        )
        if self.options.open:
            return Ok()

        return Ok(
            (
                "{server} already running {info}"
                if launch_result.already_running
                else "Launched {server} {info}"
            ).format(server=server.name, info=launch_result.server_info)
        )
