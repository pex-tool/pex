# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.dist_metadata import Requirement
from pex.enum import Enum
from pex.pep_440 import Version
from pex.targets import LocalInterpreter, Target
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Optional, Tuple


class PipVersionValue(Enum.Value):
    def __init__(
        self,
        version,  # type: str
        name=None,  # type: Optional[str]
        requirement=None,  # type: Optional[str]
        setuptools_version=None,  # type: Optional[str]
        wheel_version=None,  # type: Optional[str]
        requires_python=None,  # type: Optional[str]
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

    @property
    def requirements(self):
        # type: () -> Iterable[str]
        return self.requirement, self.setuptools_requirement, self.wheel_requirement

    def requires_python_applies(self, target):
        # type: (Target) -> bool
        if not self.requires_python:
            return True

        return LocalInterpreter.create(target.get_interpreter()).requires_python_applies(
            requires_python=self.requires_python,
            source=Requirement.parse(self.requirement),
        )


class LatestPipVersion(object):
    def __get__(self, obj, objtype=None):
        if not hasattr(self, "_latest"):
            self._latest = max(PipVersionValue._iter_values(), key=lambda pv: pv.version)
        return self._latest


class PipVersion(Enum["PipVersionValue"]):
    @classmethod
    def values(cls):
        # type: () -> Tuple[PipVersionValue, ...]
        if cls._values is None:
            cls._values = tuple(PipVersionValue._iter_values())
        return cls._values

    v20_3_4_patched = PipVersionValue(
        name="20.3.4-patched",
        version="20.3.4+patched",
        requirement=(
            "pip @ git+https://github.com/pantsbuild/pip@386a54f097ece66775d0c7f34fd29bb596c6b0be"
        ),
    )

    # TODO(John Sirois): Expose setuptools and wheel version flags - these don't affect
    #  Pex; so we should allow folks to experiment with upgrade easily:
    #  https://github.com/pantsbuild/pex/issues/1895

    v22_2_2 = PipVersionValue(
        version="22.2.2",
        setuptools_version="65.3.0",
        wheel_version="0.37.1",
        requires_python=">=3.7",
    )

    v22_3 = PipVersionValue(
        version="22.3",
        setuptools_version="65.5.0",
        wheel_version="0.37.1",
        requires_python=">=3.7",
    )

    v22_3_1 = PipVersionValue(
        version="22.3.1",
        setuptools_version="65.5.1",
        wheel_version="0.37.1",
        requires_python=">=3.7",
    )

    v23_0 = PipVersionValue(
        version="23.0",
        setuptools_version="67.2.0",
        wheel_version="0.38.4",
        requires_python=">=3.7",
    )

    v23_0_1 = PipVersionValue(
        version="23.0.1",
        setuptools_version="67.4.0",
        wheel_version="0.38.4",
        requires_python=">=3.7",
    )

    v23_1 = PipVersionValue(
        version="23.1",
        setuptools_version="67.6.1",
        wheel_version="0.40.0",
        requires_python=">=3.7",
    )

    v23_1_1 = PipVersionValue(
        version="23.1.1",
        setuptools_version="67.7.1",
        wheel_version="0.40.0",
        requires_python=">=3.7",
    )

    v23_1_2 = PipVersionValue(
        version="23.1.2",
        setuptools_version="67.7.2",
        wheel_version="0.40.0",
        requires_python=">=3.7",
    )

    VENDORED = v20_3_4_patched
    LATEST = LatestPipVersion()
