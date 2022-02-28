# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import base64
import csv
import fileinput
import hashlib
import json
import os
import sys
from contextlib import closing
from fileinput import FileInput

from pex import dist_metadata
from pex.common import is_python_script
from pex.compatibility import MODE_READ_UNIVERSAL_NEWLINES, PY2, get_stdout_bytes_buffer, urlparse
from pex.enum import Enum
from pex.third_party.pkg_resources import Distribution, EntryPoint
from pex.typing import TYPE_CHECKING, cast
from pex.util import CacheHelper

if TYPE_CHECKING:
    if PY2:
        from hashlib import _hash as _Hash
    else:
        from hashlib import _Hash
    from typing import Callable, Dict, Iterable, Iterator, Optional, Protocol, Tuple, Union

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
    path = attr.ib()  # type: str
    hash = attr.ib(default=None)  # type: Optional[Hash]
    size = attr.ib(default=None)  # type: Optional[int]


class InstallationScheme(Enum["InstallationScheme.Value"]):
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
        return cls(
            project_name=dist.project_name,
            version=dist.version,
            base_location=dist.location,
            relative_path=relative_path,
            metadata_listing=tuple(
                path for path in listing if metadata_dir == os.path.dirname(path)
            ),
            install_scheme=install_scheme,
        )

    project_name = attr.ib()  # type: str
    version = attr.ib()  # type: str
    base_location = attr.ib()  # type: str
    relative_path = attr.ib()  # type: str
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
