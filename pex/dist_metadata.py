# coding=utf-8
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools
import glob
import importlib
import os
import re
import sys
import tarfile
import zipfile
from collections import defaultdict
from contextlib import closing
from email.message import Message
from email.parser import Parser
from io import StringIO
from textwrap import dedent

from pex import pex_warnings
from pex.common import open_zip, pluralize
from pex.compatibility import to_unicode
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.third_party.packaging.markers import Marker
from pex.third_party.packaging.requirements import InvalidRequirement
from pex.third_party.packaging.requirements import Requirement as PackagingRequirement
from pex.third_party.packaging.specifiers import SpecifierSet
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


_PKG_INFO_BY_DIST_LOCATION = {}  # type: Dict[Text, Optional[Message]]


def _strip_sdist_path(sdist_path):
    # type: (Text) -> Optional[str]
    if not sdist_path.endswith((".sdist", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".zip")):
        return None

    sdist_basename = os.path.basename(sdist_path)
    filename, _ = os.path.splitext(sdist_basename)
    if filename.endswith(".tar"):
        filename, _ = os.path.splitext(filename)
    # All PEP paths lead here for the definition of a valid project name which limits things to
    # ascii; so this str(...) is Python 2.7 safe: https://peps.python.org/pep-0508/#names
    # The version part of the basename is similarly restricted by:
    #   https://peps.python.org/pep-0440/#summary-of-changes-to-pep-440
    return str(filename)


def _parse_message(message):
    # type: (bytes) -> Message
    return cast(Message, Parser().parse(StringIO(to_unicode(message))))


def _parse_sdist_package_info(sdist_path):
    # type: (Text) -> Optional[Message]
    sdist_filename = _strip_sdist_path(sdist_path)
    if sdist_filename is None:
        return None

    pkg_info_path = os.path.join(sdist_filename, "PKG-INFO")

    if zipfile.is_zipfile(sdist_path):
        with open_zip(sdist_path) as zip:
            try:
                return _parse_message(zip.read(pkg_info_path))
            except KeyError as e:
                pex_warnings.warn(
                    "Source distribution {} did not have the expected metadata file {}: {}".format(
                        sdist_path, pkg_info_path, e
                    )
                )
                return None

    if tarfile.is_tarfile(sdist_path):
        with tarfile.open(sdist_path) as tf:
            try:
                pkg_info = tf.extractfile(pkg_info_path)
                if pkg_info is None:
                    # N.B.: `extractfile` returns None for directories and special files.
                    return None
                with closing(pkg_info) as fp:
                    return _parse_message(fp.read())
            except KeyError as e:
                pex_warnings.warn(
                    "Source distribution {} did not have the expected metadata file {}: {}".format(
                        sdist_path, pkg_info_path, e
                    )
                )
                return None

    return None


@attr.s(frozen=True)
class DistMetadataFile(object):
    project_name = attr.ib()  # type: ProjectName
    version = attr.ib()  # type: Version
    path = attr.ib()  # type: str


def find_dist_info_files(
    filename,  # type: Text
    listing,  # type: Iterable[str]
):
    # type: (...) -> Iterator[DistMetadataFile]

    # N.B. We know the captured project_name and version will not contain `-` even though PEP-503
    # allows for them in project names and PEP-440 allows for them in versions in some
    # circumstances. This is since we're limiting ourselves to the products of installs by our
    # vendored versions of wheel and pip which turn `-` into `_` as explained in `ProjectName` and
    # `Version` docs.
    dist_info_metadata_pattern = "^{}$".format(
        os.path.join(r"(?P<project_name>.+)-(?P<version>.+)\.dist-info", re.escape(filename))
    )
    wheel_metadata_re = re.compile(dist_info_metadata_pattern)
    for item in listing:
        match = wheel_metadata_re.match(item)
        if match:
            yield DistMetadataFile(
                project_name=ProjectName(match.group("project_name")),
                version=Version(match.group("version")),
                path=item,
            )


def find_dist_info_file(
    project_name,  # type: Union[Text, ProjectName]
    filename,  # type: Text
    listing,  # type: Iterable[str]
    version=None,  # type: Optional[Union[Text, Version]]
):
    # type: (...) -> Optional[str]

    normalized_project_name = (
        project_name if isinstance(project_name, ProjectName) else ProjectName(project_name)
    )

    if isinstance(version, Version):
        normalized_version = version
    elif isinstance(version, str):
        normalized_version = Version(version)
    else:
        normalized_version = None

    for metadata_file in find_dist_info_files(filename, listing):
        if normalized_project_name == metadata_file.project_name:
            if normalized_version and normalized_version != metadata_file.version:
                continue
            return metadata_file.path
    return None


def _parse_wheel_package_info(wheel_path):
    # type: (Text) -> Optional[Message]
    if not wheel_path.endswith(".whl") or not zipfile.is_zipfile(wheel_path):
        return None
    project_name, version, _ = os.path.basename(wheel_path).split("-", 2)
    with open_zip(wheel_path) as whl:
        metadata_file = find_dist_info_file(
            project_name=project_name,
            version=version,
            filename="METADATA",
            listing=whl.namelist(),
        )
        if not metadata_file:
            return None
        with whl.open(metadata_file) as fp:
            return _parse_message(fp.read())


def _parse_installed_distribution_info(location):
    # type: (Text) -> Optional[Message]

    if not os.path.isdir(location):
        return None

    dist_info_dirs = glob.glob(os.path.join(location, "*.dist-info"))
    if not dist_info_dirs:
        return None

    if len(dist_info_dirs) > 1:
        raise AmbiguousDistributionError(
            "Found more than one distribution at {location}:\n{dist_info_dirs}".format(
                location=location,
                dist_info_dirs="\n".join(
                    os.path.relpath(dist_info_dir, location) for dist_info_dir in dist_info_dirs
                ),
            )
        )

    metadata_file = os.path.join(dist_info_dirs[0], "METADATA")
    if not os.path.exists(metadata_file):
        return None

    with open(metadata_file, "rb") as fp:
        return _parse_message(fp.read())


def _parse_pkg_info(location):
    # type: (Text) -> Optional[Message]
    if location not in _PKG_INFO_BY_DIST_LOCATION:
        pkg_info = _parse_wheel_package_info(location)
        if not pkg_info:
            pkg_info = _parse_sdist_package_info(location)
        if not pkg_info:
            pkg_info = _parse_installed_distribution_info(location)
        _PKG_INFO_BY_DIST_LOCATION[location] = pkg_info
    return _PKG_INFO_BY_DIST_LOCATION[location]


@attr.s(frozen=True)
class ProjectNameAndVersion(object):
    @classmethod
    def from_parsed_pkg_info(cls, source, pkg_info):
        # type: (str, Message) -> ProjectNameAndVersion
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
        if path.endswith(".whl"):
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
    location,  # type: Union[Text, Distribution, Message]
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

    pkg_info = location if isinstance(location, Message) else _parse_pkg_info(location)
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
    # type: (Union[Text, Distribution, Message]) -> Optional[SpecifierSet]
    """Examines dist for `Python-Requires` metadata and returns version constraints if any.

    See: https://www.python.org/dev/peps/pep-0345/#requires-python

    :param location: A distribution to check for `Python-Requires` metadata.
    :return: The required python version specifiers.
    """
    if isinstance(location, Distribution):
        return location.metadata.requires_python

    pkg_info = location if isinstance(location, Message) else _parse_pkg_info(location)
    if pkg_info is None:
        return None

    python_requirement = pkg_info.get("Requires-Python", None)
    if python_requirement is None:
        return None
    return SpecifierSet(python_requirement)


def requires_dists(location):
    # type: (Union[Text, Distribution, Message]) -> Iterator[Requirement]
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

    pkg_info = location if isinstance(location, Message) else _parse_pkg_info(location)
    if pkg_info is None:
        return

    for requires_dist in pkg_info.get_all("Requires-Dist", ()):
        yield Requirement.parse(requires_dist)

    legacy_requires = pkg_info.get_all("Requires", [])  # type: List[str]
    if legacy_requires:
        name_and_version = project_name_and_version(location)
        project_name = name_and_version.project_name if name_and_version else location
        pex_warnings.warn(
            dedent(
                """\
                Ignoring {count} `Requires` {field} in {dist} metadata:
                {requires}

                You may have issues using the '{project_name}' distribution as a result.
                More information on this workaround can be found here:
                  https://github.com/pantsbuild/pex/issues/1201#issuecomment-791715585
                """
            ).format(
                dist=location,
                project_name=project_name,
                count=len(legacy_requires),
                field=pluralize(legacy_requires, "field"),
                requires=os.linesep.join(
                    "{index}.) Requires: {req}".format(index=index, req=req)
                    for index, req in enumerate(legacy_requires, start=1)
                ),
            )
        )


class RequirementParseError(Exception):
    """Indicates and invalid requirement string.

    See PEP-508: https://www.python.org/dev/peps/pep-0508
    """


@attr.s(frozen=True)
class Requirement(object):
    @classmethod
    def parse(cls, requirement):
        # type: (Text) -> Requirement
        try:
            return cls.from_packaging_requirement(PackagingRequirement(requirement))
        except InvalidRequirement as e:
            raise RequirementParseError(str(e))

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

    name = attr.ib(eq=False)  # type: str
    url = attr.ib(default=None)  # type: Optional[str]
    extras = attr.ib(default=frozenset())  # type: FrozenSet[str]
    specifier = attr.ib(factory=SpecifierSet)  # type: SpecifierSet
    marker = attr.ib(default=None, eq=str)  # type: Optional[Marker]

    project_name = attr.ib(init=False, repr=False)  # type: ProjectName
    _str = attr.ib(init=False, eq=False, repr=False)  # type: str
    _legacy_version = attr.ib(init=False, repr=False)  # type: Optional[str]

    def __attrs_post_init__(self):
        object.__setattr__(self, "project_name", ProjectName(self.name))

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
        # type: (Union[str, Version, Distribution, ProjectNameAndVersion]) -> bool

        # We emulate pkg_resources.Requirement.__contains__ pre-release behavior here since the
        # codebase expects it.
        return self.contains(item, prereleases=True)

    def contains(
        self,
        item,  # type: Union[str, Version, Distribution, ProjectNameAndVersion]
        prereleases=None,  # type: Optional[bool]
    ):
        # type: (...) -> bool
        if isinstance(item, ProjectNameAndVersion):
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


# N.B.: DistributionMetadata can have an expensive hash when a distribution has many requirements;
# so we cache the hash. See: https://github.com/pantsbuild/pex/issues/1928
@attr.s(frozen=True, cache_hash=True)
class DistMetadata(object):
    @classmethod
    def load(cls, location):
        # type: (Union[Text, Message]) -> DistMetadata

        project_name_and_ver = project_name_and_version(location)
        if not project_name_and_ver:
            raise MetadataError(
                "Failed to determine project name and version for distribution at "
                "{location}.".format(location=location)
            )
        return cls(
            project_name=ProjectName(project_name_and_ver.project_name),
            version=Version(project_name_and_ver.version),
            requires_dists=tuple(requires_dists(location)),
            requires_python=requires_python(location),
        )

    project_name = attr.ib()  # type: ProjectName
    version = attr.ib()  # type: Version
    requires_dists = attr.ib(default=())  # type: Tuple[Requirement, ...]
    requires_python = attr.ib(default=SpecifierSet())  # type: Optional[SpecifierSet]


def _realpath(path):
    # type: (str) -> str
    return os.path.realpath(path)


@attr.s(frozen=True)
class Distribution(object):
    @staticmethod
    def _read_metadata_lines(metadata_path):
        # type: (str) -> Iterator[str]
        with open(os.path.join(metadata_path)) as fp:
            for line in fp:
                # This is pkg_resources.IMetadataProvider.get_metadata_lines behavior, which our
                # code expects.
                normalized = line.strip()
                if normalized and not normalized.startswith("#"):
                    yield normalized

    @classmethod
    def parse_entry_map(cls, entry_points_metadata_path):
        # type: (str) -> Dict[str, Dict[str, EntryPoint]]

        # This file format is defined here:
        #   https://packaging.python.org/en/latest/specifications/entry-points/#file-format

        entry_map = defaultdict(dict)  # type: DefaultDict[str, Dict[str, EntryPoint]]
        group = None  # type: Optional[str]
        for index, line in enumerate(cls._read_metadata_lines(entry_points_metadata_path), start=1):
            if line.startswith("[") and line.endswith("]"):
                group = line[1:-1]
            elif not group:
                raise ValueError(
                    "Failed to parse entry_points.txt, encountered an entry point with no "
                    "group on line {index}: {line}".format(index=index, line=line)
                )
            else:
                entry_point = EntryPoint.parse(line)
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
    _metadata_files_cache = attr.ib(
        factory=dict, init=False, eq=False, repr=False
    )  # type: Dict[str, str]

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

    def _get_metadata_file(self, name):
        # type: (str) -> Optional[str]
        normalized_name = os.path.normpath(name)
        if os.path.isabs(normalized_name):
            raise ValueError(
                "The metadata file name must be a relative path under the .dist-info/ directory. "
                "Given: {name}".format(name=name)
            )

        metadata_file = self._metadata_files_cache.get(normalized_name)
        if metadata_file is None:
            metadata_file = find_dist_info_file(
                project_name=self.metadata.project_name,
                version=self.version,
                filename=normalized_name,
                listing=[
                    os.path.relpath(path, self.location)
                    for path in glob.glob(
                        os.path.join(
                            self.location, "*.dist-info/{name}".format(name=normalized_name)
                        )
                    )
                ],
            )
            # N.B.: We store the falsey "" as the sentinel that we've searched already and the
            # metadata file did not exist.
            self._metadata_files_cache[normalized_name] = metadata_file or ""
        return metadata_file or None

    def has_metadata(self, name):
        # type: (str) -> bool
        return self._get_metadata_file(name) is not None

    def get_metadata_lines(self, name):
        # type: (str) -> Iterator[str]
        relative_path = self._get_metadata_file(name)
        if relative_path is None:
            raise MetadataNotFoundError(
                "The metadata file {name} is not present for {project_name} {version} at "
                "{location}".format(
                    name=name,
                    project_name=self.project_name,
                    version=self.version,
                    location=self.location,
                )
            )
        for line in self._read_metadata_lines(os.path.join(self.location, relative_path)):
            yield line

    def get_entry_map(self):
        # type: () -> Dict[str, Dict[str, EntryPoint]]
        entry_points_metadata_relpath = self._get_metadata_file("entry_points.txt")
        if entry_points_metadata_relpath is None:
            return defaultdict(dict)
        return self.parse_entry_map(os.path.join(self.location, entry_points_metadata_relpath))

    def __str__(self):
        # type: () -> str
        return "{project_name} {version}".format(
            project_name=self.project_name, version=self.version
        )


@attr.s(frozen=True)
class EntryPoint(object):
    @classmethod
    def parse(cls, spec):
        # type: (str) -> EntryPoint

        # This file format is defined here:
        #   https://packaging.python.org/en/latest/specifications/entry-points/#file-format

        components = spec.split("=")
        if len(components) != 2:
            raise ValueError("Invalid entry point specification: {spec}.".format(spec=spec))

        name, value = components
        module, sep, attrs = value.strip().partition(":")
        if sep and not attrs:
            raise ValueError("Invalid entry point specification: {spec}.".format(spec=spec))

        entry_point_name = name.strip()
        if sep:
            return CallableEntryPoint(
                name=entry_point_name, module=module, attrs=tuple(attrs.split("."))
            )

        return cls(name=entry_point_name, module=module)

    name = attr.ib()  # type: str
    module = attr.ib()  # type: str

    def __str__(self):
        # type: () -> str
        return self.module


@attr.s(frozen=True)
class CallableEntryPoint(EntryPoint):
    _attrs = attr.ib()  # type: Tuple[str, ...]

    @_attrs.validator
    def _validate_attrs(self, _, value):
        if not value:
            raise ValueError("A callable entry point must select a callable item from the module.")

    def resolve(self):
        # type: () -> Callable[[], Any]
        module = importlib.import_module(self.module)
        try:
            return cast("Callable[[], Any]", functools.reduce(getattr, self._attrs, module))
        except AttributeError as e:
            raise ImportError(
                "Could not resolve {attrs} in {module}: {err}".format(
                    attrs=".".join(self._attrs), module=module, err=e
                )
            )

    def __str__(self):
        # type: () -> str
        return "{module}:{attrs}".format(module=self.module, attrs=".".join(self._attrs))


def find_distribution(
    project_name,  # type: Union[str, ProjectName]
    search_path=None,  # type: Optional[Iterable[str]]
):
    # type: (...) -> Optional[Distribution]

    for location in search_path or sys.path:
        if not os.path.isdir(location):
            continue

        metadata_file = find_dist_info_file(
            project_name=str(project_name),
            filename="METADATA",
            listing=[
                os.path.relpath(path, location)
                for path in glob.glob(os.path.join(location, "*.dist-info/METADATA"))
            ],
        )
        if not metadata_file:
            continue

        metadata_path = os.path.join(location, metadata_file)
        with open(metadata_path, "rb") as fp:
            pkg_info = _parse_message(fp.read())
            dist = Distribution(location=location, metadata=DistMetadata.load(pkg_info))
            if dist.metadata.project_name == (
                project_name if isinstance(project_name, ProjectName) else ProjectName(project_name)
            ):
                return dist

    return None


def find_distributions(search_path=None):
    # type: (Optional[Iterable[str]]) -> Iterator[Distribution]

    seen = set()
    for location in search_path or sys.path:
        if not os.path.isdir(location):
            continue
        for metadata_file in find_dist_info_files(
            filename="METADATA",
            listing=[
                os.path.relpath(path, location)
                for path in glob.glob(os.path.join(location, "*.dist-info/METADATA"))
            ],
        ):
            metadata_path = os.path.realpath(os.path.join(location, metadata_file.path))
            if metadata_path in seen:
                continue
            seen.add(metadata_path)
            with open(metadata_path, "rb") as fp:
                pkg_info = _parse_message(fp.read())
                yield Distribution(location=location, metadata=DistMetadata.load(pkg_info))
