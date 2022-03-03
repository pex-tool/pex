# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import base64
import csv
import errno
import fileinput
import hashlib
import json
import os
import shutil
import sys
from contextlib import closing
from fileinput import FileInput

from pex import dist_metadata
from pex.common import is_python_script, safe_mkdir
from pex.compatibility import MODE_READ_UNIVERSAL_NEWLINES, PY2, get_stdout_bytes_buffer, urlparse
from pex.enum import Enum
from pex.orderedset import OrderedSet
from pex.third_party.pkg_resources import Distribution, EntryPoint
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    if PY2:
        from hashlib import _hash as _Hash
    else:
        from hashlib import _Hash
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
        # type: () -> _Hash
        return hashlib.new(self.algorithm)


@attr.s(frozen=True)
class Hash(object):
    value = attr.ib()  # type: str

    def __str__(self):
        # type: () -> str
        return self.value

    def parse(self):
        # type: () -> Digest
        algorithm, encoded_hash = self.value.split("=", 1)
        return Digest(algorithm=algorithm, encoded_hash=encoded_hash)


@attr.s(frozen=True)
class InstalledFile(object):
    """The record of a single installed file from a PEP 376 RECORD file.

    See: https://www.python.org/dev/peps/pep-0376/#record
    """

    path = attr.ib()  # type: str
    hash = attr.ib(default=None)  # type: Optional[Hash]
    size = attr.ib(default=None)  # type: Optional[int]


class InstallationScheme(Enum["InstallationScheme.Value"]):
    """Represents the Pip installation scheme used for installing a wheel.

    For more about installation schemes, see:
        https://docs.python.org/3/install/index.html#alternate-installation

    N.B.: Pex only uses the --target scheme but all schemes are represented for documentation
    purposes. Notably, Pex _could_ change to using the --prefix scheme with changes to its runtime
    `sys.path` adjustments in order to afford less hackery when reading the RECORD.
    """

    class Value(Enum.Value):
        pass

    PREFIX = Value("--prefix")
    ROOT = Value("--root")
    TARGET = Value("--target")
    USER = Value("--user")


class RecordError(Exception):
    pass


class ReinstallError(RecordError):
    """Indicates an error re-installing an installed distribution."""


class RecordNotFoundError(RecordError):
    """Indicates a distribution's RECORD metadata could not be found."""


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
    def load(
        cls,
        dist,  # type: Distribution
        install_scheme=InstallationScheme.TARGET,  # type: InstallationScheme.Value
    ):
        # type: (...) -> Record

        listing = [
            os.path.relpath(os.path.join(root, f), dist.location)
            for root, dirs, files in os.walk(dist.location)
            for f in files
        ]
        relative_path = dist_metadata.find_dist_info_file(
            project_name=dist.project_name, version=dist.version, filename="RECORD", listing=listing
        )
        if not relative_path:
            raise RecordNotFoundError(
                "Could not find the installation RECORD for {dist} at {location}".format(
                    dist=dist, location=dist.location
                )
            )
        metadata_dir = os.path.dirname(relative_path)
        data_dir = "{project_name_and_version}.data".format(
            project_name_and_version=metadata_dir[: -len(".dist-info")]
        )
        return cls(
            project_name=dist.project_name,
            version=dist.version,
            base_location=dist.location,
            relative_path=relative_path,
            data_dir=data_dir,
            metadata_listing=tuple(
                path for path in listing if metadata_dir == os.path.dirname(path)
            ),
            install_scheme=install_scheme,
        )

    project_name = attr.ib()  # type: str
    version = attr.ib()  # type: str
    base_location = attr.ib()  # type: str
    relative_path = attr.ib()  # type: str
    _data_dir = attr.ib()  # type: str
    _metadata_listing = attr.ib()  # type: Tuple[str, ...]
    install_scheme = attr.ib(default=InstallationScheme.TARGET)  # type: InstallationScheme.Value

    def _find_dist_info_file(self, filename):
        # type: (str) -> Optional[str]
        return dist_metadata.find_dist_info_file(
            project_name=self.project_name,
            version=self.version,
            filename=filename,
            listing=self._metadata_listing,
        )

    def fixup_install(self):
        # type: () -> None
        """Fixes a wheel install to be reproducible."""

        modified_scripts = list(self._fixup_scripts())
        self._fixup_record(modified_scripts=modified_scripts)

    def _fixup_scripts(self):
        # type: (...) -> Iterator[str]
        bin_dir = os.path.join(self.base_location, "bin")
        if not os.path.isdir(bin_dir):
            return

        console_scripts = {}  # type: Dict[str, EntryPoint]
        entry_points_relpath = self._find_dist_info_file("entry_points.txt")
        if entry_points_relpath:
            entry_points_abspath = os.path.join(self.base_location, entry_points_relpath)
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
                    yield os.path.relpath(script_fi.filename(), self.base_location)
                elif (
                    not first_non_shebang_line
                    or cast(bytes, line).strip() == first_non_shebang_line
                ):
                    # N.B.: These lines include the newline already.
                    buffer.write(cast(bytes, line))
                    first_non_shebang_line = None

    def _fixup_record(self, modified_scripts=None):
        # type: (Optional[Iterable[str]]) -> None

        record_abspath = os.path.join(self.base_location, self.relative_path)

        direct_url_relpath = self._find_dist_info_file("direct_url.json")
        if direct_url_relpath:
            direct_url_abspath = os.path.join(self.base_location, direct_url_relpath)
            with open(direct_url_abspath) as fp:
                if urlparse.urlparse(json.load(fp)["url"]).scheme == "file":
                    os.unlink(direct_url_abspath)

        to_rehash = {}
        if modified_scripts:
            for modified_script in modified_scripts:
                # N.B.: Pip installs wheels with RECORD entries like `../../bin/script` even when
                # it's called in `--target <dir>` mode which installs the script in `bin/script`.
                record_relpath = os.path.join(os.pardir, os.pardir, modified_script)
                modified_script_abspath = os.path.join(self.base_location, modified_script)
                to_rehash[record_relpath] = modified_script_abspath

        # The RECORD is a csv file with the path to each installed file in the 1st column.
        # See: https://www.python.org/dev/peps/pep-0376/#record
        with closing(
            fileinput.input(files=[record_abspath], inplace=True, mode=MODE_READ_UNIVERSAL_NEWLINES)
        ) as record_fi:
            csv_writer = None  # type: Optional[CSVWriter]
            for installed_file in Record.read(record_fi):
                if csv_writer is None:
                    # N.B.: The raw input lines include a newline that varies between '\r\n' and
                    # '\n' when the wheel was built from an sdist by Pip depending on whether the
                    # interpreter used was Python 2 or Python 3 respectively. As such, we normalize
                    # all RECORD files to use '\n' regardless of interpreter.
                    csv_writer = cast(
                        "CSVWriter",
                        csv.writer(sys.stdout, delimiter=",", quotechar='"', lineterminator="\n"),
                    )

                abspath_to_rehash = to_rehash.pop(installed_file.path, None)
                if installed_file.hash and abspath_to_rehash is not None:
                    digest = installed_file.hash.parse()
                    hasher = digest.new_hasher()
                    with open(abspath_to_rehash, "rb") as rehash_fp:
                        CacheHelper.update_hash(rehash_fp, digest=hasher)

                    fingerprint = base64.urlsafe_b64encode(hasher.digest()).decode("ascii")
                    de_padded, pad, rest = fingerprint.rpartition("=")
                    new_hash = str(de_padded if pad and not rest else fingerprint)
                    new_size = os.stat(abspath_to_rehash).st_size
                    csv_writer.writerow(
                        (
                            installed_file.path,
                            "{alg}={hash}".format(alg=digest.algorithm, hash=new_hash),
                            new_size,
                        )
                    )
                elif installed_file.path != direct_url_relpath:
                    csv_writer.writerow(
                        (
                            installed_file.path,
                            str(installed_file.hash) if installed_file.hash is not None else "",
                            str(installed_file.size) if installed_file.size is not None else "",
                        )
                    )

    def _handle_record_error(
        self,
        record_path,  # type: str
        error,  # type: Union[IOError, OSError]
        expected_errors=(errno.EEXIST,),  # type: Container[int]
    ):
        # type: (...) -> None
        if error.errno in expected_errors:
            return

        # It's expected that `*.data/*` dir entries won't exist. These entries are left in the
        # RECORD but the files they refer to are all "spread" to other locations during install.
        #
        # See: https://www.python.org/dev/peps/pep-0427/#installing-a-wheel-distribution-1-0-py32-none-any-whl
        if error.errno == errno.ENOENT and record_path.startswith(self._data_dir):
            return

        raise error

    def reinstall(
        self,
        venv,  # type: Virtualenv
        exclude=None,  # type: Optional[Callable[[str], bool]]
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

        if self.install_scheme is not InstallationScheme.TARGET:
            raise ReinstallError(
                "Cannot reinstall from {self}. It was installed via an unsupported scheme of "
                "`pip install {scheme}`.".format(self=self, scheme=self.install_scheme)
            )

        site_packages_dir = (
            os.path.join(venv.site_packages_dir, rel_extra_path)
            if rel_extra_path
            else venv.site_packages_dir
        )

        # N.B.: It's known that the Pip --target installation scheme results in faulty RECORD
        # entries. These are consistently faulty though; so we adjust here.
        # See: https://github.com/pypa/pip/issues/7658

        # I.E.: ../..
        scheme_prefix = os.path.join(os.path.pardir, os.path.pardir)
        # I.E.: 6 (../../)
        scheme_prefix_len = len(scheme_prefix) + len(os.path.sep)

        link = True
        symlinks = OrderedSet()  # type: OrderedSet[str]

        record_path = os.path.join(self.base_location, self.relative_path)
        with open(record_path, MODE_READ_UNIVERSAL_NEWLINES) as fp:
            for line, installed_file in enumerate(self.read(fp, exclude=exclude), start=1):
                if os.path.isabs(installed_file.path):
                    raise ReinstallError(
                        "Cannot re-install file from {record}:{line}, refusing to install to "
                        "absolute path {path}.".format(
                            record=record_path, line=line, path=installed_file.path
                        )
                    )
                if installed_file.path.startswith(scheme_prefix):
                    installed_file_relpath = installed_file.path[scheme_prefix_len:]
                    if installed_file_relpath.startswith(os.path.pardir):
                        raise ReinstallError(
                            "Cannot re-install file from {record}:{line}, path does not match "
                            "{scheme} scheme: {path}".format(
                                record=record_path,
                                line=line,
                                scheme=self.install_scheme,
                                path=installed_file.path,
                            )
                        )
                    dst = os.path.join(venv.venv_dir, installed_file_relpath)
                elif symlink:
                    top_level = installed_file.path.split(os.path.sep, 1)[0]
                    symlinks.add(top_level)
                    continue
                else:
                    installed_file_relpath = installed_file.path
                    dst = os.path.join(site_packages_dir, installed_file_relpath)

                src = os.path.join(self.base_location, installed_file_relpath)
                yield src, dst
                safe_mkdir(os.path.dirname(dst))
                try:
                    # We only try to link regular files since linking a symlink on Linux can produce
                    # another symlink, which leaves open the possibility the src target could later
                    # go missing leaving the dst dangling.
                    if link and not os.path.islink(src):
                        try:
                            os.link(src, dst)
                            continue
                        except OSError as e:
                            self._handle_record_error(
                                record_path=installed_file_relpath,
                                error=e,
                                expected_errors=(errno.EXDEV,),
                            )
                            link = False
                    shutil.copy(src, dst)
                except (IOError, OSError) as e:
                    self._handle_record_error(record_path=installed_file_relpath, error=e)

        for top_level in symlinks:
            src = os.path.join(self.base_location, top_level)
            dst = os.path.join(site_packages_dir, top_level)
            if not os.path.isdir(src):
                yield src, dst
            rel_src = os.path.relpath(src, site_packages_dir)
            safe_mkdir(site_packages_dir)
            try:
                os.symlink(rel_src, dst)
            except OSError as e:
                self._handle_record_error(record_path=top_level, error=e)
