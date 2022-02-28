# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import os
import sys

from pex import pex_warnings
from pex.common import atomic_directory, die, pluralize
from pex.inherit_path import InheritPath
from pex.interpreter import PythonInterpreter
from pex.interpreter_constraints import UnsatisfiableInterpreterConstraintsError
from pex.orderedset import OrderedSet
from pex.pex_info import PexInfo
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import Iterable, Iterator, List, NoReturn, Optional, Set, Tuple, Union

    from pex.interpreter import InterpreterIdentificationError, InterpreterOrError, PathFilter
    from pex.pex import PEX
    from pex.third_party.pkg_resources import Requirement


def parse_path(path):
    # type: (Optional[str]) -> Optional[OrderedSet[str]]
    """Parses a PATH string into a de-duped list of paths."""
    return (
        OrderedSet(PythonInterpreter.canonicalize_path(p) for p in path.split(os.pathsep))
        if path
        else None
    )


# TODO(John Sirois): Move this to interpreter_constraints.py. As things stand, both pex/bin/pex.py
#  and this file use this function. The Pex CLI should not depend on this file which hosts code
#  used at PEX runtime.
def iter_compatible_interpreters(
    path=None,  # type: Optional[str]
    valid_basenames=None,  # type: Optional[Iterable[str]]
    interpreter_constraints=None,  # type: Optional[Iterable[Union[str, Requirement]]]
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
        seen = set()  # type: Set[InterpreterOrError]

        normalized_paths = parse_path(path)

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
            constraints.append(
                "Version matches {}".format(" or ".join(map(str, interpreter_constraints)))
            )
        if valid_basenames:
            constraints.append("Basename is {}".format(" or ".join(valid_basenames)))
        raise UnsatisfiableInterpreterConstraintsError(constraints, candidates, failures)


def _select_path_interpreter(
    path=None,  # type: Optional[str]
    valid_basenames=None,  # type: Optional[Tuple[str, ...]]
    interpreter_constraints=None,  # type: Optional[Iterable[str]]
    preferred_interpreter=None,  # type: Optional[PythonInterpreter]
):
    # type: (...) -> Optional[PythonInterpreter]
    candidate_interpreters_iter = iter_compatible_interpreters(
        path=path,
        valid_basenames=valid_basenames,
        interpreter_constraints=interpreter_constraints,
        preferred_interpreter=preferred_interpreter,
    )
    current_interpreter = PythonInterpreter.get()  # type: PythonInterpreter
    preferred_interpreter = preferred_interpreter or current_interpreter
    candidate_interpreters = OrderedSet()  # type: OrderedSet[PythonInterpreter]
    for interpreter in candidate_interpreters_iter:
        if preferred_interpreter == interpreter:
            # Always respect the preferred interpreter if it doesn't violate other constraints.
            return preferred_interpreter
        else:
            candidate_interpreters.add(interpreter)
    if not candidate_interpreters:
        return None
    if current_interpreter in candidate_interpreters:
        # Always prefer continuing with the current interpreter when possible to avoid re-exec
        # overhead.
        return current_interpreter
    # TODO: Allow the selection strategy to be parameterized:
    #   https://github.com/pantsbuild/pex/issues/430
    return PythonInterpreter.latest_release_of_min_compatible_version(candidate_interpreters)


def find_compatible_interpreter(interpreter_constraints=None):
    # type: (Optional[Iterable[str]]) -> PythonInterpreter

    def gather_constraints():
        # type: () -> Iterable[str]
        constraints = []
        if ENV.PEX_PYTHON:
            constraints.append("PEX_PYTHON={}".format(ENV.PEX_PYTHON))
        if ENV.PEX_PYTHON_PATH:
            constraints.append("PEX_PYTHON_PATH={}".format(ENV.PEX_PYTHON_PATH))
        if interpreter_constraints:
            constraints.append("Version matches {}".format(" or ".join(interpreter_constraints)))
        return constraints

    preferred_interpreter = None  # type: Optional[PythonInterpreter]
    if ENV.PEX_PYTHON and os.path.isabs(ENV.PEX_PYTHON):
        try:
            preferred_interpreter = PythonInterpreter.from_binary(ENV.PEX_PYTHON)
        except PythonInterpreter.Error as e:
            raise UnsatisfiableInterpreterConstraintsError(
                constraints=gather_constraints(),
                candidates=[],
                failures=[(ENV.PEX_PYTHON, str(e))],
                preamble=(
                    "The specified PEX_PYTHON={pex_python} could not be identified as a "
                    "valid Python interpreter.".format(pex_python=ENV.PEX_PYTHON)
                ),
            )

    current_interpreter = PythonInterpreter.get()
    target = current_interpreter  # type: Optional[PythonInterpreter]
    with TRACER.timed("Selecting runtime interpreter", V=3):
        if ENV.PEX_PYTHON and not ENV.PEX_PYTHON_PATH:
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
                        preferred_interpreter=preferred_interpreter,
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
                    path=ENV.PEX_PYTHON_PATH,
                    interpreter_constraints=interpreter_constraints,
                    preferred_interpreter=preferred_interpreter,
                )
            except UnsatisfiableInterpreterConstraintsError as e:
                raise e.with_preamble(
                    "Failed to find compatible interpreter on path {path}.".format(
                        path=ENV.PEX_PYTHON_PATH or os.getenv("PATH")
                    )
                )

        if preferred_interpreter and target != preferred_interpreter:
            candidates = [preferred_interpreter, target] if target else [preferred_interpreter]
            raise UnsatisfiableInterpreterConstraintsError(
                constraints=gather_constraints(),
                candidates=candidates,
                failures=[],
                preamble=(
                    "The specified PEX_PYTHON={pex_python} did not meet other "
                    "constraints.".format(pex_python=ENV.PEX_PYTHON)
                ),
            )

        if target is None:
            # N.B.: This can only happen when PEX_PYTHON_PATH is set and interpreter_constraints
            # is empty, but we handle all constraints generally for sanity sake.
            raise UnsatisfiableInterpreterConstraintsError(
                constraints=gather_constraints(),
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
    pex_warnings.configure_warnings(ENV, pex_info=pex_info)
    return pex_info


def ensure_venv(
    pex,  # type: PEX
    collisions_ok=True,  # type: bool
):
    # type: (...) -> str
    pex_info = pex.pex_info()
    venv_dir = pex_info.venv_dir(pex_file=pex.path(), interpreter=pex.interpreter)
    if venv_dir is None:
        raise AssertionError(
            "Expected PEX-INFO for {} to have the components of a venv directory".format(pex.path())
        )
    if not pex_info.includes_tools:
        raise ValueError(
            "The PEX_VENV environment variable was set, but this PEX was not built with venv "
            "support (Re-build the PEX file with `pex --venv ...`)"
        )
    with atomic_directory(venv_dir, exclusive=True) as venv:
        if not venv.is_finalized():
            from pex.venv.pex import populate_venv
            from pex.venv.virtualenv import Virtualenv

            virtualenv = Virtualenv.create_atomic(
                venv_dir=venv,
                interpreter=pex.interpreter,
                copies=pex_info.venv_copies,
                prompt=os.path.basename(ENV.PEX) if ENV.PEX else None,
            )

            pex_path = os.path.abspath(pex.path())

            # A sha1 hash is 160 bits -> 20 bytes -> 40 hex characters. We start with 8 characters
            # (32 bits) of entropy since that is short and _very_ unlikely to collide with another
            # PEX venv on this machine. If we still collide after using the whole sha1 (for a total
            # of 33 collisions), then the universe is broken and we raise. It's the least we can do.
            venv_hash = hashlib.sha1(venv_dir.encode("utf-8")).hexdigest()
            collisions = []
            for chars in range(8, len(venv_hash) + 1):
                entropy = venv_hash[:chars]
                short_venv_dir = os.path.join(pex_info.pex_root, "venvs", "s", entropy)
                with atomic_directory(short_venv_dir, exclusive=True) as short_venv:
                    if short_venv.is_finalized():
                        collisions.append(short_venv_dir)
                        if entropy == venv_hash:
                            raise RuntimeError(
                                "The venv for {pex} at {venv} has hash collisions with {count} "
                                "other {venvs}!\n{collisions}".format(
                                    pex=pex_path,
                                    venv=venv_dir,
                                    count=len(collisions),
                                    venvs=pluralize(collisions, "venv"),
                                    collisions="\n".join(
                                        "{index}.) {venv_path}".format(
                                            index=index, venv_path=os.path.realpath(path)
                                        )
                                        for index, path in enumerate(collisions, start=1)
                                    ),
                                )
                            )
                        continue

                    os.symlink(venv_dir, os.path.join(short_venv.work_dir, "venv"))
                    shebang = populate_venv(
                        virtualenv,
                        pex,
                        bin_path=pex_info.venv_bin_path,
                        python=os.path.join(
                            short_venv_dir, "venv", "bin", os.path.basename(pex.interpreter.binary)
                        ),
                        collisions_ok=collisions_ok,
                        symlink=not pex_info.venv_site_packages_copies,
                    )

                    # There are popular Linux distributions with shebang length limits
                    # (BINPRM_BUF_SIZE in /usr/include/linux/binfmts.h) set at 128 characters, so
                    # we warn in the _very_ unlikely case that our shortened shebang is longer than
                    # this.
                    if len(shebang) > 128:
                        pex_warnings.warn(
                            "The venv for {pex} at {venv} has script shebangs of {shebang!r} with "
                            "{count} characters. On some systems this may be too long and cause "
                            "problems running the venv scripts. You may be able adjust PEX_ROOT "
                            "from {pex_root} to a shorter path as a work-around.".format(
                                pex=pex_path,
                                venv=venv_dir,
                                shebang=shebang,
                                count=len(shebang),
                                pex_root=pex_info.pex_root,
                            )
                        )

                    break

    return os.path.join(venv_dir, "pex")


# NB: This helper is used by the PEX bootstrap __main__.py code.
def bootstrap_pex(entry_point):
    # type: (str) -> None
    pex_info = _bootstrap(entry_point)

    # ENV.PEX_ROOT is consulted by PythonInterpreter and Platform so set that up as early as
    # possible in the run.
    with ENV.patch(PEX_ROOT=pex_info.pex_root):
        if not (ENV.PEX_UNZIP or ENV.PEX_TOOLS) and pex_info.venv:
            try:
                target = find_compatible_interpreter(
                    interpreter_constraints=pex_info.interpreter_constraints,
                )
            except UnsatisfiableInterpreterConstraintsError as e:
                die(str(e))
            from . import pex

            try:
                venv_pex = ensure_venv(pex.PEX(entry_point, interpreter=target))
            except ValueError as e:
                die(str(e))
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

    PEXEnvironment.mount(entry_point, pex_info).activate()
