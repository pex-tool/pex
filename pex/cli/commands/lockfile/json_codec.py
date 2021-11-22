# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json

from pex import compatibility
from pex.cli.commands.lockfile import ParseError
from pex.cli.commands.lockfile.lockfile import Lockfile
from pex.enum import Enum
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import (
    Artifact,
    Fingerprint,
    LockedRequirement,
    LockedResolve,
    LockStyle,
    Pin,
    Version,
)
from pex.resolve.resolver_configuration import ResolverVersion
from pex.third_party.packaging import tags
from pex.third_party.pkg_resources import Requirement, RequirementParseError
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import (
        Any,
        Dict,
        List,
        Mapping,
        Text,
        Tuple,
        Type,
        TypeVar,
        Union,
    )

    _V = TypeVar("_V", bound=Enum.Value)


def _load_json(
    lockfile_contents,  # type: Text
    source,  # type: str
):
    # type: (...) -> Mapping
    try:
        return cast("Mapping", json.loads(lockfile_contents))
    except ValueError as e:
        raise ParseError(
            "The lock file at {source} does not contain valid JSON: "
            "{err}".format(source=source, err=e)
        )


def loads(
    lockfile_contents,  # type: Text
    source="<string>",  # type: str
):
    # type: (...) -> Lockfile

    def get(
        key,  # type: str
        expected_type=compatibility.string,  # type: Union[Type, Tuple[Type, ...]]
        data=_load_json(lockfile_contents, source=source),  # type: Mapping
        path=".",  # type: str
    ):
        # type: (...) -> Any

        if not isinstance(data, dict):
            raise ParseError(
                "Cannot retrieve '{path}[\"{key}\"]' in {source} because '{path}' is not a "
                "JSON object but a {type} with value {value}.".format(
                    path=path,
                    key=key,
                    source=source,
                    type=type(data).__name__,
                    value=data,
                )
            )
        try:
            value = data[key]
            if not isinstance(value, expected_type):
                raise ParseError(
                    "Expected '{path}[\"{key}\"]' in {source} to be of type {expected_type} "
                    "but given {type} with value {value}.".format(
                        path=path,
                        key=key,
                        source=source,
                        expected_type=(
                            " or ".join(t.__name__ for t in expected_type)
                            if isinstance(expected_type, tuple)
                            else expected_type.__name__
                        ),
                        type=type(value).__name__,
                        value=value,
                    )
                )
            return value
        except KeyError:
            raise ParseError(
                "The object at '{path}' in {source} did not have the expected key "
                "{key!r}.".format(path=path, source=source, key=key)
            )

    def get_enum_value(
        enum_type,  # type: Type[Enum[_V]]
        key,  # type: str
        path=".",  # type: str
    ):
        # type: (...) -> _V
        try:
            return enum_type.for_value(get(key, path=path))
        except ValueError as e:
            raise ParseError(
                "The '{path}[\"{key}\"]' is invalid: {err}".format(key=key, path=path, err=e)
            )

    def parse_requirement(
        raw_requirement,  # type: str
        path,  # type: str
    ):
        # type: (...) -> Requirement
        try:
            return Requirement.parse(raw_requirement)
        except RequirementParseError as e:
            raise ParseError(
                "The requirement string at '{path}' is invalid: {err}".format(path=path, err=e)
            )

    requirements = [
        parse_requirement(req, path=".requirements[{index}]".format(index=index))
        for index, req in enumerate(get("requirements", list))
    ]

    if not requirements:
        raise ParseError(
            "Expected '.requirements' in {source} to have at least one requirement.".format(
                source=source
            )
        )

    constraints = [
        parse_requirement(constraint, path=".constraints[{index}]".format(index=index))
        for index, constraint in enumerate(get("constraints", list))
    ]

    def assemble_tag(
        components,  # type: List[str]
        path,  # type: str
    ):
        # type: (...) -> tags.Tag
        if len(components) != 3 or not all(isinstance(c, compatibility.string) for c in components):
            raise ParseError(
                "The tag at '{path}' must have 3 string components. Given {count} with types "
                "[{types}]: {components}".format(
                    path=path,
                    count=len(components),
                    types=", ".join(type(c).__name__ for c in components),
                    components=components,
                )
            )
        return tags.Tag(interpreter=components[0], abi=components[1], platform=components[2])

    locked_resolves = []
    for lock_index, locked_resolve in enumerate(get("locked_resolves", list)):
        lock_path = ".locked_resolves[{lock_index}]".format(lock_index=lock_index)
        platform_tag = assemble_tag(
            components=get("platform_tag", list, data=locked_resolve, path=lock_path),
            path='{lock_path}["platform_tag"]'.format(lock_path=lock_path),
        )
        locked_reqs = []
        for req_index, req in enumerate(
            get("locked_requirements", list, data=locked_resolve, path=lock_path)
        ):
            req_path = "{lock_path}[{req_index}]".format(lock_path=lock_path, req_index=req_index)

            requirement = parse_requirement(
                raw_requirement=get("requirement", data=req, path=req_path),
                path='{path}["requirement"]'.format(path=req_path),
            )

            artifacts = []
            for i, artifact in enumerate(get("artifacts", list, data=req, path=req_path)):
                ap = '{path}["artifacts"][{index}]'.format(path=req_path, index=i)
                artifacts.append(
                    Artifact(
                        url=get("url", data=artifact, path=ap),
                        fingerprint=Fingerprint(
                            algorithm=get("algorithm", data=artifact, path=ap),
                            hash=get("hash", data=artifact, path=ap),
                        ),
                    )
                )

            if not artifacts:
                raise ParseError(
                    "Expected '{path}' in {source} to have at least one artifact.".format(
                        path=req_path, source=source
                    )
                )
            locked_reqs.append(
                LockedRequirement.create(
                    pin=Pin(
                        project_name=ProjectName(get("project_name", data=req, path=req_path)),
                        version=Version(get("version", data=req, path=req_path)),
                    ),
                    requirement=requirement,
                    artifact=artifacts[0],
                    via=tuple(get("via", list, data=req, path=req_path)),
                    additional_artifacts=artifacts[1:],
                )
            )

        if not locked_reqs:
            raise ParseError(
                "Expected '{lock_path}[\"locked_requirements\"]' in {source} to have at least one "
                "locked requirement.".format(lock_path=lock_path, source=source)
            )
        locked_resolves.append(
            LockedResolve.from_platform_tag(
                platform_tag=platform_tag, locked_requirements=locked_reqs
            )
        )

    if not locked_resolves:
        raise ParseError(
            "Expected '.locked_resolves' in {source} to have at least one resolve.".format(
                source=source
            )
        )

    return Lockfile.create(
        pex_version=get("pex_version"),
        style=get_enum_value(LockStyle, "style"),
        resolver_version=get_enum_value(ResolverVersion, "resolver_version"),
        requirements=requirements,
        constraints=constraints,
        allow_prereleases=get("allow_prereleases", bool),
        allow_wheels=get("allow_wheels", bool),
        allow_builds=get("allow_builds", bool),
        transitive=get("transitive", bool),
        locked_resolves=locked_resolves,
        source=source,
    )


def load(lockfile_path):
    # type: (str) -> Lockfile
    try:
        with open(lockfile_path) as fp:
            return loads(fp.read(), source=lockfile_path)
    except IOError as e:
        raise ParseError(
            "Failed to read lock file at {path}: {err}".format(path=lockfile_path, err=e)
        )


def as_json_data(lockfile):
    # type: (Lockfile) -> Dict[str, Any]
    return {
        "pex_version": lockfile.pex_version,
        "style": str(lockfile.style),
        "resolver_version": str(lockfile.resolver_version),
        "requirements": [str(req) for req in lockfile.requirements],
        "constraints": [str(constraint) for constraint in lockfile.constraints],
        "allow_prereleases": lockfile.allow_prereleases,
        "allow_wheels": lockfile.allow_wheels,
        "allow_builds": lockfile.allow_builds,
        "transitive": lockfile.transitive,
        "locked_resolves": [
            {
                "platform_tag": [
                    locked_resolve.platform_tag.interpreter,
                    locked_resolve.platform_tag.abi,
                    locked_resolve.platform_tag.platform,
                ],
                "locked_requirements": [
                    {
                        "project_name": str(req.pin.project_name),
                        "version": str(req.pin.version),
                        "requirement": str(req.requirement),
                        "via": req.via,
                        "artifacts": [
                            {
                                "url": artifact.url,
                                "algorithm": artifact.fingerprint.algorithm,
                                "hash": artifact.fingerprint.hash,
                            }
                            for artifact in req.iter_artifacts()
                        ],
                    }
                    for req in locked_resolve.locked_requirements
                ],
            }
            for locked_resolve in lockfile.locked_resolves
        ],
    }
