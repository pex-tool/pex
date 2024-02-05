# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import sys
from textwrap import dedent

from pex.dist_metadata import Requirement
from pex.enum import Enum
from pex.pep_440 import Version
from pex.targets import LocalInterpreter, Target
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Iterable, Optional, Tuple, Union


class PipVersionValue(Enum.Value):
    @classmethod
    def overridden(cls):
        # type: () -> Optional[PipVersionValue]
        if not hasattr(cls, "_overridden"):
            setattr(cls, "_overridden", None)

            # We make an affordance for CI with a purposefully undocumented PEX env var.
            overriden_value = os.environ.get("_PEX_PIP_VERSION")
            if overriden_value:
                for version in cls._iter_values():
                    if version.value == overriden_value:
                        setattr(cls, "_overridden", version)
                        break
        return cast("Optional[PipVersionValue]", getattr(cls, "_overridden"))

    def __init__(
        self,
        version,  # type: str
        name=None,  # type: Optional[str]
        requirement=None,  # type: Optional[str]
        setuptools_version=None,  # type: Optional[str]
        wheel_version=None,  # type: Optional[str]
        requires_python=None,  # type: Optional[str]
        hidden=False,  # type: bool
    ):
        # type: (...) -> None
        super(PipVersionValue, self).__init__(name or version)

        def to_requirement(
            project_name,  # type: str
            project_version=None,  # type: Optional[str]
        ):
            # type: (...) -> str
            return (
                "{project_name}=={project_version}".format(
                    project_name=project_name, project_version=project_version
                )
                if project_version
                else project_name
            )

        self.version = Version(version)
        self.requirement = requirement or to_requirement("pip", version)
        self.setuptools_requirement = to_requirement("setuptools", setuptools_version)
        self.wheel_requirement = to_requirement("wheel", wheel_version)
        self.requires_python = SpecifierSet(requires_python) if requires_python else None
        self.hidden = hidden

    @property
    def requirements(self):
        # type: () -> Iterable[str]
        return self.requirement, self.setuptools_requirement, self.wheel_requirement

    def requires_python_applies(self, target=None):
        # type: (Optional[Union[Version,Target]]) -> bool
        if not self.requires_python:
            return True

        if isinstance(target, Version):
            return str(target) in self.requires_python

        return LocalInterpreter.create(
            interpreter=target.get_interpreter() if target else None
        ).requires_python_applies(
            requires_python=self.requires_python,
            source=Requirement.parse(self.requirement),
        )


class LatestPipVersion(object):
    def __get__(self, obj, objtype=None):
        if not hasattr(self, "_latest"):
            self._latest = max(
                (version for version in PipVersionValue._iter_values() if not version.hidden),
                key=lambda pv: pv.version,
            )
        return self._latest


class DefaultPipVersion(object):
    def __init__(self, preferred):
        # type: (Iterable[PipVersionValue]) -> None
        self._preferred = preferred

    def __get__(self, obj, objtype=None):
        if not hasattr(self, "_default"):
            self._default = None
            current_version = Version(".".join(map(str, sys.version_info[:3])))
            preferred_versions = (
                [PipVersionValue.overridden()] if PipVersionValue.overridden() else self._preferred
            )
            for preferred_version in preferred_versions:
                if preferred_version.requires_python_applies(current_version):
                    self._default = preferred_version
                    break
            if self._default is None:
                applicable_versions = tuple(
                    version
                    for version in PipVersionValue._iter_values()
                    if not version.hidden and version.requires_python_applies(current_version)
                )
                if not applicable_versions:
                    raise ValueError(
                        dedent(
                            """\
                            No version of Pip supported by Pex works with {python}.
                            The supported Pip versions are:
                            {versions}
                            """
                        ).format(
                            python=sys.executable,
                            versions=", ".join(
                                version.value
                                for version in PipVersionValue._iter_values()
                                if not version.hidden
                            ),
                        )
                    )
                self._default = max(applicable_versions, key=lambda pv: pv.version)
        return self._default


class PipVersion(Enum["PipVersionValue"]):
    @classmethod
    def values(cls):
        # type: () -> Tuple[PipVersionValue, ...]
        if cls._values is None:
            cls._values = tuple(
                version
                for version in PipVersionValue._iter_values()
                if version is PipVersionValue.overridden() or not version.hidden
            )
        return cls._values

    v20_3_4_patched = PipVersionValue(
        name="20.3.4-patched",
        version="20.3.4+patched",
        requirement=(
            "pip @ git+https://github.com/pantsbuild/pip@386a54f097ece66775d0c7f34fd29bb596c6b0be"
        ),
        wheel_version="0.37.1",
        requires_python="<3.12",
    )

    # TODO(John Sirois): Expose setuptools and wheel version flags - these don't affect
    #  Pex; so we should allow folks to experiment with upgrade easily:
    #  https://github.com/pantsbuild/pex/issues/1895

    v22_2_2 = PipVersionValue(
        version="22.2.2",
        setuptools_version="65.3.0",
        wheel_version="0.37.1",
        requires_python=">=3.7,<3.12",
    )

    v22_3 = PipVersionValue(
        version="22.3",
        setuptools_version="65.5.0",
        wheel_version="0.37.1",
        requires_python=">=3.7,<3.12",
    )

    v22_3_1 = PipVersionValue(
        version="22.3.1",
        setuptools_version="65.5.1",
        wheel_version="0.37.1",
        requires_python=">=3.7,<3.12",
    )

    v23_0 = PipVersionValue(
        version="23.0",
        setuptools_version="67.2.0",
        wheel_version="0.38.4",
        requires_python=">=3.7,<3.12",
    )

    v23_0_1 = PipVersionValue(
        version="23.0.1",
        setuptools_version="67.4.0",
        wheel_version="0.38.4",
        requires_python=">=3.7,<3.12",
    )

    v23_1 = PipVersionValue(
        version="23.1",
        setuptools_version="67.6.1",
        wheel_version="0.40.0",
        requires_python=">=3.7,<3.12",
    )

    v23_1_1 = PipVersionValue(
        version="23.1.1",
        setuptools_version="67.7.1",
        wheel_version="0.40.0",
        requires_python=">=3.7,<3.12",
    )

    v23_1_2 = PipVersionValue(
        version="23.1.2",
        setuptools_version="67.7.2",
        wheel_version="0.40.0",
        requires_python=">=3.7,<3.12",
    )

    v23_2 = PipVersionValue(
        version="23.2",
        setuptools_version="68.0.0",
        wheel_version="0.40.0",
        requires_python=">=3.7,<3.13",
    )

    v23_3_1 = PipVersionValue(
        version="23.3.1",
        # N.B.: The setuptools 68.2.2 release was available on 10/21/2023 (the Pip 23.3.1 release
        # date) but 68.0.0 is the last setuptools version to support 3.7.
        setuptools_version="68.0.0",
        wheel_version="0.41.2",
        requires_python=">=3.7,<3.13",
    )

    v23_3_2 = PipVersionValue(
        version="23.3.2",
        # N.B.: The setuptools 69.0.2 release was available on 12/17/2023 (the Pip 23.3.2 release
        # date) but 68.0.0 is the last setuptools version to support 3.7.
        setuptools_version="68.0.0",
        wheel_version="0.42.0",
        requires_python=">=3.7,<3.13",
    )

    v24_0 = PipVersionValue(
        version="24.0",
        # N.B.: The setuptools 69.0.3 release was available on 2/03/2024 (the Pip 24.0 release
        # date) but 68.0.0 is the last setuptools version to support 3.7.
        setuptools_version="68.0.0",
        wheel_version="0.42.0",
        requires_python=">=3.7,<3.13",
    )

    # This is https://github.com/pypa/pip/pull/12462 which is approved but not yet merged or
    # released. It allows testing Python 3.13 pre-releases but should not be used by the public; so
    # we keep it hidden.
    v24_0_dev0_patched = PipVersionValue(
        name="24.0.dev0-patched",
        version="24.0.dev0+patched",
        requirement=(
            "pip @ git+https://github.com/jsirois/pip@0257c9422f7bb99a6f319b54f808a5c50339be6c"
        ),
        setuptools_version="69.0.3",
        wheel_version="0.42.0",
        requires_python=">=3.7",
        hidden=True,
    )

    VENDORED = v20_3_4_patched
    LATEST = LatestPipVersion()
    DEFAULT = DefaultPipVersion(preferred=(VENDORED, v23_2))
