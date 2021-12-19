# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import glob
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from contextlib import contextmanager
from textwrap import dedent

import pytest

from pex import interpreter
from pex.common import chmod_plus_x, safe_mkdir, safe_mkdtemp, temporary_dir, touch
from pex.compatibility import PY3
from pex.executor import Executor
from pex.interpreter import PythonInterpreter
from pex.jobs import Job
from pex.pyenv import Pyenv
from pex.testing import (
    PY27,
    PY37,
    PY310,
    PY_VER,
    ensure_python_distribution,
    ensure_python_interpreter,
    ensure_python_venv,
    environment_as,
    pushd,
)
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

try:
    from unittest.mock import Mock, patch  # type: ignore[import]
except ImportError:
    from mock import Mock, patch  # type: ignore[misc,import]

if TYPE_CHECKING:
    from typing import Any, Iterator, List, Tuple

    from pex.interpreter import InterpreterOrError


def tuple_from_version(version_string):
    # type: (str) -> Tuple[int, ...]
    return tuple(int(component) for component in version_string.split("."))


class TestPythonInterpreter(object):
    def test_all_does_not_raise_with_empty_path_envvar(self):
        # type: () -> None
        """additionally, tests that the module does not raise at import."""
        with patch.dict(os.environ, clear=True):
            if PY3:
                import importlib

                importlib.reload(interpreter)
            else:
                reload(interpreter)
            PythonInterpreter.all()

    TEST_INTERPRETER1_VERSION = PY27
    TEST_INTERPRETER1_VERSION_TUPLE = tuple_from_version(TEST_INTERPRETER1_VERSION)

    TEST_INTERPRETER2_VERSION = PY37
    TEST_INTERPRETER2_VERSION_TUPLE = tuple_from_version(TEST_INTERPRETER2_VERSION)

    @pytest.fixture
    def test_interpreter1(self):
        # type: () -> str
        return ensure_python_interpreter(self.TEST_INTERPRETER1_VERSION)

    @pytest.fixture
    def test_interpreter2(self):
        # type: () -> str
        return ensure_python_interpreter(self.TEST_INTERPRETER2_VERSION)

    def test_interpreter_versioning(self, test_interpreter1):
        # type: (str) -> None
        py_interpreter = PythonInterpreter.from_binary(test_interpreter1)
        assert py_interpreter.identity.version == self.TEST_INTERPRETER1_VERSION_TUPLE

    def test_interpreter_caching(self, test_interpreter1, test_interpreter2):
        # type: (str, str) -> None
        py_interpreter1 = PythonInterpreter.from_binary(test_interpreter1)
        py_interpreter2 = PythonInterpreter.from_binary(test_interpreter2)
        assert py_interpreter1 is not py_interpreter2
        assert py_interpreter2.identity.version == self.TEST_INTERPRETER2_VERSION_TUPLE

        py_interpreter3 = PythonInterpreter.from_binary(test_interpreter1)
        assert py_interpreter1 is py_interpreter3

    def test_nonexistent_interpreter(self):
        # type: () -> None
        with pytest.raises(PythonInterpreter.InterpreterNotFound):
            PythonInterpreter.from_binary("/nonexistent/path")

    def test_binary_name_matching(self):
        # type: () -> None
        valid_binary_names = (
            "Python",
            "pypy",
            "pypy2",
            "pypy3",
            "pypy3.6",
            "pypy3.6m",
            "python",
            "python2",
            "python2.7",
            "python2.7m",
            "python3",
            "python3.6",
            "python3.6m",
            "python3.10",
            "python3.10m",
            "python3.99",
            "python3.99m",
            "python3.123",
            "python3.123m",
        )

        matches = PythonInterpreter._matches_binary_name
        for name in valid_binary_names:
            assert matches(name), "Expected {} to be valid binary name".format(name)

    def test_iter_interpreter_some(self, test_interpreter1, test_interpreter2):
        # type: (str, str) -> None
        assert [
            PythonInterpreter.from_binary(test_interpreter1),
            PythonInterpreter.from_binary(test_interpreter2),
        ] == list(PythonInterpreter.iter_candidates(paths=[test_interpreter1, test_interpreter2]))

    def test_iter_interpreter_none(self):
        # type: () -> None
        assert [] == list(PythonInterpreter.iter_candidates(paths=[os.devnull]))

    def test_iter_candidates_empty_paths(self, test_interpreter1):
        # type: (str) -> None
        # Whereas `paths=None` should inspect $PATH, `paths=[]` means to search nothing.
        with environment_as(PATH=test_interpreter1):
            assert [] == list(PythonInterpreter.iter_candidates(paths=[]))
            assert [PythonInterpreter.from_binary(test_interpreter1)] == list(
                PythonInterpreter.iter_candidates(paths=None)
            )

    @pytest.fixture
    def invalid_interpreter(self):
        # type: () -> Iterator[str]
        with temporary_dir() as bin_dir:
            invalid_interpreter = os.path.join(bin_dir, "python")
            touch(invalid_interpreter)
            yield invalid_interpreter

    def assert_error(self, result, expected_python):
        # type: (InterpreterOrError, str) -> None
        assert isinstance(result, tuple)
        python, error_message = result
        assert expected_python == python
        assert isinstance(error_message, str)
        assert len(error_message) > 0

    def test_iter_interpreter_errors(self, invalid_interpreter):
        # type: (str) -> None
        results = list(PythonInterpreter.iter_candidates(paths=[invalid_interpreter]))

        assert len(results) == 1
        self.assert_error(results[0], invalid_interpreter)

    def test_iter_interpreter_mixed(
        self, test_interpreter1, test_interpreter2, invalid_interpreter
    ):
        # type: (str, str, str) -> None
        results = list(
            PythonInterpreter.iter_candidates(
                paths=[test_interpreter1, invalid_interpreter, test_interpreter2]
            )
        )

        assert len(results) == 3
        assert [
            PythonInterpreter.from_binary(path) for path in (test_interpreter1, test_interpreter2)
        ] == [result for result in results if isinstance(result, PythonInterpreter)]
        errors = [result for result in results if not isinstance(result, PythonInterpreter)]
        assert len(errors) == 1
        self.assert_error(errors[0], invalid_interpreter)

    def test_iter_interpreter_path_filter(self, test_interpreter1, test_interpreter2):
        # type: (str, str) -> None
        assert [PythonInterpreter.from_binary(test_interpreter2)] == list(
            PythonInterpreter.iter_candidates(
                paths=[test_interpreter1, test_interpreter2],
                path_filter=lambda path: path == test_interpreter2,
            )
        )

    def test_iter_interpreter_path_filter_symlink(self, test_interpreter1, test_interpreter2):
        # type: (str, str) -> None
        with temporary_dir() as bin_dir:
            os.symlink(test_interpreter2, os.path.join(bin_dir, "jake"))

            # Verify path filtering happens before interpreter resolution, which os.path.realpaths
            # the interpreter binary. This supports specifying a path filter like
            # "basename is python2" where discovered interpreter binaries are symlinks to more
            # specific interpreter versions, e.g.: /usr/bin/python2 -> /usr/bin/python2.7.
            expected_interpreter = PythonInterpreter.from_binary(test_interpreter2)
            assert [expected_interpreter] == list(
                PythonInterpreter.iter_candidates(
                    paths=[test_interpreter1, bin_dir],
                    path_filter=lambda path: os.path.basename(path) == "jake",
                )
            )
            assert os.path.basename(expected_interpreter.binary) != "jake"

    def test_pyenv_shims(self, tmpdir):
        # type: (Any) -> None
        py37, _, run_pyenv = ensure_python_distribution(PY37)
        py310 = ensure_python_interpreter(PY310)

        pyenv_root = str(run_pyenv(["root"]).strip())
        pyenv_shims = os.path.join(pyenv_root, "shims")

        def pyenv_global(*versions):
            # type: (*str) -> None
            run_pyenv(["global"] + list(versions))

        def pyenv_local(*versions):
            # type: (*str) -> None
            run_pyenv(["local"] + list(versions))

        @contextmanager
        def pyenv_shell(*versions):
            # type: (*str) -> Iterator[None]
            with environment_as(PYENV_VERSION=":".join(versions)):
                yield

        pex_root = os.path.join(str(tmpdir), "pex_root")
        cwd = safe_mkdir(os.path.join(str(tmpdir), "home", "jake", "project"))
        with ENV.patch(PEX_ROOT=pex_root) as pex_env, environment_as(
            PYENV_ROOT=pyenv_root, PEX_PYTHON_PATH=pyenv_shims, **pex_env
        ), pyenv_shell(), pushd(cwd):
            pyenv = Pyenv.find()
            assert pyenv is not None
            assert pyenv_root == pyenv.root

            def interpreter_for_shim(shim_name):
                # type: (str) -> PythonInterpreter
                binary = os.path.join(pyenv_shims, shim_name)
                return PythonInterpreter.from_binary(binary, pyenv=pyenv)

            def assert_shim(
                shim_name,  # type: str
                expected_binary_path,  # type: str
            ):
                # type: (...) -> None
                python = interpreter_for_shim(shim_name)
                assert expected_binary_path == python.binary

            def assert_shim_inactive(shim_name):
                # type: (str) -> None
                with pytest.raises(PythonInterpreter.IdentificationError):
                    interpreter_for_shim(shim_name)

            pyenv_global(PY37, PY310)
            assert_shim("python", py37)
            assert_shim("python3", py37)
            assert_shim("python3.7", py37)
            assert_shim("python3.10", py310)

            pyenv_global(PY310, PY37)
            assert_shim("python", py310)
            assert_shim("python3", py310)
            assert_shim("python3.10", py310)
            assert_shim("python3.7", py37)

            pyenv_local(PY37)
            assert_shim("python", py37)
            assert_shim("python3", py37)
            assert_shim("python3.7", py37)
            assert_shim_inactive("python3.8")

            with pyenv_shell(PY310):
                assert_shim("python", py310)
                assert_shim("python3", py310)
                assert_shim("python3.10", py310)
                assert_shim_inactive("python3.7")

            with pyenv_shell(PY37, PY310):
                assert_shim("python", py37)
                assert_shim("python3", py37)
                assert_shim("python3.7", py37)
                assert_shim("python3.10", py310)

            # The shim pointer is now invalid since python3.7 was uninstalled and so
            # should be re-read and found invalid.
            py37_version_dir = os.path.dirname(os.path.dirname(py37))
            py37_deleted = "{}.uninstalled".format(py37_version_dir)
            os.rename(py37_version_dir, py37_deleted)
            try:
                assert_shim_inactive("python")
                assert_shim_inactive("python3")
                assert_shim_inactive("python3.7")
            finally:
                os.rename(py37_deleted, py37_version_dir)

            assert_shim("python", py37)


def test_latest_release_of_min_compatible_version():
    # type: () -> None
    def mock_interp(version):
        interp = Mock()
        interp.version = tuple(int(v) for v in version.split("."))
        return interp

    def assert_chosen(expected_version, other_version):
        expected = mock_interp(expected_version)
        other = mock_interp(other_version)
        assert (
            PythonInterpreter.latest_release_of_min_compatible_version([expected, other])
            == expected
        ), "{} was selected instead of {}".format(other_version, expected_version)

    # Note that we don't consider the interpreter name in comparisons.
    assert_chosen(expected_version="2.7.0", other_version="3.6.0")
    assert_chosen(expected_version="3.5.0", other_version="3.6.0")
    assert_chosen(expected_version="3.6.1", other_version="3.6.0")


def test_detect_pyvenv(tmpdir):
    # type: (Any) -> None
    venv = str(tmpdir)
    py37 = ensure_python_interpreter(PY37)
    real_interpreter = PythonInterpreter.from_binary(py37)
    real_interpreter.execute(["-m", "venv", venv])
    with pytest.raises(Executor.NonZeroExit):
        real_interpreter.execute(["-c", "import colors"])

    venv_bin_dir = os.path.join(venv, "bin")
    subprocess.check_call([os.path.join(venv_bin_dir, "pip"), "install", "ansicolors==1.1.8"])

    canonical_to_python = defaultdict(set)
    for python in glob.glob(os.path.join(venv_bin_dir, "python*")):
        venv_interpreter = PythonInterpreter.from_binary(python)
        canonical_to_python[venv_interpreter.binary].add(python)
        venv_interpreter.execute(["-c", "import colors"])

    assert (
        len(canonical_to_python) == 1
    ), "Expected exactly one canonical venv python, found: {}".format(canonical_to_python)
    canonical, pythons = canonical_to_python.popitem()

    real_python = os.path.realpath(py37)
    assert canonical != real_python
    assert os.path.dirname(canonical) == venv_bin_dir
    assert os.path.realpath(canonical) == real_python
    assert len(pythons) >= 2, "Expected at least two virtualenv python binaries, found: {}".format(
        pythons
    )


def check_resolve_venv(real_interpreter):
    # type: (PythonInterpreter) -> None
    tmpdir = safe_mkdtemp()

    def create_venv(
        interpreter,  # type: PythonInterpreter
        rel_path,  # type: str
    ):
        # type: (...) -> List[str]
        venv_dir = os.path.join(tmpdir, rel_path)
        interpreter.execute(["-m", "venv", venv_dir])
        return glob.glob(os.path.join(venv_dir, "bin", "python*"))

    assert not real_interpreter.is_venv
    assert real_interpreter is real_interpreter.resolve_base_interpreter()

    for index, python in enumerate(create_venv(real_interpreter, "first-level")):
        venv_interpreter = PythonInterpreter.from_binary(python)
        assert venv_interpreter.is_venv
        assert venv_interpreter != real_interpreter.binary
        assert real_interpreter == venv_interpreter.resolve_base_interpreter()

        for nested_python in create_venv(venv_interpreter, "second-level{}".format(index)):
            nested_venv_interpreter = PythonInterpreter.from_binary(nested_python)
            assert nested_venv_interpreter.is_venv
            assert nested_venv_interpreter != venv_interpreter
            assert nested_venv_interpreter != real_interpreter
            assert real_interpreter == nested_venv_interpreter.resolve_base_interpreter()


def test_resolve_venv():
    # type: () -> None
    real_interpreter = PythonInterpreter.from_binary(ensure_python_interpreter(PY37))
    check_resolve_venv(real_interpreter)


@pytest.mark.skipif(
    PY_VER < (3, 0), reason="Test requires the venv module which is not present in Python 2."
)
def test_resolve_venv_ambient():
    # type: () -> None
    ambient_real_interpreter = PythonInterpreter.get().resolve_base_interpreter()
    check_resolve_venv(ambient_real_interpreter)


def test_identify_cwd_isolation_issues_1231(tmpdir):
    # type: (Any) -> None

    python37, pip = ensure_python_venv(PY37)
    polluted_cwd = os.path.join(str(tmpdir), "dir")
    subprocess.check_call(args=[pip, "install", "--target", polluted_cwd, "pex==2.1.16"])

    pex_root = os.path.join(str(tmpdir), "pex_root")
    with pushd(polluted_cwd), ENV.patch(PEX_ROOT=pex_root):
        interp = PythonInterpreter.from_binary(python37)

    interp_info_files = {
        os.path.join(root, f)
        for root, _, files in os.walk(pex_root)
        for f in files
        if f == PythonInterpreter.INTERP_INFO_FILE
    }
    assert 1 == len(interp_info_files)
    with open(interp_info_files.pop()) as fp:
        assert interp.binary == json.load(fp)["binary"]


@pytest.fixture(scope="module")
def macos_monterey_interpeter(tmpdir_factory):
    # type: (Any) -> str
    pythonwrapper = os.path.join(str(tmpdir_factory.mktemp("bin")), "pythonwrapper")
    with open(pythonwrapper, "w") as fp:
        fp.write(
            dedent(
                """\
                #!/usr/bin/env bash
                echo >&2 "pythonwrapper[3129:20922] \\
                pythonwrapper is not supposed to be executed directly. Exiting."
                exit 0
                """
            )
        )
    chmod_plus_x(pythonwrapper)

    python = os.path.join(str(tmpdir_factory.mktemp("bin")), "python")
    os.symlink(pythonwrapper, python)
    return python


def test_issue_1494_job_error_not_identification_error(
    macos_monterey_interpeter,  # type: str
    tmpdir,  # type: Any
):
    # type: (...) -> None
    pex_root = os.path.join(str(tmpdir), "pex_root")
    with ENV.patch(PEX_ROOT=pex_root):
        spawned_job = PythonInterpreter._spawn_from_binary(macos_monterey_interpeter)
        with pytest.raises(Job.Error) as exc_info:
            spawned_job.await_result()
        exc_info.match(
            r"^Expected job to create file '{}/interpreters/[0-9a-f/]+/INTERP-INFO' "
            r"but it did not exist or could not be read: ".format(re.escape(pex_root))
        )
        exc_info.match(
            r"\n"
            r"STDERR:\n"
            r"pythonwrapper\[3129:20922\] "
            r"pythonwrapper is not supposed to be executed directly. Exiting.\n$"
        )


def test_issue_1494_iter(macos_monterey_interpeter):
    # type: (str) -> None
    assert [PythonInterpreter.get()] == list(
        PythonInterpreter.iter(paths=[sys.executable, macos_monterey_interpeter])
    )


def test_issue_1494_iter_candidates(macos_monterey_interpeter):
    # type: (str) -> None
    assert [
        PythonInterpreter.get(),
        (
            macos_monterey_interpeter,
            "pythonwrapper[3129:20922] pythonwrapper is not supposed to be executed directly. "
            "Exiting.",
        ),
    ] == list(PythonInterpreter.iter_candidates(paths=[sys.executable, macos_monterey_interpeter]))
