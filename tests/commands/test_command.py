# Copyright 2021 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import io
from argparse import Namespace
from textwrap import dedent

import pytest

from pex.commands.command import Command, JsonMixin, Main
from pex.compatibility import PY2
from pex.result import Error, ResultError, catch, try_
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import IO, Any, Optional, Text, Union


def test_try_catch():
    # type: () -> None

    def classify(number):
        # type: (Union[float, int]) -> Union[str, Error]
        if number == 42:
            return "Answer to the Ultimate Question of Life, the Universe, and Everything."
        return Error("Insignificant.")

    assert "Answer to the Ultimate Question of Life, the Universe, and Everything." == try_(
        classify(42)
    )

    assert "Answer to the Ultimate Question of Life, the Universe, and Everything." == catch(
        try_, classify(42)
    )

    with pytest.raises(ResultError) as exc_info:
        try_(classify(1 / 137))
    assert ResultError(Error("Insignificant.")) == exc_info.value

    assert Error("Insignificant.") == catch(try_, classify(1 / 137))


def test_main(capsys):
    # type: (Any) -> None

    class TestCommand(Command):
        @classmethod
        def add_arguments(cls, parser):
            cls.register_global_arguments(parser)

    class Command1(TestCommand):
        pass

    class Command2(TestCommand):
        pass

    main = Main[TestCommand](prog="test_main", command_types=(Command1, Command2))

    def assert_output(
        expected_stdout=None,  # type: Optional[str]
        expected_stderr=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        captured = capsys.readouterr()
        assert expected_stdout in captured.out if expected_stdout else "" == captured.out
        assert expected_stderr in captured.err if expected_stderr else "" == captured.err

    with main.parsed_command(["command1"]) as command:
        assert isinstance(command, Command1)
    assert_output()

    with main.parsed_command(["command2"]) as command:
        assert isinstance(command, Command2)
    assert_output()

    cm = main.parsed_command(
        args=[],
        # N.B.: Help output normally tries to re-write prog depending on sys.argv. Since we're
        # executing Main in-process, sys.argv is ours and not its; so disable prog re-writing so
        # that we can rely on the "test_main" prog name.
        rewrite_prog=False,
    )
    with pytest.raises(SystemExit) as exc_info:
        cm.__enter__()
    assert 2 == exc_info.value.code
    assert_output(expected_stderr="test_main [-h] [-V]")


def dump_json(
    obj,  # type: Any
    indent=None,  # type: Optional[int]
):
    # type: (...) -> Text
    def dump(out):
        # type: (IO) -> None
        JsonMixin.dump_json(options=Namespace(indent=indent), data=obj, out=out)

    if PY2:
        output = io.BytesIO()
        dump(output)
        return output.getvalue().decode("utf-8")
    else:
        output = io.StringIO()
        dump(output)
        return output.getvalue()


def test_json_mixin_no_indent():
    # type: () -> None
    assert '{"list": [1, 2]}' == dump_json({"list": [1, 2]})


def test_json_mixin_indent():
    # type: () -> None
    assert (
        dedent(
            """\
            {
              "list": [
                1,
                2
              ]
            }
            """
        ).strip()
        == dump_json({"list": [1, 2]}, indent=2)
    )
