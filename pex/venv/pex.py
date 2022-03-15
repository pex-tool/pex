# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import errno
import itertools
import os
import shutil
from collections import defaultdict, Counter
from textwrap import dedent

from pex.third_party.pkg_resources import Distribution

from pex import pex_warnings
from pex.common import safe_mkdir, pluralize, chmod_plus_x
from pex.compatibility import is_valid_python_identifier
from pex.environment import PEXEnvironment
from pex.orderedset import OrderedSet
from pex.pep_376 import InstalledWheel, LoadError
from pex.pex import PEX
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper
from pex.venv.bin_path import BinPath
from pex.venv.install_scope import InstallScope
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    import typing
    from typing import Tuple, Iterator, Optional, Iterable


def _relative_symlink(
    src,  # type: str
    dst,  # type: str
):
    # type: (...) -> None
    dst_parent = os.path.dirname(dst)
    rel_src = os.path.relpath(src, dst_parent)
    os.symlink(rel_src, dst)


# N.B.: We can't use shutil.copytree since we copy from multiple source locations to the same site
# packages directory destination. Since we're forced to stray from the stdlib here, support for
# hardlinks is added to provide a measurable speed up and disk space savings when possible.
def _copytree(
    src,  # type: str
    dst,  # type: str
    exclude=(),  # type: Tuple[str, ...]
    symlink=False,  # type: bool
):
    # type: (...) -> Iterator[Tuple[str, str]]
    safe_mkdir(dst)
    link = True
    for root, dirs, files in os.walk(src, topdown=True, followlinks=True):
        if src == root:
            dirs[:] = [d for d in dirs if d not in exclude]
            files[:] = [f for f in files if f not in exclude]

        for path, is_dir in itertools.chain(
            zip(dirs, itertools.repeat(True)), zip(files, itertools.repeat(False))
        ):
            src_entry = os.path.join(root, path)
            dst_entry = os.path.join(dst, os.path.relpath(src_entry, src))
            if not is_dir:
                yield src_entry, dst_entry
            try:
                if symlink:
                    _relative_symlink(src_entry, dst_entry)
                elif is_dir:
                    os.mkdir(dst_entry)
                else:
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

        if symlink:
            # Once we've symlinked the top-level directories and files, we've "copied" everything.
            return


class CollisionError(Exception):
    """Indicates multiple distributions provided the same file when merging a PEX into a venv."""


def populate_venv(
    venv,  # type: Virtualenv
    pex,  # type: PEX
    bin_path=BinPath.FALSE,  # type: BinPath.Value
    python=None,  # type: Optional[str]
    collisions_ok=True,  # type: bool
    symlink=False,  # type: bool
    scope=InstallScope.ALL,  # type: InstallScope.Value
):
    # type: (...) -> str

    venv_python = python or venv.interpreter.binary
    shebang = "#!{} -sE".format(venv_python)

    provenance = defaultdict(list)

    def record_provenance(src_to_dst):
        # type: (Iterable[Tuple[str, str]]) -> None
        for src, dst in src_to_dst:
            provenance[dst].append(src)

    if scope in (InstallScope.ALL, InstallScope.DEPS_ONLY):
        record_provenance(_populate_deps(venv, pex, venv_python, symlink))

    if scope in (InstallScope.ALL, InstallScope.SOURCE_ONLY):
        record_provenance(_populate_sources(venv, pex, shebang, venv_python, bin_path))

    potential_collisions = {dst: srcs for dst, srcs in provenance.items() if len(srcs) > 1}
    if potential_collisions:
        collisions = {}
        for dst, srcs in potential_collisions.items():
            contents = defaultdict(list)
            for src in srcs:
                contents[CacheHelper.hash(src)].append(src)
            if len(contents) > 1:
                collisions[dst] = contents

        if collisions:
            venv_bin_dir = os.path.dirname(python) if python else venv.bin_dir
            venv_dir = os.path.dirname(venv_bin_dir) if python else venv.venv_dir
            message_lines = [
                "Encountered {collision} building venv at {venv_dir} from {pex}:".format(
                    collision=pluralize(collisions, "collision"), venv_dir=venv_dir, pex=pex.path()
                )
            ]
            for index, (dst, contents) in enumerate(collisions.items(), start=1):
                message_lines.append(
                    "{index}. {dst} was provided by:\n\t{srcs}".format(
                        index=index,
                        dst=dst,
                        srcs="\n\t".join(
                            "sha1:{fingerprint} -> {srcs}".format(
                                fingerprint=fingerprint, srcs=", ".join(srcs)
                            )
                            for fingerprint, srcs in contents.items()
                        ),
                    )
                )
            message = "\n".join(message_lines)
            if not collisions_ok:
                raise CollisionError(message)
            pex_warnings.warn(message)

    return shebang


def _populate_legacy_dist(
    venv,  # type: Virtualenv
    dist,  # type: Distribution
    symlink=False,  # type: bool
    rel_extra_path=None,  # type: Optional[str]
):
    dst = os.path.join(
        venv.site_packages_dir, rel_extra_path
    ) if rel_extra_path else venv.site_packages_dir

    # N.B.: We do not include the top_level __pycache__ for a dist since there may be
    # multiple dists with top-level modules. In that case, one dists top-level __pycache__
    # would be symlinked and all dists with top-level modules would have the .pyc files for
    # those modules be mixed in. For sanity's sake, and since ~no dist provides more than
    # just 1 top-level module, we keep .pyc anchored to their associated dists when shared
    # and accept the cost of re-compiling top-level modules in each venv that uses them.
    for src, dst in _copytree(
        src=dist.location, dst=dst, exclude=("bin", "__pycache__"), symlink=symlink
    ):
        yield src, dst

    dist_bin_dir = os.path.join(dist.location, "bin")
    if os.path.isdir(dist_bin_dir):
        for src, dst in _copytree(src=dist_bin_dir, dst=venv.bin_dir, symlink=symlink):
            yield src, dst


def _populate_deps(
    venv,  # type: Virtualenv
    pex,  # type: PEX
    venv_python,  # type: str
    symlink=False,  # type: bool
):
    # type: (...) -> Iterator[Tuple[str, str]]

    # Since the pex distributions are all materialized to ~/.pex/installed_wheels, which we control,
    # we can optionally symlink to take advantage of sharing generated *.pyc files for auto-venvs
    # created in ~/.pex/venvs.
    top_level_packages = Counter()  # type: typing.Counter[str]
    rel_extra_paths = OrderedSet()  # type: OrderedSet[str]
    for dist in pex.resolve():
        rel_extra_path = None
        if symlink:
            # In the symlink case, in order to share all generated *.pyc files for a given
            # distribution, we need to be able to have each contribution to a namespace package get
            # its own top-level symlink. This requires adjoining extra sys.path entries beyond
            # site-packages. We create the minimal number of extra such paths to satisfy all
            # namespace package contributing dists for a given namespace package using a .pth
            # file (See: https://docs.python.org/3/library/site.html).
            #
            # For example, given a PEX that depends on 3 different distributions contributing to the
            # foo namespace package, we generate a layout like:
            #   site-packages/
            #     foo -> ../../../../../../installed_wheels/<hash>/foo-1.0-py3-none-any.why/foo
            #     foo-1.0.dist-info -> ../../../../../../installed_wheels/<hash>/foo1/foo-1.0.dist-info
            #     pex-ns-pkgs/
            #       1/
            #           foo -> ../../../../../../../../installed_wheels/<hash>/foo2-3.0-py3-none-any.whl/foo
            #           foo2-3.0.dist-info -> ../../../../../../../../installed_wheels/<hash>/foo2-3.0-py3-none-any.whl/foo2-3.0.dist-info
            #       2/
            #           foo -> ../../../../../../../../installed_wheels/<hash>/foo3-2.5-py3-none-any.whl/foo
            #           foo3-2.5.dist-info -> ../../../../../../../../installed_wheels/<hash>/foo3-2.5-py3-none-any.whl/foo2-2.5.dist-info
            #     pex-ns-pkgs.pth
            #
            # Here site-packages/pex-ns-pkgs.pth contains:
            #   pex-ns-pkgs/1
            #   pex-ns-pkgs/2
            packages = [
                name
                for name in os.listdir(dist.location)
                if name not in ("bin", "__pycache__")
                   and is_valid_python_identifier(name)
                   and os.path.isdir(os.path.join(dist.location, name))
            ]
            count = max(top_level_packages[package] for package in packages) if packages else 0
            if count > 0:
                rel_extra_path = os.path.join("pex-ns-pkgs", str(count))
                rel_extra_paths.add(rel_extra_path)
            top_level_packages.update(packages)

        try:
            installed_wheel = InstalledWheel.load(dist.location)
            for src, dst in installed_wheel.reinstall(
                venv, symlink=symlink, rel_extra_path=rel_extra_path
            ):
                yield src, dst
        except LoadError:
            for src, dst in _populate_legacy_dist(
                venv, dist, symlink=symlink, rel_extra_path=rel_extra_path
            ):
                yield src, dst

    if rel_extra_paths:
        with open(os.path.join(venv.site_packages_dir, "pex-ns-pkgs.pth"), "w") as fp:
            for rel_extra_path in rel_extra_paths:
                if venv.interpreter.version[0] == 2:
                    # Unfortunately, the declarative relative paths style does not appear to work
                    # for Python 2.7. The sys.path entries are added, but they are not in turn
                    # scanned for their own .pth additions. We work around by abusing the spec for
                    # import lines taking inspiration from setuptools generated .pth files.
                    print(
                        "import os, site, sys; "
                        "site.addsitedir("
                        "os.path.join(sys._getframe(1).f_locals['sitedir'], {sitedir!r})"
                        ")".format(sitedir=rel_extra_path),
                        file=fp,
                    )
                else:
                    print(rel_extra_path, file=fp)

    # 3. Re-write any (console) scripts to use the venv Python.
    for script in venv.rewrite_scripts(python=venv_python, python_args="-sE"):
        TRACER.log("Re-writing {}".format(script))


def _populate_sources(
    venv,  # type: Virtualenv
    pex,  # type: PEX
    shebang,  # type: str
    venv_python,  # type: str
    bin_path,  # type: BinPath.Value
):
    # type: (...) -> Iterator[Tuple[str, str]]

    # We want the venv at rest to reflect the PEX it was created from at rest; as such we use the
    # PEX's at-rest PEX-INFO to perform the layout. The venv can then be executed with various PEX
    # environment variables in-play that it respects (e.g.: PEX_EXTRA_SYS_PATH, PEX_INTERPRETER,
    # PEX_MODULE, etc.).
    pex_info = pex.pex_info(include_env_overrides=False)

    # Since the pex.path() is ~always outside our control (outside ~/.pex), we copy all PEX user
    # sources into the venv.
    for src, dst in _copytree(
        src=PEXEnvironment.mount(pex.path()).path,
        dst=venv.site_packages_dir,
        exclude=(
            pex_info.internal_cache, pex_info.bootstrap, "__main__.py", "__pycache__", pex_info.PATH
        ),
        symlink=False,
    ):
        yield src, dst

    with open(os.path.join(venv.venv_dir, pex_info.PATH), "w") as fp:
        fp.write(pex_info.dump())

    # 2. Add a __main__ to the root of the venv for running the venv dir like a loose PEX dir
    # and a main.py for running as a script.
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

            pex_file = os.environ.get("PEX", None)
            if pex_file:
                try:
                    from setproctitle import setproctitle

                    setproctitle("{{python}} {{pex_file}} {{args}}".format(
                        python=sys.executable, pex_file=pex_file, args=" ".join(sys.argv[1:]))
                    )
                except ImportError:
                    pass

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
                    "PEX_EMIT_WARNINGS",
                    # This is used by the vendoring system.
                    "__PEX_UNVENDORED__",
                    # This is _not_ used (it is ignored), but it's present under CI and simplest to
                    # add an exception for here and not warn about in CI runs.
                    "_PEX_TEST_PYENV_ROOT",
                    # These are used by Pex's Pip venv to provide foreign platform support and work
                    # around https://github.com/pypa/pip/issues/10050:
                    "_PEX_PATCHED_MARKERS_FILE",
                    "_PEX_PATCHED_TAGS_FILE",
                    # These are used by Pex's Pip venv to implement universal locks.
                    "_PEX_SKIP_MARKERS",
                    "_PEX_PYTHON_VERSIONS_FILE",
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
