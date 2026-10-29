# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import importlib
import json
import os
import sys
from argparse import ArgumentParser

# When running under MyPy, this will be set to True for us automatically; so we can use it as a
# typing module import guard to protect Python 2 imports of typing - which is not normally available
# in Python 2.
TYPE_CHECKING = False

if TYPE_CHECKING:
    from typing import Iterable, List, Optional, Tuple


def write_bindings(
    env_file,  # type: str
    bound_resource_paths=(),  # type: Tuple[Tuple[str, str], ...]
):
    # type: (...) -> None

    bindings = [
        {"key": "BIND_RESOURCE_" + env_name, "value": resource_path, "brake": "file"}
        for env_name, resource_path in bound_resource_paths
    ]
    with open(env_file, "w") as fp:
        json.dump(bindings, fp)


class ResourceBindingError(Exception):
    pass


def imported_file(
    module_name,  # type: str
    resource_name,  # type: str
):
    # type: (...) -> str
    try:
        path = importlib.import_module(module_name).__file__
    except ImportError as e:
        raise ResourceBindingError(
            "Failed to bind resource {resource}: {err}".format(resource=resource_name, err=e)
        )
    if path is None:
        raise ResourceBindingError(
            "Failed to bind path of resource {resource}: it exists but {module} has no __file__ "
            "attribute.".format(resource=resource_name, module=module_name)
        )
    return path


def _resolve_resource_path(
    name,  # type: str
    resource,  # type: str
):
    # type: (...) -> str

    if os.path.isabs(resource):
        raise ResourceBindingError(
            "The following resource binding spec is invalid: {name}={resource}\n"
            "The resource path {resource} must be relative to the `sys.path`.".format(
                name=name, resource=resource
            )
        )

    resource_path = None  # type: Optional[str]
    parents = []  # type: List[str]
    for component in resource.split("/"):
        if component == os.pardir:
            if resource_path is None:
                raise ResourceBindingError(
                    "The following resource binding spec is invalid: {name}={resource}\n"
                    "The resource path {resource} must be relative to the `sys.path`.".format(
                        name=name, resource=resource
                    )
                )
            parents.append(component)
        elif parents:
            raise ResourceBindingError(
                "The following resource binding spec is invalid: {name}={resource}\n"
                "The resource path {resource} can only have trailing {parent_dir} components; "
                "not embedded ones.".format(name=name, resource=resource, parent_dir=os.pardir)
            )
        elif resource_path is None:
            resource_path = component
        else:
            resource_path = os.path.join(resource_path, component)

    if not resource_path:
        raise ResourceBindingError(
            "The following resource binding spec is invalid: {name}={resource}\n"
            "The resource path cannot be empty.".format(name=name, resource=resource)
        )
    rel_path = os.path.normpath(resource_path)

    for entry in sys.path:
        value = os.path.join(entry, rel_path)
        if os.path.isfile(value):
            if parents:
                value = os.path.normpath(os.path.join(value, *parents))
                if not value.startswith(entry):
                    raise ResourceBindingError(
                        "The resource binding spec {name}={resource} resolved to {value} which "
                        "escapes the `sys.path` entry {entry}.".format(
                            name=name, resource=resource, value=value, entry=entry
                        )
                    )
            return value

    raise ResourceBindingError(
        "There was no resource file {resource} found on the `sys.path` corresponding to "
        "the given resource binding spec `{name}={resource}`".format(resource=resource, name=name)
    )


def bind_resource_paths(bindings):
    # type: (Iterable[str]) -> Tuple[Tuple[str, str], ...]

    resource_paths = []  # type: List[Tuple[str, str]]
    for spec in bindings:
        try:
            name, resource = spec.split("=")
        except ValueError:
            raise ResourceBindingError(
                "The following resource binding spec is invalid: {spec}\n"
                "It must be in the form `<env var name>=<resource rel path>`.".format(spec=spec)
            )

        resource_paths.append((name, _resolve_resource_path(name, resource)))
    return tuple(resource_paths)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--bind-resource-path",
        dest="bind_resource_paths",
        default=[],
        action="append",
        help=(
            "An environment variable name to bind the path of a Python resource to in the form "
            "`<name>=<resource>`."
        ),
    )
    options = parser.parse_args()

    try:
        bound_resource_paths = bind_resource_paths(options.bind_resource_paths)
    except ResourceBindingError as e:
        sys.exit(str(e))

    write_bindings(
        env_file=os.environ["SCIE_BINDING_JSON"], bound_resource_paths=bound_resource_paths
    )
    sys.exit(0)
