# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict


def patch():
    # type: () -> None

    from pip._vendor.packaging import markers  # type: ignore[import]

    from pex.exceptions import production_assert
    from pex.pip.foreign_platform import EvaluationEnvironment, PatchContext

    evaluation_environment = PatchContext.load_evaluation_environment()

    def _get_env(
        environment,  # type: Dict[Any, Any]
        name,  # type: Any
    ):
        # type: (...) -> Any
        production_assert(
            isinstance(environment, EvaluationEnvironment),
            "Expected environment to come from the {function} function, "
            "which we patch to return {expected_type}, but was {actual_type}",
            function=markers.default_environment,
            expected_type=EvaluationEnvironment,
            actual_type=type(environment),
        )
        return environment[name]

    # Works with all Pip vendored packaging distributions.
    markers.default_environment = evaluation_environment.default
    # Covers Pip<24.1 vendored packaging.
    markers._get_env = _get_env

    original_eval_op = markers._eval_op

    def _eval_op(
        lhs,  # type: Any
        op,  # type: Any
        rhs,  # type: Any
    ):
        # type: (...) -> Any
        evaluation_environment.raise_if_missing(lhs)
        evaluation_environment.raise_if_missing(rhs)
        return original_eval_op(lhs, op, rhs)

    markers._eval_op = _eval_op
