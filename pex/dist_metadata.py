# coding=utf-8
# Copyright 2020 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import errno
import functools
import glob
import importlib
import itertools
import os
import sys
import tarfile
import zipfile
from collections import defaultdict
from contextlib import closing
from email.message import Message
from email.parser import Parser
from io import StringIO
from textwrap import dedent

from pex import pex_warnings, specifier_sets
from pex.common import open_zip, pluralize
from pex.compatibility import PY2, to_unicode
from pex.enum import Enum
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.third_party.packaging.markers import Marker
from pex.third_party.packaging.requirements import InvalidRequirement
from pex.third_party.packaging.requirements import Requirement as PackagingRequirement
from pex.third_party.packaging.specifiers import InvalidSpecifier, SpecifierSet
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import (
        Any,
        Callable,
        DefaultDict,
        Dict,
        FrozenSet,
        Iterable,
        Iterator,
        List,
        Optional,
        Text,
        Tuple,
        Union,
    )

    import attr  # vendor:skip

    from pex.pep_440 import ParsedVersion
else:
    from pex.third_party import attr


class MetadataError(Exception):
    """Indicates an error reading distribution metadata."""


class UnrecognizedDistributionFormat(MetadataError):
    """Indicates a distribution file is not of any recognized format."""


class AmbiguousDistributionError(MetadataError):
    """Indicates multiple distributions were detected at a given location but one was expected."""


class MetadataNotFoundError(MetadataError):
    """Indicates an expected metadata file could not be found for a given distribution."""


class InvalidMetadataError(MetadataError):
    """Indicates a metadata value that is invalid."""


def is_tar_sdist(path):
    # type: (Text) -> bool
    # N.B.: PEP-625 (https://peps.python.org/pep-0625/) says sdists must use .tar.gz, but we
    # have a known example of tar.bz2 in the wild in python-constraint 1.4.0 on PyPI:
    # https://pypi.org/project/python-constraint/1.4.0/#files
    # This probably all stems from the legacy `python setup.py sdist` as last described here:
    #   https://docs.python.org/3.11/distutils/sourcedist.html
    # There was a move to reject exotic formats in PEP-527 in 2016 and the historical sdist
    # formats appear to be listed here: https://peps.python.org/pep-0527/#file-extensions
    # A query on the PyPI dataset shows:
    #
    # SELECT
    # REGEXP_EXTRACT(path, r'\.([^.]+|tar\.[^.]+|tar)$') as extension,
    # count(*) as count
    # FROM `bigquery-public-data.pypi.distribution_metadata`
    # group by extension
    # order by count desc
    #
    #   | extension | count   |
    #   |-----------|---------|
    #   | whl       | 6332494 |
    # * | tar.gz    | 5283102 |
    #   | egg       |  135940 |
    # * | zip       |  108532 |
    #   | exe       |   18452 |
    # * | tar.bz2   |    3857 |
    #   | msi       |     625 |
    #   | rpm       |     603 |
    # * | tgz       |     226 |
    #   | dmg       |      47 |
    #   | deb       |      36 |
    # * | tar.zip   |       2 |
    # * | ZIP       |       1 |
    return path.lower().endswith((".tar.gz", ".tgz", ".tar.bz2"))


def is_zip_sdist(path):
    # type: (Text) -> bool
    return path.lower().endswith(".zip")


def is_sdist(path):
    # type: (Text) -> bool
    return is_tar_sdist(path) or is_zip_sdist(path)


def is_wheel(path):
    # type: (Text) -> bool
    return path.lower().endswith(".whl")


def _strip_sdist_path(sdist_path):
    # type: (Text) -> Optional[Text]
    if not is_sdist(sdist_path):
        return None

    sdist_basename = os.path.basename(sdist_path)
    filename, _ = os.path.splitext(sdist_basename)
    if filename.lower().endswith(".tar"):
        filename, _ = os.path.splitext(filename)
    return filename


def parse_message(message):
    # type: (bytes) -> Message
    return cast(Message, Parser().parse(StringIO(to_unicode(message))))


@attr.s(frozen=True)
class DistMetadataFile(object):
    type = attr.ib()  # type: MetadataType.Value
    location = attr.ib()  # type: Text
    rel_path = attr.ib()  # type: Text
    project_name = attr.ib()  # type: ProjectName
    version = attr.ib()  # type: Version
    pkg_info = attr.ib(eq=False)  # type: Message

    def render_description(self):
        # type: () -> str
        return "{project_name} {version} metadata from {rel_path} at {location}".format(
            project_name=self.project_name,
            version=self.version,
            rel_path=self.rel_path,
            location=self.location,
        )


@attr.s(frozen=True)
class MetadataFiles(object):
    metadata = attr.ib()  # type: DistMetadataFile
    _additional_metadata_files = attr.ib(default=())  # type: Tuple[Text, ...]
    _read_function = attr.ib(default=None)  # type: Optional[Callable[[Text], bytes]]

    def metadata_file_rel_path(self, metadata_file_name):
        # type: (Text) -> Optional[Text]
        for rel_path in self._additional_metadata_files:
            if os.path.basename(rel_path) == metadata_file_name:
                return rel_path
        return None

    def read(self, metadata_file_name):
        # type: (Text) -> Optional[bytes]
        rel_path = self.metadata_file_rel_path(metadata_file_name)
        if rel_path is None or self._read_function is None:
            return None
        return self._read_function(rel_path)


class MetadataType(Enum["MetadataType.Value"]):
    class Value(Enum.Value):
        def load_metadata(
            self,
            location,  # type: Text
            project_name=None,  # type: Optional[ProjectName]
            rescan=False,  # type: bool
        ):
            # type: (...) -> Optional[MetadataFiles]
            return load_metadata(
                location, project_name=project_name, restrict_types_to=(self,), rescan=rescan
            )

    DIST_INFO = Value(".dist-info")
    EGG_INFO = Value(".egg-info")
    PKG_INFO = Value("PKG-INFO")


MetadataType.seal()


@attr.s(frozen=True)
class MetadataKey(object):
    metadata_type = attr.ib()  # type: MetadataType.Value
    location = attr.ib()  # type: Text


def _find_installed_metadata_files(
    location,  # type: Text
    metadata_type,  # type: MetadataType.Value
    metadata_dir_glob,  # type: str
    metadata_file_name,  # type: Text
):
    # type: (...) -> Iterator[MetadataFiles]
    metadata_files = glob.glob(os.path.join(location, metadata_dir_glob, metadata_file_name))
    for path in metadata_files:
        with open(path, "rb") as fp:
            metadata = parse_message(fp.read())
            project_name_and_version = ProjectNameAndVersion.from_parsed_pkg_info(
                source=path, pkg_info=metadata
            )

            def read_function(rel_path):
                # type: (Text) -> bytes
                with open(os.path.join(location, rel_path), "rb") as fp:
                    return fp.read()

            yield MetadataFiles(
                metadata=DistMetadataFile(
                    type=metadata_type,
                    location=location,
                    rel_path=os.path.relpath(path, location),
                    project_name=project_name_and_version.canonicalized_project_name,
                    version=project_name_and_version.canonicalized_version,
                    pkg_info=metadata,
                ),
                additional_metadata_files=tuple(
                    os.path.relpath(metadata_path, location)
                    for metadata_path in glob.glob(os.path.join(os.path.dirname(path), "*"))
                    if os.path.basename(metadata_path) != metadata_file_name
                ),
                read_function=read_function,
            )


def _read_from_zip(
    zip_location,  # type: str
    rel_path,  # type: Text
):
    # type: (...) -> bytes
    with open_zip(zip_location) as zf:
        return zf.read(rel_path)


def find_wheel_metadata(location):
    # type: (Text) -> Optional[MetadataFiles]

    read_function = functools.partial(_read_from_zip, location)
    with open_zip(location) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            dist_info_dir, metadata_file = os.path.split(name)
            if os.path.dirname(dist_info_dir):
                continue
            if "METADATA" != metadata_file:
                continue

            with zf.open(name) as fp:
                metadata = parse_message(fp.read())
                project_name_and_version = ProjectNameAndVersion.from_parsed_pkg_info(
                    source=os.path.join(location, name), pkg_info=metadata
                )
                metadata_file_name = os.path.basename(name)
                files = []  # type: List[Text]
                for rel_path in zf.namelist():
                    head, tail = os.path.split(rel_path)
                    if dist_info_dir == head and tail != metadata_file_name:
                        files.append(rel_path)

                return MetadataFiles(
                    metadata=DistMetadataFile(
                        type=MetadataType.DIST_INFO,
                        location=location,
                        rel_path=name,
                        project_name=project_name_and_version.canonicalized_project_name,
                        version=project_name_and_version.canonicalized_version,
                        pkg_info=metadata,
                    ),
                    additional_metadata_files=tuple(files),
                    read_function=read_function,
                )

    return None


def _is_dist_pkg_info_file_path(file_path):
    # type: (Text) -> bool

    # N.B.: Should be: <project name>-<version>/PKG-INFO
    project_dir, metadata_file = os.path.split(file_path)
    if os.path.dirname(project_dir):
        return False
    if not "-" in project_dir:
        return False
    return "PKG-INFO" == metadata_file


def find_zip_sdist_metadata(location):
    # type: (Text) -> Optional[DistMetadataFile]
    with open_zip(location) as zf:
        for name in zf.namelist():
            if name.endswith("/") or not _is_dist_pkg_info_file_path(name):
                continue
            with zf.open(name) as fp:
                metadata = parse_message(fp.read())
                project_name_and_version = ProjectNameAndVersion.from_parsed_pkg_info(
                    source=os.path.join(location, name), pkg_info=metadata
                )
                return DistMetadataFile(
                    type=MetadataType.PKG_INFO,
                    location=location,
                    rel_path=name,
                    project_name=project_name_and_version.canonicalized_project_name,
                    version=project_name_and_version.canonicalized_version,
                    pkg_info=metadata,
                )

    return None


def find_tar_sdist_metadata(location):
    # type: (Text) -> Optional[DistMetadataFile]
    with tarfile.open(location) as tf:
        for member in tf.getmembers():
            if not member.isreg() or not _is_dist_pkg_info_file_path(member.name):
                continue

            file_obj = tf.extractfile(member)
            if file_obj is None:
                raise IOError(
                    errno.ENOENT,
                    "Could not find {rel_path} in {location}.".format(
                        rel_path=member.name, location=location
                    ),
                )
            with closing(file_obj) as fp:
                metadata = parse_message(fp.read())
                project_name_and_version = ProjectNameAndVersion.from_parsed_pkg_info(
                    source=os.path.join(location, member.name), pkg_info=metadata
                )
                return DistMetadataFile(
                    type=MetadataType.PKG_INFO,
                    location=location,
                    rel_path=member.name,
                    project_name=project_name_and_version.canonicalized_project_name,
                    version=project_name_and_version.canonicalized_version,
                    pkg_info=metadata,
                )

    return None


_METADATA_FILES = {}  # type: Dict[MetadataKey, Tuple[MetadataFiles, ...]]


def iter_metadata_files(
    location,  # type: Text
    restrict_types_to=(),  # type: Tuple[MetadataType.Value, ...]
    rescan=False,  # type: bool
):
    # type: (...) -> Iterator[MetadataFiles]

    files = []
    for metadata_type in restrict_types_to or MetadataType.values():
        key = MetadataKey(metadata_type=metadata_type, location=location)
        if rescan:
            _METADATA_FILES.pop(key, None)
        if key not in _METADATA_FILES:
            listing = []  # type: List[MetadataFiles]
            if MetadataType.DIST_INFO is metadata_type:
                if os.path.isdir(location):
                    listing.extend(
                        _find_installed_metadata_files(
                            location, MetadataType.DIST_INFO, "*.dist-info", "METADATA"
                        )
                    )
                elif is_wheel(location) and zipfile.is_zipfile(location):
                    metadata_files = find_wheel_metadata(location)
                    if metadata_files:
                        listing.append(metadata_files)
            elif MetadataType.EGG_INFO is metadata_type and os.path.isdir(location):
                listing.extend(
                    _find_installed_metadata_files(
                        location, MetadataType.EGG_INFO, "*.egg-info", "PKG-INFO"
                    )
                )
            elif MetadataType.PKG_INFO is metadata_type:
                if is_zip_sdist(location) and zipfile.is_zipfile(location):
                    metadata_file = find_zip_sdist_metadata(location)
                    if metadata_file:
                        listing.append(MetadataFiles(metadata=metadata_file))
                elif is_tar_sdist(location) and tarfile.is_tarfile(location):
                    metadata_file = find_tar_sdist_metadata(location)
                    if metadata_file:
                        listing.append(MetadataFiles(metadata=metadata_file))
            _METADATA_FILES[key] = tuple(listing)
        files.append(_METADATA_FILES[key])
    return itertools.chain.from_iterable(files)


def load_metadata(
    location,  # type: Text
    project_name=None,  # type: Optional[ProjectName]
    restrict_types_to=(),  # type: Tuple[MetadataType.Value, ...]
    rescan=False,  # type: bool
):
    # type: (...) -> Optional[MetadataFiles]
    all_metadata_files = [
        metadata_files
        for metadata_files in iter_metadata_files(
            location, restrict_types_to=restrict_types_to, rescan=rescan
        )
        if project_name is None or project_name == metadata_files.metadata.project_name
    ]
    if len(all_metadata_files) == 1:
        return all_metadata_files[0]
    if len(all_metadata_files) > 1:
        raise AmbiguousDistributionError(
            "Found more than one distribution inside {location}:\n{metadata_files}".format(
                location=location,
                metadata_files="\n".join(
                    metadata_file.metadata.rel_path for metadata_file in all_metadata_files
                ),
            )
        )
    return None


@attr.s(frozen=True)
class ProjectNameAndVersion(object):
    @classmethod
    def from_parsed_pkg_info(cls, source, pkg_info):
        # type: (Text, Message) -> ProjectNameAndVersion
        project_name = pkg_info.get("Name", None)
        version = pkg_info.get("Version", None)
        if project_name is None or version is None:
            raise MetadataError(
                "The 'Name' and 'Version' fields are not both present in package metadata for "
                "{source}:\n{fields}".format(
                    source=source,
                    fields="\n".join("{}: {}".format(k, v) for k, v in pkg_info.items()),
                )
            )
        return cls(project_name=pkg_info["Name"], version=pkg_info["Version"])

    @classmethod
    def from_filename(cls, path):
        # type: (Text) -> ProjectNameAndVersion
        # Handle wheels:
        #
        # The wheel filename convention is specified here:
        #   https://www.python.org/dev/peps/pep-0427/#file-name-convention.
        if is_wheel(path):
            project_name, version, _ = os.path.basename(path).split("-", 2)
            return cls(project_name=project_name, version=version)

        # Handle sdists:
        #
        # The sdist name format has no accepted specification yet, but there is a proposal here:
        #   https://www.python.org/dev/peps/pep-0625/#specification.
        #
        # We do the best we can to support the current landscape. A version number can technically
        # contain a dash though, even under the standards, in un-normalized form:
        #   https://www.python.org/dev/peps/pep-0440/#pre-release-separators.
        # For those cases this logic will produce incorrect results and it does not seem there is
        # much we can do since both project names and versions can contain both alphanumeric
        # characters and dashes.
        fname = _strip_sdist_path(path)
        if fname is not None:
            components = fname.rsplit("-", 1)
            if len(components) == 2:
                project_name, version = components
                return cls(project_name=project_name, version=version)

        raise UnrecognizedDistributionFormat(
            "The distribution at path {!r} does not have a file name matching known sdist or wheel "
            "file name formats.".format(path)
        )

    project_name = attr.ib()  # type: Text
    version = attr.ib()  # type: Text

    @property
    def canonicalized_project_name(self):
        # type: () -> ProjectName
        return ProjectName(self.project_name)

    @property
    def canonicalized_version(self):
        # type: () -> Version
        return Version(self.version)


def project_name_and_version(
    location,  # type: Union[Text, Distribution, Message, MetadataFiles]
    fallback_to_filename=True,  # type: bool
):
    # type: (...) -> Optional[ProjectNameAndVersion]
    """Extracts name and version metadata from dist.

    :param location: A distribution to extract project name and version metadata from.
    :return: The project name and version.
    :raise: MetadataError if dist has invalid metadata.
    """
    if isinstance(location, Distribution):
        return ProjectNameAndVersion(project_name=location.project_name, version=location.version)
    if isinstance(location, MetadataFiles):
        return ProjectNameAndVersion(
            project_name=location.metadata.project_name.raw, version=location.metadata.version.raw
        )

    pkg_info = None  # type: Optional[Message]
    if isinstance(location, Message):
        pkg_info = location
    else:
        metadata_files = load_metadata(location)
        if metadata_files:
            pkg_info = metadata_files.metadata.pkg_info
    if pkg_info is not None:
        if isinstance(location, str):
            source = location
        else:
            source = "<parsed message>"
        return ProjectNameAndVersion.from_parsed_pkg_info(source=source, pkg_info=pkg_info)
    if fallback_to_filename and not isinstance(location, (Distribution, Message)):
        return ProjectNameAndVersion.from_filename(location)
    return None


def requires_python(location):
    # type: (Union[Distribution, MetadataFiles, Text]) -> Optional[SpecifierSet]
    """Examines dist for `Python-Requires` metadata and returns version constraints if any.

    See: https://www.python.org/dev/peps/pep-0345/#requires-python

    :param location: A distribution to check for `Python-Requires` metadata.
    :return: The required python version specifiers.
    """
    if isinstance(location, Distribution):
        return location.metadata.requires_python

    metadata_files = None  # type: Optional[MetadataFiles]
    if isinstance(location, MetadataFiles):
        metadata_files = location
    else:
        # N.B.: This load can fail, but the source is the location of the metadata files, which
        # contains useful information in the path name for identifying the problem project and
        # version.
        metadata_files = load_metadata(location)
    if metadata_files is None:
        return None

    python_requirement = metadata_files.metadata.pkg_info.get("Requires-Python", None)
    if python_requirement is None:
        return None
    try:
        return SpecifierSet(python_requirement)
    except InvalidSpecifier as e:
        raise InvalidMetadataError(
            "Invalid Requires-Python metadata found in {source} {value!r}: {err}".format(
                source=metadata_files.metadata.render_description(), value=python_requirement, err=e
            )
        )


def _parse_requires_txt(content):
    # type: (bytes) -> Iterator[Union[Requirement, Tuple[int, Text, RequirementParseError]]]
    # See:
    # + High level: https://setuptools.pypa.io/en/latest/deprecated/python_eggs.html#requires-txt
    # + Low level:
    #   + https://github.com/pypa/setuptools/blob/fbe0d7962822c2a1fdde8dd179f2f8b8c8bf8892/pkg_resources/__init__.py#L3256-L3279
    #   + https://github.com/pypa/setuptools/blob/fbe0d7962822c2a1fdde8dd179f2f8b8c8bf8892/pkg_resources/__init__.py#L2792-L2818
    marker = ""
    for line_no, line in enumerate(content.decode("utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            extra, _, mark = section.partition(":")
            markers = []  # type: List[Text]
            if extra:
                markers.append('extra == "{extra}"'.format(extra=extra))
            if mark:
                markers.append(mark)
            if markers:
                marker = "; {markers}".format(markers=" and ".join(markers))
        else:
            req = line + marker
            try:
                yield Requirement.parse(req)
            except RequirementParseError as e:
                yield line_no, req, e


def requires_dists(location):
    # type: (Union[Distribution, MetadataFiles, Text]) -> Iterator[Requirement]
    """Examines dist for and returns any declared requirements.

    Looks for `Requires-Dist` metadata.

    The older `Requires` metadata is intentionally ignored, although we do log a warning if it is
    found to draw attention to this ~work-around and the associated issue in case any new data
    comes in.

    See:
    + https://www.python.org/dev/peps/pep-0345/#requires-dist-multiple-use
    + https://www.python.org/dev/peps/pep-0314/#requires-multiple-use

    :param location: A distribution to check for requirement metadata.
    :return: All requirements found.
    """
    if isinstance(location, Distribution):
        for requirement in location.metadata.requires_dists:
            yield requirement
        return

    metadata_files = None  # type: Optional[MetadataFiles]
    if isinstance(location, MetadataFiles):
        metadata_files = location
    else:
        # N.B.: This load can fail, but the source is the location of the metadata files, which
        # contains useful information in the path name for identifying the problem project and
        # version.
        metadata_files = load_metadata(location)
    if metadata_files is None:
        return

    invalid_values = []  # type: List[str]
    requires_dists = metadata_files.metadata.pkg_info.get_all("Requires-Dist", ())
    if not requires_dists and MetadataType.EGG_INFO is metadata_files.metadata.type:
        for metadata_file in "requires.txt", "depends.txt":
            content = metadata_files.read(metadata_file)
            if content:
                for requirement_or_error in _parse_requires_txt(content):
                    if isinstance(requirement_or_error, Requirement):
                        yield requirement_or_error
                    else:
                        line_no, req, err = requirement_or_error
                        invalid_values.append(
                            "{file}:{line_no} {req!r}: {err}".format(
                                file=(
                                    metadata_files.metadata_file_rel_path(metadata_file)
                                    or metadata_file
                                ),
                                line_no=line_no,
                                req=req,
                                err=err,
                            )
                        )
    else:
        for requires_dist in requires_dists:
            try:
                yield Requirement.parse(requires_dist)
            except RequirementParseError as e:
                invalid_values.append("{req!r}: {err}".format(req=requires_dist, err=e))
    if invalid_values:
        raise InvalidMetadataError(
            "Found {count} invalid Requires-Dist metadata {values} in {source}:\n"
            "{invalid_values}".format(
                count=len(invalid_values),
                values=pluralize(invalid_values, "value"),
                source=metadata_files.metadata.render_description(),
                invalid_values="\n".join(
                    "{index}. {invalid_value}".format(index=index, invalid_value=invalid_value)
                    for index, invalid_value in enumerate(invalid_values, start=1)
                ),
            )
        )

    legacy_requires = metadata_files.metadata.pkg_info.get_all("Requires", [])  # type: List[str]
    if legacy_requires:
        pex_warnings.warn(
            dedent(
                """\
                Ignoring {count} `Requires` {field} in {dist} metadata:
                {requires}

                You may have issues using the '{project_name}' distribution as a result.
                More information on this workaround can be found here:
                  https://github.com/pex-tool/pex/issues/1201#issuecomment-791715585
                """
            ).format(
                dist=location,
                project_name=metadata_files.metadata.project_name,
                count=len(legacy_requires),
                field=pluralize(legacy_requires, "field"),
                requires=os.linesep.join(
                    "{index}.) Requires: {req}".format(index=index, req=req)
                    for index, req in enumerate(legacy_requires, start=1)
                ),
            )
        )


# Frozen exception types don't work under 3.11+ where the `__traceback__` attribute can be set
# after construction in some cases.
@attr.s
class RequirementParseError(Exception):
    """Indicates and invalid requirement string.

    See PEP-508: https://www.python.org/dev/peps/pep-0508
    """

    error = attr.ib()  # type: Any
    source = attr.ib(default=None)  # type: Optional[str]

    def __str__(self):
        # type: () -> str
        if not self.source:
            return str(self.error)
        return "Failed to parse a requirement of {source}: {err}".format(
            err=self.error, source=self.source
        )


@attr.s(frozen=True)
class Constraint(object):
    @classmethod
    def parse(
        cls,
        constraint,  # type: Text
        source=None,  # type: Optional[str]
    ):
        # type: (...) -> Constraint
        try:
            return cls.from_packaging_requirement(PackagingRequirement(constraint))
        except InvalidRequirement as e:
            raise RequirementParseError(str(e), source=source)

    @classmethod
    def from_packaging_requirement(cls, requirement):
        # type: (PackagingRequirement) -> Constraint
        return cls(
            name=requirement.name, specifier=requirement.specifier, marker=requirement.marker
        )

    name = attr.ib(eq=False)  # type: str
    specifier = attr.ib(factory=SpecifierSet)  # type: SpecifierSet
    marker = attr.ib(default=None, eq=str)  # type: Optional[Marker]

    project_name = attr.ib(init=False, repr=False)  # type: ProjectName
    _str = attr.ib(init=False, eq=False, repr=False)  # type: str
    _legacy_version = attr.ib(init=False, repr=False)  # type: Optional[str]

    def __attrs_post_init__(self):
        # type: () -> None
        object.__setattr__(self, "project_name", ProjectName(self.name))

        parts = [self.name]
        if self.specifier:
            parts.append(str(self.specifier))
        if self.marker:
            parts.append("; {marker}".format(marker=self.marker))
        object.__setattr__(self, "_str", "".join(parts))

        # We handle arbitrary equality separately since its semantics are simple - exact matches
        # only - and newer versions of packaging will fail to parse non PEP-440 compliant version
        # strings prior to performing the comparison. This needlessly negates the ~only useful
        # case for arbitrary equality - requiring exact legacy versions.
        specifiers = list(self.specifier)

        object.__setattr__(
            self,
            "_legacy_version",
            specifiers[0].version
            if len(specifiers) == 1 and "===" == specifiers[0].operator
            else None,
        )

    @property
    def key(self):
        # type: () -> str
        return self.project_name.normalized

    def __contains__(self, item):
        # type: (Union[str, Version, Distribution, ProjectNameAndVersion, Constraint]) -> bool

        # We emulate pkg_resources.Requirement.__contains__ pre-release behavior here since the
        # codebase expects it.
        return self.contains(item, prereleases=True)

    def contains(
        self,
        item,  # type: Union[str, Version, Distribution, ProjectNameAndVersion, Constraint]
        prereleases=None,  # type: Optional[bool]
    ):
        # type: (...) -> bool
        if isinstance(item, Constraint):
            return item.project_name == self.project_name and specifier_sets.includes(
                self.specifier, item.specifier
            )
        elif isinstance(item, ProjectNameAndVersion):
            if item.canonicalized_project_name != self.project_name:
                return False
            version = (
                item.canonicalized_version.raw
                if self._legacy_version
                else item.canonicalized_version.parsed_version
            )  # type: Union[ParsedVersion, Text]
        elif isinstance(item, Distribution):
            if item.key != self.key:
                return False
            version = (
                item.metadata.version.raw
                if self._legacy_version
                else item.metadata.version.parsed_version
            )
        elif isinstance(item, Version):
            version = item.raw if self._legacy_version else item.parsed_version
        else:
            version = item

        # N.B.: We handle the case of `===<legacy version>` specially since it easy to do
        # (arbitrary equality indicates an exact match) and packaging>=22.0 does not parse legacy
        # versions (even though it does handle `===`). Since the ~only useful case for `===` is
        # comparing legacy versions, this keeps that ability viable in a backwards compatible way
        # while still upgrading packaging past 22.0.
        if self._legacy_version:
            return version == self._legacy_version

        # We know SpecifierSet.contains returns bool on inspection of its code. The fact we import
        # via the pex.third_party mechanism makes the type opaque to MyPy. We also know it accepts
        # either a "parsed_version" or a str and take advantage of this to save re-parsing version
        # strings we've already parsed.
        return cast(bool, self.specifier.contains(version, prereleases=prereleases))

    def __str__(self):
        # type: () -> str
        return self._str

    def as_requirement(self):
        # type: () -> Requirement
        return Requirement(name=self.name, specifier=self.specifier, marker=self.marker)


@attr.s(frozen=True)
class Requirement(Constraint):
    @classmethod
    def parse(
        cls,
        requirement,  # type: Text
        source=None,  # type: Optional[str]
    ):
        # type: (...) -> Requirement
        try:
            return cls.from_packaging_requirement(PackagingRequirement(requirement))
        except InvalidRequirement as e:
            raise RequirementParseError(str(e), source=source)

    @classmethod
    def from_packaging_requirement(cls, requirement):
        # type: (PackagingRequirement) -> Requirement
        return cls(
            name=requirement.name,
            url=requirement.url,
            extras=frozenset(requirement.extras),
            specifier=requirement.specifier,
            marker=requirement.marker,
        )

    url = attr.ib(default=None)  # type: Optional[str]
    extras = attr.ib(default=frozenset())  # type: FrozenSet[str]

    def __attrs_post_init__(self):
        # type: () -> None
        super(Requirement, self).__attrs_post_init__()

        parts = [self.name]
        if self.extras:
            parts.append("[{extras}]".format(extras=",".join(sorted(self.extras))))
        if self.specifier:
            parts.append(str(self.specifier))
        if self.url:
            parts.append("@ {url}".format(url=self.url))
            if self.marker:
                parts.append(" ")
        if self.marker:
            parts.append("; {marker}".format(marker=self.marker))
        object.__setattr__(self, "_str", "".join(parts))

    def as_constraint(self):
        # type: () -> Constraint
        return Constraint(name=self.name, specifier=self.specifier, marker=self.marker)


# N.B.: DistributionMetadata can have an expensive hash when a distribution has many requirements;
# so we cache the hash. See: https://github.com/pex-tool/pex/issues/1928
@attr.s(frozen=True, cache_hash=True)
class DistMetadata(object):
    @classmethod
    def from_metadata_files(cls, metadata_files):
        # type: (MetadataFiles) -> DistMetadata
        return cls(
            files=metadata_files,
            project_name=metadata_files.metadata.project_name,
            version=metadata_files.metadata.version,
            requires_dists=tuple(requires_dists(metadata_files)),
            requires_python=requires_python(metadata_files),
        )

    @classmethod
    def load(
        cls,
        location,  # type: Text
        *restrict_types_to  # type: MetadataType.Value
    ):
        # type: (...) -> DistMetadata

        metadata_files = load_metadata(location, restrict_types_to=restrict_types_to)
        if metadata_files is None:
            raise MetadataError(
                "Failed to determine project name and version for distribution at "
                "{location}.".format(location=location)
            )
        return cls.from_metadata_files(metadata_files)

    files = attr.ib(eq=False)  # type: MetadataFiles
    project_name = attr.ib()  # type: ProjectName
    version = attr.ib()  # type: Version
    requires_dists = attr.ib(default=())  # type: Tuple[Requirement, ...]
    requires_python = attr.ib(default=SpecifierSet())  # type: Optional[SpecifierSet]

    @property
    def type(self):
        # type: () -> MetadataType.Value
        return self.files.metadata.type


def _realpath(path):
    # type: (str) -> str
    return os.path.realpath(path)


class DistributionType(Enum["DistributionType.Value"]):
    class Value(Enum.Value):
        pass

    WHEEL = Value("whl")
    SDIST = Value("sdist")
    INSTALLED = Value("installed")

    @classmethod
    def of(cls, location):
        # type: (Text) -> DistributionType.Value
        if os.path.isdir(location):
            return cls.INSTALLED
        if is_wheel(location) and zipfile.is_zipfile(location):
            return cls.WHEEL
        return cls.SDIST


DistributionType.seal()


@attr.s(frozen=True)
class Distribution(object):
    @staticmethod
    def _read_metadata_lines(metadata_bytes):
        # type: (bytes) -> Iterator[str]
        for line in metadata_bytes.splitlines():
            # This is pkg_resources.IMetadataProvider.get_metadata_lines behavior, which our
            # code expects.
            if PY2:
                normalized = line.strip()
            else:
                normalized = line.decode("utf-8").strip()
            if normalized and not normalized.startswith("#"):
                yield normalized

    @classmethod
    def parse_entry_map(cls, entry_points_contents):
        # type: (bytes) -> Dict[str, Dict[str, NamedEntryPoint]]

        # This file format is defined here:
        #   https://packaging.python.org/en/latest/specifications/entry-points/#file-format

        entry_map = defaultdict(dict)  # type: DefaultDict[str, Dict[str, NamedEntryPoint]]
        group = None  # type: Optional[str]
        for index, line in enumerate(cls._read_metadata_lines(entry_points_contents), start=1):
            if line.startswith("[") and line.endswith("]"):
                group = line[1:-1]
            elif not group:
                raise ValueError(
                    "Failed to parse entry_points.txt, encountered an entry point with no "
                    "group on line {index}: {line}".format(index=index, line=line)
                )
            else:
                entry_point = NamedEntryPoint.parse(line)
                entry_map[group][entry_point.name] = entry_point
        return entry_map

    @classmethod
    def load(cls, location):
        # type: (str) -> Distribution
        return cls(location=location, metadata=DistMetadata.load(location))

    # N.B.: Resolving the distribution location through any symlinks is pkg_resources behavior,
    # which our code expects.
    location = attr.ib(converter=_realpath)  # type: str

    metadata = attr.ib()  # type: DistMetadata

    @property
    def type(self):
        # type: () -> DistributionType.Value
        return DistributionType.of(self.location)

    @property
    def key(self):
        # type: () -> str
        return self.metadata.project_name.normalized

    @property
    def project_name(self):
        # type: () -> str
        return self.metadata.project_name.raw

    @property
    def version(self):
        # type: () -> str
        return self.metadata.version.raw

    def as_requirement(self):
        # type: () -> Requirement
        return Requirement(
            name=self.project_name,
            specifier=SpecifierSet(
                "{operator}{version}".format(
                    operator="===" if self.metadata.version.is_legacy else "==",
                    version=self.version,
                )
            ),
        )

    def requires(self):
        # type: () -> Tuple[Requirement, ...]
        return self.metadata.requires_dists

    def _read_metadata_file(self, name):
        # type: (str) -> Optional[bytes]
        normalized_name = os.path.normpath(name)
        if os.path.isabs(normalized_name):
            raise ValueError(
                "The metadata file name must be a relative path under the .dist-info/ (or "
                ".egg-info/) directory. Given: {name}".format(name=name)
            )

        return self.metadata.files.read(name)

    def iter_metadata_lines(self, name):
        # type: (str) -> Iterator[Text]
        contents = self._read_metadata_file(name)
        if contents:
            for line in self._read_metadata_lines(contents):
                yield line

    def get_entry_map(self):
        # type: () -> Dict[str, Dict[str, NamedEntryPoint]]
        entry_points_metadata_file = self._read_metadata_file("entry_points.txt")
        if entry_points_metadata_file is None:
            return defaultdict(dict)
        return self.parse_entry_map(entry_points_metadata_file)

    def __str__(self):
        # type: () -> str
        return "{project_name} {version}".format(
            project_name=self.project_name, version=self.version
        )


@attr.s(frozen=True)
class ModuleEntryPoint(object):
    module = attr.ib()  # type: str

    def __str__(self):
        # type: () -> str
        return self.module


@attr.s(frozen=True)
class CallableEntryPoint(object):
    module = attr.ib()  # type: str
    attrs = attr.ib()  # type: Tuple[str, ...]

    @attrs.validator
    def _validate_attrs(self, _, value):
        if not value:
            raise ValueError("A callable entry point must select a callable item from the module.")

    def resolve(self):
        # type: () -> Callable[[], Any]
        module = importlib.import_module(self.module)
        try:
            return cast("Callable[[], Any]", functools.reduce(getattr, self.attrs, module))
        except AttributeError as e:
            raise ImportError(
                "Could not resolve {attrs} in {module}: {err}".format(
                    attrs=".".join(self.attrs), module=module, err=e
                )
            )

    def __str__(self):
        # type: () -> str
        return "{module}:{attrs}".format(module=self.module, attrs=".".join(self.attrs))


def parse_entry_point(value):
    # type: (str) -> Union[ModuleEntryPoint, CallableEntryPoint]

    # The format of the value of an entry point (minus the name part), is specified here:
    #   https://packaging.python.org/en/latest/specifications/entry-points/#file-format

    # N.B.: Python identifiers must be ascii.
    module, sep, attrs = str(value).strip().partition(":")
    if sep:
        if not attrs:
            raise ValueError("Invalid entry point specification: {value}.".format(value=value))
        return CallableEntryPoint(module=module, attrs=tuple(attrs.split(".")))
    return ModuleEntryPoint(module=module)


@attr.s(frozen=True)
class NamedEntryPoint(object):
    @classmethod
    def parse(cls, spec):
        # type: (str) -> NamedEntryPoint

        # This file format is defined here:
        #   https://packaging.python.org/en/latest/specifications/entry-points/#file-format

        components = spec.split("=")
        if len(components) != 2:
            raise ValueError("Invalid entry point specification: {spec}.".format(spec=spec))

        name, value = components
        entry_point = parse_entry_point(value)
        return cls(name=name.strip(), entry_point=entry_point)

    name = attr.ib()  # type: str
    entry_point = attr.ib()  # type: Union[ModuleEntryPoint, CallableEntryPoint]

    def __str__(self):
        # type: () -> str
        return "{name}={entry_point}".format(name=self.name, entry_point=self.entry_point)


def find_distribution(
    project_name,  # type: Union[str, ProjectName]
    search_path=None,  # type: Optional[Iterable[str]]
    rescan=False,  # type: bool
):
    # type: (...) -> Optional[Distribution]

    canonicalized_project_name = (
        project_name if isinstance(project_name, ProjectName) else ProjectName(project_name)
    )
    for location in search_path or sys.path:
        if not os.path.isdir(location):
            continue
        metadata_files = load_metadata(
            location,
            project_name=canonicalized_project_name,
            restrict_types_to=(MetadataType.DIST_INFO, MetadataType.EGG_INFO),
            rescan=rescan,
        )
        if metadata_files:
            return Distribution(
                location=location, metadata=DistMetadata.from_metadata_files(metadata_files)
            )
    return None


def find_distributions(
    search_path=None,  # type: Optional[Iterable[str]]
    rescan=False,  # type: bool
):
    # type: (...) -> Iterator[Distribution]
    seen = set()
    for location in search_path or sys.path:
        if not os.path.isdir(location):
            continue
        for metadata_files in iter_metadata_files(
            location,
            restrict_types_to=(MetadataType.DIST_INFO, MetadataType.EGG_INFO),
            rescan=rescan,
        ):
            if metadata_files.metadata in seen:
                continue
            seen.add(metadata_files.metadata)
            yield Distribution(
                location=location, metadata=DistMetadata.from_metadata_files(metadata_files)
            )
