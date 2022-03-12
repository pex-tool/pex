# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import collections
import os
import subprocess
import sys
from textwrap import dedent

from pex.common import filter_pyc_dirs, filter_pyc_files, safe_mkdtemp, touch
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterator

_PACKAGE_COMPONENTS = __name__.split(".")


def _root():
    path = os.path.dirname(os.path.abspath(__file__))
    for _ in _PACKAGE_COMPONENTS:
        path = os.path.dirname(path)
    return path


class VendorSpec(
    collections.namedtuple(
        "VendorSpec", ["key", "requirement", "rewrite", "constrain", "constraints"]
    )
):
    """Represents a vendored distribution.

    :field str key: The distribution requirement key; e.g.: for a requirement of
      requests[security]==2.22.0 the key is 'requests'.
    :field str requirement: The distribution requirement string; e.g.: requests[security]==2.22.0.
    :field bool rewrite: Whether to re-write the distribution's imports for use with the
      `pex.third_party` importer.
    :field bool constrain: Whether to attempt to constrain the requirement via pip's --constraint
      mechanism.
    :field constraints: An optional list of extra constraints on the vendored requirement.

    NB: Vendored distributions should comply with the host distribution platform constraints. In the
    case of pex, which is a py2.py3 platform agnostic wheel, vendored libraries should be as well.
    """

    ROOT = _root()

    _VENDOR_DIR = "_vendored"

    @classmethod
    def vendor_root(cls):
        return os.path.join(cls.ROOT, *(_PACKAGE_COMPONENTS + [cls._VENDOR_DIR]))

    @classmethod
    def pinned(cls, key, version, rewrite=True, constraints=None):
        return cls(
            key=key,
            requirement="{}=={}".format(key, version),
            rewrite=rewrite,
            constrain=True,
            constraints=constraints,
        )

    @classmethod
    def git(cls, repo, commit, project_name, prep_command=None, rewrite=True, constraints=None):
        requirement = "git+{repo}@{commit}#egg={project_name}".format(
            repo=repo, commit=commit, project_name=project_name
        )
        if not prep_command:
            return cls(
                key=project_name,
                requirement=requirement,
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
            rewrite=rewrite,
            constrain=False,
            constraints=constraints,
        )

    @property
    def _subpath_components(self):
        return [self._VENDOR_DIR, self.key]

    @property
    def relpath(self):
        return os.path.join(*(_PACKAGE_COMPONENTS + self._subpath_components))

    @property
    def target_dir(self):
        return os.path.join(self.ROOT, self.relpath)

    def prepare(self):
        return self.requirement

    def create_packages(self):
        """Create missing packages joining the vendor root to the base of the vendored distribution.

        For example, given a root at ``/home/jake/dev/pantsbuild/pex`` and a vendored distribution at
        ``pex/vendor/_vendored/requests`` this method would create the following package files::

          pex/vendor/_vendored/__init__.py
          pex/vendor/_vendored/requests/__init__.py

        These package files allow for standard python importers to find vendored code via re-directs
        from a `PEP-302 <https://www.python.org/dev/peps/pep-0302/>`_ importer like
        :class:`pex.third_party.VendorImporter`.
        """
        if not self.rewrite:
            # The extra package structure is only required for vendored code used via import rewrites.
            return

        for index, _ in enumerate(self._subpath_components):
            relpath = _PACKAGE_COMPONENTS + self._subpath_components[: index + 1] + ["__init__.py"]
            touch(os.path.join(self.ROOT, *relpath))


def iter_vendor_specs():
    # type: () -> Iterator[VendorSpec]
    """Iterate specifications for code vendored by pex.

    :return: An iterator over specs of all vendored code.
    """
    # We use this for a better @dataclass that is also Python2.7 and PyPy compatible.
    # N.B.: The `[testenv:typecheck]` section in `tox.ini` should have its deps list updated to
    # reflect this attrs version.
    yield VendorSpec.pinned("attrs", "21.2.0")

    # We use this via pex.third_party at runtime to check for compatible wheel tags and at build
    # time to implement resolving distributions from a PEX repository.
    yield VendorSpec.pinned("packaging", "20.9", constraints=("pyparsing<3",))

    # We shell out to pip at buildtime to resolve and install dependencies.
    # N.B.: We're currently using a patched version of Pip 20.3.4 housed at
    # https://github.com/pantsbuild/pip/tree/pex/patches/generation-2.
    # It has 2 patches:
    # 1.) https://github.com/pantsbuild/pip/commit/06f462537c981116c763c1ba40cf40e9dd461bcf
    #     The patch works around a bug in `pip download --constraint...` tracked at
    #     https://github.com/pypa/pip/issues/9283 and fixed by https://github.com/pypa/pip/pull/9301
    #     there and https://github.com/pantsbuild/pip/pull/8 in our fork.
    # 2.) https://github.com/pantsbuild/pip/commit/386a54f097ece66775d0c7f34fd29bb596c6b0be
    #     This is a cherry-pick of
    #     https://github.com/pantsbuild/pip/commit/00fb5a0b224cde08e3e5ca034247baadfb646468
    #     (https://github.com/pypa/pip/pull/9533) from upstream that upgrades Pip's vendored
    #     packaging to 20.9 to pick up support for mac universal2 wheels.
    yield VendorSpec.git(
        repo="https://github.com/pantsbuild/pip",
        commit="386a54f097ece66775d0c7f34fd29bb596c6b0be",
        project_name="pip",
        rewrite=False,
    )

    # We expose this to pip at buildtime for legacy builds, but we also use pkg_resources via
    # pex.third_party at runtime in various ways.
    # N.B.: 44.0.0 is the last setuptools version compatible with Python 2 and we use a fork of that
    # with patches needed to support Pex on the v44.0.0/patches/pex-2.x branch.
    pantsbuild_setuptools_commit = "3acb925dd708430aeaf197ea53ac8a752f7c1863"
    yield VendorSpec.git(
        repo="https://github.com/pantsbuild/setuptools",
        commit=pantsbuild_setuptools_commit,
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
            ).format(commit=pantsbuild_setuptools_commit),
        ],
    )

    # We expose this to pip at buildtime for legacy builds.
    yield VendorSpec.pinned("wheel", "0.37.1", rewrite=False)


def vendor_runtime(chroot, dest_basedir, label, root_module_names, include_dist_info=False):
    """Includes portions of vendored distributions in a chroot.

    The portion to include is selected by root module name. If the module is a file, just it is
    included. If the module represents a package, the package and all its sub-packages are added
    recursively.

    :param chroot: The chroot to add vendored code to.
    :type chroot: :class:`pex.common.Chroot`
    :param str dest_basedir: The prefix to store the vendored code under in the ``chroot``.
    :param str label: The chroot label for the vendored code fileset.
    :param root_module_names: The names of the root vendored modules to include in the chroot.
    :type root_module_names: :class:`collections.Iterable` of str
    :param bool include_dist_info: Include the .dist-info dirs associated with the root module
                                   names.
    :raise: :class:`ValueError` if any of the given ``root_module_names`` could not be found amongst
            the vendored code and added to the chroot.
    """
    vendor_module_names = {root_module_name: False for root_module_name in root_module_names}

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
                    dest = os.path.join(dest_basedir, pkg_file)
                    if os.path.exists(src):
                        chroot.copy(src, dest, label)
                    else:
                        # We delete `pex/vendor/_vendored/<dist>/__init__.py` when isolating
                        # third_party.
                        chroot.touch(dest, label)
                for name in vendored_names:
                    vendor_module_names[name] = True
                    TRACER.log("Vendoring {} from {} @ {}".format(name, spec, spec.target_dir), V=3)
                dirs[:] = packages + [
                    d for d in dirs if include_dist_info and d.endswith(".dist-info")
                ]
                files[:] = modules

            # We copy over sources and data only; no pyc files.
            dirs[:] = filter_pyc_dirs(dirs)
            for filename in filter_pyc_files(files):
                src = os.path.join(root, filename)
                dest = os.path.join(
                    dest_basedir, spec.relpath, os.path.relpath(src, spec.target_dir)
                )
                chroot.copy(src, dest, label)

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
