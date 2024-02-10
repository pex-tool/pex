# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pex import targets
from pex.interpreter import PythonInterpreter
from pex.pip.version import PipVersion, PipVersionValue
from pex.typing import TYPE_CHECKING
from testing import IntegResults, run_pex_command

if TYPE_CHECKING:
    from typing import NoReturn, Union


def pex_execute_cowsay(*extra_pex_args):
    # type: (*str) -> IntegResults
    return run_pex_command(
        args=list(extra_pex_args) + ["cowsay==5.0", "-c", "cowsay", "--", "Moo!"], quiet=True
    )


WARNING_PREFIX = "PEXWarning: "


def test_default_resolve_no_warning():
    # type: () -> None

    result = pex_execute_cowsay()
    result.assert_success()
    assert WARNING_PREFIX not in result.error
    assert "Moo!" in result.output


@pytest.fixture
def incompatible_pip_version():
    # type: () -> Union[PipVersionValue, NoReturn]
    for pip_version in PipVersion.values():
        if not pip_version.requires_python_applies(targets.current()):
            return pip_version

    pytest.skip(
        "There is no supported Pip version incompatible with {interpreter}.".format(
            interpreter=PythonInterpreter.get()
        )
    )
    raise AssertionError("Unreachable: satisfy type checker.")


def expected_incompatible_pip_message(
    incompatible_pip_version,  # type: PipVersionValue
    warning,  # type: bool
):
    # type: (...) -> str
    header = (
        "The Pip requested for PEX building was {pip_requirement} but it does not work with any "
        "of the targets selected.".format(pip_requirement=incompatible_pip_version.requirement)
    )
    return dedent(
        """\
        {prefix}{header}

        Pip {pip_version} requires Python {python_req} and the following target does not apply:
        1. {target}
        """.format(
            prefix=WARNING_PREFIX if warning else "",
            header=header,
            pip_version=incompatible_pip_version,
            python_req=incompatible_pip_version.requires_python,
            target=targets.current(),
        )
    )


def test_incompatible_resolve_warning(incompatible_pip_version):
    # type: (PipVersionValue) -> None

    result = pex_execute_cowsay("--pip-version", str(incompatible_pip_version))
    result.assert_success()
    assert (
        expected_incompatible_pip_message(incompatible_pip_version, warning=True) in result.error
    ), result.error
    assert "Moo!" in result.output, result.output


def test_incompatible_resolve_error(incompatible_pip_version):
    # type: (PipVersionValue) -> None

    result = pex_execute_cowsay(
        "--pip-version", str(incompatible_pip_version), "--no-allow-pip-version-fallback"
    )
    result.assert_failure()
    assert result.error.endswith(
        expected_incompatible_pip_message(incompatible_pip_version, warning=False)
    ), result.error
