# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
from email.message import Message

from pex.common import safe_mkdtemp
from pex.dist_metadata import DistMetadata, DistMetadataFile, MetadataFiles, MetadataType
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Optional


def create_dist_metadata(
    project_name,  # type: str
    version,  # type: str
    requires_python=None,  # type: Optional[str]
    requires_dists=(),  # type: Iterable[str]
    location=None,  # type: Optional[str]
):
    # type: (...) -> DistMetadata

    pkg_info = Message()
    pkg_info.add_header("Name", project_name)
    pkg_info.add_header("Version", version)
    if requires_python:
        pkg_info.add_header("Requires-Python", requires_python)
    for requirement in requires_dists:
        pkg_info.add_header("Requires-Dist", requirement)
    return DistMetadata.from_metadata_files(
        MetadataFiles(
            DistMetadataFile(
                type=MetadataType.DIST_INFO,
                location=location or safe_mkdtemp(),
                rel_path=os.path.join(
                    "{project_name}-{version}.dist-info".format(
                        project_name=project_name, version=version
                    ),
                    "METADATA",
                ),
                project_name=ProjectName(project_name),
                version=Version(version),
                pkg_info=pkg_info,
            )
        )
    )
