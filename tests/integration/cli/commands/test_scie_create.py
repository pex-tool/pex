# Copyright 2026 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import re
import shutil
import subprocess
import sys

from pex.fetcher import URLFetcher
from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.typing import TYPE_CHECKING
from testing import PY310, PY311, ensure_python_interpreter, run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir
from testing.scie import skip_if_no_provider

if TYPE_CHECKING:
    from typing import Optional, Text, Tuple


def test_not_a_pex(tmpdir):
    # type: (Tempdir) -> None

    run_pex3("scie", "create", "--style", "eager", tmpdir.path).assert_failure(
        expected_error_re=r"^{message}.+$".format(
            message=re.escape(
                "The path {pex_path} does not appear to be a PEX: ".format(pex_path=tmpdir.path)
            )
        )
    )


def download_pex_pex(
    tmpdir,  # type: Tempdir
    version=None,  # type: Optional[str]
):
    # type: (...) -> str

    fetcher = URLFetcher()
    if version:
        url = "https://github.com/pex-tool/pex/releases/download/v{version}/pex".format(
            version=version
        )
    else:
        url = "https://github.com/pex-tool/pex/releases/latest/download/pex"
    with fetcher.get_body_stream(url) as in_fp, open(
        tmpdir.join("pex-{version}.pex".format(version=version or "latest")), "wb"
    ) as out_fp:
        shutil.copyfileobj(in_fp, out_fp)
    return out_fp.name


def test_pex_too_old(tmpdir):
    # type: (Tempdir) -> None

    pex_2_1_24 = download_pex_pex(tmpdir, "2.1.24")
    run_pex3("scie", "create", "--style", "eager", pex_2_1_24).assert_failure(
        expected_error_re=r"^{message}$".format(
            message=re.escape(
                "Can only create scies from PEXes built by Pex 2.1.25 (which was released on "
                "January 21st, 2021) or newer.\n"
                "The PEX at {pex_file} was built by Pex 2.1.24.".format(pex_file=pex_2_1_24)
            )
        )
    )


def get_version(*exe):
    # type: (*Text) -> Version
    return Version(subprocess.check_output(args=list(exe) + ["--version"]).decode("utf-8").strip())


def create_scie(*args):
    # type: (Text) -> Tuple[Text, Version]

    result = run_pex3("scie", "create", "--style", "eager", *args)

    match = re.search(r"^Saved PEX scie for .+ to (?P<path>.+)$", result.output)
    assert match is not None

    scie_path = match.group("path")
    assert scie_path is not None

    return scie_path, get_version(scie_path)


def test_pex_old(tmpdir):
    # type: (Tempdir) -> None

    pex_2_1_25 = download_pex_pex(tmpdir, "2.1.25")

    # N.B.: The 20251031 PBS release was the last to ship Python 3.9, which is the upper-bound of
    # supported Pythons for Pex 2.1.25.
    scie_path, scie_version = create_scie("--scie-pbs-release", "20251031", pex_2_1_25)
    assert scie_path != pex_2_1_25
    assert Version("2.1.25") == scie_version


# N.B.: Modern Pex PEXes ship with no ICs; so the current interpreter is used.
@skip_if_no_provider
def test_nominal(tmpdir):
    # type: (Tempdir) -> None

    pex_latest = download_pex_pex(tmpdir)
    pex_latest_version = get_version(sys.executable, pex_latest)

    scie_path, scie_version = create_scie(pex_latest)
    assert scie_path != pex_latest
    assert pex_latest_version == scie_version


@skip_if_no_provider
def test_ics(tmpdir):
    # type: (Tempdir) -> None

    major, minor = sys.version_info[:2]
    current_interpreter_constraint = "=={major}.{minor}.*".format(major=major, minor=minor)

    other_version = PY310 if (major, minor) == (3, 11) else PY311
    other_python = PythonInterpreter.from_binary(ensure_python_interpreter(other_version))
    other_interpreter_constraint = "=={major}.{minor}.*".format(
        major=other_python.version[0], minor=other_python.version[1]
    )

    cowsay_pex = tmpdir.join("cowsay.pex")

    run_pex_command(
        args=[
            "--interpreter-constraint",
            current_interpreter_constraint,
            "--interpreter-constraint",
            other_interpreter_constraint,
            "cowsay==5.0",
            "-c",
            "cowsay",
            "-o",
            cowsay_pex,
        ]
    ).assert_success()

    sorted_ics = sorted((current_interpreter_constraint, other_interpreter_constraint))
    run_pex3(
        "scie", "create", "--style", "eager", "--interpreter-constraint", "==3.9.*", cowsay_pex
    ).assert_failure(
        expected_error_re=r"^{message}$".format(
            message=re.escape(
                "The PEX has interpreter constraints of {ic1} or {ic2} and the user-supplied "
                "interpreter constraints of ==3.9.* do not form a subset of those.".format(
                    ic1=sorted_ics[0], ic2=sorted_ics[1]
                )
            )
        )
    )

    scie_path, scie_version = create_scie(
        "--interpreter-constraint", current_interpreter_constraint, cowsay_pex
    )
    assert Version("5") == scie_version
    assert b"| Moo! |" in subprocess.check_output(args=[scie_path, "Moo!"])
