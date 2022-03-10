# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""pex support for interacting with interpreters."""

from __future__ import absolute_import

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import sysconfig
from collections import OrderedDict
from textwrap import dedent

from pex import third_party
from pex.common import is_exe, safe_mkdtemp, safe_rmtree
from pex.compatibility import string
from pex.executor import Executor
from pex.jobs import ErrorHandler, Job, Retain, SpawnedJob, execute_parallel
from pex.orderedset import OrderedSet
from pex.pep_425 import CompatibilityTags
from pex.pep_508 import MarkerEnvironment
from pex.platforms import Platform
from pex.pyenv import Pyenv
from pex.third_party.packaging import tags
from pex.third_party.pkg_resources import Distribution, Requirement
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast, overload
from pex.util import CacheHelper
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import (
        Any,
        AnyStr,
        Callable,
        Dict,
        Iterable,
        Iterator,
        List,
        Mapping,
        MutableMapping,
        Optional,
        Text,
        Tuple,
        Union,
    )

    PathFilter = Callable[[str], bool]

    InterpreterIdentificationJobError = Tuple[str, Union[Job.Error, Exception]]
    InterpreterOrJobError = Union["PythonInterpreter", InterpreterIdentificationJobError]

    # N.B.: We convert InterpreterIdentificationJobErrors that result from spawning interpreter
    # identification jobs to these end-user InterpreterIdentificationErrors for display.
    InterpreterIdentificationError = Tuple[str, Text]
    InterpreterOrError = Union["PythonInterpreter", InterpreterIdentificationError]


class PythonIdentity(object):
    class Error(Exception):
        pass

    class InvalidError(Error):
        pass

    class UnknownRequirement(Error):
        pass

    ABBR_TO_INTERPRETER_NAME = {
        "pp": "PyPy",
        "cp": "CPython",
    }

    @staticmethod
    def _normalize_macosx_deployment_target(value):
        # type: (Any) -> Optional[str]

        # N.B.: Sometimes MACOSX_DEPLOYMENT_TARGET can be configured as a float.
        # See: https://github.com/pantsbuild/pex/issues/1337
        if value is None:
            return None
        return str(value)

    @classmethod
    def get(cls, binary=None):
        # type: (Optional[str]) -> PythonIdentity

        # N.B.: We should not need to look past `sys.executable` to learn the current interpreter's
        # executable path, but on OSX there has been a bug where the `sys.executable` reported is
        # _not_ the path of the current interpreter executable:
        #   https://bugs.python.org/issue22490#msg283859
        # That case is distinguished by the presence of a `__PYVENV_LAUNCHER__` environment
        # variable as detailed in the Python bug linked above.
        if binary and binary != sys.executable and "__PYVENV_LAUNCHER__" not in os.environ:
            # Here we assume sys.executable is accurate and binary is something like a pyenv shim.
            binary = sys.executable

        supported_tags = tuple(tags.sys_tags())
        preferred_tag = supported_tags[0]

        configured_macosx_deployment_target = cls._normalize_macosx_deployment_target(
            sysconfig.get_config_var("MACOSX_DEPLOYMENT_TARGET")
        )

        # Pex identifies interpreters using a bit of Pex code injected via an extraction of that
        # code under the `PEX_ROOT` adjoined to `sys.path` via `PYTHONPATH`. We ignore such adjoined
        # `sys.path` entries to discover the true base interpreter `sys.path`.
        pythonpath = frozenset(os.environ.get("PYTHONPATH", "").split(os.pathsep))
        sys_path = [item for item in sys.path if item and item not in pythonpath]

        return cls(
            binary=binary or sys.executable,
            prefix=sys.prefix,
            base_prefix=(
                # Old virtualenv (16 series and lower) sets `sys.real_prefix` in all cases.
                cast("Optional[str]", getattr(sys, "real_prefix", None))
                # Both pyvenv and virtualenv 20+ set `sys.base_prefix` as per
                # https://www.python.org/dev/peps/pep-0405/.
                or cast(str, getattr(sys, "base_prefix", sys.prefix))
            ),
            sys_path=sys_path,
            python_tag=preferred_tag.interpreter,
            abi_tag=preferred_tag.abi,
            platform_tag=preferred_tag.platform,
            version=sys.version_info[:3],
            supported_tags=supported_tags,
            env_markers=MarkerEnvironment.default(),
            configured_macosx_deployment_target=configured_macosx_deployment_target,
        )

    @classmethod
    def decode(cls, encoded):
        TRACER.log("creating PythonIdentity from encoded: %s" % encoded, V=9)
        values = json.loads(encoded)
        if len(values) != 11:
            raise cls.InvalidError("Invalid interpreter identity: %s" % encoded)

        supported_tags = values.pop("supported_tags")

        def iter_tags():
            for (interpreter, abi, platform) in supported_tags:
                yield tags.Tag(interpreter=interpreter, abi=abi, platform=platform)

        # N.B.: Old encoded identities may have numeric values; so we support these and convert
        # back to strings here as needed. See: https://github.com/pantsbuild/pex/issues/1337
        configured_macosx_deployment_target = cls._normalize_macosx_deployment_target(
            values.pop("configured_macosx_deployment_target")
        )

        env_markers = MarkerEnvironment(**values.pop("env_markers"))
        return cls(
            supported_tags=iter_tags(),
            configured_macosx_deployment_target=configured_macosx_deployment_target,
            env_markers=env_markers,
            **values
        )

    @classmethod
    def _find_interpreter_name(cls, python_tag):
        for abbr, interpreter in cls.ABBR_TO_INTERPRETER_NAME.items():
            if python_tag.startswith(abbr):
                return interpreter
        raise ValueError("Unknown interpreter: {}".format(python_tag))

    def __init__(
        self,
        binary,  # type: str
        prefix,  # type: str
        base_prefix,  # type: str
        sys_path,  # type: Iterable[str]
        python_tag,  # type: str
        abi_tag,  # type: str
        platform_tag,  # type: str
        version,  # type: Iterable[int]
        supported_tags,  # type: Iterable[tags.Tag]
        env_markers,  # type: MarkerEnvironment
        configured_macosx_deployment_target,  # type: Optional[str]
    ):
        # type: (...) -> None
        # N.B.: We keep this mapping to support historical values for `distribution` and
        # `requirement` properties.
        self._interpreter_name = self._find_interpreter_name(python_tag)

        self._binary = binary
        self._prefix = prefix
        self._base_prefix = base_prefix
        self._sys_path = tuple(sys_path)
        self._python_tag = python_tag
        self._abi_tag = abi_tag
        self._platform_tag = platform_tag
        self._version = tuple(version)
        self._supported_tags = CompatibilityTags(tags=supported_tags)
        self._env_markers = env_markers
        self._configured_macosx_deployment_target = configured_macosx_deployment_target

    def encode(self):
        values = dict(
            binary=self._binary,
            prefix=self._prefix,
            base_prefix=self._base_prefix,
            sys_path=self._sys_path,
            python_tag=self._python_tag,
            abi_tag=self._abi_tag,
            platform_tag=self._platform_tag,
            version=self._version,
            supported_tags=[
                (tag.interpreter, tag.abi, tag.platform) for tag in self._supported_tags
            ],
            env_markers=self._env_markers.as_dict(),
            configured_macosx_deployment_target=self._configured_macosx_deployment_target,
        )
        return json.dumps(values, sort_keys=True)

    @property
    def binary(self):
        return self._binary

    @property
    def prefix(self):
        # type: () -> str
        return self._prefix

    @property
    def base_prefix(self):
        # type: () -> str
        return self._base_prefix

    @property
    def sys_path(self):
        # type: () -> Tuple[str, ...]
        return self._sys_path

    @property
    def python_tag(self):
        return self._python_tag

    @property
    def abi_tag(self):
        return self._abi_tag

    @property
    def platform_tag(self):
        return self._platform_tag

    @property
    def version(self):
        # type: () -> Tuple[int, int, int]
        """The interpreter version as a normalized tuple.

        Consistent with `sys.version_info`, the tuple corresponds to `<major>.<minor>.<micro>`.
        """
        return cast("Tuple[int, int, int]", self._version)

    @property
    def version_str(self):
        # type: () -> str
        return ".".join(map(str, self.version))

    @property
    def supported_tags(self):
        # type: () -> CompatibilityTags
        return self._supported_tags

    @property
    def env_markers(self):
        # type: () -> MarkerEnvironment
        return self._env_markers

    @property
    def configured_macosx_deployment_target(self):
        # type: () -> Optional[str]
        return self._configured_macosx_deployment_target

    @property
    def interpreter(self):
        return self._interpreter_name

    @property
    def requirement(self):
        # type: () -> Requirement
        return self.distribution.as_requirement()

    @property
    def distribution(self):
        # type: () -> Distribution
        return Distribution(project_name=self.interpreter, version=self.version_str)

    def iter_supported_platforms(self):
        # type: () -> Iterator[Platform]
        """All platforms supported by the associated interpreter ordered from most specific to
        least."""
        yield Platform(
            platform=self._platform_tag,
            impl=self.python_tag[:2],
            version=self.version_str,
            version_info=self.version,
            abi=self.abi_tag,
        )
        for tag in self._supported_tags:
            yield Platform.from_tag(tag)

    @classmethod
    def parse_requirement(cls, requirement, default_interpreter="CPython"):
        if isinstance(requirement, Requirement):
            return requirement
        elif isinstance(requirement, string):
            try:
                requirement = Requirement.parse(requirement)
            except ValueError:
                try:
                    requirement = Requirement.parse("%s%s" % (default_interpreter, requirement))
                except ValueError:
                    raise ValueError("Unknown requirement string: %s" % requirement)
            return requirement
        else:
            raise ValueError("Unknown requirement type: %r" % (requirement,))

    def matches(self, requirement):
        """Given a Requirement, check if this interpreter matches."""
        try:
            requirement = self.parse_requirement(requirement, self._interpreter_name)
        except ValueError as e:
            raise self.UnknownRequirement(str(e))
        return self.distribution in requirement

    def hashbang(self):
        # type: () -> str
        if self._interpreter_name == "PyPy":
            hashbang_string = "pypy" if self._version[0] == 2 else "pypy{}".format(self._version[0])
        else:
            hashbang_string = "python{}.{}".format(self._version[0], self._version[1])
        return "#!/usr/bin/env {}".format(hashbang_string)

    @property
    def python(self):
        # type: () -> str
        # return the python version in the format of the 'python' key for distributions
        # specifically, '2.7', '3.2', etc.
        return "%d.%d" % (self.version[0:2])

    def __str__(self):
        # type: () -> str
        # N.B.: Kept as distinct from __repr__ to support legacy str(identity) used by Pants v1 when
        # forming cache locations.
        return "{interpreter_name}-{major}.{minor}.{patch}".format(
            interpreter_name=self._interpreter_name,
            major=self._version[0],
            minor=self._version[1],
            patch=self._version[2],
        )

    def __repr__(self):
        # type: () -> str
        return (
            "{type}({binary!r}, {python_tag!r}, {abi_tag!r}, {platform_tag!r}, {version!r})".format(
                type=self.__class__.__name__,
                binary=self._binary,
                python_tag=self._python_tag,
                abi_tag=self._abi_tag,
                platform_tag=self._platform_tag,
                version=self._version,
            )
        )

    def _tup(self):
        return self._binary, self._python_tag, self._abi_tag, self._platform_tag, self._version

    def __eq__(self, other):
        if type(other) is not type(self):
            return NotImplemented
        return self._tup() == other._tup()

    def __hash__(self):
        # type: () -> int
        return hash(self._tup())


class PythonInterpreter(object):
    _REGEXEN = (
        # NB: OSX ships python binaries named Python with a capital-P; so we allow for this.
        re.compile(r"^Python$"),
        re.compile(
            r"""
            ^
            (?:
                python |
                pypy
            )
            (?:
                # Major version
                [2-9]
                (?:.
                    # Minor version
                    [0-9]+
                    # Some distributions include a suffix on the interpreter name, similar to
                    # PEP-3149. For example, Gentoo has /usr/bin/python3.6m to indicate it was
                    # built with pymalloc
                    [a-z]?
                )?
            )?
            $
            """,
            flags=re.VERBOSE,
        ),
    )

    _PYTHON_INTERPRETER_BY_NORMALIZED_PATH = {}  # type: Dict

    @staticmethod
    def _get_pyvenv_cfg(path):
        # type: (str) -> Optional[str]
        # See: https://www.python.org/dev/peps/pep-0405/#specification
        pyvenv_cfg_path = os.path.join(path, "pyvenv.cfg")
        if os.path.isfile(pyvenv_cfg_path):
            with open(pyvenv_cfg_path) as fp:
                for line in fp:
                    name, _, value = line.partition("=")
                    if name.strip() == "home":
                        return pyvenv_cfg_path
        return None

    @classmethod
    def _find_pyvenv_cfg(cls, maybe_venv_python_binary):
        # type: (str) -> Optional[str]
        # A pyvenv is identified by a pyvenv.cfg file with a home key in one of the two following
        # directory layouts:
        #
        # 1. <venv dir>/
        #      bin/
        #        pyvenv.cfg
        #        python*
        #
        # 2. <venv dir>/
        #      pyvenv.cfg
        #      bin/
        #        python*
        #
        # In practice, we see layout 2 in the wild, but layout 1 is also allowed by the spec.
        #
        # See: # See: https://www.python.org/dev/peps/pep-0405/#specification
        maybe_venv_bin_dir = os.path.dirname(maybe_venv_python_binary)
        pyvenv_cfg = cls._get_pyvenv_cfg(maybe_venv_bin_dir)
        if not pyvenv_cfg:
            maybe_venv_dir = os.path.dirname(maybe_venv_bin_dir)
            pyvenv_cfg = cls._get_pyvenv_cfg(maybe_venv_dir)
        return pyvenv_cfg

    @classmethod
    def _resolve_pyvenv_canonical_python_binary(
        cls,
        real_binary,  # type: str
        maybe_venv_python_binary,  # type: str
    ):
        # type: (...) -> Optional[str]
        maybe_venv_python_binary = os.path.abspath(maybe_venv_python_binary)
        if not os.path.islink(maybe_venv_python_binary):
            return None

        pyvenv_cfg = cls._find_pyvenv_cfg(maybe_venv_python_binary)
        if pyvenv_cfg is None:
            return None

        while os.path.islink(maybe_venv_python_binary):
            resolved = os.readlink(maybe_venv_python_binary)
            if not os.path.isabs(resolved):
                resolved = os.path.abspath(
                    os.path.join(os.path.dirname(maybe_venv_python_binary), resolved)
                )
            if os.path.dirname(resolved) == os.path.dirname(maybe_venv_python_binary):
                maybe_venv_python_binary = resolved
            else:
                # We've escaped the venv bin dir; so the last resolved link was the
                # canonical venv Python binary.
                #
                # For example, for:
                #   ./venv/bin/
                #     python -> python3.8
                #     python3 -> python3.8
                #     python3.8 -> /usr/bin/python3.8
                #
                # We want to resolve each of ./venv/bin/python{,3{,.8}} to the canonical
                # ./venv/bin/python3.8 which is the symlink that points to the home binary.
                break
        return maybe_venv_python_binary

    @classmethod
    def canonicalize_path(cls, path):
        # type: (str) -> str
        """Canonicalize a potential Python interpreter path.

        This will return a path-equivalent of the given `path` in canonical form for use in cache
        keys.

        N.B.: If the path is a venv symlink it will not be fully de-referenced in order to maintain
        fidelity with the requested venv Python binary choice.
        """
        real_binary = os.path.realpath(path)

        # If the path is a PEP-405 venv interpreter symlink we do not want to resolve outside of the
        # venv in order to stay faithful to the binary path choice.
        return (
            cls._resolve_pyvenv_canonical_python_binary(
                real_binary=real_binary, maybe_venv_python_binary=path
            )
            or real_binary
        )

    class Error(Exception):
        pass

    class IdentificationError(Error):
        pass

    class InterpreterNotFound(Error):
        pass

    @staticmethod
    def latest_release_of_min_compatible_version(interps):
        # type: (Iterable[PythonInterpreter]) -> PythonInterpreter
        """Find the minimum major version, but use the most recent micro version within that minor
        version.

        That is, prefer 3.6.1 over 3.6.0, and prefer both over 3.7.*.
        """
        assert interps, "No interpreters passed to `PythonInterpreter.safe_min()`"
        return min(
            interps, key=lambda interp: (interp.version[0], interp.version[1], -interp.version[2])
        )

    @classmethod
    def get(cls):
        # type: () -> PythonInterpreter
        return cls.from_binary(sys.executable)

    @staticmethod
    def _paths(paths=None):
        # type: (Optional[Iterable[str]]) -> Iterable[str]
        # NB: If `paths=[]`, we will not read $PATH.
        return OrderedSet(paths if paths is not None else os.getenv("PATH", "").split(os.pathsep))

    @classmethod
    def iter(cls, paths=None):
        # type: (Optional[Iterable[str]]) -> Iterator[PythonInterpreter]
        """Iterate all valid interpreters found in `paths`.

        NB: The paths can either be directories to search for python binaries or the paths of python
        binaries themselves.

        :param paths: The paths to look for python interpreters; by default the `PATH`.
        """
        return cls._filter(cls._find(cls._paths(paths=paths)))

    @classmethod
    def iter_candidates(cls, paths=None, path_filter=None):
        # type: (Optional[Iterable[str]], Optional[PathFilter]) -> Iterator[InterpreterOrError]
        """Iterate all likely interpreters found in `paths`.

        NB: The paths can either be directories to search for python binaries or the paths of python
        binaries themselves.

        :param paths: The paths to look for python interpreters; by default the `PATH`.
        :param path_filter: An optional predicate to test whether a candidate interpreter's binary
                            path is acceptable.
        :return: A heterogeneous iterator over valid interpreters and (python, error) invalid
                 python binary tuples.
        """
        failed_interpreters = OrderedDict()  # type: MutableMapping[str, Text]

        def iter_interpreters():
            # type: () -> Iterator[PythonInterpreter]
            for candidate in cls._find(
                cls._paths(paths=paths), path_filter=path_filter, error_handler=Retain()
            ):
                if isinstance(candidate, cls):
                    yield candidate
                else:
                    python, exception = cast("InterpreterIdentificationJobError", candidate)
                    if isinstance(exception, Job.Error) and exception.stderr:
                        # We spawned a subprocess to identify the interpreter but the interpreter
                        # could not run our identification code meaning the interpreter is either
                        # broken or old enough that it either can't parse our identification code
                        # or else provide stdlib modules we expect. The stderr should indicate the
                        # broken-ness appropriately.
                        failed_interpreters[python] = exception.stderr.strip()
                    else:
                        # We couldn't even spawn a subprocess to identify the interpreter. The
                        # likely OSError should help identify the underlying issue.
                        failed_interpreters[python] = repr(exception)

        for interpreter in cls._filter(iter_interpreters()):
            yield interpreter

        for python, error in failed_interpreters.items():
            yield python, error

    @classmethod
    def all(cls, paths=None):
        # type: (Optional[Iterable[str]]) -> Iterable[PythonInterpreter]
        return list(cls.iter(paths=paths))

    @classmethod
    def _create_isolated_cmd(
        cls,
        binary,  # type: str
        args=None,  # type: Optional[Iterable[str]]
        pythonpath=None,  # type: Optional[Iterable[str]]
        env=None,  # type: Optional[Mapping[str, str]]
    ):
        # type: (...) -> Tuple[Iterable[str], Mapping[str, str]]
        cmd = [binary]

        # Don't add the user site directory to `sys.path`.
        #
        # Additionally, it would be nice to pass `-S` to disable adding site-packages but unfortunately
        # some python distributions include portions of the standard library there.
        cmd.append("-s")

        env = cls._sanitized_environment(env=env)
        pythonpath = list(pythonpath or ())
        if pythonpath:
            env["PYTHONPATH"] = os.pathsep.join(pythonpath)
        else:
            # Turn off reading of PYTHON* environment variables.
            cmd.append("-E")

        if args:
            cmd.extend(args)

        rendered_command = " ".join(cmd)
        if pythonpath:
            rendered_command = "PYTHONPATH={} {}".format(env["PYTHONPATH"], rendered_command)
        TRACER.log("Executing: {}".format(rendered_command), V=3)

        return cmd, env

    # We use () as the unset sentinel for this lazily calculated cached value. The cached value
    # itself should always be Optional[Pyenv].
    #
    # N.B.: The empty tuple type is not represented as Tuple[] as you might naivly guess but
    # instead as Tuple[()].
    #
    # See:
    # + https://github.com/python/mypy/issues/4211
    # + https://www.python.org/dev/peps/pep-0484/#the-typing-module
    _PYENV = ()  # type: Union[Tuple[()],Optional[Pyenv]]

    @classmethod
    def _pyenv(cls):
        # type: () -> Optional[Pyenv]
        if isinstance(cls._PYENV, tuple):
            cls._PYENV = Pyenv.find()
        return cls._PYENV

    @classmethod
    def _resolve_pyenv_shim(
        cls,
        binary,  # type: str
        pyenv=None,  # type: Optional[Pyenv]
    ):
        # type: (...) -> Optional[str]

        pyenv = pyenv or cls._pyenv()
        if pyenv is not None:
            shim = pyenv.as_shim(binary)
            if shim is not None:
                python = shim.select_version()
                if python is None:
                    TRACER.log("Detected inactive pyenv shim: {}.".format(shim), V=3)
                else:
                    TRACER.log("Detected pyenv shim activated to {}: {}.".format(python, shim), V=3)
                return python
        return binary

    INTERP_INFO_FILE = "INTERP-INFO"

    @classmethod
    def _spawn_from_binary_external(cls, binary):
        # type: (str) -> SpawnedJob[PythonInterpreter]

        def create_interpreter(
            stdout,  # type: bytes
            check_binary=False,  # type: bool
        ):
            # type: (...) -> PythonInterpreter
            identity = stdout.decode("utf-8").strip()
            if not identity:
                raise cls.IdentificationError("Could not establish identity of {}.".format(binary))
            interpreter = cls(PythonIdentity.decode(identity))
            # We should not need to check this since binary == interpreter.binary should always be
            # true, but historically this could be untrue as noted in `PythonIdentity.get`.
            if check_binary and not os.path.exists(interpreter.binary):
                raise cls.InterpreterNotFound(
                    "Cached interpreter for {} reports a binary of {}, which could not be found".format(
                        binary, interpreter.binary
                    )
                )
            return interpreter

        # Part of the PythonInterpreter data are environment markers that depend on the current OS
        # release. That data can change when the OS is upgraded but (some of) the installed interpreters
        # remain the same. As such, include the OS in the hash structure for cached interpreters.
        os_digest = hashlib.sha1()
        for os_identifier in platform.release(), platform.version():
            os_digest.update(os_identifier.encode("utf-8"))
        os_hash = os_digest.hexdigest()

        interpreter_cache_dir = os.path.join(ENV.PEX_ROOT, "interpreters")
        os_cache_dir = os.path.join(interpreter_cache_dir, os_hash)
        if os.path.isdir(interpreter_cache_dir) and not os.path.isdir(os_cache_dir):
            with TRACER.timed("GCing interpreter cache from prior OS version"):
                safe_rmtree(interpreter_cache_dir)

        interpreter_hash = CacheHelper.hash(binary)

        # Some distributions include more than one copy of the same interpreter via a hard link (e.g.:
        # python3.7 is a hardlink to python3.7m). To ensure a deterministic INTERP-INFO file we must
        # emit a separate INTERP-INFO for each link since INTERP-INFO contains the interpreter path and
        # would otherwise be unstable.
        #
        # See cls._REGEXEN for a related affordance.
        #
        # N.B.: The path for --venv mode interpreters can be quite long; so we just used a fixed
        # length hash of the interpreter binary path to ensure uniqueness and not run afoul of file
        # name length limits.
        path_id = hashlib.sha1(binary.encode("utf-8")).hexdigest()

        cache_dir = os.path.join(os_cache_dir, interpreter_hash, path_id)
        cache_file = os.path.join(cache_dir, cls.INTERP_INFO_FILE)
        if os.path.isfile(cache_file):
            try:
                with open(cache_file, "rb") as fp:
                    return SpawnedJob.completed(create_interpreter(fp.read(), check_binary=True))
            except (IOError, OSError, cls.Error, PythonIdentity.Error):
                safe_rmtree(cache_dir)
                return cls._spawn_from_binary_external(binary)
        else:
            pythonpath = third_party.expose(["pex"])
            cmd, env = cls._create_isolated_cmd(
                binary,
                args=[
                    "-c",
                    dedent(
                        """\
                        import os
                        import sys

                        from pex.common import atomic_directory, safe_open
                        from pex.interpreter import PythonIdentity


                        encoded_identity = PythonIdentity.get(binary={binary!r}).encode()
                        with atomic_directory({cache_dir!r}, exclusive=False) as cache_dir:
                            if not cache_dir.is_finalized():
                                with safe_open(
                                    os.path.join(cache_dir.work_dir, {info_file!r}), 'w'
                                ) as fp:
                                    fp.write(encoded_identity)
                        """.format(
                            binary=binary, cache_dir=cache_dir, info_file=cls.INTERP_INFO_FILE
                        )
                    ),
                ],
                pythonpath=pythonpath,
            )
            # Ensure the `.` implicit PYTHONPATH entry contains no Pex code (of a different version)
            # that might interfere with the behavior we expect in the script above.
            cwd = safe_mkdtemp()
            process = Executor.open_process(
                cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd
            )
            job = Job(command=cmd, process=process, finalizer=lambda _: safe_rmtree(cwd))
            return SpawnedJob.file(job, output_file=cache_file, result_func=create_interpreter)

    @classmethod
    def _expand_path(cls, path):
        if os.path.isfile(path):
            return [path]
        elif os.path.isdir(path):
            return sorted(os.path.join(path, fn) for fn in os.listdir(path))
        return []

    @classmethod
    def from_env(
        cls,
        hashbang,  # type: str
        paths=None,  # type: Optional[Iterable[str]]
    ):
        # type: (...) -> Optional[PythonInterpreter]
        """Resolve a PythonInterpreter as /usr/bin/env would.

        :param hashbang: A string, e.g. "python3.3" representing some binary on the search path.
        :param paths: The search path to use; defaults to $PATH.
        :return: the first matching interpreter found or `None`.
        """

        def hashbang_matches(fn):
            basefile = os.path.basename(fn)
            return hashbang == basefile

        for interpreter in cls._identify_interpreters(
            filter=hashbang_matches, error_handler=None, paths=paths
        ):
            return interpreter
        return None

    @classmethod
    def _spawn_from_binary(cls, binary):
        # type: (str) -> SpawnedJob[PythonInterpreter]
        canonicalized_binary = cls.canonicalize_path(binary)
        if not os.path.exists(canonicalized_binary):
            raise cls.InterpreterNotFound(
                "The interpreter path {} does not exist.".format(canonicalized_binary)
            )

        # N.B.: The cache is written as the last step in PythonInterpreter instance initialization.
        cached_interpreter = cls._PYTHON_INTERPRETER_BY_NORMALIZED_PATH.get(canonicalized_binary)
        if cached_interpreter is not None:
            return SpawnedJob.completed(cached_interpreter)
        if canonicalized_binary == cls.canonicalize_path(sys.executable):
            current_interpreter = cls(PythonIdentity.get())
            return SpawnedJob.completed(current_interpreter)
        return cls._spawn_from_binary_external(canonicalized_binary)

    @classmethod
    def from_binary(
        cls,
        binary,  # type: str
        pyenv=None,  # type: Optional[Pyenv]
    ):
        # type: (...) -> PythonInterpreter
        """Create an interpreter from the given `binary`.

        :param binary: The path to the python interpreter binary.
        :param pyenv: A custom Pyenv installation for handling pyenv shim identification.
                      Auto-detected by default.
        :return: an interpreter created from the given `binary`.
        """
        python = cls._resolve_pyenv_shim(binary, pyenv=pyenv)
        if python is None:
            raise cls.IdentificationError("The pyenv shim at {} is not active.".format(binary))

        try:
            return cast(PythonInterpreter, cls._spawn_from_binary(python).await_result())
        except Job.Error as e:
            raise cls.IdentificationError("Failed to identify {}: {}".format(binary, e))

    @classmethod
    def _matches_binary_name(cls, path):
        # type: (str) -> bool
        basefile = os.path.basename(path)
        return any(matcher.match(basefile) is not None for matcher in cls._REGEXEN)

    @overload
    @classmethod
    def _find(cls, paths):
        # type: (Iterable[str]) -> Iterator[PythonInterpreter]
        pass

    @overload
    @classmethod
    def _find(
        cls,
        paths,  # type: Iterable[str]
        error_handler,  # type: Retain
        path_filter=None,  # type: Optional[PathFilter]
    ):
        # type: (...) -> Iterator[InterpreterOrJobError]
        pass

    @classmethod
    def _find(
        cls,
        paths,  # type: Iterable[str]
        error_handler=None,  # type: Optional[ErrorHandler]
        path_filter=None,  # type: Optional[PathFilter]
    ):
        # type: (...) -> Union[Iterator[PythonInterpreter], Iterator[InterpreterOrJobError]]
        """Given a list of files or directories, try to detect python interpreters amongst them.

        Returns an iterator over PythonInterpreter objects.
        """
        return cls._identify_interpreters(
            filter=path_filter or cls._matches_binary_name, paths=paths, error_handler=error_handler
        )

    @overload
    @classmethod
    def _identify_interpreters(
        cls,
        filter,  # type: PathFilter
        error_handler,  # type: None
        paths=None,  # type: Optional[Iterable[str]]
    ):
        # type: (...) -> Iterator[PythonInterpreter]
        pass

    @overload
    @classmethod
    def _identify_interpreters(
        cls,
        filter,  # type: PathFilter
        error_handler,  # type: Retain
        paths=None,  # type: Optional[Iterable[str]]
    ):
        # type: (...) -> Iterator[InterpreterOrJobError]
        pass

    @classmethod
    def _identify_interpreters(
        cls,
        filter,  # type: PathFilter
        error_handler=None,  # type: Optional[ErrorHandler]
        paths=None,  # type: Optional[Iterable[str]]
    ):
        # type: (...) -> Union[Iterator[PythonInterpreter], Iterator[InterpreterOrJobError]]
        def iter_candidates():
            # type: () -> Iterator[str]
            for path in cls._paths(paths=paths):
                for fn in cls._expand_path(path):
                    if filter(fn):
                        binary = cls._resolve_pyenv_shim(fn)
                        if binary:
                            yield binary

        results = execute_parallel(
            inputs=OrderedSet(iter_candidates()),
            spawn_func=cls._spawn_from_binary,
            error_handler=error_handler,
        )
        return cast("Union[Iterator[PythonInterpreter], Iterator[InterpreterOrJobError]]", results)

    @classmethod
    def _filter(cls, pythons):
        # type: (Iterable[PythonInterpreter]) -> Iterator[PythonInterpreter]
        """Filters duplicate python interpreters and versions we don't support.

        Returns an iterator over PythonInterpreters.
        """
        MAJOR, MINOR, SUBMINOR = range(3)

        def version_filter(version):
            # type: (Tuple[int, int, int]) -> bool
            return (
                version[MAJOR] == 2
                and version[MINOR] >= 7
                or version[MAJOR] == 3
                and version[MINOR] >= 5
            )

        seen = set()
        for interp in pythons:
            version = interp.identity.version
            identity = version, interp.identity.abi_tag
            if identity not in seen and version_filter(version):
                seen.add(identity)
                yield interp

    @classmethod
    def _sanitized_environment(cls, env=None):
        # type: (Optional[Mapping[str, str]]) -> Dict[str, str]
        # N.B. This is merely a hack because sysconfig.py on the default OS X
        # installation of 2.7 breaks. See: https://bugs.python.org/issue9516
        env_copy = dict(env or os.environ)
        env_copy.pop("MACOSX_DEPLOYMENT_TARGET", None)
        return env_copy

    def __init__(self, identity):
        # type: (PythonIdentity) -> None
        """Construct a PythonInterpreter.

        You should probably use `PythonInterpreter.from_binary` instead.
        """
        self._identity = identity
        self._binary = self.canonicalize_path(self.identity.binary)

        self._supported_platforms = None

        self._PYTHON_INTERPRETER_BY_NORMALIZED_PATH[self._binary] = self

    @property
    def binary(self):
        # type: () -> str
        return self._binary

    @property
    def is_venv(self):
        # type: () -> bool
        """Return `True` if this interpreter is homed in a virtual environment."""
        return self._identity.prefix != self._identity.base_prefix

    @property
    def prefix(self):
        # type: () -> str
        """Return the `sys.prefix` of this interpreter.

        For virtual environments, this will be the virtual environment directory itself.
        """
        return self._identity.prefix

    @property
    def sys_path(self):
        # type: () -> Tuple[str, ...]
        """Return the interpreter's `sys.path`.

        The implicit `$PWD` entry and any entries injected via PYTHONPATH or in the user site
        directory are excluded such that the `sys.path` presented is the base interpreter `sys.path`
        with no adornments.
        """
        return self._identity.sys_path

    class BaseInterpreterResolutionError(Exception):
        """Indicates the base interpreter for a virtual environment could not be resolved."""

    def resolve_base_interpreter(self):
        # type: () -> PythonInterpreter
        """Finds the base system interpreter used to create a virtual environment.

        If this interpreter is not homed in a virtual environment, returns itself.
        """
        if not self.is_venv:
            return self

        # In the case of PyPy, the <base_prefix> dir might contain one of the following:
        #
        # 1. On a system with PyPy 2.7 series and one PyPy 3.x series
        # bin/
        #   pypy
        #   pypy3
        #
        # 2. On a system with PyPy 2.7 series and more than one PyPy 3.x series
        # bin/
        #   pypy
        #   pypy3
        #   pypy3.6
        #   pypy3.7
        #
        # In both cases, bin/pypy is a 2.7 series interpreter. In case 2 bin/pypy3 could be either
        # PyPy 3.6 series or PyPy 3.7 series. In order to ensure we pick the correct base executable
        # of a PyPy virtual environment, we always try to resolve the most specific basename first
        # to the least specific basename last and we also verify that, if the basename resolves, it
        # resolves to an equivalent interpreter. We employ the same strategy for CPython, but only
        # for uniformity in the algorithm. It appears to always be the case for CPython that
        # python<major>.<minor> is present in any given <prefix>/bin/ directory; so the algorithm
        # gets a hit on 1st try for CPython binaries incurring ~no extra overhead.

        version = self._identity.version
        abi_tag = self._identity.abi_tag

        prefix = "pypy" if self._identity.interpreter == "PyPy" else "python"
        suffixes = ("{}.{}".format(version[0], version[1]), str(version[0]), "")
        candidate_binaries = tuple("{}{}".format(prefix, suffix) for suffix in suffixes)

        def iter_base_candidate_binary_paths(interpreter):
            # type: (PythonInterpreter) -> Iterator[str]
            bin_dir = os.path.join(interpreter._identity.base_prefix, "bin")
            for candidate_binary in candidate_binaries:
                candidate_binary_path = os.path.join(bin_dir, candidate_binary)
                if is_exe(candidate_binary_path):
                    yield candidate_binary_path

        def is_same_interpreter(interpreter):
            # type: (PythonInterpreter) -> bool
            identity = interpreter._identity
            return identity.version == version and identity.abi_tag == abi_tag

        resolution_path = []  # type: List[str]
        base_interpreter = self
        while base_interpreter.is_venv:
            resolved = None  # type: Optional[PythonInterpreter]
            for candidate_path in iter_base_candidate_binary_paths(base_interpreter):
                resolved_interpreter = self.from_binary(candidate_path)
                if is_same_interpreter(resolved_interpreter):
                    resolved = resolved_interpreter
                    break
            if resolved is None:
                message = [
                    "Failed to resolve the base interpreter for the virtual environment at "
                    "{venv_dir}.".format(venv_dir=self._identity.prefix)
                ]
                if resolution_path:
                    message.append(
                        "Resolved through {path}".format(
                            path=" -> ".join(binary for binary in resolution_path)
                        )
                    )
                message.append(
                    "Search of base_prefix {} found no equivalent interpreter for {}".format(
                        base_interpreter._identity.base_prefix, base_interpreter._binary
                    )
                )
                raise self.BaseInterpreterResolutionError("\n".join(message))
            base_interpreter = resolved_interpreter
            resolution_path.append(base_interpreter.binary)
        return base_interpreter

    @property
    def identity(self):
        # type: () -> PythonIdentity
        return self._identity

    @property
    def python(self):
        return self._identity.python

    @property
    def version(self):
        return self._identity.version

    @property
    def version_string(self):
        # type: () -> str
        return str(self._identity)

    @property
    def platform(self):
        # type: () -> Platform
        """The most specific platform of this interpreter."""
        return next(self._identity.iter_supported_platforms())

    @property
    def supported_platforms(self):
        """All platforms supported by this interpreter.

        :rtype: frozenset of :class:`Platform`
        """
        if self._supported_platforms is None:
            self._supported_platforms = frozenset(self._identity.iter_supported_platforms())
        return self._supported_platforms

    def create_isolated_cmd(
        self,
        args=None,  # type: Optional[Iterable[str]]
        pythonpath=None,  # type: Optional[Iterable[str]]
        env=None,  # type: Optional[Mapping[str, str]]
    ):
        # type: (...) -> Tuple[Iterable[str], Mapping[str, str]]
        env_copy = dict(env or os.environ)

        if self._identity.configured_macosx_deployment_target:
            # System interpreters on mac have a history of bad configuration from one source or
            # another. See `cls._sanitized_environment` for one example of this.
            #
            # When a Python interpreter is used to build platform specific wheels on a mac, it needs
            # to report a platform of `macosx-X.Y-<machine>` to conform to PEP-425 & PyPAs
            # `packaging` tags library. The X.Y release is derived from the MACOSX_DEPLOYMENT_TARGET
            # sysconfig (Makefile) variable. Sometimes the configuration is provided by a user
            # building a custom Python. See https://github.com/pypa/wheel/issues/385 for an example
            # where MACOSX_DEPLOYMENT_TARGET is set to 11. Other times the configuration is provided
            # by the system maintainer (Apple). See https://github.com/pantsbuild/pants/issues/11061
            # for an example of this via XCode 12s system Python 3.8 interpreter which reports
            # 10.14.6.
            release = self._identity.configured_macosx_deployment_target
            version = release.split(".")
            if len(version) == 1:
                release = "{}.0".format(version[0])
            elif len(version) > 2:
                release = ".".join(version[:2])

            if release != self._identity.configured_macosx_deployment_target:
                osname, _, machine = sysconfig.get_platform().split("-")
                pep425_compatible_platform = "{osname}-{release}-{machine}".format(
                    osname=osname, release=release, machine=machine
                )
                # An undocumented feature of `sysconfig.get_platform()` is respect for the
                # _PYTHON_HOST_PLATFORM environment variable. We can fix up badly configured macOS
                # interpreters by influencing the platform this way, which is enough to get wheels
                # building with proper platform tags. This is supported for the CPythons we support:
                # + https://github.com/python/cpython/blob/v2.7.18/Lib/sysconfig.py#L567-L569
                # ... through ...
                # + https://github.com/python/cpython/blob/v3.9.2/Lib/sysconfig.py#L652-L654
                TRACER.log(
                    "Correcting mis-configured MACOSX_DEPLOYMENT_TARGET of {} to {} corresponding "
                    "to a valid PEP-425 platform of {} for {}.".format(
                        self._identity.configured_macosx_deployment_target,
                        release,
                        pep425_compatible_platform,
                        self,
                    )
                )
                env_copy.update(_PYTHON_HOST_PLATFORM=pep425_compatible_platform)

        return self._create_isolated_cmd(
            self.binary, args=args, pythonpath=pythonpath, env=env_copy
        )

    def execute(
        self,
        args=None,  # type: Optional[Iterable[str]]
        stdin_payload=None,  # type: Optional[AnyStr]
        pythonpath=None,  # type: Optional[Iterable[str]]
        env=None,  # type: Optional[Mapping[str, str]]
        **kwargs  # type: Any
    ):
        # type: (...) -> Tuple[Iterable[str], str, str]
        cmd, env = self.create_isolated_cmd(args=args, pythonpath=pythonpath, env=env)
        stdout, stderr = Executor.execute(cmd, stdin_payload=stdin_payload, env=env, **kwargs)
        return cmd, stdout, stderr

    def open_process(
        self,
        args=None,  # type: Optional[Iterable[str]]
        pythonpath=None,  # type: Optional[Iterable[str]]
        env=None,  # type: Optional[Mapping[str, str]]
        **kwargs  # type: Any
    ):
        # type: (...) -> Tuple[Iterable[str], subprocess.Popen]
        cmd, env = self.create_isolated_cmd(args=args, pythonpath=pythonpath, env=env)
        process = Executor.open_process(cmd, env=env, **kwargs)
        return cmd, process

    def __hash__(self):
        return hash(self._binary)

    def __eq__(self, other):
        if type(other) is not type(self):
            return NotImplemented
        return self._binary == other._binary

    def __repr__(self):
        return "{type}({binary!r}, {identity!r})".format(
            type=self.__class__.__name__, binary=self._binary, identity=self._identity
        )


def spawn_python_job(
    args,  # type: Iterable[str]
    env=None,  # type: Optional[Mapping[str, str]]
    interpreter=None,  # type: Optional[PythonInterpreter]
    expose=None,  # type: Optional[Iterable[str]]
    pythonpath=None,  # type: Optional[Iterable[str]]
    **subprocess_kwargs  # type: Any
):
    # type: (...) -> Job
    """Spawns a python job.

    :param args: The arguments to pass to the python interpreter.
    :param env: The environment to spawn the python interpreter process in. Defaults to the ambient
                environment.
    :param interpreter: The interpreter to use to spawn the python job. Defaults to the current
                        interpreter.
    :param expose: The names of any vendored distributions to expose to the spawned python process.
                   These will be appended to `pythonpath` if passed.
    :param pythonpath: The PYTHONPATH to expose to the spawned python process. These will be
                       pre-pended to the `expose` path if passed.
    :param subprocess_kwargs: Any additional :class:`subprocess.Popen` kwargs to pass through.
    :returns: A job handle to the spawned python process.
    """
    pythonpath = list(pythonpath or ())
    subprocess_env = dict(env or os.environ)
    if expose:
        # In order to expose vendored distributions with their un-vendored import paths in-tact, we
        # need to set `__PEX_UNVENDORED__`. See: vendor.__main__.ImportRewriter._modify_import.
        subprocess_env["__PEX_UNVENDORED__"] = "1"

        pythonpath.extend(third_party.expose(expose))

    interpreter = interpreter or PythonInterpreter.get()
    cmd, process = interpreter.open_process(
        args=args, pythonpath=pythonpath, env=subprocess_env, **subprocess_kwargs
    )
    return Job(command=cmd, process=process)
