# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import re
import sys
from textwrap import dedent

import pytest

from pex.cache.dirs import VenvDirs
from pex.common import safe_open
from pex.typing import TYPE_CHECKING
from pex.version import __version__
from testing import run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    import colors  # vendor:skip
else:
    from pex.third_party import colors

skip_if_locked_dev_cmd_not_compatible = pytest.mark.skipif(
    sys.version_info[:2] < (3, 9),
    reason=(
        "The dev-cmd project started shipping embedded locks when it moved to supporting "
        "Python>=3.9."
    ),
)


@pytest.fixture(scope="session")
def dev_cmd_version():
    # type: () -> str

    result = run_pex_command(args=["dev-cmd", "-c", "dev-cmd", "--", "-V"])
    result.assert_success()
    return str(result.output)


@skip_if_locked_dev_cmd_not_compatible
def test_nominal(dev_cmd_version):
    # type: (str) -> None

    run_pex3(
        "run",
        "--from",
        "dev-cmd=={version}".format(version=dev_cmd_version.strip()),
        "dev-cmd",
        "-V",
    ).assert_success(expected_output_re=re.escape(dev_cmd_version))


@skip_if_locked_dev_cmd_not_compatible
def test_locked_wheel(dev_cmd_version):
    # type: (str) -> None

    run_pex3(
        "run",
        "--only-wheel",
        "dev-cmd",
        "--from",
        "dev-cmd=={version}".format(version=dev_cmd_version.strip()),
        "--locked",
        "require",
        "dev-cmd",
        "-V",
    ).assert_success(expected_output_re=re.escape(dev_cmd_version))


@skip_if_locked_dev_cmd_not_compatible
def test_locked_sdist(dev_cmd_version):
    # type: (str) -> None

    run_pex3(
        "run",
        "--only-build",
        "dev-cmd",
        "--from",
        "dev-cmd=={version}".format(version=dev_cmd_version.strip()),
        "--locked",
        "require",
        "dev-cmd",
        "-V",
    ).assert_success(expected_output_re=re.escape(dev_cmd_version))


def test_locked_require_error(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")

    run_pex3("run", "--pex-root", pex_root, "cowsay<6", "Moo!").assert_success(
        expected_output_re=r".*| Moo! |.*", re_flags=re.MULTILINE | re.DOTALL
    )

    # N.B.: Although we now require a lock, the tool venv is cached; so we should get no error.
    run_pex3(
        "run", "--pex-root", pex_root, "--locked", "require", "cowsay<6", "Moo!"
    ).assert_success(expected_output_re=r".*| Moo! |.*", re_flags=re.MULTILINE | re.DOTALL)

    run_pex3(
        "run", "--pex-root", pex_root, "--locked", "require", "--refresh", "cowsay<6", "Moo!"
    ).assert_failure(
        expected_error_re=r".*^A tool lock file was required but none was found\.$.*",
        re_flags=re.MULTILINE | re.DOTALL,
    )


def test_locked_require_backoff(tmpdir):
    # type: (Tempdir) -> None

    pex_root = tmpdir.join("pex-root")

    run_pex3(
        "run", "--pex-root", pex_root, "--locked", "require", "--refresh", "cowsay<6", "Moo!"
    ).assert_failure(
        expected_error_re=r".*^A tool lock file was required but none was found\.$.*",
        re_flags=re.MULTILINE | re.DOTALL,
    )

    # We should go back to success in auto mode.
    run_pex3("run", "--pex-root", pex_root, "cowsay<6", "Moo!").assert_success(
        expected_output_re=r".*| Moo! |.*", re_flags=re.MULTILINE | re.DOTALL
    )


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 9), reason="The black 25.1 release requires Python>=3.9."
)
def test_entry_point_with_extras():
    # type: () -> None

    run_pex3("run", "--from", "black[d]==25.1", "blackd", "--version").assert_success(
        expected_output_re=re.escape("blackd, version 25.1.0")
    )


@pytest.mark.skipif(
    sys.version_info[:2] < (3, 8), reason="The Pex pyproject.toml uses heterogeneous arrays."
)
def test_locked_local_project(
    tmpdir,  # type: Tempdir
    pex_project_dir,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")

    run_pex3(
        "run",
        "--pex-root",
        pex_root,
        "--pip-version",
        "latest-compatible",
        "--locked",
        "require",
        pex_project_dir,
        "-V",
    ).assert_success(expected_output_re=re.escape(__version__))
    venvs = tuple(VenvDirs.iter_all(pex_root))

    run_pex3(
        "run",
        "--pex-root",
        pex_root,
        "--pip-version",
        "latest-compatible",
        "--from",
        pex_project_dir,
        "pex3",
        "-V",
    ).assert_success(expected_output_re=re.escape(__version__))
    assert venvs == tuple(VenvDirs.iter_all(pex_root)), (
        "Expected the tool venv for the local Pex project to be re-used when running a different "
        "entry point."
    )


@pytest.fixture
def example(tmpdir):
    # type: (Tempdir) -> str

    project = tmpdir.join("project")
    with safe_open(os.path.join(project, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = example
                version = 0.1.0

                [options]
                py_modules =
                    example
                install_requires =
                    cowsay<6

                [options.entry_points]
                console_scripts =
                    say = example:say
                """
            )
        )
    with safe_open(os.path.join(project, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools"]
                backend = "setuptools.build_meta"
                """
            )
        )
    with safe_open(os.path.join(project, "example.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import sys

                import cowsay


                def say():
                    msg = " ".join(sys.argv[1:])
                    try:
                        import colors
                    except ImportError:
                        pass
                    else:
                        msg = colors.yellow(msg)
                    cowsay.tux(msg)


                if __name__ == "__main__":
                    sys.exit(say())
                """
            )
        )
    return project


def test_with_extra_deps_req(
    tmpdir,  # type: Tempdir
    example,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")

    run_pex3("run", "--pex-root", pex_root, "--from", example, "say", "Moo!").assert_success(
        expected_output_re=r".*\| Moo! \|.*", re_flags=re.DOTALL | re.MULTILINE
    )

    run_pex3(
        "run", "--pex-root", pex_root, "--with", "ansicolors", "--from", example, "say", "Moo!"
    ).assert_success(
        expected_output_re=r".*\| {msg} \|.*".format(msg=re.escape(colors.yellow("Moo!"))),
        re_flags=re.DOTALL | re.MULTILINE,
    )


def test_with_extra_deps_script(
    tmpdir,  # type: Tempdir
    example,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    script = os.path.join(example, "example.py")

    run_pex3("run", "--pex-root", pex_root, "--from", "cowsay<6", script, "Moo!").assert_success(
        expected_output_re=r".*\| Moo! \|.*", re_flags=re.DOTALL | re.MULTILINE
    )

    run_pex3(
        "run", "--pex-root", pex_root, "--with", "ansicolors", "--from", "cowsay<6", script, "Moo!"
    ).assert_success(
        expected_output_re=r".*\| {msg} \|.*".format(msg=re.escape(colors.yellow("Moo!"))),
        re_flags=re.DOTALL | re.MULTILINE,
    )


@pytest.fixture
def script(tmpdir):
    # type: (Tempdir) -> str

    with open(tmpdir.join("script.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import sys

                import cowsay


                cowsay.tux(" ".join(sys.argv[1:]))
                """
            )
        )
    return fp.name


def test_script_bare(
    tmpdir,  # type: Tempdir
    script,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")

    run_pex3("run", "--pex-root", pex_root, script, "Moo!").assert_failure(
        expected_error_re=r".*: No module named '?cowsay'?.*", re_flags=re.DOTALL | re.MULTILINE
    )
    run_pex3("run", "--pex-root", pex_root, "--with", "cowsay<6", script, "Moo!").assert_success(
        expected_output_re=r".*\| Moo! \|.*", re_flags=re.DOTALL | re.MULTILINE
    )


def test_script_pep_723(
    tmpdir,  # type: Tempdir
    script,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")

    run_pex3("run", "--pex-root", pex_root, script, "Moo!").assert_failure(
        expected_error_re=r".*: No module named '?cowsay'?.*", re_flags=re.DOTALL | re.MULTILINE
    )

    with open(script, "a") as fp:
        fp.write(
            dedent(
                """\
                # /// script
                # dependencies = [
                #   "cowsay<6",
                # ]
                # ///
                """
            )
        )
    run_pex3("run", "--pex-root", pex_root, script, "Moo!").assert_success(
        expected_output_re=r".*\| Moo! \|.*", re_flags=re.DOTALL | re.MULTILINE
    )
