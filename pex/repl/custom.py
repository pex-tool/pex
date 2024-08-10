# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import re
import sys
import warnings
from code import InteractiveConsole

TYPE_CHECKING = False

if TYPE_CHECKING:
    from typing import Any, Callable, Dict, Mapping, Optional, Tuple


_ANSI_RE = re.compile(r"\033\[[;?0-9]*[a-zA-Z]")


def _try_enable_readline(
    history=False,  # type: bool
    history_file=None,  # type: Optional[str]
):
    # type: (...) -> bool

    libedit = False

    try:
        import readline
    except ImportError:
        if history:
            warnings.warn(
                "PEX_INTERPRETER_HISTORY was requested which requires the `readline` "
                "module, but the current interpreter at {python} does not have readline "
                "support.".format(python=sys.executable)
            )
    else:
        # This import is used for its side effects by the parse_and_bind lines below.
        import rlcompleter  # NOQA

        # N.B.: This hacky method of detecting use of libedit for the readline
        # implementation is the recommended means.
        # See https://docs.python.org/3/library/readline.html
        if "libedit" in readline.__doc__:
            # Mac can use libedit, and libedit has different config syntax.
            readline.parse_and_bind("bind ^I rl_complete")
            libedit = True
        else:
            readline.parse_and_bind("tab: complete")

        try:
            # Under current PyPy readline does not implement read_init_file and emits a
            # warning; so we squelch that noise.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                readline.read_init_file()
        except (IOError, OSError):
            # No init file (~/.inputrc for readline or ~/.editrc for libedit).
            pass

        if history:
            import atexit

            histfile = os.path.expanduser(history_file or os.path.join("~", ".python_history"))
            try:
                readline.read_history_file(histfile)
                readline.set_history_length(1000)
            except (IOError, OSError) as e:
                sys.stderr.write(
                    "Failed to read history file at {path} due to: {err}\n".format(
                        path=histfile, err=e
                    )
                )

            atexit.register(readline.write_history_file, histfile)

    return libedit


def repl_loop(
    banner=None,  # type: Optional[str]
    ps1=None,  # type: Optional[str]
    ps2=None,  # type: Optional[str]
    custom_commands=None,  # type: Optional[Mapping[str, Tuple[Callable, str]]]
    history=False,  # type: bool
    history_file=None,  # type: Optional[str]
):
    # type: (...) -> Callable[[], Dict[str, Any]]

    libedit = _try_enable_readline(history=history, history_file=history_file)

    _custom_commands = custom_commands or {}

    class CustomREPL(InteractiveConsole):
        def raw_input(self, prompt=""):
            # type: (InteractiveConsole, str) -> Any
            line = InteractiveConsole.raw_input(self, prompt=prompt)
            maybe_custom_command = line.strip()
            command_info = _custom_commands.get(maybe_custom_command)
            if command_info:
                print(command_info[1])
                return ""
            return line

    local = {name: command_info[0] for name, command_info in _custom_commands.items()}

    # Expose the custom commands in the __main__ module so that rlcompleter (setup above in the
    # call to `_try_enable_readline`) will tab-complete them.
    main = sys.modules.get("__main__")
    if main:
        for name, command in local.items():
            setattr(main, name, command)

    repl = CustomREPL(locals=local)
    extra_args = {"exitmsg": ""} if sys.version_info[:2] >= (3, 6) else {}

    def fixup_ansi(
        text,  # type: str
        prompt=False,  # type: bool
    ):
        # type: (...) -> str

        if not sys.stdout.isatty():
            text = _ANSI_RE.sub("", text)
        elif prompt and libedit:
            # Most versions of libedit do not support ansi terminal escape sequences, but they do
            # support a readline back door where you can bracket characters that should be ignored
            # for prompt width calculation but otherwise passed through unaltered to the terminal.
            # This back door is defined in readline.h, which libedit implements, with the
            # RL_PROMPT_START_IGNORE and RL_PROMPT_END_IGNORE character constants which we use
            # below to bracket ansi terminal escape sequences.
            #
            # See:
            # + https://tiswww.cwru.edu/php/chet/readline/readline.html#index-rl_005fexpand_005fprompt
            # + https://git.savannah.gnu.org/cgit/readline.git/tree/readline.h?id=037d85f199a8c6e5b16689a46c8bc31b586a0c94#n884
            text = _ANSI_RE.sub(
                lambda match: "\001{ansi_sequence}\002".format(ansi_sequence=match.group(0)), text
            )
        return text + " " if prompt else text

    repl_banner = fixup_ansi(banner) if banner else banner

    def loop():
        # type: () -> Dict[str, Any]
        if ps1:
            sys.ps1 = fixup_ansi(ps1, prompt=True)
        if ps2:
            sys.ps2 = fixup_ansi(ps2, prompt=True)
        repl.interact(banner=repl_banner, **extra_args)
        return local

    return loop
