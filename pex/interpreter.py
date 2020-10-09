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
from collections import OrderedDict
from textwrap import dedent

from pex import third_party
from pex.common import safe_rmtree
from pex.compatibility import string
from pex.executor import Executor
from pex.jobs import ErrorHandler, Job, Retain, SpawnedJob, execute_parallel
from pex.platforms import Platform
from pex.third_party.packaging import markers, tags
from pex.third_party.pkg_resources import Distribution, Requirement
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING, cast, overload
from pex.util import CacheHelper
from pex.variables import ENV

if TYPE_CHECKING:
    from typing import Callable, Dict, Iterable, Iterator, MutableMapping, Optional, Tuple, Union

    PathFilter = Callable[[str], bool]

    InterpreterIdentificationJobError = Tuple[str, Union[Job.Error, Exception]]
    InterpreterOrJobError = Union["PythonInterpreter", InterpreterIdentificationJobError]

    # N.B.: We convert InterpreterIdentificationJobErrors that result from spawning interpreter
    # identification jobs to these end-user InterpreterIdentificationErrors for display.
    InterpreterIdentificationError = Tuple[str, str]
    InterpreterOrError = Union["PythonInterpreter", InterpreterIdentificationError]


class PythonIdentity(object):
    class Error(Exception):
        pass

    class InvalidError(Error):
        pass

    class UnknownRequirement(Error):
        pass

    # TODO(wickman)  Support interpreter-specific versions, e.g. PyPy-2.2.1
    INTERPRETER_NAME_TO_HASHBANG = {
        "CPython": "python%(major)d.%(minor)d",
        "Jython": "jython",
        "PyPy": "pypy",
        "IronPython": "ipy",
    }

    ABBR_TO_INTERPRETER_NAME = {
        "pp": "PyPy",
        "jy": "Jython",
        "ip": "IronPython",
        "cp": "CPython",
    }

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
        return cls(
            binary=binary or sys.executable,
            python_tag=preferred_tag.interpreter,
            abi_tag=preferred_tag.abi,
            platform_tag=preferred_tag.platform,
            version=sys.version_info[:3],
            supported_tags=supported_tags,
            env_markers=markers.default_environment(),
        )

    @classmethod
    def decode(cls, encoded):
        TRACER.log("creating PythonIdentity from encoded: %s" % encoded, V=9)
        values = json.loads(encoded)
        if len(values) != 7:
            raise cls.InvalidError("Invalid interpreter identity: %s" % encoded)

        supported_tags = values.pop("supported_tags")

        def iter_tags():
            for (interpreter, abi, platform) in supported_tags:
                yield tags.Tag(interpreter=interpreter, abi=abi, platform=platform)

        return cls(supported_tags=iter_tags(), **values)

    @classmethod
    def _find_interpreter_name(cls, python_tag):
        for abbr, interpreter in cls.ABBR_TO_INTERPRETER_NAME.items():
            if python_tag.startswith(abbr):
                return interpreter
        raise ValueError("Unknown interpreter: {}".format(python_tag))

    def __init__(
        self, binary, python_tag, abi_tag, platform_tag, version, supported_tags, env_markers
    ):
        # N.B.: We keep this mapping to support historical values for `distribution` and `requirement`
        # properties.
        self._interpreter_name = self._find_interpreter_name(python_tag)

        self._binary = binary
        self._python_tag = python_tag
        self._abi_tag = abi_tag
        self._platform_tag = platform_tag
        self._version = tuple(version)
        self._supported_tags = tuple(supported_tags)
        self._env_markers = dict(env_markers)

    def encode(self):
        values = dict(
            binary=self._binary,
            python_tag=self._python_tag,
            abi_tag=self._abi_tag,
            platform_tag=self._platform_tag,
            version=self._version,
            supported_tags=[
                (tag.interpreter, tag.abi, tag.platform) for tag in self._supported_tags
            ],
            env_markers=self._env_markers,
        )
        return json.dumps(values, sort_keys=True)

    @property
    def binary(self):
        return self._binary

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
        return self._version

    @property
    def version_str(self):
        # type: () -> str
        return ".".join(map(str, self.version))

    @property
    def supported_tags(self):
        return self._supported_tags

    @property
    def env_markers(self):
        return dict(self._env_markers)

    @property
    def interpreter(self):
        return self._interpreter_name

    @property
    def requirement(self):
        return self.distribution.as_requirement()

    @property
    def distribution(self):
        # type: () -> Distribution
        return Distribution(project_name=self.interpreter, version=self.version_str)

    def iter_supported_platforms(self):
        # type: () -> Iterator[Platform]
        """All platforms supported by the associated interpreter ordered from most specific to
        least."""
        for tags in self._supported_tags:
            yield Platform.from_tags(platform=tags.platform, python=tags.interpreter, abi=tags.abi)

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
        hashbang_string = self.INTERPRETER_NAME_TO_HASHBANG.get(
            self._interpreter_name, "CPython"
        ) % {
            "major": self._version[0],
            "minor": self._version[1],
            "patch": self._version[2],
        }
        return "#!/usr/bin/env %s" % hashbang_string

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
        re.compile(r"jython$"),
        # NB: OSX ships python binaries named Python so we allow for capital-P.
        re.compile(r"[Pp]ython$"),
        re.compile(r"python[23]$"),
        re.compile(r"python[23].[0-9]$"),
        # Some distributions include a suffix on the interpreter name, similar to PEP-3149.
        # For example, Gentoo has /usr/bin/python3.6m to indicate it was built with pymalloc.
        re.compile(r"python[23].[0-9][a-z]$"),
        re.compile(r"pypy$"),
        re.compile(r"pypy-1.[0-9]$"),
    )

    _PYTHON_INTERPRETER_BY_NORMALIZED_PATH = {}  # type: Dict

    @staticmethod
    def _normalize_path(path):
        return os.path.realpath(path)

    class Error(Exception):
        pass

    class IdentificationError(Error):
        pass

    class InterpreterNotFound(Error):
        pass

    @classmethod
    def get(cls):
        return cls.from_binary(sys.executable)

    @staticmethod
    def _paths(paths=None):
        # type: (Optional[Iterable[str]]) -> Iterable[str]
        return paths or os.getenv("PATH", "").split(os.pathsep)

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
        failed_interpreters = OrderedDict()  # type: MutableMapping[str, str]

        def iter_interpreters():
            # type: () -> Iterator[PythonInterpreter]
            for candidate in cls._find(
                cls._paths(paths=paths), path_filter=path_filter, error_handler=Retain()
            ):
                if isinstance(candidate, cls):
                    yield candidate
                else:
                    python, exception = cast("InterpreterIdentificationJobError", candidate)
                    if isinstance(exception, Job.Error):
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
    def _create_isolated_cmd(cls, binary, args=None, pythonpath=None, env=None):
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

    @classmethod
    def _execute(cls, binary, args=None, pythonpath=None, env=None, stdin_payload=None, **kwargs):
        cmd, env = cls._create_isolated_cmd(binary, args=args, pythonpath=pythonpath, env=env)
        stdout, stderr = Executor.execute(cmd, stdin_payload=stdin_payload, env=env, **kwargs)
        return cmd, stdout, stderr

    INTERP_INFO_FILE = "INTERP-INFO"

    @classmethod
    def _spawn_from_binary_external(cls, binary):
        def create_interpreter(stdout, check_binary=False):
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
        path_id = binary.replace(os.sep, ".").lstrip(".")

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
                        sys.stdout.write(encoded_identity)
                        with atomic_directory({cache_dir!r}, exclusive=False) as cache_dir:
                            if cache_dir:
                                with safe_open(os.path.join(cache_dir, {info_file!r}), 'w') as fp:
                                    fp.write(encoded_identity)
                        """.format(
                            binary=binary, cache_dir=cache_dir, info_file=cls.INTERP_INFO_FILE
                        )
                    ),
                ],
                pythonpath=pythonpath,
            )
            process = Executor.open_process(
                cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            job = Job(command=cmd, process=process)
            return SpawnedJob.stdout(job, result_func=create_interpreter)

    @classmethod
    def _expand_path(cls, path):
        if os.path.isfile(path):
            return [path]
        elif os.path.isdir(path):
            return sorted(os.path.join(path, fn) for fn in os.listdir(path))
        return []

    @classmethod
    def from_env(cls, hashbang):
        """Resolve a PythonInterpreter as /usr/bin/env would.

        :param hashbang: A string, e.g. "python3.3" representing some binary on the $PATH.
        :return: the first matching interpreter found or `None`.
        :rtype: :class:`PythonInterpreter`
        """

        def hashbang_matches(fn):
            basefile = os.path.basename(fn)
            return hashbang == basefile

        for interpreter in cls._identify_interpreters(filter=hashbang_matches):
            return interpreter

    @classmethod
    def _spawn_from_binary(cls, binary):
        normalized_binary = cls._normalize_path(binary)
        if not os.path.exists(normalized_binary):
            raise cls.InterpreterNotFound(normalized_binary)

        # N.B.: The cache is written as the last step in PythonInterpreter instance initialization.
        cached_interpreter = cls._PYTHON_INTERPRETER_BY_NORMALIZED_PATH.get(normalized_binary)
        if cached_interpreter is not None:
            return SpawnedJob.completed(cached_interpreter)
        if normalized_binary == cls._normalize_path(sys.executable):
            current_interpreter = cls(PythonIdentity.get())
            return SpawnedJob.completed(current_interpreter)
        return cls._spawn_from_binary_external(normalized_binary)

    @classmethod
    def from_binary(cls, binary):
        # type: (str) -> PythonInterpreter
        """Create an interpreter from the given `binary`.

        :param binary: The path to the python interpreter binary.
        :return: an interpreter created from the given `binary`.
        """
        return cast(PythonInterpreter, cls._spawn_from_binary(binary).await_result())

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
                        yield fn

        results = execute_parallel(
            inputs=list(iter_candidates()),
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
            if version not in seen and version_filter(version):
                seen.add(version)
                yield interp

    @classmethod
    def _sanitized_environment(cls, env=None):
        # N.B. This is merely a hack because sysconfig.py on the default OS X
        # installation of 2.7 breaks.
        env_copy = (env or os.environ).copy()
        env_copy.pop("MACOSX_DEPLOYMENT_TARGET", None)
        return env_copy

    def __init__(self, identity):
        """Construct a PythonInterpreter.

        You should probably use `PythonInterpreter.from_binary` instead.

        :param identity: The :class:`PythonIdentity` of the PythonInterpreter.
        """
        self._identity = identity
        self._binary = self._normalize_path(self.identity.binary)

        self._supported_platforms = None

        self._PYTHON_INTERPRETER_BY_NORMALIZED_PATH[self._binary] = self

    @property
    def binary(self):
        return self._binary

    @property
    def identity(self):
        return self._identity

    @property
    def python(self):
        return self._identity.python

    @property
    def version(self):
        return self._identity.version

    @property
    def version_string(self):
        return str(self._identity)

    @property
    def platform(self):
        """The most specific platform of this interpreter.

        :rtype: :class:`Platform`
        """
        return next(self._identity.iter_supported_platforms())

    @property
    def supported_platforms(self):
        """All platforms supported by this interpreter.

        :rtype: frozenset of :class:`Platform`
        """
        if self._supported_platforms is None:
            self._supported_platforms = frozenset(self._identity.iter_supported_platforms())
        return self._supported_platforms

    def execute(self, args=None, stdin_payload=None, pythonpath=None, env=None, **kwargs):
        return self._execute(
            self.binary,
            args=args,
            stdin_payload=stdin_payload,
            pythonpath=pythonpath,
            env=env,
            **kwargs
        )

    def open_process(self, args=None, pythonpath=None, env=None, **kwargs):
        cmd, env = self._create_isolated_cmd(self.binary, args=args, pythonpath=pythonpath, env=env)
        process = Executor.open_process(cmd, env=env, **kwargs)
        return cmd, process

    def __hash__(self):
        return hash(self._binary)

    def __eq__(self, other):
        if type(other) is not type(self):
            return NotImplemented
        return self._binary == other._binary

    def __lt__(self, other):
        if type(other) is not type(self):
            return NotImplemented
        return self.version < other.version

    def __repr__(self):
        return "{type}({binary!r}, {identity!r})".format(
            type=self.__class__.__name__, binary=self._binary, identity=self._identity
        )


def spawn_python_job(
    args, env=None, interpreter=None, expose=None, pythonpath=None, **subprocess_kwargs
):
    """Spawns a python job.

    :param args: The arguments to pass to the python interpreter.
    :type args: list of str
    :param env: The environment to spawn the python interpreter process in. Defaults to the ambient
                environment.
    :type env: dict of (str, str)
    :param interpreter: The interpreter to use to spawn the python job. Defaults to the current
                        interpreter.
    :type interpreter: :class:`PythonInterpreter`
    :param expose: The names of any vendored distributions to expose to the spawned python process.
                   These will be appended to `pythonpath` if passed.
    :type expose: list of str
    :param pythonpath: The PYTHONPATH to expose to the spawned python process. These will be
                       pre-pended to the `expose` path if passed.
    :type pythonpath: list of str
    :param subprocess_kwargs: Any additional :class:`subprocess.Popen` kwargs to pass through.
    :returns: A job handle to the spawned python process.
    :rtype: :class:`Job`
    """
    pythonpath = list(pythonpath or ())
    if expose:
        subprocess_env = (env or os.environ).copy()
        # In order to expose vendored distributions with their un-vendored import paths in-tact, we
        # need to set `__PEX_UNVENDORED__`. See: vendor.__main__.ImportRewriter._modify_import.
        subprocess_env["__PEX_UNVENDORED__"] = "1"

        pythonpath.extend(third_party.expose(expose))
    else:
        subprocess_env = env

    interpreter = interpreter or PythonInterpreter.get()
    cmd, process = interpreter.open_process(
        args=args, pythonpath=pythonpath, env=subprocess_env, **subprocess_kwargs
    )
    return Job(command=cmd, process=process)
