# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pex import interpreter
from pex.common import temporary_dir, touch
from pex.compatibility import PY3
from pex.interpreter import PythonInterpreter
from pex.testing import (
    PY27,
    PY35,
    PY36,
    ensure_python_distribution,
    ensure_python_interpreter,
    environment_as,
)
from pex.typing import TYPE_CHECKING
from pex.variables import ENV

try:
    from mock import Mock, patch
except ImportError:
    from unittest.mock import Mock, patch  # type: ignore[misc,no-redef,import]

if TYPE_CHECKING:
    from typing import Iterator, Tuple, Union

    InterpreterIdentificationError = Tuple[str, str]
    InterpreterOrError = Union[PythonInterpreter, InterpreterIdentificationError]


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

    TEST_INTERPRETER2_VERSION = PY35
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
            "jython",
            "pypy",
            "pypy-1.1",
            "python",
            "Python",
            "python2",
            "python2.7",
            "python2.7m",
            "python3",
            "python3.6",
            "python3.6m",
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

    def test_pyenv_shims(self):
        # type: () -> None
        py35, _, run_pyenv = ensure_python_distribution(PY35)
        py36, _, _ = ensure_python_distribution(PY36)

        pyenv_root = str(run_pyenv(["root"]).strip())
        pyenv_shims = os.path.join(pyenv_root, "shims")

        def pyenv_global(*versions):
            run_pyenv(["global"] + list(versions))

        def assert_shim(shim_name, expected_binary_path):
            python = PythonInterpreter.from_binary(os.path.join(pyenv_shims, shim_name))
            assert expected_binary_path == python.binary

        with temporary_dir() as pex_root:
            with ENV.patch(PEX_ROOT=pex_root) as pex_env:
                with environment_as(PYENV_ROOT=pyenv_root, **pex_env):
                    pyenv_global(PY35, PY36)
                    assert_shim("python3", py35)

                    pyenv_global(PY36, PY35)
                    # The python3 shim is now pointing at python3.6 but the Pex cache has a valid
                    # entry for the old python3.5 association (the interpreter still exists.)
                    assert_shim("python3", py35)

                    # The shim pointer is now invalid since python3.5 was uninstalled and so should
                    # be re-read.
                    py35_deleted = "{}.uninstalled".format(py35)
                    os.rename(py35, py35_deleted)
                    try:
                        assert_shim("python3", py36)
                    finally:
                        os.rename(py35_deleted, py35)


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
