# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os
import pkgutil
import re

from pex.common import safe_mkdtemp
from pex.pep_425 import CompatibilityTags
from pex.pip.download_observer import DownloadObserver, Patch
from pex.pip.log_analyzer import ErrorAnalyzer, ErrorMessage
from pex.platforms import Platform
from pex.targets import AbbreviatedPlatform, CompletePlatform, Target
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterator, Optional, Text, Tuple

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


_CODE = None  # type: Optional[Text]


def _code():
    # type: () -> Text
    global _CODE
    if _CODE is None:
        code = pkgutil.get_data(__name__, "foreign_platform_patches.py")
        assert code is not None, (
            "The sibling resource foreign_platform_patches.py of {} should always be present in a "
            "Pex distribution or source tree.".format(__name__)
        )
        _CODE = code.decode("utf-8")
    return _CODE


def patch(target):
    # type: (Target) -> Optional[DownloadObserver]
    if not isinstance(target, (AbbreviatedPlatform, CompletePlatform)):
        return None

    analyzer = _Issue10050Analyzer(target.platform)
    args = ()  # type: Tuple[str, ...]

    patches_dir = safe_mkdtemp()
    patched_environment = target.marker_environment.as_dict()
    with open(os.path.join(patches_dir, "markers.json"), "w") as markers_fp:
        json.dump(patched_environment, markers_fp)
    env = dict(_PEX_PATCHED_MARKERS_FILE=markers_fp.name)

    if isinstance(target, AbbreviatedPlatform):
        args = tuple(iter_platform_args(target.platform, target.manylinux))

    if isinstance(target, CompletePlatform):
        compatible_tags = target.supported_tags
        if compatible_tags:
            env.update(patch_tags(compatible_tags).env)

    TRACER.log(
        "Patching environment markers for {} with {}".format(target, patched_environment),
        V=3,
    )
    return DownloadObserver(analyzer=analyzer, patch=Patch(code=_code(), args=args, env=env))


def patch_tags(compatible_tags):
    # type: (CompatibilityTags) -> Patch
    patches_dir = safe_mkdtemp()
    with open(os.path.join(patches_dir, "tags.json"), "w") as tags_fp:
        json.dump(compatible_tags.to_string_list(), tags_fp)
    env = dict(_PEX_PATCHED_TAGS_FILE=tags_fp.name)
    return Patch(env=env, code=_code())
