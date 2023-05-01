# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import errno
import itertools
import os
import shutil
import subprocess
from collections import Counter, OrderedDict, defaultdict
from textwrap import dedent

from pex import layout, pex_warnings
from pex.common import chmod_plus_x, pluralize, safe_mkdir
from pex.compatibility import is_valid_python_identifier
from pex.dist_metadata import Distribution
from pex.environment import PEXEnvironment
from pex.orderedset import OrderedSet
from pex.pep_376 import InstalledWheel, LoadError
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.result import Error
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper
from pex.venv.bin_path import BinPath
from pex.venv.install_scope import InstallScope
from pex.venv.virtualenv import PipUnavailableError, Virtualenv

if TYPE_CHECKING:
    import typing
    from typing import DefaultDict, Iterable, Iterator, List, Optional, Tuple, Union


def find_dist(
    project_name,  # type: ProjectName
    dists,  # type: Iterable[Distribution]
):
    # type: (...) -> Optional[Version]
    for dist in dists:
        if project_name == dist.metadata.project_name:
            return dist.metadata.version
    return None


_PIP = ProjectName("pip")
_SETUPTOOLS = ProjectName("setuptools")


def ensure_pip_installed(
    venv,  # type: Virtualenv
    distributions,  # type: Iterable[Distribution]
    scope,  # type: InstallScope.Value
    collisions_ok,  # type: bool
    source,  # type: str
):
    # type: (...) -> Union[Version, Error]

    venv_pip_version = find_dist(_PIP, venv.iter_distributions())
    if venv_pip_version:
        TRACER.log(
            "The venv at {venv_dir} already has Pip {version} installed.".format(
                venv_dir=venv.venv_dir, version=venv_pip_version
            )
        )
    else:
        try:
            venv.install_pip()
        except PipUnavailableError as e:
            return Error(
                "The virtual environment was successfully created, but Pip was not "
                "installed:\n{}".format(e)
            )
        venv_pip_version = find_dist(_PIP, venv.iter_distributions())
        if not venv_pip_version:
            return Error(
                "Failed to install pip into venv at {venv_dir}".format(venv_dir=venv.venv_dir)
            )

    if InstallScope.SOURCE_ONLY == scope:
        return venv_pip_version

    uninstall = OrderedDict()
    pex_pip_version = find_dist(_PIP, distributions)
    if pex_pip_version and pex_pip_version != venv_pip_version:
        uninstall[_PIP] = pex_pip_version

    venv_setuptools_version = find_dist(_SETUPTOOLS, venv.iter_distributions())
    if venv_setuptools_version:
        pex_setuptools_version = find_dist(_SETUPTOOLS, distributions)
        if pex_setuptools_version and venv_setuptools_version != pex_setuptools_version:
            uninstall[_SETUPTOOLS] = pex_setuptools_version

    if not uninstall:
        return venv_pip_version

    message = (
        "You asked for --pip to be installed in the venv at {venv_dir},\n"
        "but the {source} already contains:\n{distributions}"
    ).format(
        venv_dir=venv.venv_dir,
        source=source,
        distributions="\n".join(
            "{project_name} {version}".format(project_name=project_name, version=version)
            for project_name, version in uninstall.items()
        ),
    )
    if not collisions_ok:
        return Error(
            "{message}\nConsider re-running either without --pip or with --collisions-ok.".format(
                message=message
            )
        )

    pex_warnings.warn(
        "{message}\nUninstalling venv versions and using versions from the PEX.".format(
            message=message
        )
    )
    projects_to_uninstall = sorted(str(project_name) for project_name in uninstall)
    try:
        subprocess.check_call(
            args=[venv.interpreter.binary, "-m", "pip", "uninstall", "-y"] + projects_to_uninstall
        )
    except subprocess.CalledProcessError as e:
        return Error(
            "Failed to uninstall venv versions of {projects}: {err}".format(
                projects=" and ".join(projects_to_uninstall), err=e
            )
        )
    return pex_pip_version or venv_pip_version


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
# hardlinks is added to provide a measurable speed-up and disk space savings when possible.
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


class Provenance(object):
    @classmethod
    def create(
        cls,
        venv,  # type: Virtualenv
        python=None,  # type: Optional[str]
    ):
        # type: (...) -> Provenance
        venv_bin_dir = os.path.dirname(python) if python else venv.bin_dir
        venv_dir = os.path.dirname(venv_bin_dir) if python else venv.venv_dir

        venv_python = python or venv.interpreter.binary
        return cls(target_dir=venv_dir, target_python=venv_python)

    def __init__(
        self,
        target_dir,  # type: str
        target_python,  # type: str
    ):
        # type: (...) -> None
        self._target_dir = target_dir
        self._target_python = target_python
        self._provenance = defaultdict(list)  # type: DefaultDict[str, List[str]]

    @property
    def target_python(self):
        # type: () -> str
        return self._target_python

    def calculate_shebang(self, hermetic_scripts=True):
        # type: (bool) -> str

        shebang_argv = [self.target_python]
        python_args = _script_python_args(hermetic=hermetic_scripts)
        if python_args:
            shebang_argv.append(python_args)
        return "#!{shebang}".format(shebang=" ".join(shebang_argv))

    def record(self, src_to_dst):
        # type: (Iterable[Tuple[str, str]]) -> None
        for src, dst in src_to_dst:
            self._provenance[dst].append(src)

    def check_collisions(
        self,
        collisions_ok=False,  # type: bool
        source=None,  # type: Optional[str]
    ):
        # type: (...) -> None

        potential_collisions = {
            dst: srcs for dst, srcs in self._provenance.items() if len(srcs) > 1
        }
        if not potential_collisions:
            return

        collisions = {}
        for dst, srcs in potential_collisions.items():
            contents = defaultdict(list)
            for src in srcs:
                contents[CacheHelper.hash(src)].append(src)
            if len(contents) > 1:
                collisions[dst] = contents

        if not collisions:
            return

        message_lines = [
            "Encountered {collision} populating {target_dir}{source}:".format(
                collision=pluralize(collisions, "collision"),
                target_dir=self._target_dir,
                source=" from {source}".format(source=source) if source else "",
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


def _script_python_args(hermetic):
    # type: (bool) -> Optional[str]
    return "-sE" if hermetic else None


def _populate_flat_deps(
    dest_dir,  # type: str
    distributions,  # type: Iterable[Distribution]
    symlink=False,  # type: bool
):
    # type: (...) -> Iterator[Tuple[str, str]]
    for dist in distributions:
        try:
            installed_wheel = InstalledWheel.load(dist.location)
            for src, dst in installed_wheel.reinstall_flat(target_dir=dest_dir, symlink=symlink):
                yield src, dst
        except LoadError:
            for src, dst in _populate_legacy_dist(
                dest_dir=dest_dir, bin_dir=dest_dir, dist=dist, symlink=symlink
            ):
                yield src, dst


def populate_flat_distributions(
    dest_dir,  # type: str
    distributions,  # type: Iterable[Distribution]
    provenance,  # type: Provenance
    symlink=False,  # type: bool
):
    # type: (...) -> None

    provenance.record(
        _populate_flat_deps(dest_dir=dest_dir, distributions=distributions, symlink=symlink)
    )


def populate_venv_distributions(
    venv,  # type: Virtualenv
    distributions,  # type: Iterable[Distribution]
    provenance,  # type: Provenance
    symlink=False,  # type: bool
    hermetic_scripts=True,  # type: bool
):
    # type: (...) -> None

    provenance.record(
        _populate_venv_deps(
            venv=venv,
            distributions=distributions,
            venv_python=provenance.target_python,
            symlink=symlink,
            hermetic_scripts=hermetic_scripts,
        )
    )


def populate_flat_sources(
    dst,  # type: str
    pex,  # type: PEX
    provenance,  # type: Provenance
):
    provenance.record(_populate_sources(pex=pex, dst=dst))


def populate_venv_sources(
    venv,  # type: Virtualenv
    pex,  # type: PEX
    provenance,  # type: Provenance
    bin_path=BinPath.FALSE,  # type: BinPath.Value
    hermetic_scripts=True,  # type: bool
    shebang=None,  # type: Optional[str]
):
    # type: (...) -> str

    shebang = shebang or provenance.calculate_shebang(hermetic_scripts=hermetic_scripts)
    provenance.record(
        _populate_first_party(
            venv=venv,
            pex=pex,
            shebang=shebang,
            venv_python=provenance.target_python,
            bin_path=bin_path,
        )
    )
    return shebang


def populate_venv_from_pex(
    venv,  # type: Virtualenv
    pex,  # type: PEX
    bin_path=BinPath.FALSE,  # type: BinPath.Value
    python=None,  # type: Optional[str]
    collisions_ok=True,  # type: bool
    symlink=False,  # type: bool
    scope=InstallScope.ALL,  # type: InstallScope.Value
    hermetic_scripts=True,  # type: bool
):
    # type: (...) -> str

    provenance = Provenance.create(venv, python=python)
    shebang = provenance.calculate_shebang(hermetic_scripts=hermetic_scripts)

    if scope in (InstallScope.ALL, InstallScope.DEPS_ONLY):
        populate_venv_distributions(
            venv=venv,
            distributions=pex.resolve(),
            symlink=symlink,
            hermetic_scripts=hermetic_scripts,
            provenance=provenance,
        )

    if scope in (InstallScope.ALL, InstallScope.SOURCE_ONLY):
        populate_venv_sources(
            venv=venv,
            pex=pex,
            bin_path=bin_path,
            hermetic_scripts=hermetic_scripts,
            provenance=provenance,
            shebang=shebang,
        )

    provenance.check_collisions(collisions_ok, source="PEX at {pex}".format(pex=pex.path()))

    return shebang


def _populate_legacy_dist(
    dest_dir,  # type: str
    bin_dir,  # type: str
    dist,  # type: Distribution
    symlink=False,  # type: bool
):
    # N.B.: We do not include the top_level __pycache__ for a dist since there may be
    # multiple dists with top-level modules. In that case, one dists top-level __pycache__
    # would be symlinked and all dists with top-level modules would have the .pyc files for
    # those modules be mixed in. For sanity's sake, and since ~no dist provides more than
    # just 1 top-level module, we keep .pyc anchored to their associated dists when shared
    # and accept the cost of re-compiling top-level modules in each venv that uses them.
    for src, dst in _copytree(
        src=dist.location, dst=dest_dir, exclude=("bin", "__pycache__"), symlink=symlink
    ):
        yield src, dst

    dist_bin_dir = os.path.join(dist.location, "bin")
    if os.path.isdir(dist_bin_dir):
        for src, dst in _copytree(src=dist_bin_dir, dst=bin_dir, symlink=symlink):
            yield src, dst


def _populate_venv_deps(
    venv,  # type: Virtualenv
    distributions,  # type: Iterable[Distribution]
    venv_python,  # type: str
    symlink=False,  # type: bool
    hermetic_scripts=True,  # type: bool
):
    # type: (...) -> Iterator[Tuple[str, str]]

    # Since the pex distributions are all materialized to ~/.pex/installed_wheels, which we control,
    # we can optionally symlink to take advantage of sharing generated *.pyc files for auto-venvs
    # created in ~/.pex/venvs.
    top_level_packages = Counter()  # type: typing.Counter[str]
    rel_extra_paths = OrderedSet()  # type: OrderedSet[str]
    for dist in distributions:
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
            for src, dst in installed_wheel.reinstall_venv(
                venv, symlink=symlink, rel_extra_path=rel_extra_path
            ):
                yield src, dst
        except LoadError:
            dst = (
                os.path.join(venv.site_packages_dir, rel_extra_path)
                if rel_extra_path
                else venv.site_packages_dir
            )
            for src, dst in _populate_legacy_dist(
                dest_dir=dst, bin_dir=venv.bin_dir, dist=dist, symlink=symlink
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
    for script in venv.rewrite_scripts(
        python=venv_python, python_args=_script_python_args(hermetic=hermetic_scripts)
    ):
        TRACER.log("Re-writing {}".format(script))


def _populate_sources(
    pex,  # type: PEX
    dst,  # type: str
):
    # type: (...) -> Iterator[Tuple[str, str]]

    # Since the pex.path() is ~always outside our control (outside ~/.pex), we copy all PEX user
    # sources into the venv.
    for src, dst in _copytree(
        src=PEXEnvironment.mount(pex.path()).path,
        dst=dst,
        exclude=(
            "__main__.py",
            "__pex__",
            "__pycache__",
            layout.BOOTSTRAP_DIR,
            layout.DEPS_DIR,
            layout.PEX_INFO_PATH,
            layout.PEX_LAYOUT_PATH,
        ),
        symlink=False,
    ):
        yield src, dst


def _populate_first_party(
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

    for src, dst in _populate_sources(pex=pex, dst=venv.site_packages_dir):
        yield src, dst

    with open(os.path.join(venv.site_packages_dir, "PEX_EXTRA_SYS_PATH.pth"), "w") as fp:
        # N.B.: .pth import lines must be single lines: https://docs.python.org/3/library/site.html
        for env_var in "PEX_EXTRA_SYS_PATH", "__PEX_EXTRA_SYS_PATH__":
            print(
                "import os, sys; "
                "sys.path.extend("
                "entry for entry in os.environ.get('{env_var}', '').split(':') if entry"
                ")".format(env_var=env_var),
                file=fp,
            )

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

            def sys_executable_paths():
                exe = sys.executable
                executables = {{exe}}
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

            current_interpreter_blessed_env_var = "_PEX_SHOULD_EXIT_VENV_REEXEC"
            if (
                not os.environ.pop(current_interpreter_blessed_env_var, None)
                and sys_executable_paths().isdisjoint(iter_valid_venv_pythons())
            ):
                sys.stderr.write("Re-execing from {{}}\\n".format(sys.executable))
                os.environ[current_interpreter_blessed_env_var] = "1"
                argv = [python]
                if {hermetic_re_exec!r}:
                    argv.append("-sE")
                argv.extend(sys.argv)
                os.execv(python, argv)

            pex_file = os.environ.get("PEX", None)
            if pex_file:
                pex_file_path = os.path.realpath(pex_file)
                sys.argv[0] = pex_file_path
                os.environ["PEX"] = pex_file_path
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
                    # This is used by the vendoring system.
                    "__PEX_UNVENDORED__",
                    # These are _not_ used at runtime, but are present under CI and simplest to add
                    # an exception for here and not warn about in CI runs.
                    "_PEX_TEST_PYENV_ROOT",
                    "_PEX_PIP_VERSION",
                    # This is used by Pex's Pip to inject runtime patches dynamically.
                    "_PEX_PIP_RUNTIME_PATCHES_PACKAGE",
                    # These are used by Pex's Pip venv to provide foreign platform support and work
                    # around https://github.com/pypa/pip/issues/10050.
                    "_PEX_PATCHED_MARKERS_FILE",
                    "_PEX_PATCHED_TAGS_FILE",
                    # These are used by Pex's Pip venv to implement universal locks.
                    "_PEX_PYTHON_VERSIONS_FILE",
                    "_PEX_TARGET_SYSTEMS_FILE",
                    # This is used as an experiment knob for atomic_directory locking.
                    "_PEX_FILE_LOCK_STYLE",
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
            is_exec_override = len(pex_overrides) == 1

            pex_interpreter_history = os.environ.get(
                "PEX_INTERPRETER_HISTORY", "false"
            ).lower() in ("1", "true")
            pex_interpreter_history_file = os.environ.get(
                "PEX_INTERPRETER_HISTORY_FILE", os.path.join("~", ".python_history")
            )

            if {strip_pex_env!r}:
                for key in list(os.environ):
                    if key.startswith("PEX_"):
                        if key == "PEX_EXTRA_SYS_PATH":
                            # We always want sys.path additions to propagate so that the venv PEX
                            # acts like a normal Python interpreter where sys.path seen in
                            # subprocesses is the same as the sys.executable in the parent process.
                            os.environ["__PEX_EXTRA_SYS_PATH__"] = os.environ.get(
                                "PEX_EXTRA_SYS_PATH"
                            )
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

            if entry_point == PEX_INTERPRETER_ENTRYPOINT:
                # A Python interpreter always inserts the CWD at the head of the sys.path.
                # See https://docs.python.org/3/library/sys.html#sys.path
                sys.path.insert(0, "")

                if pex_interpreter_history:
                    import atexit
                    import readline

                    histfile = os.path.expanduser(pex_interpreter_history_file)
                    try:
                        readline.read_history_file(histfile)
                        readline.set_history_length(1000)
                    except OSError:
                        pass

                    atexit.register(readline.write_history_file, histfile)

            if entry_point == PEX_INTERPRETER_ENTRYPOINT and len(sys.argv) > 1:
                args = sys.argv[1:]

                python_options = []
                for index, arg in enumerate(args):
                    # Check if the arg is an expected startup arg
                    if arg.startswith("-") and arg not in ("-", "-c", "-m"):
                        python_options.append(arg)
                    else:
                        args = args[index:]
                        break

                # The pex was called with Python interpreter options, so we need to re-exec to
                # respect those:
                if python_options:
                    # Find the installed (unzipped) PEX entry point.
                    main = sys.modules.get("__main__")
                    if not main or not main.__file__:
                        # N.B.: This should never happen.
                        sys.stderr.write(
                            "Unable to resolve PEX __main__ module file: {{}}\\n".format(main)
                        )
                        sys.exit(1)

                    python = sys.executable
                    cmdline = [python] + python_options + [main.__file__] + args
                    sys.stderr.write(
                        "Re-executing with Python interpreter options: "
                        "cmdline={{cmdline!r}}\\n".format(cmdline=" ".join(cmdline))
                    )
                    os.execv(python, cmdline)

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
                        file_path = arg if os.path.isfile(arg) else os.path.join(arg, "__main__.py")
                        with open(file_path) as fp:
                            content = fp.read()

                    ast = compile(content, filename, "exec", flags=0, dont_inherit=1)
                    globals_map = globals().copy()
                    globals_map["__name__"] = "__main__"
                    globals_map["__file__"] = filename
                    locals_map = globals_map
                    {exec_ast}
                    sys.exit(0)

            if not is_exec_override:
                for name, value in {inject_env!r}:
                    os.environ.setdefault(name, value)
                sys.argv[1:1] = {inject_args!r}

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
            inject_env=tuple(pex_info.inject_env.items()),
            inject_args=list(pex_info.inject_args),
            entry_point=pex_info.entry_point,
            script=pex_info.script,
            exec_ast=(
                "exec ast in globals_map, locals_map"
                if venv.interpreter.version[0] == 2
                else "exec(ast, globals_map, locals_map)"
            ),
            hermetic_re_exec=pex_info.venv_hermetic_scripts,
        )
    )
    with open(venv.join_path("__main__.py"), "w") as fp:
        fp.write(main_contents)
    chmod_plus_x(fp.name)
    os.symlink(os.path.basename(fp.name), venv.join_path("pex"))
