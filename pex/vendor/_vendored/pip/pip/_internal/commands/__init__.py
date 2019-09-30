"""
Package containing all pip commands
"""
from __future__ import absolute_import

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.commands.completion import CompletionCommand  # vendor:skip
else:
  from pex.third_party.pip._internal.commands.completion import CompletionCommand

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.commands.configuration import ConfigurationCommand  # vendor:skip
else:
  from pex.third_party.pip._internal.commands.configuration import ConfigurationCommand

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.commands.debug import DebugCommand  # vendor:skip
else:
  from pex.third_party.pip._internal.commands.debug import DebugCommand

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.commands.download import DownloadCommand  # vendor:skip
else:
  from pex.third_party.pip._internal.commands.download import DownloadCommand

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.commands.freeze import FreezeCommand  # vendor:skip
else:
  from pex.third_party.pip._internal.commands.freeze import FreezeCommand

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.commands.hash import HashCommand  # vendor:skip
else:
  from pex.third_party.pip._internal.commands.hash import HashCommand

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.commands.help import HelpCommand  # vendor:skip
else:
  from pex.third_party.pip._internal.commands.help import HelpCommand

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.commands.list import ListCommand  # vendor:skip
else:
  from pex.third_party.pip._internal.commands.list import ListCommand

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.commands.check import CheckCommand  # vendor:skip
else:
  from pex.third_party.pip._internal.commands.check import CheckCommand

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.commands.search import SearchCommand  # vendor:skip
else:
  from pex.third_party.pip._internal.commands.search import SearchCommand

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.commands.show import ShowCommand  # vendor:skip
else:
  from pex.third_party.pip._internal.commands.show import ShowCommand

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.commands.install import InstallCommand  # vendor:skip
else:
  from pex.third_party.pip._internal.commands.install import InstallCommand

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.commands.uninstall import UninstallCommand  # vendor:skip
else:
  from pex.third_party.pip._internal.commands.uninstall import UninstallCommand

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.commands.wheel import WheelCommand  # vendor:skip
else:
  from pex.third_party.pip._internal.commands.wheel import WheelCommand


if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.utils.typing import MYPY_CHECK_RUNNING  # vendor:skip
else:
  from pex.third_party.pip._internal.utils.typing import MYPY_CHECK_RUNNING


if MYPY_CHECK_RUNNING:
    from typing import List, Type
    if "__PEX_UNVENDORED__" in __import__("os").environ:
      from pip._internal.cli.base_command import Command  # vendor:skip
    else:
      from pex.third_party.pip._internal.cli.base_command import Command


commands_order = [
    InstallCommand,
    DownloadCommand,
    UninstallCommand,
    FreezeCommand,
    ListCommand,
    ShowCommand,
    CheckCommand,
    ConfigurationCommand,
    SearchCommand,
    WheelCommand,
    HashCommand,
    CompletionCommand,
    DebugCommand,
    HelpCommand,
]  # type: List[Type[Command]]

commands_dict = {c.name: c for c in commands_order}


def get_summaries(ordered=True):
    """Yields sorted (command name, command summary) tuples."""

    if ordered:
        cmditems = _sort_commands(commands_dict, commands_order)
    else:
        cmditems = commands_dict.items()

    for name, command_class in cmditems:
        yield (name, command_class.summary)


def get_similar_commands(name):
    """Command name auto-correct."""
    from difflib import get_close_matches

    name = name.lower()

    close_commands = get_close_matches(name, commands_dict.keys())

    if close_commands:
        return close_commands[0]
    else:
        return False


def _sort_commands(cmddict, order):
    def keyfn(key):
        try:
            return order.index(key[1])
        except ValueError:
            # unordered items should come last
            return 0xff

    return sorted(cmddict.items(), key=keyfn)
