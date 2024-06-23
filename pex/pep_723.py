# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import re

from pex.dist_metadata import Requirement
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Tuple

    import attr  # vendor:skip
    import toml  # vendor:skip
else:
    from pex.third_party import attr, toml


@attr.s(frozen=True)
class ScriptMetadata(object):

    _UNSPECIFIED_SOURCE = "<unspecified source>"

    @classmethod
    def parse(
        cls,
        script,  # type: str
        source=_UNSPECIFIED_SOURCE,  # type: str
    ):
        # type: (...) -> ScriptMetadata

        # The spec this code follows was defined in PEP-723: https://peps.python.org/pep-0723/
        # and now lives here:
        # https://packaging.python.org/specifications/inline-script-metadata#inline-script-metadata
        matches = list(
            re.finditer(r"^# /// script$\s(?P<content>(^#(| .*)$\s)+)^# ///$", script, re.MULTILINE)
        )
        if not matches:
            return cls()
        if len(matches) > 1:
            raise ValueError(
                "Multiple `script` metadata blocks found and at most one is allowed. "
                "See: https://packaging.python.org/en/latest/specifications/"
                "inline-script-metadata/#inline-script-metadata"
            )
        content = "".join(
            line[2:] if line.startswith("# ") else line[1:]
            for line in matches[0].group("content").splitlines(True)
        )
        script_metadata = toml.loads(content)

        return cls(
            dependencies=tuple(
                Requirement.parse(req) for req in script_metadata.get("dependencies", ())
            ),
            requires_python=SpecifierSet(script_metadata.get("requires-python", "")),
            source=source,
        )

    dependencies = attr.ib(default=())  # type: Tuple[Requirement, ...]
    requires_python = attr.ib(default=SpecifierSet())  # type: SpecifierSet
    source = attr.ib(default=_UNSPECIFIED_SOURCE)  # type: str

    def __bool__(self):
        # type: () -> bool
        return bool(self.dependencies) or bool(self.requires_python)

    # N.B.: For Python 2.7.
    __nonzero__ = __bool__
