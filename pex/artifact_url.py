# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import codecs
import hashlib
import re
from collections import defaultdict

from pex import hashing
from pex.compatibility import PY3, url_unquote, url_unquote_plus, urlparse
from pex.dist_metadata import is_wheel
from pex.enum import Enum
from pex.hashing import HashlibHasher
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import (
        BinaryIO,
        Container,
        DefaultDict,
        Dict,
        Iterable,
        List,
        Mapping,
        Optional,
        Sequence,
        Text,
        Tuple,
        Union,
    )

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class VCS(Enum["VCS.Value"]):
    class Value(Enum.Value):
        pass

    Bazaar = Value("bzr")
    Git = Value("git")
    Mercurial = Value("hg")
    Subversion = Value("svn")


VCS.seal()


@attr.s(frozen=True)
class VCSScheme(object):
    vcs = attr.ib()  # type: VCS.Value
    scheme = attr.ib()  # type: str


class ArchiveScheme(Enum["ArchiveScheme.Value"]):
    class Value(Enum.Value):
        pass

    FTP = Value("ftp")
    HTTP = Value("http")
    HTTPS = Value("https")


ArchiveScheme.seal()


def parse_scheme(scheme):
    # type: (str) -> Union[str, ArchiveScheme.Value, VCSScheme]
    match = re.match(
        r"""
        ^
        (?:
            (?P<archive_scheme>
                # Archives
                  ftp
                | https?
            )
            |
            (?P<vcs_type>
                # VCSs: https://pip.pypa.io/en/stable/reference/pip_install/#vcs-support
                  bzr
                | git
                | hg
                | svn
            )\+(?P<vcs_scheme>.+)
        )
        $
        """,
        scheme,
        re.VERBOSE,
    )
    if not match:
        return scheme

    archive_scheme = match.group("archive_scheme")
    if archive_scheme:
        return cast(ArchiveScheme.Value, ArchiveScheme.for_value(archive_scheme))

    return VCSScheme(vcs=VCS.for_value(match.group("vcs_type")), scheme=match.group("vcs_scheme"))


@attr.s(frozen=True)
class Fingerprint(object):
    @classmethod
    def from_stream(
        cls,
        stream,  # type: BinaryIO
        algorithm="sha256",  # type: str
    ):
        # type: (...) -> Fingerprint
        digest = hashlib.new(algorithm)
        hashing.update_hash(filelike=stream, digest=digest)
        return cls(algorithm=algorithm, hash=digest.hexdigest())

    @classmethod
    def from_digest(cls, digest):
        # type: (HashlibHasher) -> Fingerprint
        return cls.from_hashing_fingerprint(digest.hexdigest())

    @classmethod
    def from_hashing_fingerprint(cls, fingerprint):
        # type: (hashing.Fingerprint) -> Fingerprint
        return cls(algorithm=fingerprint.algorithm, hash=fingerprint)

    algorithm = attr.ib()  # type: str
    hash = attr.ib()  # type: str


# These ranks prefer the highest digest size and then use alphabetic order for a tie-break.
RANKED_ALGORITHMS = tuple(
    sorted(
        hashlib.algorithms_guaranteed,
        key=lambda alg: (-hashlib.new(alg).digest_size, alg),
    )
)


def parse_qs(query_string):
    # type: (str) -> Dict[str, List[str]]
    if PY3:
        return urlparse.parse_qs(query_string)
    else:
        # N.B.: Python2.7 splits parameters on `&` _and_ `;`. We only want splits on `&`.
        parameters = defaultdict(list)  # type: DefaultDict[str, List[str]]
        for parameter in query_string.split("&"):
            raw_name, sep, raw_value = parameter.partition("=")
            if not sep:
                continue
            name = url_unquote_plus(raw_name)
            value = url_unquote_plus(raw_value)
            parameters[name].append(value)
        return parameters


@attr.s(frozen=True)
class ArtifactURL(object):
    @staticmethod
    def create_fragment(
        fragment_parameters,  # type: Mapping[str, Iterable[str]]
        excludes=(),  # type: Container[str]
    ):
        # type: (...) -> str
        return "&".join(
            sorted(
                "{name}={value}".format(name=name, value=value)
                for name, values in fragment_parameters.items()
                for value in values
                if name not in excludes
            )
        )

    @classmethod
    def parse(cls, url):
        # type: (Text) -> ArtifactURL

        try:
            codecs.encode(url, "ascii")
        except ValueError as e:
            raise ValueError(
                "Invalid URL:{url}\n"
                "URLs can only contain ASCII octets: {err}".format(url=url, err=e)
            )
        else:
            raw_url = str(url)

        url_info = urlparse.urlparse(raw_url)
        scheme = parse_scheme(url_info.scheme) if url_info.scheme else "file"
        path = url_unquote(url_info.path)

        parameters = url_unquote(url_info.params)

        fingerprints = []
        fragment_parameters = parse_qs(url_info.fragment)
        if fragment_parameters:
            # Artifact URLs from indexes may contain pre-computed hashes. We isolate those here,
            # centrally, if present.
            # See: https://peps.python.org/pep-0503/#specification
            for alg in RANKED_ALGORITHMS:
                hashes = fragment_parameters.pop(alg, None)
                if not hashes:
                    continue
                if len(hashes) > 1 and len(set(hashes)) > 1:
                    TRACER.log(
                        "The artifact url contains multiple distinct hash values for the {alg} "
                        "algorithm, not trusting any of these: {url}".format(alg=alg, url=url)
                    )
                    continue
                fingerprints.append(Fingerprint(algorithm=alg, hash=hashes[0]))

        subdirectories = fragment_parameters.get("subdirectory")
        subdirectory = subdirectories[-1] if subdirectories else None

        download_url = urlparse.urlunparse(
            url_info._replace(fragment=cls.create_fragment(fragment_parameters))
        )
        normalized_url = urlparse.urlunparse(
            url_info._replace(path=path, params="", query="", fragment="")
        )
        return cls(
            raw_url=raw_url,
            url_info=url_info,
            download_url=download_url,
            normalized_url=normalized_url,
            scheme=scheme,
            path=path,
            subdirectory=subdirectory,
            parameters=parameters,
            fragment_parameters=fragment_parameters,
            fingerprints=tuple(fingerprints),
        )

    raw_url = attr.ib(eq=False)  # type: str
    url_info = attr.ib(eq=False)  # type: urlparse.ParseResult
    download_url = attr.ib(eq=False)  # type: str
    normalized_url = attr.ib()  # type: str
    scheme = attr.ib(eq=False)  # type: Union[str, ArchiveScheme.Value, VCSScheme]
    path = attr.ib(eq=False)  # type: str
    subdirectory = attr.ib(eq=False)  # type: Optional[str]
    parameters = attr.ib(eq=False)  # type: str
    fragment_parameters = attr.ib(eq=False)  # type: Mapping[str, Sequence[str]]
    fingerprints = attr.ib(eq=False)  # type: Tuple[Fingerprint, ...]

    def fragment(self, excludes=()):
        # type: (Container[str]) -> str
        return self.create_fragment(self.fragment_parameters, excludes=excludes)

    @property
    def is_wheel(self):
        # type: () -> bool
        return is_wheel(self.path)

    @property
    def fingerprint(self):
        # type: () -> Optional[Fingerprint]
        return self.fingerprints[0] if self.fingerprints else None
