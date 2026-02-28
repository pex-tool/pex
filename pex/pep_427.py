# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import errno
import itertools
import json
import os.path
import re
import shutil
import subprocess
import time
import zipfile

from pex import pex_warnings
from pex.common import (
    CopyMode,
    ZipFileType,
    deterministic_walk,
    open_zip,
    safe_copy,
    safe_mkdir,
    safe_mkdtemp,
    safe_open,
    safe_relative_symlink,
    safe_rmtree,
    touch,
)
from pex.compatibility import commonpath, string
from pex.dist_metadata import DistMetadata, Distribution, MetadataFiles
from pex.entry_points_txt import install_scripts
from pex.enum import Enum
from pex.exceptions import production_assert, reportable_unexpected_error_msg
from pex.executables import chmod_plus_x, is_python_script
from pex.installed_wheel import InstalledWheel
from pex.interpreter import PythonInterpreter
from pex.pep_376 import InstalledDirectory, InstalledFile, Record, create_installed_file
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.sysconfig import SCRIPT_DIR, SysPlatform
from pex.typing import TYPE_CHECKING, cast
from pex.venv.virtualenv import Virtualenv
from pex.wheel import Wheel

if TYPE_CHECKING:
    from typing import (  # noqa
        Any,
        Callable,
        DefaultDict,
        Dict,
        Iterable,
        Iterator,
        List,
        Mapping,
        Optional,
        Set,
        Text,
        Tuple,
        Union,
    )

    import attr  # vendor:skip

    from pex.installed_wheel import InstalledWheel  # noqa
else:
    from pex.third_party import attr


class WheelError(Exception):
    """Indicates an error interacting with a wheel."""


class InstallableType(Enum["InstallableType.Value"]):
    class Value(Enum.Value):
        pass

    INSTALLED_WHEEL_CHROOT = Value("installed-wheel-chroot")
    WHEEL_FILE = Value(".whl-file")


InstallableType.seal()


def _headers_install_path_for_wheel(
    base,  # type: str
    wheel,  # type: Wheel
):
    # type: (...) -> str

    major = "X"  # type: Any
    minor = "Y"  # type: Any
    compatible_python_versions = tuple(frozenset(wheel.iter_compatible_python_versions()))
    if len(compatible_python_versions) == 1 and len(compatible_python_versions[0]) >= 2:
        major, minor = compatible_python_versions[0][:2]

    return _headers_install_path(base, version=(major, minor), project_name=wheel.project_name)


def _headers_install_path(
    base,  # type: str
    version,  # type: Tuple[Any, Any]
    project_name,  # type: ProjectName
):
    # type: (...) -> str

    # N.B.: You'd think sysconfig_paths["include"] would be the right answer here but both
    # `pip`, and by emulation, `uv pip`, use `<venv>/include/site/pythonX.Y/<project name>`.
    #
    # The "mess" is admitted and described at length here:
    # + https://discuss.python.org/t/clarification-on-a-wheels-header-data/9305
    # + https://discuss.python.org/t/deprecating-the-headers-wheel-data-key/23712
    #
    # Both discussions died out with no path resolved to clean up the mess.

    return os.path.join(
        base,
        "include",
        "site",
        "python{major}.{minor}".format(major=version[0], minor=version[1]),
        project_name.raw,
    )


@attr.s(frozen=True)
class InstallPaths(object):

    CHROOT_STASH = ".prefix"

    @classmethod
    def chroot(
        cls,
        destination,  # type: str
        wheel,  # type: Wheel
    ):
        # type: (...) -> InstallPaths

        base = os.path.join(destination, cls.CHROOT_STASH)

        if wheel.root_is_purelib:
            purelib = destination
            platlib = os.path.join(base, "platlib")
            path_names = ("headers", "scripts", "platlib", "data", "purelib")
        else:
            purelib = os.path.join(base, "purelib")
            platlib = destination
            path_names = ("headers", "scripts", "purelib", "data", "platlib")

        return cls(
            purelib=purelib,
            platlib=platlib,
            headers=_headers_install_path_for_wheel(base, wheel),
            scripts=os.path.join(base, SCRIPT_DIR),
            data=os.path.join(base, "data"),
            path_names=path_names,
        )

    @classmethod
    def interpreter(
        cls,
        interpreter,  # type: PythonInterpreter
        project_name,  # type: ProjectName
        root_is_purelib,  # type: bool
    ):
        # type: (...) -> InstallPaths

        sysconfig_paths = interpreter.identity.paths

        if root_is_purelib:
            path_names = ("purelib", "platlib", "headers", "scripts", "data")
        else:
            path_names = ("platlib", "purelib", "headers", "scripts", "data")

        return cls(
            purelib=sysconfig_paths["purelib"],
            platlib=sysconfig_paths["platlib"],
            headers=_headers_install_path(
                interpreter.prefix,
                version=(interpreter.version[0], interpreter.version[1]),
                project_name=project_name,
            ),
            scripts=sysconfig_paths["scripts"],
            data=sysconfig_paths["data"],
            path_names=path_names,
        )

    @classmethod
    def flat(
        cls,
        destination,  # type: str
        wheel,  # type: Wheel
    ):
        # type: (...) -> InstallPaths
        return cls(
            purelib=destination,
            platlib=destination,
            headers=_headers_install_path_for_wheel(destination, wheel),
            scripts=os.path.join(destination, SCRIPT_DIR),
            data=destination,
            path_names=("headers", "scripts", "data", "purelib", "platlib"),
        )

    @classmethod
    def wheel(
        cls,
        destination,  # type: str
        wheel,  # type: Union[Wheel, InstallableWheel]
    ):
        # type: (...) -> InstallPaths

        data = os.path.join(
            destination, "{wheel_prefix}.data".format(wheel_prefix=wheel.wheel_prefix)
        )

        if wheel.root_is_purelib:
            purelib = destination
            platlib = os.path.join(data, "platlib")
            path_names = ("headers", "scripts", "platlib", "data", "purelib")
        else:
            purelib = os.path.join(data, "purelib")
            platlib = destination
            path_names = ("headers", "scripts", "purelib", "data", "platlib")

        return cls(
            purelib=purelib,
            platlib=platlib,
            headers=os.path.join(data, "headers"),
            scripts=os.path.join(data, "scripts"),
            data=os.path.join(data, "data"),
            path_names=path_names,
        )

    purelib = attr.ib()  # type: str
    platlib = attr.ib()  # type: str
    headers = attr.ib()  # type: str
    scripts = attr.ib()  # type: str
    data = attr.ib()  # type: str
    _path_names = attr.ib()  # type: Tuple[str, ...]

    def __getitem__(self, item):
        # type: (Text) -> str
        if "purelib" == item:
            return self.purelib
        elif "platlib" == item:
            return self.platlib
        elif "headers" == item:
            return self.headers
        elif "scripts" == item:
            return self.scripts
        elif "data" == item:
            return self.data
        raise KeyError("Not a known install path: {item}".format(item=item))

    def __iter__(self):
        # type: () -> Iterator[Tuple[str, str]]
        for path_name in self._path_names:
            yield path_name, self[path_name]

    def __str__(self):
        # type: () -> str
        return "\n".join(
            "{path}={value}".format(path=path_name, value=value) for path_name, value in self
        )


@attr.s(frozen=True)
class ZipEntryInfo(object):
    @classmethod
    def from_zip_info(
        cls,
        zip_info,  # type: zipfile.ZipInfo
        normalize_file_stat=False,  # type: bool
    ):
        # type: (...) -> ZipEntryInfo
        return cls(
            filename=zip_info.filename,
            date_time=zip_info.date_time,
            external_attr=(
                ZipFileType.from_zip_info(zip_info).deterministic_external_attr
                if normalize_file_stat
                else zip_info.external_attr
            ),
        )

    @classmethod
    def from_json(cls, data):
        # type: (Any) -> ZipEntryInfo

        if not isinstance(data, list) or not len(data) == 3:
            raise ValueError(
                "Invalid ZipEntryInfo JSON data. Expected a 3-item list, given {value} of type "
                "{type}.".format(value=data, type=type(data))
            )

        filename, date_time, external_attr = data
        if not isinstance(filename, string):
            raise ValueError(
                "Invalid ZipEntryInfo JSON data. Expected a `filename` string property; found "
                "{value} of type {type}.".format(value=filename, type=type(filename))
            )

        if (
            not isinstance(date_time, list)
            or not len(date_time) == 6
            or not all(isinstance(component, int) for component in date_time)
        ):
            raise ValueError(
                "Invalid ZipEntryInfo JSON data. Expected a `date_time` list of six integers "
                "property; found {value} of type {type}.".format(
                    value=date_time, type=type(date_time)
                )
            )

        if not isinstance(external_attr, int):
            raise ValueError(
                "Invalid ZipEntryInfo JSON data. Expected an `external_attr` integer property; "
                "found {value} of type {type}.".format(
                    value=external_attr, type=type(external_attr)
                )
            )

        return cls(
            filename=filename,
            date_time=cast("Tuple[int, int, int, int, int, int]", tuple(date_time)),
            external_attr=external_attr,
        )

    filename = attr.ib()  # type: Text
    date_time = attr.ib()  # type: Tuple[int, int, int, int, int, int]
    external_attr = attr.ib()  # type: int

    @property
    def is_dir(self):
        # type: () -> bool
        return self.filename.endswith("/")

    def date_time_as_struct_time(self):
        # type: () -> time.struct_time
        return time.struct_time(self.date_time + (0, 0, -1))

    def external_attr_as_stat_mode(self):
        # type: () -> int
        return self.external_attr >> 16

    def to_json(self):
        # type: () -> Any
        return self.filename, self.date_time, self.external_attr


@attr.s(frozen=True)
class ZipMetadata(object):
    FILENAME = "original-whl-info.json"

    @classmethod
    def from_zip(
        cls,
        filename,  # type: str
        info_list,  # type: Iterable[zipfile.ZipInfo]
        normalize_file_stat=False,  # type: bool
    ):
        # type: (...) -> ZipMetadata
        return cls(
            filename=os.path.basename(filename),
            entry_info=tuple(
                ZipEntryInfo.from_zip_info(zip_info, normalize_file_stat=normalize_file_stat)
                for zip_info in info_list
            ),
        )

    @classmethod
    def read(cls, wheel):
        # type: (Wheel) -> Optional[ZipMetadata]

        data = wheel.read_pex_metadata(cls.FILENAME)
        if not data:
            return None
        zip_metadata = json.loads(data)
        if not isinstance(zip_metadata, dict):
            raise ValueError(
                "Invalid ZipMetadata JSON data. Expected an object; found "
                "{value} of type {type}.".format(value=zip_metadata, type=type(zip_metadata))
            )

        filename = zip_metadata.pop("filename", None)
        if not isinstance(filename, string):
            raise ValueError(
                "Invalid ZipMetadata JSON data. Expected an object with a string-valued 'filename' "
                "property; instead found {value} of type {type}.".format(
                    value=zip_metadata, type=type(zip_metadata)
                )
            )

        entries = zip_metadata.pop("entries", None)
        if not isinstance(entries, list):
            raise ValueError(
                "Invalid ZipMetadata JSON data. Expected an object with a list-valued 'entries' "
                "property; instead found {value} of type {type}.".format(
                    value=zip_metadata, type=type(zip_metadata)
                )
            )

        if zip_metadata:
            raise ValueError(
                "Invalid ZipMetadata JSON data. Unrecognized object keys: {keys}".format(
                    keys=", ".join(zip_metadata)
                )
            )

        return cls(
            filename=filename,
            entry_info=tuple(ZipEntryInfo.from_json(zip_entry_info) for zip_entry_info in entries),
        )

    filename = attr.ib()  # type: str
    entry_info = attr.ib()  # type: Tuple[ZipEntryInfo, ...]

    def __iter__(self):
        # type: () -> Iterator[ZipEntryInfo]
        return iter(self.entry_info)

    def write(
        self,
        dest,  # type: str
        wheel,  # type: Wheel
    ):
        # type: (...) -> str
        path = os.path.join(dest, wheel.pex_metadata_path(self.FILENAME))
        with safe_open(path, "w") as fp:
            json.dump(
                {
                    "filename": self.filename,
                    "entries": [entry_info.to_json() for entry_info in self.entry_info],
                },
                fp,
                sort_keys=True,
                separators=(",", ":"),
            )
        return path


@attr.s(frozen=True)
class InstallableWheel(object):
    @classmethod
    def from_whl(
        cls,
        whl,  # type: Union[str, Wheel]
        install_paths=None,  # type: Optional[InstallPaths]
    ):
        # type: (...) -> InstallableWheel
        wheel = whl if isinstance(whl, Wheel) else Wheel.load(whl)
        zip_metadata = ZipMetadata.read(wheel)
        return cls(wheel=wheel, install_paths=install_paths, zip_metadata=zip_metadata)

    @classmethod
    def from_installed_wheel(cls, installed_wheel):
        # type: (InstalledWheel) -> InstallableWheel
        wheel = Wheel.load(installed_wheel.prefix_dir)
        return cls.from_whl(
            whl=wheel, install_paths=InstallPaths.chroot(installed_wheel.prefix_dir, wheel=wheel)
        )

    wheel = attr.ib()  # type: Wheel
    is_whl = attr.ib(init=False)  # type: bool
    install_paths = attr.ib(default=None)  # type: Optional[InstallPaths]
    zip_metadata = attr.ib(default=None)  # type: Optional[ZipMetadata]

    def record_zip_metadata(self, dest):
        # type: (str) -> Optional[str]
        if self.zip_metadata:
            return self.zip_metadata.write(dest, self.wheel)
        return None

    @property
    def project_name(self):
        # type: () -> ProjectName
        return self.wheel.project_name

    @property
    def version(self):
        # type: () -> Version
        return self.wheel.version

    def __attrs_post_init__(self):
        # type: () -> None
        is_whl = zipfile.is_zipfile(self.wheel.location)

        if is_whl and self.install_paths:
            raise ValueError(
                "A wheel file should have no installed paths but given the following paths for "
                "{wheel}:\n"
                "{install_paths}".format(
                    wheel=self.wheel.location, install_paths=self.install_paths
                )
            )

        if not is_whl and not self.install_paths:
            raise ValueError(
                "The wheel for {source} is installed but not given its install paths".format(
                    source=self.source
                )
            )

        object.__setattr__(self, "is_whl", is_whl)

    def iter_install_paths_by_name(self):
        # type: () -> Iterator[Tuple[str, str]]
        if self.install_paths:
            for path_name, path in self.install_paths:
                yield path_name, path

    @property
    def location(self):
        # type: () -> str
        return self.wheel.location

    @property
    def source(self):
        # type: () -> str
        return self.wheel.source

    @property
    def metadata_files(self):
        # type: () -> MetadataFiles
        return self.wheel.metadata_files

    @property
    def root_is_purelib(self):
        # type: () -> bool
        return self.wheel.root_is_purelib

    @property
    def data_dir(self):
        # type: () -> str
        return self.wheel.data_dir

    @property
    def wheel_prefix(self):
        # type: () -> str
        return self.wheel.wheel_prefix

    @property
    def wheel_file_name(self):
        # type: () -> str
        return self.zip_metadata.filename if self.zip_metadata else self.wheel.wheel_file_name

    def dist_metadata(self):
        # type: () -> DistMetadata
        return self.wheel.dist_metadata()

    def metadata_path(self, *components):
        # type: (*str) -> str
        return self.wheel.metadata_path(*components)

    def distribution(self):
        # type: () -> Distribution
        return Distribution(location=self.location, metadata=self.dist_metadata())

    def pex_metadata_path(self, *components):
        # type: (*str) -> str
        return self.wheel.pex_metadata_path(*components)


class WheelInstallError(WheelError):
    """Indicates an error installing a `.whl` file."""


def reinstall_flat(
    installed_wheel,  # type: InstalledWheel
    target_dir,  # type: str
    copy_mode=CopyMode.LINK,  # type: CopyMode.Value
):
    # type: (...) -> Iterator[Tuple[Text, Text]]
    """Re-installs the installed wheel in a flat target directory.

    N.B.: A record of reinstalled files is returned in the form of an iterator that must be
    consumed to drive the installation to completion.

    If there is an error re-installing a file due to it already existing in the target
    directory, the error is suppressed, and it's expected that the caller detects this by
    comparing the record of installed files against those installed previously.

    :return: An iterator over src -> dst pairs.
    """
    for src, dst in install_wheel_flat(
        wheel=InstallableWheel.from_installed_wheel(installed_wheel),
        destination=target_dir,
        copy_mode=copy_mode,
    ):
        yield src, dst


def reinstall_venv(
    installed_wheel,  # type: InstalledWheel
    venv,  # type: Virtualenv
    copy_mode=CopyMode.LINK,  # type: CopyMode.Value
    rel_extra_path=None,  # type: Optional[str]
    hermetic_scripts=False,  # type: bool
):
    # type: (...) -> Iterator[Tuple[Text, Text]]
    """Re-installs the installed wheel in a venv.

    N.B.: A record of reinstalled files is returned in the form of an iterator that must be
    consumed to drive the installation to completion.

    If there is an error re-installing a file due to it already existing in the destination
    venv, the error is suppressed, and it's expected that the caller detects this by comparing
    the record of installed files against those installed previously.

    :return: An iterator over src -> dst pairs.
    """

    for src, dst in install_wheel_interpreter(
        wheel=InstallableWheel.from_installed_wheel(installed_wheel),
        interpreter=venv.interpreter,
        copy_mode=copy_mode,
        rel_extra_path=rel_extra_path,
        compile=False,
        hermetic_scripts=hermetic_scripts,
    ):
        yield src, dst


def repack(
    installed_wheel,  # type: InstalledWheel
    dest_dir,  # type: str
    use_system_time=False,  # type: bool
    override_wheel_file_name=None,  # type: Optional[str]
):
    # type: (...) -> str
    return create_whl(
        wheel=InstallableWheel.from_installed_wheel(installed_wheel),
        destination=dest_dir,
        use_system_time=use_system_time,
        override_wheel_file_name=override_wheel_file_name,
    )


def install_wheel_chroot(
    wheel,  # type: Union[str, InstallableWheel]
    destination,  # type: str
    normalize_file_stat=False,  # type: bool
    re_hash=False,  # type: bool
):
    # type: (...) -> InstalledWheel

    wheel_to_install = (
        wheel if isinstance(wheel, InstallableWheel) else InstallableWheel.from_whl(wheel)
    )
    chroot_install_paths = InstallPaths.chroot(destination, wheel=wheel_to_install.wheel)
    install_wheel(
        wheel_to_install,
        chroot_install_paths,
        record_entry_info=True,
        normalize_file_stat=normalize_file_stat,
        re_hash=re_hash,
    )

    record_relpath = wheel_to_install.metadata_files.metadata_file_rel_path("RECORD")
    assert (
        record_relpath is not None
    ), "The {module}.install_wheel function should always create a RECORD.".format(module=__name__)

    root_is_purelib = wheel_to_install.root_is_purelib

    entry_names = ("purelib", "platlib") if root_is_purelib else ("platlib", "purelib")
    sys_path_entries = []  # type: List[str]
    for entry_name in entry_names:
        entry = chroot_install_paths[entry_name]
        if os.path.isdir(entry):
            sys_path_entries.append(os.path.relpath(entry, destination))

    return InstalledWheel.save(
        prefix_dir=destination,
        stash_dir=InstallPaths.CHROOT_STASH,
        record_relpath=record_relpath,
        root_is_purelib=root_is_purelib,
        sys_path_entries=tuple(sys_path_entries),
    )


def install_wheel_interpreter(
    wheel,  # type: Union[str, InstallableWheel]
    interpreter,  # type: PythonInterpreter
    copy_mode=CopyMode.LINK,  # type: CopyMode.Value
    rel_extra_path=None,  # type: Optional[str]
    compile=True,  # type: bool
    requested=True,  # type: bool
    hermetic_scripts=False,  # type: bool
):
    # type: (...) -> Tuple[Tuple[Text, Text], ...]

    wheel_to_install = (
        wheel if isinstance(wheel, InstallableWheel) else InstallableWheel.from_whl(wheel)
    )
    return install_wheel(
        wheel_to_install,
        InstallPaths.interpreter(
            interpreter,
            project_name=wheel_to_install.project_name,
            root_is_purelib=wheel_to_install.root_is_purelib,
        ),
        copy_mode=copy_mode,
        interpreter=interpreter,
        rel_extra_path=rel_extra_path,
        compile=compile,
        requested=requested,
        record_entry_info=True,
        hermetic_scripts=hermetic_scripts,
    )


def install_wheel_flat(
    wheel,  # type: Union[str, InstallableWheel]
    destination,  # type: str
    copy_mode=CopyMode.LINK,  # type: CopyMode.Value
    compile=False,  # type: bool
):
    # type: (...) -> Tuple[Tuple[Text, Text], ...]

    wheel_to_install = (
        wheel if isinstance(wheel, InstallableWheel) else InstallableWheel.from_whl(wheel)
    )
    return install_wheel(
        wheel_to_install,
        InstallPaths.flat(destination, wheel=wheel_to_install.wheel),
        copy_mode=copy_mode,
        compile=compile,
    )


def create_whl(
    wheel,  # type: Union[str, InstallableWheel]
    destination,  # type: str
    compile=False,  # type: bool
    use_system_time=False,  # type: bool
    override_wheel_file_name=None,  # type: Optional[str]
):
    # type: (...) -> str

    if not isinstance(wheel, InstallableWheel) and zipfile.is_zipfile(wheel):
        wheel_dst = os.path.join(destination, os.path.basename(wheel))
        safe_copy(wheel, wheel_dst)
        return wheel_dst

    wheel_to_create = (
        wheel if isinstance(wheel, InstallableWheel) else InstallableWheel.from_whl(wheel)
    )
    whl_file_name = override_wheel_file_name or wheel_to_create.wheel_file_name
    whl_chroot = os.path.join(safe_mkdtemp(prefix="pex_create_whl."), whl_file_name)
    install_wheel(
        wheel_to_create,
        InstallPaths.wheel(destination=whl_chroot, wheel=wheel_to_create),
        compile=compile,
        install_entry_point_scripts=False,
    )
    record_data = Wheel.load(whl_chroot).metadata_files.read("RECORD")
    if record_data is None:
        raise AssertionError(reportable_unexpected_error_msg())

    wheel_path = os.path.join(destination, whl_file_name)
    with open_zip(wheel_path, "w") as zip_fp:
        if use_system_time and wheel_to_create.zip_metadata:
            for zip_entry_info in wheel_to_create.zip_metadata:
                src = os.path.join(whl_chroot, zip_entry_info.filename)
                if not os.path.exists(src):
                    production_assert(
                        zip_entry_info.is_dir,
                        "The wheel entry {filename} is unexpectedly missing from {source}.",
                        filename=zip_entry_info.filename,
                        source=wheel_to_create.source,
                    )
                    safe_mkdir(src)
                zip_fp.write_ex(
                    src,
                    zip_entry_info.filename,
                    date_time=zip_entry_info.date_time_as_struct_time(),
                    file_mode=zip_entry_info.external_attr_as_stat_mode(),
                )
        else:
            for installed_file in Record.read(lines=iter(record_data.decode("utf-8").splitlines())):
                path = (
                    installed_file.dir_info.path
                    if isinstance(installed_file, InstalledDirectory)
                    else installed_file.path
                )
                src = os.path.join(whl_chroot, path)
                if not os.path.exists(src):
                    production_assert(
                        isinstance(installed_file, InstalledDirectory),
                        "The wheel entry {filename} is unexpectedly missing from {source}.",
                        filename=path,
                        source=wheel_to_create.source,
                    )
                    safe_mkdir(src)
                if use_system_time:
                    zip_fp.write(src, path)
                else:
                    zip_fp.write_deterministic(src, path)
    return wheel_path


def _detect_record_eol(path):
    # type: (Text) -> str

    with open(path, "rb") as fp:
        line = fp.readline()
    return "\r\n" if line.endswith(b"\r\n") else "\n"


def _iter_installed_files(
    chroot,  # type: str
    exclude_rel_paths=(),  # type: Iterable[str]
):
    # type: (...) -> Iterator[InstalledFile]
    exclude = frozenset(exclude_rel_paths)
    for root, _, files in deterministic_walk(chroot):
        for path in files:
            rel_path = os.path.relpath(os.path.join(root, path), chroot)
            if rel_path in exclude:
                continue
            yield InstalledFile(rel_path)


def install_wheel(
    wheel,  # type: InstallableWheel
    install_paths,  # type: InstallPaths
    copy_mode=CopyMode.LINK,  # type: CopyMode.Value
    interpreter=None,  # type: Optional[PythonInterpreter]
    rel_extra_path=None,  # type: Optional[str]
    compile=False,  # type: bool
    requested=True,  # type: bool
    install_entry_point_scripts=True,  # type: bool
    record_entry_info=False,  # type: bool
    normalize_file_stat=False,  # type: bool
    re_hash=False,  # type: bool
    hermetic_scripts=False,  # type: bool
):
    # type: (...) -> Tuple[Tuple[Text, Text], ...]

    # See: https://packaging.python.org/en/latest/specifications/binary-distribution-format/#installing-a-wheel-distribution-1-0-py32-none-any-whl

    dest = install_paths.purelib if wheel.root_is_purelib else install_paths.platlib
    if rel_extra_path:
        dest = os.path.join(dest, rel_extra_path)
        if wheel.root_is_purelib:
            install_paths = attr.evolve(install_paths, purelib=dest)
        else:
            install_paths = attr.evolve(install_paths, platlib=dest)

    data_dir = None  # type: Optional[str]
    if wheel.is_whl:
        whl = wheel.location
        zip_metadata = None  # type: Optional[ZipMetadata]
        with open_zip(whl) as zf:
            # 1. Unpack
            zf.extractall(dest)
            data_dir = os.path.join(dest, wheel.data_dir)
            if record_entry_info:
                zip_metadata = ZipMetadata.from_zip(
                    filename=whl, info_list=zf.infolist(), normalize_file_stat=normalize_file_stat
                )

            # TODO(John Sirois): Consider verifying signatures.
            # N.B.: Pip does not and its also not clear what good this does. A zip can be easily
            # poked on a per-entry basis allowing forging a RECORD entry and its associated file.
            # Only an outer fingerprint of the whole wheel really solves this sort of tampering.

        unpacked_wheel = Wheel.load(dest, project_name=wheel.project_name)
        wheel = InstallableWheel(
            wheel=unpacked_wheel,
            install_paths=InstallPaths.wheel(dest, wheel=unpacked_wheel),
            zip_metadata=zip_metadata,
        )

        # Deal with bad whl `RECORD`s. We happen to hit one from selenium-4.1.2-py3-none-any.whl
        # in our tests. The selenium >=4,<4.1.3 wheels are all published with absolute paths for
        # all the .py file RECORD entries. The .dist-info and .data entries are fine though.
        record_data = wheel.metadata_files.read("RECORD")

        record_lines = []  # type: List[Text]
        eol = os.sep
        if record_data:
            record_lines = record_data.decode("utf-8").splitlines(
                True  #  N.B. no kw in 2.7: keepends=True
            )
            eol = "\r\n" if record_lines[0].endswith("\r\n") else "\n"

        if not record_data or any(
            os.path.isabs(
                installed_file.dir_info.path
                if isinstance(installed_file, InstalledDirectory)
                else installed_file.path
            )
            for installed_file in Record.read(lines=iter(record_lines))
        ):
            prefix = "The RECORD in {whl}".format(whl=os.path.basename(whl))
            suffix = "so wheel re-packing will not be round-trippable."
            if not record_data:
                pex_warnings.warn(
                    "{the_record} is missing; {and_so}.".format(the_record=prefix, and_so=suffix)
                )
            else:
                pex_warnings.warn(
                    "{the_record} has at least some invalid entries with absolute paths; "
                    "{and_so}.".format(the_record=prefix, and_so=suffix)
                )
            # Write a minimal repaired record to drive the spread operation below.
            Record.write(
                dst=os.path.join(dest, wheel.metadata_path("RECORD")),
                installed_files=list(_iter_installed_files(dest)),
                eol=eol,
            )

    if not wheel.install_paths:
        raise AssertionError(reportable_unexpected_error_msg())

    record_data = wheel.metadata_files.read("RECORD")
    if not record_data:
        try:
            installed_wheel = InstalledWheel.load(wheel.location)
        except InstalledWheel.LoadError:
            raise WheelInstallError(
                "Cannot re-install wheel for {source} because it has no installation RECORD "
                "metadata.".format(source=wheel.source)
            )
        else:
            # This is a legacy installed wheel layout with no RECORD; so we concoct one
            layout_file_rel_path = os.path.relpath(
                installed_wheel.layout_file(wheel.location), wheel.location
            )
            record_data = Record.write_bytes(
                installed_files=_iter_installed_files(
                    chroot=wheel.location, exclude_rel_paths=[layout_file_rel_path]
                )
            )

    # 2. Spread
    entry_points = wheel.distribution().get_entry_map()
    script_names = frozenset(
        SysPlatform.CURRENT.binary_name(script)
        for script in itertools.chain.from_iterable(
            entry_points.get(key, {}) for key in ("console_scripts", "gui_scripts")
        )
    )

    def is_entry_point_script(script_path):
        # type: (Text) -> bool
        return os.path.basename(script_path) in script_names

    record_relpath = wheel.metadata_path("RECORD")
    record_eol = os.linesep

    dist_info_dir_relpath = wheel.metadata_path()
    pex_info_dir_relpath = wheel.pex_metadata_path()
    installer_relpath = wheel.metadata_path("INSTALLER")
    requested_relpath = wheel.metadata_path("REQUESTED")
    zip_metadata_relpath = wheel.pex_metadata_path(ZipMetadata.FILENAME)

    installed_files = []  # type: List[Union[InstalledFile, InstalledDirectory]]
    provenance = []  # type: List[Tuple[Text, Text]]
    symlinked = set()  # type: Set[Tuple[Text, Text]]
    warned_bad_record = False
    for installed_file_or_dir in Record.read(lines=iter(record_data.decode("utf-8").splitlines())):
        if isinstance(installed_file_or_dir, InstalledDirectory):
            installed_files.append(installed_file_or_dir)
            continue

        installed_file = installed_file_or_dir
        if installed_file.path == record_relpath:
            record_eol = _detect_record_eol(os.path.join(wheel.location, installed_file.path))
            installed_files.append(InstalledFile(path=record_relpath, hash=None, size=None))
            # We'll generate these metadata files below as needed.
            continue
        if installed_file.path in (installer_relpath, requested_relpath, zip_metadata_relpath):
            # We'll generate these metadata files below as needed.
            continue

        if not compile and installed_file.path.endswith(".pyc"):
            continue

        src_file = os.path.normpath(os.path.join(wheel.location, installed_file.path))
        src_file_realpath = os.path.realpath(src_file)
        if not os.path.exists(src_file_realpath):
            if not warned_bad_record:
                pex_warnings.warn(
                    "The wheel {whl} has a bad RECORD. Skipping install of non-existent file "
                    "{path} and possibly others.".format(
                        whl=wheel.wheel_file_name, path=installed_file.path
                    )
                )
                warned_bad_record = True
            continue

        dst_components = None  # type: Optional[Tuple[Text, Text, bool]]
        for path_name, installed_path in wheel.iter_install_paths_by_name():
            installed_path = os.path.realpath(installed_path)

            src_path = None  # type: Optional[Text]
            if installed_path == commonpath((installed_path, src_file_realpath)):
                src_path = src_file_realpath
            elif installed_path == commonpath((installed_path, src_file)):
                src_path = src_file

            if src_path:
                rewrite_script = False
                if "scripts" == path_name:
                    if is_entry_point_script(src_path):
                        # This entry point script will be installed afresh below as needed.
                        break
                    rewrite_script = interpreter is not None and is_python_script(
                        src_path, check_executable=False
                    )

                dst_rel_path = os.path.relpath(src_path, installed_path)
                dst_components = path_name, dst_rel_path, rewrite_script
                break
        else:
            raise WheelInstallError(
                "Encountered a file from {source} with no identifiable target install path: "
                "{file}".format(source=wheel.source, file=installed_file.path)
            )
        if dst_components:
            dst_path_name, dst_rel_path, rewrite_script = dst_components
            dst_file = os.path.join(install_paths[dst_path_name], dst_rel_path)

            def create_dst_installed_file(regenerate_hash):
                # type: (bool) -> InstalledFile
                return (
                    create_installed_file(path=dst_file, dest_dir=dest)
                    if regenerate_hash
                    else InstalledFile(
                        path=os.path.relpath(dst_file, dest),
                        hash=installed_file.hash,
                        size=installed_file.size,
                    )
                )

            if rewrite_script and interpreter is not None:
                with open(src_file, mode="rb") as in_fp, safe_open(dst_file, "wb") as out_fp:
                    first_line = in_fp.readline()
                    if first_line and re.match(br"^#!pythonw?", first_line):
                        _, _, shebang_args = first_line.partition(b" ")
                        if hermetic_scripts and not shebang_args:
                            shebang_args = interpreter.hermetic_args.encode("utf-8")
                        encoding_line = ""
                        next_line = in_fp.readline()
                        # See: https://peps.python.org/pep-0263/
                        if next_line and re.match(
                            br"^[ \t\f]*#.*?coding[:=][ \t]*([-_.a-zA-Z0-9]+)", next_line
                        ):
                            encoding_line = str(next_line.decode("ascii"))
                        out_fp.write(
                            "{shebang}\n".format(
                                shebang=interpreter.shebang(
                                    args=shebang_args.decode("utf-8"), encoding_line=encoding_line
                                )
                            ).encode("utf-8")
                        )
                        if not encoding_line and next_line:
                            out_fp.write(next_line)
                    shutil.copyfileobj(in_fp, out_fp)
                chmod_plus_x(out_fp.name)

                # We modified the script shebang; so we need to re-hash / re-size.
                dst_installed_file = create_dst_installed_file(regenerate_hash=True)
            elif copy_mode is CopyMode.SYMLINK:
                top_level = dst_rel_path.split(os.sep)[0]
                if top_level in (dist_info_dir_relpath, pex_info_dir_relpath):
                    safe_relative_symlink(src_file, dst_file)
                elif (dst_path_name, top_level) not in symlinked:
                    top_level_src = os.path.join(wheel.install_paths[dst_path_name], top_level)
                    top_level_dst = os.path.join(install_paths[dst_path_name], top_level)
                    try:
                        safe_relative_symlink(top_level_src, top_level_dst)
                        symlinked.add((dst_path_name, top_level))
                    except OSError as e:
                        if e.errno != errno.EEXIST:
                            raise
                dst_installed_file = create_dst_installed_file(regenerate_hash=re_hash)
            else:
                safe_mkdir(os.path.dirname(dst_file))
                if copy_mode is CopyMode.LINK:
                    safe_copy(src_file, dst_file, overwrite=False)
                elif not os.path.exists(dst_file):
                    shutil.copy(src_file, dst_file)
                dst_installed_file = create_dst_installed_file(regenerate_hash=re_hash)
            installed_files.append(dst_installed_file)
            provenance.append((src_file, dst_file))
    if data_dir:
        safe_rmtree(data_dir)

    if compile:
        compile_target = interpreter or PythonInterpreter.get()
        args = [
            compile_target.binary,
            compile_target.hermetic_args,
            "-m",
            "compileall",
        ]  # type: List[Text]
        py_files = [
            os.path.join(dest, installed_file.path)
            for installed_file in installed_files
            if isinstance(installed_file, InstalledFile) and installed_file.path.endswith(".py")
        ]
        process = subprocess.Popen(
            args=args + py_files, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        _, stderr = process.communicate()
        if process.returncode != 0:
            pex_warnings.warn(
                "Failed to compile some .py files for install of {wheel} to {dest}:\n"
                "{stderr}".format(wheel=wheel.source, dest=dest, stderr=stderr.decode("utf-8"))
            )
        for root, _, files in os.walk(commonpath(py_files)):
            for f in files:
                if f.endswith(".pyc"):
                    file = InstalledFile(path=os.path.relpath(os.path.join(root, f), dest))
                    installed_files.append(file)

    if install_entry_point_scripts:
        for script_src, script_abspath in install_scripts(
            install_paths.scripts,
            entry_points,
            interpreter,
            overwrite=False,
            hermetic_scripts=hermetic_scripts,
        ):
            installed_files.append(create_installed_file(path=script_abspath, dest_dir=dest))
            provenance.append((script_src, script_abspath))

    if interpreter:
        # Finalize a proper venv install with INSTALLER and REQUESTED (if it was).
        with safe_open(os.path.join(dest, installer_relpath), "w") as fp:
            print("pex", file=fp)
        installed_files.append(create_installed_file(path=fp.name, dest_dir=dest))
        if requested:
            requested_path = os.path.join(dest, requested_relpath)
            touch(requested_path)
            installed_files.append(create_installed_file(path=requested_path, dest_dir=dest))

    if record_entry_info:
        zip_metadata_path = wheel.record_zip_metadata(dest)
        if zip_metadata_path:
            installed_files.append(create_installed_file(path=zip_metadata_path, dest_dir=dest))

    Record.write(
        dst=os.path.join(dest, record_relpath), installed_files=installed_files, eol=record_eol
    )

    return tuple(provenance)
