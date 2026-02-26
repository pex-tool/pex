# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import os
import sys

TYPE_CHECKING = False

if TYPE_CHECKING:
    from types import CodeType
    from typing import Any, Dict, Iterable, List, Mapping, NoReturn, Optional, Tuple, Union

_PY2_EXEC_FUNCTION = """
def exec_function(ast, globals_map):
    locals_map = globals_map
    exec ast in globals_map, locals_map
    return locals_map
"""

if sys.version_info[0] == 2:

    def exec_function(
        ast,  # type: CodeType
        globals_map,  # type: Dict[str, Any]
    ):
        raise AssertionError("Expected this function to be re-defined at runtime.")

    # This will result in `exec_function` being re-defined at runtime.
    eval(compile(_PY2_EXEC_FUNCTION, "<exec_function>", "exec"))
else:

    def exec_function(
        ast,  # type: CodeType
        globals_map,  # type: Dict[str, Any]
    ):
        locals_map = globals_map
        exec (ast, globals_map, locals_map)
        return locals_map


if sys.platform == "win32":

    def safe_execv(argv):
        # type: (List[str]) -> NoReturn
        import subprocess

        sys.exit(subprocess.call(args=argv))

else:

    def safe_execv(argv):
        # type: (List[str]) -> NoReturn
        os.execv(argv[0], argv)


class Error(str):
    pass


def _resolve_resource_path(
    name,  # type: str
    resource,  # type: str
):
    # type: (...) -> Union[str, Error]

    rel_path = os.path.normpath(os.path.join(*resource.split("/")))
    if os.path.isabs(resource) or rel_path.startswith(os.pardir):
        return Error(
            "The following resource binding spec is invalid: {name}={resource}\n"
            "The resource path {resource} must be relative to the `sys.path`.".format(
                name=name, resource=resource
            )
        )

    for entry in sys.path:
        value = os.path.join(entry, rel_path)
        if os.path.isfile(value):
            return value

    return Error(
        "There was no resource file {resource} found on the `sys.path` corresponding to "
        "the given resource binding spec `{name}={resource}`".format(resource=resource, name=name)
    )


def boot(
    shebang_python,  # type: str
    venv_bin_dir,  # type: str
    bin_path,  # type: str
    strip_pex_env,  # type: bool
    bind_resource_paths,  # type: Iterable[Tuple[str, str]]
    inject_env,  # type: Iterable[Tuple[str, str]]
    inject_args,  # type: List[str]
    entry_point,  # type: Optional[str]
    script,  # type: Optional[str]
    hermetic_re_exec,  # type: Optional[str]
):
    # type: (...) -> None

    venv_dir = os.path.abspath(os.path.dirname(__file__))
    venv_bin_dir = os.path.join(venv_dir, venv_bin_dir)
    python = os.path.join(venv_bin_dir, os.path.basename(shebang_python))

    def iter_valid_venv_pythons():
        # Allow for both the known valid venv pythons and their fully resolved venv path
        # version in the case their parent directories contain symlinks.
        for python_binary in (python, shebang_python):
            yield python_binary
            yield os.path.join(
                os.path.realpath(os.path.dirname(python_binary)), os.path.basename(python_binary)
            )

    def sys_executable_paths():
        exe = sys.executable
        executables = {exe}
        while os.path.islink(exe):
            exe = os.readlink(exe)
            if not os.path.isabs(exe):
                exe = os.path.join(venv_bin_dir, exe)

            if os.path.dirname(exe) == venv_bin_dir and exe not in executables:
                executables.add(exe)
            else:
                # We've either followed relative links inside the bin/ dir out of the bin
                # dir to the original venv seed Python binary or we've walked around a loop
                # of symlinks once; either way, we've found all valid venv python binaries.
                break
        return executables

    def maybe_log(*message):
        if "PEX_VERBOSE" in os.environ:
            print(*message, file=sys.stderr)

    current_interpreter_blessed_env_var = "_PEX_SHOULD_EXIT_VENV_REEXEC"
    if not os.environ.pop(
        current_interpreter_blessed_env_var, None
    ) and sys_executable_paths().isdisjoint(iter_valid_venv_pythons()):
        maybe_log("Re-exec'ing from", sys.executable)
        os.environ[current_interpreter_blessed_env_var] = "1"
        argv = [python]
        if hermetic_re_exec:
            argv.append(hermetic_re_exec)
        argv.extend(sys.argv)
        safe_execv(argv)

    pex_file = os.environ.get("__PEX_EXE__") or os.environ.get("PEX")
    if pex_file:
        pex_file_path = os.path.realpath(pex_file)
        if os.path.isfile(pex_file_path):
            sys.argv[0] = pex_file_path
        else:
            pex_exe = os.path.join(pex_file_path, "pex")
            if os.path.isfile(pex_exe):
                sys.argv[0] = pex_exe
        os.environ["PEX"] = pex_file_path
        try:
            from setproctitle import setproctitle  # type: ignore[import]

            setproctitle(
                "{python} {pex_file} {args}".format(
                    python=sys.executable, pex_file=pex_file, args=" ".join(sys.argv[1:])
                )
            )
        except ImportError:
            pass

    ignored_pex_env_vars = [
        "{}={}".format(name, value)
        for name, value in os.environ.items()
        if name.startswith(("PEX_", "_PEX_", "__PEX_"))
        and name
        not in (
            # These are used inside this script / the PEX_EXTRA_SYS_PATH.pth site-packages
            # file.
            "_PEX_SHOULD_EXIT_VENV_REEXEC",
            "PEX_EXTRA_SYS_PATH",
            "PEX_VENV_BIN_PATH",
            "PEX_INTERPRETER",
            "PEX_INTERPRETER_HISTORY",
            "PEX_INTERPRETER_HISTORY_FILE",
            "PEX_SCRIPT",
            "PEX_MODULE",
            # This is used when loading ENV (Variables()):
            "PEX_IGNORE_RCFILES",
            # And ENV is used to access these during PEX bootstrap when delegating here via
            # a --venv mode PEX file.
            "PEX_ROOT",
            "PEX_VENV",
            "PEX_PATH",
            "PEX_PYTHON",
            "PEX_PYTHON_PATH",
            "PEX_VERBOSE",
            "PEX_EMIT_WARNINGS",
            "PEX_MAX_INSTALL_JOBS",
            # This is used by the vendoring system.
            "__PEX_UNVENDORED__",
            # These are _not_ used at runtime, but are present under testing / CI and
            # simplest to add an exception for here and not warn about in CI runs.
            "_PEX_CACHE_WINDOWS_STUBS_DIR",
            "_PEX_FETCH_WINDOWS_STUBS_BEARER",
            "_PEX_HTTP_SERVER_TIMEOUT",
            "_PEX_PEXPECT_TIMEOUT",
            "_PEX_PIP_VERSION",
            "_PEX_PIP_ADHOC_VERSION",
            "_PEX_PIP_ADHOC_REQUIRES_PYTHON",
            "_PEX_PIP_ADHOC_BUILD_SYSTEM_REQUIRES",
            "_PEX_PIP_ADHOC_REQUIREMENT",
            "_PEX_REQUIRES_PYTHON",
            "_PEX_TEST_DEV_ROOT",
            "_PEX_TEST_POS_ARGS",
            "_PEX_TEST_PROJECT_DIR",
            "_PEX_USE_PIP_CONFIG",
            # This is used by Pex's Pip to inject runtime patches dynamically.
            "_PEX_PIP_RUNTIME_PATCHES_PACKAGE",
            # These are used by Pex's Pip venv to provide foreign platform support, universal lock
            # support and work around https://github.com/pypa/pip/issues/10050.
            "_PEX_INTERPRETER_IMPLEMENTATION",
            "_PEX_PATCHED_MARKERS_FILE",
            "_PEX_PATCHED_TAGS_FILE",
            # These are used by Pex's Pip venv to implement universal locks.
            "_PEX_PYTHON_VERSIONS_FILE",
            "_PEX_UNIVERSAL_TARGET_FILE",
            # This is used to implement Pex --exclude and --override support.
            "_PEX_DEP_CONFIG_FILE",
            # This is used to implement --source support.
            "_PEX_REPOS_CONFIG_FILE",
            # This is used as an experiment knob for atomic_directory locking.
            "_PEX_FILE_LOCK_STYLE",
            # This is used in the scie binding command for ZIPAPP PEXes.
            "_PEX_SCIE_INSTALLED_PEX_DIR",
            # This is used to override PBS distribution URLs in lazy PEX scies.
            "PEX_BOOTSTRAP_URLS",
            # This is used to support `pex3 cache {prune,purge}`.
            "_PEX_CACHE_ACCESS_LOCK",
            # This is used to support cleanup of temporary PEX_ROOTs on exit.
            "_PEX_ROOT_FALLBACK",
            # This is used to support concurrent Pex test suite runs.
            "_PEX_LOCKED_PROJECT_DIR",
        )
    ]
    if ignored_pex_env_vars:
        maybe_log(
            "Ignoring the following environment variables in Pex venv mode:\n"
            "{ignored_env_vars}".format(ignored_env_vars="\n".join(sorted(ignored_pex_env_vars)))
        )

    os.environ["VIRTUAL_ENV"] = venv_dir

    bin_path = os.environ.get("PEX_VENV_BIN_PATH", bin_path)
    if bin_path != "false":
        PATH = os.environ.get("PATH", "").split(os.pathsep)
        if bin_path == "prepend":
            PATH.insert(0, venv_bin_dir)
        elif bin_path == "append":
            PATH.append(venv_bin_dir)
        else:
            print(
                "PEX_VENV_BIN_PATH must be one of 'false', 'prepend' or 'append', given: "
                "{!r}".format(bin_path),
                file=sys.stderr,
            )
            sys.exit(1)
        os.environ["PATH"] = os.pathsep.join(PATH)

    PEX_EXEC_OVERRIDE_KEYS = ("PEX_INTERPRETER", "PEX_SCRIPT", "PEX_MODULE")
    pex_overrides = {key: os.environ[key] for key in PEX_EXEC_OVERRIDE_KEYS if key in os.environ}
    if len(pex_overrides) > 1:
        print(
            "Can only specify one of {overrides}; found: {found}".format(
                overrides=", ".join(PEX_EXEC_OVERRIDE_KEYS),
                found=" ".join("{}={}".format(k, v) for k, v in pex_overrides.items()),
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    is_exec_override = len(pex_overrides) == 1

    pex_interpreter_history = os.environ.get("PEX_INTERPRETER_HISTORY")
    pex_interpreter_history_file = os.environ.get("PEX_INTERPRETER_HISTORY_FILE")
    if strip_pex_env:
        for key in list(os.environ):
            if key.startswith("PEX_"):
                if key == "PEX_EXTRA_SYS_PATH":
                    # We always want sys.path additions to propagate so that the venv PEX
                    # acts like a normal Python interpreter where sys.path seen in
                    # subprocesses is the same as the sys.executable in the parent process.
                    os.environ["__PEX_EXTRA_SYS_PATH__"] = os.environ["PEX_EXTRA_SYS_PATH"]
                del os.environ[key]

    for name, value in inject_env:
        os.environ.setdefault(name, value)

    for name, resource in bind_resource_paths:
        resource_path = _resolve_resource_path(name, resource)
        if isinstance(resource_path, Error):
            sys.exit(resource_path)
        os.environ[name] = resource_path

    class Namespace(object):
        def __init__(
            self,
            seed=(),  # type: Union[Mapping[str, Any], Iterable[Tuple[str, Any]]]
            safe=False,  # type: bool
            **kwargs  # type: Any
        ):
            # type: (...) -> None
            self.__dict__.update(seed)
            self.__dict__.update(kwargs)
            self._safe = safe

        def __getattr__(self, key):
            # type: (str) -> Any
            return self._value(key)

        def __getitem__(self, key):
            # type: (str) -> Any
            return self._value(key)

        def _value(self, key):
            # type: (str) -> Any
            if self._safe:
                return self.__dict__.get(key, "")
            return self.__dict__[key]

    replacements = Namespace(env=Namespace(os.environ, safe=True))

    pex_script = pex_overrides.get("PEX_SCRIPT") if pex_overrides else script
    if pex_script:
        script_path = os.path.join(venv_bin_dir, pex_script)
        safe_execv([script_path] + sys.argv[1:])

    pex_interpreter = pex_overrides.get("PEX_INTERPRETER", "").lower() in ("1", "true")
    entry_point = None if pex_interpreter else pex_overrides.get("PEX_MODULE", entry_point)
    if not entry_point:
        # A Python interpreter always inserts the CWD at the head of the sys.path.
        # See https://docs.python.org/3/library/sys.html#sys.path
        sys.path.insert(0, "")

        args = sys.argv[1:]

        python_options = []
        for index, arg in enumerate(args):
            # Check if the arg is an expected startup arg
            if arg != "-" and arg.startswith("-") and not arg.startswith(("--", "-c", "-m")):
                python_options.append(arg)
            else:
                args = args[index:]
                break
        else:
            # All the args were python options
            args = []

        # The pex was called with Python interpreter options, so we need to re-exec to
        # respect those:
        if not args or python_options or "PYTHONINSPECT" in os.environ:
            python = sys.executable
            cmdline = [python] + python_options
            inspect = "PYTHONINSPECT" in os.environ or any(
                arg.startswith("-") and not arg.startswith("--") and "i" in arg
                for arg in python_options
            )
            if not args:
                if pex_interpreter_history:
                    os.environ["PEX_INTERPRETER_HISTORY"] = pex_interpreter_history
                if pex_interpreter_history_file:
                    os.environ["PEX_INTERPRETER_HISTORY_FILE"] = pex_interpreter_history_file
                cmdline.append(os.path.join(os.path.dirname(__file__), "pex-repl"))
            elif not inspect:
                # We're not interactive; so find the installed (unzipped) PEX entry point.
                cmdline.append(__file__)
            cmdline.extend(args)
            maybe_log(
                "Re-executing with Python interpreter options: "
                "cmdline={cmdline!r}".format(cmdline=" ".join(cmdline))
            )
            safe_execv(cmdline)

        arg = args[0]
        if arg == "-m":
            if len(args) < 2:
                print("Argument expected for the -m option", file=sys.stderr)
                sys.exit(2)
            entry_point = args[1]
            sys.argv = args[1:]
            # Fall through to entry_point handling below.
        else:
            filename = arg
            sys.argv = args
            if arg == "-c":
                if len(args) < 2:
                    print("Argument expected for the -c option", file=sys.stderr)
                    sys.exit(2)
                filename = "-c <cmd>"
                content = args[1]
                sys.argv = ["-c"] + args[2:]
            elif arg == "-":
                content = sys.stdin.read()
            else:
                file_path = arg if os.path.isfile(arg) else os.path.join(arg, "__main__.py")
                with open(file_path) as fp:
                    content = fp.read()

            ast = compile(content, filename, "exec", flags=0, dont_inherit=1)
            globals_map = globals().copy()
            globals_map["__name__"] = "__main__"
            globals_map["__file__"] = filename
            exec_function(ast, globals_map)
            sys.exit(0)

    if not is_exec_override:
        sys.argv[1:1] = [arg.format(pex=replacements) for arg in inject_args]

    module_name, _, function = entry_point.partition(":")
    if not function:
        import runpy

        runpy.run_module(module_name, run_name="__main__", alter_sys=True)
    else:
        import importlib

        module = importlib.import_module(module_name)
        # N.B.: Functions may be hung off top-level objects in the module namespace,
        # e.g.: Class.method; so we drill down through any attributes to the final function
        # object.
        root_object, _, chained_access = function.partition(".")
        func = getattr(module, root_object)
        if chained_access:
            for attr in chained_access.split("."):
                func = getattr(func, attr)
        sys.exit(func())
