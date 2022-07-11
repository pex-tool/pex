# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import ast
import os

from pex.common import is_python_script
from pex.dist_metadata import Distribution, EntryPoint
from pex.pep_376 import InstalledWheel
from pex.pep_503 import ProjectName
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Dict, Iterable, Optional, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class DistributionScript(object):
    @classmethod
    def find(
        cls,
        dist,  # type: Distribution
        name,  # type: str
    ):
        # type: (...) -> Optional[DistributionScript]
        script_path = InstalledWheel.load(dist.location).stashed_path("bin", name)
        return cls(dist=dist, path=script_path) if os.path.isfile(script_path) else None

    dist = attr.ib()  # type: Distribution
    path = attr.ib()  # type: str

    def read_contents(self):
        # type: () -> bytes
        with open(self.path, "rb") as fp:
            return fp.read()

    def python_script(self):
        # type: () -> Optional[ast.AST]
        if not is_python_script(self.path):
            return None

        try:
            return cast(
                ast.AST, compile(self.read_contents(), self.path, "exec", flags=0, dont_inherit=1)
            )
        except (SyntaxError, TypeError):
            return None


def get_script_from_distributions(
    name,  # type: str
    dists,  # type: Iterable[Distribution]
):
    # type: (...) -> Optional[DistributionScript]
    for dist in dists:
        distribution_script = DistributionScript.find(dist, name)
        if distribution_script:
            return distribution_script
    return None


@attr.s(frozen=True)
class DistributionEntryPoint(object):
    dist = attr.ib()  # type: Distribution
    entry_point = attr.ib()  # type: EntryPoint


def get_entry_point_from_console_script(
    script,  # type: str
    dists,  # type: Iterable[Distribution]
):
    # type: (...) -> Optional[DistributionEntryPoint]
    # Check all distributions for the console_script "script". De-dup by dist key to allow for a
    # duplicate console script IFF the distribution is platform-specific and this is a
    # multi-platform pex.
    def get_entrypoint(dist):
        # type: (Distribution) -> Optional[EntryPoint]
        return dist.get_entry_map().get("console_scripts", {}).get(script)

    entries = {}  # type: Dict[ProjectName, DistributionEntryPoint]
    for dist in dists:
        entry_point = get_entrypoint(dist)
        if entry_point is not None:
            entries[dist.metadata.project_name] = DistributionEntryPoint(dist, entry_point)

    if len(entries) > 1:
        raise RuntimeError(
            "Ambiguous script specification {script} matches multiple entry points:\n\t"
            "{entry_points}".format(
                script=script,
                entry_points="\n\t".join(
                    "{entry_point} from {dist}".format(
                        entry_point=dist_entry_point.entry_point, dist=dist_entry_point.dist
                    )
                    for dist_entry_point in entries.values()
                ),
            )
        )

    dist_entry_point = None
    if entries:
        dist_entry_point = next(iter(entries.values()))
    return dist_entry_point
