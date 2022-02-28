# coding=utf-8
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import re
import tarfile
import zipfile
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
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.pkg_resources import DistInfoDistribution, Distribution, Requirement
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Dict, Iterable, Iterator, List, Optional, Tuple, Union

    import attr  # vendor:skip

    DistributionLike = Union[Distribution, str]
else:
    from pex.third_party import attr


class MetadataError(Exception):
    """Indicates an error reading distribution metadata."""


class UnrecognizedDistributionFormat(MetadataError):
    """Indicates a distribution file is not of any recognized format."""


_PKG_INFO_BY_DIST = {}  # type: Dict[Distribution, Optional[Message]]


def _strip_sdist_path(sdist_path):
    # type: (str) -> Optional[str]
    if not sdist_path.endswith((".sdist", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".zip")):
        return None

    sdist_basename = os.path.basename(sdist_path)
    filename, _ = os.path.splitext(sdist_basename)
    if filename.endswith(".tar"):
        filename, _ = os.path.splitext(filename)
    return filename


def _parse_message(message):
    # type: (bytes) -> Message
    return cast(Message, Parser().parse(StringIO(to_unicode(message))))


def _parse_sdist_package_info(sdist_path):
    # type: (str) -> Optional[Message]
    sdist_filename = _strip_sdist_path(sdist_path)
    if sdist_filename is None:
        return None

    pkg_info_path = os.path.join(sdist_filename, Distribution.PKG_INFO)

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


def find_dist_info_file(
    project_name,  # type: str
    version,  # type: str
    filename,  # type: str
    listing,  # type: Iterable[str]
):
    # type: (...) -> Optional[str]

    # The relevant PEP for project names appears to be the wheel 2.1 spec in PEP-566:
    #   https://www.python.org/dev/peps/pep-0566/#name
    #
    # That defers to PEP-508:
    #   https://www.python.org/dev/peps/pep-0508/#names
    #
    # In practice though it appears the PyPA ecosystem at least does a variant of the name
    # normalization defined for the simple repository API in PEP-503:
    #   https://www.python.org/dev/peps/pep-0503/#normalized-names
    #
    # For example, with the following setup.py:
    # ---
    # from setuptools import setup
    #
    # setup(name="Stress-.__Test", version="1.0")
    #
    # Using `pip wheel` generates a wheel with a `.dist-info/` dir of `Stress_._Test-1.0.dist-info`.
    # So `-` -> `_` and runs of `_` go to a single `_`. To be flexible, we accept any run of any
    # combo of `-`, `_`, and `.` as name component separators.
    project_name_pattern = re.sub(r"[-_.]+", "[-_.]+", project_name)

    # The relevant PEP for versions is https://www.python.org/dev/peps/pep-0440 which does not allow
    # a `-` in modern versions but also stipulates that all versions (legacy) must be handled. It
    # turns out wheel normalizes `-` to `_` and Pip has had to deal with this:
    #   https://github.com/pypa/pip/issues/1150
    #
    # We also deal with this, accepting either `-` or `_` when a `-` is expected.
    version_pattern = re.sub(
        r"(?P<left>[^-]+)-(?P<right>[^-]+)",
        lambda match: "{left}[-_]{right}".format(
            left=re.escape(match.group("left")), right=re.escape(match.group("right"))
        ),
        version,
    )
    if version_pattern == version:
        version_pattern = re.escape(version)

    wheel_metadata_pattern = "^{}$".format(
        os.path.join(
            "{}-{}\\.dist-info".format(project_name_pattern, version_pattern), re.escape(filename)
        )
    )
    wheel_metadata_re = re.compile(wheel_metadata_pattern, re.IGNORECASE)
    for item in listing:
        if wheel_metadata_re.match(item):
            return item
    return None


def _parse_wheel_package_info(wheel_path):
    # type: (str) -> Optional[Message]
    if not wheel_path.endswith(".whl") or not zipfile.is_zipfile(wheel_path):
        return None
    project_name, version, _ = os.path.basename(wheel_path).split("-", 2)
    with open_zip(wheel_path) as whl:
        metadata_file = find_dist_info_file(
            project_name=project_name,
            version=version,
            filename=DistInfoDistribution.PKG_INFO,
            listing=whl.namelist(),
        )
        if not metadata_file:
            return None
        with whl.open(metadata_file) as fp:
            return _parse_message(fp.read())


def _parse_distribution_package_info(dist):
    # type: (Distribution) -> Optional[Message]
    if not dist.has_metadata(DistInfoDistribution.PKG_INFO):
        return None
    metadata = dist.get_metadata(DistInfoDistribution.PKG_INFO)
    return _parse_message(metadata)


def _parse_pkg_info(dist):
    # type: (DistributionLike) -> Optional[Message]
    if dist not in _PKG_INFO_BY_DIST:
        if isinstance(dist, Distribution):
            pkg_info = _parse_distribution_package_info(dist)
        elif dist.endswith(".whl"):
            pkg_info = _parse_wheel_package_info(dist)
        else:
            pkg_info = _parse_sdist_package_info(dist)
        _PKG_INFO_BY_DIST[dist] = pkg_info
    return _PKG_INFO_BY_DIST[dist]


@attr.s(frozen=True)
class ProjectNameAndVersion(object):
    @classmethod
    def from_parsed_pkg_info(cls, source, pkg_info):
        # type: (DistributionLike, Message) -> ProjectNameAndVersion
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
    def from_distribution(cls, dist):
        # type: (Distribution) -> ProjectNameAndVersion
        project_name = dist.project_name
        try:
            version = dist.version
        except ValueError as e:
            raise MetadataError(
                "The version could not be determined for project {} @ {}: {}".format(
                    project_name, dist.location, e
                )
            )
        return cls(project_name=project_name, version=version)

    @classmethod
    def from_filename(cls, path):
        # type: (str) -> ProjectNameAndVersion
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
            project_name, version = fname.rsplit("-", 1)
            return cls(project_name=project_name, version=version)

        raise UnrecognizedDistributionFormat(
            "The distribution at path {!r} does not have a file name matching known sdist or wheel "
            "file name formats.".format(path)
        )

    project_name = attr.ib()  # type: str
    version = attr.ib()  # type: str


def project_name_and_version(dist, fallback_to_filename=True):
    # type: (DistributionLike, bool) -> Optional[ProjectNameAndVersion]
    """Extracts name and version metadata from dist.

    :param dist: A distribution to extract project name and version metadata from.
    :return: The project name and version.
    :raise: MetadataError if dist has invalid metadata.
    """
    pkg_info = _parse_pkg_info(dist)
    if pkg_info is not None:
        return ProjectNameAndVersion.from_parsed_pkg_info(dist, pkg_info)
    if isinstance(dist, Distribution):
        return ProjectNameAndVersion.from_distribution(dist)
    if fallback_to_filename:
        return ProjectNameAndVersion.from_filename(dist)
    return None


def requires_python(dist):
    # type: (DistributionLike) -> Optional[SpecifierSet]
    """Examines dist for `Python-Requires` metadata and returns version constraints if any.

    See: https://www.python.org/dev/peps/pep-0345/#requires-python

    :param dist: A distribution to check for `Python-Requires` metadata.
    :return: The required python version specifiers.
    """
    pkg_info = _parse_pkg_info(dist)
    if pkg_info is None:
        return None

    python_requirement = pkg_info.get("Requires-Python", None)
    if python_requirement is None:
        return None
    return SpecifierSet(python_requirement)


def requires_dists(dist):
    # type: (DistributionLike) -> Iterator[Requirement]
    """Examines dist for and returns any declared requirements.

    Looks for `Requires-Dist` metadata.

    The older `Requires` metadata is intentionally ignored, athough we do log a warning if it is
    found to draw attention to this ~work-around and the associated issue in case any new data
    comes in.

    See:
    + https://www.python.org/dev/peps/pep-0345/#requires-dist-multiple-use
    + https://www.python.org/dev/peps/pep-0314/#requires-multiple-use

    :param dist: A distribution to check for requirement metadata.
    :return: All requirements found.
    """
    pkg_info = _parse_pkg_info(dist)
    if pkg_info is None:
        return

    for requires_dist in pkg_info.get_all("Requires-Dist", ()):
        yield Requirement.parse(requires_dist)

    legacy_requires = pkg_info.get_all("Requires", [])  # type: List[str]
    if legacy_requires:
        name_and_version = project_name_and_version(dist)
        project_name = name_and_version.project_name if name_and_version else dist
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
                dist=dist,
                project_name=project_name,
                count=len(legacy_requires),
                field=pluralize(legacy_requires, "field"),
                requires=os.linesep.join(
                    "{index}.) Requires: {req}".format(index=index, req=req)
                    for index, req in enumerate(legacy_requires, start=1)
                ),
            )
        )


@attr.s(frozen=True)
class DistMetadata(object):
    @classmethod
    def for_dist(cls, dist):
        # type: (DistributionLike) -> DistMetadata

        project_name_and_ver = project_name_and_version(dist)
        if not project_name_and_ver:
            raise MetadataError(
                "Failed to determine project name and version for distribution {dist}.".format(
                    dist=dist
                )
            )
        return cls(
            project_name=ProjectName(project_name_and_ver.project_name),
            version=Version(project_name_and_ver.version),
            requires_dists=tuple(requires_dists(dist)),
            requires_python=requires_python(dist),
        )

    project_name = attr.ib()  # type: ProjectName
    version = attr.ib()  # type: Version
    requires_dists = attr.ib()  # type: Tuple[Requirement, ...]
    requires_python = attr.ib()  # type: Optional[SpecifierSet]
