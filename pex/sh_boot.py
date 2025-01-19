# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import itertools
import os
import shlex
from textwrap import dedent

from pex import dist_metadata, variables
from pex.compatibility import shlex_quote
from pex.dist_metadata import Distribution
from pex.interpreter import PythonInterpreter, calculate_binary_name
from pex.interpreter_constraints import InterpreterConstraints, iter_compatible_versions
from pex.layout import Layout
from pex.orderedset import OrderedSet
from pex.pep_440 import Version
from pex.pex_info import PexInfo
from pex.targets import Targets
from pex.typing import TYPE_CHECKING
from pex.version import __version__

if TYPE_CHECKING:
    from typing import Iterable, List, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class PythonBinaryName(object):
    name = attr.ib()  # type: str
    version = attr.ib()  # type: Tuple[int, ...]

    def render(self, version_components=2):
        # type: (int) -> str
        return "{name}{version}".format(
            name=self.name, version=".".join(map(str, self.version[:version_components]))
        )


def _calculate_applicable_binary_names(
    targets,  # type: Targets
    interpreter_constraints,  # type: InterpreterConstraints
):
    # type: (...) -> Iterable[str]

    # Find all possible major / minor version targeted by this Pex, preferring explicit targets and
    # then filling in any other versions implied by interpreter constraints to be checked after
    # those.

    ic_majors_minors = OrderedSet()  # type: OrderedSet[PythonBinaryName]
    if interpreter_constraints:
        ic_majors_minors.update(
            PythonBinaryName(
                name=calculate_binary_name(platform_python_implementation=name), version=version
            )
            for interpreter_constraint in interpreter_constraints
            for version in iter_compatible_versions(
                requires_python=[str(interpreter_constraint.requires_python)]
            )
            for name in (
                (interpreter_constraint.name,)
                if interpreter_constraint.name
                else ("CPython", "PyPy")
            )
        )
    # If we get targets from ICs, we only want explicitly specified local interpreter targets;
    # otherwise, if there are none, we want the implicit current target interpreter.
    only_explicit = len(ic_majors_minors) > 0

    names = OrderedSet()  # type: OrderedSet[PythonBinaryName]
    # 1. Explicit targets 1st.
    for target in targets.unique_targets(only_explicit=only_explicit):
        if target.python_version is not None:
            names.add(
                PythonBinaryName(
                    name=target.binary_name(version_components=0), version=target.python_version
                )
            )

    # 2. ICs next.
    names.update(ic_majors_minors)

    # 3. As the final backstop, fill in all the interpreters Pex is compatible with since Pex can do
    # more sophisticated detection and re-direction from these during its own bootstrap. When doing
    # so, select these interpreters from newest to oldest since it more likely any given machine
    # will have Python 3 at this point than it will Python 2.
    pex_requires_python = ">=2.7"
    dist = dist_metadata.find_distribution("pex")  # type: Optional[Distribution]
    if dist and dist.metadata.version == Version(__version__):
        pex_requires_python = str(dist.metadata.requires_python)
    pex_supported_python_versions = tuple(
        reversed(list(iter_compatible_versions(requires_python=[pex_requires_python])))
    )

    # Favor CPython over PyPy since the interpreter discovered via these names will just be used
    # to re-execute into Pex using the right interpreter. That should be a low-latency operation
    # for CPython end targets and for PyPy it need not be quite as fast since it inherently asks you
    # to trade startup latency for longer term jit performance.
    names.update(
        PythonBinaryName(name="python", version=version)
        for version in pex_supported_python_versions
    )
    names.update(
        PythonBinaryName(name="pypy", version=version) for version in pex_supported_python_versions
    )

    # Favor more specific interpreter names since these should need re-direction less often.
    return OrderedSet(
        itertools.chain(
            (name.render(version_components=2) for name in names),
            (name.render(version_components=1) for name in names),
            (name.render(version_components=0) for name in names),
        )
    )


def create_sh_boot_script(
    pex_name,  # type: str
    pex_info,  # type: PexInfo
    targets,  # type: Targets
    interpreter,  # type: PythonInterpreter
    python_shebang=None,  # type: Optional[str]
    layout=Layout.ZIPAPP,  # type: Layout.Value
):
    # type: (...) -> str
    """Creates the body of a POSIX `sh` compatible script that executes a PEX ZIPAPP appended to it.

    N.B.: The shebang line is not included.

    Although a Python ZIPAPP is self-executing, it is only self-executing if the shebang happens to
    work on a given machine. Since there is variance with how pythons are named in various installs,
    this can lead to a failure to launch the ZIPAPP at all at the OS level.

    If the Python ZIPAPP shebang works, PEX still needs to check if it has installed itself in the
    PEX_ROOT and if the current interpreter selected by the shebang is appropriate and then it needs
    to re-execute itself using the appropriate interpreter and final installed location. This takes
    a non-trivial amount of time. Roughly 50ms in the warm case where the current interpreter is
    correct and the PEX ZIPAPP is already installed in the PEX_ROOT.

    Using this `sh` script can provide higher shebang success rates since almost every Unix has an
    `sh` interpreter at `/bin/sh`, and it reduces re-exec overhead to ~2ms in the warm case (and
    adds ~2ms in the cold case).
    """
    python = ""  # type: str
    python_args = list(pex_info.inject_python_args)  # type: List[str]
    if python_shebang:
        shebang = python_shebang[2:] if python_shebang.startswith("#!") else python_shebang
        # Drop leading `/usr/bin/env [args]?`.
        args = list(
            itertools.dropwhile(
                lambda word: not PythonInterpreter.matches_binary_name(word), shlex.split(shebang)
            )
        )
        python = args[0]
        python_args.extend(args[1:])
    venv_python_args = python_args[:]
    if pex_info.venv_hermetic_scripts:
        venv_python_args.append("-sE")

    python_names = tuple(
        _calculate_applicable_binary_names(
            targets=targets,
            interpreter_constraints=pex_info.interpreter_constraints,
        )
    )

    venv_dir = pex_info.raw_venv_dir(pex_file=pex_name, interpreter=interpreter)
    if venv_dir:
        pex_installed_path = venv_dir.path
    else:
        pex_hash = pex_info.pex_hash
        if pex_hash is None:
            raise ValueError("Expected pex_hash to be set already in PEX-INFO.")
        pex_installed_path = variables.unzip_dir(
            pex_info.raw_pex_root, pex_hash, expand_pex_root=False
        )

    return dedent(
        """\
        # N.B.: This script should stick to syntax defined for POSIX `sh` and avoid non-builtins.
        # See: https://pubs.opengroup.org/onlinepubs/9699919799/idx/shell.html
        set -eu

        VENV="{venv}"
        VENV_PYTHON_ARGS="{venv_python_args}"

        # N.B.: This ensures tilde-expansion of the DEFAULT_PEX_ROOT value.
        DEFAULT_PEX_ROOT="$(echo {pex_root})"

        DEFAULT_PYTHON="{python}"
        PYTHON_ARGS="{python_args}"

        PEX_ROOT="${{PEX_ROOT:-${{DEFAULT_PEX_ROOT}}}}"
        INSTALLED_PEX="${{PEX_ROOT}}/{pex_installed_relpath}"

        if [ -n "${{VENV}}" -a -x "${{INSTALLED_PEX}}" ]; then
            # We're a --venv execution mode PEX installed under the PEX_ROOT and the venv
            # interpreter to use is embedded in the shebang of our venv pex script; so just
            # execute that script directly.
            export PEX="{pex}"
            exec "${{INSTALLED_PEX}}/bin/python" ${{VENV_PYTHON_ARGS}} "${{INSTALLED_PEX}}" \\
                "$@"
        fi

        find_python() {{
            for python in \\
        {pythons} \\
            ; do
                if command -v "${{python}}" 2>/dev/null; then
                    return
                fi
            done
        }}

        if [ -x "${{DEFAULT_PYTHON}}" ]; then
            python_exe="${{DEFAULT_PYTHON}}"
        else
            python_exe="$(find_python)"
        fi
        if [ -n "${{python_exe}}" ]; then
            if [ -n "${{PEX_VERBOSE:-}}" ]; then
                echo >&2 "$0 used /bin/sh boot to select python: ${{python_exe}} for re-exec..."
            fi
            if [ -z "${{VENV}}" -a -e "${{INSTALLED_PEX}}" ]; then
                # We're a --zipapp execution mode PEX installed under the PEX_ROOT with a
                # __main__.py in our top-level directory; so execute Python against that
                # directory.
                export __PEX_EXE__="{pex}"
                exec "${{python_exe}}" ${{PYTHON_ARGS}} "${{INSTALLED_PEX}}" "$@"
            else
                # The slow path: this PEX zipapp is not installed yet. Run the PEX zipapp so it
                # can install itself, rebuilding its fast path layout under the PEX_ROOT.
                if [ -n "${{PEX_VERBOSE:-}}" ]; then
                    echo >&2 "Running zipapp pex to lay itself out under PEX_ROOT."
                fi
                exec "${{python_exe}}" ${{PYTHON_ARGS}} "$0" "$@"
            fi
        fi

        echo >&2 "Failed to find any of these python binaries on the PATH:"
        for python in \\
        {pythons} \\
        ; do
            echo >&2 "${{python}}"
        done
        echo >&2 'Either adjust your $PATH which is currently:'
        echo >&2 "${{PATH}}"
        echo >&2 -n "Or else install an appropriate Python that provides one of the binaries in "
        echo >&2 "this list."
        exit 1
        """
    ).format(
        venv="1" if pex_info.venv else "",
        python=python,
        python_args=" ".join(shlex_quote(python_arg) for python_arg in python_args),
        pythons=" \\\n".join('"{python}"'.format(python=python) for python in python_names),
        pex_root=pex_info.raw_pex_root,
        pex_installed_relpath=os.path.relpath(pex_installed_path, pex_info.raw_pex_root),
        venv_python_args=" ".join(
            shlex_quote(venv_python_arg) for venv_python_arg in venv_python_args
        ),
        pex="$0" if layout is Layout.ZIPAPP else '$(dirname "$0")',
    )
