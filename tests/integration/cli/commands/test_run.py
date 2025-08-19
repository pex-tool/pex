# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os.path
import re
import sys
from textwrap import dedent
from typing import Iterator

import pytest

from pex.cache.dirs import VenvDirs
from pex.common import safe_copy, safe_open
from pex.http.server import Server, ServerInfo
from pex.typing import TYPE_CHECKING
from pex.version import __version__
from testing import IS_MAC, run_pex_command
from testing.cli import run_pex3
from testing.pytest_utils import IS_CI
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


@pytest.fixture
def cowsay_pylock(tmpdir):
    # type: (Tempdir) -> str

    lock = tmpdir.join("lock.json")
    run_pex3("lock", "create", "cowsay<6", "--indent", "2", "-o", lock).assert_success()

    pylock = tmpdir.join("pylock.toml")
    run_pex3("lock", "export", "--format", "pep-751", "-o", pylock, lock).assert_success()

    return pylock


def test_local_script_locked(
    tmpdir,  # type: Tempdir
    script,  # type: str
    cowsay_pylock,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")

    def assert_locked(lock_name):
        # type: (str) -> None

        pylock = os.path.join(os.path.dirname(script), lock_name)
        safe_copy(cowsay_pylock, pylock)
        run_pex3(
            "run", "-v", "--pex-root", pex_root, script, "--locked", "require", "Moo!"
        ).assert_success(expected_output_re=r".*\| Moo! \|.*", re_flags=re.DOTALL | re.MULTILINE)
        os.unlink(pylock)

    assert_locked("pylock.script.toml")
    assert_locked("pylock.toml")


@pytest.fixture
def script_server(
    tmpdir,  # type: Tempdir
    script,  # type: str
    cowsay_pylock,  # type: str
):
    # type: (...) -> Iterator[ServerInfo]

    script_dir = os.path.dirname(script)
    safe_copy(cowsay_pylock, os.path.join(script_dir, "pylock.toml"))

    server = Server(name="Test Providers Server", cache_dir=tmpdir.join("server"))
    result = server.launch(
        script_dir,
        timeout=float(os.environ.get("_PEX_HTTP_SERVER_TIMEOUT", "5.0")),
        verbose_error=True,
    )
    try:
        yield result.server_info
    finally:
        server.shutdown()


CI_skip_mac = pytest.mark.xfail(
    IS_CI and IS_MAC,
    reason=(
        "The script server fails to start, at least on the macos-15 CI runners, and since this "
        "is not a multi-platform test, just checking on Linux is not ideal but good enough."
    ),
)


@CI_skip_mac
def test_remote_script_locked(
    tmpdir,  # type: Tempdir
    script,  # type: str
    script_server,  # type: ServerInfo
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    script_url = "/".join((script_server.url, os.path.basename(script)))
    run_pex3(
        "run",
        "--pex-root",
        pex_root,
        "--locked",
        "require",
        script_url,
        "Moo!",
    ).assert_success(expected_output_re=r".*\| Moo! \|.*", re_flags=re.DOTALL | re.MULTILINE)

    with open(script, "a") as fp:
        fp.write(
            dedent(
                """\
                # /// script
                # dependencies = [
                #   "cowsay==6",
                # ]
                # ///
                """
            )
        )
    run_pex3(
        "run",
        "--pex-root",
        pex_root,
        "--refresh",
        "--locked",
        "require",
        script_url,
        "Moo!",
    ).assert_failure(
        expected_error_re=r".*{err}.*".format(
            err=re.escape("Failed to resolve a package satisfying cowsay==6 from ")
        ),
        re_flags=re.DOTALL | re.MULTILINE,
    )


def test_run_requirements_file(
    tmpdir,  # type: Tempdir
    example,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")
    with open(tmpdir.join("requirements.txt"), "w") as fp:
        print("ansicolors", file=fp)

    run_pex3(
        "run",
        "--pex-root",
        pex_root,
        "--with-requirements",
        fp.name,
        "--from",
        example,
        "say",
        "Moo!",
    ).assert_success(
        expected_output_re=r".*\| {msg} \|.*".format(msg=re.escape(colors.yellow("Moo!"))),
        re_flags=re.DOTALL | re.MULTILINE,
    )

    with open(fp.name, "a") as fp:
        print(example, file=fp)

    run_pex3(
        "run",
        "--pex-root",
        pex_root,
        "--with-requirements",
        fp.name,
        os.path.join(example, "example.py"),
        "Foo!",
    ).assert_success(
        expected_output_re=r".*\| {msg} \|.*".format(msg=re.escape(colors.yellow("Foo!"))),
        re_flags=re.DOTALL | re.MULTILINE,
    )


def test_run_constraints(
    tmpdir,  # type: Tempdir
    example,  # type: str
):
    # type: (...) -> None

    pex_root = tmpdir.join("pex-root")

    run_pex3(
        "run", "--pex-root", pex_root, "--from", example, "cowsay", "--version"
    ).assert_success(expected_output_re=r"^5\.0$")

    with open(tmpdir.join("constraints.txt"), "w") as fp:
        print("cowsay<5", file=fp)

    run_pex3(
        "run",
        "--pex-root",
        pex_root,
        "--constraints",
        fp.name,
        "--from",
        example,
        "cowsay",
        "--version",
    ).assert_success(expected_output_re=r"^4\.0$")
