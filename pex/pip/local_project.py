# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path

from pex import hashing, sdist
from pex.build_system import pep_517
from pex.common import temporary_dir
from pex.pip.version import PipVersionValue
from pex.resolve.resolvers import Resolver
from pex.result import Error
from pex.targets import Target
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional, Union

    from pex.hashing import HintedDigest


def digest_local_project(
    directory,  # type: str
    digest,  # type: HintedDigest
    target,  # type: Target
    resolver,  # type: Resolver
    dest_dir=None,  # type: Optional[str]
    pip_version=None,  # type: Optional[PipVersionValue]
):
    # type: (...) -> Union[str, Error]
    with TRACER.timed("Fingerprinting local project at {directory}".format(directory=directory)):
        with temporary_dir() as td:
            sdist_path_or_error = pep_517.build_sdist(
                project_directory=directory,
                dist_dir=os.path.join(td, "dists"),
                pip_version=pip_version,
                target=target,
                resolver=resolver,
            )
            if isinstance(sdist_path_or_error, Error):
                return sdist_path_or_error
            sdist_path = sdist_path_or_error

            extract_dir = dest_dir or os.path.join(td, "extracted")
            project_dir = sdist.extract_tarball(sdist_path, dest_dir=extract_dir)
            hashing.dir_hash(directory=project_dir, digest=digest)
            return os.path.join(extract_dir, project_dir)
