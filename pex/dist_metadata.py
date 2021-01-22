# coding=utf-8
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import tarfile
import zipfile
from collections import namedtuple
from contextlib import closing
from email.message import Message
from email.parser import Parser

from pex import pex_warnings
from pex.common import open_zip
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.pkg_resources import DistInfoDistribution, Distribution, Requirement
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Dict, Iterator, Optional, Text, Union

    DistributionLike = Union[Distribution, str]


class MetadataError(Exception):
    """Indicates an error reading distribution metadata."""


class UnrecognizedDistributionFormat(MetadataError):
    """Indicates a distribution file is not of any recognized format."""


_PKG_INFO_BY_DIST = {}  # type: Dict[Distribution, Optional[Message]]


def _strip_sdist_path(sdist_path):
    # type: (str) -> Optional[str]
    if not sdist_path.endswith((".sdist", ".tar.gz", ".zip")):
        return None

    sdist_basename = os.path.basename(sdist_path)
    filename, _ = os.path.splitext(sdist_basename)
    if filename.endswith(".tar"):
        filename, _ = os.path.splitext(filename)
    return filename


def _parse_message(message):
    # type: (Text) -> Message
    return cast(Message, Parser().parsestr(message))


def _parse_sdist_package_info(sdist_path):
    # type: (str) -> Optional[Message]
    sdist_filename = _strip_sdist_path(sdist_path)
    if sdist_filename is None:
        return None

    pkg_info_path = os.path.join(sdist_filename, Distribution.PKG_INFO)

    if zipfile.is_zipfile(sdist_path):
        with open_zip(sdist_path) as zip:
            try:
                return _parse_message(zip.read(pkg_info_path).decode("utf-8"))
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
                    return _parse_message(fp.read().decode("utf-8"))
            except KeyError as e:
                pex_warnings.warn(
                    "Source distribution {} did not have the expected metadata file {}: {}".format(
                        sdist_path, pkg_info_path, e
                    )
                )
                return None

    return None


def _parse_wheel_package_info(wheel_path):
    # type: (str) -> Optional[Message]
    if not wheel_path.endswith(".whl") or not zipfile.is_zipfile(wheel_path):
        return None
    project_name, version, _ = os.path.basename(wheel_path).split("-", 2)
    dist_info_dir = "{}-{}.dist-info".format(project_name, version)
    with open_zip(wheel_path) as whl:
        with whl.open(os.path.join(dist_info_dir, DistInfoDistribution.PKG_INFO)) as fp:
            return _parse_message(fp.read().decode("utf-8"))


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


class ProjectNameAndVersion(namedtuple("ProjectNameAndVersion", ["project_name", "version"])):
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


def requires_dists(
    dist,  # type: DistributionLike
    include_1_1_requires=True,  # type: bool
):
    # type: (...) -> Iterator[Requirement]
    """Examines dist for and returns any declared requirements.

    Looks for `Requires-Dist` metadata and, optionally, the older `Requires` metadata if
    `include_1_1_requires`.

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

    if include_1_1_requires:
        for requires in pkg_info.get_all("Requires", ()):
            yield Requirement.parse(requires)
