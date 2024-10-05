# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import sqlite3
from contextlib import closing, contextmanager
from itertools import repeat
from multiprocessing.pool import ThreadPool

from pex import pex_warnings
from pex.atomic_directory import atomic_directory
from pex.cache.dirs import CacheDir
from pex.compatibility import cpu_count
from pex.fetcher import URLFetcher
from pex.resolve.pep_691.api import Client
from pex.resolve.pep_691.model import Endpoint, Project
from pex.resolve.resolved_requirement import Fingerprint, PartialArtifact
from pex.resolve.resolvers import MAX_PARALLEL_DOWNLOADS
from pex.result import Error, catch
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class _FingerprintedURL(object):
    url = attr.ib()  # type: str
    fingerprint = attr.ib()  # type: Fingerprint


@attr.s(frozen=True)
class FingerprintService(object):
    @classmethod
    def create(
        cls,
        url_fetcher,  # type: URLFetcher
        max_parallel_jobs=None,  # type: Optional[int]
    ):
        return cls(api=Client(url_fetcher=url_fetcher), max_parallel_jobs=max_parallel_jobs)

    _api = attr.ib(factory=Client)  # type: Client
    _db_dir = attr.ib(factory=lambda: CacheDir.DBS.path("pep_691"))  # type: str
    _max_parallel_jobs = attr.ib(default=None)  # type: Optional[int]

    @property
    def accept(self):
        # type: () -> Tuple[str, ...]
        return self._api.ACCEPT

    _SCHEMA = """
    PRAGMA journal_mode=WAL;

    CREATE TABLE hashes (
        url TEXT PRIMARY KEY ASC,
        algorithm TEXT NOT NULL,
        hash TEXT NOT NULL
    ) WITHOUT ROWID;
    """

    @contextmanager
    def _db_connection(self):
        # type: () -> Iterator[sqlite3.Connection]
        with atomic_directory(self._db_dir) as atomic_dir:
            if not atomic_dir.is_finalized():
                with sqlite3.connect(os.path.join(atomic_dir.work_dir, "fingerprints.db")) as conn:
                    conn.executescript(self._SCHEMA).close()
        with sqlite3.connect(os.path.join(self._db_dir, "fingerprints.db")) as conn:
            conn.execute("PRAGMA synchronous=NORMAL").close()
            yield conn

    def _iter_cached(self, urls_to_fingerprint):
        # type: (Iterable[str]) -> Iterator[_FingerprintedURL]

        urls = sorted(urls_to_fingerprint)
        with TRACER.timed("Searching for {count} fingerprints in database".format(count=len(urls))):
            with self._db_connection() as conn:
                # N.B.: Maximum parameter count is 999 in pre-2020 versions of SQLite 3; so we limit
                # to an even lower chunk size to be safe: https://www.sqlite.org/limits.html
                chunk_size = 100
                for index in range(0, len(urls), chunk_size):
                    chunk = urls[index : index + chunk_size]
                    with closing(
                        conn.execute(
                            "SELECT url, algorithm, hash FROM hashes WHERE url IN ({})".format(
                                ", ".join(repeat("?", len(chunk)))
                            ),
                            tuple(chunk),
                        )
                    ) as cursor:
                        for url, algorithm, hash_ in cursor:
                            yield _FingerprintedURL(
                                url=url, fingerprint=Fingerprint(algorithm=algorithm, hash=hash_)
                            )

    def _cache(self, fingerprinted_urls):
        # type: (Sequence[_FingerprintedURL]) -> None

        with TRACER.timed(
            "Caching {count} fingerprints in database".format(count=len(fingerprinted_urls))
        ):
            with self._db_connection() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO hashes (url, algorithm, hash) VALUES (?, ?, ?)",
                    tuple(
                        (
                            fingerprinted_url.url,
                            fingerprinted_url.fingerprint.algorithm,
                            fingerprinted_url.fingerprint.hash,
                        )
                        for fingerprinted_url in fingerprinted_urls
                    ),
                ).close()

    def _safe_request(self, endpoint):
        # type: (Endpoint) -> Union[Project, Error]
        return catch(self._api.request, endpoint)

    @staticmethod
    def _warn_database_error(
        error,  # type: sqlite3.DatabaseError
        message,  # type: str
    ):
        pex_warnings.warn(
            "{message}: {error}\n"
            "\n"
            "If you encounter this error frequently, Pex may need to adjust how it uses SQLite for "
            "its cache of artifact fingerprints obtained from PEP-691 indexes. Please consider "
            "reporting the problem by filing an issue at "
            "https://github.com/pex-tool/pex/issues/new.".format(message=message, error=error)
        )

    def fingerprint(
        self,
        endpoints,  # type: Set[Endpoint]
        artifacts,  # type: Iterable[PartialArtifact]
    ):
        # type: (...) -> Iterator[PartialArtifact]
        """Attempts to fingerprint all artifacts that are missing a fingerprint.

        Fingerprints are obtained via the PEP-691 JSON API and are not verified.

        :param artifacts: The artifacts to fill in missing fingerprints for.
        :return: An iterator over all the artifacts given, where some returned artifacts may have
                 previously missing fingerprints filled in (but not verified).
        """
        # N.B.: In the absence of having an advertised fingerprint for an artifact, Pex will
        # download the artifact and hash it at higher layers; so simply warning about the error is
        # enough; we need not fail the whole endeavor. The partial artifact just remains partial
        # and becomes more expensive to lock. The warning is likely un-actionable by the user but
        # also rare; so it can be reported to maintainers in case the 5s default sqlite3 timeout is
        # being hit or something similar that might be mitigated by adding more code here.

        artifacts_to_fingerprint = {}  # type: Dict[str, PartialArtifact]
        for artifact in artifacts:
            if artifact.fingerprint:
                yield artifact
            else:
                artifacts_to_fingerprint[artifact.url.normalized_url] = artifact

        if not artifacts_to_fingerprint:
            return

        try:
            cached = 0
            for fingerprinted_url in self._iter_cached(artifacts_to_fingerprint):
                yield attr.evolve(
                    artifacts_to_fingerprint[fingerprinted_url.url],
                    fingerprint=fingerprinted_url.fingerprint,
                )
                artifacts_to_fingerprint.pop(fingerprinted_url.url)
                cached += 1
            TRACER.log("Found {count} fingerprints cached in database.".format(count=cached))
        except sqlite3.DatabaseError as e:
            self._warn_database_error(
                error=e,
                message=(
                    "Failed to read fingerprints from the cache, continuing to fetch them via the "
                    "PEP-691 JSON API instead"
                ),
            )

        if not artifacts_to_fingerprint:
            return

        max_threads = min(
            len(endpoints) or 1,
            min(MAX_PARALLEL_DOWNLOADS, 4 * (self._max_parallel_jobs or cpu_count() or 1)),
        )
        with TRACER.timed(
            "Making {api_count} PEP-691 JSON API requests across {thread_count} threads to "
            "fingerprint {artifact_count} artifacts".format(
                api_count=len(endpoints),
                thread_count=max_threads,
                artifact_count=len(artifacts_to_fingerprint),
            )
        ):
            pool = ThreadPool(processes=max_threads)
            try:
                api_results = pool.map(self._safe_request, endpoints)
            finally:
                pool.close()
                pool.join()

        fingerprinted_urls = []  # type: List[_FingerprintedURL]
        for result in api_results:
            if isinstance(result, Error):
                pex_warnings.warn(
                    "Failed to fetch project metadata, continuing: {error}".format(error=result)
                )
                continue

            for file in result.files:
                fingerprinted_artifact = artifacts_to_fingerprint.pop(file.url.normalized_url, None)
                if not fingerprinted_artifact:
                    continue

                maybe_fingerprint = file.select_fingerprint()
                yield attr.evolve(fingerprinted_artifact, fingerprint=maybe_fingerprint)
                if maybe_fingerprint:
                    fingerprinted_urls.append(
                        _FingerprintedURL(
                            url=file.url.normalized_url, fingerprint=maybe_fingerprint
                        )
                    )

        # The remaining artifacts have no fingerprint and no endpoint to fetch the data from; so we
        # just return them as-is.
        for artifact in artifacts_to_fingerprint.values():
            yield artifact

        if not fingerprinted_urls:
            return

        try:
            self._cache(fingerprinted_urls)
        except sqlite3.DatabaseError as e:
            self._warn_database_error(
                error=e,
                message="Failed to cache fingerprints for {count} URLs, continuing".format(
                    count=len(fingerprinted_urls)
                ),
            )
