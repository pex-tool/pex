# Copyright 2018 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import collections
import os
import subprocess
import sys
from textwrap import dedent

from pex.common import Chroot, is_pyc_dir, is_pyc_file, open_zip, safe_mkdtemp, touch
from pex.exceptions import production_assert
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Iterator, List, Optional, Sequence, Set, Text, Tuple, Union

    from pex.interpreter import PythonInterpreter

_PACKAGE_COMPONENTS = __name__.split(".")


class EnclosingZip(collections.namedtuple("EnclosingZip", ["path", "entries"])):
    pass


class VendorRoot(collections.namedtuple("VendorRoot", ["path", "enclosing_zip"])):
    pass


def _root():
    # type: () -> VendorRoot

    path = os.path.dirname(os.path.abspath(__file__))
    for _ in _PACKAGE_COMPONENTS:
        path = os.path.dirname(path)

    if os.path.isdir(path):
        return VendorRoot(path, enclosing_zip=None)

    import zipfile

    enclosing_zip = path
    while not zipfile.is_zipfile(enclosing_zip):
        parent = os.path.dirname(enclosing_zip)
        production_assert(
            parent != enclosing_zip,
            "Expected to find enclosing PEX or .whl zip for vendor root: {root}",
            root=path,
        )
        enclosing_zip = parent

    with open_zip(enclosing_zip) as zf:
        return VendorRoot(
            path, enclosing_zip=EnclosingZip(path=enclosing_zip, entries=frozenset(zf.namelist()))
        )


class VendorSpec(
    collections.namedtuple(
        "VendorSpec", ["key", "requirement", "import_path", "rewrite", "constrain", "constraints"]
    )
):
    """Represents a vendored distribution.

    :field str key: The distribution requirement key; e.g.: for a requirement of
      requests[security]==2.22.0 the key is 'requests'.
    :field str requirement: The distribution requirement string; e.g.: requests[security]==2.22.0.
    :field str import_path: A Python importable directory name to house the vendored distribution
      in.
    :field bool rewrite: Whether to re-write the distribution's imports for use with the
      `pex.third_party` importer.
    :field bool constrain: Whether to attempt to constrain the requirement via pip's --constraint
      mechanism.
    :field constraints: An optional list of extra constraints on the vendored requirement.
    NB: Vendored distributions should comply with the host distribution platform constraints. In the
    case of pex, which is a py2.py3 platform-agnostic wheel, vendored libraries should be as well.
    """

    ROOT, _ENCLOSING_ZIP = _root()

    _VENDOR_DIR = "_vendored"

    @classmethod
    def vendor_root(cls):
        return os.path.join(cls.ROOT, *(_PACKAGE_COMPONENTS + [cls._VENDOR_DIR]))

    @classmethod
    def pinned(
        cls,
        key,  # type: str
        version,  # type: str
        import_path=None,  # type: Optional[str]
        rewrite=True,  # type: bool
        constraints=(),  # type: Tuple[str, ...]
    ):
        return cls(
            key=key,
            requirement="{}=={}".format(key, version),
            import_path=import_path or key,
            rewrite=rewrite,
            constrain=True,
            constraints=constraints,
        )

    @classmethod
    def git(
        cls,
        repo,  # type: str
        commit,  # type: Text
        project_name,  # type: str
        import_path=None,  # type: Optional[str]
        prep_command=None,  # type: Optional[Sequence[str]]
        rewrite=True,  # type: bool
        constraints=(),  # type: Tuple[str, ...]
    ):
        requirement = "{project_name} @ git+{repo}@{commit}".format(
            repo=repo, commit=commit, project_name=project_name
        )
        if not prep_command:
            return cls(
                key=project_name,
                requirement=requirement,
                import_path=import_path or project_name,
                rewrite=rewrite,
                constrain=False,
                constraints=constraints,
            )

        class PreparedGit(VendorSpec):
            def prepare(self):
                clone_dir = safe_mkdtemp()
                subprocess.check_call(["git", "clone", "--depth", "1", repo, clone_dir])
                subprocess.check_call(
                    ["git", "fetch", "--depth", "1", "origin", commit], cwd=clone_dir
                )
                subprocess.check_call(["git", "checkout", commit], cwd=clone_dir)
                if prep_command:
                    subprocess.check_call(prep_command, cwd=clone_dir)
                return clone_dir

        return PreparedGit(
            key=project_name,
            requirement=requirement,
            import_path=import_path or project_name,
            rewrite=rewrite,
            constrain=False,
            constraints=constraints,
        )

    @property
    def _subpath_components(self):
        # type: () -> List[str]
        return [self._VENDOR_DIR, self.import_path]

    @property
    def relpath(self):
        # type: () -> str
        return self._relpath()

    def _relpath(self, sep=os.sep):
        # type: (str) -> str
        return sep.join(_PACKAGE_COMPONENTS + self._subpath_components)

    @property
    def target_dir(self):
        return os.path.join(self.ROOT, self.relpath)

    @property
    def exists(self):
        # type: () -> bool
        if self._ENCLOSING_ZIP:
            prefix = self.ROOT[len(self._ENCLOSING_ZIP.path) + len(os.sep) :]
            target_dir = prefix + "/" + self._relpath("/") + "/"
            return target_dir in self._ENCLOSING_ZIP.entries
        return os.path.isdir(self.target_dir)

    def prepare(self):
        return self.requirement

    def create_packages(self):
        """Create missing packages joining the vendor root to the base of the vendored distribution.

        For example, given a root at ``/home/jake/dev/pex-tool/pex`` and a vendored distribution
        at ``pex/vendor/_vendored/requests`` this method would create the following package files::

          pex/vendor/_vendored/__init__.py
          pex/vendor/_vendored/requests/__init__.py

        These package files allow for standard python importers to find vendored code via re-directs
        from a `PEP-302 <https://peps.python.org/pep-0302/>`_ importer like
        :class:`pex.third_party.VendorImporter`.
        """
        if not self.rewrite:
            # The extra package structure is only required by Pex for vendored code used via import
            # rewrites.

            # N.B.: Although we've historically early-returned here, the switch from flit to
            # setuptools for our build backend necessitates all vendored dists are seen as part of
            # the `pex` package tree by setuptools to get all vendored code properly included in
            # our distribution.
            # TODO(John Sirois): re-introduce early return once it is no longer foils our build
            #  process.
            pass

        for index, _ in enumerate(self._subpath_components):
            relpath = _PACKAGE_COMPONENTS + self._subpath_components[: index + 1] + ["__init__.py"]
            touch(os.path.join(self.ROOT, *relpath))


# N.B.: We're currently using a patched version of Pip 20.3.4 housed at
# https://github.com/pex-tool/pip/tree/pex/patches/generation-2.
# It has 5 substantive patches:
# 1.) https://github.com/pex-tool/pip/commit/06f462537c981116c763c1ba40cf40e9dd461bcf
#     The patch works around a bug in `pip download --constraint...` tracked at
#     https://github.com/pypa/pip/issues/9283 and fixed by https://github.com/pypa/pip/pull/9301
#     there and https://github.com/pex-tool/pip/pull/8 in our fork.
# 2.) https://github.com/pex-tool/pip/commit/386a54f097ece66775d0c7f34fd29bb596c6b0be
#     This is a cherry-pick of
#     https://github.com/pypa/pip/commit/00fb5a0b224cde08e3e5ca034247baadfb646468
#     (https://github.com/pypa/pip/pull/9533) from upstream that upgrades Pip's vendored
#     packaging to 20.9 to pick up support for mac universal2 wheels.
# 3.) https://github.com/pex-tool/pip/commit/00827ec9f4275a7786425cf006466c56f4cbd862
#     This is a cherry-pick of
#     https://github.com/pypa/pip/commit/601bcf82eccfbc15c1ff6cc735aafb2c9dab81a5
#     (https://github.com/pypa/pip/pull/12716) from upstream that fixes glibc version probing on
#     musl libc systems.
# 4.) https://github.com/pex-tool/pip/commit/48508331d331a1c326b0eccf4aac7476bc7ccca8
#     This sets up and runs the 1st semi-automated update of Pip's vendored certifi's cacert.pem
#     bringing it up to date with certifi 2024.7.4.
# 5.) https://github.com/pex-tool/pip/commit/963e2d662597bfa4298eb3c0c51bc113c4508a80
#     Automated update of Pip's vendored certifi's cacert.pem to that from certifi 2024.8.30.
# 6.) https://github.com/pex-tool/pip/commit/b83e4ef396a98599111e96bfdcd19c5f3ee7c5c7
#     Automated update of Pip's vendored certifi's cacert.pem to that from certifi 2024.12.14.
# 7.) https://github.com/pex-tool/pip/commit/6476fc578af434f379f245019c0f0d90da4ea883
#     Automated update of Pip's vendored certifi's cacert.pem to that from certifi 2025.1.31.
# 8.) https://github.com/pex-tool/pip/commit/0f4a71cca9ef0f686faf5fc9f89b1070cbe38598
#     Automated update of Pip's vendored certifi's cacert.pem to that from certifi 2025.4.26.
# 9.) https://github.com/pex-tool/pip/commit/098dc9ab34428f2af5ff5a0c9816ca3fc1511ea5
#     Automated update of Pip's vendored certifi's cacert.pem to that from certifi 2025.6.15.
# 10.) https://github.com/pex-tool/pip/commit/c91ae3c016c772b391dbd5dc5bdee3c9974ac0c7
#     Automated update of Pip's vendored certifi's cacert.pem to that from certifi 2025.7.9.
# 11.) https://github.com/pex-tool/pip/commit/6e5e5a40c9fc8622f5a3e4c9b173b018bf089cb9
#     Automated update of Pip's vendored certifi's cacert.pem to that from certifi 2025.7.14.
# 12.) https://github.com/pex-tool/pip/commit/21a4058f77f9864151510b725419206a2e5645ae
#     Automated update of Pip's vendored certifi's cacert.pem to that from certifi 2025.8.3.
# 13.) https://github.com/pex-tool/pip/commit/cef23bb7153ec49037d963e84fcad0f08880fbc5
#     Automated update of Pip's vendored certifi's cacert.pem to that from certifi 2025.10.5.
# 14.) https://github.com/pex-tool/pip/commit/c7cb62f1602c6c16e23ac0b4d3867818555eb7a7
#     Automated update of Pip's vendored certifi's cacert.pem to that from certifi 2025.11.12.
# 15.) https://github.com/pex-tool/pip/commit/31398c4540a9277d73a9c80ca2c653d82470b46e
#     Automated update of Pip's vendored certifi's cacert.pem to that from certifi 2026.1.4.
# 16.) https://github.com/pex-tool/pip/commit/d4e5b3c34e3ada747a87b307683726d53a8889b3
#     Automated update of Pip's vendored certifi's cacert.pem to that from certifi 2026.2.25.
PIP_SPEC = VendorSpec.git(
    repo="https://github.com/pex-tool/pip",
    commit="d4e5b3c34e3ada747a87b307683726d53a8889b3",
    project_name="pip",
    rewrite=False,
)


def iter_vendor_specs(
    filter_requires_python=None,  # type: Optional[Union[Tuple[int, int], PythonInterpreter]]
    filter_exists=True,  # type: bool
):
    # type: (...) -> Iterator[VendorSpec]
    """Iterate specifications for code vendored by pex.

    :param filter_requires_python: An optional interpreter (or its major and minor version) to
                                   tailor the vendor specs to.
    :param filter_exists: Whether to exclude vendor specs whose vendored content is not present.
    :return: An iterator over specs of all vendored code.
    """
    python_major_minor = None  # type: Optional[Tuple[int, int]]
    if filter_requires_python:
        python_major_minor = (
            filter_requires_python
            if isinstance(filter_requires_python, tuple)
            else filter_requires_python.version[:2]
        )

    yield VendorSpec.pinned("ansicolors", "1.1.8")
    yield VendorSpec.pinned("appdirs", "1.4.4")

    # We use this for a better @dataclass that is also Python2.7 and PyPy compatible.
    # N.B.: The `[dependency-groups] mypy` section in `pyproject.toml` should have its deps list
    # updated to reflect this attrs version.
    # This vcs version gets us the fix in https://github.com/python-attrs/attrs/pull/909
    # which is not yet released.
    yield VendorSpec.git(
        repo="https://github.com/python-attrs/attrs",
        commit="947bfb542104209a587280701d8cb389c813459d",
        project_name="attrs",
    )

    # We use this via pex.third_party at runtime to check for compatible wheel tags and at build
    # time to implement resolving distributions from a PEX repository.
    if not python_major_minor or python_major_minor < (3, 6):
        # N.B.: The pyparsing constraint is needed for 2.7 support.
        yield VendorSpec.pinned(
            "packaging", "20.9", import_path="packaging_20_9", constraints=("pyparsing<3",)
        )
    if not python_major_minor or python_major_minor == (3, 6):
        # N.B.: Introduced to add support for musllinux wheels via:
        #   https://github.com/pex-tool/pex/issues/1933
        # N.B.: The pyparsing constraint is needed for 3.6 support.
        yield VendorSpec.pinned(
            "packaging", "21.3", import_path="packaging_21_3", constraints=("pyparsing<3.0.8",)
        )
    if not python_major_minor or python_major_minor == (3, 7):
        # The last version to support 3.7.
        yield VendorSpec.pinned("packaging", "24.0", import_path="packaging_24_0")
    if not python_major_minor or python_major_minor >= (3, 8):
        # Modern packaging for everyone else.
        yield VendorSpec.pinned("packaging", "26.0", import_path="packaging_26_0")

    # N.B.: All vendored items below are optional and may not be present in Pex distributions
    # targeting newer Pythons.

    # We use toml to read pyproject.toml when building sdists from local source projects.
    # The toml project provides compatibility back to Python 2.7, but is frozen in time in 2020
    # with bugs - notably no support for heterogeneous lists. We add the more modern tomli for
    # other Pythons and just use tomllib for Python 3.11+.
    if not python_major_minor or python_major_minor < (3, 7):
        vendored_toml = VendorSpec.pinned("toml", "0.10.2")
        if not filter_exists or vendored_toml.exists:
            yield vendored_toml
    if not python_major_minor or (3, 7) <= python_major_minor < (3, 11):
        vendored_tomli = VendorSpec.pinned("tomli", "2.0.1")
        if not filter_exists or vendored_tomli.exists:
            yield vendored_tomli

    # We shell out to pip at build-time to resolve and install dependencies.
    if not python_major_minor or python_major_minor < (3, 12):
        if not filter_exists or PIP_SPEC.exists:
            yield PIP_SPEC

    # We expose this to pip at build-time for legacy builds, but we also use pkg_resources via
    # pex.third_party at runtime to inject pkg_resources style namespace packages if needed.
    # N.B.: 44.0.0 is the last setuptools version compatible with Python 2 and we use a fork of that
    # with patches needed to support Pex on the v44.0.0/patches/pex-2.x branch.
    pex_tool_setuptools_commit = "3acb925dd708430aeaf197ea53ac8a752f7c1863"
    vendored_setuptools = VendorSpec.git(
        repo="https://github.com/pex-tool/setuptools",
        commit=pex_tool_setuptools_commit,
        project_name="setuptools",
        # Setuptools from source requires running bootstrap.py 1st manually due to circularity in
        # needing setuptools to build setuptools. The bootstrap runs `setup.py egg_info` which
        # generates a version containing a date stamp. We override setup.cfg's egg_info section to
        # avoid this instability and instead force using the commit as the stable version
        # modifier.
        # N.B.: This code assumes its run under Python 3.5+.
        prep_command=[
            sys.executable,
            "-c",
            dedent(
                """\
                import configparser
                import subprocess
                import sys


                parser = configparser.ConfigParser()
                parser.read("setup.cfg")
                parser["egg_info"]["tag_build"] = "+{commit}"
                del parser["egg_info"]["tag_date"]
                with open("setup.cfg", "w") as fp:
                    parser.write(fp)

                subprocess.check_call([sys.executable, "bootstrap.py"])
                """
            ).format(commit=pex_tool_setuptools_commit),
        ],
    )
    if not python_major_minor or python_major_minor < (3, 12):
        if not filter_exists or vendored_setuptools.exists:
            yield vendored_setuptools


def vendor_runtime(
    chroot,  # type: Chroot
    dest_basedir,  # type: str
    label,  # type: str
    root_module_names,  # type: Iterable[str]
):
    # type: (...) -> Set[str]
    """Includes portions of vendored distributions in a chroot.

    The portion to include is selected by root module name. If the module is a file, just it is
    included. If the module represents a package, the package and all its sub-packages are added
    recursively.

    :param chroot: The chroot to add vendored code to.
    :param dest_basedir: The prefix to store the vendored code under in the ``chroot``.
    :param label: The chroot label for the vendored code fileset.
    :param root_module_names: The names of the root vendored modules to include in the chroot.
    :returns: The set of absolute paths of the source files that were vendored.
    :raise: :class:`ValueError` if any of the given ``root_module_names`` could not be found amongst
            the vendored code and added to the chroot.
    """
    vendor_module_names = {root_module_name: False for root_module_name in root_module_names}

    vendored_sources = set()  # type: Set[str]
    for spec in iter_vendor_specs():
        for root, dirs, files in os.walk(spec.target_dir):
            if root == spec.target_dir:
                packages = [pkg_name for pkg_name in dirs if pkg_name in vendor_module_names]
                modules = [mod_name for mod_name in files if mod_name[:-3] in vendor_module_names]
                vendored_names = packages + [filename[:-3] for filename in modules]
                if not vendored_names:
                    dirs[:] = []
                    files[:] = []
                    continue

                pkg_path = ""
                for pkg in spec.relpath.split(os.sep):
                    pkg_path = os.path.join(pkg_path, pkg)
                    pkg_file = os.path.join(pkg_path, "__init__.py")
                    src = os.path.join(VendorSpec.ROOT, pkg_file)
                    if src in vendored_sources:
                        continue
                    dest = os.path.join(dest_basedir, pkg_file)
                    if os.path.exists(src):
                        chroot.copy(src, dest, label)
                    else:
                        # We delete `pex/vendor/_vendored/<dist>/__init__.py` when isolating
                        # third_party.
                        chroot.touch(dest, label)
                    vendored_sources.add(src)

                for name in vendored_names:
                    vendor_module_names[name] = True
                    TRACER.log("Vendoring {} from {} @ {}".format(name, spec, spec.target_dir), V=3)

                dirs[:] = packages
                files[:] = modules

            # We copy over sources and data only; no pyc files.
            dirs[:] = [d for d in dirs if not is_pyc_dir(d)]
            for filename in files:
                if is_pyc_file(filename):
                    continue
                src = os.path.join(root, filename)
                if src in vendored_sources:
                    continue
                dest = os.path.join(
                    dest_basedir, spec.relpath, os.path.relpath(src, spec.target_dir)
                )
                chroot.copy(src, dest, label)
                vendored_sources.add(src)

    if not all(vendor_module_names.values()):
        raise ValueError(
            "Failed to extract {module_names} from:\n\t{specs}".format(
                module_names=", ".join(
                    module for module, written in vendor_module_names.items() if not written
                ),
                specs="\n\t".join(
                    "{} @ {}".format(spec, spec.target_dir) for spec in iter_vendor_specs()
                ),
            )
        )

    return vendored_sources
