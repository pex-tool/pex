# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import sysconfig

import pytest

from pex.compatibility import PY2
from pex.interpreter import PythonInterpreter
from pex.os import WINDOWS
from pex.pep_425 import CompatibilityTags
from pex.pep_508 import MarkerEnvironment
from pex.typing import TYPE_CHECKING, cast
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing import IntegResults
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any, Dict, Optional


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
    # type: (...) -> IntegResults

    result = inspect(*args, **popen_kwargs)
    result.assert_success()
    return result


def test_inspect_default():
    # type: () -> None
    result = assert_inspect()
    assert result.interpreter.binary == result.output.strip()


def assert_default_verbose_data(
    *args,  # type: str
    **popen_kwargs  # type: str
):
    # type: (...) -> Dict[str, Any]

    return assert_verbose_data(None, *args, **popen_kwargs)


def assert_verbose_data(
    interpreter,  # type: Optional[PythonInterpreter]
    *args,  # type: str
    **popen_kwargs  # type: str
):
    # type: (...) -> Dict[str, Any]

    result = assert_inspect(*args, **popen_kwargs)
    data = json.loads(result.output)
    assert (interpreter or result.interpreter).binary == data.pop("path")
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
    assert [pi.binary for pi in PythonInterpreter.all()] == assert_inspect(
        "--all"
    ).output.splitlines()


def test_inspect_interpreter_selection(
    py27,  # type: PythonInterpreter
    py39,  # type: PythonInterpreter
    py311,  # type: PythonInterpreter
):
    # type: (...) -> None

    assert [py27.binary, py311.binary] == assert_inspect(
        "--python", py27.binary, "--python", py311.binary
    ).output.splitlines()

    assert [py39.binary, py311.binary] == assert_inspect(
        "--all", "--python-path", os.pathsep.join([os.path.dirname(py39.binary), py311.binary])
    ).output.splitlines()

    assert [py39.binary] == assert_inspect(
        "--interpreter-constraint",
        "<3.11",
        "--python-path",
        os.pathsep.join([os.path.dirname(py39.binary), py311.binary]),
    ).output.splitlines()


def test_inspect_distributions(tmpdir):
    # type: (Any) -> None

    venv = Virtualenv.create(
        venv_dir=os.path.join(str(tmpdir), "venv"), install_pip=InstallationChoice.YES
    )
    venv.interpreter.execute(args=["-mpip", "install", "ansicolors==1.1.8", "cowsay==5.0"])

    data = assert_verbose_data(venv.interpreter, "-vd", "--python", venv.interpreter.binary)
    assert {"pip", "ansicolors", "cowsay"}.issubset(data["distributions"].keys())


@pytest.mark.skipif(PY2, reason="Virtualenvs on Python 2.7 have no `pyvenv.cfg` to re-home.")
@pytest.mark.skipif(WINDOWS, reason="Symlinks are not generally available on Windows.")
def test_inspect_verbose_venv_with_unresolvable_base_interpreter(tmpdir):
    # type: (Any) -> None

    # A venv keeps working when its base interpreter is replaced with one of a different ABI or
    # removed outright, but its base interpreter can then no longer be resolved. The rest of the
    # verbose data is still valid, so inspection should warn and carry on instead of failing.
    venv = Virtualenv.create(
        venv_dir=os.path.join(str(tmpdir), "venv"),
        copies=True,
        install_pip=InstallationChoice.NO,
    )

    # Re-home the venv on a base prefix that has the venv's stdlib - so its interpreter keeps
    # working - but no interpreter binary, so base interpreter resolution has nothing to find.
    base_prefix = os.path.join(str(tmpdir), "base")
    os.makedirs(os.path.join(base_prefix, "bin"))
    os.makedirs(os.path.join(base_prefix, "lib"))
    os.symlink(
        sysconfig.get_path("stdlib"),
        os.path.join(base_prefix, "lib", "python{0}.{1}".format(*venv.interpreter.version[:2])),
    )
    pyvenv_cfg = os.path.join(venv.venv_dir, "pyvenv.cfg")
    with open(pyvenv_cfg) as fp:
        lines = fp.read().splitlines()
    with open(pyvenv_cfg, "w") as fp:
        for line in lines:
            if line.startswith("home = "):
                line = "home = {bin_dir}".format(bin_dir=os.path.join(base_prefix, "bin"))
            fp.write(line + "\n")

    result = run_pex3(
        "interpreter",
        "inspect",
        "-v",
        "--pex-root",
        str(tmpdir.join("pex-root")),
        "--python",
        venv.interpreter.binary,
        use_pex_whl_venv=False,
    )
    result.assert_success()

    data = json.loads(result.output)
    assert venv.interpreter.binary == data.pop("path")
    assert data.pop("venv") is True
    assert "base_interpreter" not in data, (
        "There is no base interpreter to report, but the rest of the verbose data should be "
        "present: {data}".format(data=data)
    )
    warning = "Failed to determine base interpreter for venv interpreter"
    assert warning in result.error, "Expected warning {!r}; got: {error}".format(
        warning, error=result.error
    )
