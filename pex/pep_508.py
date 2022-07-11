# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.platforms import Platform
from pex.third_party.packaging import markers
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class MarkerEnvironment(object):
    """A PEP-508 marker environment.

    See: https://www.python.org/dev/peps/pep-0508/#environment-markers
    """

    @classmethod
    def default(cls):
        # type: () -> MarkerEnvironment
        """The marker environment for the current interpreter."""
        return cls(**markers.default_environment())

    @classmethod
    def from_platform(cls, platform):
        # type: (Platform) -> MarkerEnvironment
        """Populate a partial marker environment given what we know from platform information.

        Since Pex support is (currently) restricted to:
        + interpreters: CPython and PyPy
        + os: Linux and Mac

        We can fill in most of the environment markers used in these environments in practice in the
        wild. For those we can't, we leave the markers unset (`None`).
        """

        major_version = platform.version_info[0]

        implementation_name = None
        implementation_version = None

        if major_version == 2:
            # Python 2 does not expose the `sys.implementation` object which these values are
            # derived from; so we default them as per the PEP-508 defaulting spec ("0" for versions
            # and the empty string for everything else).
            implementation_name = ""
            implementation_version = "0"
        elif platform.impl == "cp":
            implementation_name = "cpython"
        elif platform.impl == "pp":
            implementation_name = "pypy"

        os_name = None
        platform_machine = None
        platform_system = None
        sys_platform = None

        if "linux" in platform.platform:
            os_name = "posix"
            if platform.platform.startswith(
                ("linux_", "manylinux1_", "manylinux2010_", "manylinux2014_")
            ):
                # E.G.:
                # + linux_x86_64
                # + manylinux{1,2010,2014}_x86_64
                # For the manylinux* See:
                # + manylinux1: https://www.python.org/dev/peps/pep-0513/
                # + manylinux2010: https://www.python.org/dev/peps/pep-0571/
                # + manylinux2014: https://www.python.org/dev/peps/pep-0599/
                platform_machine = platform.platform.split("_", 1)[-1]
            else:
                # E.G.: manylinux_<glibc major>_<glibc_minor>_x86_64
                # See: https://www.python.org/dev/peps/pep-0600/
                platform_machine = platform.platform.split("_", 3)[-1]
            platform_system = "Linux"
            sys_platform = "linux2" if major_version == 2 else "linux"
        elif "mac" in platform.platform:
            os_name = "posix"
            # E.G:
            # + macosx_10_15_x86_64
            # + macosx_11_0_arm64
            platform_machine = platform.platform.split("_", 3)[-1]
            platform_system = "Darwin"
            sys_platform = "darwin"

        platform_python_implementation = None

        if platform.impl == "cp":
            platform_python_implementation = "CPython"
        elif platform.impl == "pp":
            platform_python_implementation = "PyPy"

        python_version = ".".join(map(str, platform.version_info[:2]))

        python_full_version = None
        if len(platform.version_info) == 3:
            python_full_version = ".".join(map(str, platform.version_info))

        return cls(
            implementation_name=implementation_name,
            implementation_version=implementation_version,
            os_name=os_name,
            platform_machine=platform_machine,
            platform_python_implementation=platform_python_implementation,
            platform_release=None,
            platform_system=platform_system,
            platform_version=None,
            python_full_version=python_full_version,
            python_version=python_version,
            sys_platform=sys_platform,
        )

    implementation_name = attr.ib(default=None)  # type: Optional[str]
    implementation_version = attr.ib(default=None)  # type: Optional[str]
    os_name = attr.ib(default=None)  # type: Optional[str]
    platform_machine = attr.ib(default=None)  # type: Optional[str]
    platform_python_implementation = attr.ib(default=None)  # type: Optional[str]
    platform_release = attr.ib(default=None)  # type: Optional[str]
    platform_system = attr.ib(default=None)  # type: Optional[str]
    platform_version = attr.ib(default=None)  # type: Optional[str]
    python_full_version = attr.ib(default=None)  # type: Optional[str]
    python_version = attr.ib(default=None)  # type: Optional[str]
    sys_platform = attr.ib(default=None)  # type: Optional[str]

    def as_dict(self):
        # type: () -> Dict[str, str]
        """Render this marker environment as a dictionary.

        For any environment markers that are unset (`None`), the entry is omitted from the
        environment so that any attempt to evaluate a marker needing the entry's value will fail.
        """
        return attr.asdict(self, filter=lambda _attribute, value: value is not None)
