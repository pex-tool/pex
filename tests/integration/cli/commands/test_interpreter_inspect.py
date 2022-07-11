# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os

from pex.cli.testing import run_pex3
from pex.interpreter import PythonInterpreter
from pex.pep_425 import CompatibilityTags
from pex.pep_508 import MarkerEnvironment
from pex.testing import IntegResults
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any, Dict, Text


def inspect(
    *args,  # type: str
    **popen_kwargs  # type: str
):
    # type: (...) -> IntegResults
    return run_pex3("interpreter", "inspect", *args, **popen_kwargs)


def assert_inspect(
    *args,  # type: str
    **popen_kwargs  # type: str
):
    # type: (...) -> Text

    result = inspect(*args, **popen_kwargs)
    result.assert_success()
    return result.output


def test_inspect_default(current_interpreter):
    # type: (PythonInterpreter) -> None
    assert current_interpreter.binary == assert_inspect().strip()


def assert_default_verbose_data(
    *args,  # type: str
    **popen_kwargs  # type: str
):
    # type: (...) -> Dict[str, Any]

    data = json.loads(assert_inspect(*args, **popen_kwargs))
    assert PythonInterpreter.get().binary == data.pop("path")
    return cast("Dict[str, Any]", data)


def test_inspect_default_verbose():
    # type: () -> None

    data = assert_default_verbose_data("-v")
    assert data, "There should be additional verbose details beyond just 'path'."


def assert_marker_environment(data):
    # type: (Dict[str, Any]) -> None
    assert PythonInterpreter.get().identity.env_markers == MarkerEnvironment(
        **data.pop("marker_environment")
    )


def test_inspect_default_markers():
    # type: () -> None

    data = assert_default_verbose_data("-m")
    assert_marker_environment(data)
    assert not data


def assert_compatible_tags(data):
    assert PythonInterpreter.get().identity.supported_tags == CompatibilityTags.from_strings(
        data.pop("compatible_tags")
    )


def test_inspect_default_tags():
    # type: () -> None

    data = assert_default_verbose_data("-t")
    assert_compatible_tags(data)
    assert not data


def test_inspect_default_combined():
    # type: () -> None

    data = assert_default_verbose_data("-vmt")
    assert_marker_environment(data)
    assert_compatible_tags(data)
    assert data, (
        "There should be additional verbose details beyond just 'path', 'marker_environment' and "
        "'compatible_tags'."
    )


def test_inspect_all():
    # type: () -> None
    assert [pi.binary for pi in PythonInterpreter.all()] == assert_inspect("--all").splitlines()


def test_inspect_interpreter_selection(
    py27,  # type: PythonInterpreter
    py37,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    assert [py27.binary, py310.binary] == assert_inspect(
        "--python", py27.binary, "--python", py310.binary
    ).splitlines()

    assert [py37.binary, py310.binary] == assert_inspect(
        "--all", "--python-path", ":".join([os.path.dirname(py37.binary), py310.binary])
    ).splitlines()

    assert [py37.binary] == assert_inspect(
        "--interpreter-constraint",
        "<3.10",
        "--python-path",
        ":".join([os.path.dirname(py37.binary), py310.binary]),
    ).splitlines()
