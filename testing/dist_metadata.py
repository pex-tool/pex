# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import glob
import os.path
from email.message import Message
from typing import Callable, Text, Tuple

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
    metadata_type=MetadataType.DIST_INFO,  # type: MetadataType.Value
):
    # type: (...) -> DistMetadata

    pkg_info = Message()
    pkg_info.add_header("Name", project_name)
    pkg_info.add_header("Version", version)
    if requires_python:
        pkg_info.add_header("Requires-Python", requires_python)
    for requirement in requires_dists:
        pkg_info.add_header("Requires-Dist", requirement)

    resolved_location = location or safe_mkdtemp()
    metadata_dir = "{project_name}-{version}.{suffix}".format(
        project_name=project_name,
        version=version,
        suffix="dist-info" if metadata_type is MetadataType.DIST_INFO else "egg-info",
    )
    metadata_file_name = "METADATA" if metadata_type is MetadataType.DIST_INFO else "PKG-INFO"

    additional_metadata_files = ()  # type: Tuple[Text, ...]
    read_function = None  # type: Optional[Callable[[Text], bytes]]
    if os.path.isdir(resolved_location):
        additional_metadata_files = tuple(
            os.path.relpath(metadata_path, resolved_location)
            for metadata_path in glob.glob(os.path.join(resolved_location, metadata_dir, "*"))
            if os.path.basename(metadata_path) != metadata_file_name
        )
        if additional_metadata_files:

            def read_function(rel_path):
                # type: (Text) -> bytes
                with open(os.path.join(resolved_location, rel_path), "rb") as fp:
                    return fp.read()

    return DistMetadata.from_metadata_files(
        MetadataFiles(
            metadata=DistMetadataFile(
                type=metadata_type,
                location=resolved_location,
                rel_path=os.path.join(metadata_dir, metadata_file_name),
                project_name=ProjectName(project_name),
                version=Version(version),
                pkg_info=pkg_info,
            ),
            additional_metadata_files=additional_metadata_files,
            read_function=read_function,
        )
    )
