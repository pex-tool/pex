# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import errno
import os
import shutil
import zipfile
from argparse import ArgumentParser, Namespace
from textwrap import dedent

from pex import pex_builder, pex_warnings
from pex.common import chmod_plus_x, safe_mkdir
from pex.environment import PEXEnvironment
from pex.pex import PEX
from pex.tools.command import Command, Error, Ok, Result
from pex.tools.commands.virtualenv import PipUnavailableError, Virtualenv
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Tuple


# N.B.: We can't use shutil.copytree since we copy from multiple source locations to the same site
# packages directory destination. Since we're forced to stray from the stdlib here, support for
# hardlinks is added to provide a measurable speed up and disk space savings when possible.
def _copytree(
    src,  # type: str
    dst,  # type: str
    exclude=(),  # type: Tuple[str, ...]
    collisions_ok=False,  # type: bool
):
    # type: (...) -> None
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
            try:
                if link:
                    try:
                        os.link(src_entry, dst_entry)
                        continue
                    except OSError as e:
                        if e.errno != errno.EXDEV:
                            raise e
                        link = False
                shutil.copy(src_entry, dst_entry)
            except OSError as e:
                if e.errno == errno.EEXIST:
                    pex_warnings.warn(
                        "Failed to overwrite {} with {}: {}".format(dst_entry, src_entry, e)
                    )
                    if not collisions_ok:
                        raise e


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
            choices=("prepend", "append"),
            default=None,
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
                "with colliding files."
            ),
        )
        parser.add_argument(
            "-p",
            "--pip",
            action="store_true",
            default=False,
            help="Add pip to the venv.",
        )

    def run(
        self,
        pex,  # type: PEX
        options,  # type: Namespace
    ):
        # type: (...) -> Result

        # 0. Create an empty virtual environment to populate with the PEX code and dependencies.
        venv = Virtualenv.create(options.venv[0], interpreter=pex.interpreter, force=options.force)

        # 1. Populate the venv with the PEX contents.
        pex_info = pex.pex_info()
        if zipfile.is_zipfile(pex.path()):
            PEXEnvironment.explode_code(
                pex.path(), pex_info, venv.site_packages_dir, exclude=("__main__.py",)
            )
        else:
            _copytree(
                src=pex.path(),
                dst=venv.site_packages_dir,
                exclude=(pex_info.internal_cache, pex_builder.BOOTSTRAP_DIR, "__main__.py"),
            )

        for dist in pex.activate():
            _copytree(
                src=dist.location,
                dst=venv.site_packages_dir,
                exclude=("bin",),
                collisions_ok=options.collisions_ok,
            )
            dist_bin_dir = os.path.join(dist.location, "bin")
            if os.path.isdir(dist_bin_dir):
                _copytree(dist_bin_dir, venv.bin_dir, collisions_ok=options.collisions_ok)

        # 2. Add a __main__ to the root of the venv for running the venv dir like a loose PEX dir
        # and a main.py for running as a script.
        main_contents = dedent(
            """\
            #!{venv_python} -sE

            import os
            import sys

            python = {venv_python!r}
            if sys.executable != python:
                os.execv(python, [python, "-sE"] + sys.argv)

            os.environ["VIRTUAL_ENV"] = {venv_dir!r}
            sys.path.extend(os.environ.get("PEX_EXTRA_SYS_PATH", "").split(os.pathsep))

            bin_dir = {venv_bin_dir!r}
            bin_path = {bin_path!r}
            if bin_path:
                PATH = os.environ.get("PATH", "").split(os.pathsep)
                if bin_path == "prepend":
                    PATH = [bin_dir] + PATH
                else:
                    PATH.append(bin_dir)
                os.environ["PATH"] = os.pathsep.join(PATH)

            PEX_OVERRIDE_KEYS = ("PEX_INTERPRETER", "PEX_SCRIPT", "PEX_MODULE")
            pex_overrides = dict(
                (key, os.environ.pop(key)) for key in PEX_OVERRIDE_KEYS if key in os.environ
            )
            if len(pex_overrides) > 1:
                sys.stderr.write(
                    "Can only specify one of {{overrides}}; found: {{found}}\\n".format(
                        overrides=", ".join(PEX_OVERRIDE_KEYS),
                        found=" ".join("{{}}={{}}".format(k, v) for k, v in pex_overrides.items())
                    )
                )
                sys.exit(1)

            pex_script = pex_overrides.get("PEX_SCRIPT")
            if pex_script:
                script_path = os.path.join(bin_dir, pex_script)
                os.execv(script_path, [script_path] + sys.argv[1:])

            # TODO(John Sirois): Support `-c`, `-m` and `-` special modes when PEX_INTERPRETER is
            # activated like PEX files do: https://github.com/pantsbuild/pex/issues/1136
            pex_interpreter = pex_overrides.get("PEX_INTERPRETER", "").lower()
            entry_point = (
                "code:interact"
                if pex_interpreter in ("1", "true")
                else pex_overrides.get("PEX_MODULE", {entry_point!r} or "code:interact")
            )
            module_name, _, function = entry_point.partition(":")
            if not function:
                import runpy
                runpy.run_module(module_name, run_name="__main__")
            else:
                import importlib
                module = importlib.import_module(module_name)
                # N.B.: Functions may be hung off top-level objects in the module namespace,
                # e.g.: Class.method; so we drill down through any attributes to the final function
                # object.
                namespace, func = module, None
                for attr in function.split("."):
                    func = namespace = getattr(namespace, attr)
                func()
            """.format(
                venv_python=venv.interpreter.binary,
                bin_path=options.bin_path,
                venv_dir=venv.venv_dir,
                venv_bin_dir=venv.bin_dir,
                entry_point=pex_info.entry_point,
            )
        )
        with open(venv.join_path("__main__.py"), "w") as fp:
            fp.write(main_contents)
        chmod_plus_x(fp.name)
        os.symlink(os.path.basename(fp.name), venv.join_path("pex"))

        # 3. Re-write any (console) scripts to use the venv Python.
        for script in venv.rewrite_scripts(python_args="-sE"):
            TRACER.log("Re-writing {}".format(script))

        if options.pip:
            try:
                venv.install_pip()
            except PipUnavailableError as e:
                return Error(
                    "The virtual environment was successfully created, but Pip was not "
                    "installed:\n{}".format(e)
                )

        return Ok()
