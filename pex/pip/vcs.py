# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import re

from pex import hashing
from pex.artifact_url import VCS, Fingerprint
from pex.common import is_pyc_dir, is_pyc_file
from pex.exceptions import reportable_unexpected_error_msg
from pex.hashing import Sha256
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.result import Error, try_
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    # N.B.: The `re.Pattern` type is not available in all Python versions Pex supports.
    from re import Pattern  # type: ignore[attr-defined]
    from typing import Callable, Optional, Text, Tuple, Union

    from pex.hashing import HintedDigest


def _project_name_re(project_name):
    # type: (ProjectName) -> str
    return project_name.normalized.replace("-", "[-_.]+")


def _built_source_dist_pattern(project_name):
    # type: (ProjectName) -> Pattern
    return re.compile(
        r"(?P<project_name>{project_name_re})-(?P<version>.+)\.zip".format(
            project_name_re=_project_name_re(project_name)
        ),
        re.IGNORECASE,
    )


def _find_built_source_dist(
    build_dir,  # type: str
    project_name,  # type: ProjectName
    version,  # type: Version
):
    # type: (...) -> Union[str, Error]

    # All VCS requirements are prepared as zip archives with this naming scheme as
    # encoded in: `pip._internal.req.req_install.InstallRequirement.archive`.

    listing = os.listdir(build_dir)
    pattern = _built_source_dist_pattern(project_name)
    for name in listing:
        match = pattern.match(name)
        if match and Version(match.group("version")) == version:
            return os.path.join(build_dir, name)

    return Error(
        "Expected to find built sdist for {project_name} {version} in {build_dir} but only found:\n"
        "{listing}".format(
            project_name=project_name.raw,
            version=version.raw,
            build_dir=build_dir,
            listing="\n".join(listing),
        )
    )


def fingerprint_downloaded_vcs_archive(
    download_dir,  # type: str
    project_name,  # type: ProjectName
    version,  # type: Version
    vcs,  # type: VCS.Value
):
    # type: (...) -> Tuple[Fingerprint, str]

    archive_path = try_(
        _find_built_source_dist(build_dir=download_dir, project_name=project_name, version=version)
    )
    digest = Sha256()
    digest_vcs_archive(project_name=project_name, archive_path=archive_path, vcs=vcs, digest=digest)
    return Fingerprint.from_digest(digest), archive_path


def _vcs_dir_filter(
    vcs,  # type: VCS.Value
    project_name,  # type: ProjectName
):
    # type: (...) -> Callable[[Text], bool]

    # Ignore VCS control directories for the purposes of fingerprinting the version controlled
    # source tree. VCS control directories can contain non-reproducible content (Git at least
    # has files that contain timestamps).
    #
    # We cannot prune these directories from the source archive directly unfortunately since
    # some build processes use VCS version information to derive their version numbers (C.F.:
    # https://pypi.org/project/setuptools-scm/). As such, we'll get a stable fingerprint, but be
    # forced to re-build a wheel each time the VCS requirement is re-locked later, even when it
    # hashes the same.
    vcs_control_dir = ".{vcs}".format(vcs=vcs)

    # N.B.: If the VCS project uses setuptools as its build backend, depending on the version of
    # Pip used, the VCS checkout can have a `<project name>.egg-info/` directory littering its root
    # left over from Pip generating project metadata to determine version and dependencies. No other
    # well known build-backend has this problem at this time (checked hatchling, poetry-core,
    # pdm-backend and uv_build).
    # C.F.: https://github.com/pypa/pip/pull/13602
    egg_info_dir_re = re.compile(
        r"^{project_name_re}\.egg-info$".format(project_name_re=_project_name_re(project_name)),
        re.IGNORECASE,
    )

    def vcs_dir_filter(dir_path):
        # type: (Text) -> bool
        if is_pyc_dir(dir_path):
            return False

        base_dir_name = dir_path.split(os.sep)[0]
        return base_dir_name != vcs_control_dir and not egg_info_dir_re.match(base_dir_name)

    return vcs_dir_filter


def _vcs_file_filter(vcs):
    # type: (VCS.Value) -> Callable[[Text], bool]
    return lambda f: not is_pyc_file(f)


def digest_vcs_archive(
    project_name,  # type: ProjectName
    archive_path,  # type: str
    vcs,  # type: VCS.Value
    digest,  # type: HintedDigest
):
    # type: (...) -> None

    # All VCS requirements are prepared as zip archives as encoded in:
    # `pip._internal.req.req_install.InstallRequirement.archive` and the archive is already offset
    # by a subdirectory (if any).

    # The zip archives created by Pip have a single project name top-level directory housing
    # the full clone. We look for that to get a consistent clone hash with a bare clone.
    match = _built_source_dist_pattern(project_name).match(os.path.basename(archive_path))
    if match is None:
        raise AssertionError(
            reportable_unexpected_error_msg(
                "Failed to determine the project name prefix for the VCS zip {zip} with expected "
                "canonical project name {project_name}".format(
                    zip=archive_path, project_name=project_name
                )
            )
        )
    top_dir = match.group("project_name")

    hashing.zip_hash(
        zip_path=archive_path,
        digest=digest,
        relpath=top_dir,
        dir_filter=_vcs_dir_filter(vcs, project_name),
        file_filter=_vcs_file_filter(vcs),
    )


def digest_vcs_repo(
    project_name,  # type: ProjectName
    repo_path,  # type: str
    vcs,  # type: VCS.Value
    digest,  # type: HintedDigest
    subdirectory=None,  # type: Optional[str]
):
    # type: (...) -> None

    hashing.dir_hash(
        directory=os.path.join(repo_path, subdirectory) if subdirectory else repo_path,
        digest=digest,
        dir_filter=_vcs_dir_filter(vcs, project_name),
        file_filter=_vcs_file_filter(vcs),
    )
