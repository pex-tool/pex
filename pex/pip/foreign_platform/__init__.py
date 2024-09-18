# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os

from pex.common import safe_mkdtemp
from pex.interpreter_constraints import iter_compatible_versions
from pex.pep_425 import CompatibilityTags
from pex.pip.download_observer import DownloadObserver, Patch, PatchSet
from pex.platforms import PlatformSpec
from pex.targets import AbbreviatedPlatform, CompletePlatform, Target
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Iterable, Iterator, Mapping, Optional


def iter_platform_args(
    platform_spec,  # type: PlatformSpec
    manylinux=None,  # type: Optional[str]
):
    # type: (...) -> Iterator[str]

    platform = platform_spec.platform
    # N.B.: Pip supports passing multiple --platform and --abi. We pass multiple --platform to
    # support the following use case 1st surfaced by Twitter in 2018:
    #
    # An organization has its own index or find-links repository where it publishes wheels built
    # for linux machines it runs. Critically, all those machines present uniform kernel and
    # library ABIs for the purposes of python code that organization runs on those machines.
    # As such, the organization can build non-manylinux-compliant wheels and serve these wheels
    # from its private index / find-links repository with confidence these wheels will work on
    # the machines it controls. This is in contrast to the public PyPI index which does not
    # allow non-manylinux-compliant wheels to be uploaded at all since the wheels it serves can
    # be used on unknown target linux machines (for background on this, see:
    # https://www.python.org/dev/peps/pep-0513/#rationale). If that organization wishes to
    # consume both its own custom-built wheels as well as other manylinux-compliant wheels in
    # the same application, it needs to advertise that the target machine supports both
    # `linux_x86_64` wheels and `manylinux2014_x86_64` wheels (for example).
    if manylinux and platform.startswith("linux"):
        yield "--platform"
        yield platform.replace("linux", manylinux, 1)

    yield "--platform"
    yield platform

    yield "--implementation"
    yield platform_spec.impl

    yield "--python-version"
    yield platform_spec.version

    yield "--abi"
    yield platform_spec.abi


class EvaluationEnvironment(dict):
    class _Missing(str):
        pass

    class UndefinedName(Exception):
        pass

    def __init__(
        self,
        target_description,  # type: str
        *args,  # type: Any
        **kwargs  # type: Any
    ):
        # type: (...) -> None
        self._target_description = target_description
        super(EvaluationEnvironment, self).__init__(*args, **kwargs)

    def __missing__(self, key):
        # type: (Any) -> Any
        return self._Missing(
            "Failed to resolve for {target_description}. Resolve requires evaluation of unknown "
            "environment marker: {marker!r} does not exist in evaluation environment.".format(
                target_description=self._target_description, marker=key
            )
        )

    def raise_if_missing(self, value):
        # type: (Any) -> None
        if isinstance(value, self._Missing):
            raise self.UndefinedName(value)

    def default(self):
        # type: () -> EvaluationEnvironment
        return EvaluationEnvironment(self._target_description, self.copy())


class PatchContext(object):
    _PEX_PATCHED_MARKERS_FILE_ENV_VAR_NAME = "_PEX_PATCHED_MARKERS_FILE"

    @classmethod
    def load_evaluation_environment(cls):
        # type: () -> EvaluationEnvironment

        patched_markers_file = os.environ.pop(cls._PEX_PATCHED_MARKERS_FILE_ENV_VAR_NAME)
        with open(patched_markers_file) as fp:
            data = json.load(fp)
        return EvaluationEnvironment(data["target_description"], data["patched_environment"])

    @classmethod
    def dump_marker_environment(cls, target):
        # type: (Target) -> Mapping[str, str]

        target_description = target.render_description()
        patched_environment = target.marker_environment.as_dict()
        patches_file = os.path.join(safe_mkdtemp(), "markers.json")
        with open(patches_file, "w") as markers_fp:
            json.dump(
                {
                    "target_description": target_description,
                    "patched_environment": patched_environment,
                },
                markers_fp,
            )
        TRACER.log(
            "Patching environment markers for {target_description} with "
            "{patched_environment}".format(
                target_description=target_description, patched_environment=patched_environment
            ),
            V=3,
        )
        return {cls._PEX_PATCHED_MARKERS_FILE_ENV_VAR_NAME: patches_file}


def patch(target):
    # type: (Target) -> Optional[DownloadObserver]
    if not isinstance(target, (AbbreviatedPlatform, CompletePlatform)):
        return None

    patches = []
    patches_dir = safe_mkdtemp()

    patches.append(
        Patch.from_code_resource(
            __name__, "markers.py", **PatchContext.dump_marker_environment(target)
        )
    )

    compatible_tags = target.supported_tags
    if compatible_tags:
        patches.append(patch_tags(compatible_tags=compatible_tags, patches_dir=patches_dir))

    assert (
        target.marker_environment.python_full_version or target.marker_environment.python_version
    ), (
        "A complete platform should always have both `python_full_version` and `python_version` "
        "environment markers defined and an abbreviated platform should always have at least the"
        "`python_version` environment marker defined. Given: {target}".format(target=target)
    )
    requires_python = (
        "=={full_version}".format(full_version=target.marker_environment.python_full_version)
        if target.marker_environment.python_full_version
        else "=={version}.*".format(version=target.marker_environment.python_version)
    )
    patches.append(
        patch_requires_python(requires_python=[requires_python], patches_dir=patches_dir)
    )

    return DownloadObserver(analyzer=None, patch_set=PatchSet(patches=tuple(patches)))


def patch_tags(
    compatible_tags,  # type: CompatibilityTags
    patches_dir=None,  # type: Optional[str]
):
    # type: (...) -> Patch
    with open(os.path.join(patches_dir or safe_mkdtemp(), "tags.json"), "w") as tags_fp:
        json.dump(compatible_tags.to_string_list(), tags_fp)
    return Patch.from_code_resource(__name__, "tags.py", _PEX_PATCHED_TAGS_FILE=tags_fp.name)


def patch_requires_python(
    requires_python,  # type: Iterable[str]
    patches_dir=None,  # type: Optional[str]
):
    # type: (...) -> Patch
    """N.B.: This Path exports Python version information in the `requires_python` module.

    Exports:
    + PYTHON_FULL_VERSIONS: List[Tuple[int, int, int]]
        A sorted list of Python full versions compatible with the given `requires_python`.
    + PYTHON_VERSIONS: List[Tuple[int, int]]
        A sorted list of Python versions compatible with the given `requires_python`.
    """
    with TRACER.timed(
        "Calculating compatible python versions for {requires_python}".format(
            requires_python=requires_python
        )
    ):
        python_full_versions = list(iter_compatible_versions(requires_python))
        with open(
            os.path.join(patches_dir or safe_mkdtemp(), "python_full_versions.json"), "w"
        ) as fp:
            json.dump(python_full_versions, fp)
        return Patch.from_code_resource(
            __name__, "requires_python.py", _PEX_PYTHON_VERSIONS_FILE=fp.name
        )
