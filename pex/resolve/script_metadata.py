# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from textwrap import dedent

from pex import specifier_sets
from pex.interpreter_constraints import InterpreterConstraint, InterpreterConstraints
from pex.orderedset import OrderedSet
from pex.pep_723 import ScriptMetadata
from pex.resolve.requirement_configuration import RequirementConfiguration
from pex.resolve.resolvers import Unsatisfiable
from pex.resolve.target_configuration import InterpreterConfiguration, TargetConfiguration
from pex.specifier_sets import UnsatisfiableSpecifierSet
from pex.targets import Target
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import List, Optional, Sequence, Tuple

    import attr  # vendor:skip

else:
    from pex.third_party import attr


@attr.s(frozen=True)
class ScriptMetadataApplication(object):
    scripts = attr.ib()  # type: Tuple[ScriptMetadata, ...]
    requirement_configuration = attr.ib()  # type: RequirementConfiguration
    target_configuration = attr.ib()  # type: TargetConfiguration

    def target_does_not_apply(self, target):
        # type: (Target) -> Tuple[ScriptMetadata, ...]
        return tuple(
            script
            for script in self.scripts
            if not target.requires_python_applies(
                requires_python=script.requires_python, source=script.source
            )
        )


def apply_script_metadata(
    scripts,  # type: Sequence[str]
    requirement_configuration=None,  # type: Optional[RequirementConfiguration]
    target_configuration=None,  # type: Optional[TargetConfiguration]
):
    # type: (...) -> ScriptMetadataApplication

    script_metadatas = []  # type: List[ScriptMetadata]
    requirements = OrderedSet(
        requirement_configuration.requirements
        if requirement_configuration and requirement_configuration.requirements
        else ()
    )  # type: OrderedSet[str]
    requires_python = SpecifierSet()
    for script in scripts:
        with open(script) as fp:
            script_metadata = ScriptMetadata.parse(fp.read(), source=fp.name)
        script_metadatas.append(script_metadata)
        requirements.update(map(str, script_metadata.dependencies))
        requires_python &= script_metadata.requires_python

    if isinstance(specifier_sets.as_range(requires_python), UnsatisfiableSpecifierSet):
        raise Unsatisfiable(
            dedent(
                """\
                The requires-python metadata of two or more of the specified scripts is in conflict.
                Given the scripts: {scripts} and {script}
                The resulting Python requirement is '{requires_python}' which is not satisfiable.
                """
            ).format(
                scripts=", ".join(scripts[:-1]), script=scripts[-1], requires_python=requires_python
            )
        )

    if target_configuration and requires_python:
        interpreter_constraints = (
            target_configuration.interpreter_configuration.interpreter_constraints.constraints
        )
        if interpreter_constraints:
            ics = []  # type: List[InterpreterConstraint]
            for interpreter_constraint in interpreter_constraints:
                merged_requires_python = interpreter_constraint.requires_python & requires_python
                if isinstance(
                    specifier_sets.as_range(merged_requires_python), UnsatisfiableSpecifierSet
                ):
                    raise Unsatisfiable(
                        "The requires-python metadata of one or more specified scripts is "
                        "in conflict with specified `--interpreter-constraint "
                        "'{interpreter_constraint}'` resulting in a Python requirement of "
                        "'{requires_python}' which is not satisfiable.".format(
                            interpreter_constraint=interpreter_constraint,
                            requires_python=requires_python,
                        ),
                    )
                ics.append(attr.evolve(interpreter_constraint, specifier=merged_requires_python))

            target_config = attr.evolve(
                target_configuration,
                interpreter_configuration=attr.evolve(
                    target_configuration.interpreter_configuration,
                    interpreter_constraints=InterpreterConstraints(constraints=tuple(ics)),
                ),
            )
        else:
            target_config = attr.evolve(
                target_configuration,
                interpreter_configuration=attr.evolve(
                    target_configuration.interpreter_configuration,
                    interpreter_constraints=InterpreterConstraints(
                        constraints=tuple([InterpreterConstraint(requires_python)])
                    ),
                ),
            )
    elif target_configuration:
        target_config = target_configuration
    elif not requires_python:
        target_config = TargetConfiguration()
    else:
        target_config = TargetConfiguration(
            interpreter_configuration=InterpreterConfiguration(
                interpreter_constraints=InterpreterConstraints(
                    constraints=tuple([InterpreterConstraint(requires_python)])
                )
            )
        )

    if requirement_configuration:
        requirement_config = attr.evolve(requirement_configuration, requirements=requirements)
    else:
        requirement_config = RequirementConfiguration(requirements=requirements)

    return ScriptMetadataApplication(
        scripts=tuple(script_metadatas),
        requirement_configuration=requirement_config,
        target_configuration=target_config,
    )
