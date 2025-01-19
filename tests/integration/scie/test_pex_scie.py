# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import json
import os.path
import re
import shutil
import subprocess
import sys
from textwrap import dedent
from typing import Optional

import pytest

from pex.cache.dirs import CacheDir
from pex.common import safe_open
from pex.executables import chmod_plus_x, is_exe
from pex.fetcher import URLFetcher
from pex.layout import Layout
from pex.orderedset import OrderedSet
from pex.scie import SciePlatform, ScieStyle
from pex.targets import LocalInterpreter
from pex.typing import TYPE_CHECKING
from pex.version import __version__
from testing import IS_PYPY, PY_VER, make_env, run_pex_command
from testing.scie import skip_if_no_provider

if TYPE_CHECKING:
    from typing import Any, Iterable, List


@pytest.mark.parametrize(
    "scie_style", [pytest.param(style, id=str(style)) for style in ScieStyle.values()]
)
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=str(layout)) for layout in Layout.values()]
)
@pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--venv"], id="VENV"),
        pytest.param(["--sh-boot"], id="ZIPAPP-sh-boot"),
        pytest.param(["--venv", "--sh-boot"], id="VENV-sh-boot"),
    ],
)
def test_basic(
    tmpdir,  # type: Any
    scie_style,  # type: ScieStyle.Value
    layout,  # type: Layout.Value
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "cowsay.pex")
    result = run_pex_command(
        args=[
            "cowsay==5.0",
            "-c",
            "cowsay",
            "-o",
            pex,
            "--scie",
            str(scie_style),
            "--layout",
            str(layout),
        ]
        + execution_mode_args
    )
    if PY_VER < (3, 8) and not IS_PYPY:
        result.assert_failure(
            expected_error_re=r".*^{message}$".format(
                message=re.escape(
                    "You selected `--scie {style}`, but none of the selected targets have "
                    "compatible interpreters that can be embedded to form a scie:\n"
                    "{target}".format(
                        style=scie_style, target=LocalInterpreter.create().render_description()
                    )
                )
            ),
            re_flags=re.DOTALL | re.MULTILINE,
        )
        return
    if PY_VER == (3, 8) or PY_VER >= (3, 14):
        result.assert_failure(
            expected_error_re=(
                r".*"
                r"^Failed to build 1 scie:$"
                r".*"
                r"^Provider: No released assets found for release [0-9]{{8}} Python {version} "
                r"of flavor install_only\.$".format(version=".".join(map(str, PY_VER)))
            ),
            re_flags=re.DOTALL | re.MULTILINE,
        )
        return
    result.assert_success()

    scie = os.path.join(str(tmpdir), "cowsay")
    assert b"| PAR! |" in subprocess.check_output(args=[scie, "PAR!"], env=make_env(PATH=None))


@skip_if_no_provider
@pytest.mark.skipif(
    not any(
        is_exe(os.path.join(entry, "shasum"))
        for entry in os.environ.get("PATH", os.path.defpath).split(os.pathsep)
    ),
    reason="This test requires the `shasum` utility be available on the PATH.",
)
def test_hashes(tmpdir):
    # type: (Any) -> None

    pex = os.path.join(str(tmpdir), "cowsay")
    run_pex_command(
        args=[
            "cowsay==5.0",
            "-c",
            "cowsay",
            "-o",
            pex,
            "--scie",
            "lazy",
            "--scie-hash-alg",
            "sha256",
            "--scie-hash-alg",
            "sha512",
        ]
    ).assert_success()

    assert b"| PEX-scie wabbit! |" in subprocess.check_output(
        args=[pex, "PEX-scie wabbit!"], env=make_env(PATH=None)
    )

    for alg in "sha256", "sha512":
        shasum_file = "{pex}.{alg}".format(pex=pex, alg=alg)
        assert os.path.exists(shasum_file), "Expected {shasum_file} to be generated.".format(
            shasum_file=shasum_file
        )
        subprocess.check_call(args=["shasum", "-c", os.path.basename(shasum_file)], cwd=str(tmpdir))


def test_multiple_platforms(tmpdir):
    # type: (Any) -> None

    def create_scies(
        output_dir,  # type: str
        extra_args=(),  # type: Iterable[str]
    ):
        pex = os.path.join(output_dir, "cowsay.pex")
        run_pex_command(
            args=[
                "cowsay==5.0",
                "-c",
                "cowsay",
                "-o",
                pex,
                "--scie",
                "lazy",
                "--platform",
                "linux-aarch64-cp-39-cp39",
                "--platform",
                "linux-armv7l-cp-311-cp311",
                "--platform",
                "linux-ppc64le-cp-312-cp312",
                "--platform",
                "linux-s390x-cp-313-cp313",
                "--platform",
                "linux-x86_64-cp-310-cp310",
                "--platform",
                "macosx-10.9-arm64-cp-311-cp311",
                "--platform",
                "macosx-10.9-x86_64-cp-312-cp312",
            ]
            + list(extra_args)
        ).assert_success()

    python_version_by_platform = {
        SciePlatform.LINUX_AARCH64: "3.9",
        SciePlatform.LINUX_ARMV7L: "3.11",
        SciePlatform.LINUX_PPC64LE: "3.12",
        SciePlatform.LINUX_S390X: "3.13",
        SciePlatform.LINUX_X86_64: "3.10",
        SciePlatform.MACOS_AARCH64: "3.11",
        SciePlatform.MACOS_X86_64: "3.12",
    }
    assert SciePlatform.CURRENT in python_version_by_platform

    def assert_platforms(
        output_dir,  # type: str
        expected_platforms,  # type: Iterable[SciePlatform.Value]
    ):
        # type: (...) -> None

        all_output_files = set(
            path
            for path in os.listdir(output_dir)
            if os.path.isfile(os.path.join(output_dir, path))
        )
        for platform in OrderedSet(expected_platforms):
            python_version = python_version_by_platform[platform]
            binary = platform.qualified_binary_name("cowsay")
            assert binary in all_output_files
            all_output_files.remove(binary)
            scie = os.path.join(output_dir, binary)
            assert is_exe(scie), "Expected --scie build to produce a {binary} binary.".format(
                binary=binary
            )
            if platform is SciePlatform.CURRENT:
                assert b"| PEX-scie wabbit! |" in subprocess.check_output(
                    args=[scie, "PEX-scie wabbit!"], env=make_env(PATH=None)
                )
                assert (
                    python_version
                    == subprocess.check_output(
                        args=[
                            scie,
                            "-c",
                            "import sys; print('.'.join(map(str, sys.version_info[:2])))",
                        ],
                        env=make_env(PEX_INTERPRETER=1),
                    )
                    .decode("utf-8")
                    .strip()
                )
        assert {"cowsay.pex"} == all_output_files, (
            "Expected one output scie for each platform plus the original cowsay.pex. All expected "
            "scies were found, but the remaining files are: {remaining_files}".format(
                remaining_files=all_output_files
            )
        )

    all_platforms_output_dir = os.path.join(str(tmpdir), "all-platforms")
    create_scies(output_dir=all_platforms_output_dir)
    assert_platforms(
        output_dir=all_platforms_output_dir,
        expected_platforms=(
            SciePlatform.LINUX_AARCH64,
            SciePlatform.LINUX_ARMV7L,
            SciePlatform.LINUX_PPC64LE,
            SciePlatform.LINUX_S390X,
            SciePlatform.LINUX_X86_64,
            SciePlatform.MACOS_AARCH64,
            SciePlatform.MACOS_X86_64,
        ),
    )

    # Now restrict the PEX's implied natural platform set of 7 down to 2 or 3 using
    # `--scie-platform`.
    restricted_platforms_output_dir = os.path.join(str(tmpdir), "restricted-platforms")
    create_scies(
        output_dir=restricted_platforms_output_dir,
        extra_args=[
            "--scie-platform",
            "current",
            "--scie-platform",
            str(SciePlatform.LINUX_AARCH64),
            "--scie-platform",
            str(SciePlatform.LINUX_X86_64),
        ],
    )
    assert_platforms(
        output_dir=restricted_platforms_output_dir,
        expected_platforms=(
            SciePlatform.CURRENT,
            SciePlatform.LINUX_AARCH64,
            SciePlatform.LINUX_X86_64,
        ),
    )


PRINT_VERSION_SCRIPT = "import sys; print('.'.join(map(str, sys.version_info[:3])))"


def test_specified_interpreter(tmpdir):
    # type: (Any) -> None

    pex = os.path.join(str(tmpdir), "empty.pex")

    # We pick a specific version that is not in the latest release but is known to provide
    # distributions for all platforms Pex tests run on.
    if IS_PYPY:
        release_args = ["--scie-pypy-release", "v7.3.12"]
    else:
        release_args = ["--scie-pbs-release", "20230726"]
    run_pex_command(
        args=[
            "-o",
            pex,
            "--scie",
            "lazy",
            "--scie-python-version",
            "3.10.12",
        ]
        + release_args,
    ).assert_success()

    assert (
        ".".join(map(str, sys.version_info[:3]))
        == subprocess.check_output(args=[pex, "-c", PRINT_VERSION_SCRIPT]).decode("utf-8").strip()
    )

    scie = os.path.join(str(tmpdir), "empty")
    assert b"3.10.12\n" == subprocess.check_output(args=[scie, "-c", PRINT_VERSION_SCRIPT])


def test_specified_science_binary(tmpdir):
    # type: (Any) -> None

    local_science_binary = os.path.join(str(tmpdir), "science")
    with open(local_science_binary, "wb") as write_fp, URLFetcher().get_body_stream(
        "https://github.com/a-scie/lift/releases/download/v0.10.1/{binary}".format(
            binary=SciePlatform.CURRENT.qualified_binary_name("science")
        )
    ) as read_fp:
        shutil.copyfileobj(read_fp, write_fp)
    chmod_plus_x(local_science_binary)

    pex_root = os.path.join(str(tmpdir), "pex_root")
    scie = os.path.join(str(tmpdir), "cowsay")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "cowsay==6.0",
            "-c",
            "cowsay",
            "--scie",
            "lazy",
            "--scie-python-version",
            "3.10",
            "-o",
            scie,
            "--scie-science-binary",
            local_science_binary,
        ],
        env=make_env(PATH=None),
    ).assert_success()

    assert b"| Alternative SCIENCE Facts! |" in subprocess.check_output(
        args=[scie, "-t", "Alternative SCIENCE Facts!"]
    )

    cached_science_binaries = glob.glob(
        os.path.join(
            CacheDir.SCIES.path("science", pex_root=pex_root),
            "*",
            "bin",
            "science",
        )
    )
    assert 0 == len(
        cached_science_binaries
    ), "Expected the local science binary to be used but not cached."
    assert (
        "0.10.1"
        == subprocess.check_output(args=[local_science_binary, "--version"]).decode("utf-8").strip()
    )


@pytest.mark.skipif(IS_PYPY, reason="This test relies on PBS distribution URLs")
def test_custom_lazy_urls(tmpdir):
    # type: (Any) -> None

    scie = os.path.join(str(tmpdir), "empty")
    run_pex_command(
        args=[
            "-o",
            scie,
            "--scie",
            "lazy",
            "--scie-pbs-release",
            "20221002",
            "--scie-python-version",
            "3.10.7",
        ],
    ).assert_success()

    assert b"3.10.7\n" == subprocess.check_output(args=[scie, "-c", PRINT_VERSION_SCRIPT])

    pex_bootstrap_urls = os.path.join(str(tmpdir), "pex_bootstrap_urls.json")

    def make_20221002_3_10_7_file(platform):
        # type: (str) -> str
        return "cpython-3.10.7+20221002-{platform}-install_only.tar.gz".format(platform=platform)

    def make_20240415_3_10_14_url(platform):
        # type: (str) -> str
        return (
            "https://github.com/astral-sh/python-build-standalone/releases/download/20240415/"
            "cpython-3.10.14+20240415-{platform}-install_only.tar.gz".format(platform=platform)
        )

    with open(pex_bootstrap_urls, "w") as fp:
        json.dump(
            {
                "ptex": {
                    make_20221002_3_10_7_file(platform): make_20240415_3_10_14_url(platform)
                    for platform in (
                        "aarch64-apple-darwin",
                        "x86_64-apple-darwin",
                        "aarch64-unknown-linux-gnu",
                        "armv7-unknown-linux-gnueabihf",
                        "ppc64le-unknown-linux-gnu",
                        "s390x-unknown-linux-gnu",
                        "x86_64-unknown-linux-gnu",
                    )
                }
            },
            fp,
        )

    process = subprocess.Popen(
        args=[scie, "-c", PRINT_VERSION_SCRIPT],
        env=make_env(
            PEX_BOOTSTRAP_URLS=pex_bootstrap_urls, SCIE_BASE=os.path.join(str(tmpdir), "nce")
        ),
        stderr=subprocess.PIPE,
    )
    _, stderr = process.communicate()
    assert 0 != process.returncode, (
        "Expected PEX_BOOTSTRAP_URLS to be used and the resulting fetched interpreter distribution "
        "to fail its digest check."
    )

    expected_platform = None  # type: Optional[str]
    if SciePlatform.CURRENT is SciePlatform.LINUX_AARCH64:
        expected_platform = "aarch64-unknown-linux-gnu"
    elif SciePlatform.CURRENT is SciePlatform.LINUX_ARMV7L:
        expected_platform = "armv7-unknown-linux-gnueabihf"
    elif SciePlatform.CURRENT is SciePlatform.LINUX_PPC64LE:
        expected_platform = "ppc64le-unknown-linux-gnu"
    elif SciePlatform.CURRENT is SciePlatform.LINUX_S390X:
        expected_platform = "s390x-unknown-linux-gnu"
    elif SciePlatform.CURRENT is SciePlatform.LINUX_X86_64:
        expected_platform = "x86_64-unknown-linux-gnu"
    elif SciePlatform.CURRENT is SciePlatform.MACOS_AARCH64:
        expected_platform = "aarch64-apple-darwin"
    elif SciePlatform.CURRENT is SciePlatform.MACOS_X86_64:
        expected_platform = "x86_64-apple-darwin"
    assert expected_platform is not None

    assert re.match(
        r"^.*Population of work directory failed: The tar\.gz destination .*{expected_file_name} "
        r"of size \d+ had unexpected hash: [a-f0-9]{{64}}$.*".format(
            expected_file_name=re.escape(make_20221002_3_10_7_file(expected_platform))
        ),
        stderr.decode("utf-8"),
        flags=re.DOTALL | re.MULTILINE,
    ), stderr.decode("utf-8")


def test_pex_pex_scie(
    tmpdir,  # type: Any
    pex_project_dir,  # type: Any
):
    # type: (...) -> None

    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[
            pex_project_dir,
            "-c",
            "pex",
            "--scie",
            "lazy",
            "--scie-python-version",
            "3.10",
            "-o",
            pex,
        ]
    ).assert_success()
    assert (
        __version__
        == subprocess.check_output(args=[pex, "-V"], env=make_env(PATH=None))
        .decode("utf-8")
        .strip()
    )


def make_project(
    tmpdir,  # type: Any
    name,  # type: str
):
    # type: (...) -> str

    project_dir = os.path.join(str(tmpdir), name)
    with safe_open(os.path.join(project_dir, "{name}.py".format(name=name)), "w") as fp:
        fp.write(
            dedent(
                """\
                from __future__ import print_function

                import functools
                import os
                import sys


                def _print(label=""):
                    env_var = {name!r}.upper()
                    env_value = os.environ.get(env_var)
                    if env_value:
                        print(
                            "{{env_var}}={{env_value}} ".format(
                                env_var=env_var, env_value=env_value
                            ),
                            end="",
                        )
                    print("{name}{{label}}:".format(label=label), *sys.argv[1:])


                one = functools.partial(_print, "1")
                two = functools.partial(_print, "2")
                three = functools.partial(_print, "3")


                if __name__ == "__main__":
                    _print()
                """
            ).format(name=name)
        )
    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup


                setup(
                    name={name!r},
                    version="0.1.0",
                    entry_points={{
                        "console_scripts": [
                            "{name}-script1 = {name}:one",
                            "{name}-script2 = {name}:two",
                        ],
                    }},
                    py_modules=[{name!r}],
                )
                """
            ).format(name=name)
        )
    return project_dir


@pytest.fixture
def foo(tmpdir):
    # type: (Any) -> str
    return make_project(tmpdir, "foo")


@pytest.fixture
def bar(tmpdir):
    # type: (Any) -> str
    return make_project(tmpdir, "bar")


@skip_if_no_provider
@pytest.mark.parametrize(
    "execution_mode_args",
    [
        pytest.param([], id="ZIPAPP"),
        pytest.param(["--venv"], id="VENV"),
    ],
)
def test_scie_busybox_console_scripts_all(
    tmpdir,  # type: Any
    foo,  # type: str
    bar,  # type: str
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    busybox = os.path.join(str(tmpdir), "busybox")
    run_pex_command(
        args=[foo, bar, "--scie", "lazy", "--scie-busybox", "@", "-o", busybox]
        + execution_mode_args
    ).assert_success()

    assert b"foo1: all\n" == subprocess.check_output(args=[busybox, "foo-script1", "all"])
    assert b"foo2: all\n" == subprocess.check_output(args=[busybox, "foo-script2", "all"])
    assert b"bar1: all\n" == subprocess.check_output(args=[busybox, "bar-script1", "all"])
    assert b"bar2: all\n" == subprocess.check_output(args=[busybox, "bar-script2", "all"])

    bin_dir = os.path.join(str(tmpdir), "bin_dir")
    subprocess.check_call(args=[busybox, bin_dir], env=make_env(SCIE="install"))
    assert sorted(["foo-script1", "foo-script2", "bar-script1", "bar-script2"]) == sorted(
        os.listdir(bin_dir)
    )

    assert b"foo1: all\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "foo-script1"), "all"]
    )
    assert b"foo2: all\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "foo-script2"), "all"]
    )
    assert b"bar1: all\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "bar-script1"), "all"]
    )
    assert b"bar2: all\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "bar-script2"), "all"]
    )


@skip_if_no_provider
def test_scie_busybox_console_scripts_add_distribution(
    tmpdir,  # type: Any
    foo,  # type: str
    bar,  # type: str
):
    # type: (...) -> None

    busybox = os.path.join(str(tmpdir), "busybox")
    run_pex_command(
        args=[foo, bar, "--scie", "lazy", "--scie-busybox", "@foo", "-o", busybox]
    ).assert_success()

    assert b"foo1: add-dist\n" == subprocess.check_output(args=[busybox, "foo-script1", "add-dist"])
    assert b"foo2: add-dist\n" == subprocess.check_output(args=[busybox, "foo-script2", "add-dist"])

    bin_dir = os.path.join(str(tmpdir), "bin_dir")
    subprocess.check_call(args=[busybox, bin_dir], env=make_env(SCIE="install"))
    assert sorted(["foo-script1", "foo-script2"]) == sorted(os.listdir(bin_dir))

    assert b"foo1: add-dist\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "foo-script1"), "add-dist"]
    )
    assert b"foo2: add-dist\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "foo-script2"), "add-dist"]
    )


@skip_if_no_provider
def test_scie_busybox_console_scripts_remove_distribution(
    tmpdir,  # type: Any
    foo,  # type: str
    bar,  # type: str
):
    # type: (...) -> None

    busybox = os.path.join(str(tmpdir), "busybox")
    run_pex_command(
        args=[
            foo,
            bar,
            "--scie",
            "lazy",
            "--scie-busybox",
            "@",
            "--scie-busybox",
            "!@foo",
            "-o",
            busybox,
        ],
        quiet=True,
    ).assert_success()

    assert b"bar1: del-dist\n" == subprocess.check_output(args=[busybox, "bar-script1", "del-dist"])
    assert b"bar2: del-dist\n" == subprocess.check_output(args=[busybox, "bar-script2", "del-dist"])

    bin_dir = os.path.join(str(tmpdir), "bin_dir")
    subprocess.check_call(args=[busybox, bin_dir], env=make_env(SCIE="install"))
    assert sorted(["bar-script1", "bar-script2"]) == sorted(os.listdir(bin_dir))

    assert b"bar1: del-dist\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "bar-script1"), "del-dist"]
    )
    assert b"bar2: del-dist\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "bar-script2"), "del-dist"]
    )


@skip_if_no_provider
def test_scie_busybox_console_scripts_remove_script(
    tmpdir,  # type: Any
    foo,  # type: str
    bar,  # type: str
):
    # type: (...) -> None

    busybox = os.path.join(str(tmpdir), "busybox")
    run_pex_command(
        args=[foo, bar, "--scie", "lazy", "--scie-busybox", "@foo,!foo-script1", "-o", busybox],
        quiet=True,
    ).assert_success()

    assert b"foo2: del-script\n" == subprocess.check_output(
        args=[busybox, "foo-script2", "del-script"]
    )

    bin_dir = os.path.join(str(tmpdir), "bin_dir")
    subprocess.check_call(args=[busybox, bin_dir], env=make_env(SCIE="install"))
    assert ["foo-script2"] == os.listdir(bin_dir)

    assert b"foo2: del-script\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "foo-script2"), "del-script"]
    )


@skip_if_no_provider
def test_scie_busybox_console_scripts_add_script(
    tmpdir,  # type: Any
    foo,  # type: str
    bar,  # type: str
):
    # type: (...) -> None

    busybox = os.path.join(str(tmpdir), "busybox")
    run_pex_command(
        args=[foo, bar, "--scie", "lazy", "--scie-busybox", "@bar,foo-script1", "-o", busybox],
        quiet=True,
    ).assert_success()

    assert b"foo1: add-script\n" == subprocess.check_output(
        args=[busybox, "foo-script1", "add-script"]
    )
    assert b"bar1: add-script\n" == subprocess.check_output(
        args=[busybox, "bar-script1", "add-script"]
    )
    assert b"bar2: add-script\n" == subprocess.check_output(
        args=[busybox, "bar-script2", "add-script"]
    )

    bin_dir = os.path.join(str(tmpdir), "bin_dir")
    subprocess.check_call(args=[busybox, bin_dir], env=make_env(SCIE="install"))
    assert sorted(["foo-script1", "bar-script1", "bar-script2"]) == sorted(os.listdir(bin_dir))

    assert b"foo1: add-script\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "foo-script1"), "add-script"]
    )
    assert b"bar1: add-script\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "bar-script1"), "add-script"]
    )
    assert b"bar2: add-script\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "bar-script2"), "add-script"]
    )


execution_mode_args = pytest.mark.parametrize(
    "execution_mode_args", [pytest.param([], id="ZIPAPP"), pytest.param(["--venv"], id="VENV")]
)


@skip_if_no_provider
@execution_mode_args
def test_scie_busybox_console_script_inject_args(
    tmpdir,  # type: Any
    foo,  # type: str
    bar,  # type: str
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    busybox = os.path.join(str(tmpdir), "busybox")
    run_pex_command(
        args=[
            foo,
            bar,
            "-c",
            "foo-script1",
            "--inject-args",
            "--injected yes",
            "--scie",
            "lazy",
            "--scie-busybox",
            "@bar,foo-script1",
            "-o",
            busybox,
        ]
        + execution_mode_args,
        quiet=True,
    ).assert_success()

    assert b"foo1: --injected yes injected?\n" == subprocess.check_output(
        args=[busybox, "foo-script1", "injected?"]
    )
    assert b"bar1: injected?\n" == subprocess.check_output(
        args=[busybox, "bar-script1", "injected?"]
    )
    assert b"bar2: injected?\n" == subprocess.check_output(
        args=[busybox, "bar-script2", "injected?"]
    )

    bin_dir = os.path.join(str(tmpdir), "bin_dir")
    subprocess.check_call(args=[busybox, bin_dir], env=make_env(SCIE="install"))
    assert sorted(["foo-script1", "bar-script1", "bar-script2"]) == sorted(os.listdir(bin_dir))

    assert b"foo1: --injected yes injected?\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "foo-script1"), "injected?"]
    )
    assert b"bar1: injected?\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "bar-script1"), "injected?"]
    )
    assert b"bar2: injected?\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "bar-script2"), "injected?"]
    )


@skip_if_no_provider
@execution_mode_args
def test_scie_busybox_console_script_inject_env(
    tmpdir,  # type: Any
    foo,  # type: str
    bar,  # type: str
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    busybox = os.path.join(str(tmpdir), "busybox")
    run_pex_command(
        args=[
            foo,
            bar,
            "-m",
            "foo:one",
            "--inject-env",
            "FOO=bar",
            "--scie",
            "lazy",
            "--scie-busybox",
            "@bar,foo-script1",
            "-o",
            busybox,
        ]
        + execution_mode_args,
        quiet=True,
    ).assert_success()

    assert b"FOO=bar foo1: injected?\n" == subprocess.check_output(
        args=[busybox, "foo-script1", "injected?"]
    )
    assert b"FOO=baz foo1: injected?\n" == subprocess.check_output(
        args=[busybox, "foo-script1", "injected?"], env=make_env(FOO="baz")
    )
    assert b"bar1: injected?\n" == subprocess.check_output(
        args=[busybox, "bar-script1", "injected?"]
    )
    assert b"bar2: injected?\n" == subprocess.check_output(
        args=[busybox, "bar-script2", "injected?"]
    )

    bin_dir = os.path.join(str(tmpdir), "bin_dir")
    subprocess.check_call(args=[busybox, bin_dir], env=make_env(SCIE="install"))
    assert sorted(["foo-script1", "bar-script1", "bar-script2"]) == sorted(os.listdir(bin_dir))

    assert b"FOO=bar foo1: injected?\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "foo-script1"), "injected?"]
    )
    assert b"FOO=baz foo1: injected?\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "foo-script1"), "injected?"], env=make_env(FOO="baz")
    )
    assert b"bar1: injected?\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "bar-script1"), "injected?"]
    )
    assert b"bar2: injected?\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "bar-script2"), "injected?"]
    )


@skip_if_no_provider
@execution_mode_args
def test_scie_busybox_console_script_inject_python_args(
    tmpdir,  # type: Any
    foo,  # type: str
    bar,  # type: str
    execution_mode_args,  # type: List[str]
):
    # type: (...) -> None

    busybox = os.path.join(str(tmpdir), "busybox")
    run_pex_command(
        args=[
            foo,
            bar,
            "-c",
            "foo-script1",
            "--inject-python-args=-v",
            "--scie",
            "lazy",
            "--scie-busybox",
            "@bar,foo-script-ad-hoc=foo:one",
            "-o",
            busybox,
        ]
        + execution_mode_args,
        quiet=True,
    ).assert_success()

    def assert_output(
        args,  # type: List[str]
        expected_output_prefix,  # type: str
        expect_python_verbose,  # type: bool
    ):
        # type: (...) -> None
        output_lines = (
            subprocess.check_output(args=args + ["injected?"], stderr=subprocess.STDOUT)
            .decode("utf-8")
            .splitlines()
        )
        assert (
            "{expected_output_prefix}: injected?".format(
                expected_output_prefix=expected_output_prefix
            )
            in output_lines
        )
        stderr_import_logging = any(line.startswith("import ") for line in output_lines)
        assert expect_python_verbose is stderr_import_logging, os.linesep.join(output_lines)

    assert_output(
        args=[busybox, "foo-script-ad-hoc"],
        expected_output_prefix="foo1",
        expect_python_verbose=True,
    )
    assert_output(
        args=[busybox, "bar-script1"], expected_output_prefix="bar1", expect_python_verbose=False
    )
    assert_output(
        args=[busybox, "bar-script2"], expected_output_prefix="bar2", expect_python_verbose=False
    )

    bin_dir = os.path.join(str(tmpdir), "bin_dir")
    subprocess.check_call(args=[busybox, bin_dir], env=make_env(SCIE="install"))
    assert sorted(["foo-script-ad-hoc", "bar-script1", "bar-script2"]) == sorted(
        os.listdir(bin_dir)
    )

    assert_output(
        args=[os.path.join(bin_dir, "foo-script-ad-hoc")],
        expected_output_prefix="foo1",
        expect_python_verbose=True,
    )
    assert_output(
        args=[os.path.join(bin_dir, "bar-script1")],
        expected_output_prefix="bar1",
        expect_python_verbose=False,
    )
    assert_output(
        args=[os.path.join(bin_dir, "bar-script2")],
        expected_output_prefix="bar2",
        expect_python_verbose=False,
    )


@skip_if_no_provider
def test_scie_busybox_module_entry_points(
    tmpdir,  # type: Any
    foo,  # type: str
    bar,  # type: str
):
    # type: (...) -> None

    busybox = os.path.join(str(tmpdir), "busybox")
    run_pex_command(
        args=[
            foo,
            bar,
            "--scie",
            "lazy",
            "--scie-busybox",
            "bar-mod=bar,foo=foo:three",
            "-o",
            busybox,
        ],
        quiet=True,
    ).assert_success()

    assert b"bar: mep\n" == subprocess.check_output(args=[busybox, "bar-mod", "mep"])
    assert b"foo3: mep\n" == subprocess.check_output(args=[busybox, "foo", "mep"])

    bin_dir = os.path.join(str(tmpdir), "bin_dir")
    subprocess.check_call(args=[busybox, bin_dir], env=make_env(SCIE="install"))
    assert sorted(["bar-mod", "foo"]) == sorted(os.listdir(bin_dir))

    assert b"bar: mep\n" == subprocess.check_output(args=[os.path.join(bin_dir, "bar-mod"), "mep"])
    assert b"foo3: mep\n" == subprocess.check_output(args=[os.path.join(bin_dir, "foo"), "mep"])


@skip_if_no_provider
def test_scie_busybox_module_entry_point_injections(
    tmpdir,  # type: Any
    foo,  # type: str
    bar,  # type: str
):
    # type: (...) -> None

    busybox = os.path.join(str(tmpdir), "busybox")
    run_pex_command(
        args=[
            foo,
            bar,
            "-m",
            "bar",
            "--inject-args",
            "--injected yes",
            "--scie",
            "lazy",
            "--scie-busybox",
            "bar-mod=bar,foo=foo:three",
            "-o",
            busybox,
        ],
        quiet=True,
    ).assert_success()

    assert b"bar: --injected yes injected?\n" == subprocess.check_output(
        args=[busybox, "bar-mod", "injected?"]
    )
    assert b"foo3: injected?\n" == subprocess.check_output(args=[busybox, "foo", "injected?"])

    bin_dir = os.path.join(str(tmpdir), "bin_dir")
    subprocess.check_call(args=[busybox, bin_dir], env=make_env(SCIE="install"))
    assert sorted(["bar-mod", "foo"]) == sorted(os.listdir(bin_dir))

    assert b"bar: --injected yes injected?\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "bar-mod"), "injected?"]
    )
    assert b"foo3: injected?\n" == subprocess.check_output(
        args=[os.path.join(bin_dir, "foo"), "injected?"]
    )


@skip_if_no_provider
def test_script_not_found(
    tmpdir,  # type: Any
    foo,  # type: str
    bar,  # type: str
):
    # type: (...) -> None

    busybox = os.path.join(str(tmpdir), "busybox")
    run_pex_command(
        args=[
            foo,
            bar,
            "--scie",
            "lazy",
            "--scie-busybox",
            "foo-script1@foo,foo-script2@bar,bar-script1@foo,bar-script2@bar,baz",
            "-o",
            busybox,
        ],
        quiet=True,
    ).assert_failure(
        expected_error_re=re.escape(
            dedent(
                """\
                Failed to resolve some console scripts:
                + Could not find script: baz
                + Found scripts in the wrong projects:
                  foo-script2@bar found in foo
                  bar-script1@foo found in bar
                """
            )
        )
    )


@pytest.mark.skipif(IS_PYPY, reason="The --scie-pbs-stripped option only applies to CPython scies.")
def test_pbs_stripped(tmpdir):
    # type: (Any) -> None

    def create_python_scie(
        scie_path,  # type: str
        *extra_args  # type: str
    ):
        # type: (...) -> int

        run_pex_command(
            args=["-o", scie_path, "--scie", "eager", "--scie-python-version", "3.12"]
            + list(extra_args)
        ).assert_success()
        assert b"3.12\n" == subprocess.check_output(
            args=[scie_path, "-c", "import sys; print('.'.join(map(str, sys.version_info[:2])))"]
        )
        return os.path.getsize(scie_path)

    pex_scie_stripped = os.path.join(str(tmpdir), "pex-scie-stripped")
    pex_scie_stripped_size = create_python_scie(pex_scie_stripped, "--scie-pbs-stripped")

    pex_scie = os.path.join(str(tmpdir), "pex-scie")
    pex_scie_size = create_python_scie(pex_scie)

    assert pex_scie_stripped_size < pex_scie_size, (
        "Expected the stripped scie to be smaller, but found:\n"
        "{pex_scie_stripped}: {pex_scie_stripped_size} bytes\n"
        "{pex_scie}: {pex_scie_size} bytes\n"
    ).format(
        pex_scie_stripped=pex_scie_stripped,
        pex_scie_stripped_size=pex_scie_stripped_size,
        pex_scie=pex_scie,
        pex_scie_size=pex_scie_size,
    )


@skip_if_no_provider
def test_scie_only(tmpdir):
    # type: (Any) -> None

    dist_dir = os.path.join(str(tmpdir), "dist")
    output_file = os.path.join(dist_dir, "app.pex")
    run_pex_command(args=["--scie", "lazy", "-o", output_file]).assert_success()
    assert sorted(["app.pex", "app"]) == sorted(os.listdir(dist_dir))

    shutil.rmtree(dist_dir)
    run_pex_command(args=["--scie", "lazy", "--scie-only", "-o", output_file]).assert_success()
    assert ["app"] == os.listdir(dist_dir)


@skip_if_no_provider
def test_scie_name_style_platform_file_suffix(tmpdir):
    # type: (Any) -> None

    dist_dir = os.path.join(str(tmpdir), "dist")
    output_file = os.path.join(dist_dir, "app")
    run_pex_command(
        args=["--scie", "lazy", "--scie-name-style", "platform-file-suffix", "-o", output_file]
    ).assert_success()
    assert sorted(["app", SciePlatform.CURRENT.qualified_binary_name("app")]) == sorted(
        os.listdir(dist_dir)
    )


@skip_if_no_provider
def test_scie_name_style_platform_parent_dir(tmpdir):
    # type: (Any) -> None

    foreign_platform = next(
        plat for plat in SciePlatform.values() if SciePlatform.CURRENT is not plat
    )
    dist_dir = os.path.join(str(tmpdir), "dist")
    output_file = os.path.join(dist_dir, "app")
    run_pex_command(
        args=[
            "--scie",
            "lazy",
            "--scie-platform",
            str(foreign_platform),
            "--scie-name-style",
            "platform-parent-dir",
            "-o",
            output_file,
        ]
    ).assert_success()
    assert sorted(["app", foreign_platform.value]) == sorted(os.listdir(dist_dir))
    assert [foreign_platform.binary_name("app")] == os.listdir(
        os.path.join(dist_dir, foreign_platform.value)
    )
