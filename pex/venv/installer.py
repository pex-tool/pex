# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import inspect
import os
import subprocess
from collections import Counter, OrderedDict, defaultdict
from textwrap import dedent

from pex import layout, pex_warnings, repl
from pex.cache import access as cache_access
from pex.common import CopyMode, iter_copytree, pluralize
from pex.compatibility import is_valid_python_identifier
from pex.dist_metadata import Distribution
from pex.environment import PEXEnvironment
from pex.executables import chmod_plus_x
from pex.fs import safe_symlink
from pex.installed_wheel import InstalledWheel
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.os import WINDOWS
from pex.pep_427 import reinstall_flat, reinstall_venv
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.pex_info import PexInfo
from pex.result import Error
from pex.sysconfig import SCRIPT_DIR
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper
from pex.venv import venv_pex
from pex.venv.bin_path import BinPath
from pex.venv.install_scope import InstallScope
from pex.venv.virtualenv import PipUnavailableError, Virtualenv
from pex.wheel import Wheel, WheelMetadataLoadError

if TYPE_CHECKING:
    import typing
    from typing import (
        Container,
        DefaultDict,
        Iterable,
        Iterator,
        List,
        Optional,
        Sequence,
        Text,
        Tuple,
        Union,
    )

    import attr  # vendor:skip
else:
    from pex.third_party import attr


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
            venv.ensure_pip()
        except PipUnavailableError as e:
            return Error(
                "The virtual environment was successfully created, but Pip was not "
                "installed:\n{}".format(e)
            )
        venv_pip_version = find_dist(_PIP, venv.iter_distributions(rescan=True))
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


class CollisionError(Exception):
    """Indicates multiple distributions provided the same file when merging a PEX into a venv."""


class Provenance(object):
    @classmethod
    def create(
        cls,
        venv,  # type: Virtualenv
        shebang_python=None,  # type: Optional[str]
    ):
        # type: (...) -> Provenance
        return cls(
            target_dir=venv.venv_dir, target_python=venv.interpreter, shebang_python=shebang_python
        )

    def __init__(
        self,
        target_dir,  # type: str
        target_python,  # type: PythonInterpreter
        shebang_python=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        self._target_dir = target_dir
        self._target_python = target_python
        self._shebang_python = shebang_python
        self._provenance = defaultdict(list)  # type: DefaultDict[Text, List[Text]]

    @property
    def target_dir(self):
        # type: () -> str
        return self._target_dir

    @property
    def target_python(self):
        # type: () -> str
        return self._shebang_python or self._target_python.binary

    def calculate_shebang(self, hermetic_scripts=True):
        # type: (bool) -> str

        shebang_argv = [self.target_python]
        if hermetic_scripts:
            shebang_argv.append(self._target_python.hermetic_args)
        return "#!{shebang}".format(shebang=" ".join(shebang_argv))

    def record(self, src_to_dst):
        # type: (Iterable[Tuple[Text, Text]]) -> None
        for src, dst in src_to_dst:
            self._provenance[dst].append(src)

    def _equal_asts(self, srcs):
        # type: (Iterable[Text]) -> bool
        args = [
            self._target_python.binary,
            "-c",
            dedent(
                """\
                import ast
                import sys


                def equal_asts(srcs):
                    normalized = None
                    for src in srcs:
                        with open(src) as fp:
                            content = ast.unparse(ast.parse(fp.read(), fp.name))
                            if normalized is None:
                                normalized = content
                            elif content != normalized:
                                return False
                    return True


                if __name__ == "__main__":
                    srcs = sys.argv[1:]
                    if sys.version_info[:2] >= (3, 9) and equal_asts(srcs):
                        sys.exit(0)
                    sys.exit(len(srcs))    
                """
            ),
        ]  # type: List[Text]
        args.extend(srcs)
        return subprocess.call(args) == 0

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
            if len(contents) > 1 and (
                os.path.basename(dst) != "__init__.py" or not self._equal_asts(srcs)
            ):
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


def _populate_flat_deps(
    dest_dir,  # type: str
    distributions,  # type: Iterable[Distribution]
    copy_mode=CopyMode.LINK,  # type: CopyMode.Value
):
    # type: (...) -> Iterator[Tuple[Text, Text]]
    for dist in distributions:
        try:
            installed_wheel = InstalledWheel.load(dist.location)
            for src, dst in reinstall_flat(
                installed_wheel=installed_wheel, target_dir=dest_dir, copy_mode=copy_mode
            ):
                yield src, dst
        except InstalledWheel.LoadError:
            for src, dst in _populate_legacy_dist(
                dest_dir=dest_dir, bin_dir=dest_dir, dist=dist, copy_mode=copy_mode
            ):
                yield src, dst


def populate_flat_distributions(
    dest_dir,  # type: str
    distributions,  # type: Iterable[Distribution]
    provenance,  # type: Provenance
    copy_mode=CopyMode.LINK,  # type: CopyMode.Value
):
    # type: (...) -> None

    provenance.record(
        _populate_flat_deps(dest_dir=dest_dir, distributions=distributions, copy_mode=copy_mode)
    )


def populate_venv_distributions(
    venv,  # type: Virtualenv
    distributions,  # type: Iterable[Distribution]
    provenance,  # type: Provenance
    copy_mode=CopyMode.LINK,  # type: CopyMode.Value
    hermetic_scripts=True,  # type: bool
    top_level_source_packages=(),  # type: Iterable[str]
):
    # type: (...) -> None

    provenance.record(
        _populate_venv_deps(
            venv=venv,
            distributions=distributions,
            venv_python=provenance.target_python,
            copy_mode=CopyMode.LINK if copy_mode is CopyMode.SYMLINK and WINDOWS else copy_mode,
            hermetic_scripts=hermetic_scripts,
            top_level_source_packages=top_level_source_packages,
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
            target_dir=provenance.target_dir,
            venv=venv,
            pex=pex,
            shebang=shebang,
            venv_python=provenance.target_python,
            bin_path=bin_path,
        )
    )
    return shebang


def _iter_top_level_packages(
    path,  # type: str
    excludes=(SCRIPT_DIR, "__pycache__"),  # type: Container[str]
):
    # type: (...) -> Iterator[str]
    for name in os.listdir(path):
        if (
            name not in excludes
            and is_valid_python_identifier(name)
            and os.path.isdir(os.path.join(path, name))
        ):
            yield name


def iter_top_level_source_packages(pex):
    # type: (PEX) -> Iterator[str]
    pex_sources = PEXSources.mount(pex)
    for path in _iter_top_level_packages(pex_sources.path, excludes=pex_sources.excludes):
        yield path


def populate_venv_from_pex(
    venv,  # type: Virtualenv
    pex,  # type: PEX
    bin_path=BinPath.FALSE,  # type: BinPath.Value
    shebang_python=None,  # type: Optional[str]
    collisions_ok=True,  # type: bool
    copy_mode=CopyMode.LINK,  # type: CopyMode.Value
    scope=InstallScope.ALL,  # type: InstallScope.Value
    hermetic_scripts=True,  # type: bool
):
    # type: (...) -> str

    provenance = Provenance.create(venv, shebang_python=shebang_python)
    shebang = provenance.calculate_shebang(hermetic_scripts=hermetic_scripts)
    top_level_source_packages = tuple(iter_top_level_source_packages(pex))

    if scope in (InstallScope.ALL, InstallScope.DEPS_ONLY):
        populate_venv_distributions(
            venv=venv,
            distributions=pex.resolve(),
            copy_mode=copy_mode,
            hermetic_scripts=hermetic_scripts,
            provenance=provenance,
            top_level_source_packages=top_level_source_packages,
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
    copy_mode=CopyMode.LINK,  # type: CopyMode.Value
):
    # N.B.: We do not include the top_level __pycache__ for a dist since there may be
    # multiple dists with top-level modules. In that case, one dists top-level __pycache__
    # would be symlinked and all dists with top-level modules would have the .pyc files for
    # those modules be mixed in. For sanity's sake, and since ~no dist provides more than
    # just 1 top-level module, we keep .pyc anchored to their associated dists when shared
    # and accept the cost of re-compiling top-level modules in each venv that uses them.
    for src, dst in iter_copytree(
        src=dist.location, dst=dest_dir, exclude=(SCRIPT_DIR, "__pycache__"), copy_mode=copy_mode
    ):
        yield src, dst

    dist_bin_dir = os.path.join(dist.location, SCRIPT_DIR)
    if os.path.isdir(dist_bin_dir):
        for src, dst in iter_copytree(src=dist_bin_dir, dst=bin_dir, copy_mode=copy_mode):
            yield src, dst


def _populate_venv_deps(
    venv,  # type: Virtualenv
    distributions,  # type: Iterable[Distribution]
    venv_python,  # type: str
    copy_mode=CopyMode.LINK,  # type: CopyMode.Value
    hermetic_scripts=True,  # type: bool
    top_level_source_packages=(),  # type: Iterable[str]
):
    # type: (...) -> Iterator[Tuple[Text, Text]]

    # Since the pex distributions are all materialized to <PEX_ROOT>/installed_wheels, which we
    # control, we can optionally symlink to take advantage of sharing generated *.pyc files for
    # auto-venvs created in <PEX_ROOT>/venvs.
    top_level_packages = Counter(top_level_source_packages)  # type: typing.Counter[str]
    rel_extra_paths = OrderedSet()  # type: OrderedSet[str]
    for dist in distributions:
        rel_extra_path = None
        if copy_mode is CopyMode.SYMLINK:
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
            packages = list(_iter_top_level_packages(dist.location))
            count = max(top_level_packages[package] for package in packages) if packages else 0
            if count > 0:
                rel_extra_path = os.path.join("pex-ns-pkgs", str(count))
                rel_extra_paths.add(rel_extra_path)
            top_level_packages.update(packages)

        try:
            installed_wheel = InstalledWheel.load(dist.location)
            for src, dst in reinstall_venv(
                installed_wheel=installed_wheel,
                venv=venv,
                copy_mode=copy_mode,
                rel_extra_path=rel_extra_path,
                hermetic_scripts=hermetic_scripts,
            ):
                yield src, dst
        except InstalledWheel.LoadError:
            try:
                wheel = Wheel.load(dist.location)
            except WheelMetadataLoadError:
                site_packages_dir = venv.site_packages_dir
            else:
                site_packages_dir = venv.purelib if wheel.root_is_purelib else venv.platlib
            dst = (
                os.path.join(site_packages_dir, rel_extra_path)
                if rel_extra_path
                else site_packages_dir
            )
            for src, dst in _populate_legacy_dist(
                dest_dir=dst, bin_dir=venv.bin_dir, dist=dist, copy_mode=copy_mode
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
        python=venv_python,
        python_args=venv.interpreter.hermetic_args if hermetic_scripts else None,
    ):
        TRACER.log("Re-writing {}".format(script))


@attr.s(frozen=True)
class PEXSources(object):
    @classmethod
    def mount(cls, pex):
        # type: (PEX) -> PEXSources
        return cls(
            path=PEXEnvironment.mount(pex.path()).path,
            excludes=(
                "__main__.py",
                "__pex__",
                "__pycache__",
                "pex",
                cache_access.LAST_ACCESS_FILE,
                layout.BOOTSTRAP_DIR,
                layout.DEPS_DIR,
                layout.PEX_INFO_PATH,
                layout.PEX_LAYOUT_PATH,
            ),
        )

    path = attr.ib()  # type: str
    excludes = attr.ib()  # type: Container[str]


def _populate_sources(
    pex,  # type: PEX
    dst,  # type: str
):
    # type: (...) -> Iterator[Tuple[Text, Text]]

    # Since the pex.path() is ~always outside our control (outside <PEX_ROOT>), we copy all PEX user
    # sources into the venv.
    pex_sources = PEXSources.mount(pex)
    for src, dest in iter_copytree(
        src=pex_sources.path,
        dst=dst,
        exclude=pex_sources.excludes,
        copy_mode=CopyMode.COPY,
    ):
        yield src, dest


def install_pex_main(
    target_dir,  # type: str
    venv,  # type: Virtualenv
    pex_info,  # type: PexInfo
    activated_dists,  # type: Sequence[Distribution]
    shebang,  # type: str
    venv_python,  # type: str
    bin_path,  # type: BinPath.Value
):
    # type: (...) -> None

    with open(os.path.join(venv.site_packages_dir, "PEX_EXTRA_SYS_PATH.pth"), "w") as fp:
        # N.B.: .pth import lines must be single lines: https://docs.python.org/3/library/site.html
        for env_var in "PEX_EXTRA_SYS_PATH", "__PEX_EXTRA_SYS_PATH__":
            print(
                "import os, sys; "
                "sys.path.extend("
                "entry for entry in os.environ.get('{env_var}', '').split({pathsep!r}) if entry"
                ")".format(env_var=env_var, pathsep=os.pathsep),
                file=fp,
            )

    with open(os.path.join(venv.venv_dir, pex_info.PATH), "w") as fp:
        fp.write(pex_info.dump())

    # Add a __main__ to the root of the venv for running the venv dir like a loose PEX dir
    # and a main.py for running as a script.
    with open(venv.join_path("__main__.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                {shebang}
                {code}


                if __name__ == "__main__":
                    import os
                    pex_root_fallback = os.environ.get("_PEX_ROOT_FALLBACK")
                    if pex_root_fallback:
                        import atexit
                        import shutil

                        atexit.register(shutil.rmtree, pex_root_fallback, True)

                    boot(
                        shebang_python={shebang_python!r},
                        venv_bin_dir={venv_bin_dir!r},
                        bin_path={bin_path!r},
                        strip_pex_env={strip_pex_env!r},
                        bind_resource_paths={bind_resource_paths!r},
                        inject_env={inject_env!r},
                        inject_args={inject_args!r},
                        entry_point={entry_point!r},
                        script={script!r},
                        hermetic_re_exec={hermetic_re_exec!r},
                    )
                """
            ).format(
                shebang=shebang,
                code=inspect.getsource(venv_pex).strip(),
                shebang_python=venv_python,
                venv_bin_dir=SCRIPT_DIR,
                bin_path=bin_path,
                strip_pex_env=pex_info.strip_pex_env,
                bind_resource_paths=tuple(pex_info.bind_resource_paths.items()),
                inject_env=tuple(pex_info.inject_env.items()),
                inject_args=list(pex_info.inject_args),
                entry_point=pex_info.entry_point,
                script=pex_info.script,
                hermetic_re_exec=(
                    venv.interpreter.hermetic_args if pex_info.venv_hermetic_scripts else None
                ),
            )
        )
    chmod_plus_x(fp.name)
    safe_symlink(os.path.basename(fp.name), venv.join_path("pex"))

    with open(venv.join_path("pex-repl"), "w") as fp:
        fp.write(
            repl.create_pex_repl_exe(
                shebang=shebang,
                pex_info=pex_info,
                activated_dists=activated_dists,
                pex=os.path.join(target_dir, "pex"),
                venv=True,
            )
        )
    chmod_plus_x(fp.name)


def _populate_first_party(
    target_dir,  # type: str
    venv,  # type: Virtualenv
    pex,  # type: PEX
    shebang,  # type: str
    venv_python,  # type: str
    bin_path,  # type: BinPath.Value
):
    # type: (...) -> Iterator[Tuple[Text, Text]]

    for src, dst in _populate_sources(pex=pex, dst=venv.site_packages_dir):
        yield src, dst

    # We want the venv at rest to reflect the PEX it was created from at rest; as such we use the
    # PEX's at-rest PEX-INFO to perform the layout. The venv can then be executed with various PEX
    # environment variables in-play that it respects (e.g.: PEX_EXTRA_SYS_PATH, PEX_INTERPRETER,
    # PEX_MODULE, etc.).
    pex_info = pex.pex_info(include_env_overrides=False)
    install_pex_main(
        target_dir=target_dir,
        venv=venv,
        pex_info=pex_info,
        activated_dists=tuple(pex.resolve()),
        shebang=shebang,
        venv_python=venv_python,
        bin_path=bin_path,
    )
