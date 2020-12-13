# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os

from pex import pex_warnings, variables
from pex.common import can_write_dir, open_zip, safe_mkdtemp
from pex.compatibility import PY2
from pex.compatibility import string as compatibility_string
from pex.inherit_path import InheritPath
from pex.orderedset import OrderedSet
from pex.typing import TYPE_CHECKING, cast
from pex.variables import ENV, Variables
from pex.venv_bin_path import BinPath
from pex.version import __version__ as pex_version

if TYPE_CHECKING:
    from pex.interpreter import PythonInterpreter

    from typing import Any, Dict, Mapping, Optional, Text, Union


# TODO(wickman) Split this into a PexInfoBuilder/PexInfo to ensure immutability.
# Issue #92.
class PexInfo(object):
    """PEX metadata.

    # Build metadata:
    build_properties: BuildProperties  # (key-value information about the build system)
    code_hash: str                     # sha1 hash of all names/code in the archive
    distributions: {dist_name: str}    # map from distribution name (i.e. path in
                                       # the internal cache) to its cache key (sha1)
    pex_hash: str                      # sha1 hash of all names/code and distributions in the pex
    requirements: list                 # list of requirements for this environment

    # Environment options
    pex_root: string                    # root of all pex-related files eg: ~/.pex
    entry_point: string                 # entry point into this pex
    script: string                      # script to execute in this pex environment
                                        # at most one of script/entry_point can be specified
    zip_safe: bool, default True        # is this pex zip safe?
    unzip: bool, default False          # should this pex be unzipped and re-executed from there?
    inherit_path: false/fallback/prefer # should this pex inherit site-packages + user site-packages
                                        # + PYTHONPATH?
    ignore_errors: True, default False  # should we ignore inability to resolve dependencies?
    always_write_cache: False           # should we always write the internal cache to disk first?
                                        # this is useful if you have very large dependencies that
                                        # do not fit in RAM constrained environments

    .. versionchanged:: 0.8
      Removed the ``repositories`` and ``indices`` information, as they were never
      implemented.
    """

    PATH = "PEX-INFO"
    INSTALL_CACHE = "installed_wheels"

    @classmethod
    def make_build_properties(cls, interpreter=None):
        # This lazy import is currently needed for performance reasons. At PEX runtime PexInfo is
        # read in the bootstrap to see if the PEX should run in `--unzip` mode. If so, it must
        # re-exec itself to run against its unzipped contents. Since `make_build_properties` is only
        # used at PEX buildtime and the transitive imports of PythonInterpreter are large and slow,
        # we avoid this import cost for runtime-only use.
        #
        # See: https://github.com/pantsbuild/pex/issues/1054
        from pex.interpreter import PythonInterpreter

        pi = interpreter or PythonInterpreter.get()
        plat = pi.platform
        platform_name = plat.platform
        return {
            "pex_version": pex_version,
            "class": pi.identity.interpreter,
            "version": pi.identity.version,
            "platform": platform_name,
        }

    @classmethod
    def default(cls, interpreter=None):
        # type: (Optional[PythonInterpreter]) -> PexInfo
        pex_info = {
            "requirements": [],
            "distributions": {},
            "build_properties": cls.make_build_properties(interpreter),
        }
        return cls(info=pex_info)

    @classmethod
    def from_pex(cls, pex):
        # type: (str) -> PexInfo
        if os.path.isfile(pex):
            with open_zip(pex) as zf:
                pex_info = zf.read(cls.PATH)
        else:
            with open(os.path.join(pex, cls.PATH)) as fp:
                pex_info = fp.read()
        return cls.from_json(pex_info)

    @classmethod
    def from_json(cls, content):
        # type: (Union[bytes, Text]) -> PexInfo
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        return cls(info=json.loads(content))

    @classmethod
    def from_env(cls, env=ENV):
        # type: (Variables) -> PexInfo
        pex_force_local = Variables.PEX_FORCE_LOCAL.strip_default(env)
        zip_safe = None if pex_force_local is None else not pex_force_local

        pex_inherit_path = Variables.PEX_INHERIT_PATH.strip_default(env)
        inherit_path = None if pex_inherit_path is None else pex_inherit_path.value

        pex_info = {
            "pex_root": Variables.PEX_ROOT.strip_default(env),
            "entry_point": env.PEX_MODULE,
            "script": env.PEX_SCRIPT,
            "zip_safe": zip_safe,
            "unzip": Variables.PEX_UNZIP.strip_default(env),
            "venv": Variables.PEX_VENV.strip_default(env),
            "inherit_path": inherit_path,
            "ignore_errors": Variables.PEX_IGNORE_ERRORS.strip_default(env),
            "always_write_cache": Variables.PEX_ALWAYS_CACHE.strip_default(env),
        }
        # Filter out empty entries not explicitly set in the environment.
        return cls(info=dict((k, v) for (k, v) in pex_info.items() if v is not None))

    @classmethod
    def _parse_requirement_tuple(cls, requirement_tuple):
        if isinstance(requirement_tuple, (tuple, list)):
            if len(requirement_tuple) != 3:
                raise ValueError("Malformed PEX requirement: %r" % (requirement_tuple,))
            # pre 0.8.x requirement type:
            pex_warnings.warn(
                "Attempting to use deprecated PEX feature.  Please upgrade past PEX 0.8.x."
            )
            return requirement_tuple[0]
        elif isinstance(requirement_tuple, compatibility_string):
            return requirement_tuple
        raise ValueError("Malformed PEX requirement: %r" % (requirement_tuple,))

    def __init__(self, info=None):
        # type: (Optional[Mapping[str, Any]]) -> None
        """Construct a new PexInfo.

        This should not be used directly.
        """

        if info is not None and not isinstance(info, dict):
            raise ValueError(
                "PexInfo can only be seeded with a dict, got: " "%s of type %s" % (info, type(info))
            )
        self._pex_info = dict(info) if info else {}  # type Dict[str, Any]
        self._distributions = self._pex_info.get("distributions", {})
        # cast as set because pex info from json must store interpreter_constraints as a list
        self._interpreter_constraints = set(self._pex_info.get("interpreter_constraints", set()))
        requirements = self._pex_info.get("requirements", [])
        if not isinstance(requirements, (list, tuple)):
            raise ValueError("Expected requirements to be a list, got %s" % type(requirements))
        self._requirements = OrderedSet(self._parse_requirement_tuple(req) for req in requirements)

    def _get_safe(self, key):
        if key not in self._pex_info:
            return None
        value = self._pex_info[key]
        return value.encode("utf-8") if PY2 else value

    @property
    def build_properties(self):
        """Information about the system on which this PEX was generated.

        :returns: A dictionary containing metadata about the environment used to build this PEX.
        """
        return self._pex_info.get("build_properties", {})

    @build_properties.setter
    def build_properties(self, value):
        if not isinstance(value, dict):
            raise TypeError("build_properties must be a dictionary!")
        self._pex_info["build_properties"] = self.make_build_properties()
        self._pex_info["build_properties"].update(value)

    @property
    def zip_safe(self):
        """Whether or not this PEX should be treated as zip-safe.

        If set to false and the PEX is zipped, the contents of the PEX will be unpacked into a
        directory within the PEX_ROOT prior to execution.  This allows code and frameworks depending
        upon __file__ existing on disk to operate normally.

        By default zip_safe is True.  May be overridden at runtime by the $PEX_FORCE_LOCAL environment
        variable.
        """
        return self._pex_info.get("zip_safe", True)

    @zip_safe.setter
    def zip_safe(self, value):
        self._pex_info["zip_safe"] = bool(value)

    @property
    def unzip(self):
        """Whether or not PEX should be unzipped before it's executed.

        Unzipping a PEX is a operation that can be cached on the 1st run of a given PEX file which
        can result in lower startup latency in subsequent runs.
        """
        return self._pex_info.get("unzip", False)

    @unzip.setter
    def unzip(self, value):
        self._pex_info["unzip"] = bool(value)

    @property
    def unzip_dir(self):
        # type: () -> Optional[str]
        if not self.unzip:
            return None
        if self.pex_hash is None:
            raise ValueError("The unzip_dir was requested but no pex_hash was set.")
        return variables.unzip_dir(self.pex_root, self.pex_hash)

    @property
    def venv(self):
        # type: () -> bool
        """Whether or not PEX should be converted to a venv before it's executed.

        Creating a venv from a PEX is a operation that can be cached on the 1st run of a given PEX
        file which results in lower startup latency in subsequent runs.
        """
        return self._pex_info.get("venv", False)

    @venv.setter
    def venv(self, value):
        # type: (bool) -> None
        self._pex_info["venv"] = bool(value)

    @property
    def venv_bin_path(self):
        # type: () -> BinPath.Value
        """When run as a venv, whether or not to include `bin/` scripts on the PATH."""
        return BinPath.for_value(self._pex_info.get("venv_bin_path", BinPath.FALSE.value))

    @venv_bin_path.setter
    def venv_bin_path(self, value):
        # type: (BinPath.Value) -> None
        self._pex_info["venv_bin_path"] = str(value)

    @property
    def venv_dir(self):
        # type: () -> Optional[str]
        if not self.venv:
            return None
        if self.pex_hash is None:
            raise ValueError("The venv_dir was requested but no pex_hash was set.")
        return variables.venv_dir(self.pex_root, self.pex_hash, self.interpreter_constraints)

    @property
    def strip_pex_env(self):
        """Whether or not this PEX should strip `PEX_*` env vars before executing its entrypoint.

        You might want to set this to `False` if this PEX executes other PEXes or the Pex CLI itself
        and you want the executed PEX to be controlled via PEX environment variables.
        """
        return self._pex_info.get("strip_pex_env", True)

    @strip_pex_env.setter
    def strip_pex_env(self, value):
        self._pex_info["strip_pex_env"] = bool(value)

    @property
    def pex_path(self):
        # type: () -> Optional[str]
        """A colon separated list of other pex files to merge into the runtime environment.

        This pex info property is used to persist the PEX_PATH environment variable into the pex
        info metadata for reuse within a built pex.
        """
        return cast("Optional[str]", self._pex_info.get("pex_path"))

    @pex_path.setter
    def pex_path(self, value):
        # type: (str) -> None
        self._pex_info["pex_path"] = value

    @property
    def inherit_path(self):
        # type: () -> InheritPath.Value
        """Whether or not this PEX should be allowed to inherit system dependencies.

        By default, PEX environments are scrubbed of all system distributions prior to execution.
        This means that PEX files cannot rely upon preexisting system libraries.

        By default inherit_path is false. This may be overridden at runtime by the $PEX_INHERIT_PATH
        environment variable.
        """
        inherit_path = self._pex_info.get("inherit_path")
        return InheritPath.for_value(inherit_path) if inherit_path else InheritPath.FALSE

    @inherit_path.setter
    def inherit_path(self, value):
        # type: (InheritPath.Value) -> None
        self._pex_info["inherit_path"] = value.value

    @property
    def interpreter_constraints(self):
        """A list of constraints that determine the interpreter compatibility for this pex, using
        the Requirement-style format, e.g. ``'CPython>=3', or just '>=2.7,<3'`` for requirements
        agnostic to interpreter class.

        This property will be used at exec time when bootstrapping a pex to search PEX_PYTHON_PATH
        for a list of compatible interpreters.
        """
        return list(self._interpreter_constraints)

    def add_interpreter_constraint(self, value):
        self._interpreter_constraints.add(str(value))

    @property
    def ignore_errors(self):
        return self._pex_info.get("ignore_errors", False)

    @ignore_errors.setter
    def ignore_errors(self, value):
        self._pex_info["ignore_errors"] = bool(value)

    @property
    def emit_warnings(self):
        return self._pex_info.get("emit_warnings", True)

    @emit_warnings.setter
    def emit_warnings(self, value):
        self._pex_info["emit_warnings"] = bool(value)

    @property
    def code_hash(self):
        # type: () -> Optional[str]
        return self._pex_info.get("code_hash")

    @code_hash.setter
    def code_hash(self, value):
        # type: (str) -> None
        self._pex_info["code_hash"] = value

    @property
    def pex_hash(self):
        # type: () -> Optional[str]
        return self._pex_info.get("pex_hash")

    @pex_hash.setter
    def pex_hash(self, value):
        # type: (str) -> None
        self._pex_info["pex_hash"] = value

    @property
    def entry_point(self):
        return self._get_safe("entry_point")

    @entry_point.setter
    def entry_point(self, value):
        self._pex_info["entry_point"] = value

    @property
    def script(self):
        return self._get_safe("script")

    @script.setter
    def script(self, value):
        self._pex_info["script"] = value

    def add_requirement(self, requirement):
        self._requirements.add(str(requirement))

    @property
    def requirements(self):
        return self._requirements

    def add_distribution(self, location, sha):
        self._distributions[location] = sha

    @property
    def distributions(self):
        return self._distributions

    @property
    def always_write_cache(self):
        return self._pex_info.get("always_write_cache", False)

    @always_write_cache.setter
    def always_write_cache(self, value):
        self._pex_info["always_write_cache"] = bool(value)

    @property
    def raw_pex_root(self):
        # type: () -> str
        return cast(str, self._pex_info.get("pex_root", os.path.join("~", ".pex")))

    @property
    def pex_root(self):
        # type: () -> str
        pex_root = os.path.expanduser(self.raw_pex_root)
        if not can_write_dir(pex_root):
            tmp_root = safe_mkdtemp()
            pex_warnings.warn(
                "PEX_ROOT is configured as {pex_root} but that path is un-writeable, "
                "falling back to a temporary PEX_ROOT of {tmp_root} which will hurt "
                "performance.".format(pex_root=pex_root, tmp_root=tmp_root)
            )
            pex_root = self._pex_info["pex_root"] = tmp_root
        return pex_root

    @pex_root.setter
    def pex_root(self, value):
        # type: (Optional[str]) -> None
        if value is None:
            self._pex_info.pop("pex_root", None)
        else:
            self._pex_info["pex_root"] = value

    @property
    def internal_cache(self):
        return ".deps"

    @property
    def install_cache(self):
        return os.path.join(self.pex_root, self.INSTALL_CACHE)

    @property
    def zip_unsafe_cache(self):
        #: type: () -> str
        return os.path.join(self.pex_root, "code")

    def update(self, other):
        # type: (PexInfo) -> None
        if not isinstance(other, PexInfo):
            raise TypeError("Cannot merge a %r with PexInfo" % type(other))
        self._pex_info.update(other._pex_info)
        self._distributions.update(other.distributions)
        self._interpreter_constraints.update(other.interpreter_constraints)
        self._requirements.update(other.requirements)

    def as_json_dict(self):
        # type: () -> Dict[str, Any]
        data = self._pex_info.copy()
        data["inherit_path"] = self.inherit_path.value
        data["requirements"] = list(self._requirements)
        data["interpreter_constraints"] = list(self._interpreter_constraints)
        data["distributions"] = self._distributions.copy()
        return data

    def dump(self):
        # type: (...) -> str
        data = self.as_json_dict()
        data["requirements"].sort()
        data["interpreter_constraints"].sort()
        return json.dumps(data, sort_keys=True)

    def copy(self):
        # type: () -> PexInfo
        return PexInfo(self.as_json_dict())

    @staticmethod
    def _merge_split(*paths):
        filtered_paths = filter(None, paths)
        return [p for p in ":".join(filtered_paths).split(":") if p]

    def merge_pex_path(self, pex_path):
        """Merges a new PEX_PATH definition into the existing one (if any).

        :param str pex_path: The PEX_PATH to merge.
        """
        if not pex_path:
            return
        self.pex_path = ":".join(self._merge_split(self.pex_path, pex_path))

    def __repr__(self):
        return "{}({!r})".format(type(self).__name__, self._pex_info)
