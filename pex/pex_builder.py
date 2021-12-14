# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib
import logging
import os
import shutil

from pex import pex_warnings
from pex.common import (
    Chroot,
    atomic_directory,
    chmod_plus_x,
    is_pyc_temporary_file,
    open_zip,
    safe_copy,
    safe_mkdir,
    safe_mkdtemp,
    safe_open,
    safe_rmtree,
    temporary_dir,
)
from pex.compatibility import to_bytes
from pex.compiler import Compiler
from pex.distribution_target import DistributionTarget
from pex.enum import Enum
from pex.finders import get_entry_point_from_console_script, get_script_from_distributions
from pex.interpreter import PythonInterpreter
from pex.layout import Layout
from pex.orderedset import OrderedSet
from pex.pex import PEX
from pex.pex_info import PexInfo
from pex.pip import get_pip
from pex.third_party.pkg_resources import DefaultProvider, Distribution, ZipProvider, get_provider
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper, DistributionHelper

if TYPE_CHECKING:
    from typing import Dict, Optional


class CopyMode(Enum["CopyMode.Value"]):
    class Value(Enum.Value):
        pass

    COPY = Value("copy")
    LINK = Value("link")
    SYMLINK = Value("symlink")


BOOTSTRAP_ENVIRONMENT = """\
import os
import sys


__INSTALLED_FROM__ = '__PEX_EXE__'


def __re_exec__(argv0, *extra_launch_args):
  os.execv(argv0, [argv0] + list(extra_launch_args) + sys.argv[1:])


def __maybe_install_pex__(pex, pex_root, pex_hash):
  from pex.layout import maybe_install
  from pex.tracer import TRACER

  installed_location = maybe_install(pex, pex_root, pex_hash)
  if not installed_location:
    return

  # N.B.: This is read upon re-exec below to point sys.argv[0] back to the original pex before
  # unconditionally scrubbing the env var and handing off to user code.
  os.environ[__INSTALLED_FROM__] = pex

  TRACER.log('Executing installed PEX for {{}} at {{}}'.format(pex, installed_location))
  __re_exec__(sys.executable, installed_location)


def __maybe_run_venv__(pex, pex_root, pex_path):
  from pex.common import is_exe
  from pex.tracer import TRACER
  from pex.variables import venv_dir

  venv_home = venv_dir(
    pex_file=pex,
    pex_root=pex_root, 
    pex_hash={pex_hash!r},
    has_interpreter_constraints={has_interpreter_constraints!r},
    pex_path=pex_path,
  )
  venv_pex = os.path.join(venv_home, 'pex')
  if not is_exe(venv_pex):
    # Code in bootstrap_pex will (re)create the venv after selecting the correct interpreter. 
    return

  TRACER.log('Executing venv PEX for {{}} at {{}}'.format(pex, venv_pex))
  __re_exec__(venv_pex)


__entry_point__ = None
if '__file__' in locals() and __file__ is not None:
  __entry_point__ = os.path.dirname(__file__)
elif '__loader__' in locals():
  from pkgutil import ImpLoader
  if hasattr(__loader__, 'archive'):
    __entry_point__ = __loader__.archive
  elif isinstance(__loader__, ImpLoader):
    __entry_point__ = os.path.dirname(__loader__.get_filename())

if __entry_point__ is None:
  sys.stderr.write('Could not launch python executable!\\n')
  sys.exit(2)

__installed_from__ = os.environ.pop(__INSTALLED_FROM__, None)
sys.argv[0] = __installed_from__ or sys.argv[0]

sys.path[0] = os.path.abspath(sys.path[0])
sys.path.insert(0, os.path.abspath(os.path.join(__entry_point__, {bootstrap_dir!r})))

if not __installed_from__:
    os.environ['PEX'] = os.path.realpath(__entry_point__)
    from pex.variables import ENV, Variables
    __pex_root__ = Variables.PEX_ROOT.value_or(ENV, {pex_root!r})
    if not ENV.PEX_TOOLS and Variables.PEX_VENV.value_or(ENV, {is_venv!r}):
      __maybe_run_venv__(
        __entry_point__,
        pex_root=__pex_root__,
        pex_path=Variables.PEX_PATH.value_or(ENV, {pex_path!r}),
      )
    __maybe_install_pex__(__entry_point__, pex_root=__pex_root__, pex_hash={pex_hash!r})
else:
    os.environ['PEX'] = os.path.realpath(__installed_from__)

from pex.pex_bootstrapper import bootstrap_pex
bootstrap_pex(__entry_point__)
"""


class PEXBuilder(object):
    """Helper for building PEX environments."""

    class Error(Exception):
        pass

    class ImmutablePEX(Error):
        pass

    class InvalidDistribution(Error):
        pass

    class InvalidDependency(Error):
        pass

    class InvalidExecutableSpecification(Error):
        pass

    def __init__(
        self,
        path=None,  # type: Optional[str]
        interpreter=None,  # type: Optional[PythonInterpreter]
        chroot=None,  # type: Optional[Chroot]
        pex_info=None,  # type: Optional[PexInfo]
        preamble=None,  # type: Optional[str]
        copy_mode=CopyMode.LINK,  # type: CopyMode.Value
    ):
        # type: (...) -> None
        """Initialize a pex builder.

        :keyword path: The path to write the PEX as it is built.  If ``None`` is specified,
          a temporary directory will be created.
        :keyword interpreter: The interpreter to use to build this PEX environment.  If ``None``
          is specified, the current interpreter is used.
        :keyword chroot: If specified, preexisting :class:`Chroot` to use for building the PEX.
        :keyword pex_info: A preexisting PexInfo to use to build the PEX.
        :keyword preamble: If supplied, execute this code prior to bootstrapping this PEX
          environment.
        :keyword copy_mode: Create the pex environment using the given copy mode.

        .. versionchanged:: 0.8
          The temporary directory created when ``path`` is not specified is now garbage collected on
          interpreter exit.
        """
        self._interpreter = interpreter or PythonInterpreter.get()
        self._chroot = chroot or Chroot(path or safe_mkdtemp())
        self._pex_info = pex_info or PexInfo.default(self._interpreter)
        self._preamble = preamble or ""
        self._copy_mode = copy_mode

        self._shebang = self._interpreter.identity.hashbang()
        self._logger = logging.getLogger(__name__)
        self._frozen = False
        self._distributions = {}  # type: Dict[str, Distribution]

    def _ensure_unfrozen(self, name="Operation"):
        if self._frozen:
            raise self.ImmutablePEX("%s is not allowed on a frozen PEX!" % name)

    @property
    def interpreter(self):
        return self._interpreter

    def chroot(self):
        # type: () -> Chroot
        return self._chroot

    def clone(self, into=None):
        """Clone this PEX environment into a new PEXBuilder.

        :keyword into: (optional) An optional destination directory to clone this PEXBuilder into.  If
          not specified, a temporary directory will be created.

        Clones PEXBuilder into a new location.  This is useful if the PEXBuilder has been frozen and
        rendered immutable.

        .. versionchanged:: 0.8
          The temporary directory created when ``into`` is not specified is now garbage collected on
          interpreter exit.
        """
        chroot_clone = self._chroot.clone(into=into)
        clone = self.__class__(
            chroot=chroot_clone,
            interpreter=self._interpreter,
            pex_info=self._pex_info.copy(),
            preamble=self._preamble,
            copy_mode=self._copy_mode,
        )
        clone.set_shebang(self._shebang)
        clone._distributions = self._distributions.copy()
        return clone

    def path(self):
        # type: () -> str
        return self.chroot().path()

    @property
    def info(self):
        return self._pex_info

    @info.setter
    def info(self, value):
        if not isinstance(value, PexInfo):
            raise TypeError("PEXBuilder.info must be a PexInfo!")
        self._ensure_unfrozen("Changing PexInfo")
        self._pex_info = value

    def add_source(self, filename, env_filename):
        """Add a source to the PEX environment.

        :param filename: The source filename to add to the PEX; None to create an empty file at
          `env_filename`.
        :param env_filename: The destination filename in the PEX.  This path
          must be a relative path.
        """
        self._ensure_unfrozen("Adding source")
        self._copy_or_link(filename, env_filename, "source")

    def add_resource(self, filename, env_filename):
        """Add a resource to the PEX environment.

        :param filename: The source filename to add to the PEX; None to create an empty file at
          `env_filename`.
        :param env_filename: The destination filename in the PEX.  This path
          must be a relative path.
        """
        pex_warnings.warn(
            "The `add_resource` method is deprecated. Resources should be added via the "
            "`add_source` method instead."
        )
        self._ensure_unfrozen("Adding a resource")
        self._copy_or_link(filename, env_filename, "resource")

    def add_requirement(self, req):
        """Add a requirement to the PEX environment.

        :param req: A requirement that should be resolved in this environment.

        .. versionchanged:: 0.8
          Removed ``dynamic`` and ``repo`` keyword arguments as they were unused.
        """
        self._ensure_unfrozen("Adding a requirement")
        self._pex_info.add_requirement(req)

    def add_interpreter_constraint(self, ic):
        """Add an interpreter constraint to the PEX environment.

        :param ic: A version constraint on the interpreter used to build and run this PEX environment.
        """
        self._ensure_unfrozen("Adding an interpreter constraint")
        self._pex_info.add_interpreter_constraint(ic)

    def add_from_requirements_pex(self, pex):
        """Add requirements from an existing pex.

        :param pex: The path to an existing .pex file or unzipped pex directory.
        """
        self._ensure_unfrozen("Adding from pex")
        pex_info = PexInfo.from_pex(pex)

        def add(location, dname, expected_dhash):
            dhash = self._add_dist_dir(location, dname)
            if dhash != expected_dhash:
                raise self.InvalidDistribution(
                    "Distribution {} at {} had hash {}, expected {}".format(
                        dname, location, dhash, expected_dhash
                    )
                )
            self._pex_info.add_distribution(dname, dhash)

        if os.path.isfile(pex):
            with open_zip(pex) as zf:
                for dist_name, dist_hash in pex_info.distributions.items():
                    internal_dist_path = "/".join([pex_info.internal_cache, dist_name])
                    cached_location = os.path.join(pex_info.install_cache, dist_hash, dist_name)
                    CacheHelper.cache_distribution(zf, internal_dist_path, cached_location)
                    add(cached_location, dist_name, dist_hash)
        else:
            for dist_name, dist_hash in pex_info.distributions.items():
                add(os.path.join(pex, pex_info.internal_cache, dist_name), dist_name, dist_hash)
        for req in pex_info.requirements:
            self._pex_info.add_requirement(req)

    def set_executable(self, filename, env_filename=None):
        """Set the executable for this environment.

        :param filename: The file that should be executed within the PEX environment when the PEX is
          invoked.
        :keyword env_filename: (optional) The name that the executable file should be stored as within
          the PEX.  By default this will be the base name of the given filename.

        The entry point of the PEX may also be specified via ``PEXBuilder.set_entry_point``.
        """
        self._ensure_unfrozen("Setting the executable")
        if self._pex_info.script:
            raise self.InvalidExecutableSpecification(
                "Cannot set both entry point and script of PEX!"
            )
        if env_filename is None:
            env_filename = os.path.basename(filename)
        if self._chroot.get("executable"):
            raise self.InvalidExecutableSpecification(
                "Setting executable on a PEXBuilder that already has one!"
            )
        self._copy_or_link(filename, env_filename, "executable")
        entry_point = env_filename
        entry_point = entry_point.replace(os.path.sep, ".")
        self._pex_info.entry_point = entry_point.rpartition(".")[0]

    def set_script(self, script):
        """Set the entry point of this PEX environment based upon a distribution script.

        :param script: The script name as defined either by a console script or ordinary
          script within the setup.py of one of the distributions added to the PEX.
        :raises: :class:`PEXBuilder.InvalidExecutableSpecification` if the script is not found
          in any distribution added to the PEX.
        """

        distributions = OrderedSet(self._distributions.values())
        if self._pex_info.pex_path:
            for pex in self._pex_info.pex_path.split(":"):
                if os.path.exists(pex):
                    distributions.update(PEX(pex, interpreter=self._interpreter).resolve())

        # Check if 'script' is a console_script.
        dist, entry_point = get_entry_point_from_console_script(script, distributions)
        if entry_point:
            self.set_entry_point(entry_point)
            TRACER.log("Set entrypoint to console_script {!r} in {!r}".format(entry_point, dist))
            return

        # Check if 'script' is an ordinary script.
        dist_script = get_script_from_distributions(script, distributions)
        if dist_script:
            if self._pex_info.entry_point:
                raise self.InvalidExecutableSpecification(
                    "Cannot set both entry point and script of PEX!"
                )
            self._pex_info.script = script
            TRACER.log("Set entrypoint to script {!r} in {!r}".format(script, dist_script.dist))
            return

        raise self.InvalidExecutableSpecification(
            "Could not find script {!r} in any distribution {} within PEX!".format(
                script, ", ".join(str(d) for d in distributions)
            )
        )

    def set_entry_point(self, entry_point):
        """Set the entry point of this PEX environment.

        :param entry_point: The entry point of the PEX in the form of ``module`` or ``module:symbol``,
          or ``None``.
        :type entry_point: string or None

        By default the entry point is None.  The behavior of a ``None`` entry point is dropping into
        an interpreter.  If ``module``, it will be executed via ``runpy.run_module``.  If
        ``module:symbol``, it is equivalent to ``from module import symbol; symbol()``.

        The entry point may also be specified via ``PEXBuilder.set_executable``.
        """
        self._ensure_unfrozen("Setting an entry point")
        self._pex_info.entry_point = entry_point

    def set_shebang(self, shebang):
        """Set the exact shebang line for the PEX file.

        For example, pex_builder.set_shebang('/home/wickman/Local/bin/python3.4').  This is
        used to override the default behavior which is to have a #!/usr/bin/env line referencing an
        interpreter compatible with the one used to build the PEX.

        :param shebang: The shebang line. If it does not include the leading '#!' it will be added.
        :type shebang: str
        """
        self._shebang = "#!%s" % shebang if not shebang.startswith("#!") else shebang

    def _add_dist_dir(self, path, dist_name, fingerprint=None):
        target_dir = os.path.join(self._pex_info.internal_cache, dist_name)
        if self._copy_mode == CopyMode.SYMLINK:
            self._copy_or_link(path, target_dir, label=dist_name)
        else:
            for root, _, files in os.walk(path):
                for f in files:
                    filename = os.path.join(root, f)
                    relpath = os.path.relpath(filename, path)
                    target = os.path.join(target_dir, relpath)
                    self._copy_or_link(filename, target, label=dist_name)
        return fingerprint or CacheHelper.dir_hash(path)

    def _add_dist_wheel_file(self, path, dist_name, fingerprint=None):
        with temporary_dir() as install_dir:
            get_pip(interpreter=self._interpreter).spawn_install_wheel(
                wheel=path,
                install_dir=install_dir,
                target=DistributionTarget.for_interpreter(self.interpreter),
            ).wait()
            return self._add_dist_dir(install_dir, dist_name, fingerprint=fingerprint)

    def add_distribution(self, dist, dist_name=None, fingerprint=None):
        """Add a :class:`pkg_resources.Distribution` from its handle.

        :param dist: The distribution to add to this environment.
        :keyword dist_name: (optional) The name of the distribution e.g. 'Flask-0.10.0'.  By default
          this will be inferred from the distribution itself should it be formatted in a standard
          way.
        :keyword fingerprint: The fingerprint of the distribution, if already known.
        :type dist: :class:`pkg_resources.Distribution`
        """
        if dist.location in self._distributions:
            TRACER.log(
                "Skipping adding {} - already added from {}".format(dist, dist.location), V=9
            )
            return
        self._ensure_unfrozen("Adding a distribution")
        dist_name = dist_name or os.path.basename(dist.location)
        self._distributions[dist.location] = dist

        if os.path.isdir(dist.location):
            dist_hash = self._add_dist_dir(dist.location, dist_name, fingerprint=fingerprint)
        elif dist.location.endswith(".whl"):
            dist_hash = self._add_dist_wheel_file(dist.location, dist_name, fingerprint=fingerprint)
        else:
            raise self.InvalidDistribution(
                "Unsupported distribution type: {}, pex can only accept dist "
                "dirs and wheels.".format(dist)
            )

        # add dependency key so that it can rapidly be retrieved from cache
        self._pex_info.add_distribution(dist_name, dist_hash)

    def add_dist_location(self, dist, name=None, fingerprint=None):
        """Add a distribution by its location on disk.

        :param dist: The path to the distribution to add.
        :keyword name: (optional) The name of the distribution, should the dist directory alone be
          ambiguous.  Packages contained within site-packages directories may require specifying
          ``name``.
        :keyword fingerprint: The fingerprint of the distribution, if already known.
        :raises PEXBuilder.InvalidDistribution: When the path does not contain a matching distribution.

        PEX supports packed and unpacked .whl and .egg distributions, as well as any distribution
        supported by setuptools/pkg_resources.
        """
        self._ensure_unfrozen("Adding a distribution")
        dist_path = dist
        if os.path.isfile(dist_path) and dist_path.endswith(".whl"):
            dist_path = os.path.join(safe_mkdtemp(), os.path.basename(dist))
            get_pip(interpreter=self._interpreter).spawn_install_wheel(
                wheel=dist,
                install_dir=dist_path,
                target=DistributionTarget.for_interpreter(self.interpreter),
            ).wait()

        dist = DistributionHelper.distribution_from_path(dist_path)
        self.add_distribution(dist, dist_name=name, fingerprint=fingerprint)
        self.add_requirement(dist.as_requirement())

    def _precompile_source(self):
        source_relpaths = [
            path
            for label in ("source", "executable", "main", "bootstrap")
            for path in self._chroot.filesets.get(label, ())
            if path.endswith(".py")
            # N.B.: This file if Python 3.6+ only and will not compile under Python 2.7 or
            # Python 3.5. Since we don't actually use it we just skip compiling it.
            and path
            != os.path.join(
                self._pex_info.bootstrap, "pex/vendor/_vendored/attrs/attr/_next_gen.py"
            )
        ]

        compiler = Compiler(self.interpreter)
        compiled_relpaths = compiler.compile(self._chroot.path(), source_relpaths)
        for compiled in compiled_relpaths:
            self._chroot.touch(compiled, label="bytecode")

    def _prepare_code(self):
        self._pex_info.code_hash = CacheHelper.pex_code_hash(self._chroot.path())
        self._pex_info.pex_hash = hashlib.sha1(self._pex_info.dump().encode("utf-8")).hexdigest()
        self._chroot.write(self._pex_info.dump().encode("utf-8"), PexInfo.PATH, label="manifest")

        bootstrap = BOOTSTRAP_ENVIRONMENT.format(
            bootstrap_dir=self._pex_info.bootstrap,
            pex_root=self._pex_info.raw_pex_root,
            pex_hash=self._pex_info.pex_hash,
            has_interpreter_constraints=bool(self._pex_info.interpreter_constraints),
            pex_path=self._pex_info.pex_path,
            is_venv=self._pex_info.venv,
        )
        self._chroot.write(
            data=to_bytes(self._shebang + "\n" + self._preamble + "\n" + bootstrap),
            dst="__main__.py",
            executable=True,
            label="main",
        )

    def _copy_or_link(self, src, dst, label=None):
        if src is None:
            self._chroot.touch(dst, label)
        elif self._copy_mode == CopyMode.COPY:
            self._chroot.copy(src, dst, label)
        elif self._copy_mode == CopyMode.SYMLINK:
            self._chroot.symlink(src, dst, label)
        else:
            self._chroot.link(src, dst, label)

    def _prepare_bootstrap(self):
        from . import vendor

        vendor.vendor_runtime(
            chroot=self._chroot,
            dest_basedir=self._pex_info.bootstrap,
            label="bootstrap",
            # NB: We use pip here in the builder, but that's only at buildtime and
            # although we don't use pyparsing directly, packaging.markers, which we
            # do use at runtime, does.
            root_module_names=["attr", "packaging", "pkg_resources", "pyparsing"],
        )
        if self._pex_info.includes_tools:
            # The `repository extract` tool needs setuptools and wheel to build sdists and wheels
            # and distutils needs .dist-info to discover setuptools (and wheel).
            vendor.vendor_runtime(
                chroot=self._chroot,
                dest_basedir=self._pex_info.bootstrap,
                label="bootstrap",
                root_module_names=["setuptools", "wheel"],
                include_dist_info=True,
            )

        source_name = "pex"
        provider = get_provider(source_name)
        if not isinstance(provider, DefaultProvider):
            mod = __import__(source_name, fromlist=["ignore"])
            provider = ZipProvider(mod)

        bootstrap_digest = hashlib.sha1()
        bootstrap_packages = ["", "third_party"]
        if self._pex_info.includes_tools:
            bootstrap_packages.extend(["commands", "tools", "tools/commands"])
        for package in bootstrap_packages:
            for fn in provider.resource_listdir(package):
                rel_path = os.path.join(package, fn)
                if not (
                    provider.resource_isdir(rel_path)
                    or fn.endswith(".pyc")
                    or fn.endswith("testing.py")
                ):
                    data = provider.get_resource_string(source_name, rel_path)
                    self._chroot.write(
                        data,
                        dst=os.path.join(self._pex_info.bootstrap, source_name, rel_path),
                        label="bootstrap",
                    )
                    bootstrap_digest.update(data)
        self._pex_info.bootstrap_hash = bootstrap_digest.hexdigest()

    def freeze(self, bytecode_compile=True):
        """Freeze the PEX.

        :param bytecode_compile: If True, precompile .py files into .pyc files when freezing code.

        Freezing the PEX writes all the necessary metadata and environment bootstrapping code.  It may
        only be called once and renders the PEXBuilder immutable.
        """
        self._ensure_unfrozen("Freezing the environment")
        self._prepare_bootstrap()
        self._prepare_code()
        if bytecode_compile:
            self._precompile_source()
        self._frozen = True

    def build(
        self,
        path,  # type: str
        bytecode_compile=True,  # type: bool
        deterministic_timestamp=False,  # type: bool
        layout=Layout.ZIPAPP,  # type: Layout.Value
    ):
        # type: (...) -> None
        """Package the PEX application.

        By default, the PEX is packaged as a zipapp for ease of shipping as a single file, but it
        can also be packaged in spread mode for efficiency of syncing over the network
        incrementally.

        :param path: The path where the PEX should be stored.
        :param bytecode_compile: If True, precompile .py files into .pyc files.
        :param deterministic_timestamp: If True, will use our hardcoded time for zipfile timestamps.
        :param layout: The layout to use for the PEX.

        If the PEXBuilder is not yet frozen, it will be frozen by ``build``.  This renders the
        PEXBuilder immutable.
        """
        if not self._frozen:
            self.freeze(bytecode_compile=bytecode_compile)
        if layout in (Layout.LOOSE, Layout.PACKED):
            safe_rmtree(path)

            # N.B.: We want an atomic directory, but we don't expect a user to race themselves
            # building to a single non-PEX_ROOT user-requested output path; so we don't grab an
            # exclusive lock and dirty the target directory with a `.lck` file.
            with atomic_directory(path, source="app", exclusive=False) as app_chroot:
                if not app_chroot.is_finalized:
                    dirname = os.path.join(app_chroot.work_dir, "app")
                    if layout == Layout.LOOSE:
                        shutil.copytree(self.path(), dirname)
                    else:
                        os.mkdir(dirname)
                        self._build_packedapp(
                            dirname=dirname, deterministic_timestamp=deterministic_timestamp
                        )
        else:
            self._build_zipapp(filename=path, deterministic_timestamp=deterministic_timestamp)

    def _build_packedapp(
        self,
        dirname,  # type: str
        deterministic_timestamp=False,  # type: bool
    ):
        # type: (...) -> None

        pex_info = self._pex_info.copy()
        pex_info.update(PexInfo.from_env())

        # Include user sources, PEX-INFO and __main__ as loose files in src/.
        for fileset in "source", "resource", "executable", "main", "manifest":
            for f in self._chroot.filesets.get(fileset, ()):
                dest = os.path.join(dirname, f)
                safe_mkdir(os.path.dirname(dest))
                safe_copy(os.path.realpath(os.path.join(self._chroot.chroot, f)), dest)

        # Zip up the bootstrap which is constant for a given version of Pex.
        bootstrap_hash = pex_info.bootstrap_hash
        if bootstrap_hash is None:
            raise AssertionError(
                "Expected bootstrap_hash to be populated for {}.".format(self._pex_info)
            )
        cached_bootstrap_zip_dir = os.path.join(pex_info.pex_root, "bootstrap_zips", bootstrap_hash)
        with atomic_directory(
            cached_bootstrap_zip_dir, exclusive=False
        ) as atomic_bootstrap_zip_dir:
            if not atomic_bootstrap_zip_dir.is_finalized:
                self._chroot.zip(
                    os.path.join(atomic_bootstrap_zip_dir.work_dir, pex_info.bootstrap),
                    deterministic_timestamp=deterministic_timestamp,
                    exclude_file=is_pyc_temporary_file,
                    strip_prefix=pex_info.bootstrap,
                    labels=("bootstrap",),
                )
        safe_copy(
            os.path.join(cached_bootstrap_zip_dir, pex_info.bootstrap),
            os.path.join(dirname, pex_info.bootstrap),
        )

        # Zip up each installed wheel chroot, which is constant for a given version of a
        # wheel.
        if pex_info.distributions:
            internal_cache = os.path.join(dirname, pex_info.internal_cache)
            os.mkdir(internal_cache)
            for location, fingerprint in pex_info.distributions.items():
                cached_installed_wheel_zip_dir = os.path.join(
                    pex_info.pex_root, "installed_wheel_zips", fingerprint
                )
                with atomic_directory(
                    cached_installed_wheel_zip_dir, exclusive=False
                ) as atomic_zip_dir:
                    if not atomic_zip_dir.is_finalized:
                        self._chroot.zip(
                            os.path.join(atomic_zip_dir.work_dir, location),
                            deterministic_timestamp=deterministic_timestamp,
                            exclude_file=is_pyc_temporary_file,
                            strip_prefix=os.path.join(pex_info.internal_cache, location),
                            labels=(location,),
                        )
                safe_copy(
                    os.path.join(cached_installed_wheel_zip_dir, location),
                    os.path.join(internal_cache, location),
                )

    def _build_zipapp(
        self,
        filename,  # type: str
        deterministic_timestamp=False,  # type: bool
    ):
        # type: (...) -> None
        tmp_zip = filename + "~"
        try:
            os.unlink(tmp_zip)
            self._logger.warning(
                "Previous binary unexpectedly exists, cleaning: {}".format(tmp_zip)
            )
        except OSError:
            # The expectation is that the file does not exist, so continue
            pass
        with safe_open(tmp_zip, "ab") as pexfile:
            assert os.path.getsize(pexfile.name) == 0
            pexfile.write(to_bytes("{}\n".format(self._shebang)))
        with TRACER.timed("Zipping PEX file."):
            self._chroot.zip(
                tmp_zip,
                mode="a",
                deterministic_timestamp=deterministic_timestamp,
                # When configured with a `copy_mode` of `CopyMode.SYMLINK`, we symlink distributions
                # as pointers to installed wheel directories in ~/.pex/installed_wheels/... Since
                # those installed wheels reside in a shared cache, they can be in-use by other
                # processes and so their code may be in the process of being bytecode compiled as we
                # attempt to zip up our chroot. Bytecode compilation produces ephemeral temporary
                # pyc files that we should avoid copying since they are unuseful and inherently
                # racy.
                exclude_file=is_pyc_temporary_file,
            )
        if os.path.exists(filename):
            os.unlink(filename)
        os.rename(tmp_zip, filename)
        chmod_plus_x(filename)
