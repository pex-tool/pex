# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os

# N.B.: The following environment variable is used by the Pex runtime to control Pip and must be
# kept in-sync with `__init__.py`.
with open(os.environ.pop("_PEX_PYTHON_VERSIONS_FILE")) as fp:
    PYTHON_FULL_VERSIONS = sorted(tuple(version) for version in json.load(fp))
PYTHON_VERSIONS = sorted(set(version[:2] for version in PYTHON_FULL_VERSIONS))


def patch():
    # The pip-legacy-resolver patch.
    from pip._internal.utils import packaging  # type: ignore[import]

    if PYTHON_FULL_VERSIONS:
        orig_check_requires_python = packaging.check_requires_python

        def check_requires_python(requires_python, *_args, **_kw):
            # Ensure any dependency we lock is compatible with the full interpreter range
            # specified since we have no way to force Pip to backtrack and follow paths for any
            # divergences. Most (all?) true divergences should be covered by forked environment
            # markers.
            return all(
                orig_check_requires_python(requires_python, python_full_version)
                for python_full_version in PYTHON_FULL_VERSIONS
            )

        packaging.check_requires_python = check_requires_python
    else:
        packaging.check_requires_python = lambda *_args, **_kw: True

    # The pip-2020-resolver patch.
    from pip._internal.resolution.resolvelib.candidates import (  # type: ignore[import]
        RequiresPythonCandidate,
    )
    from pip._internal.resolution.resolvelib.requirements import (  # type: ignore[import]
        RequiresPythonRequirement,
    )

    if PYTHON_FULL_VERSIONS:
        orig_get_candidate_lookup = RequiresPythonRequirement.get_candidate_lookup
        orig_is_satisfied_by = RequiresPythonRequirement.is_satisfied_by

        # Ensure we do a proper, but minimal, comparison for Python versions. Previously we
        # always tested all `Requires-Python` specifier sets against Python full versions.
        # That can be pathologically slow (see:
        # https://github.com/pantsbuild/pants/issues/14998); so we avoid using Python full
        # versions unless the `Requires-Python` specifier set requires that data. In other
        # words:
        #
        # Need full versions to evaluate properly:
        # + Requires-Python: >=3.7.6
        # + Requires-Python: >=3.7,!=3.7.6,<4
        #
        # Do not need full versions to evaluate properly:
        # + Requires-Python: >=3.7,<4
        # + Requires-Python: ==3.7.*
        # + Requires-Python: >=3.6.0
        #
        def needs_full_versions(spec):
            components = spec.version.split(".", 2)
            if len(components) < 3:
                return False
            major_, minor_, patch = components
            if spec.operator in ("<", "<=", ">", ">=") and patch == "0":
                return False
            return patch != "*"

        def _py_versions(self):
            if not hasattr(self, "__py_versions"):
                self.__py_versions = (
                    version
                    for version in (
                        PYTHON_FULL_VERSIONS
                        if any(needs_full_versions(spec) for spec in self.specifier)
                        else PYTHON_VERSIONS
                    )
                    if ".".join(map(str, version)) in self.specifier
                )
            return self.__py_versions

        def get_candidate_lookup(self):
            for py_version in self._py_versions():
                delegate = RequiresPythonRequirement(
                    self.specifier, RequiresPythonCandidate(py_version)
                )
                candidate_lookup = orig_get_candidate_lookup(delegate)
                if candidate_lookup != (None, None):
                    return candidate_lookup
            return None, None

        def is_satisfied_by(self, *_args, **_kw):
            # Ensure any dependency we lock is compatible with the full interpreter range
            # specified since we have no way to force Pip to backtrack and follow paths for any
            # divergences. Most (all?) true divergences should be covered by forked environment
            # markers.
            return all(
                orig_is_satisfied_by(self, RequiresPythonCandidate(py_version))
                for py_version in self._py_versions()
            )

        RequiresPythonRequirement._py_versions = _py_versions
        RequiresPythonRequirement.get_candidate_lookup = get_candidate_lookup
        RequiresPythonRequirement.is_satisfied_by = is_satisfied_by
    else:
        RequiresPythonRequirement.get_candidate_lookup = lambda self: (self._candidate, None)
        RequiresPythonRequirement.is_satisfied_by = lambda *_args, **_kw: True
