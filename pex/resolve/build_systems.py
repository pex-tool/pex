# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import tarfile
from collections import OrderedDict

from pex.build_system import DEFAULT_BUILD_SYSTEM_TABLE, BuildSystemTable
from pex.build_system.pep_518 import load_build_system_table
from pex.common import open_zip, safe_mkdtemp
from pex.dist_metadata import is_sdist, is_tar_sdist, is_zip_sdist
from pex.exceptions import production_assert, reportable_unexpected_error_msg
from pex.jobs import iter_map_parallel
from pex.resolve.resolved_requirement import PartialArtifact
from pex.resolve.resolvers import Resolver
from pex.result import try_
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Iterable, Iterator, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def extract_build_system_table(source_archive_path):
    # type: (str) -> BuildSystemTable

    if is_tar_sdist(source_archive_path):
        extract_chroot = safe_mkdtemp()
        with tarfile.open(source_archive_path) as fp:
            fp.extractall(extract_chroot)
    elif is_zip_sdist(source_archive_path):
        extract_chroot = safe_mkdtemp()
        with open_zip(source_archive_path) as fp:
            fp.extractall(extract_chroot)
    else:
        raise AssertionError(
            reportable_unexpected_error_msg(
                "Asked to extract a build system table from {path} which does not appear to be a "
                "source archive.".format(path=source_archive_path)
            )
        )

    # We might get a Python-standard sdist, in which case the project root is at
    # `<project>-<version>/` at the top of the archive, but we also might get some other sort of
    # archive, like a GitHub source archive which does not use Python conventions. As such we just
    # perform a top-down search for a project file and exit early for the highest-level such file
    # found.
    # TODO(John Sirois): XXX: Check if this works with VCS requirements that use Pip-proprietary
    #  subdirectory=YYY.
    for root, dirs, files in os.walk(extract_chroot):
        if any(f in ("pyproject.toml", "setup.py", "setupcfg") for f in files):
            return try_(load_build_system_table(root))
    return DEFAULT_BUILD_SYSTEM_TABLE


@attr.s(frozen=True)
class BuildSystems(object):
    resolver = attr.ib()  # type: Resolver

    def determine_build_systems(self, artifacts):
        # type: (Iterable[PartialArtifact]) -> Iterator[Tuple[PartialArtifact, Optional[BuildSystemTable]]]

        undetermined_artifacts = OrderedDict()  # type: OrderedDict[PartialArtifact, float]
        for artifact in artifacts:
            if artifact.build_system_table:
                yield artifact, artifact.build_system_table
            elif artifact.url.is_wheel:
                yield artifact, None
            else:
                if "file" == artifact.url.scheme:
                    if os.path.isdir(artifact.url.path):
                        cost = 0.0
                    else:
                        # For almost all source archives this value should be <= 1
                        cost = os.path.getsize(artifact.url.path) / 5.0 * 1024 * 1024
                else:
                    # We have no clue how big the archive is, but assume an internet fetch is 10
                    # times more costly per byte than extraction from an archive alone is.
                    cost = 10.0
                undetermined_artifacts[artifact] = cost

        for artifact, build_system_table in iter_map_parallel(
            inputs=undetermined_artifacts,
            function=self._determine_build_system,
            costing_function=lambda a: undetermined_artifacts[a],
            result_render_function=lambda result: (
                cast("Tuple[PartialArtifact, Optional[BuildSystemTable]]", result)[0].url
            ),
            noun="artifact",
            verb="extract build system",
            verb_past="extracted build system",
        ):
            yield artifact, build_system_table

    def _determine_build_system(self, artifact):
        # type: (PartialArtifact) -> Tuple[PartialArtifact, BuildSystemTable]

        if "file" == artifact.url.scheme and os.path.isdir(artifact.url.path):
            return artifact, try_(load_build_system_table(artifact.url.path))

        production_assert(is_sdist(artifact.url.path))
        if artifact.url.scheme == "file":
            archive = artifact.url.path
        else:
            archive = (
                self.resolver.download_requirements(
                    requirements=[artifact.url.download_url], transitive=False
                )
                .local_distributions[0]
                .path
            )
        return artifact, extract_build_system_table(archive)
