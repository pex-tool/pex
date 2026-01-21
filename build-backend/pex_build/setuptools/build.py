# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import pex_build
from pex_build import serialized_build

import pex.build_backend.wrap

# We re-export all wrapped PEP-517 build backend hooks here for the build frontend to call.
from pex.build_backend.wrap import *  # NOQA
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Dict, List, Optional


def get_requires_for_build_editable(config_settings=None):
    # type: (Optional[Dict[str, Any]]) -> List[str]

    # N.B.: The default setuptools implementation would eventually return nothing, but only after
    # running code that can temporarily pollute our project directory, foiling concurrent test runs;
    # so we short-circuit the answer here. Faster and safer.
    return []


def get_requires_for_build_sdist(config_settings=None):
    # type: (Optional[Dict[str, Any]]) -> List[str]

    # N.B.: The default setuptools implementation would eventually return nothing, but only after
    # running code that can temporarily pollute our project directory, foiling concurrent test runs;
    # so we short-circuit the answer here. Faster and safer.
    return []


build_sdist = serialized_build(pex.build_backend.wrap.build_sdist)
build_wheel = serialized_build(pex.build_backend.wrap.build_wheel)


def _maybe_rewrite_metadata(
    metadata_directory,  # type: str
    dist_info_dir,  # type: str
):
    # type: (...) -> str

    import os.path

    requires_python = os.environ.get("_PEX_REQUIRES_PYTHON")
    if requires_python:
        import email

        metadata_file = os.path.join(metadata_directory, dist_info_dir, "METADATA")
        with open(metadata_file) as fp:
            metadata = email.message_from_file(fp)
        del metadata["Requires-Python"]
        metadata["Requires-Python"] = requires_python
        with open(metadata_file, "w") as fp:
            fp.write(metadata.as_string())
    return dist_info_dir


@serialized_build
def prepare_metadata_for_build_editable(
    metadata_directory,  # type: str
    config_settings=None,  # type: Optional[Dict[str, Any]]
):
    # type: (...) -> str

    return _maybe_rewrite_metadata(
        metadata_directory,
        pex.build_backend.wrap.prepare_metadata_for_build_editable(  # type: ignore[attr-defined]
            metadata_directory, config_settings=config_settings
        ),
    )


@serialized_build
def get_requires_for_build_wheel(config_settings=None):
    # type: (Optional[Dict[str, Any]]) -> List[str]

    if not pex_build.INCLUDE_DOCS:
        return []

    from pex import toml

    pyproject_data = toml.load("pyproject.toml")
    return cast(
        "List[str]",
        # Here we skip any included dependency groups and just grab the direct doc requirements.
        [req for req in pyproject_data["dependency-groups"]["docs"] if isinstance(req, str)],
    )


@serialized_build
def prepare_metadata_for_build_wheel(
    metadata_directory,  # type: str
    config_settings=None,  # type: Optional[Dict[str, Any]]
):
    # type: (...) -> str

    return _maybe_rewrite_metadata(
        metadata_directory,
        pex.build_backend.wrap.prepare_metadata_for_build_wheel(  # type: ignore[attr-defined]
            metadata_directory, config_settings=config_settings
        ),
    )
