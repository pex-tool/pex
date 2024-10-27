# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import filecmp
import os.path
import subprocess
from textwrap import dedent

import pytest
from tools.commands.test_venv import make_env

from pex.common import safe_open
from pex.typing import TYPE_CHECKING
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any, Optional


@pytest.fixture
def reproducibility_hostile_project(tmpdir):
    # type: (Any) -> str
    project = os.path.join(str(tmpdir), "project")

    # N.B.: This simulates the setup.py seen here:
    # https://github.com/Unstructured-IO/unstructured/tree/06c85235ee8f014eae417b44ca17872f13960280
    # This was brought to Pex's attention here:
    #   https://github.com/pantsbuild/pants/discussions/21145
    with safe_open(os.path.join(project, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup


                csv_reqs = ["pandas"]
                doc_reqs = ["python-docx>=1.1.2"]
                docx_reqs = ["python-docx>=1.1.2"]
                epub_reqs = ["pypandoc"]
                image_reqs = [
                    "onnx",
                    "pdf2image",
                    "pdfminer.six",
                    "pikepdf",
                    "pillow_heif",
                    "pypdf",
                    "google-cloud-vision",
                    "effdet",
                    "unstructured-inference==0.7.36",
                    "unstructured.pytesseract>=0.3.12",
                ]
                markdown_reqs = ["markdown"]
                msg_reqs = ["python-oxmsg"]
                odt_reqs = ["python-docx>=1.1.2", "pypandoc"]
                org_reqs = ["pypandoc"]
                pdf_reqs = [
                    "onnx",
                    "pdf2image",
                    "pdfminer.six",
                    "pikepdf",
                    "pillow_heif",
                    "pypdf",
                    "google-cloud-vision",
                    "effdet",
                    "unstructured-inference==0.7.36",
                    "unstructured.pytesseract>=0.3.12",
                ]
                ppt_reqs = ["python-pptx<=0.6.23"]
                pptx_reqs = ["python-pptx<=0.6.23"]
                rtf_reqs = ["pypandoc"]
                rst_reqs = ["pypandoc"]
                tsv_reqs = ["pandas"]
                xlsx_reqs = [
                    "openpyxl",
                    "pandas",
                    "xlrd",
                    "networkx",
                ]

                all_doc_reqs = list(
                    set(
                        csv_reqs
                        + docx_reqs
                        + epub_reqs
                        + image_reqs
                        + markdown_reqs
                        + msg_reqs
                        + odt_reqs
                        + org_reqs
                        + pdf_reqs
                        + pptx_reqs
                        + rtf_reqs
                        + rst_reqs
                        + tsv_reqs
                        + xlsx_reqs,
                    ),
                )


                setup(
                    name="reproducibility_hostile",
                    version="0.1.0",
                    extras_require={
                        "all-docs": all_doc_reqs
                    }
                )
                """
            )
        )
    with safe_open(os.path.join(project, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools"]
                build-backend = "setuptools.build_meta"
                """
            )
        )
    return project


def create_lock(
    tmpdir,  # type: Any
    requirement,  # type: str
    index=None,  # type: Optional[int]
):
    # type: (...) -> str
    lock_file = os.path.join(
        str(tmpdir),
        "lock{index}.json".format(index=index) if index is not None else "lock.json",
    )
    run_pex3(
        "lock",
        "create",
        requirement,
        "--indent",
        "2",
        "-o",
        lock_file,
        env=make_env(PYTHONHASHSEED="random"),
    ).assert_success()
    return lock_file


def test_reproducibility_hostile_project_lock(
    tmpdir,  # type: Any
    reproducibility_hostile_project,  # type: str
):
    # type: (...) -> None

    lock = create_lock(tmpdir, reproducibility_hostile_project)
    for attempt in range(2):
        assert filecmp.cmp(
            lock, create_lock(tmpdir, reproducibility_hostile_project, attempt), shallow=False
        )


def test_reproducibility_hostile_vcs_lock(
    tmpdir,  # type: Any
    reproducibility_hostile_project,  # type: str
):
    # type: (...) -> None

    subprocess.check_call(args=["git", "init", reproducibility_hostile_project])
    subprocess.check_call(
        args=["git", "config", "user.email", "forty@two.com"], cwd=reproducibility_hostile_project
    )
    subprocess.check_call(
        args=["git", "config", "user.name", "Douglas Adams"], cwd=reproducibility_hostile_project
    )
    subprocess.check_call(
        args=["git", "checkout", "-b", "Golgafrincham"], cwd=reproducibility_hostile_project
    )
    subprocess.check_call(args=["git", "add", "."], cwd=reproducibility_hostile_project)
    subprocess.check_call(
        args=["git", "commit", "--no-gpg-sign", "-m", "Only commit."],
        cwd=reproducibility_hostile_project,
    )

    vcs_requirement = "git+file://{project}#egg=reproducibility_hostile".format(
        project=reproducibility_hostile_project
    )

    lock = create_lock(tmpdir, vcs_requirement)
    for attempt in range(2):
        assert filecmp.cmp(lock, create_lock(tmpdir, vcs_requirement, attempt), shallow=False)
