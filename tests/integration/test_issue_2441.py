# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import re

import pytest

from pex.pip.version import PipVersion
from pex.typing import TYPE_CHECKING
from testing import PY_VER
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any


EXPECTED_ERROR_HEADER_LEAD_IN = (
    "Found 7 invalid Requires-Dist metadata values in mlflow 1.27 metadata from "
    "mlflow-1.27.0.dist-info/METADATA at"
)

EXPECTED_WHEEL = "mlflow-1.27.0-py3-none-any.whl"

EXPECTED_ERROR_FOOTER = """\
1. "scikit-learn (>=1.0.*) ; extra == 'pipelines'": .* suffix can only be used with `==` or `!=` operators
    scikit-learn (>=1.0.*) ; extra == 'pipelines'
                  ~~~~~~^
2. "pyarrow (>=7.0.*) ; extra == 'pipelines'": .* suffix can only be used with `==` or `!=` operators
    pyarrow (>=7.0.*) ; extra == 'pipelines'
             ~~~~~~^
3. "shap (>=0.40.*) ; extra == 'pipelines'": .* suffix can only be used with `==` or `!=` operators
    shap (>=0.40.*) ; extra == 'pipelines'
          ~~~~~~~^
4. "pandas-profiling (>=3.1.*) ; extra == 'pipelines'": .* suffix can only be used with `==` or `!=` operators
    pandas-profiling (>=3.1.*) ; extra == 'pipelines'
                      ~~~~~~^
5. "ipython (>=7.0.*) ; extra == 'pipelines'": .* suffix can only be used with `==` or `!=` operators
    ipython (>=7.0.*) ; extra == 'pipelines'
             ~~~~~~^
6. "markdown (>=3.3.*) ; extra == 'pipelines'": .* suffix can only be used with `==` or `!=` operators
    markdown (>=3.3.*) ; extra == 'pipelines'
              ~~~~~~^
7. "Jinja2 (>=3.0.*) ; extra == 'pipelines'": .* suffix can only be used with `==` or `!=` operators
    Jinja2 (>=3.0.*) ; extra == 'pipelines'
            ~~~~~~^
"""


@pytest.mark.skipif(
    PY_VER < (3, 7) or PipVersion.DEFAULT.version >= PipVersion.v24_1.version,
    reason="The mlflow 1.27.0 distribution requires Python>=3.7 and the test requires Pip<24.1.",
)
def test_invalid_metadata_error_messages_under_old_pip(tmpdir):
    # type: (Any) -> None

    run_pex3("lock", "create", "mlflow==1.27.0", "--intransitive").assert_failure(
        expected_error_re=r"^{header_lead_in} .*/{expected_wheel}:\n{footer}$".format(
            header_lead_in=re.escape(EXPECTED_ERROR_HEADER_LEAD_IN),
            expected_wheel=re.escape(EXPECTED_WHEEL),
            footer=re.escape(EXPECTED_ERROR_FOOTER),
        )
    )
