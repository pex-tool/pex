# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os

from pex.common import atomic_directory, open_zip, safe_copy, safe_mkdir, safe_open
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.variables import unzip_dir

if TYPE_CHECKING:
    import attr
    from typing import Iterable, Text, Tuple, Union
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Spread(object):
    zip_relpath = attr.ib()  # type: str
    unpack_relpath = attr.ib()  # type: str
    strip_zip_relpath = attr.ib(default=True)  # type: bool


@attr.s(frozen=True)
class SpreadInfo(object):
    PATH = "PEX-SPREAD-INFO"

    @classmethod
    def from_pex(cls, pex):
        # type: (str) -> SpreadInfo
        with open(os.path.join(pex, cls.PATH)) as fp:
            return cls.from_json(fp.read())

    @classmethod
    def from_json(cls, content):
        # type: (Union[bytes, Text]) -> SpreadInfo
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        data = json.loads(content)
        return cls.create(
            sources=data["sources"],
            spreads=(
                Spread(
                    zip_relpath=s["zip_relpath"],
                    strip_zip_relpath=s["strip_zip_relpath"],
                    unpack_relpath=s["unpack_relpath"],
                )
                for s in data["spreads"]
            ),
        )

    @classmethod
    def create(
        cls,
        sources,  # type: Iterable[str]
        spreads,  # type: Iterable[Spread]
    ):
        # type: (...) -> SpreadInfo
        return cls(sources=tuple(sources), spreads=tuple(spreads))

    sources = attr.ib()  # type: Tuple[str, ...]
    spreads = attr.ib()  # type: Tuple[Spread, ...]

    def dump(self, dest_dir):
        # type: (str) -> str
        data = {
            "sources": sorted(self.sources),
            "spreads": [
                {
                    "zip_relpath": s.zip_relpath,
                    "strip_zip_relpath": s.strip_zip_relpath,
                    "unpack_relpath": s.unpack_relpath,
                }
                for s in sorted(self.spreads)
            ],
        }
        dest = os.path.join(dest_dir, self.PATH)
        with safe_open(dest, "w") as fp:
            json.dump(data, fp, sort_keys=True)
        return dest


def spread(
    spread_pex,  # type: str
    pex_root,  # type: str
    pex_hash,  # type: str
):
    # type: (...) -> str
    """Installs a spread pex into the pex root as an unzipped PEX.

    Returns the path of the unzipped PEX.
    """
    spread_to = unzip_dir(pex_root=pex_root, pex_hash=pex_hash)
    with atomic_directory(spread_to, exclusive=True) as chroot:
        if not chroot.is_finalized:
            with TRACER.timed("Extracting {} to {}".format(spread_pex, spread_to)):
                spread_info = SpreadInfo.from_pex(spread_pex)

                for source in spread_info.sources:
                    dest = os.path.join(spread_to, source)
                    safe_mkdir(os.path.dirname(dest))
                    safe_copy(os.path.join(spread_pex, "src", source), dest)

                for s in spread_info.spreads:
                    spread_dest = os.path.join(pex_root, s.unpack_relpath)
                    with atomic_directory(
                        spread_dest,
                        source=s.zip_relpath if s.strip_zip_relpath else None,
                        exclusive=True,
                    ) as spread_chroot:
                        if not spread_chroot.is_finalized:
                            with open_zip(os.path.join(spread_pex, s.zip_relpath)) as zfp:
                                zfp.extractall(spread_chroot.work_dir)

                    symlink_dest = os.path.join(spread_to, s.zip_relpath)
                    safe_mkdir(os.path.dirname(symlink_dest))
                    os.symlink(
                        os.path.relpath(
                            spread_dest, os.path.join(spread_to, os.path.dirname(s.zip_relpath))
                        ),
                        symlink_dest,
                    )
    return spread_to
