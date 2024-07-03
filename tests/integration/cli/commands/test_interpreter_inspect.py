# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os

from pex.interpreter import PythonInterpreter
from pex.pep_425 import CompatibilityTags
from pex.pep_508 import MarkerEnvironment
from pex.typing import TYPE_CHECKING, cast
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing import IntegResults
from testing.cli import run_pex3

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

    return assert_verbose_data(PythonInterpreter.get(), *args, **popen_kwargs)


def assert_verbose_data(
    interpreter,  # type: PythonInterpreter
    *args,  # type: str
    **popen_kwargs  # type: str
):
    # type: (...) -> Dict[str, Any]

    data = json.loads(assert_inspect(*args, **popen_kwargs))
    assert interpreter.binary == data.pop("path")
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
    py38,  # type: PythonInterpreter
    py310,  # type: PythonInterpreter
):
    # type: (...) -> None

    assert [py27.binary, py310.binary] == assert_inspect(
        "--python", py27.binary, "--python", py310.binary
    ).splitlines()

    assert [py38.binary, py310.binary] == assert_inspect(
        "--all", "--python-path", os.pathsep.join([os.path.dirname(py38.binary), py310.binary])
    ).splitlines()

    assert [py38.binary] == assert_inspect(
        "--interpreter-constraint",
        "<3.10",
        "--python-path",
        os.pathsep.join([os.path.dirname(py38.binary), py310.binary]),
    ).splitlines()


def test_inspect_distributions(tmpdir):
    # type: (Any) -> None

    venv = Virtualenv.create(
        venv_dir=os.path.join(str(tmpdir), "venv"), install_pip=InstallationChoice.YES
    )
    venv.interpreter.execute(args=["-mpip", "install", "ansicolors==1.1.8", "cowsay==5.0"])

    data = assert_verbose_data(venv.interpreter, "-vd", "--python", venv.interpreter.binary)
    assert {"pip", "ansicolors", "cowsay"}.issubset(data["distributions"].keys())
