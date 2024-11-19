#!/usr/bin/env python3

import os
import re
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any


def analyze(log: Path) -> Any:
    tests: dict[str, bool] = {}
    with log.open() as fp:
        for line in fp:
            # E.G.: 2024-11-13T06:29:33.3456360Z tests/integration/test_issue_1018.py::test_execute_module_alter_sys[ep-function-zipapp-VENV]
            match = re.match(r"^.*\d+Z (?P<test>tests/\S+(?:\[[^\]]+\])?).*", line)
            if match:
                test = match.group("test")
                if test not in tests:
                    tests[test] = False
                continue

            # E.G.: 2024-11-13T06:29:33.3478200Z [gw3] PASSED tests/integration/venv_ITs/test_issue_1745.py::test_interpreter_mode_python_options[-c <code>-VENV]
            match = re.match(r"^.*\d+Z \[gw\d+\] [A-Z]+ (?P<test>tests/\S+(?:\[[^\]]+\])?).*", line)
            if match:
                tests[match.group("test")] = True
                continue

    hung_tests = sorted(test for test, complete in tests.items() if not complete)
    if hung_tests:
        return f"The following tests never finished:\n{os.linesep.join(hung_tests)}"


def main() -> Any:
    if len(sys.argv) != 2:
        return dedent(
            f"""\
            Usage: {sys.argv[0]} <CI log file>

            Analyzes a Pex CI log file from a timed-out shard to determine
            which tests never completed.
            """
        )

    log = Path(sys.argv[1])
    if not log.exists():
        return f"The log specified at {sys.argv[0]} does not exist."

    return analyze(Path(sys.argv[1]))


if __name__ == "__main__":
    sys.exit(main())
