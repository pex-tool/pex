# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os
import zipfile

from pex import layout, pex_warnings, variables
from pex.cache import root as cache_root
from pex.common import can_write_dir, open_zip, safe_mkdtemp
from pex.compatibility import PY2
from pex.compatibility import string as compatibility_string
from pex.inherit_path import InheritPath
from pex.orderedset import OrderedSet
from pex.os import WINDOWS
from pex.typing import TYPE_CHECKING, cast
from pex.variables import ENV, Variables
from pex.venv.bin_path import BinPath
from pex.version import __version__ as pex_version

if TYPE_CHECKING:
    # MyPy run for 2.7 does not recognize the Collection type
    from typing import Collection  # type: ignore[attr-defined]
    from typing import Any, Dict, Iterable, Mapping, Optional, Text, Tuple, Union

    from pex.cache.dirs import VenvDir
    from pex.dist_metadata import Requirement

    # N.B.: These are expensive imports and PexInfo is used during PEX bootstrapping which we want
    # to be as fast as possible.
    from pex.interpreter import PythonInterpreter
    from pex.interpreter_constraints import InterpreterConstraints


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
    pex_root: string                    # root of all pex-related files eg: ~/.cache/pex
    entry_point: string                 # entry point into this pex
    script: string                      # script to execute in this pex environment
                                        # at most one of script/entry_point can be specified
    inherit_path: false/fallback/prefer # should this pex inherit site-packages + user site-packages
                                        # + PYTHONPATH?
    ignore_errors: True, default False  # should we ignore inability to resolve dependencies?

    .. versionchanged:: 0.8
      Removed the ``repositories`` and ``indices`` information, as they were never
      implemented.
    """

    PATH = layout.PEX_INFO_PATH

    @classmethod
    def make_build_properties(cls):
        return {
            "pex_version": pex_version,
        }

    @classmethod
    def default(cls):
        # type: () -> PexInfo
        return cls(info={"build_properties": cls.make_build_properties()})

    @classmethod
    def from_pex(cls, pex):
        # type: (str) -> PexInfo
        if zipfile.is_zipfile(pex):  # Zip App PEX
            with open_zip(pex) as zf:
                pex_info = zf.read(cls.PATH)
        elif os.path.isfile(pex):  # Venv PEX
            with open(os.path.join(os.path.dirname(pex), cls.PATH), "rb") as fp:
                pex_info = fp.read()
        else:  # Directory (Either loose or installed) PEX
            with open(os.path.join(pex, cls.PATH), "rb") as fp:
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
        pex_inherit_path = Variables.PEX_INHERIT_PATH.strip_default(env)
        inherit_path = None if pex_inherit_path is None else pex_inherit_path.value

        pex_info = {
            "pex_root": Variables.PEX_ROOT.strip_default(env),
            "entry_point": env.PEX_MODULE,
            "script": env.PEX_SCRIPT,
            "venv": Variables.PEX_VENV.strip_default(env),
            "inherit_path": inherit_path,
            "ignore_errors": Variables.PEX_IGNORE_ERRORS.strip_default(env),
            "max_install_jobs": Variables.PEX_MAX_INSTALL_JOBS.strip_default(env),
        }
        # Filter out empty entries not explicitly set in the environment.
        return cls(info={k: v for k, v in pex_info.items() if v is not None})

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
        self._pex_info = dict(info) if info else {}  # type: Dict[str, Any]
        self._distributions = self._pex_info.get("distributions", {})  # type: Dict[str, str]

        # N.B.: InterpreterConstraints is an expensive type to import; so we do so lazily since
        # PexInfo is used during PEX bootstrapping which we want to be fast.
        self._interpreter_constraints = None  # type: Optional[InterpreterConstraints]

        requirements = self._pex_info.get("requirements", [])
        if not isinstance(requirements, (list, tuple)):
            raise ValueError("Expected requirements to be a list, got %s" % type(requirements))
        self._requirements = OrderedSet(self._parse_requirement_tuple(req) for req in requirements)

        self._excluded = OrderedSet(self._pex_info.get("excluded", ()))  # type: OrderedSet[str]
        self._overridden = OrderedSet(self._pex_info.get("overridden", ()))  # type: OrderedSet[str]

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
    def inject_python_args(self):
        # type: () -> Tuple[str, ...]
        return tuple(self._pex_info.get("inject_python_args", ()))

    @inject_python_args.setter
    def inject_python_args(self, value):
        # type: (Iterable[str]) -> None
        self._pex_info["inject_python_args"] = tuple(value)

    @property
    def inject_env(self):
        # type: () -> Dict[str, str]
        return dict(self._pex_info.get("inject_env", {}))

    @inject_env.setter
    def inject_env(self, value):
        # type: (Mapping[str, str]) -> None
        self._pex_info["inject_env"] = dict(value)

    @property
    def inject_args(self):
        # type: () -> Tuple[str, ...]
        return tuple(self._pex_info.get("inject_args", ()))

    @inject_args.setter
    def inject_args(self, value):
        # type: (Iterable[str]) -> None
        self._pex_info["inject_args"] = tuple(value)

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
    def venv_copies(self):
        # type: () -> bool
        return self._pex_info.get("venv_copies", False)

    @venv_copies.setter
    def venv_copies(self, value):
        # type: (bool) -> None
        self._pex_info["venv_copies"] = value

    @property
    def venv_site_packages_copies(self):
        # type: () -> bool
        return self._pex_info.get("venv_site_packages_copies", False)

    @venv_site_packages_copies.setter
    def venv_site_packages_copies(self, value):
        # type: (bool) -> None
        self._pex_info["venv_site_packages_copies"] = value

    @property
    def venv_system_site_packages(self):
        # type: () -> bool
        return self._pex_info.get("venv_system_site_packages", False)

    @venv_system_site_packages.setter
    def venv_system_site_packages(self, value):
        # type: (bool) -> None
        self._pex_info["venv_system_site_packages"] = value

    @property
    def venv_hermetic_scripts(self):
        # type: () -> bool
        return self._pex_info.get("venv_hermetic_scripts", True)

    @venv_hermetic_scripts.setter
    def venv_hermetic_scripts(self, value):
        # type: (bool) -> None
        self._pex_info["venv_hermetic_scripts"] = value

    def _venv_dir(
        self,
        pex_root,  # type: str
        pex_file,  # type: str
        interpreter=None,  # type: Optional[PythonInterpreter]
        expand_pex_root=True,  # type: bool
    ):
        # type: (...) -> Optional[VenvDir]
        if not self.venv:
            return None
        if self.pex_hash is None:
            raise ValueError("The venv_dir was requested but no pex_hash was set.")
        return variables.venv_dir(
            pex_file=pex_file,
            pex_root=pex_root,
            pex_hash=self.pex_hash,
            has_interpreter_constraints=self.has_interpreter_constraints,
            interpreter=interpreter,
            pex_path=self.pex_path,
            expand_pex_root=expand_pex_root,
        )

    def runtime_venv_dir(
        self,
        pex_file,  # type: str
        interpreter=None,  # type: Optional[PythonInterpreter]
    ):
        # type: (...) -> Optional[VenvDir]
        return self._venv_dir(self.pex_root, pex_file, interpreter)

    def raw_venv_dir(
        self,
        pex_file,  # type: str
        interpreter=None,  # type: Optional[PythonInterpreter]
    ):
        # type: (...) -> Optional[VenvDir]
        """Distiguished from ``venv_dir`` by use of the raw_pex_root.
        We don't expand the pex_root at build time in case the pex_root is not
        writable or doesn't exist at build time.
        """
        return self._venv_dir(self.raw_pex_root, pex_file, interpreter, expand_pex_root=False)

    @property
    def includes_tools(self):
        # type: () -> bool
        return self._pex_info.get("includes_tools", self.venv)

    @includes_tools.setter
    def includes_tools(self, value):
        # type: (bool) -> None
        self._pex_info["includes_tools"] = bool(value)

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
        # type: () -> Tuple[str, ...]
        """A list of other pex files to merge into the runtime environment.

        This pex info property is used to persist the PEX_PATH environment variable into the pex
        info metadata for reuse within a built pex.
        """
        pex_paths = self._pex_info.get("pex_paths")
        if pex_paths:
            return tuple(cast("Iterable[str]", pex_paths))

        # Legacy PEX-INFO stored this in a single string as a colon-separated list.
        pex_path = self._pex_info.get("pex_path")
        if pex_path:
            return tuple(pex_path.split(":"))

        return ()

    @pex_path.setter
    def pex_path(self, value):
        # type: (Iterable[str]) -> None
        if not WINDOWS:
            # Store in the legacy format on the legacy supported OSes for backwards compatibility
            # with old tools reading new PEX-INFO.
            self._pex_info["pex_path"] = ":".join(value)
        self._pex_info["pex_paths"] = tuple(value)

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
    def has_interpreter_constraints(self):
        # type: () -> bool
        if self._interpreter_constraints is not None:
            return bool(self._interpreter_constraints)
        return bool(self._pex_info.get("interpreter_constraints", ()))

    @property
    def interpreter_constraints(self):
        # type: () -> InterpreterConstraints
        """A list of constraints that determine the interpreter compatibility for this pex, using
        the Requirement-style format, e.g. ``'CPython>=3', or just '>=2.7,<3'`` for requirements
        agnostic to interpreter class.

        This property will be used at exec time when bootstrapping a pex to search PEX_PYTHON_PATH
        for a list of compatible interpreters.
        """
        if self._interpreter_constraints is None:
            # N.B.: InterpreterConstraints is an expensive import and PexInfo is used during PEX
            # bootstrapping which we want to be as fast as possible; so we go through hoops to be
            # lazy here.
            from pex.interpreter_constraints import InterpreterConstraints

            self._interpreter_constraints = InterpreterConstraints.parse(
                *self._pex_info.get("interpreter_constraints", ())
            )
        return self._interpreter_constraints

    @interpreter_constraints.setter
    def interpreter_constraints(self, value):
        # type: (InterpreterConstraints) -> None
        self._interpreter_constraints = value

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
        # type: () -> Collection[str]
        return self._requirements

    def add_exclude(self, requirement):
        # type: (Requirement) -> None
        self._excluded.add(str(requirement))

    @property
    def excluded(self):
        # type: () -> Iterable[str]
        return self._excluded

    def add_override(self, requirement):
        # type: (Requirement) -> None
        self._overridden.add(str(requirement))

    @property
    def overridden(self):
        # type: () -> Iterable[str]
        return self._overridden

    def add_distribution(self, location, sha):
        self._distributions[location] = sha

    @property
    def distributions(self):
        # type: () -> Dict[str, str]
        return self._distributions

    @property
    def raw_pex_root(self):
        # type: () -> str
        return cast(str, self._pex_info.get("pex_root", cache_root.path(expand_user=False)))

    @property
    def pex_root(self):
        # type: () -> str
        pex_root = os.path.realpath(os.path.expanduser(self.raw_pex_root))
        if not can_write_dir(pex_root):
            tmp_root = os.path.realpath(safe_mkdtemp())
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
    def bootstrap_hash(self):
        # type: () -> Optional[str]
        return self._pex_info.get("bootstrap_hash")

    @bootstrap_hash.setter
    def bootstrap_hash(self, value):
        # type: (str) -> None
        self._pex_info["bootstrap_hash"] = value

    @property
    def deps_are_wheel_files(self):
        # type: () -> bool
        return self._pex_info.get("deps_are_wheel_files", False)

    @deps_are_wheel_files.setter
    def deps_are_wheel_files(self, value):
        # type: (bool) -> None
        self._pex_info["deps_are_wheel_files"] = value

    @property
    def max_install_jobs(self):
        # type: () -> int
        return self._pex_info.get("max_install_jobs", 1)

    @max_install_jobs.setter
    def max_install_jobs(self, value):
        # type: (int) -> None
        if value < -1:
            raise ValueError(
                "The value for max_install_jobs must be -1 or greater; given: {jobs}".format(
                    jobs=value
                )
            )
        self._pex_info["max_install_jobs"] = value

    @property
    def bootstrap(self):
        # type: () -> str
        return layout.BOOTSTRAP_DIR

    @property
    def internal_cache(self):
        # type: () -> str
        return layout.DEPS_DIR

    def update(self, other):
        # type: (PexInfo) -> None
        if not isinstance(other, PexInfo):
            raise TypeError("Cannot merge a %r with PexInfo" % type(other))
        self._pex_info.update(other._pex_info)
        self._distributions.update(other.distributions)
        if other.has_interpreter_constraints:
            self._interpreter_constraints = self.interpreter_constraints.merged(
                other.interpreter_constraints
            )
        self._requirements.update(other.requirements)
        self._excluded.update(other.excluded)

    def as_json_dict(self):
        # type: () -> Dict[str, Any]
        data = self._pex_info.copy()
        data["inherit_path"] = self.inherit_path.value
        data["requirements"] = sorted(self._requirements)
        data["excluded"] = sorted(self._excluded)
        data["overridden"] = sorted(self._overridden)
        data["interpreter_constraints"] = sorted(str(ic) for ic in self.interpreter_constraints)
        data["distributions"] = self._distributions.copy()
        return data

    def dump(self, **extra_json_dumps_kwargs):
        # type: (**Any) -> str
        return json.dumps(self.as_json_dict(), sort_keys=True, **extra_json_dumps_kwargs)

    def copy(self):
        # type: () -> PexInfo
        return PexInfo(self.as_json_dict())

    def merge_pex_path(self, pex_path):
        # type: (Iterable[str]) -> None
        """Merges a new PEX_PATH definition into the existing one (if any).

        :param pex_path: The PEX_PATH to merge.
        """
        if not pex_path:
            return
        merged_pex_path = OrderedSet(self.pex_path)
        merged_pex_path.update(pex_path)
        self.pex_path = tuple(merged_pex_path)

    def __repr__(self):
        return "{}({!r})".format(type(self).__name__, self._pex_info)
