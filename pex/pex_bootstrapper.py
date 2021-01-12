# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import sys

from pex import pex_warnings
from pex.common import atomic_directory, die
from pex.inherit_path import InheritPath
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import UnsatisfiableInterpreterConstraintsError
from pex.orderedset import OrderedSet
from pex.pex_info import PexInfo
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import (
        Iterable,
        Iterator,
        List,
        NoReturn,
        Optional,
        Tuple,
        Union,
    )

    from pex.interpreter import InterpreterIdentificationError, InterpreterOrError, PathFilter
    from pex.pex import PEX


# TODO(John Sirois): Move this to interpreter_constraints.py. As things stand, both pex/bin/pex.py
#  and this file use this function. The Pex CLI should not depend on this file which hosts code
#  used at PEX runtime.
def iter_compatible_interpreters(
    path=None,  # type: Optional[str]
    valid_basenames=None,  # type: Optional[Iterable[str]]
    interpreter_constraints=None,  # type: Optional[Iterable[str]]
    preferred_interpreter=None,  # type: Optional[PythonInterpreter]
):
    # type: (...) -> Iterator[PythonInterpreter]
    """Find all compatible interpreters on the system within the supplied constraints.

    :param path: A PATH-style string with files or directories separated by os.pathsep.
    :param valid_basenames: Valid basenames for discovered interpreter binaries. If not specified,
                            Then all typical names are accepted (i.e.: python, python3, python2.7,
                            pypy, etc.).
    :param interpreter_constraints: Interpreter type and version constraint strings as described in
                                    `--interpreter-constraint`.
    :param preferred_interpreter: For testing - an interpreter to prefer amongst all others.
                                  Defaults to the current running interpreter.

    Interpreters are searched for in `path` if specified and $PATH if not.

    If no interpreters are found and there are no further constraints (neither `valid_basenames` nor
    `interpreter_constraints` is specified) then the returned iterator will be empty. However, if
    there are constraints specified, the returned iterator, although emtpy, will raise
    `UnsatisfiableInterpreterConstraintsError` to provide information about any found interpreters
    that did not match all the constraints.
    """

    _valid_path = None  # type: Optional[PathFilter]
    if valid_basenames:
        _valid_basenames = frozenset(cast("Iterable[str]", valid_basenames))
        _valid_path = (
            lambda interpreter_path: os.path.basename(interpreter_path) in _valid_basenames
        )

    def _iter_interpreters():
        # type: () -> Iterator[InterpreterOrError]
        seen = set()

        normalized_paths = (
            OrderedSet(PythonInterpreter.canonicalize_path(p) for p in path.split(os.pathsep))
            if path
            else None
        )

        # Prefer the current interpreter, if valid.
        current_interpreter = preferred_interpreter or PythonInterpreter.get()
        if not _valid_path or _valid_path(current_interpreter.binary):
            if normalized_paths:
                candidate_paths = frozenset(
                    (current_interpreter.binary, os.path.dirname(current_interpreter.binary))
                )
                candidate_paths_in_path = candidate_paths.intersection(normalized_paths)
                if candidate_paths_in_path:
                    # In case the full path of the current interpreter binary was in the
                    # `normalized_paths` we're searching, remove it to prevent identifying it again
                    # just to then skip it as `seen`.
                    normalized_paths.discard(current_interpreter.binary)
                    seen.add(current_interpreter)
                    yield current_interpreter
            else:
                seen.add(current_interpreter)
                yield current_interpreter

        for interp in PythonInterpreter.iter_candidates(
            paths=normalized_paths, path_filter=_valid_path
        ):
            if interp not in seen:
                seen.add(interp)
                yield interp

    def _valid_interpreter(interp_or_error):
        # type: (InterpreterOrError) -> bool
        if not isinstance(interp_or_error, PythonInterpreter):
            return False

        if not interpreter_constraints:
            return True

        interp = cast(PythonInterpreter, interp_or_error)

        if any(
            interp.identity.matches(interpreter_constraint)
            for interpreter_constraint in interpreter_constraints
        ):
            TRACER.log(
                "Constraints on interpreters: {}, Matching Interpreter: {}".format(
                    interpreter_constraints, interp.binary
                ),
                V=3,
            )
            return True

        return False

    candidates = []  # type: List[PythonInterpreter]
    failures = []  # type: List[InterpreterIdentificationError]
    found = False

    for interpreter_or_error in _iter_interpreters():
        if isinstance(interpreter_or_error, PythonInterpreter):
            interpreter = cast(PythonInterpreter, interpreter_or_error)
            candidates.append(interpreter)
            if _valid_interpreter(interpreter_or_error):
                found = True
                yield interpreter
        else:
            error = cast("InterpreterIdentificationError", interpreter_or_error)
            failures.append(error)

    if not found and (interpreter_constraints or valid_basenames):
        constraints = []  # type: List[str]
        if interpreter_constraints:
            constraints.append("Version matches {}".format(" or ".join(interpreter_constraints)))
        if valid_basenames:
            constraints.append("Basename is {}".format(" or ".join(valid_basenames)))
        raise UnsatisfiableInterpreterConstraintsError(constraints, candidates, failures)


def _select_path_interpreter(
    path=None,  # type: Optional[str]
    valid_basenames=None,  # type: Optional[Tuple[str, ...]]
    interpreter_constraints=None,  # type: Optional[Iterable[str]]
):
    # type: (...) -> Optional[PythonInterpreter]
    candidate_interpreters_iter = iter_compatible_interpreters(
        path=path,
        valid_basenames=valid_basenames,
        interpreter_constraints=interpreter_constraints,
    )
    current_interpreter = PythonInterpreter.get()  # type: PythonInterpreter
    candidate_interpreters = []
    for interpreter in candidate_interpreters_iter:
        if current_interpreter == interpreter:
            # Always prefer continuing with the current interpreter when possible to avoid re-exec
            # overhead.
            return current_interpreter
        else:
            candidate_interpreters.append(interpreter)
    if not candidate_interpreters:
        return None

    # TODO: Allow the selection strategy to be parameterized:
    #   https://github.com/pantsbuild/pex/issues/430
    return PythonInterpreter.latest_release_of_min_compatible_version(candidate_interpreters)


def find_compatible_interpreter(interpreter_constraints=None):
    # type: (Optional[Iterable[str]]) -> PythonInterpreter
    current_interpreter = PythonInterpreter.get()
    target = current_interpreter  # type: Optional[PythonInterpreter]
    with TRACER.timed("Selecting runtime interpreter", V=3):
        if ENV.PEX_PYTHON and not ENV.PEX_PYTHON_PATH:
            # preserve PEX_PYTHON re-exec for backwards compatibility
            # TODO: Kill this off completely in favor of PEX_PYTHON_PATH
            # https://github.com/pantsbuild/pex/issues/431
            TRACER.log(
                "Using PEX_PYTHON={} constrained by {}".format(
                    ENV.PEX_PYTHON, interpreter_constraints
                ),
                V=3,
            )
            try:
                if os.path.isabs(ENV.PEX_PYTHON):
                    target = _select_path_interpreter(
                        path=ENV.PEX_PYTHON,
                        interpreter_constraints=interpreter_constraints,
                    )
                else:
                    target = _select_path_interpreter(
                        valid_basenames=(os.path.basename(ENV.PEX_PYTHON),),
                        interpreter_constraints=interpreter_constraints,
                    )
            except UnsatisfiableInterpreterConstraintsError as e:
                raise e.with_preamble(
                    "Failed to find a compatible PEX_PYTHON={pex_python}.".format(
                        pex_python=ENV.PEX_PYTHON
                    )
                )
        elif ENV.PEX_PYTHON_PATH or interpreter_constraints:
            TRACER.log(
                "Using {path} constrained by {constraints}".format(
                    path="PEX_PYTHON_PATH={}".format(ENV.PEX_PYTHON_PATH)
                    if ENV.PEX_PYTHON_PATH
                    else "$PATH",
                    constraints=interpreter_constraints,
                ),
                V=3,
            )
            try:
                target = _select_path_interpreter(
                    path=ENV.PEX_PYTHON_PATH, interpreter_constraints=interpreter_constraints
                )
            except UnsatisfiableInterpreterConstraintsError as e:
                raise e.with_preamble(
                    "Failed to find compatible interpreter on path {path}.".format(
                        path=ENV.PEX_PYTHON_PATH or os.getenv("PATH")
                    )
                )

        if target is None:
            # N.B.: This can only happen when PEX_PYTHON_PATH is set and interpreter_constraints
            # is empty, but we handle all constraints generally for sanity sake.
            constraints = []
            if ENV.PEX_PYTHON:
                constraints.append("PEX_PYTHON={}".format(ENV.PEX_PYTHON))
            if ENV.PEX_PYTHON_PATH:
                constraints.append("PEX_PYTHON_PATH={}".format(ENV.PEX_PYTHON_PATH))
            if interpreter_constraints:
                constraints.append(
                    "Version matches {}".format(" or ".join(interpreter_constraints))
                )
            raise UnsatisfiableInterpreterConstraintsError(
                constraints=constraints,
                candidates=[current_interpreter],
                failures=[],
                preamble="Could not find a compatible interpreter.",
            )
        return target


def maybe_reexec_pex(interpreter_constraints=None):
    # type: (Optional[Iterable[str]]) -> Union[None, NoReturn]
    """Handle environment overrides for the Python interpreter to use when executing this pex.

    This function supports interpreter filtering based on interpreter constraints stored in PEX-INFO
    metadata. If PEX_PYTHON is set it attempts to obtain the binary location of the interpreter
    specified by PEX_PYTHON. If PEX_PYTHON_PATH is set, it attempts to search the path for a
    matching interpreter in accordance with the interpreter constraints. If both variables are
    present, this function gives precedence to PEX_PYTHON_PATH and errors out if no compatible
    interpreters can be found on said path.

    If neither variable is set, we fall back to plain PEX execution using PATH searching or the
    currently executing interpreter. If compatibility constraints are used, we match those
    constraints against these interpreters.

    :param interpreter_constraints: Optional list of requirements-style strings that constrain the
                                    Python interpreter to re-exec this pex with.
    """

    current_interpreter = PythonInterpreter.get()

    # NB: Used only for tests.
    if "_PEX_EXEC_CHAIN" in os.environ:
        flag_or_chain = os.environ.pop("_PEX_EXEC_CHAIN")
        pex_exec_chain = [] if flag_or_chain == "1" else flag_or_chain.split(os.pathsep)
        pex_exec_chain.append(current_interpreter.binary)
        os.environ["_PEX_EXEC_CHAIN"] = os.pathsep.join(pex_exec_chain)

    current_interpreter_blessed_env_var = "_PEX_SHOULD_EXIT_BOOTSTRAP_REEXEC"
    if os.environ.pop(current_interpreter_blessed_env_var, None):
        # We've already been here and selected an interpreter. Continue to execution.
        return None

    try:
        target = find_compatible_interpreter(
            interpreter_constraints=interpreter_constraints,
        )
    except UnsatisfiableInterpreterConstraintsError as e:
        die(str(e))

    os.environ.pop("PEX_PYTHON", None)
    os.environ.pop("PEX_PYTHON_PATH", None)

    if ENV.PEX_INHERIT_PATH == InheritPath.FALSE:
        # Now that we've found a compatible Python interpreter, make sure we resolve out of any
        # virtual environments it may be contained in since virtual environments created with
        # `--system-site-packages` foil PEX attempts to scrub the sys.path.
        resolved = target.resolve_base_interpreter()
        if resolved != target:
            TRACER.log(
                "Resolved base interpreter of {} from virtual environment at {}".format(
                    resolved, target.prefix
                ),
                V=3,
            )
        target = resolved

    from . import pex

    pythonpath = pex.PEX.stash_pythonpath()
    if pythonpath is not None:
        TRACER.log("Stashed PYTHONPATH of {}".format(pythonpath), V=2)
    elif target == current_interpreter:
        TRACER.log(
            "Using the current interpreter {} since it matches constraints and "
            "PYTHONPATH is not set.".format(sys.executable)
        )
        return None

    target_binary = target.binary
    cmdline = [target_binary] + sys.argv
    TRACER.log(
        "Re-executing: "
        "cmdline={cmdline!r}, "
        "sys.executable={python!r}, "
        "PEX_PYTHON={pex_python!r}, "
        "PEX_PYTHON_PATH={pex_python_path!r}, "
        "interpreter_constraints={interpreter_constraints!r}"
        "{pythonpath}".format(
            cmdline=" ".join(cmdline),
            python=sys.executable,
            pex_python=ENV.PEX_PYTHON,
            pex_python_path=ENV.PEX_PYTHON_PATH,
            interpreter_constraints=interpreter_constraints,
            pythonpath=', (stashed) PYTHONPATH="{}"'.format(pythonpath)
            if pythonpath is not None
            else "",
        )
    )

    # Avoid a re-run through compatibility_constraint checking.
    os.environ[current_interpreter_blessed_env_var] = "1"

    os.execv(target_binary, cmdline)


def _bootstrap(entry_point):
    # type: (str) -> PexInfo
    pex_info = PexInfo.from_pex(entry_point)  # type: PexInfo
    pex_info.update(PexInfo.from_env())
    pex_warnings.configure_warnings(pex_info, ENV)
    return pex_info


def ensure_venv(pex):
    # type: (PEX) -> str
    pex_info = pex.pex_info()
    venv_dir = pex_info.venv_dir
    if venv_dir is None:
        raise AssertionError(
            "Expected PEX-INFO for {} to have the components of a venv directory".format(pex.path())
        )
    with atomic_directory(venv_dir, exclusive=True) as venv:
        if venv:
            from .tools.commands.venv import populate_venv_with_pex
            from .tools.commands.virtualenv import Virtualenv

            virtualenv = Virtualenv.create(venv_dir=venv, interpreter=pex.interpreter)
            populate_venv_with_pex(
                virtualenv,
                pex,
                bin_path=pex_info.venv_bin_path,
                python=os.path.join(venv_dir, "bin", os.path.basename(pex.interpreter.binary)),
                collisions_ok=True,
            )
    return os.path.join(venv_dir, "pex")


# NB: This helper is used by the PEX bootstrap __main__.py code.
def bootstrap_pex(entry_point):
    # type: (str) -> None
    pex_info = _bootstrap(entry_point)

    if not ENV.PEX_TOOLS and pex_info.venv:
        try:
            target = find_compatible_interpreter(
                interpreter_constraints=pex_info.interpreter_constraints,
            )
        except UnsatisfiableInterpreterConstraintsError as e:
            die(str(e))
        from . import pex

        venv_pex = ensure_venv(pex.PEX(entry_point, interpreter=target))
        os.execv(venv_pex, [venv_pex] + sys.argv[1:])
    else:
        maybe_reexec_pex(pex_info.interpreter_constraints)
        from . import pex

        pex.PEX(entry_point).execute()


# NB: This helper is used by third party libs - namely https://github.com/wickman/lambdex.
# TODO(John Sirois): Kill once https://github.com/wickman/lambdex/issues/5 is resolved.
def is_compressed(entry_point):
    # type: (str) -> bool
    return os.path.exists(entry_point) and not os.path.exists(
        os.path.join(entry_point, PexInfo.PATH)
    )


# NB: This helper is used by third party libs like https://github.com/wickman/lambdex and
# https://github.com/kwlzn/pyuwsgi_pex.
def bootstrap_pex_env(entry_point):
    # type: (str) -> None
    """Bootstrap the current runtime environment using a given pex."""
    pex_info = _bootstrap(entry_point)

    from .environment import PEXEnvironment

    PEXEnvironment(entry_point, pex_info).activate()
