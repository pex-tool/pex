# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import contextlib
import os
import platform
import random
import subprocess
import sys
from contextlib import contextmanager
from textwrap import dedent

from pex.common import open_zip, safe_mkdir, safe_mkdtemp, safe_rmtree, temporary_dir, touch
from pex.compatibility import to_unicode
from pex.distribution_target import DistributionTarget
from pex.executor import Executor
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.pip import get_pip
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

PY_VER = sys.version_info[:2]
IS_PYPY = hasattr(sys, "pypy_version_info")
NOT_CPYTHON27 = IS_PYPY or PY_VER != (2, 7)
NOT_CPYTHON36 = IS_PYPY or PY_VER != (3, 6)
IS_LINUX = platform.system() == "Linux"
IS_NOT_LINUX = not IS_LINUX
NOT_CPYTHON27_OR_OSX = NOT_CPYTHON27 or IS_NOT_LINUX
NOT_CPYTHON36_OR_LINUX = NOT_CPYTHON36 or IS_LINUX


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
            )
            """
        ),
        "scripts/hello_world": '#!/usr/bin/env python\nprint("hello world!")\n',
        "scripts/shell_script": "#!/usr/bin/env bash\necho hello world\n",
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
    }

    with temporary_content(project_content, interp=interp) as td:
        yield td


class WheelBuilder(object):
    """Create a wheel distribution from an unpacked setup.py-based project."""

    class BuildFailure(Exception):
        pass

    def __init__(self, source_dir, interpreter=None, wheel_dir=None):
        # type: (str, Optional[PythonInterpreter], Optional[str]) -> None
        """Create a wheel from an unpacked source distribution in source_dir."""
        self._source_dir = source_dir
        self._wheel_dir = wheel_dir or safe_mkdtemp()
        self._interpreter = interpreter or PythonInterpreter.get()

    def bdist(self):
        # type: () -> str
        get_pip().spawn_build_wheels(
            distributions=[self._source_dir],
            wheel_dir=self._wheel_dir,
            interpreter=self._interpreter,
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
    interpreter=None,  # type: Optional[PythonInterpreter]
    python_requires=None,  # type: Optional[str]
    **kwargs  # type: Any
):
    # type: (...) -> Iterator[str]
    with make_project(
        name=name,
        version=version,
        zip_safe=zip_safe,
        install_reqs=install_reqs,
        extras_require=extras_require,
        python_requires=python_requires,
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
        get_pip().spawn_install_wheel(
            wheel=dist_location,
            install_dir=install_dir,
            target=DistributionTarget.for_interpreter(interpreter),
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


# TODO(#1041): use `typing.NamedTuple` once we require Python 3.
class IntegResults(object):
    """Convenience object to return integration run results."""

    def __init__(self, output, error, return_code):
        # type: (Text, Text, int) -> None
        super(IntegResults, self).__init__()
        self.output = output
        self.error = error
        self.return_code = return_code

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


def run_pex_command(args, env=None, python=None, quiet=False):
    # type: (Iterable[str], Optional[Dict[str, str]], Optional[str], bool) -> IntegResults
    """Simulate running pex command for integration testing.

    This is different from run_simple_pex in that it calls the pex command rather than running a
    generated pex.  This is useful for testing end to end runs with specific command line arguments
    or env options.
    """
    cmd = [python or sys.executable, "-mpex"]
    if not quiet:
        cmd.append("-vvvvv")
    cmd.extend(args)
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
    safe_rmtree(dest)
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
    # Create an empty file indicating the fingerprint of the correct set of test interpreters.
    touch(os.path.join(dest, _INTERPRETER_SET_FINGERPRINT))


# NB: We keep the pool of bootstrapped interpreters as small as possible to avoid timeouts in CI
# otherwise encountered when fetching and building too many on a cache miss. In the past we had
# issues with the combination of 7 total unique interpreter versions and a Travis-CI timeout of 50
# minutes for a shard.
PY27 = "2.7.15"
PY35 = "3.5.6"
PY36 = "3.6.6"

_VERSIONS = (PY27, PY35, PY36)
# This is the filename of a sentinel file that sits in the pyenv root directory.
# Its purpose is to indicate whether pyenv has the correct interpreters installed
# and will be useful for indicating whether we should trigger a reclone to update
# pyenv.
_INTERPRETER_SET_FINGERPRINT = "_".join(_VERSIONS) + "_pex_fingerprint"


def ensure_python_distribution(version):
    # type: (str) -> Tuple[str, str, Callable[[Iterable[str]], Text]]
    if version not in _VERSIONS:
        raise ValueError("Please constrain version to one of {}".format(_VERSIONS))

    pyenv_root = os.path.join(os.getcwd(), ".pyenv_test")
    interpreter_location = os.path.join(pyenv_root, "versions", version)

    pyenv = os.path.join(pyenv_root, "bin", "pyenv")
    pyenv_env = os.environ.copy()
    pyenv_env["PYENV_ROOT"] = pyenv_root

    pip = os.path.join(interpreter_location, "bin", "pip")

    if not os.path.exists(os.path.join(pyenv_root, _INTERPRETER_SET_FINGERPRINT)):
        bootstrap_python_installer(pyenv_root)

    if not os.path.exists(interpreter_location):
        env = pyenv_env.copy()
        if sys.platform.lower() == "linux":
            env["CONFIGURE_OPTS"] = "--enable-shared"
        subprocess.check_call([pyenv, "install", "--keep", version], env=env)
        subprocess.check_call([pip, "install", "-U", "pip"])

    python = os.path.join(interpreter_location, "bin", "python" + version[0:3])

    def run_pyenv(args):
        # type: (Iterable[str]) -> Text
        return to_unicode(subprocess.check_output([pyenv] + list(args), env=pyenv_env))

    return python, pip, run_pyenv


def ensure_python_interpreter(version):
    # type: (str) -> str
    python, _, _ = ensure_python_distribution(version)
    return python


@contextmanager
def environment_as(**kwargs):
    # type: (**str) -> Iterator[None]
    existing = {key: os.environ.get(key) for key in kwargs}

    def adjust_environment(mapping):
        for key, value in mapping.items():
            if value is not None:
                os.environ[key] = value
            else:
                del os.environ[key]

    adjust_environment(kwargs)
    try:
        yield
    finally:
        adjust_environment(existing)
