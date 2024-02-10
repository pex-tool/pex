# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import io
import json
import sys

from pex.compatibility import HTTPError, string, text, urlparse
from pex.fetcher import URLFetcher
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.pep_691.model import Endpoint, File, Meta, Project
from pex.resolve.resolved_requirement import ArtifactURL, Fingerprint
from pex.sorted_tuple import SortedTuple
from pex.third_party.packaging.version import Version as PackagingVersion
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast, overload

if TYPE_CHECKING:
    from typing import Any, Dict, Optional, Tuple, Type, TypeVar, Union

    import attr  # vendor:skip

    _V = TypeVar("_V")
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Client(object):
    class Error(Exception):
        """Indicates an error accessing or parsing the results of a PEP-691 API endpoint."""

    ACCEPT = ("application/vnd.pypi.simple.v1+json",)

    _url_fetcher = attr.ib(factory=URLFetcher)  # type: URLFetcher

    def request(self, endpoint):
        # type: (Endpoint) -> Project
        """Fetches PEP-691 project file metadata from the endpoint.

        Raises :class:`Client.Error` if there is a problem accessing the endpoint or parsing the
        results returned from it.
        """

        if endpoint.content_type not in self.ACCEPT:
            raise ValueError(
                "Asked to request project metadata from {url} for {content_type} but only the "
                "following API content types are accepted: {accepted}".format(
                    url=endpoint.url,
                    content_type=endpoint.content_type,
                    accepted=", ".join(self.ACCEPT),
                )
            )

        def request_error(msg):
            # type: (str) -> Client.Error
            return self.Error(
                "PEP-691 API request to {url} for {content_type} {msg}".format(
                    url=endpoint.url, content_type=endpoint.content_type, msg=msg
                )
            )

        try:
            with TRACER.timed(
                "Fetching PEP-691 index metadata from {url} for {content_type}".format(
                    url=endpoint.url, content_type=endpoint.content_type
                )
            ):
                with self._url_fetcher.get_body_stream(
                    endpoint.url, extra_headers={"Accept": endpoint.content_type}
                ) as fp:
                    # Python 3.5 alone amongst Pex supported Python versions requires a text
                    # stream and JSON exchanged between systems must be UTF-8:
                    # https://www.rfc-editor.org/rfc/rfc8259#section-8.1
                    stream = (
                        io.TextIOWrapper(fp, encoding="utf-8")
                        if sys.version_info[:2] == (3, 5)
                        else fp
                    )
                    # The above is tested to work with PyPy 2.7, PyPy 3.{6,7,8,9}, CPython 2.7 and
                    # CPython 3.{5,6,7,8,9,10,11}; so the type suppression is well vetted here.
                    data = json.load(stream)  # type: ignore[arg-type]
        except (IOError, OSError, HTTPError) as e:
            raise request_error("failed: {err}".format(err=e))
        except ValueError as e:
            raise request_error("returned invalid JSON: {err}".format(err=e))

        def response_error(msg):
            # type: (str) -> Client.Error
            return self.Error(
                "PEP-691 API response from {url} for {content_type} {msg}:\n{response}".format(
                    url=endpoint.url,
                    content_type=endpoint.content_type,
                    msg=msg,
                    response=json.dumps(data, indent=2),
                )
            )

        if not isinstance(data, dict):
            raise response_error(
                "was supposed to return a JSON object but returned a JSON {type}.".format(
                    type=type(data).__name__
                )
            )

        @overload
        def get(
            key,  # type: str
            expected_type,  # type: Type[_V]
            obj=None,  # type: Optional[Dict[str, Any]]
            default=None,  # type: Optional[_V]
            path=".",  # type: str
        ):
            # type: (...) -> _V
            pass

        @overload
        def get(
            key,  # type: str
            expected_type,  # type: Tuple[Type, ...]
            obj=None,  # type: Optional[Dict[str, Any]]
            default=None,  # type: Optional[Any]
            path=".",  # type: str
        ):
            # type: (...) -> Any
            pass

        def get(
            key,  # type: str
            expected_type,  # type: Union[Type[_V], Tuple[Type, ...]]
            obj=None,  # type: Optional[Dict[str, Any]]
            default=None,  # type: Optional[_V]
            path=".",  # type: str
        ):
            # type: (...) -> Any
            if obj and not isinstance(obj, dict):
                raise response_error(
                    "was expected to contain an object at '{path}' but contained a {type} "
                    "instead".format(path=path, type=type(obj).__name__)
                )

            obj = obj or data
            try:
                value = obj[key]
            except KeyError:
                if default is not None:
                    return default
                raise response_error(
                    "did not contain the expected key '{path}[\"{key}\"]'".format(
                        path=path, key=key
                    )
                )

            if not isinstance(value, expected_type):
                raise response_error(
                    "was expected to contain a {expected_type} at '{path}[\"{key}\"]' but "
                    "contained a {type} instead.".format(
                        expected_type=expected_type.__name__
                        if isinstance(expected_type, type)
                        else " or ".join(et.__name__ for et in expected_type),
                        path=path,
                        key=key,
                        type=type(value).__name__,
                    )
                )

            return value

        api_version = Version(get("api-version", text, obj=get("meta", dict), path=".meta"))
        if not isinstance(api_version.parsed_version, PackagingVersion):
            raise response_error(
                "reports an api-version of {api_version} which does not have the required "
                "<major>.<minor> structure.".format(api_version=api_version.raw)
            )
        if api_version.parsed_version.major != 1:
            raise response_error(
                "reports an api-version of {api_version} and Pex currently only supports "
                "api-version 1.x".format(api_version=api_version.raw)
            )

        name = ProjectName(get("name", text))

        files = []
        for index, file in enumerate(get("files", list, default=[]), start=0):
            path = ".files[{index}]".format(index=index)

            fingerprints = []
            for algorithm, hash_ in get("hashes", dict, obj=file, path=path).items():
                if not isinstance(hash_, text):
                    raise response_error(
                        "reports a hash value of {hash} of type {type} for "
                        "'{path}.hashes[\"{algorithm}\"]' but hash values should be strings".format(
                            hash=hash_, type=type(hash_).__name__, path=path, algorithm=algorithm
                        )
                    )
                fingerprints.append(
                    Fingerprint(
                        algorithm=algorithm,
                        # N.B.: Hash values are hex which is ascii; so cast(str, hash_) is correct
                        # for Python 2.7.
                        hash=cast(str, hash_),
                    )
                )

            # N.B.: All URLs in the PEP-691 API are allowed to be relative, see:
            #   https://peps.python.org/pep-0691/#json-serialization
            # The `urljoin` functions does the right thing here and creates an absolute URL
            # only when needed (never for the current PyPI scheme, potentially for other
            # indexes though).
            absolute_url = urlparse.urljoin(endpoint.url, get("url", string, obj=file, path=path))
            files.append(
                File(
                    filename=get("filename", text, obj=file, path=path),
                    url=ArtifactURL.parse(absolute_url),
                    hashes=SortedTuple(fingerprints),
                )
            )

        return Project(name=name, files=SortedTuple(files), meta=Meta(api_version=api_version))
