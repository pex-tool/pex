# Copyright 2017 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from textwrap import dedent

from pex.pep_425 import CompatibilityTags
from pex.third_party.packaging import tags
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Tuple, Union

    import attr  # vendor:skip

    VersionInfo = Union[Tuple[int], Tuple[int, int], Tuple[int, int, int]]
else:
    from pex.third_party import attr


def _normalize_platform(platform):
    # type: (str) -> str
    return platform.lower().replace("-", "_").replace(".", "_")


@attr.s(frozen=True)
class PlatformSpec(object):
    """Represents a target Python platform, implementation, version and ABI."""

    class InvalidSpecError(Exception):
        """Indicates an invalid platform string."""

        @classmethod
        def create(cls, platform, cause=None):
            message_parts = ["Not a valid platform specifier: {platform}".format(platform=platform)]
            if cause:
                message_parts.append(cause)
            message_parts.append(
                dedent(
                    """\
                    Platform strings must be in one of two forms:
                    1. Canonical: <platform>-<python impl abbr>-<python version>-<abi>
                    2. Abbreviated: <platform>-<python impl abbr>-<python version>-<abbr abi>

                    These fields stem from wheel name conventions as outlined in
                    https://www.python.org/dev/peps/pep-0427#file-name-convention and influenced by
                    https://www.python.org/dev/peps/pep-0425 except as otherwise noted below.

                    Given a canonical platform string for CPython 3.7.5 running on 64 bit Linux of:
                      linux-x86_64-cp-37-cp37m

                    Where the fields above are:
                    + <platform>: linux-x86_64
                    + <python impl abbr>: cp (e.g.: cp for CPython or pp for PyPY)
                    + <python version>: 37 (a 2 or more digit major/minor version or a component 
                                            dotted version)
                    + <abi>: cp37m

                    The abbreviated platform string is:
                      linux-x86_64-cp-37-m

                    Some other canonical platform string examples:
                    + OSX CPython: macosx-10.13-x86_64-cp-36-cp36m
                    + Linux PyPy: linux-x86_64-pp-273-pypy_73.

                    Unlike in the conventions set forth in PEP-425 and PEP-427, the python version 
                    field can take on a component dotted value. So, for the example of CPython 3.7.5
                    running on 64 bit Linux, you could also specify:
                    + canonical: linux-x86_64-cp-3.7.5-cp37m
                    + abbreviated: linux-x86_64-cp-3.7.5-m

                    You may be forced to specify this form when resolves encounter environment
                    markers that use `python_full_version`. See the `--complete-platform` help as
                    well as:
                    + https://docs.pex-tool.org/buildingpex.html#complete-platform
                    + https://www.python.org/dev/peps/pep-0508/#environment-markers
                    """
                )
            )
            return cls("\n\n".join(message_parts))

    SEP = "-"

    @classmethod
    def parse(cls, platform_spec):
        # type: (str) -> PlatformSpec
        platform_components = platform_spec.rsplit(cls.SEP, 3)
        try:
            plat, impl, version, abi = platform_components
        except ValueError:
            raise cls.InvalidSpecError.create(
                platform_spec,
                cause="There are missing platform fields. Expected 4 but given {count}.".format(
                    count=len(platform_components)
                ),
            )

        version_components = version.split(".")
        if len(version_components) == 1:
            component = version_components[0]
            if len(component) < 2:
                raise cls.InvalidSpecError.create(
                    platform_spec,
                    cause=(
                        "The version field must either be a 2 or more digit digit major/minor "
                        "version or else a component dotted version. "
                        "Given: {version!r}".format(version=version)
                    ),
                )

            # Here version is py_version_nodot (e.g.: "37" or "310") as outlined in
            # https://www.python.org/dev/peps/pep-0425/#python-tag
            version_components = [component[0], component[1:]]

        try:
            version_info = cast("VersionInfo", tuple(map(int, version_components)))
        except ValueError:
            raise cls.InvalidSpecError.create(
                platform_spec,
                cause="The version specified had non-integer components. Given: {version!r}".format(
                    version=version
                ),
            )

        return cls(platform=plat, impl=impl, version=version, version_info=version_info, abi=abi)

    @classmethod
    def from_tag(cls, tag):
        # type: (tags.Tag) -> PlatformSpec
        """Creates a platform corresponding to wheel compatibility tags.

        See: https://www.python.org/dev/peps/pep-0425/#details
        """
        impl, version = tag.interpreter[:2], tag.interpreter[2:]

        major, minor = version[0], version[1:]
        components = [major] if not minor else [major, minor]
        try:
            version_info = cast("VersionInfo", tuple(map(int, components)))
        except ValueError:
            raise cls.InvalidSpecError.create(
                tag,
                cause=(
                    "The tag's interpreter field has an non-integer version suffix following the "
                    "impl {impl!r} of {version!r}.".format(impl=impl, version=version)
                ),
            )

        return cls(
            platform=tag.platform,
            impl=impl,
            version=version,
            version_info=version_info,
            abi=tag.abi,
        )

    platform = attr.ib(converter=_normalize_platform)  # type: str
    impl = attr.ib()  # type: str
    version = attr.ib()  # type: str
    version_info = attr.ib()  # type: VersionInfo
    abi = attr.ib()  # type: str

    @platform.validator
    @impl.validator
    @version.validator
    @abi.validator
    def _non_blank(self, attribute, value):
        if not value:
            raise self.InvalidSpecError.create(
                platform=str(self),
                cause=(
                    "Platform specifiers cannot have blank fields. Given a blank {field}.".format(
                        field=attribute.name
                    )
                ),
            )

    def __attrs_post_init__(self):
        # type: () -> None
        if self.impl == "cp" and not self.abi.startswith(self.interpreter):
            # N.B. This permits CPython users to pass in simpler extended platform
            # strings like `linux-x86_64-cp-27-mu` vs e.g. `linux-x86_64-cp-27-cp27mu`.
            object.__setattr__(self, "abi", self.interpreter + self.abi)

    @property
    def interpreter(self):
        # type: () -> str
        return "{impl}{version}".format(
            impl=self.impl, version="".join(map(str, self.version_info[:2]))
        )

    @property
    def tag(self):
        # type: () -> tags.Tag
        return tags.Tag(interpreter=self.interpreter, abi=self.abi, platform=self.platform)

    def __str__(self):
        # type: () -> str
        return cast(str, self.SEP.join((self.platform, self.impl, self.version, self.abi)))


@attr.s(frozen=True)
class Platform(PlatformSpec):
    @classmethod
    def from_tags(cls, compatibility_tags):
        # type: (CompatibilityTags) -> Platform
        platform_spec = PlatformSpec.from_tag(compatibility_tags[0])
        return Platform(
            platform=platform_spec.platform,
            impl=platform_spec.impl,
            version=platform_spec.version,
            version_info=platform_spec.version_info,
            abi=platform_spec.abi,
            supported_tags=compatibility_tags,
        )

    supported_tags = attr.ib(eq=False)  # type: CompatibilityTags
