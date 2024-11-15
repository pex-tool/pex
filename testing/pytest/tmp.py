# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import errno
import hashlib
import os.path
import re
import warnings

import attr

from pex.common import safe_delete, safe_mkdir, safe_rmtree
from pex.enum import Enum
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Optional

_MAX_ATTEMPTS = 100


class RetentionPolicy(Enum["RetentionPolicy.Value"]):
    class Value(Enum.Value):
        pass

    ALL = Value("all")
    FAILED = Value("failed")
    NONE = Value("none")


RetentionPolicy.seal()


def _realpath(path):
    # type: (str) -> str
    return os.path.realpath(path)


@attr.s(frozen=True)
class Tempdir(object):
    path = attr.ib(converter=_realpath)  # type: str
    symlink = attr.ib(default=None)  # type: Optional[str]

    def join(self, *components):
        # type: (*str) -> str
        return os.path.join(self.path, *components)

    def safe_remove(self):
        # type: () -> None
        if self.symlink:
            safe_delete(self.symlink)
        safe_rmtree(self.path)

    def __str__(self):
        # type: () -> str
        return self.path


@attr.s(frozen=True)
class TempdirFactory(object):
    path = attr.ib(converter=_realpath)  # type: str
    retention_policy = attr.ib()  # type: RetentionPolicy.Value

    def getbasetemp(self):
        # type: () -> str
        return self.path

    def mktemp(
        self,
        name,  # type: str
        request=None,  # type: Optional[Any]
    ):
        # type: (...) -> Tempdir

        long_name = None  # type: Optional[str]
        name = "{name}-{node}".format(name=name, node=request.node.name) if request else name
        normalized_name = re.sub(r"\W", "_", name)
        if len(normalized_name) > 30:
            # The pytest implementation simply truncates at 30 which leads to collisions and this
            # causes issues when tmpdir teardown is active - 1 test with the same 30 character
            # prefix in its test name as another test can have its directories torn down out from
            # underneath it! Here we ~ensure unique tmpdir names while preserving a filename length
            # limit to play well with various file systems.
            long_name = normalized_name

            # This is yields a ~1 in a million (5 hex chars at 4 bits a piece -> 2^20) chance of
            # collision if the 1st 24 characters of the test name match.
            prefix = normalized_name[:24]
            fingerprint = hashlib.sha1(normalized_name.encode("utf-8")).hexdigest()[:5]
            normalized_name = "{prefix}-{hash}".format(prefix=prefix, hash=fingerprint)
        for index in range(_MAX_ATTEMPTS):
            tempdir_name = "{name}{index}".format(name=normalized_name, index=index)
            tempdir = os.path.join(self.path, tempdir_name)
            try:
                os.makedirs(tempdir)
                symlink = None  # type: Optional[str]
                if long_name:
                    symlink = os.path.join(self.path, long_name)
                    safe_delete(symlink)
                    os.symlink(tempdir_name, symlink)
                return Tempdir(tempdir, symlink=symlink)
            except OSError as e:
                if e.errno == errno.EEXIST:
                    continue
        raise OSError(
            "Could not create numbered dir with prefix {prefix} in {root} after {max} tries".format(
                prefix=normalized_name, root=self.path, max=_MAX_ATTEMPTS
            )
        )


def tmpdir_factory(
    basetemp,  # type: str
    retention_count,  # type: int
    retention_policy,  # type: RetentionPolicy.Value
):
    # type: (...) -> TempdirFactory

    safe_rmtree(basetemp)
    if retention_count > 1:
        warnings.warn(
            "Ignoring temp dir retention count of {count}: only temp dirs from the current run "
            "will be retained.".format(count=retention_count)
        )
    safe_mkdir(basetemp)
    return TempdirFactory(path=basetemp, retention_policy=retention_policy)
