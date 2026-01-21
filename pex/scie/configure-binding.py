# Copyright 2024 Pex project contributors.
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
    pex,  # type: str
    venv_bin_dir=None,  # type: Optional[str]
    bound_resource_paths=(),  # type: Tuple[Tuple[str, str], ...]
):
    # type: (...) -> None

    with open(env_file, "a") as fp:
        print("PYTHON=" + sys.executable, file=fp)
        print("PEX=" + pex, file=fp)
        if venv_bin_dir:
            print("VIRTUAL_ENV=" + os.path.dirname(venv_bin_dir), file=fp)
            print("VENV_BIN_DIR_PLUS_SEP=" + venv_bin_dir + os.path.sep, file=fp)
        for env_name, resource_path in bound_resource_paths:
            print("BIND_RESOURCE_" + env_name + "=" + resource_path, file=fp)


class PexDirNotFound(Exception):
    pass


def find_pex_dir(pex_hash):
    # type: (str) -> str

    for entry in sys.path:
        pex_info = os.path.join(entry, "PEX-INFO")
        if not os.path.exists(pex_info):
            continue
        try:
            with open(pex_info) as fp:
                data = json.load(fp)
        except (IOError, OSError, ValueError):
            continue
        else:
            if pex_hash == data.get("pex_hash"):
                return os.path.realpath(entry)
    raise PexDirNotFound()


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

        rel_path = os.path.normpath(os.path.join(*resource.split("/")))
        if os.path.isabs(resource) or rel_path.startswith(os.pardir):
            raise ResourceBindingError(
                "The following resource binding spec is invalid: {spec}\n"
                "The resource path {resource} must be relative to the `sys.path`.".format(
                    spec=spec, resource=resource
                )
            )

        for entry in sys.path:
            value = os.path.join(entry, rel_path)
            if os.path.isfile(value):
                resource_paths.append((name, value))
                break
        else:
            raise ResourceBindingError(
                "There was no resource file {resource} found on the `sys.path` corresponding to "
                "the given resource binding spec `{spec}`".format(resource=resource, spec=spec)
            )
    return tuple(resource_paths)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "pex_hash",
        nargs=1,
        help="The PEX hash.",
    )
    parser.add_argument("--venv-bin-dir", help="The platform-specific venv bin dir name.")
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

    pex_hash = options.pex_hash[0]

    try:
        pex = find_pex_dir(pex_hash)
    except PexDirNotFound:
        sys.exit(
            "Failed to determine installed PEX (pex_hash: {pex_hash}) directory using sys.path:\n"
            "    {sys_path}".format(
                pex_hash=pex_hash,
                sys_path=os.linesep.join("    {entry}".format(entry=entry) for entry in sys.path),
            )
        )

    try:
        bound_resource_paths = bind_resource_paths(options.bind_resource_paths)
    except ResourceBindingError as e:
        sys.exit(str(e))

    write_bindings(
        env_file=os.environ["SCIE_BINDING_ENV"],
        pex=pex,
        venv_bin_dir=os.path.join(pex, options.venv_bin_dir) if options.venv_bin_dir else None,
        bound_resource_paths=bound_resource_paths,
    )
    sys.exit(0)
