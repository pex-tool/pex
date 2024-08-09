# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.typing import TYPE_CHECKING
from pex.venv.bin_path import BinPath
from pex.venv.install_scope import InstallScope

if TYPE_CHECKING:
    from typing import Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class InstallerConfiguration(object):
    scope = attr.ib(default=InstallScope.ALL)  # type: InstallScope.Value
    bin_path = attr.ib(default=BinPath.FALSE)  # type: BinPath.Value
    force = attr.ib(default=False)  # type: bool
    collisions_ok = attr.ib(default=False)  # type: bool
    pip = attr.ib(default=False)  # type: bool
    copies = attr.ib(default=False)  # type: bool
    site_packages_copies = attr.ib(default=False)  # type: bool
    system_site_packages = attr.ib(default=False)  # type: bool
    compile = attr.ib(default=False)  # type: bool
    prompt = attr.ib(default=None)  # type: Optional[str]
    hermetic_scripts = attr.ib(default=False)  # type: bool
