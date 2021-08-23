# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import errno
import os
import shutil
import zipfile
from argparse import ArgumentParser, Namespace
from collections import defaultdict
from textwrap import dedent

from pex import pex_warnings
from pex.common import chmod_plus_x, pluralize, safe_mkdir
from pex.environment import PEXEnvironment
from pex.pex import PEX
from pex.tools.command import Command, Error, Ok, Result
from pex.tools.commands.virtualenv import PipUnavailableError, Virtualenv
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.venv_bin_path import BinPath

if TYPE_CHECKING:
    from typing import Iterable, Iterator, Optional, Tuple


# N.B.: We can't use shutil.copytree since we copy from multiple source locations to the same site
# packages directory destination. Since we're forced to stray from the stdlib here, support for
# hardlinks is added to provide a measurable speed up and disk space savings when possible.
def _copytree(
    src,  # type: str
    dst,  # type: str
    exclude=(),  # type: Tuple[str, ...]
):
    # type: (...) -> Iterator[Tuple[str, str]]
    safe_mkdir(dst)
    link = True
    for root, dirs, files in os.walk(src, topdown=True, followlinks=False):
        if src == root:
            dirs[:] = [d for d in dirs if d not in exclude]
            files[:] = [f for f in files if f not in exclude]

        for d in dirs:
            try:
                os.mkdir(os.path.join(dst, os.path.relpath(os.path.join(root, d), src)))
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise e

        for f in files:
            src_entry = os.path.join(root, f)
            dst_entry = os.path.join(dst, os.path.relpath(src_entry, src))
            yield src_entry, dst_entry
            try:
                # We only try to link regular files since linking a symlink on Linux can produce
                # another symlink, which leaves open the possibility the src_entry target could
                # later go missing leaving the dst_entry dangling.
                if link and not os.path.islink(src_entry):
                    try:
                        os.link(src_entry, dst_entry)
                        continue
                    except OSError as e:
                        if e.errno != errno.EXDEV:
                            raise e
                        link = False
                shutil.copy(src_entry, dst_entry)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise e


class CollisionError(Exception):
    """Indicates multiple distributions provided the same file when merging a PEX into a venv."""


def populate_venv_with_pex(
    venv,  # type: Virtualenv
    pex,  # type: PEX
    bin_path=BinPath.FALSE,  # type: BinPath.Value
    python=None,  # type: Optional[str]
    collisions_ok=True,  # type: bool
):
    # type: (...) -> str

    venv_python = python or venv.interpreter.binary
    venv_bin_dir = os.path.dirname(python) if python else venv.bin_dir
    venv_dir = os.path.dirname(venv_bin_dir) if python else venv.venv_dir

    # 1. Populate the venv with the PEX contents.
    provenance = defaultdict(list)

    def record_provenance(src_to_dst):
        # type: (Iterable[Tuple[str, str]]) -> None
        for src, dst in src_to_dst:
            provenance[dst].append(src)

    pex_info = pex.pex_info()
    if zipfile.is_zipfile(pex.path()):
        record_provenance(
            PEXEnvironment(pex.path()).explode_code(
                venv.site_packages_dir, exclude=("__main__.py", pex_info.PATH)
            )
        )
    else:
        record_provenance(
            _copytree(
                src=pex.path(),
                dst=venv.site_packages_dir,
                exclude=(pex_info.internal_cache, pex_info.bootstrap, "__main__.py", pex_info.PATH),
            )
        )

    with open(os.path.join(venv.venv_dir, pex_info.PATH), "w") as fp:
        fp.write(pex_info.dump())

    for dist in pex.resolve():
        record_provenance(
            _copytree(src=dist.location, dst=venv.site_packages_dir, exclude=("bin",))
        )
        dist_bin_dir = os.path.join(dist.location, "bin")
        if os.path.isdir(dist_bin_dir):
            record_provenance(_copytree(dist_bin_dir, venv.bin_dir))

    collisions = {dst: srcs for dst, srcs in provenance.items() if len(srcs) > 1}
    if collisions:
        message_lines = [
            "Encountered {collision} building venv at {venv_dir} from {pex}:".format(
                collision=pluralize(collisions, "collision"), venv_dir=venv_dir, pex=pex.path()
            )
        ]
        for index, (dst, srcs) in enumerate(collisions.items(), start=1):
            message_lines.append(
                "{index}. {dst} was provided by:\n\t{srcs}".format(
                    index=index, dst=dst, srcs="\n\t".join(srcs)
                )
            )
        message = "\n".join(message_lines)
        if not collisions_ok:
            raise CollisionError(message)
        pex_warnings.warn(message)

    # 2. Add a __main__ to the root of the venv for running the venv dir like a loose PEX dir
    # and a main.py for running as a script.
    shebang = "#!{} -sE".format(venv_python)
    main_contents = dedent(
        """\
        {shebang}

        if __name__ == "__main__":
            import os
            import sys

            venv_dir = os.path.abspath(os.path.dirname(__file__))
            venv_bin_dir = os.path.join(venv_dir, "bin")
            shebang_python = {shebang_python!r}
            python = os.path.join(venv_bin_dir, os.path.basename(shebang_python))

            def iter_valid_venv_pythons():
                # Allow for both the known valid venv pythons and their fully resolved venv path
                # version in the case their parent directories contain symlinks.
                for python_binary in (python, shebang_python):
                    yield python_binary
                    yield os.path.join(
                        os.path.realpath(os.path.dirname(python_binary)),
                        os.path.basename(python_binary)
                    )

            current_interpreter_blessed_env_var = "_PEX_SHOULD_EXIT_VENV_REEXEC"
            if (
                not os.environ.pop(current_interpreter_blessed_env_var, None)
                and sys.executable not in tuple(iter_valid_venv_pythons())
            ):
                sys.stderr.write("Re-execing from {{}}\\n".format(sys.executable))
                os.environ[current_interpreter_blessed_env_var] = "1"
                os.execv(python, [python, "-sE"] + sys.argv)

            ignored_pex_env_vars = [
                "{{}}={{}}".format(name, value)
                for name, value in os.environ.items()
                if name.startswith(("PEX_", "_PEX_", "__PEX_")) and name not in (
                    # These are used inside this script.
                    "_PEX_SHOULD_EXIT_VENV_REEXEC",
                    "PEX_EXTRA_SYS_PATH",
                    "PEX_VENV_BIN_PATH",
                    "PEX_INTERPRETER",
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
                    "__PEX_EXE__",
                    "__PEX_UNVENDORED__",
                    # This is _not_ used (it is ignored), but it's present under CI and simplest to
                    # add an exception for here and not warn about in CI runs.
                    "_PEX_TEST_PYENV_ROOT",
                    # This is used by Pex's Pip venv to work around
                    # https://github.com/pypa/pip/issues/10050:
                    "_PEX_PATCHED_MARKERS_FILE",
                )
            ]
            if ignored_pex_env_vars:
                sys.stderr.write(
                    "Ignoring the following environment variables in Pex venv mode:\\n"
                    "{{}}\\n\\n".format(
                        os.linesep.join(sorted(ignored_pex_env_vars))
                    )
                )

            os.environ["VIRTUAL_ENV"] = venv_dir
            sys.path.extend(os.environ.get("PEX_EXTRA_SYS_PATH", "").split(os.pathsep))

            bin_path = os.environ.get("PEX_VENV_BIN_PATH", {bin_path!r})
            if bin_path != "false":
                PATH = os.environ.get("PATH", "").split(os.pathsep)
                if bin_path == "prepend":
                    PATH.insert(0, venv_bin_dir)
                elif bin_path == "append":
                    PATH.append(venv_bin_dir)
                else:
                    sys.stderr.write(
                        "PEX_VENV_BIN_PATH must be one of 'false', 'prepend' or 'append', given: "
                        "{{!r}}\\n".format(
                            bin_path
                        )
                    )
                    sys.exit(1)
                os.environ["PATH"] = os.pathsep.join(PATH)

            PEX_EXEC_OVERRIDE_KEYS = ("PEX_INTERPRETER", "PEX_SCRIPT", "PEX_MODULE")
            pex_overrides = {{
                key: os.environ.get(key) for key in PEX_EXEC_OVERRIDE_KEYS if key in os.environ
            }}
            if len(pex_overrides) > 1:
                sys.stderr.write(
                    "Can only specify one of {{overrides}}; found: {{found}}\\n".format(
                        overrides=", ".join(PEX_EXEC_OVERRIDE_KEYS),
                        found=" ".join("{{}}={{}}".format(k, v) for k, v in pex_overrides.items())
                    )
                )
                sys.exit(1)
            if {strip_pex_env!r}:
                for key in list(os.environ):
                    if key.startswith("PEX_"):
                        del os.environ[key]

            pex_script = pex_overrides.get("PEX_SCRIPT") if pex_overrides else {script!r}
            if pex_script:
                script_path = os.path.join(venv_bin_dir, pex_script)
                os.execv(script_path, [script_path] + sys.argv[1:])

            pex_interpreter = pex_overrides.get("PEX_INTERPRETER", "").lower() in ("1", "true")
            PEX_INTERPRETER_ENTRYPOINT = "code:interact"
            entry_point = (
                PEX_INTERPRETER_ENTRYPOINT
                if pex_interpreter
                else pex_overrides.get("PEX_MODULE", {entry_point!r} or PEX_INTERPRETER_ENTRYPOINT)
            )
            if entry_point == PEX_INTERPRETER_ENTRYPOINT and len(sys.argv) > 1:
                args = sys.argv[1:]
                arg = args[0]
                if arg == "-m":
                    if len(args) < 2:
                        sys.stderr.write("Argument expected for the -m option\\n")
                        sys.exit(2)
                    entry_point = module = args[1]
                    sys.argv = args[1:]
                    # Fall through to entry_point handling below.
                else:
                    filename = arg
                    sys.argv = args
                    if arg == "-c":
                        if len(args) < 2:
                            sys.stderr.write("Argument expected for the -c option\\n")
                            sys.exit(2)
                        filename = "-c <cmd>"
                        content = args[1]
                        sys.argv = ["-c"] + args[2:]
                    elif arg == "-":
                        content = sys.stdin.read()
                    else:
                        with open(arg) as fp:
                            content = fp.read()

                    ast = compile(content, filename, "exec", flags=0, dont_inherit=1)
                    globals_map = globals().copy()
                    globals_map["__name__"] = "__main__"
                    globals_map["__file__"] = filename
                    locals_map = globals_map
                    {exec_ast}
                    sys.exit(0)

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
                namespace, func = module, None
                for attr in function.split("."):
                    func = namespace = getattr(namespace, attr)
                sys.exit(func())
        """.format(
            shebang=shebang,
            shebang_python=venv_python,
            bin_path=bin_path,
            strip_pex_env=pex_info.strip_pex_env,
            entry_point=pex_info.entry_point,
            script=pex_info.script,
            exec_ast=(
                "exec ast in globals_map, locals_map"
                if venv.interpreter.version[0] == 2
                else "exec(ast, globals_map, locals_map)"
            ),
        )
    )
    with open(venv.join_path("__main__.py"), "w") as fp:
        fp.write(main_contents)
    chmod_plus_x(fp.name)
    os.symlink(os.path.basename(fp.name), venv.join_path("pex"))

    # 3. Re-write any (console) scripts to use the venv Python.
    for script in venv.rewrite_scripts(python=venv_python, python_args="-sE"):
        TRACER.log("Re-writing {}".format(script))

    return shebang


class Venv(Command):
    """Creates a venv from the PEX file."""

    def add_arguments(self, parser):
        # type: (ArgumentParser) -> None
        parser.add_argument(
            "venv",
            nargs=1,
            metavar="PATH",
            help="The directory to create the virtual environment in.",
        )
        parser.add_argument(
            "-b",
            "--bin-path",
            choices=[choice.value for choice in BinPath.values],
            default=BinPath.FALSE.value,
            help="Add the venv bin dir to the PATH in the __main__.py script.",
        )
        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            default=False,
            help="If the venv directory already exists, overwrite it.",
        )
        parser.add_argument(
            "--collisions-ok",
            action="store_true",
            default=False,
            help=(
                "Don't error if population of the venv encounters distributions in the PEX file "
                "with colliding files, just emit a warning."
            ),
        )
        parser.add_argument(
            "-p",
            "--pip",
            action="store_true",
            default=False,
            help="Add pip to the venv.",
        )
        parser.add_argument(
            "--copies",
            action="store_true",
            default=False,
            help="Create the venv using copies of system files instead of symlinks",
        )
        parser.add_argument(
            "--compile",
            action="store_true",
            default=False,
            help="Compile all `.py` files in the venv.",
        )

    def run(
        self,
        pex,  # type: PEX
        options,  # type: Namespace
    ):
        # type: (...) -> Result

        venv_dir = options.venv[0]
        venv = Virtualenv.create(
            venv_dir, interpreter=pex.interpreter, force=options.force, copies=options.copies
        )
        populate_venv_with_pex(
            venv,
            pex,
            bin_path=BinPath.for_value(options.bin_path),
            collisions_ok=options.collisions_ok,
        )
        if options.pip:
            try:
                venv.install_pip()
            except PipUnavailableError as e:
                return Error(
                    "The virtual environment was successfully created, but Pip was not "
                    "installed:\n{}".format(e)
                )
        if options.compile:
            pex.interpreter.execute(["-m", "compileall", venv_dir])
        return Ok()
