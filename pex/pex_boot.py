# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys

TYPE_CHECKING = False

if TYPE_CHECKING:
    from typing import Any, List, NoReturn, Optional, Tuple


if sys.version_info >= (3, 10):

    def orig_argv():
        # type: () -> List[str]
        return sys.orig_argv

else:
    try:
        import ctypes

        # N.B.: None of the PyPy versions we support <3.10 supports the pythonapi.
        from ctypes import pythonapi

        def orig_argv():
            # type: () -> List[str]

            # Under MyPy for Python 3.5, ctypes.POINTER is incorrectly typed. This code is tested
            # to work correctly in practice on all Pythons Pex supports.
            argv = ctypes.POINTER(  # type: ignore[call-arg]
                ctypes.c_char_p if sys.version_info[0] == 2 else ctypes.c_wchar_p
            )()

            argc = ctypes.c_int()
            pythonapi.Py_GetArgcArgv(ctypes.byref(argc), ctypes.byref(argv))

            # Under MyPy for Python 3.5, argv[i] has its type incorrectly evaluated. This code
            # is tested to work correctly in practice on all Pythons Pex supports.
            return [argv[i] for i in range(argc.value)]  # type: ignore[misc]

    except ImportError:
        # N.B.: This handles the older PyPy case.
        def orig_argv():
            # type: () -> List[str]
            return []


def __re_exec__(
    python,  # type: str
    python_args,  # type: List[str]
    *extra_python_args  # type: str
):
    # type: (...) -> NoReturn

    argv = [python]
    argv.extend(python_args)
    argv.extend(extra_python_args)

    os.execv(python, argv + sys.argv[1:])


__SHOULD_EXECUTE__ = __name__ == "__main__"


def __entry_point_from_filename__(filename):
    # type: (str) -> str

    # Either the entry point is "__main__" and we're in execute mode or "__pex__/__init__.py"
    # and we're in import hook mode.
    entry_point = os.path.dirname(filename)
    if __SHOULD_EXECUTE__:
        return entry_point
    return os.path.dirname(entry_point)


__INSTALLED_FROM__ = "__PEX_EXE__"


def __ensure_pex_installed__(
    pex,  # type: str
    pex_root,  # type: str
    pex_hash,  # type: str
    python_args,  # type: List[str]
):
    # type: (...) -> Optional[str]

    from pex.layout import ensure_installed
    from pex.tracer import TRACER

    installed_location = ensure_installed(pex=pex, pex_root=pex_root, pex_hash=pex_hash)
    if not __SHOULD_EXECUTE__ or pex == installed_location:
        return installed_location

    # N.B.: This is read upon re-exec below to point sys.argv[0] back to the original pex
    # before unconditionally scrubbing the env var and handing off to user code.
    os.environ[__INSTALLED_FROM__] = pex

    TRACER.log(
        "Executing installed PEX for {pex} at {installed_location}".format(
            pex=pex, installed_location=installed_location
        )
    )
    __re_exec__(sys.executable, python_args, installed_location)


def __maybe_run_venv__(
    pex,  # type: str
    pex_root,  # type: str
    pex_hash,  # type: str
    has_interpreter_constraints,  # type: bool
    hermetic_venv_scripts,  # type: bool
    pex_path,  # type: Tuple[str, ...]
    python_args,  # type: List[str]
):
    # type: (...) -> Optional[str]

    from pex.executables import is_exe
    from pex.tracer import TRACER
    from pex.variables import venv_dir

    venv_root_dir = venv_dir(
        pex_file=pex,
        pex_root=pex_root,
        pex_hash=pex_hash,
        has_interpreter_constraints=has_interpreter_constraints,
        pex_path=pex_path,
    )
    venv_pex = os.path.join(venv_root_dir, "pex")
    if not __SHOULD_EXECUTE__ or not is_exe(venv_pex):
        # Code in bootstrap_pex will (re)create the venv after selecting the correct
        # interpreter.
        return venv_root_dir

    TRACER.log("Executing venv PEX for {pex} at {venv_pex}".format(pex=pex, venv_pex=venv_pex))
    venv_python = os.path.join(venv_root_dir, "bin", "python")
    if hermetic_venv_scripts:
        __re_exec__(venv_python, python_args, "-sE", venv_pex)
    else:
        __re_exec__(venv_python, python_args, venv_pex)


def boot(
    bootstrap_dir,  # type: str
    pex_root,  # type: str
    pex_hash,  # type: str
    has_interpreter_constraints,  # type: bool
    hermetic_venv_scripts,  # type: bool
    pex_path,  # type: Tuple[str, ...]
    is_venv,  # type: bool
    inject_python_args,  # type: Tuple[str, ...]
):
    # type: (...) -> Tuple[Any, bool, bool]

    entry_point = None  # type: Optional[str]
    __file__ = globals().get("__file__")
    __loader__ = globals().get("__loader__")
    if __file__ is not None and os.path.exists(__file__):
        entry_point = __entry_point_from_filename__(__file__)
    elif __loader__ is not None:
        if hasattr(__loader__, "archive"):
            entry_point = __loader__.archive
        elif hasattr(__loader__, "get_filename"):
            # The source of the loader interface has changed over the course of Python history
            # from `pkgutil.ImpLoader` to `importlib.abc.Loader`, but the existence and
            # semantics of `get_filename` has remained constant; so we just check for the
            # method.
            entry_point = __entry_point_from_filename__(__loader__.get_filename())

    if entry_point is None:
        sys.stderr.write("Could not launch python executable!\\n")
        return 2, True, False

    python_args = list(inject_python_args)  # type: List[str]
    orig_args = orig_argv()
    if orig_args:
        for index, arg in enumerate(orig_args[1:], start=1):
            if os.path.exists(arg) and os.path.samefile(entry_point, arg):
                python_args.extend(orig_args[1:index])
                break

    installed_from = os.environ.pop(__INSTALLED_FROM__, None)
    if installed_from:
        if os.path.isfile(installed_from):
            sys.argv[0] = installed_from
        else:
            pex_exe = os.path.join(installed_from, "pex")
            if os.path.isfile(pex_exe):
                sys.argv[0] = pex_exe

    sys.path[0] = os.path.abspath(sys.path[0])
    sys.path.insert(0, os.path.abspath(os.path.join(entry_point, bootstrap_dir)))

    venv_dir = None  # type: Optional[str]
    if not installed_from:
        os.environ["PEX"] = os.path.realpath(entry_point)
        from pex.variables import ENV, Variables

        pex_root = Variables.PEX_ROOT.value_or(ENV, pex_root)

        if not ENV.PEX_TOOLS and Variables.PEX_VENV.value_or(ENV, is_venv):
            venv_dir = __maybe_run_venv__(
                pex=entry_point,
                pex_root=pex_root,
                pex_hash=pex_hash,
                has_interpreter_constraints=has_interpreter_constraints,
                hermetic_venv_scripts=hermetic_venv_scripts,
                pex_path=ENV.PEX_PATH or pex_path,
                python_args=python_args,
            )
        entry_point = __ensure_pex_installed__(
            pex=entry_point, pex_root=pex_root, pex_hash=pex_hash, python_args=python_args
        )
        if entry_point is None:
            # This means we re-exec'd ourselves already; so this just appeases type checking.
            return 0, True, False
    else:
        os.environ["PEX"] = os.path.realpath(installed_from)

    from pex.globals import Globals
    from pex.pex_bootstrapper import bootstrap_pex

    result = bootstrap_pex(
        entry_point, python_args=python_args, execute=__SHOULD_EXECUTE__, venv_dir=venv_dir
    )
    should_exit = __SHOULD_EXECUTE__ and "PYTHONINSPECT" not in os.environ
    is_globals = isinstance(result, Globals)
    return result, should_exit, is_globals
