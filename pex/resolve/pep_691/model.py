# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import hashlib

from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.resolved_requirement import ArtifactURL, Fingerprint
from pex.sorted_tuple import SortedTuple
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Optional, Text

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class File(object):
    # These ranks prefer the highest digest size and then use alphabetic order for a tie-break.
    _GUARANTEED_HASH_ALGORITHM_DIGEST_RANKS = {
        algorithm: (-hashlib.new(algorithm).digest_size, algorithm)
        for algorithm in hashlib.algorithms_guaranteed
    }

    @classmethod
    def _select_algorithm(cls, algorithms):
        # type: (Iterable[str]) -> Optional[str]

        # See: https://peps.python.org/pep-0691/#project-detail
        # In short, sha256 is recommended, but it is highly recommended that at
        # least 1 guaranteed available hash is presented. We only collect from
        # guaranteed so that our lock files are usefully portable. If there are
        # hashes present but none are in the guaranteed set, this just means we'll
        # fall back to downloading the artifact and hashing it with sha256.
        if "sha256" in algorithms:
            return "sha256"

        ranked_algorithms = sorted(
            (alg for alg in algorithms if alg in cls._GUARANTEED_HASH_ALGORITHM_DIGEST_RANKS),
            key=lambda alg: cls._GUARANTEED_HASH_ALGORITHM_DIGEST_RANKS[alg],
        )
        return ranked_algorithms[0] if ranked_algorithms else None

    filename = attr.ib()  # type: Text
    url = attr.ib()  # type: ArtifactURL
    hashes = attr.ib()  # type: SortedTuple[Fingerprint]

    def select_fingerprint(self):
        # type: () -> Optional[Fingerprint]
        """Selects the "best" fingerprint, if any, for this file from amongst its hashes."""
        fingerprints_by_algorithm = {
            fingerprint.algorithm: fingerprint for fingerprint in self.hashes
        }
        algorithm = self._select_algorithm(fingerprints_by_algorithm)
        if algorithm is None:
            return None
        return fingerprints_by_algorithm[algorithm]


@attr.s(frozen=True)
class Meta(object):
    api_version = attr.ib()  # type: Version


@attr.s(frozen=True)
class Project(object):
    """The required data in a PEP-691 project response."""

    name = attr.ib()  # type: ProjectName
    files = attr.ib()  # type: SortedTuple[File]
    meta = attr.ib()


@attr.s(frozen=True)
class Endpoint(object):
    url = attr.ib()  # type: str
    content_type = attr.ib()  # type: str
