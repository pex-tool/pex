# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import hashlib
import logging
import os
import shutil
import zipimport
from textwrap import dedent
from zipimport import ZipImportError

from pex import layout, pex_warnings
from pex.atomic_directory import atomic_directory
from pex.cache.dirs import BootstrapZipDir, PackedWheelDir
from pex.common import (
    Chroot,
    CopyMode,
    deterministic_walk,
    is_pyc_file,
    is_pyc_temporary_file,
    safe_copy,
    safe_delete,
    safe_mkdir,
    safe_mkdtemp,
    safe_open,
)
from pex.compatibility import safe_commonpath, to_bytes
from pex.compiler import Compiler
from pex.dist_metadata import Distribution, DistributionType, MetadataError
from pex.enum import Enum
from pex.executables import chmod_plus_x, create_sh_python_redirector_shebang
from pex.finders import get_entry_point_from_console_script, get_script_from_distributions
from pex.fs import safe_rename, safe_symlink
from pex.installed_wheel import InstalledWheel
from pex.interpreter import PythonInterpreter
from pex.layout import Layout
from pex.orderedset import OrderedSet
from pex.os import WINDOWS
from pex.pex import PEX
from pex.pex_info import PexInfo
from pex.sh_boot import create_sh_boot_script
from pex.targets import Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.util import CacheHelper

if TYPE_CHECKING:
    from typing import Dict, Iterable, Optional

# N.B.: __file__ will be relative when this module is loaded from a "" `sys.path` entry under
# Python 2.7. This can occur in test scenarios; so we ensure the __file__ is resolved to an absolute
# path here at import time before any cd'ing occurs in test code that might interfere with our
# attempts to locate Pex files later below.
_ABS_PEX_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))


class InvalidZipAppError(Exception):
    pass


class Check(Enum["Check.Value"]):
    class Value(Enum.Value):
        def perform_check(
            self,
            layout,  # type: Layout.Value
            path,  # type: str
        ):
            # type: (...) -> Optional[bool]

            if self is Check.NONE:
                return None

            if layout is not Layout.ZIPAPP:
                return None

            try:
                importer = zipimport.zipimporter(path)

                # N.B.: The legacy `find_module` method returns the `zipimporter` instance itself on
                # success and the `find_spec` method returns a `ModuleSpec` instance on success, but
                # both return `None` on failure to find the module.
                finder = "find_spec" if hasattr(importer, "find_spec") else "find_module"
                if getattr(importer, finder)("__main__") is not None:
                    return True
                reason = "Could not find the `__main__` module."
            except ZipImportError as e:
                # N.B.: PyPy<3.8 raises "ZipImportError: <PATH> seems not to be a zipfile" for ZIP64
                # zips; so we handle that here.
                reason = str(e)

            message = (
                dedent(
                    """\
                    The PEX zip at {path} is not a valid zipapp: {reason}
                    This is likely due to the zip requiring ZIP64 extensions due to size or the
                    number of file entries or both. You can work around this limitation in Python's
                    `zipimport` module by re-building the PEX with `--layout packed` or
                    `--layout loose`.
                    """
                )
                .format(path=path, reason=reason)
                .strip()
            )
            if self is Check.ERROR:
                raise InvalidZipAppError(message)

            pex_warnings.warn(message)
            return False

    NONE = Value("none")
    WARN = Value("warn")
    ERROR = Value("error")


Check.seal()


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
        self._pex_info = pex_info or PexInfo.default()
        self._preamble = preamble or ""
        self._copy_mode = (
            CopyMode.LINK if ((copy_mode is CopyMode.SYMLINK) and WINDOWS) else copy_mode
        )

        self._shebang = self._interpreter.identity.hashbang()
        self._header = None  # type: Optional[str]
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
        for pex in self._pex_info.pex_path:
            if os.path.exists(pex):
                distributions.update(PEX(pex, interpreter=self._interpreter).resolve())

        # Check if 'script' is a console_script.
        dist_entry_point = get_entry_point_from_console_script(script, distributions)
        if dist_entry_point:
            self.set_entry_point(str(dist_entry_point.entry_point))
            TRACER.log(
                "Set entrypoint to {console_script}".format(
                    console_script=dist_entry_point.render_description()
                )
            )
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

    @property
    def shebang(self):
        # type: () -> str
        return self._shebang

    def set_shebang(self, shebang):
        """Set the exact shebang line for the PEX file.

        For example, pex_builder.set_shebang('/home/wickman/Local/bin/python3.4').  This is
        used to override the default behavior which is to have a #!/usr/bin/env line referencing an
        interpreter compatible with the one used to build the PEX.

        :param shebang: The shebang line. If it does not include the leading '#!' it will be added.
        :type shebang: str
        """
        self._shebang = "#!%s" % shebang if not shebang.startswith("#!") else shebang

    def set_header(self, header):
        # type: (str) -> None
        """Set a header script for the PEX.

        By default, there is none and the default shebang invokes Python against the PEX zip file,
        which causes Python to look for a root `__main__.py` module in the PEX zip and execute that.
        Adding a header is not useful if the shebang selects a Python interpreter since Python will
        ignore this header script content and execute the zipapp algorithm described above. It can
        be useful though when the PEX is passed to some other type of interpreter and / or the
        shebang is also customised to be a non-Python interpreter that acts incrementally (I.E.: it
        won't try to parse the zip file all at once; thus choking on the zip content after the
        header.). An important case of this are unix shells, in particular (ba)sh, which evaluates
        files incrementally line by line.
        """
        self._header = header

    def _add_dist(
        self,
        path,  # type: str
        dist_name,  # type: str
        fingerprint=None,  # type: Optional[str]
        is_wheel_file=False,  # type: bool
    ):
        target_dir = os.path.join(self._pex_info.internal_cache, dist_name)
        if self._copy_mode is CopyMode.SYMLINK or is_wheel_file:
            self._copy_or_link(
                path,
                target_dir,
                label=dist_name,
                compress=not is_wheel_file,
                copy_mode=CopyMode.LINK if is_wheel_file else None,
            )
        else:
            for root, _, files in deterministic_walk(path):
                for f in files:
                    if is_pyc_file(f):
                        continue
                    filename = os.path.join(root, f)
                    relpath = os.path.relpath(filename, path)
                    target = os.path.join(target_dir, relpath)
                    self._copy_or_link(filename, target, label=dist_name)
        if fingerprint:
            return fingerprint
        if not is_wheel_file:
            try:
                installed_wheel = InstalledWheel.load(path)
                if installed_wheel.fingerprint:
                    return installed_wheel.fingerprint
            except InstalledWheel.LoadError:
                pass
        return CacheHelper.hash(path) if is_wheel_file else CacheHelper.dir_hash(path)

    def add_distribution(
        self,
        dist,  # type: Distribution
        fingerprint=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        """Add a :class:`pex.dist_metadata.Distribution` from its handle.

        :param dist: The distribution to add to this environment.
        :keyword fingerprint: The fingerprint of the distribution, if already known.
        """
        if dist.location in self._distributions:
            TRACER.log(
                "Skipping adding {} - already added from {}".format(dist, dist.location), V=9
            )
            return
        self._ensure_unfrozen("Adding a distribution")
        dist_name = os.path.basename(dist.location)
        self._distributions[dist.location] = dist

        if dist.type not in (DistributionType.WHEEL, DistributionType.INSTALLED):
            raise self.InvalidDistribution(
                "Unsupported distribution type: {}, pex can only accept wheel files and dist "
                "dirs (installed wheels).".format(dist)
            )
        dist_hash = self._add_dist(
            dist.location,
            dist_name,
            fingerprint=fingerprint,
            is_wheel_file=dist.type is DistributionType.WHEEL,
        )

        # add dependency key so that it can rapidly be retrieved from cache
        self._pex_info.add_distribution(dist_name, dist_hash)

    def add_dist_location(
        self,
        dist,  # type: str
        fingerprint=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        """Add a distribution by its location on disk.

        :param dist: The path to the distribution to add.
        :keyword fingerprint: The fingerprint of the distribution, if already known.
        :raises PEXBuilder.InvalidDistribution: When the path does not contain a matching
          distribution.

        PEX supports only installed wheel distributions.
        """
        self._ensure_unfrozen("Adding a distribution")
        try:
            distribution = Distribution.load(dist)
        except MetadataError as e:
            raise self.InvalidDistribution(str(e))
        self.add_distribution(distribution, fingerprint=fingerprint)
        self.add_requirement(distribution.as_requirement())

    @property
    def distributions(self):
        # type: () -> Iterable[Distribution]
        return self._distributions.values()

    def _precompile_source(self):
        vendored_dir = os.path.join(self._pex_info.bootstrap, "pex/vendor/_vendored")
        source_relpaths = [
            path
            for label in ("source", "executable", "main", "bootstrap")
            for path in self._chroot.filesets.get(label, ())
            if path.endswith(".py")
            # N.B.: Some of our vendored code does not work with all versions of Python we support;
            # so we just skip compiling it.
            and vendored_dir != safe_commonpath((vendored_dir, path))
        ]

        compiler = Compiler(self.interpreter)
        compiled_relpaths = compiler.compile(self._chroot.path(), source_relpaths)
        for compiled in compiled_relpaths:
            self._chroot.touch(compiled, label="bytecode")

    def _prepare_code(self):
        chroot_path = self._chroot.path()
        self._pex_info.code_hash = CacheHelper.pex_code_hash(
            chroot_path, exclude_dirs=(layout.BOOTSTRAP_DIR, layout.DEPS_DIR)
        )
        self._pex_info.pex_hash = hashlib.sha1(self._pex_info.dump().encode("utf-8")).hexdigest()
        self._chroot.write(self._pex_info.dump().encode("utf-8"), PexInfo.PATH, label="manifest")

        with open(os.path.join(_ABS_PEX_PACKAGE_DIR, "pex_boot.py")) as fp:
            pex_boot = fp.read()

        pex_main = dedent(
            """
            result, should_exit, is_globals = boot(
                bootstrap_dir={bootstrap_dir!r},
                pex_root={pex_root!r},
                pex_hash={pex_hash!r},
                has_interpreter_constraints={has_interpreter_constraints!r},
                pex_path={pex_path!r},
                is_venv={is_venv!r},
                inject_python_args={inject_python_args!r},
            )
            if should_exit:
                sys.exit(0 if is_globals else result)
            elif is_globals:
                globals().update(result)
            """
        ).format(
            bootstrap_dir=self._pex_info.bootstrap,
            pex_root=self._pex_info.raw_pex_root,
            pex_hash=self._pex_info.pex_hash,
            has_interpreter_constraints=bool(self._pex_info.interpreter_constraints),
            pex_path=self._pex_info.pex_path,
            is_venv=self._pex_info.venv,
            inject_python_args=self._pex_info.inject_python_args,
        )
        bootstrap = pex_boot + "\n" + pex_main

        self._chroot.write(
            data=to_bytes(self._shebang + "\n" + self._preamble + "\n" + bootstrap),
            dst="__main__.py",
            executable=True,
            label="main",
        )
        self._chroot.write(
            data=to_bytes(bootstrap),
            dst=os.path.join("__pex__", "__init__.py"),
            label="importhook",
        )

    def _copy_or_link(
        self,
        src,  # type: Optional[str]
        dst,  # type: str
        label=None,  # type: Optional[str]
        compress=True,  # type: bool
        copy_mode=None,  # type: Optional[CopyMode.Value]
    ):
        copy_mode = copy_mode or self._copy_mode
        if src is None:
            self._chroot.touch(dst, label)
        elif copy_mode is CopyMode.COPY:
            self._chroot.copy(src, dst, label, compress)
        elif copy_mode is CopyMode.SYMLINK:
            self._chroot.symlink(src, dst, label, compress)
        else:
            self._chroot.link(src, dst, label, compress)

    def _prepare_bootstrap(self):
        from . import vendor

        # NB: We use pip here in the builder, but that's only at build time, and
        # although we don't use pyparsing directly, packaging.markers, which we
        # do use at runtime, does.
        root_module_names = ["appdirs", "attr", "colors", "packaging", "pyparsing"]
        for vendor_spec in vendor.iter_vendor_specs():
            if vendor_spec.key == "setuptools":
                root_module_names.append("pkg_resources")

        prepared_sources = vendor.vendor_runtime(
            chroot=self._chroot,
            dest_basedir=self._pex_info.bootstrap,
            label="bootstrap",
            root_module_names=root_module_names,
        )

        bootstrap_digest = hashlib.sha1()
        bootstrap_packages = ["cache", "fs", "repl", "third_party", "venv", "windows"]
        if self._pex_info.includes_tools:
            bootstrap_packages.extend(["commands", "tools"])

        # TODO(John Sirois): Switch to a symlink model, isolate(), then symlink from there?
        # The bootstraps, as it stands, are ~4.5 MB for each loose dogfood PEX. For the Pex ITs,
        # this ends up taking up a significant amount of disk space.

        for root, dirs, files in deterministic_walk(_ABS_PEX_PACKAGE_DIR):
            if root == _ABS_PEX_PACKAGE_DIR:
                dirs[:] = bootstrap_packages

            for f in files:
                if is_pyc_file(f):
                    continue
                abs_src = os.path.join(root, f)
                # N.B.: Some of the `pex.*` package files (__init__.py) will already have been
                # prepared when vendoring the runtime above; so we skip them here.
                if abs_src in prepared_sources:
                    continue
                with open(abs_src, "rb") as fp:
                    data = fp.read()
                self._chroot.write(
                    data,
                    dst=os.path.join(
                        self._pex_info.bootstrap,
                        "pex",
                        os.path.relpath(abs_src, _ABS_PEX_PACKAGE_DIR),
                    ),
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
        deterministic=False,  # type: bool
        layout=Layout.ZIPAPP,  # type: Layout.Value
        compress=True,  # type: bool
        check=Check.NONE,  # type: Check.Value
    ):
        # type: (...) -> None
        """Package the PEX application.

        By default, the PEX is packaged as a zipapp for ease of shipping as a single file, but it
        can also be packaged in spread mode for efficiency of syncing over the network
        incrementally.

        :param path: The path where the PEX should be stored.
        :param bytecode_compile: If True, precompile .py files into .pyc files.
        :param deterministic: If True, will use our hardcoded time for zipfile timestamps.
        :param layout: The layout to use for the PEX.
        :param compress: Whether to compress zip entries when building to a layout that uses zip
                         files.
        :param check: The check to perform on the built PEX.
        If the PEXBuilder is not yet frozen, it will be frozen by ``build``.  This renders the
        PEXBuilder immutable.
        """
        if not self._frozen:
            self.freeze(bytecode_compile=bytecode_compile)

        # The PEX building proceeds assuming a user will not race themselves building to a single
        # non-PEX_ROOT output path they requested;
        tmp_pex = path + "~"
        if os.path.exists(tmp_pex):
            self._logger.warning("Previous binary unexpectedly exists, cleaning: {}".format(path))
            if os.path.isfile(tmp_pex):
                os.unlink(tmp_pex)
            else:
                shutil.rmtree(tmp_pex, True)

        if layout == Layout.LOOSE:
            shutil.copytree(
                self.path(),
                tmp_pex,
                ignore=None if bytecode_compile else lambda _, names: filter(is_pyc_file, names),
            )
        elif layout == Layout.PACKED:
            self._build_packedapp(
                dirname=tmp_pex,
                deterministic=deterministic,
                compress=compress,
                bytecode_compile=bytecode_compile,
            )
        else:
            self._build_zipapp(
                filename=tmp_pex,
                deterministic=deterministic,
                compress=compress,
                bytecode_compile=bytecode_compile,
            )
        if layout in (Layout.LOOSE, Layout.PACKED):
            pex_script = os.path.join(tmp_pex, "pex")
            if self._header:
                main_py = os.path.join(tmp_pex, "__main__.py")
                with open(pex_script, "w") as script_fp:
                    print(self._shebang, file=script_fp)
                    print(self._header, file=script_fp)
                    with open(main_py) as main_fp:
                        main_fp.readline()  # Throw away shebang line.
                        shutil.copyfileobj(main_fp, script_fp)
                chmod_plus_x(pex_script)
                safe_rename(pex_script, main_py)
            safe_symlink("__main__.py", pex_script)

        if os.path.isdir(path):
            shutil.rmtree(path, True)
        elif os.path.isdir(tmp_pex):
            safe_delete(path)
        check.perform_check(layout, tmp_pex)
        safe_rename(tmp_pex, path)

    def set_sh_boot_script(
        self,
        pex_name,  # type: str
        targets,  # type: Targets
        python_shebang,  # type: Optional[str]
        layout=Layout.ZIPAPP,  # type: Layout.Value
    ):
        if not self._frozen:
            raise Exception("Generating a sh_boot script requires the pex to be frozen.")

        script = create_sh_boot_script(
            pex_name=pex_name,
            pex_info=self._pex_info,
            targets=targets,
            interpreter=self.interpreter,
            python_shebang=python_shebang,
            layout=layout,
        )
        if layout is Layout.ZIPAPP:
            self.set_shebang("/bin/sh")
            self.set_header(script)
        else:
            shebang, header = create_sh_python_redirector_shebang(script)
            self.set_shebang(shebang)
            self.set_header(header)

    def _build_packedapp(
        self,
        dirname,  # type: str
        deterministic=False,  # type: bool
        compress=True,  # type: bool
        bytecode_compile=False,  # type: bool
    ):
        # type: (...) -> None

        pex_info = self._pex_info.copy()
        pex_info.update(PexInfo.from_env())

        # Include user sources, PEX-INFO and __main__ as loose files in src/.
        for fileset in ("executable", "importhook", "main", "manifest", "resource", "source"):
            for f in self._chroot.filesets.get(fileset, ()):
                dest = os.path.join(dirname, f)
                safe_mkdir(os.path.dirname(dest))
                safe_copy(os.path.realpath(os.path.join(self._chroot.chroot, f)), dest)

        # Zip up the bootstrap which is constant for a given version of Pex.
        if pex_info.bootstrap_hash is None:
            raise AssertionError(
                "Expected bootstrap_hash to be populated for {}.".format(self._pex_info)
            )
        cached_bootstrap_zip_dir = BootstrapZipDir.create(
            pex_info.bootstrap_hash, compress=compress, pex_root=pex_info.pex_root
        )
        with TRACER.timed("Zipping PEX .bootstrap/ code."):
            with atomic_directory(cached_bootstrap_zip_dir) as atomic_bootstrap_zip_dir:
                if not atomic_bootstrap_zip_dir.is_finalized():
                    self._chroot.zip(
                        os.path.join(atomic_bootstrap_zip_dir.work_dir, pex_info.bootstrap),
                        deterministic=deterministic,
                        exclude_file=is_pyc_temporary_file if bytecode_compile else is_pyc_file,
                        strip_prefix=pex_info.bootstrap,
                        labels=("bootstrap",),
                        compress=compress,
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
            with TRACER.timed(
                "{action} {count} distributions.".format(
                    action="Copying" if pex_info.deps_are_wheel_files else "Zipping",
                    count=len(pex_info.distributions),
                )
            ):
                for location, fingerprint in pex_info.distributions.items():
                    dest = os.path.join(internal_cache, location)
                    if pex_info.deps_are_wheel_files:
                        for path in self._chroot.filesets[location]:
                            safe_copy(os.path.join(self._chroot.chroot, path), dest)
                    else:
                        cached_installed_wheel_zip_dir = PackedWheelDir.create(
                            fingerprint, compress, pex_root=pex_info.pex_root
                        )
                        with atomic_directory(cached_installed_wheel_zip_dir) as atomic_zip_dir:
                            if not atomic_zip_dir.is_finalized():
                                self._chroot.zip(
                                    os.path.join(atomic_zip_dir.work_dir, location),
                                    deterministic=deterministic,
                                    exclude_file=(
                                        is_pyc_temporary_file if bytecode_compile else is_pyc_file
                                    ),
                                    strip_prefix=os.path.join(pex_info.internal_cache, location),
                                    labels=(location,),
                                    compress=compress,
                                )
                        safe_copy(os.path.join(cached_installed_wheel_zip_dir, location), dest)

    def _build_zipapp(
        self,
        filename,  # type: str
        deterministic=False,  # type: bool
        compress=True,  # type: bool
        bytecode_compile=False,  # type: bool
    ):
        # type: (...) -> None
        with safe_open(filename, "wb") as pexfile:
            assert os.path.getsize(pexfile.name) == 0
            pexfile.write(to_bytes("{}\n".format(self._shebang)))
            if self._header:
                pexfile.write(to_bytes(self._header))
        with TRACER.timed("Zipping PEX file."):
            self._chroot.zip(
                filename,
                mode="a",
                deterministic=deterministic,
                # When configured with a `copy_mode` of `CopyMode.SYMLINK`, we symlink distributions
                # as pointers to installed wheel directories in <PEX_ROOT>/installed_wheels/...
                # Since those installed wheels reside in a shared cache, they can be in-use by other
                # processes and so their code may be in the process of being bytecode compiled as we
                # attempt to zip up our chroot. Bytecode compilation produces ephemeral temporary
                # pyc files that we should avoid copying since they are useless and inherently
                # racy.
                exclude_file=is_pyc_temporary_file if bytecode_compile else is_pyc_file,
                compress=compress,
            )
        chmod_plus_x(filename)
