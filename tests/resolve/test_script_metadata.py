# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import re
from textwrap import dedent

import pytest

from pex.dist_metadata import Requirement
from pex.interpreter_constraints import InterpreterConstraints
from pex.pep_723 import ScriptMetadata
from pex.resolve import script_metadata
from pex.resolve.resolvers import Unsatisfiable
from pex.resolve.target_configuration import InterpreterConfiguration, TargetConfiguration
from pex.third_party.packaging.specifiers import SpecifierSet
from testing.pytest.tmp import Tempdir


@pytest.fixture
def script(tmpdir):
    # type: (Tempdir) -> str

    script = tmpdir.join("script.py")
    with open(script, "w") as fp:
        fp.write(
            dedent(
                """\
                # /// script
                # dependencies = ["cowsay==5.0"]
                # requires-python = ">=3.8"
                # ///
                """
            )
        )
    return script


def test_single(script):
    # type: (str) -> None

    result = script_metadata.apply_script_metadata([script])
    assert (
        tuple(
            [
                ScriptMetadata(
                    dependencies=tuple([Requirement.parse("cowsay==5.0")]),
                    requires_python=SpecifierSet(">=3.8"),
                    source=script,
                )
            ]
        )
        == result.scripts
    )
    assert result.requirement_configuration.requirements is not None
    assert ["cowsay==5.0"] == list(result.requirement_configuration.requirements)
    assert (
        InterpreterConstraints.parse(">=3.8")
        == result.target_configuration.interpreter_configuration.interpreter_constraints
    )


@pytest.fixture
def script2(tmpdir):
    # type: (Tempdir) -> str

    script2 = tmpdir.join("script2.py")
    with open(script2, "w") as fp:
        fp.write(
            dedent(
                """\
                # /// script
                # dependencies = ["ansicolors==1.1.8"]
                # requires-python = "<3.14"
                # ///
                """
            )
        )
    return script2


def test_multiple(
    script,  # type: str
    script2,  # type: str
):
    # type: (...) -> None

    result = script_metadata.apply_script_metadata(
        [script, script2],
        target_configuration=TargetConfiguration(
            interpreter_configuration=InterpreterConfiguration(
                interpreter_constraints=InterpreterConstraints.parse("!=3.10.*")
            )
        ),
    )
    assert (
        ScriptMetadata(
            dependencies=tuple([Requirement.parse("cowsay==5.0")]),
            requires_python=SpecifierSet(">=3.8"),
            source=script,
        ),
        ScriptMetadata(
            dependencies=tuple([Requirement.parse("ansicolors==1.1.8")]),
            requires_python=SpecifierSet("<3.14"),
            source=script2,
        ),
    ) == result.scripts
    assert result.requirement_configuration.requirements is not None
    assert ["cowsay==5.0", "ansicolors==1.1.8"] == list(
        result.requirement_configuration.requirements
    )
    assert (
        InterpreterConstraints.parse(">=3.8,!=3.10.*,<3.14")
        == result.target_configuration.interpreter_configuration.interpreter_constraints
    )


@pytest.fixture
def script3(tmpdir):
    # type: (Tempdir) -> str

    script3 = tmpdir.join("script3.py")
    with open(script3, "w") as fp:
        fp.write(
            dedent(
                """\
                # /// script
                # requires-python = "<3.8"
                # ///
                """
            )
        )
    return script3


def test_script_conflict(
    script,  # type: str
    script2,  # type: str
    script3,  # type: str
):
    # type: (...) -> None

    with pytest.raises(
        Unsatisfiable,
        match=re.escape(
            "The requires-python metadata of two or more of the specified scripts is in conflict.\n"
            "Given the scripts: {script}, {script2} and {script3}\n"
            "The resulting Python requirement is '{requires_python}' which is not "
            "satisfiable.\n".format(
                script=script,
                script2=script2,
                script3=script3,
                requires_python=SpecifierSet("<3.8,>=3.8,<3.14"),
            )
        ),
    ):
        script_metadata.apply_script_metadata([script, script2, script3])


def test_ic_conflict(script):
    # type: (str) -> None

    with pytest.raises(
        Unsatisfiable,
        match=re.escape(
            "The requires-python metadata of one or more specified scripts is in conflict with "
            "specified `--interpreter-constraint '<3.8'` resulting in a Python requirement of "
            "'>=3.8' which is not satisfiable."
        ),
    ):
        script_metadata.apply_script_metadata(
            [script],
            target_configuration=TargetConfiguration(
                interpreter_configuration=InterpreterConfiguration(
                    interpreter_constraints=InterpreterConstraints.parse("<3.8")
                )
            ),
        )
