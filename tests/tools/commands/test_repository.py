# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import filecmp
import itertools
import json
import os
import signal
import subprocess
from textwrap import dedent

import pytest

from pex.common import DETERMINISTIC_DATETIME, open_zip, safe_open, temporary_dir
from pex.testing import PY310, ensure_python_venv, run_command_with_jitter, run_pex_command
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.third_party.pkg_resources import Distribution, Requirement
from pex.typing import TYPE_CHECKING
from pex.util import DistributionHelper

if TYPE_CHECKING:
    from typing import Any, Dict, Iterator


@pytest.fixture(scope="module")
def pex():
    # type: () -> Iterator[str]
    with temporary_dir() as tmpdir:
        pex_path = os.path.join(tmpdir, "example.pex")

        src = os.path.join(tmpdir, "src")
        with safe_open(os.path.join(src, "data", "url.txt"), "w") as fp:
            fp.write("https://example.com")
        with safe_open(os.path.join(src, "main.py"), "w") as fp:
            fp.write(
                dedent(
                    """\
                    from __future__ import print_function

                    import os
                    import sys

                    import requests


                    def do():
                        with open(os.path.join(os.path.dirname(__file__), "data", "url.txt")) as fp:
                            url = fp.read().strip()
                        print("Fetching from {} ...".format(url))
                        print(requests.get(url).text, file=sys.stderr)
                    """
                )
            )
        result = run_pex_command(
            args=[
                "-D",
                src,
                "requests==2.25.1",
                "-e",
                "main:do",
                "--interpreter-constraint",
                "CPython>=2.7,<4",
                "-o",
                pex_path,
                "--include-tools",
            ],
        )
        result.assert_success()
        yield os.path.realpath(pex_path)


@pytest.fixture(scope="module")
def pex_tools_env():
    # type: () -> Dict[str, str]
    env = os.environ.copy()
    env.update(PEX_TOOLS="1")
    return env


def test_info(pex, pex_tools_env):
    # type: (str, Dict[str, str]) -> None
    output = subprocess.check_output(args=[pex, "repository", "info"], env=pex_tools_env)
    distributions = {}
    for line in output.decode("utf-8").splitlines():
        name, version, location = line.split(" ", 2)
        distribution = DistributionHelper.distribution_from_path(location)
        assert isinstance(distribution, Distribution)
        assert name == distribution.project_name
        assert version == distribution.version
        distributions[name] = version

    assert {"certifi", "chardet", "idna", "requests", "urllib3"} == set(distributions.keys())
    assert "2.25.1" == distributions["requests"]


def test_info_verbose(pex, pex_tools_env):
    # type: (str, Dict[str, str]) -> None
    output = subprocess.check_output(args=[pex, "repository", "info", "-v"], env=pex_tools_env)
    infos = {}
    for line in output.decode("utf-8").splitlines():
        info = json.loads(line)
        distribution = DistributionHelper.distribution_from_path(info["location"])
        assert isinstance(distribution, Distribution)
        project_name = info["project_name"]
        assert distribution.project_name == project_name
        assert distribution.version == info["version"]
        infos[project_name] = info

    assert {"certifi", "chardet", "idna", "requests", "urllib3"} == set(infos.keys())

    requests_info = infos["requests"]
    assert "2.25.1" == requests_info["version"]
    assert SpecifierSet("!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*,>=2.7") == SpecifierSet(
        requests_info["requires_python"]
    )
    assert {
        Requirement.parse(req)
        for req in (
            'PySocks!=1.5.7,>=1.5.6; extra == "socks"',
            "certifi>=2017.4.17",
            "chardet<5,>=3.0.2",
            'cryptography>=1.3.4; extra == "security"',
            "idna<3,>=2.5",
            'pyOpenSSL>=0.14; extra == "security"',
            "urllib3<1.27,>=1.21.1",
            'win-inet-pton; (sys_platform == "win32" and python_version == "2.7") and extra == "socks"',
        )
    } == {Requirement.parse(req) for req in requests_info["requires_dists"]}


def test_extract_deterministic_timestamp(pex, pex_tools_env, tmpdir):
    deterministic_date_time = (
        DETERMINISTIC_DATETIME.year,
        DETERMINISTIC_DATETIME.month,
        DETERMINISTIC_DATETIME.day,
        DETERMINISTIC_DATETIME.hour,
        DETERMINISTIC_DATETIME.minute,
        DETERMINISTIC_DATETIME.second,
    )

    deterministic_dists_dir = os.path.join(str(tmpdir), "deterministic-dists")
    subprocess.check_call(
        args=[pex, "repository", "extract", "-f", deterministic_dists_dir], env=pex_tools_env
    )
    with open_zip(
        os.path.join(deterministic_dists_dir, "requests-2.25.1-py2.py3-none-any.whl")
    ) as zipfile:
        infolist = zipfile.infolist()
        assert len(infolist) > 0
        for info in infolist:
            assert deterministic_date_time == info.date_time

    non_deterministic_dists_dir = os.path.join(str(tmpdir), "non_deterministic_dists_dir")
    subprocess.check_call(
        args=[pex, "repository", "extract", "-f", non_deterministic_dists_dir, "--use-system-time"],
        env=pex_tools_env,
    )
    with open_zip(
        os.path.join(non_deterministic_dists_dir, "requests-2.25.1-py2.py3-none-any.whl")
    ) as zipfile:
        infolist = zipfile.infolist()
        assert len(infolist) > 0
        for info in infolist:
            assert deterministic_date_time != info.date_time


def test_extract_non_deterministic_wheels(pex, pex_tools_env):
    dist_dirs = run_command_with_jitter(
        args=[pex, "repository", "extract", "--use-system-time"],
        path_argument="-f",
        extra_env=pex_tools_env,
        count=3,
    )
    for dists_dir1, dists_dir2 in itertools.combinations(dist_dirs, 2):
        dists1 = sorted(os.listdir(dists_dir1))
        assert len(dists1) > 1
        assert dists1 == sorted(os.listdir(dists_dir2))

        same, different, non_reg = filecmp.cmpfiles(
            dists_dir1, dists_dir2, common=dists1, shallow=False
        )
        assert not same
        assert not non_reg
        assert sorted(dists1) == sorted(different)


def test_extract_deterministic_wheels(pex, pex_tools_env):
    # We already have tests that ensure PEX file creation is deterministic; so here we just test
    # that extracting wheels from a fixed PEX file is also deterministic.

    dist_dirs = run_command_with_jitter(
        args=[pex, "repository", "extract"], path_argument="-f", extra_env=pex_tools_env, count=3
    )
    dists_dir1 = dist_dirs.pop()
    dists1 = sorted(os.listdir(dists_dir1))
    assert len(dists1) > 1
    for dists_dir2 in dist_dirs:
        assert dists1 == sorted(os.listdir(dists_dir2))
        same, different, non_reg = filecmp.cmpfiles(
            dists_dir1, dists_dir2, common=dists1, shallow=False
        )
        assert not different
        assert not non_reg
        assert sorted(dists1) == sorted(same)


def test_extract_lifecycle(pex, pex_tools_env, tmpdir):
    # type: (str, Dict[str, str], Any) -> None
    dists_dir = os.path.join(str(tmpdir), "dists")
    pid_file = os.path.join(str(tmpdir), "pid")
    os.mkfifo(pid_file)
    find_links_server = subprocess.Popen(
        args=[
            pex,
            "repository",
            "extract",
            "--serve",
            "--sources",
            "--dest-dir",
            dists_dir,
            "--pid-file",
            pid_file,
        ],
        env=pex_tools_env,
        stdout=subprocess.PIPE,
    )
    with open(pid_file) as fp:
        _, port = fp.read().strip().split(":", 1)
    example_sdist_pex = os.path.join(str(tmpdir), "example-sdist.pex")
    find_links_url = "http://localhost:{}".format(port)
    result = run_pex_command(
        args=[
            "--no-pypi",
            "--find-links",
            find_links_url,
            "example",
            "-c",
            "example",
            "-o",
            example_sdist_pex,
        ]
    )
    result.assert_success()

    _, pip = ensure_python_venv(PY310)
    subprocess.check_call(
        args=[pip, "install", "--no-index", "--find-links", find_links_url, "example"]
    )
    example_console_script = os.path.join(os.path.dirname(pip), "example")

    find_links_server.send_signal(signal.SIGQUIT)
    assert -1 * int(signal.SIGQUIT) == find_links_server.wait()

    expected_output = b"Fetching from https://example.com ...\n"
    assert expected_output == subprocess.check_output(args=[example_sdist_pex])
    assert expected_output == subprocess.check_output(args=[example_console_script])
