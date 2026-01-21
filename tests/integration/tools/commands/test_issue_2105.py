# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
from textwrap import dedent

import pytest

from pex.dist_metadata import Distribution
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing import IS_MAC, make_env, run_pex_command, subprocess
from testing.pytest_utils.tmp import Tempdir, TempdirFactory

if TYPE_CHECKING:
    from typing import Any, Iterable, Mapping, Optional


@pytest.fixture(scope="module")
def td(
    tmpdir_factory,  # type: TempdirFactory
    request,  # type: Any
):
    # type: (...) -> Tempdir
    return tmpdir_factory.mktemp("td", request=request)


PIP_PROJECT_NAME = ProjectName("pip")
SETUPTOOLS_PROJECT_NAME = ProjectName("setuptools")


def index_distributions(dists):
    # type: (Iterable[Distribution]) -> Mapping[ProjectName, Version]
    return {dist.metadata.project_name: dist.metadata.version for dist in dists}


@pytest.fixture(scope="module")
def baseline_venv_with_pip(td):
    # type: (Any) -> Mapping[ProjectName, Version]
    baseline_venv = Virtualenv.create(
        venv_dir=str(td.join("baseline.venv")), install_pip=InstallationChoice.YES
    )
    baseline_venv_distributions = index_distributions(baseline_venv.iter_distributions())
    assert PIP_PROJECT_NAME in baseline_venv_distributions
    return baseline_venv_distributions


@pytest.fixture(scope="module")
def baseline_venv_pip_version(baseline_venv_with_pip):
    # type: (Mapping[ProjectName, Version]) -> Version
    return baseline_venv_with_pip[PIP_PROJECT_NAME]


@pytest.fixture(scope="module")
def baseline_venv_setuptools_version(baseline_venv_with_pip):
    # type: (Mapping[ProjectName, Version]) -> Optional[Version]
    return baseline_venv_with_pip.get(SETUPTOOLS_PROJECT_NAME)


def assert_venv_dists(
    venv_dir,  # type: str
    expected_pip_version,  # type: Version
    expected_setuptools_version,  # type: Optional[Version]
):
    virtualenv = Virtualenv(venv_dir)
    dists = index_distributions(virtualenv.iter_distributions())
    assert expected_pip_version == dists[PIP_PROJECT_NAME]
    assert expected_setuptools_version == dists.get(SETUPTOOLS_PROJECT_NAME)

    def reported_version(module):
        # type: (str) -> Version
        return Version(
            subprocess.check_output(
                args=[
                    virtualenv.interpreter.binary,
                    "-c",
                    "import {module}; print({module}.__version__)".format(module=module),
                ]
            ).decode("utf-8")
        )

    assert expected_pip_version == reported_version("pip")
    if expected_setuptools_version:
        assert expected_setuptools_version == reported_version("setuptools")


def assert_venv_dists_no_conflicts(
    tmpdir,  # type: Any
    pex,  # type: str
    expected_pip_version,  # type: Version
    expected_setuptools_version,  # type: Optional[Version]
):
    # type: (...) -> None
    venv_dir = os.path.join(str(tmpdir), "venv_dir")
    subprocess.check_call(args=[pex, "venv", "--pip", venv_dir], env=make_env(PEX_TOOLS=1))
    assert_venv_dists(venv_dir, expected_pip_version, expected_setuptools_version)


def test_pip_empty_pex(
    tmpdir,  # type: Any
    baseline_venv_pip_version,  # type: Version
    baseline_venv_setuptools_version,  # type: Optional[Version]
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["-o", pex, "--include-tools"]).assert_success()

    assert_venv_dists_no_conflicts(
        tmpdir,
        pex,
        expected_pip_version=baseline_venv_pip_version,
        expected_setuptools_version=baseline_venv_setuptools_version,
    )


def test_pip_pex_no_conflicts(
    tmpdir,  # type: Any
    baseline_venv_pip_version,  # type: Version
    baseline_venv_setuptools_version,  # type: Optional[Version]
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    args = ["-o", pex, "pip=={version}".format(version=baseline_venv_pip_version)]
    if baseline_venv_setuptools_version:
        args.append("setuptools=={version}".format(version=baseline_venv_setuptools_version))
    args.append("--include-tools")
    run_pex_command(args).assert_success()

    assert_venv_dists_no_conflicts(
        tmpdir,
        pex,
        expected_pip_version=baseline_venv_pip_version,
        expected_setuptools_version=baseline_venv_setuptools_version,
    )


def assert_venv_dists_conflicts(
    tmpdir,  # type: Any
    pex,  # type: str
    baseline_venv_pip_version,  # type: Version
    baseline_venv_setuptools_version,  # type: Optional[Version]
    expected_pip_version,  # type: Version
    expected_setuptools_version,  # type: Optional[Version]
):
    # type: (...) -> None

    expected_conflicts = []
    if baseline_venv_pip_version != expected_pip_version:
        expected_conflicts.append("pip {version}".format(version=expected_pip_version))
    if baseline_venv_setuptools_version != expected_setuptools_version:
        expected_conflicts.append(
            "setuptools {version}".format(version=expected_setuptools_version)
        )
    assert (
        expected_conflicts
    ), "The assert_venv_dists_conflicts function requires at least one conflict."

    venv_dir = os.path.join(str(tmpdir), "venv_dir")
    args = [pex, "venv", "--pip", venv_dir]

    expected_message_prefix = (
        dedent(
            """\
            You asked for --pip to be installed in the venv at {venv_dir},
            but the PEX at {pex} already contains:
            {conflicts}
            """
        )
        .format(venv_dir=venv_dir, pex=pex, conflicts=os.linesep.join(expected_conflicts))
        .strip()
    )

    process = subprocess.Popen(args, stderr=subprocess.PIPE, env=make_env(PEX_TOOLS=1))
    _, stderr = process.communicate()
    assert 0 != process.returncode

    decoded_stderr = stderr.decode("utf-8")
    assert (
        dedent(
            """\
            {prefix}
            Consider re-running either without --pip or with --collisions-ok.
            """
        ).format(prefix=expected_message_prefix)
        in decoded_stderr
    ), decoded_stderr

    process = subprocess.Popen(
        args + ["--force", "--collisions-ok"], stderr=subprocess.PIPE, env=make_env(PEX_TOOLS=1)
    )
    _, stderr = process.communicate()
    assert 0 == process.returncode
    decoded_stderr = stderr.decode("utf-8")
    assert (
        dedent(
            """\
            {prefix}
            Uninstalling venv versions and using versions from the PEX.
            """
        ).format(prefix=expected_message_prefix)
        in decoded_stderr
    ), decoded_stderr

    assert_venv_dists(venv_dir, expected_pip_version, expected_setuptools_version)


def test_pip_pex_pip_conflict(
    tmpdir,  # type: Any
    baseline_venv_pip_version,  # type: Version
    baseline_venv_setuptools_version,  # type: Optional[Version]
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[
            "-o",
            pex,
            "pip!={version}".format(version=baseline_venv_pip_version),
            "--include-tools",
        ]
    ).assert_success()
    pex_pip_version = index_distributions(PEX(pex).resolve())[PIP_PROJECT_NAME]

    assert_venv_dists_conflicts(
        tmpdir,
        pex,
        baseline_venv_pip_version=baseline_venv_pip_version,
        baseline_venv_setuptools_version=baseline_venv_setuptools_version,
        expected_pip_version=pex_pip_version,
        expected_setuptools_version=baseline_venv_setuptools_version,
    )


def test_pip_pex_setuptools_conflict(
    tmpdir,  # type: Any
    baseline_venv_pip_version,  # type: Version
    baseline_venv_setuptools_version,  # type: Optional[Version]
):
    # type: (...) -> None

    if not baseline_venv_setuptools_version:
        return

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[
            "-o",
            pex,
            "setuptools!={version}".format(version=baseline_venv_setuptools_version),
            "--include-tools",
        ]
    ).assert_success()
    pex_setuptools_version = index_distributions(PEX(pex).resolve()).get(SETUPTOOLS_PROJECT_NAME)

    assert_venv_dists_conflicts(
        tmpdir,
        pex,
        baseline_venv_pip_version=baseline_venv_pip_version,
        baseline_venv_setuptools_version=baseline_venv_setuptools_version,
        expected_pip_version=baseline_venv_pip_version,
        expected_setuptools_version=pex_setuptools_version,
    )


# The inscrutable resolution impossible error mentioned in the skip below:
#   ---
#   STDERR:
#   pex: Building pex
#   pex: Building pex :: Adding distributions from pexes:
#   pex: Building pex :: Adding distributions built from local projects and collecting their requirements:
#   pex: Building pex :: Adding distributions built from local projects and collecting their requirements:  :: Resolving requirements.
#   pex: Building pex :: Resolving distributions for requirements: pip!=25.2
#   pex: Building pex :: Resolving distributions for requirements: pip!=25.2 :: Resolving requirements.
#   pex: Building pex :: Resolving distributions for requirements: pip!=25.2 :: Resolving requirements. :: Resolving for:
#     cp314-cp314-macosx_15_0_arm64 interpreter at /Users/runner/work/pex/pex/repo/.dev-cmd/venvs/eifTbqY9fwETmYR92DGjgrNIwgz2tC-6z-DbobVZfbA/bin/python3.14
#   pex: Hashing pex
#   pex: Hashing pex: 39.4ms
#   pex: Isolating pex
#   pex: Isolating pex: 0.1ms
#   pid 7181 -> /Users/runner/Library/Caches/pex/venvs/1/8b925ca6f6dedd44821a3c7b47687e08bc0c4405/e76c619a30dca26fe88754ac969840a7d8230406/bin/python /Users/runner/Library/Caches/pex/venvs/1/8b925ca6f6dedd44821a3c7b47687e08bc0c4405/e76c619a30dca26fe88754ac969840a7d8230406/pex --disable-pip-version-check --exists-action a --no-input --log /private/var/folders/q0/wmf37v850txck86cpnvwm_zw0000gn/T/pytest-of-runner/pytest-0/popen-gw2/test_pip_pex_both_conflict0/pip.log -q --cache-dir /Users/runner/Library/Caches/pex/pip/1/25.2/pip_cache download --dest /Users/runner/Library/Caches/pex/downloads/1/.tmp/resolver_download.uoss1_xb/CPython-3.14.0 pip!=25.2 --retries 5 --resume-retries 3 --timeout 15 exited with 1 and STDERR:
#   pip: ERROR: Could not find a version that satisfies the requirement pip!=25.2 (from versions: none)
#   pip: ERROR: No matching distribution found for pip!=25.2
#   pex: Building pex: 2083.8ms
#   pex:   Adding distributions from pexes: : 0.0ms
#   pex:   Adding distributions built from local projects and collecting their requirements: : 0.1ms
#   pex:     Resolving requirements.: 0.1ms
#   pex:   Resolving distributions for requirements: pip!=25.2: 2083.4ms
#   pex:     Resolving requirements.: 2083.3ms
#   pex:       Resolving for:
#     cp314-cp314-macosx_15_0_arm64 interpreter at /Users/runner/work/pex/pex/repo/.dev-cmd/venvs/eifTbqY9fwETmYR92DGjgrNIwgz2tC-6z-DbobVZfbA/bin/python3.14: 2081.8ms
#
#   ---
#   Pip logs:
#   2025-10-08T04:41:38,274 Created temporary directory: /Users/runner/Library/Caches/pex/pip/1/25.2/pip_cache/.tmp/pip-build-tracker-bonl7_j_
#   2025-10-08T04:41:38,275 Initialized build tracking at /Users/runner/Library/Caches/pex/pip/1/25.2/pip_cache/.tmp/pip-build-tracker-bonl7_j_
#   2025-10-08T04:41:38,275 Created build tracker: /Users/runner/Library/Caches/pex/pip/1/25.2/pip_cache/.tmp/pip-build-tracker-bonl7_j_
#   2025-10-08T04:41:38,275 Entered build tracker: /Users/runner/Library/Caches/pex/pip/1/25.2/pip_cache/.tmp/pip-build-tracker-bonl7_j_
#   2025-10-08T04:41:38,275 Created temporary directory: /Users/runner/Library/Caches/pex/pip/1/25.2/pip_cache/.tmp/pip-download-453dr6hw
#   2025-10-08T04:41:38,305 Looking in indexes: http://127.0.0.1:49305/root/pypi/+simple/
#   2025-10-08T04:41:38,306 1 location(s) to search for versions of pip:
#   2025-10-08T04:41:38,306 * http://127.0.0.1:49305/root/pypi/+simple/pip/
#   2025-10-08T04:41:38,306 Fetching project page and analyzing links: http://127.0.0.1:49305/root/pypi/+simple/pip/
#   2025-10-08T04:41:38,306 Getting page http://127.0.0.1:49305/root/pypi/+simple/pip/
#   2025-10-08T04:41:38,306 Found index url http://127.0.0.1:49305/root/pypi/+simple/
#   2025-10-08T04:41:38,311 Looking up "http://127.0.0.1:49305/root/pypi/+simple/pip/" in the cache
#   2025-10-08T04:41:38,311 Request header has "max_age" as 0, cache bypassed
#   2025-10-08T04:41:38,311 No cache entry available
#   2025-10-08T04:41:38,312 Starting new HTTP connection (1): 127.0.0.1:49305
#   2025-10-08T04:41:39,605 http://127.0.0.1:49305 "GET /root/pypi/+simple/pip/ HTTP/1.1" 200 None
#   2025-10-08T04:41:39,648 Updating cache with response from "http://127.0.0.1:49305/root/pypi/+simple/pip/"
#   2025-10-08T04:41:39,649 Fetched page http://127.0.0.1:49305/root/pypi/+simple/pip/ as application/vnd.pypi.simple.v1+json
#   2025-10-08T04:41:39,649 Skipping link: not a file: http://127.0.0.1:49305/root/pypi/+simple/pip/
#   2025-10-08T04:41:39,650 Given no hashes to check 0 links for project 'pip': discarding no candidates
#   2025-10-08T04:41:39,650 ERROR: Could not find a version that satisfies the requirement pip!=25.2 (from versions: none)
#   2025-10-08T04:41:39,650 ERROR: No matching distribution found for pip!=25.2
#   2025-10-08T04:41:39,650 Exception information:
#   2025-10-08T04:41:39,650 Traceback (most recent call last):
#   2025-10-08T04:41:39,650   File "/Users/runner/Library/Caches/pex/venvs/1/8b925ca6f6dedd44821a3c7b47687e08bc0c4405/e76c619a30dca26fe88754ac969840a7d8230406/lib/python3.14/site-packages/pip/_vendor/resolvelib/resolvers/resolution.py", line 429, in resolve
#   2025-10-08T04:41:39,650     self._add_to_criteria(self.state.criteria, r, parent=None)
#   2025-10-08T04:41:39,650     ~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#   2025-10-08T04:41:39,650   File "/Users/runner/Library/Caches/pex/venvs/1/8b925ca6f6dedd44821a3c7b47687e08bc0c4405/e76c619a30dca26fe88754ac969840a7d8230406/lib/python3.14/site-packages/pip/_vendor/resolvelib/resolvers/resolution.py", line 151, in _add_to_criteria
#   2025-10-08T04:41:39,650     raise RequirementsConflicted(criterion)
#   2025-10-08T04:41:39,650 pip._vendor.resolvelib.resolvers.exceptions.RequirementsConflicted: Requirements conflict: SpecifierRequirement('pip!=25.2')
#   2025-10-08T04:41:39,650
#   2025-10-08T04:41:39,650 The above exception was the direct cause of the following exception:
#   2025-10-08T04:41:39,650
#   2025-10-08T04:41:39,650 Traceback (most recent call last):
#   2025-10-08T04:41:39,650   File "/Users/runner/Library/Caches/pex/venvs/1/8b925ca6f6dedd44821a3c7b47687e08bc0c4405/e76c619a30dca26fe88754ac969840a7d8230406/lib/python3.14/site-packages/pip/_internal/resolution/resolvelib/resolver.py", line 98, in resolve
#   2025-10-08T04:41:39,650     result = self._result = resolver.resolve(
#   2025-10-08T04:41:39,650                             ~~~~~~~~~~~~~~~~^
#   2025-10-08T04:41:39,650         collected.requirements, max_rounds=limit_how_complex_resolution_can_be
#   2025-10-08T04:41:39,650         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#   2025-10-08T04:41:39,650     )
#   2025-10-08T04:41:39,650     ^
#   2025-10-08T04:41:39,650   File "/Users/runner/Library/Caches/pex/venvs/1/8b925ca6f6dedd44821a3c7b47687e08bc0c4405/e76c619a30dca26fe88754ac969840a7d8230406/lib/python3.14/site-packages/pip/_vendor/resolvelib/resolvers/resolution.py", line 596, in resolve
#   2025-10-08T04:41:39,650     state = resolution.resolve(requirements, max_rounds=max_rounds)
#   2025-10-08T04:41:39,650   File "/Users/runner/Library/Caches/pex/venvs/1/8b925ca6f6dedd44821a3c7b47687e08bc0c4405/e76c619a30dca26fe88754ac969840a7d8230406/lib/python3.14/site-packages/pip/_vendor/resolvelib/resolvers/resolution.py", line 431, in resolve
#   2025-10-08T04:41:39,650     raise ResolutionImpossible(e.criterion.information) from e
#   2025-10-08T04:41:39,650 pip._vendor.resolvelib.resolvers.exceptions.ResolutionImpossible: [RequirementInformation(requirement=SpecifierRequirement('pip!=25.2'), parent=None)]
#   2025-10-08T04:41:39,650
#   2025-10-08T04:41:39,650 The above exception was the direct cause of the following exception:
#   2025-10-08T04:41:39,650
#   2025-10-08T04:41:39,650 Traceback (most recent call last):
#   2025-10-08T04:41:39,650   File "/Users/runner/Library/Caches/pex/venvs/1/8b925ca6f6dedd44821a3c7b47687e08bc0c4405/e76c619a30dca26fe88754ac969840a7d8230406/lib/python3.14/site-packages/pip/_internal/cli/base_command.py", line 107, in _run_wrapper
#   2025-10-08T04:41:39,650     status = _inner_run()
#   2025-10-08T04:41:39,650   File "/Users/runner/Library/Caches/pex/venvs/1/8b925ca6f6dedd44821a3c7b47687e08bc0c4405/e76c619a30dca26fe88754ac969840a7d8230406/lib/python3.14/site-packages/pip/_internal/cli/base_command.py", line 98, in _inner_run
#   2025-10-08T04:41:39,650     return self.run(options, args)
#   2025-10-08T04:41:39,650            ~~~~~~~~^^^^^^^^^^^^^^^
#   2025-10-08T04:41:39,650   File "/Users/runner/Library/Caches/pex/venvs/1/8b925ca6f6dedd44821a3c7b47687e08bc0c4405/e76c619a30dca26fe88754ac969840a7d8230406/lib/python3.14/site-packages/pip/_internal/cli/req_command.py", line 71, in wrapper
#   2025-10-08T04:41:39,650     return func(self, options, args)
#   2025-10-08T04:41:39,650   File "/Users/runner/Library/Caches/pex/venvs/1/8b925ca6f6dedd44821a3c7b47687e08bc0c4405/e76c619a30dca26fe88754ac969840a7d8230406/lib/python3.14/site-packages/pip/_internal/commands/download.py", line 131, in run
#   2025-10-08T04:41:39,650     requirement_set = resolver.resolve(reqs, check_supported_wheels=True)
#   2025-10-08T04:41:39,650   File "/Users/runner/Library/Caches/pex/venvs/1/8b925ca6f6dedd44821a3c7b47687e08bc0c4405/e76c619a30dca26fe88754ac969840a7d8230406/lib/python3.14/site-packages/pip/_internal/resolution/resolvelib/resolver.py", line 107, in resolve
#   2025-10-08T04:41:39,650     raise error from e
#   2025-10-08T04:41:39,650 pip._internal.exceptions.DistributionNotFound: No matching distribution found for pip!=25.2
#   2025-10-08T04:41:39,654 Removed build tracker: '/Users/runner/Library/Caches/pex/pip/1/25.2/pip_cache/.tmp/pip-build-tracker-bonl7_j_'
@pytest.mark.skipif(
    IS_MAC,
    reason=(
        "For unknown reasons, under Mac Python 3.14 / Pip 25.2, we get resolution impossible for "
        "the requirement `pip!=25.2`. Since this test is not platform dependent, we just skip Mac "
        "for now."
    ),
)
def test_pip_pex_both_conflict(
    tmpdir,  # type: Tempdir
    baseline_venv_pip_version,  # type: Version
    baseline_venv_setuptools_version,  # type: Optional[Version]
):
    # type: (...) -> None

    pex = tmpdir.join("pex")
    pip_log = tmpdir.join("pip.log")
    args = ["-o", pex, "pip!={version}".format(version=baseline_venv_pip_version)]
    if baseline_venv_setuptools_version:
        args.append("setuptools!={version}".format(version=baseline_venv_setuptools_version))
    args.append("--include-tools")
    args.append("--pip-log")
    args.append(pip_log)
    result = run_pex_command(args)

    def render_errors():
        # type: () -> str
        with open(pip_log) as fp:
            return ("STDERR:\n" "{stderr}\n" "---\n" "Pip logs:\n" "{pip_logs}").format(
                stderr=result.error, pip_logs=fp.read()
            )

    assert result.return_code == 0, render_errors()

    pex_pip_version = index_distributions(PEX(pex).resolve())[PIP_PROJECT_NAME]
    pex_setuptools_version = index_distributions(PEX(pex).resolve()).get(SETUPTOOLS_PROJECT_NAME)

    assert_venv_dists_conflicts(
        tmpdir,
        pex,
        baseline_venv_pip_version=baseline_venv_pip_version,
        baseline_venv_setuptools_version=baseline_venv_setuptools_version,
        expected_pip_version=pex_pip_version,
        expected_setuptools_version=pex_setuptools_version,
    )
