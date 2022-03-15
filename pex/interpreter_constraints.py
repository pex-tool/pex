# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# A library of functions for filtering Python interpreters based on compatibility constraints

from __future__ import absolute_import

import itertools

from pex.enum import Enum
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Iterator, Optional, Tuple

    import attr  # vendor:skip

    from pex.interpreter import InterpreterIdentificationError
else:
    from pex.third_party import attr


class UnsatisfiableInterpreterConstraintsError(Exception):
    """Indicates interpreter constraints could not be satisfied."""

    def __init__(
        self,
        constraints,  # type: Iterable[str]
        candidates,  # type: Iterable[PythonInterpreter]
        failures,  # type: Iterable[InterpreterIdentificationError]
        preamble=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        """
        :param constraints: The constraints that could not be satisfied.
        :param candidates: The python interpreters that were compared against the constraints.
        :param failures: Descriptions of the python interpreters that were unidentifiable.
        :param preamble: An optional preamble for the exception message.
        """
        self.constraints = tuple(constraints)
        self.candidates = tuple(candidates)
        self.failures = tuple(failures)
        super(UnsatisfiableInterpreterConstraintsError, self).__init__(
            self.create_message(preamble=preamble)
        )

    def with_preamble(self, preamble):
        # type: (str) -> UnsatisfiableInterpreterConstraintsError
        return UnsatisfiableInterpreterConstraintsError(
            self.constraints, self.candidates, self.failures, preamble=preamble
        )

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
                canonical_python = PythonInterpreter.canonicalize_path(python)
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


class Lifecycle(Enum["Lifecycle.Value"]):
    class Value(Enum.Value):
        pass

    DEV = Value("dev")
    STABLE = Value("stable")
    EOL = Value("eol")


# This value is based off of:
# 1. Past releases: https://www.python.org/downloads/ where the max patch level was achieved by
#    2.7.18.
# 2. The 3.9+ annual release cycle formalization: https://www.python.org/dev/peps/pep-0602/ where
#    the last bugfix release will be at a patch level of ~10 and then 3.5 years of security fixes
#    as needed before going to EOL at the 5-year mark.
DEFAULT_MAX_PATCH = 30


@attr.s(frozen=True)
class PythonVersion(object):
    lifecycle = attr.ib()  # type: Lifecycle.Value
    major = attr.ib()  # type: int
    minor = attr.ib()  # type: int
    patch = attr.ib()  # type: int

    def iter_compatible_versions(
        self,
        specifier_sets,  # type: Iterable[SpecifierSet]
        max_patch=DEFAULT_MAX_PATCH,  # type: int
    ):
        # type: (...) -> Iterator[Tuple[int, int, int]]
        last_patch = self.patch if self.lifecycle == Lifecycle.EOL else max_patch
        for patch in range(last_patch + 1):
            version = (self.major, self.minor, patch)
            version_string = ".".join(map(str, version))
            if not specifier_sets:
                yield version
            else:
                for specifier_set in specifier_sets:
                    if version_string in specifier_set:
                        yield version
                        break


# TODO(John Sirois): Integrate a `pyenv install -l` based lint / generate script for CI / local
# use that emits the current max patch for these versions so we automatically stay up to date
# mod dormancy in the project.

COMPATIBLE_PYTHON_VERSIONS = (
    PythonVersion(Lifecycle.EOL, 2, 7, 18),
    # N.B.: Pex does not support the missing 3.x versions here.
    PythonVersion(Lifecycle.EOL, 3, 5, 10),
    PythonVersion(Lifecycle.EOL, 3, 6, 15),
    PythonVersion(Lifecycle.STABLE, 3, 7, 12),
    PythonVersion(Lifecycle.STABLE, 3, 8, 12),
    PythonVersion(Lifecycle.STABLE, 3, 9, 10),
    PythonVersion(Lifecycle.STABLE, 3, 10, 2),
    PythonVersion(Lifecycle.DEV, 3, 11, 0),
)


def iter_compatible_versions(
    requires_python,  # type: Iterable[str]
    max_patch=DEFAULT_MAX_PATCH,  # type: int
):
    # type: (...) -> Iterator[Tuple[int, int, int]]

    specifier_sets = OrderedSet(SpecifierSet(req) for req in requires_python)
    return itertools.chain.from_iterable(
        python_version.iter_compatible_versions(specifier_sets, max_patch=max_patch)
        for python_version in COMPATIBLE_PYTHON_VERSIONS
    )
