# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# A library of functions for filtering Python interpreters based on compatibility constraints

from __future__ import absolute_import

import itertools

from pex.common import die
from pex.enum import Enum
from pex.interpreter import PythonIdentity, PythonInterpreter
from pex.orderedset import OrderedSet
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import Iterable, Iterator, Optional, Tuple

    from pex.interpreter import InterpreterIdentificationError
else:
    from pex.third_party import attr


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


class Lifecycle(Enum):
    class Value(Enum.Value):
        pass

    DEV = Value("dev")
    STABLE = Value("stable")
    EOL = Value("eol")


@attr.s(frozen=True)
class PythonVersion(object):
    lifecycle = attr.ib()  # type: Lifecycle.Value
    major = attr.ib()  # type: int
    minor = attr.ib()  # type: int
    patch = attr.ib()  # type: int

    def pad(self, padding):
        # type: (int) -> PythonVersion
        if self.lifecycle == Lifecycle.EOL:
            return self
        return attr.evolve(self, patch=self.patch + padding)

    def iter_compatible_versions(self, specifier_sets):
        # type: (Iterable[SpecifierSet]) -> Iterator[Tuple[int, int, int]]
        for patch in range(self.patch + 1):
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

COMPATIBLE_PYTHON_VERSIONS = tuple(
    # Each 5 units of padding costs `iter_compatible_versions` ~2 extra ms and a padding of 10 gets
    # us through most of a brand new stable release's likely active lifecycle.
    version.pad(10)
    for version in (
        PythonVersion(Lifecycle.EOL, 2, 7, 18),
        # N.B.: Pex does not support the missing 3.x versions here.
        PythonVersion(Lifecycle.EOL, 3, 5, 10),
        PythonVersion(Lifecycle.EOL, 3, 6, 15),
        PythonVersion(Lifecycle.STABLE, 3, 7, 12),
        PythonVersion(Lifecycle.STABLE, 3, 8, 11),
        PythonVersion(Lifecycle.STABLE, 3, 9, 10),
        PythonVersion(Lifecycle.STABLE, 3, 10, 2),
        PythonVersion(Lifecycle.DEV, 3, 11, 0),
    )
)


def iter_compatible_versions(requires_python):
    # type: (Iterable[str]) -> Iterator[Tuple[int, int, int]]

    specifier_sets = OrderedSet(SpecifierSet(req) for req in requires_python)
    return itertools.chain.from_iterable(
        python_version.iter_compatible_versions(specifier_sets)
        for python_version in COMPATIBLE_PYTHON_VERSIONS
    )
