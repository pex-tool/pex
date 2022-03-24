# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import base64
import csv
import errno
import fileinput
import hashlib
import itertools
import json
import os
import shutil
from contextlib import closing
from fileinput import FileInput

from pex import dist_metadata, hashing
from pex.common import (
    filter_pyc_dirs,
    filter_pyc_files,
    find_site_packages,
    is_python_script,
    safe_mkdir,
    safe_open,
)
from pex.compatibility import get_stdout_bytes_buffer, urlparse
from pex.interpreter import PythonInterpreter
from pex.third_party.pkg_resources import EntryPoint
from pex.typing import TYPE_CHECKING, cast
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import (
        Callable,
        Container,
        Dict,
        Iterable,
        Iterator,
        Optional,
        Protocol,
        Tuple,
        Union,
    )

    import attr  # vendor:skip

    from pex.hashing import Hasher

    class CSVWriter(Protocol):
        def writerow(self, row):
            # type: (Iterable[Union[str, int]]) -> None
            pass

else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Digest(object):
    algorithm = attr.ib()  # type: str
    encoded_hash = attr.ib()  # type: str

    def new_hasher(self):
        # type: () -> Hasher
        return hashlib.new(self.algorithm)


@attr.s(frozen=True)
class Hash(object):
    @classmethod
    def create(cls, hasher):
        # type: (Hasher) -> Hash

        # The fingerprint encoding is defined for PEP-376 RECORD files as `urlsafe-base64-nopad`
        # which is fully spelled out in code in PEP-427:
        # + https://peps.python.org/pep-0376/#record
        # + https://peps.python.org/pep-0427/#appendix
        fingerprint = base64.urlsafe_b64encode(hasher.digest()).rstrip(b"=")
        return cls(value="{alg}={hash}".format(alg=hasher.name, hash=fingerprint.decode("ascii")))

    value = attr.ib()  # type: str

    def __str__(self):
        # type: () -> str
        return self.value


def find_and_replace_path_components(
    path,  # type: str
    find,  # type: str
    replace,  # type: str
):
    # type: (...) -> str
    """Replace components of `path` that are exactly `find` with `replace`.

    >>> find_and_replace_path_components("foo/bar/baz", "bar", "spam")
    foo/spam/baz
    >>>
    """
    if not find or not replace:
        raise ValueError(
            "Both find and replace must be non-empty strings. Given find={find!r} "
            "replace={replace!r}".format(find=find, replace=replace)
        )
    if not path:
        return path

    components = []
    head = path
    while head:
        new_head, tail = os.path.split(head)
        if new_head == head:
            components.append(head)
            break
        components.append(tail)
        head = new_head
    components.reverse()
    return os.path.join(*(replace if component == find else component for component in components))


@attr.s(frozen=True)
class InstalledFile(object):
    """The record of a single installed file from a PEP 376 RECORD file.

    See: https://www.python.org/dev/peps/pep-0376/#record
    """

    _PYTHON_VER_PLACEHOLDER = "pythonX.Y"

    @staticmethod
    def _python_ver(interpreter=None):
        # type: (Optional[PythonInterpreter]) -> str
        python = interpreter or PythonInterpreter.get()
        return "python{major}.{minor}".format(major=python.version[0], minor=python.version[1])

    @classmethod
    def normalized_path(
        cls,
        path,  # type: str
        interpreter=None,  # type: Optional[PythonInterpreter]
    ):
        # type: (...) -> str
        return find_and_replace_path_components(
            path, cls._python_ver(interpreter=interpreter), cls._PYTHON_VER_PLACEHOLDER
        )

    @classmethod
    def denormalized_path(
        cls,
        path,  # type: str
        interpreter=None,  # type: Optional[PythonInterpreter]
    ):
        # type: (...) -> str
        return find_and_replace_path_components(
            path, cls._PYTHON_VER_PLACEHOLDER, cls._python_ver(interpreter=interpreter)
        )

    path = attr.ib()  # type: str
    hash = attr.ib(default=None)  # type: Optional[Hash]
    size = attr.ib(default=None)  # type: Optional[int]


class InstalledWheelError(Exception):
    pass


class LoadError(InstalledWheelError):
    """Indicates an installed wheel was not loadable at a particular path."""


class ReinstallError(InstalledWheelError):
    """Indicates an error re-installing an installed wheel."""


@attr.s(frozen=True)
class InstalledWheel(object):
    _LAYOUT_JSON_FILENAME = ".layout.json"

    @classmethod
    def layout_file(cls, prefix_dir):
        # type: (str) -> str
        return os.path.join(prefix_dir, cls._LAYOUT_JSON_FILENAME)

    @classmethod
    def save(
        cls,
        prefix_dir,  # type: str
        stash_dir,  # type: str
        record_relpath,  # type: str
    ):
        # type: (...) -> InstalledWheel
        layout = {"stash_dir": stash_dir, "record_relpath": record_relpath}
        with open(cls.layout_file(prefix_dir), "w") as fp:
            json.dump(layout, fp, sort_keys=True)
        return cls(prefix_dir=prefix_dir, stash_dir=stash_dir, record_relpath=record_relpath)

    @classmethod
    def load(cls, prefix_dir):
        # type: (str) -> InstalledWheel
        layout_file = cls.layout_file(prefix_dir)
        try:
            with open(layout_file) as fp:
                layout = json.load(fp)
        except (IOError, OSError) as e:
            raise LoadError(
                "Failed to load an installed wheel layout from {layout_file}: {err}".format(
                    layout_file=layout_file, err=e
                )
            )
        if not isinstance(layout, dict):
            raise LoadError(
                "The installed wheel layout file at {layout_file} must contain a single top-level "
                "object, found: {value}.".format(layout_file=layout_file, value=layout)
            )
        stash_dir = layout.get("stash_dir")
        record_relpath = layout.get("record_relpath")
        if not stash_dir or not record_relpath:
            raise LoadError(
                "The installed wheel layout file at {layout_file} must contain an object with both "
                "`stash_dir` and `record_relpath` attributes, found: {value}".format(
                    layout_file=layout_file, value=layout
                )
            )
        return cls(
            prefix_dir=prefix_dir,
            stash_dir=cast(str, stash_dir),
            record_relpath=cast(str, record_relpath),
        )

    prefix_dir = attr.ib()  # type: str
    stash_dir = attr.ib()  # type: str
    record_relpath = attr.ib()  # type: str

    def stashed_path(self, *components):
        # type: (*str) -> str
        return os.path.join(self.prefix_dir, self.stash_dir, *components)

    def reinstall(
        self,
        venv,  # type: Virtualenv
        symlink=False,  # type: bool
        rel_extra_path=None,  # type: Optional[str]
    ):
        # type: (...) -> Iterator[Tuple[str, str]]
        """Re-installs the installed wheel in a venv.

        N.B.: A record of reinstalled files is returned in the form of an iterator that must be
        consumed to drive the installation to completion.

        If there is an error re-installing a file due to it already existing in the destination
        venv, the error is suppressed, and it's expected that the caller detects this by comparing
        the record of installed files against those installed previously.

        :return: An iterator over src -> dst pairs.
        """

        site_packages_dir = (
            os.path.join(venv.site_packages_dir, rel_extra_path)
            if rel_extra_path
            else venv.site_packages_dir
        )

        installed_files = [InstalledFile(self.record_relpath)]
        for src, dst in itertools.chain(
            self._reinstall_stash(venv),
            self._reinstall_site_packages(site_packages_dir, symlink=symlink),
        ):
            hasher = hashlib.sha256()
            hashing.file_hash(dst, digest=hasher)
            installed_files.append(
                InstalledFile(
                    path=os.path.relpath(dst, site_packages_dir),
                    hash=Hash.create(hasher),
                    size=os.stat(dst).st_size,
                )
            )

            yield src, dst

        # The RECORD is a csv file with the path to each installed file in the 1st column.
        # See: https://www.python.org/dev/peps/pep-0376/#record
        with safe_open(os.path.join(site_packages_dir, self.record_relpath), "w") as fp:
            csv_writer = cast(
                "CSVWriter",
                csv.writer(fp, delimiter=",", quotechar='"', lineterminator="\n"),
            )
            for installed_file in sorted(installed_files, key=lambda installed: installed.path):
                csv_writer.writerow(attr.astuple(installed_file, recurse=False))

    def _reinstall_stash(self, venv):
        # type: (Virtualenv) -> Iterator[Tuple[str, str]]

        link = True
        stash_abs_path = os.path.join(self.prefix_dir, self.stash_dir)
        for root, dirs, files in os.walk(stash_abs_path, topdown=True, followlinks=True):
            for d in dirs:
                src_relpath = os.path.relpath(os.path.join(root, d), stash_abs_path)
                dst = InstalledFile.denormalized_path(
                    path=os.path.join(venv.venv_dir, src_relpath), interpreter=venv.interpreter
                )
                safe_mkdir(dst)

            for f in files:
                src = os.path.join(root, f)
                src_relpath = os.path.relpath(src, stash_abs_path)
                dst = InstalledFile.denormalized_path(
                    path=os.path.join(venv.venv_dir, src_relpath), interpreter=venv.interpreter
                )
                try:
                    # We only try to link regular files since linking a symlink on Linux can produce
                    # another symlink, which leaves open the possibility the src target could later
                    # go missing leaving the dst dangling.
                    if link and not os.path.islink(src):
                        try:
                            os.link(src, dst)
                            continue
                        except OSError as e:
                            if e.errno != errno.EXDEV:
                                raise e
                            link = False
                    shutil.copy(src, dst)
                except (IOError, OSError) as e:
                    if e.errno != errno.EEXIST:
                        raise e
                finally:
                    yield src, dst

    def _reinstall_site_packages(
        self,
        site_packages_dir,  # type: str
        symlink=False,  # type: bool
    ):
        # type: (...) -> Iterator[Tuple[str, str]]

        link = True
        for root, dirs, files in os.walk(self.prefix_dir, topdown=True, followlinks=True):
            if root == self.prefix_dir:
                dirs[:] = [d for d in filter_pyc_dirs(dirs) if d != self.stash_dir]
                files[:] = [f for f in filter_pyc_files(files) if f != self._LAYOUT_JSON_FILENAME]

            traverse = set(dirs)
            for path, is_dir in itertools.chain(
                zip(dirs, itertools.repeat(True)), zip(files, itertools.repeat(False))
            ):
                src_entry = os.path.join(root, path)
                dst_entry = os.path.join(
                    site_packages_dir, os.path.relpath(src_entry, self.prefix_dir)
                )
                try:
                    if symlink and not (
                        src_entry.endswith(".dist-info") and os.path.isdir(src_entry)
                    ):
                        dst_parent = os.path.dirname(dst_entry)
                        safe_mkdir(dst_parent)
                        rel_src = os.path.relpath(src_entry, dst_parent)
                        os.symlink(rel_src, dst_entry)
                        traverse.discard(path)
                    elif is_dir:
                        safe_mkdir(dst_entry)
                    else:
                        # We only try to link regular files since linking a symlink on Linux can
                        # produce another symlink, which leaves open the possibility the src_entry
                        # target could later go missing leaving the dst_entry dangling.
                        if link and not os.path.islink(src_entry):
                            try:
                                os.link(src_entry, dst_entry)
                                continue
                            except OSError as e:
                                if e.errno != errno.EXDEV:
                                    raise e
                                link = False
                        shutil.copy(src_entry, dst_entry)
                except (IOError, OSError) as e:
                    if e.errno != errno.EEXIST:
                        raise e
                finally:
                    if not is_dir:
                        yield src_entry, dst_entry

            dirs[:] = list(traverse)


class RecordError(Exception):
    pass


class RecordNotFoundError(RecordError):
    """Indicates a distribution's RECORD metadata could not be found."""


class UnrecognizedInstallationSchemeError(RecordError):
    """Indicates a distribution's RECORD was nested in an unrecognized installation scheme."""


@attr.s(frozen=True)
class Record(object):
    """Represents the PEP-376 RECORD of an installed wheel.

    See: https://www.python.org/dev/peps/pep-0376/#record
    """

    @classmethod
    def read(
        cls,
        lines,  # type: Union[FileInput[str], Iterator[str]]
        exclude=None,  # type: Optional[Callable[[str], bool]]
    ):
        # type: (...) -> Iterator[InstalledFile]

        # The RECORD is a csv file with the path to each installed file in the 1st column.
        # See: https://www.python.org/dev/peps/pep-0376/#record
        for line, (path, fingerprint, file_size) in enumerate(
            csv.reader(lines, delimiter=",", quotechar='"'), start=1
        ):
            resolved_path = path
            if exclude and exclude(resolved_path):
                continue
            file_hash = Hash(fingerprint) if fingerprint else None
            size = int(file_size) if file_size else None
            yield InstalledFile(path=path, hash=file_hash, size=size)

    @classmethod
    def from_prefix_install(
        cls,
        prefix_dir,  # type: str
        project_name,  # type: str
        version,  # type: str
    ):

        site_packages = find_site_packages(prefix_dir=prefix_dir)
        if site_packages is None:
            raise RecordNotFoundError(
                "Could not find a site-packages directory under installation prefix "
                "{prefix_dir}.".format(prefix_dir=prefix_dir)
            )

        site_packages_listing = [
            os.path.relpath(os.path.join(root, f), site_packages)
            for root, _, files in os.walk(site_packages)
            for f in files
        ]
        record_relative_path = dist_metadata.find_dist_info_file(
            project_name, version, filename="RECORD", listing=site_packages_listing
        )
        if not record_relative_path:
            raise RecordNotFoundError(
                "Could not find the installation RECORD for {project_name} {version} under "
                "{prefix_dir}".format(
                    project_name=project_name, version=version, prefix_dir=prefix_dir
                )
            )

        metadata_dir = os.path.dirname(record_relative_path)
        base_dir = os.path.relpath(site_packages, prefix_dir)
        return cls(
            project_name=project_name,
            version=version,
            prefix_dir=prefix_dir,
            rel_base_dir=base_dir,
            relative_path=record_relative_path,
            metadata_listing=tuple(
                path for path in site_packages_listing if metadata_dir == os.path.dirname(path)
            ),
        )

    project_name = attr.ib()  # type: str
    version = attr.ib()  # type: str
    prefix_dir = attr.ib()  # type: str
    rel_base_dir = attr.ib()  # type: str
    relative_path = attr.ib()  # type: str
    _metadata_listing = attr.ib()  # type: Tuple[str, ...]

    def _find_dist_info_file(self, filename):
        # type: (str) -> Optional[str]
        metadata_file = dist_metadata.find_dist_info_file(
            project_name=self.project_name,
            version=self.version,
            filename=filename,
            listing=self._metadata_listing,
        )
        if not metadata_file:
            return None
        return os.path.join(self.rel_base_dir, metadata_file)

    def fixup_install(
        self,
        exclude=(),  # type: Container[str]
        interpreter=None,  # type: Optional[PythonInterpreter]
    ):
        # type: (...) -> InstalledWheel
        """Fixes a wheel install to be reproducible and importable.

        After fixed up, this RECORD can be used to re-install the wheel in a venv with `reinstall`.

        :param exclude: Any top-level items to exclude.
        :param interpreter: The interpreter used to perform the wheel install.
        """
        self._fixup_scripts()
        self._fixup_direct_url()

        # The RECORD is unused in PEX zipapp mode and only needed in venv mode. Since it can contain
        # relative path entries that differ between interpreters - notably pypy for Python < 3.8 has
        # a custom scheme - we just delete the file and create it on-demand for venv re-installs.
        os.unlink(os.path.join(self.prefix_dir, self.rel_base_dir, self.relative_path))

        # An example of the installed wheel chroot we're aiming for:
        # .prefix/bin/...                    # scripts
        # .prefix/include/site/pythonX.Y/... # headers
        # .prefix/share/...                  # data files
        # greenlet/...                       # importables
        # greenlet-1.1.2.dist-info/...       # importables
        stash_dir = ".prefix"
        prefix_stash = os.path.join(self.prefix_dir, stash_dir)
        safe_mkdir(prefix_stash)

        # 1. Move everything into the stash.
        for item in os.listdir(self.prefix_dir):
            if stash_dir == item or item in exclude:
                continue
            shutil.move(os.path.join(self.prefix_dir, item), os.path.join(prefix_stash, item))
        # 2. Normalize all `*/{python ver}` paths to `*/pythonX.Y`
        for root, dirs, _ in os.walk(prefix_stash):
            dirs_to_scan = []
            for d in dirs:
                path = os.path.join(root, d)
                normalized_path = InstalledFile.normalized_path(path, interpreter=interpreter)
                if normalized_path != path:
                    shutil.move(path, normalized_path)
                else:
                    dirs_to_scan.append(d)
            dirs[:] = dirs_to_scan

        # 3. Move `site-packages` content back up to the prefix dir chroot so that content is
        # importable when this prefix dir chroot is added to the `sys.path` in PEX zipapp mode.
        importable_stash = InstalledFile.normalized_path(
            os.path.join(prefix_stash, self.rel_base_dir), interpreter=interpreter
        )
        for importable_item in os.listdir(importable_stash):
            shutil.move(
                os.path.join(importable_stash, importable_item),
                os.path.join(self.prefix_dir, importable_item),
            )
        os.rmdir(importable_stash)

        return InstalledWheel.save(
            prefix_dir=self.prefix_dir,
            stash_dir=stash_dir,
            record_relpath=self.relative_path,
        )

    def _fixup_scripts(self):
        # type: (...) -> None
        bin_dir = os.path.join(self.prefix_dir, "bin")
        if not os.path.isdir(bin_dir):
            return

        console_scripts = {}  # type: Dict[str, EntryPoint]
        entry_points_relpath = self._find_dist_info_file("entry_points.txt")
        if entry_points_relpath:
            entry_points_abspath = os.path.join(self.prefix_dir, entry_points_relpath)
            with open(entry_points_abspath) as fp:
                console_scripts.update(EntryPoint.parse_map(fp.read()).get("console_scripts", {}))

        scripts = {}  # type: Dict[str, Optional[bytes]]
        for script_name in os.listdir(bin_dir):
            script_path = os.path.join(bin_dir, script_name)
            if is_python_script(script_path):
                scripts[script_path] = None
            elif script_name in console_scripts:
                # When a wheel is installed by Pip and that wheel contains console_scripts, they are
                # normally written with a faux-shebang of:
                # #!python
                #
                # Pex relies on this hermetic shebang and only ever reifies it when creating venvs.
                #
                # If Pip is being run under a Python executable with a path length >127 characters
                # on Linux though, it writes a shebang / header of:
                # #!/bin/sh
                # '''exec' <too long path to Pip venv python> "$0" "$@"'
                # ' '''
                #
                # That header is immediately followed by the expected console_script shim contents:
                # # -*- coding: utf-8 -*-
                # import re
                # import sys
                # from <ep_module> import <ep_func>
                # if __name__ == '__main__':
                #     sys.argv[0] = re.sub(r'(-script\.pyw|\.exe)?$', '', sys.argv[0])
                #     sys.exit(main())
                #
                # Instead of guessing that 127 characters is the shebang length limit and using
                # Pip's safety-hatch `/bin/sh` trick, we forcibly re-write the header to be just the
                # expected `#!python` shebang. We detect the end of the header with the known 1st
                # line of console_script shim ~code defined in
                # pex/vendor/_vendored/pip/pip/_vendor/distlib/scripts.py on line 41:
                # https://github.com/pantsbuild/pex/blob/196b4cd5b8dd4b4af2586460530e9a777262be7d/pex/vendor/_vendored/pip/pip/_vendor/distlib/scripts.py#L41
                scripts[script_path] = b"# -*- coding: utf-8 -*-"
        if not scripts:
            return

        with closing(fileinput.input(files=scripts.keys(), inplace=True, mode="rb")) as script_fi:
            first_non_shebang_line = None  # type: Optional[bytes]
            for line in script_fi:
                buffer = get_stdout_bytes_buffer()
                if script_fi.isfirstline():
                    first_non_shebang_line = scripts[script_fi.filename()]
                    # Ensure python shebangs are reproducible. The only place these can be used is
                    # in venv mode PEXes where the `#!python` placeholder shebang will be re-written
                    # to use the venv's python interpreter.
                    buffer.write(b"#!python\n")
                elif (
                    not first_non_shebang_line
                    or cast(bytes, line).strip() == first_non_shebang_line
                ):
                    # N.B.: These lines include the newline already.
                    buffer.write(cast(bytes, line))
                    first_non_shebang_line = None

    def _fixup_direct_url(self):
        # type: () -> None
        direct_url_relpath = self._find_dist_info_file("direct_url.json")
        if direct_url_relpath:
            direct_url_abspath = os.path.join(self.prefix_dir, direct_url_relpath)
            with open(direct_url_abspath) as fp:
                if urlparse.urlparse(json.load(fp)["url"]).scheme == "file":
                    os.unlink(direct_url_abspath)
