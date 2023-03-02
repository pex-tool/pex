# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os
import re

from pex.common import safe_mkdtemp
from pex.interpreter_constraints import iter_compatible_versions
from pex.pep_425 import CompatibilityTags
from pex.pip.download_observer import DownloadObserver, Patch, PatchSet
from pex.pip.log_analyzer import ErrorAnalyzer, ErrorMessage
from pex.platforms import Platform
from pex.targets import AbbreviatedPlatform, CompletePlatform, Target
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Iterator, Optional

    import attr  # vendor:skip

    from pex.pip.log_analyzer import ErrorAnalysis
else:
    from pex.third_party import attr


def iter_platform_args(
    platform,  # type: Platform
    manylinux=None,  # type: Optional[str]
):
    # type: (...) -> Iterator[str]

    plat = platform.platform
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
    if manylinux and plat.startswith("linux"):
        yield "--platform"
        yield plat.replace("linux", manylinux, 1)

    yield "--platform"
    yield plat

    yield "--implementation"
    yield platform.impl

    yield "--python-version"
    yield platform.version

    yield "--abi"
    yield platform.abi


@attr.s(frozen=True)
class _Issue10050Analyzer(ErrorAnalyzer):
    # Part of the workaround for: https://github.com/pypa/pip/issues/10050

    _platform = attr.ib()  # type: Platform

    def analyze(self, line):
        # type: (str) -> ErrorAnalysis
        # N.B.: Pip --log output looks like:
        # 2021-06-20T19:06:00,981 pip._vendor.packaging.markers.UndefinedEnvironmentName: 'python_full_version' does not exist in evaluation environment.
        match = re.match(
            r"^[^ ]+ pip._vendor.packaging.markers.UndefinedEnvironmentName: "
            r"(?P<missing_marker>.*)\.$",
            line,
        )
        if match:
            return self.Complete(
                ErrorMessage(
                    "Failed to resolve for platform {}. Resolve requires evaluation of unknown "
                    "environment marker: {}.".format(self._platform, match.group("missing_marker"))
                )
            )
        return self.Continue()


def patch(target):
    # type: (Target) -> Optional[DownloadObserver]
    if not isinstance(target, (AbbreviatedPlatform, CompletePlatform)):
        return None

    analyzer = _Issue10050Analyzer(target.platform)

    patches = []
    patches_dir = safe_mkdtemp()

    patched_environment = target.marker_environment.as_dict()
    with open(os.path.join(patches_dir, "markers.json"), "w") as markers_fp:
        json.dump(patched_environment, markers_fp)
    patches.append(
        Patch.from_code_resource(__name__, "markers.py", _PEX_PATCHED_MARKERS_FILE=markers_fp.name)
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

    TRACER.log(
        "Patching environment markers for {} with {}".format(target, patched_environment),
        V=3,
    )
    return DownloadObserver(analyzer=analyzer, patch_set=PatchSet(patches=tuple(patches)))


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
