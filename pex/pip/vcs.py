# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import re

from pex import hashing
from pex.common import is_pyc_dir, is_pyc_file, open_zip, temporary_dir
from pex.hashing import Sha256
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.requirements import VCS
from pex.resolve.resolved_requirement import Fingerprint
from pex.result import Error, try_
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Tuple, Union

    from pex.hashing import HintedDigest


def _find_built_source_dist(
    build_dir,  # type: str
    project_name,  # type: ProjectName
    version,  # type: Version
):
    # type: (...) -> Union[str, Error]

    # All VCS requirements are prepared as zip archives with this naming scheme as
    # encoded in: `pip._internal.req.req_install.InstallRequirement.archive`.

    listing = os.listdir(build_dir)
    pattern = re.compile(
        r"{project_name}-(?P<version>.+)\.zip".format(
            project_name=project_name.normalized.replace("-", "[-_.]+")
        )
    )
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
    project_name,  # type: str
    version,  # type: str
    vcs,  # type: VCS.Value
):
    # type: (...) -> Tuple[Fingerprint, str]

    archive_path = try_(
        _find_built_source_dist(
            build_dir=download_dir, project_name=ProjectName(project_name), version=Version(version)
        )
    )
    digest = Sha256()
    digest_vcs_archive(archive_path=archive_path, vcs=vcs, digest=digest)
    return Fingerprint.from_digest(digest), archive_path


def digest_vcs_archive(
    archive_path,  # type: str
    vcs,  # type: VCS.Value
    digest,  # type: HintedDigest
):
    # type: (...) -> None

    # All VCS requirements are prepared as zip archives as encoded in:
    # `pip._internal.req.req_install.InstallRequirement.archive`.
    with TRACER.timed(
        "Digesting {archive} {vcs} archive".format(archive=os.path.basename(archive_path), vcs=vcs)
    ), temporary_dir() as chroot, open_zip(archive_path) as archive:
        archive.extractall(chroot)

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

        # TODO(John Sirois): Consider implementing zip_hash to avoid the extractall.
        hashing.dir_hash(
            directory=chroot,
            digest=digest,
            dir_filter=(
                lambda dir_path: (
                    not is_pyc_dir(dir_path) and os.path.basename(dir_path) != vcs_control_dir
                )
            ),
            file_filter=lambda f: not is_pyc_file(f),
        )
