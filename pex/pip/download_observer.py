# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
import pkgutil

from pex import third_party
from pex.common import safe_mkdtemp
from pex.pip.log_analyzer import LogAnalyzer
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict, Mapping, Optional, Text, Tuple

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Patch(object):
    @classmethod
    def from_code_resource(
        cls,
        package,  # type: str
        resource,  # type: str
        **env  # type: str
    ):
        # type: (...) -> Patch
        module, ext = os.path.splitext(resource)
        if ext != ".py":
            raise ValueError(
                "Code resources must be `.py` files, asked to load: {resource}".format(
                    resource=resource
                )
            )
        code = pkgutil.get_data(package, resource)
        assert code is not None, (
            "The resource {resource} relative to {package} should always be present in a "
            "Pex distribution or source tree.".format(resource=resource, package=package)
        )
        return cls(module=module, code=code.decode("utf-8"), env=env)

    module = attr.ib()  # type: str
    code = attr.ib()  # type: Text
    env = attr.ib(factory=dict)  # type: Mapping[str, str]


@attr.s(frozen=True)
class PatchSet(object):
    @classmethod
    def create(cls, *patches):
        # type: (*Patch) -> PatchSet
        return cls(patches=patches)

    patches = attr.ib(default=())  # type: Tuple[Patch, ...]

    @property
    def env(self):
        # type: () -> Dict[str, str]
        env = {}  # type: Dict[str, str]
        for patch in self.patches:
            env.update(patch.env)
        return env

    def emit_patches(self, package):
        # type: (str) -> Tuple[str, ...]

        if not self.patches:
            return ()

        if not package or "." in package:
            raise ValueError(
                "The `package` argument must be a non-empty, non-nested package name. "
                "Given: {package!r}".format(package=package)
            )

        import_paths = list(third_party.expose(["pex"]))
        patches_dir = safe_mkdtemp()
        import_paths.append(patches_dir)
        patches_package = os.path.join(patches_dir, package)
        os.mkdir(patches_package)

        for patch in self.patches:
            python_file = "{module}.py".format(module=patch.module)
            with open(os.path.join(patches_package, python_file), "wb") as code_fp:
                code_fp.write(patch.code.encode("utf-8"))

        with open(os.path.join(patches_package, "__init__.py"), "w") as fp:
            print("from __future__ import absolute_import", file=fp)
            for patch in self.patches:
                print("from . import {module}".format(module=patch.module), file=fp)
                print("{module}.patch()".format(module=patch.module), file=fp)

        return tuple(import_paths)

    def add(self, patch_set):
        # type: (PatchSet) -> PatchSet
        return PatchSet(self.patches + patch_set.patches)

    def __add__(self, other):
        # type: (Any) -> PatchSet
        if type(other) is not type(self):
            return NotImplemented
        return self.add(other)

    def __bool__(self):
        # type: () -> bool
        return bool(self.patches)

    # N.B.: For Python 2.7.
    __nonzero__ = __bool__


@attr.s(frozen=True)
class DownloadObserver(object):
    analyzer = attr.ib()  # type: Optional[LogAnalyzer]
    patch_set = attr.ib()  # type: PatchSet
