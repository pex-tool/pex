# Expose a limited set of classes and functions so callers outside of
# the vcs package don't need to import deeper than `pip._internal.vcs`.
# (The test directory and imports protected by MYPY_CHECK_RUNNING may
# still need to import from a vcs sub-package.)
if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.vcs.versioncontrol import (  # noqa: F401
    RemoteNotFoundError, make_vcs_requirement_url, vcs,
)  # vendor:skip
else:
  from pex.third_party.pip._internal.vcs.versioncontrol import (  # noqa: F401
    RemoteNotFoundError, make_vcs_requirement_url, vcs,
)

# Import all vcs modules to register each VCS in the VcsSupport object.
if "__PEX_UNVENDORED__" in __import__("os").environ:
  import pip._internal.vcs.bazaar  # vendor:skip
else:
  import pex.third_party.pip._internal.vcs.bazaar, pex.third_party.pip as pip

if "__PEX_UNVENDORED__" in __import__("os").environ:
  import pip._internal.vcs.git  # vendor:skip
else:
  import pex.third_party.pip._internal.vcs.git, pex.third_party.pip as pip

if "__PEX_UNVENDORED__" in __import__("os").environ:
  import pip._internal.vcs.mercurial  # vendor:skip
else:
  import pex.third_party.pip._internal.vcs.mercurial, pex.third_party.pip as pip

if "__PEX_UNVENDORED__" in __import__("os").environ:
  import pip._internal.vcs.subversion  # vendor:skip
else:
  import pex.third_party.pip._internal.vcs.subversion, pex.third_party.pip as pip
  # noqa: F401
