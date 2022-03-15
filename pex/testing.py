# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import contextlib
import itertools
import os
import platform
import random
import subprocess
import sys
from contextlib import contextmanager
from textwrap import dedent

from pex.common import (
    atomic_directory,
    open_zip,
    safe_mkdir,
    safe_mkdtemp,
    safe_rmtree,
    safe_sleep,
    temporary_dir,
)
from pex.compatibility import to_unicode
from pex.executor import Executor
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.pip.tool import get_pip
from pex.targets import LocalInterpreter
from pex.third_party.pkg_resources import Distribution
from pex.typing import TYPE_CHECKING
from pex.util import DistributionHelper, named_temporary_file

if TYPE_CHECKING:
    from typing import (
        Any,
        Callable,
        Dict,
        Iterable,
        Iterator,
        List,
        Mapping,
        Optional,
        Set,
        Text,
        Tuple,
        Union,
    )

    import attr  # vendor:skip
else:
    from pex.third_party import attr

PY_VER = sys.version_info[:2]
IS_PYPY = hasattr(sys, "pypy_version_info")
IS_PYPY2 = IS_PYPY and sys.version_info[0] == 2
IS_PYPY3 = IS_PYPY and sys.version_info[0] == 3
NOT_CPYTHON27 = IS_PYPY or PY_VER != (2, 7)
IS_LINUX = platform.system() == "Linux"
IS_MAC = platform.system() == "Darwin"
IS_NOT_LINUX = not IS_LINUX
NOT_CPYTHON27_OR_OSX = NOT_CPYTHON27 or IS_NOT_LINUX


@contextlib.contextmanager
def temporary_filename():
    # type: () -> Iterator[str]
    """Creates a temporary filename.

    This is useful when you need to pass a filename to an API. Windows requires all handles to a
    file be closed before deleting/renaming it, so this makes it a bit simpler.
    """
    with named_temporary_file() as fp:
        fp.write(b"")
        fp.close()
        yield fp.name


def random_bytes(length):
    # type: (int) -> bytes
    return "".join(map(chr, (random.randint(ord("a"), ord("z")) for _ in range(length)))).encode(
        "utf-8"
    )


def get_dep_dist_names_from_pex(pex_path, match_prefix=""):
    # type: (str, str) -> Set[str]
    """Given an on-disk pex, extract all of the unique first-level paths under `.deps`."""
    with open_zip(pex_path) as pex_zip:
        dep_gen = (f.split(os.sep)[1] for f in pex_zip.namelist() if f.startswith(".deps/"))
        return set(item for item in dep_gen if item.startswith(match_prefix))


@contextlib.contextmanager
def temporary_content(content_map, interp=None, seed=31337, perms=0o644):
    # type: (Mapping[str, Union[int, str]], Optional[Dict[str, Any]], int, int) -> Iterator[str]
    """Write content to disk where content is map from string => (int, string).

    If target is int, write int random bytes.  Otherwise write contents of string.
    """
    random.seed(seed)
    interp = interp or {}
    with temporary_dir() as td:
        for filename, size_or_content in content_map.items():
            dest = os.path.join(td, filename)
            safe_mkdir(os.path.dirname(dest))
            with open(dest, "wb") as fp:
                if isinstance(size_or_content, int):
                    fp.write(random_bytes(size_or_content))
                else:
                    fp.write((size_or_content % interp).encode("utf-8"))
            os.chmod(dest, perms)
        yield td


@contextlib.contextmanager
def make_project(
    name="my_project",  # type: str
    version="0.0.0",  # type: str
    zip_safe=True,  # type: bool
    install_reqs=None,  # type: Optional[List[str]]
    extras_require=None,  # type: Optional[Dict[str, List[str]]]
    entry_points=None,  # type: Optional[Union[str, Dict[str, List[str]]]]
    python_requires=None,  # type: Optional[str]
    universal=False,  # type: bool
):
    # type: (...) -> Iterator[str]
    project_content = {
        "setup.py": dedent(
            """
            from setuptools import setup
            
            setup(
            name=%(project_name)r,
            version=%(version)r,
            zip_safe=%(zip_safe)r,
            packages=[%(project_name)r],
            scripts=[
              'scripts/hello_world',
              'scripts/shell_script',
            ],
            package_data={%(project_name)r: ['package_data/*.dat']},
            install_requires=%(install_requires)r,
            extras_require=%(extras_require)r,
            entry_points=%(entry_points)r,
            python_requires=%(python_requires)r,
            options={'bdist_wheel': {'universal': %(universal)r}},
            )
            """
        ),
        "scripts/hello_world": '#!/usr/bin/env python\nprint("hello world from py script!")\n',
        "scripts/shell_script": "#!/usr/bin/env bash\necho hello world from shell script\n",
        os.path.join(name, "__init__.py"): 0,
        os.path.join(name, "my_module.py"): 'def do_something():\n  print("hello world!")\n',
        os.path.join(name, "package_data/resource1.dat"): 1000,
        os.path.join(name, "package_data/resource2.dat"): 1000,
    }  # type: Dict[str, Union[str, int]]

    interp = {
        "project_name": name,
        "version": version,
        "zip_safe": zip_safe,
        "install_requires": install_reqs or [],
        "extras_require": extras_require or {},
        "entry_points": entry_points or {},
        "python_requires": python_requires,
        "universal": universal,
    }

    with temporary_content(project_content, interp=interp) as td:
        yield td


class WheelBuilder(object):
    """Create a wheel distribution from an unpacked setup.py-based project."""

    class BuildFailure(Exception):
        pass

    def __init__(
        self,
        source_dir,  # type: str
        interpreter=None,  # type: Optional[PythonInterpreter]
        wheel_dir=None,  # type: Optional[str]
        verify=True,  # type: bool
    ):
        # type: (...) -> None
        """Create a wheel from an unpacked source distribution in source_dir."""
        self._source_dir = source_dir
        self._wheel_dir = wheel_dir or safe_mkdtemp()
        self._interpreter = interpreter or PythonInterpreter.get()
        self._verify = verify

    def bdist(self):
        # type: () -> str
        get_pip(interpreter=self._interpreter).spawn_build_wheels(
            distributions=[self._source_dir],
            wheel_dir=self._wheel_dir,
            interpreter=self._interpreter,
            verify=self._verify,
        ).wait()
        dists = os.listdir(self._wheel_dir)
        if len(dists) == 0:
            raise self.BuildFailure("No distributions were produced!")
        if len(dists) > 1:
            raise self.BuildFailure("Ambiguous source distributions found: %s" % (" ".join(dists)))
        return os.path.join(self._wheel_dir, dists[0])


@contextlib.contextmanager
def built_wheel(
    name="my_project",  # type: str
    version="0.0.0",  # type: str
    zip_safe=True,  # type: bool
    install_reqs=None,  # type: Optional[List[str]]
    extras_require=None,  # type: Optional[Dict[str, List[str]]]
    entry_points=None,  # type: Optional[Union[str, Dict[str, List[str]]]]
    interpreter=None,  # type: Optional[PythonInterpreter]
    python_requires=None,  # type: Optional[str]
    universal=False,  # type: bool
    **kwargs  # type: Any
):
    # type: (...) -> Iterator[str]
    with make_project(
        name=name,
        version=version,
        zip_safe=zip_safe,
        install_reqs=install_reqs,
        extras_require=extras_require,
        entry_points=entry_points,
        python_requires=python_requires,
        universal=universal,
    ) as td:
        builder = WheelBuilder(td, interpreter=interpreter, **kwargs)
        yield builder.bdist()


@contextlib.contextmanager
def make_source_dir(
    name="my_project",  # type: str
    version="0.0.0",  # type: str
    install_reqs=None,  # type: Optional[List[str]]
    extras_require=None,  # type: Optional[Dict[str, List[str]]]
):
    # type: (...) -> Iterator[str]
    with make_project(
        name=name, version=version, install_reqs=install_reqs, extras_require=extras_require
    ) as td:
        yield td


@contextlib.contextmanager
def make_bdist(
    name="my_project",  # type: str
    version="0.0.0",  # type: str
    zip_safe=True,  # type: bool
    interpreter=None,  # type: Optional[PythonInterpreter]
    **kwargs  # type: Any
):
    # type: (...) -> Iterator[Distribution]
    with built_wheel(
        name=name, version=version, zip_safe=zip_safe, interpreter=interpreter, **kwargs
    ) as dist_location:

        install_dir = os.path.join(safe_mkdtemp(), os.path.basename(dist_location))
        get_pip(interpreter=interpreter).spawn_install_wheel(
            wheel=dist_location,
            install_dir=install_dir,
            target=LocalInterpreter.create(interpreter),
        ).wait()
        dist = DistributionHelper.distribution_from_path(install_dir)
        assert dist is not None
        yield dist


COVERAGE_PREAMBLE = """
try:
  from coverage import coverage
  cov = coverage(auto_data=True, data_suffix=True)
  cov.start()
except ImportError:
  pass
"""


def write_simple_pex(
    td,  # type: str
    exe_contents=None,  # type: Optional[str]
    dists=None,  # type: Optional[Iterable[Distribution]]
    sources=None,  # type: Optional[Iterable[Tuple[str, str]]]
    coverage=False,  # type: bool
    interpreter=None,  # type: Optional[PythonInterpreter]
    pex_info=None,  # type: Optional[PexInfo]
):
    # type: (...) -> PEXBuilder
    """Write a pex file that optionally contains an executable entry point.

    :param td: temporary directory path
    :param exe_contents: entry point python file
    :param dists: distributions to include, typically sdists or bdists
    :param sources: sources to include, as a list of pairs (env_filename, contents)
    :param coverage: include coverage header
    :param interpreter: a custom interpreter to use to build the pex
    :param pex_info: a custom PexInfo to use to build the pex.
    """
    dists = dists or []
    sources = sources or []

    safe_mkdir(td)

    pb = PEXBuilder(
        path=td,
        preamble=COVERAGE_PREAMBLE if coverage else None,
        interpreter=interpreter,
        pex_info=pex_info,
    )

    for dist in dists:
        pb.add_dist_location(dist.location if isinstance(dist, Distribution) else dist)

    for env_filename, contents in sources:
        src_path = os.path.join(td, env_filename)
        safe_mkdir(os.path.dirname(src_path))
        with open(src_path, "w") as fp:
            fp.write(contents)
        pb.add_source(src_path, env_filename)

    if exe_contents:
        with open(os.path.join(td, "exe.py"), "w") as fp:
            fp.write(exe_contents)
        pb.set_executable(os.path.join(td, "exe.py"))

    pb.freeze()

    return pb


@attr.s(frozen=True)
class IntegResults(object):
    """Convenience object to return integration run results."""

    output = attr.ib()  # type: Text
    error = attr.ib()  # type: Text
    return_code = attr.ib()  # type: int

    def assert_success(self):
        # type: () -> None
        assert (
            self.return_code == 0
        ), "integration test failed: return_code={}, output={}, error={}".format(
            self.return_code, self.output, self.error
        )

    def assert_failure(self):
        # type: () -> None
        assert self.return_code != 0


def create_pex_command(
    args=None,  # type: Optional[Iterable[str]]
    python=None,  # type: Optional[str]
    quiet=False,  # type: bool
):
    # type: (...) -> List[str]
    cmd = [python or sys.executable, "-mpex"]
    if not quiet:
        cmd.append("-vvvvv")
    if args:
        cmd.extend(args)
    return cmd


def run_pex_command(
    args,  # type: Iterable[str]
    env=None,  # type: Optional[Dict[str, str]]
    python=None,  # type: Optional[str]
    quiet=False,  # type: bool
):
    # type: (...) -> IntegResults
    """Simulate running pex command for integration testing.

    This is different from run_simple_pex in that it calls the pex command rather than running a
    generated pex.  This is useful for testing end to end runs with specific command line arguments
    or env options.
    """
    cmd = create_pex_command(args, python=python, quiet=quiet)
    process = Executor.open_process(
        cmd=cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    output, error = process.communicate()
    return IntegResults(output.decode("utf-8"), error.decode("utf-8"), process.returncode)


def run_simple_pex(
    pex,  # type: str
    args=(),  # type: Iterable[str]
    interpreter=None,  # type: Optional[PythonInterpreter]
    stdin=None,  # type: Optional[bytes]
    **kwargs  # type: Any
):
    # type: (...) -> Tuple[bytes, int]
    p = PEX(pex, interpreter=interpreter)
    process = p.run(
        args=args,
        blocking=False,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **kwargs
    )
    stdout, _ = process.communicate(input=stdin)
    return stdout.replace(b"\r", b""), process.returncode


def run_simple_pex_test(
    body,  # type: str
    args=(),  # type: Iterable[str]
    env=None,  # type: Optional[Mapping[str, str]]
    dists=None,  # type: Optional[Iterable[Distribution]]
    coverage=False,  # type: bool
    interpreter=None,  # type: Optional[PythonInterpreter]
):
    # type: (...) -> Tuple[bytes, int]
    with temporary_dir() as td1, temporary_dir() as td2:
        pb = write_simple_pex(td1, body, dists=dists, coverage=coverage, interpreter=interpreter)
        pex = os.path.join(td2, "app.pex")
        pb.build(pex)
        return run_simple_pex(pex, args=args, env=env, interpreter=interpreter)


def bootstrap_python_installer(dest):
    # type: (str) -> None
    for _ in range(3):
        try:
            subprocess.check_call(["git", "clone", "https://github.com/pyenv/pyenv.git", dest])
        except subprocess.CalledProcessError as e:
            print("caught exception: %r" % e)
            continue
        else:
            break
    else:
        raise RuntimeError("Helper method could not clone pyenv from git after 3 tries")


# NB: We keep the pool of bootstrapped interpreters as small as possible to avoid timeouts in CI
# otherwise encountered when fetching and building too many on a cache miss. In the past we had
# issues with the combination of 7 total unique interpreter versions and a Travis-CI timeout of 50
# minutes for a shard.
PY27 = "2.7.18"
PY37 = "3.7.11"
PY310 = "3.10.1"

ALL_PY_VERSIONS = (PY27, PY37, PY310)
_ALL_PY3_VERSIONS = (PY37, PY310)


def ensure_python_distribution(version):
    # type: (str) -> Tuple[str, str, Callable[[Iterable[str]], Text]]
    if version not in ALL_PY_VERSIONS:
        raise ValueError("Please constrain version to one of {}".format(ALL_PY_VERSIONS))

    pyenv_root = os.path.abspath(
        os.path.join(
            os.path.expanduser(os.environ.get("_PEX_TEST_PYENV_ROOT", "~/.pex_dev")),
            "pyenv",
        )
    )
    interpreter_location = os.path.join(pyenv_root, "versions", version)

    pyenv = os.path.join(pyenv_root, "bin", "pyenv")
    pyenv_env = os.environ.copy()
    pyenv_env["PYENV_ROOT"] = pyenv_root

    pip = os.path.join(interpreter_location, "bin", "pip")

    with atomic_directory(target_dir=os.path.join(pyenv_root), exclusive=True) as target_dir:
        if not target_dir.is_finalized():
            bootstrap_python_installer(target_dir.work_dir)

    with atomic_directory(
        target_dir=interpreter_location, exclusive=True
    ) as interpreter_target_dir:
        if not interpreter_target_dir.is_finalized():
            subprocess.check_call(
                [
                    "git",
                    "--git-dir={}".format(os.path.join(pyenv_root, ".git")),
                    "--work-tree={}".format(pyenv_root),
                    "pull",
                    "--ff-only",
                    "https://github.com/pyenv/pyenv.git",
                ]
            )
            env = pyenv_env.copy()
            if sys.platform.lower().startswith("linux"):
                env["CONFIGURE_OPTS"] = "--enable-shared"
                # The pyenv builder detects `--enable-shared` and sets up `RPATH` via
                # `LDFLAGS=-Wl,-rpath=... $LDFLAGS` to ensure the built python binary links the
                # correct libpython shared lib. Some versions of compiler set the `RUNPATH` instead
                # though which is searched _after_ the `LD_LIBRARY_PATH` environment variable. To
                # ensure an inopportune `LD_LIBRARY_PATH` doesn't fool the pyenv python binary into
                # linking the wrong libpython, force `RPATH`, which is searched 1st by the linker,
                # with with `--disable-new-dtags`.
                env["LDFLAGS"] = "-Wl,--disable-new-dtags"
            subprocess.check_call([pyenv, "install", "--keep", version], env=env)
            subprocess.check_call([pip, "install", "-U", "pip"])

    major, minor = version.split(".")[:2]
    python = os.path.join(
        interpreter_location, "bin", "python{major}.{minor}".format(major=major, minor=minor)
    )

    def run_pyenv(args):
        # type: (Iterable[str]) -> Text
        return to_unicode(subprocess.check_output([pyenv] + list(args), env=pyenv_env))

    return python, pip, run_pyenv


def ensure_python_venv(version, latest_pip=True, system_site_packages=False):
    python, pip, _ = ensure_python_distribution(version)
    venv = safe_mkdtemp()
    if version in _ALL_PY3_VERSIONS:
        args = [python, "-m", "venv", venv]
        if system_site_packages:
            args.append("--system-site-packages")
        subprocess.check_call(args=args)
    else:
        subprocess.check_call(args=[pip, "install", "virtualenv==16.7.10"])
        args = [python, "-m", "virtualenv", venv, "-q"]
        if system_site_packages:
            args.append("--system-site-packages")
        subprocess.check_call(args=args)
    python, pip = tuple(os.path.join(venv, "bin", exe) for exe in ("python", "pip"))
    if latest_pip:
        subprocess.check_call(args=[pip, "install", "-U", "pip"])
    return python, pip


def ensure_python_interpreter(version):
    # type: (str) -> str
    python, _, _ = ensure_python_distribution(version)
    return python


@contextmanager
def environment_as(**kwargs):
    # type: (**Any) -> Iterator[None]
    existing = {key: os.environ.get(key) for key in kwargs}

    def adjust_environment(mapping):
        for key, value in mapping.items():
            if value is not None:
                os.environ[key] = str(value)
            else:
                os.environ.pop(key, None)

    adjust_environment(kwargs)
    try:
        yield
    finally:
        adjust_environment(existing)


@contextmanager
def pushd(directory):
    # type: (str) -> Iterator[None]
    cwd = os.getcwd()
    try:
        os.chdir(directory)
        yield
    finally:
        os.chdir(cwd)


def make_env(**kwargs):
    # type: (**Any) -> Dict[str, str]
    """Create a copy of the current environment with the given modifications.

    The given kwargs add to or update the environment when they have a non-`None` value. When they
    have a `None` value, the environment variable is removed from the environment.

    All non-`None` values are converted to strings by apply `str`.
    """
    env = os.environ.copy()
    env.update((k, str(v)) for k, v in kwargs.items() if v is not None)
    for k, v in kwargs.items():
        if v is None:
            env.pop(k, None)
    return env


def run_commands_with_jitter(
    commands,  # type: Iterable[Iterable[str]]
    path_argument,  # type: str
    extra_env=None,  # type: Optional[Mapping[str, str]]
    delay=2.0,  # type: float
):
    # type: (...) -> List[str]
    """Runs the commands with tactics that attempt to introduce randomness in outputs.

    Each command will run against a clean Pex cache with a unique path injected as the value for
    `path_argument`. A unique `PYTHONHASHSEED` is set in the environment for each execution as well.

    Additionally, a delay is inserted between executions. By default, this delay is 2s to ensure zip
    precision is stressed. See: https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT.
    """
    td = safe_mkdtemp()
    pex_root = os.path.join(td, "pex_root")

    paths = []
    for index, command in enumerate(commands):
        path = os.path.join(td, str(index))
        cmd = list(command) + [path_argument, path]

        # Note that we change the `PYTHONHASHSEED` to ensure that there are no issues resulting
        # from the random seed, such as data structures, as Tox sets this value by default.
        # See:
        # https://tox.readthedocs.io/en/latest/example/basic.html#special-handling-of-pythonhashseed
        env = make_env(PEX_ROOT=pex_root, PYTHONHASHSEED=(index * 497) + 4)
        if extra_env:
            env.update(extra_env)

        if index > 0:
            safe_sleep(delay)

        # Ensure the PEX is fully rebuilt.
        safe_rmtree(pex_root)
        subprocess.check_call(args=cmd, env=env)
        paths.append(path)
    return paths


def run_command_with_jitter(
    args,  # type: Iterable[str]
    path_argument,  # type: str
    extra_env=None,  # type: Optional[Mapping[str, str]]
    delay=2.0,  # type: float
    count=3,  # type: int
):
    # type: (...) -> List[str]
    """Runs the command `count` times in an attempt to introduce randomness.

    Each run of the command will run against a clean Pex cache with a unique path injected as the
    value for `path_argument`. A unique `PYTHONHASHSEED` is set in the environment for each
    execution as well.

    Additionally, a delay is inserted between executions. By default, this delay is 2s to ensure zip
    precision is stressed. See: https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT.
    """
    return run_commands_with_jitter(
        commands=list(itertools.repeat(list(args), count)),
        path_argument=path_argument,
        extra_env=extra_env,
        delay=delay,
    )


def pex_project_dir():
    # type: () -> str
    return str(
        subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode("ascii").strip()
    )
