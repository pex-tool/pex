# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import subprocess
from textwrap import dedent

from pex.typing import TYPE_CHECKING
from testing import WheelBuilder
from testing.docker import skip_unless_docker

if TYPE_CHECKING:
    from typing import Any


@skip_unless_docker
def test_resolved_wheel_tag_platform_mismatch_warns(
    tmpdir,  # type: Any
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    context = os.path.join(str(tmpdir), "context")
    pex_wheel = WheelBuilder(pex_project_dir, wheel_dir=context).bdist()
    with open(os.path.join(context, "Dockerfile"), "w") as fp:
        fp.write(
            dedent(
                r"""
                FROM almalinux:8.10

                RUN dnf install -y \
                    python3.11-devel \
                    gcc \
                    make \
                    libffi-devel
                
                RUN mkdir /wheels
                COPY {pex_wheel} {pex_wheel}
                RUN python3.11 -mvenv /pex/venv && \
                    /pex/venv/bin/pip install {pex_wheel} && \
                    rm {pex_wheel}
        
                ENV PATH=/pex/venv/bin:$PATH

                RUN mkdir /work
                WORKDIR /work
                """.format(
                    pex_wheel=os.path.basename(pex_wheel)
                )
            )
        )
    subprocess.check_call(args=["docker", "build", "-t", "pex_test_issue_2532", context])

    process = subprocess.Popen(
        args=[
            "docker",
            "run",
            "--rm",
            "pex_test_issue_2532",
            "bash",
            "-c",
            dedent(
                r"""
                pex \
                    --python python3.11 \
                    --platform manylinux_2_28_x86_64-cp-3.11.9-cp311 \
                    cryptography==42.0.8 \
                    cffi==1.16.0 \
                    -o component_deps.pex
                ./component_deps.pex -c 'import cffi; print(cffi.__file__)'
                """
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate()
    error = stderr.decode("utf-8")
    assert 0 == process.returncode, error

    # N.B.: The tags calculated for manylinux_2_28_x86_64-cp-3.11.9-cp311 via `pip -v debug ...`
    # are:
    # ----
    # cp311-cp311-manylinux_2_28_x86_64
    # cp311-abi3-manylinux_2_28_x86_64
    # cp311-none-manylinux_2_28_x86_64
    # ...
    #
    # This does not match either of the wheel tags of:
    # + cp311-cp311-manylinux_2_17_x86_64
    # + cp311-cp311-manylinux_2014_x86_64
    #
    # Instead of failing the resolve check though, we should just see a warning since both of these
    # tags may be compatible at runtime, and, in fact, they are.
    assert (
        dedent(
            """\
            PEXWarning: The resolved distributions for 1 target may not be compatible:
            1: abbreviated platform cp311-cp311-manylinux_2_28_x86_64 may not be compatible with:
                cffi==1.16.0 was requested but 2 incompatible dists were resolved:
                    cffi-1.16.0-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
                    cffi-1.16.0-cp311-cp311-linux_x86_64.whl
                cryptography 42.0.8 requires cffi>=1.12; platform_python_implementation != "PyPy" but 2 incompatible dists were resolved:
                    cffi-1.16.0-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
                    cffi-1.16.0-cp311-cp311-linux_x86_64.whl

            Its generally advisable to use `--complete-platform` instead of `--platform` to
            ensure resolved distributions will be compatible with the target platform at
            runtime. For instructions on how to generate a `--complete-platform` see:
                https://docs.pex-tool.org/buildingpex.html#complete-platform
            """
        ).strip()
        in error
    ), error

    output = stdout.decode("utf-8")
    assert (
        "cffi-1.16.0-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl" in output
    ), output
