# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# A library of functions for filtering Python interpreters based on compatibility constraints

from __future__ import absolute_import

import os

from pex.common import die
from pex.interpreter import PythonIdentity, PythonInterpreter
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Optional, Tuple

    InterpreterIdentificationError = Tuple[str, str]


def validate_constraints(constraints):
    # type: (Iterable[str]) -> None
    # TODO: add check to see if constraints are mutually exclusive (bad) so no time is wasted:
    # https://github.com/pantsbuild/pex/issues/432
    for req in constraints:
        # Check that the compatibility requirements are well-formed.
        try:
            PythonIdentity.parse_requirement(req)
        except ValueError as e:
            die("Compatibility requirements are not formatted properly: %s" % str(e))


class UnsatisfiableInterpreterConstraintsError(Exception):
    """Indicates interpreter constraints could not be satisfied."""

    def __init__(
        self,
        constraints,  # type: Iterable[str]
        candidates,  # type: Iterable[PythonInterpreter]
        failures,  # type: Iterable[InterpreterIdentificationError]
    ):
        # type: (...) -> None
        """
        :param constraints: The constraints that could not be satisfied.
        :param candidates: The python interpreters that were compared against the constraints.
        :param failures: Descriptions of the python interpreters that were unidentifiable.
        """
        self.constraints = tuple(constraints)
        self.candidates = tuple(candidates)
        self.failures = tuple(failures)
        super(UnsatisfiableInterpreterConstraintsError, self).__init__(self.create_message())

    def create_message(self, preamble=None):
        # type: (Optional[str]) -> str
        """Create a message describing  failure to find matching interpreters with an optional
        preamble.

        :param preamble: An optional preamble to the message that will be displayed above it
                             separated by an empty blank line.
        :return: A descriptive message useable for display to an end user.
        """
        preamble = "{}\n\n".format(preamble) if preamble else ""

        failures_message = ""
        if self.failures:
            seen = set()
            broken_interpreters = []
            for python, error in self.failures:
                canonical_python = os.path.realpath(python)
                if canonical_python not in seen:
                    broken_interpreters.append((canonical_python, error))
                    seen.add(canonical_python)

            failures_message = (
                "{}\n"
                "\n"
                "(See https://github.com/pantsbuild/pex/issues/1027 for a list of known breaks and "
                "workarounds.)"
            ).format(
                "\n".join(
                    "{index}.) {binary}:\n{error}".format(index=i, binary=python, error=error)
                    for i, (python, error) in enumerate(broken_interpreters, start=1)
                )
            )

        if not self.candidates:
            if failures_message:
                return (
                    "{preamble}"
                    "Interpreters were found but they all appear to be broken:\n"
                    "{failures}"
                ).format(preamble=preamble, failures=failures_message)
            return "{}No interpreters could be found on the system.".format(preamble)

        binary_column_width = max(len(candidate.binary) for candidate in self.candidates)
        interpreters_format = "{{index}}.) {{binary: >{}}} {{requirement}}".format(
            binary_column_width
        )

        qualifier = ""
        if failures_message:
            failures_message = "Skipped the following broken interpreters:\n{}".format(
                failures_message
            )
            qualifier = "working "

        constraints_message = ""
        if self.constraints:
            constraints_message = (
                "No {qualifier}interpreter compatible with the requested constraints was found:\n"
                "  {constraints}"
            ).format(qualifier=qualifier, constraints="\n  ".join(self.constraints))

        problems = "\n\n".join(msg for msg in (failures_message, constraints_message) if msg)
        if problems:
            problems = "\n\n{}".format(problems)

        return (
            "{preamble}"
            "Examined the following {qualifier}interpreters:\n"
            "{interpreters}"
            "{problems}"
        ).format(
            preamble=preamble,
            qualifier=qualifier,
            interpreters="\n".join(
                interpreters_format.format(
                    index=i, binary=candidate.binary, requirement=candidate.identity.requirement
                )
                for i, candidate in enumerate(self.candidates, start=1)
            ),
            problems=problems,
        )
