# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import functools
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from contextlib import contextmanager
from textwrap import dedent

import pytest

from pex.common import safe_mkdir, safe_open, safe_rmtree, temporary_dir, touch
from pex.compatibility import WINDOWS, to_bytes
from pex.fetcher import URLFetcher
from pex.interpreter import PythonInterpreter
from pex.layout import Layout
from pex.network_configuration import NetworkConfiguration
from pex.pex_info import PexInfo
from pex.requirements import LogicalLine, PyPIRequirement, parse_requirement_file
from pex.testing import (
    IS_MAC,
    NOT_CPYTHON27,
    NOT_CPYTHON27_OR_OSX,
    PY27,
    PY37,
    PY310,
    IntegResults,
    WheelBuilder,
    built_wheel,
    ensure_python_interpreter,
    get_dep_dist_names_from_pex,
    make_env,
    run_pex_command,
    run_simple_pex,
    run_simple_pex_test,
    temporary_content,
)
from pex.third_party import pkg_resources
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING, cast
from pex.util import DistributionHelper, named_temporary_file
from pex.variables import ENV, unzip_dir, venv_dir

if TYPE_CHECKING:
    from typing import Any, Callable, ContextManager, Iterator, List, Optional, Tuple


def test_pex_execute():
    # type: () -> None
    body = "print('Hello')"
    _, rc = run_simple_pex_test(body, coverage=True)
    assert rc == 0


def test_pex_raise():
    # type: () -> None
    body = "raise Exception('This will improve coverage.')"
    run_simple_pex_test(body, coverage=True)


def assert_interpreters(label, pex_root):
    # type: (str, str) -> None
    assert "interpreters" in os.listdir(
        pex_root
    ), "Expected {label} pex root to be populated with interpreters.".format(label=label)


def assert_installed_wheels(label, pex_root):
    # type: (str, str) -> None
    assert "installed_wheels" in os.listdir(
        pex_root
    ), "Expected {label} pex root to be populated with buildtime artifacts.".format(label=label)


def test_pex_root_build():
    # type: () -> None
    with temporary_dir() as td, temporary_dir() as home:
        buildtime_pex_root = os.path.join(td, "buildtime_pex_root")
        output_dir = os.path.join(td, "output_dir")

        output_path = os.path.join(output_dir, "pex.pex")
        args = [
            "pex",
            "-o",
            output_path,
            "--not-zip-safe",
            "--pex-root={}".format(buildtime_pex_root),
        ]
        results = run_pex_command(args=args, env=make_env(HOME=home, PEX_INTERPRETER="1"))
        results.assert_success()
        assert ["pex.pex"] == os.listdir(output_dir), "Expected built pex file."
        assert [] == os.listdir(home), "Expected empty home dir."
        assert_installed_wheels(label="buildtime", pex_root=buildtime_pex_root)


def test_pex_root_run():
    # type: () -> None
    python37 = ensure_python_interpreter(PY37)
    python310 = ensure_python_interpreter(PY310)

    with temporary_dir() as td, temporary_dir() as runtime_pex_root, temporary_dir() as home:
        pex_env = make_env(HOME=home, PEX_PYTHON_PATH=os.pathsep.join((python37, python310)))

        buildtime_pex_root = os.path.join(td, "buildtime_pex_root")
        output_dir = os.path.join(td, "output_dir")

        pex_pex = os.path.join(output_dir, "pex.pex")
        args = [
            "pex",
            "-o",
            pex_pex,
            "-c",
            "pex",
            "--not-zip-safe",
            "--pex-root={}".format(buildtime_pex_root),
            "--runtime-pex-root={}".format(runtime_pex_root),
            "--interpreter-constraint=CPython=={version}".format(version=PY37),
        ]
        results = run_pex_command(args=args, env=pex_env, python=python310)
        results.assert_success()
        assert ["pex.pex"] == os.listdir(output_dir), "Expected built pex file."
        assert [] == os.listdir(home), "Expected empty home dir."

        assert_interpreters(label="buildtime", pex_root=buildtime_pex_root)
        assert_installed_wheels(label="buildtime", pex_root=buildtime_pex_root)
        safe_mkdir(buildtime_pex_root, clean=True)

        assert [] == os.listdir(
            runtime_pex_root
        ), "Expected runtime pex root to be empty prior to any runs."

        subprocess.check_call(args=[python310, pex_pex, "--version"], env=pex_env)
        assert_interpreters(label="runtime", pex_root=runtime_pex_root)
        assert_installed_wheels(label="runtime", pex_root=runtime_pex_root)
        assert [] == os.listdir(
            buildtime_pex_root
        ), "Expected buildtime pex root to be empty after runs using a separate runtime pex root."
        assert [] == os.listdir(home), "Expected empty home dir."


def test_cache_disable():
    # type: () -> None
    with temporary_dir() as td, temporary_dir() as output_dir, temporary_dir() as tmp_home:
        output_path = os.path.join(output_dir, "pex.pex")
        args = [
            "pex",
            "-o",
            output_path,
            "--not-zip-safe",
            "--disable-cache",
            "--pex-root={}".format(td),
        ]
        results = run_pex_command(args=args, env=make_env(HOME=tmp_home, PEX_INTERPRETER="1"))
        results.assert_success()
        assert ["pex.pex"] == os.listdir(output_dir), "Expected built pex file."
        assert [] == os.listdir(tmp_home), "Expected empty temp home dir."


def test_pex_interpreter():
    # type: () -> None
    with named_temporary_file() as fp:
        fp.write(b"print('Hello world')")
        fp.flush()

        env = make_env(PEX_INTERPRETER=1)

        so, rc = run_simple_pex_test("", args=(fp.name,), coverage=True, env=env)
        assert so == b"Hello world\n"
        assert rc == 0


def test_pex_repl_cli():
    # type: () -> None
    """Tests the REPL in the context of the pex cli itself."""
    stdin_payload = b"import sys; sys.exit(3)"

    with temporary_dir() as output_dir:
        # Create a temporary pex containing just `requests` with no entrypoint.
        pex_path = os.path.join(output_dir, "pex.pex")
        results = run_pex_command(["requests", "-o", pex_path])
        results.assert_success()

        # Test that the REPL is functional.
        stdout, rc = run_simple_pex(pex_path, stdin=stdin_payload)
        assert rc == 3
        assert b">>>" in stdout


def test_pex_repl_built():
    # type: () -> None
    """Tests the REPL in the context of a built pex."""
    stdin_payload = b"import requests; import sys; sys.exit(3)"

    with temporary_dir() as output_dir:
        # Create a temporary pex containing just `requests` with no entrypoint.
        pex_path = os.path.join(output_dir, "requests.pex")
        results = run_pex_command(["--disable-cache", "requests", "-o", pex_path])
        results.assert_success()

        # Test that the REPL is functional.
        stdout, rc = run_simple_pex(pex_path, stdin=stdin_payload)
        assert rc == 3
        assert b">>>" in stdout


@pytest.mark.skipif(WINDOWS, reason="No symlinks on windows")
def test_pex_python_symlink():
    # type: () -> None
    with temporary_dir() as td:
        symlink_path = os.path.join(td, "python-symlink")
        os.symlink(sys.executable, symlink_path)
        pexrc_path = os.path.join(td, ".pexrc")
        with open(pexrc_path, "w") as pexrc:
            pexrc.write("PEX_PYTHON=%s" % symlink_path)

        body = "print('Hello')"
        _, rc = run_simple_pex_test(body, coverage=True, env=make_env(HOME=td))
        assert rc == 0


def test_entry_point_exit_code():
    # type: () -> None
    setup_py = dedent(
        """
        from setuptools import setup

        setup(
            name='my_app',
            version='0.0.0',
            zip_safe=True,
            packages=[''],
            entry_points={'console_scripts': ['my_app = my_app:do_something']},
        )
        """
    )

    error_msg = "setuptools expects this to exit non-zero"

    my_app = dedent(
        """
        def do_something():
          return '%s'
  """
        % error_msg
    )

    with temporary_content({"setup.py": setup_py, "my_app.py": my_app}) as project_dir:
        installer = WheelBuilder(project_dir)
        dist = installer.bdist()
        so, rc = run_simple_pex_test("", env=make_env(PEX_SCRIPT="my_app"), dists=[dist])
        assert so.decode("utf-8").strip() == error_msg
        assert rc == 1


def test_pex_multi_resolve():
    # type: () -> None
    """Tests multi-interpreter + multi-platform resolution."""
    python27 = ensure_python_interpreter(PY27)
    python37 = ensure_python_interpreter(PY37)
    with temporary_dir() as output_dir:
        pex_path = os.path.join(output_dir, "pex.pex")
        results = run_pex_command(
            [
                "--disable-cache",
                "lxml==4.2.4",
                "--no-build",
                "--platform=linux-x86_64-cp-36-m",
                "--platform=macosx-10.6-x86_64-cp-36-m",
                "--python={}".format(python27),
                "--python={}".format(python37),
                "-o",
                pex_path,
            ]
        )
        results.assert_success()

        included_dists = get_dep_dist_names_from_pex(pex_path, "lxml")
        assert len(included_dists) == 4
        for dist_substr in ("-cp27-", "-cp36-", "-cp37-", "-manylinux1_x86_64", "-macosx_"):
            assert any(dist_substr in f for f in included_dists)


def test_pex_path_arg():
    # type: () -> None
    with temporary_dir() as output_dir:

        # create 2 pex files for PEX_PATH
        pex1_path = os.path.join(output_dir, "pex1.pex")
        res1 = run_pex_command(["--disable-cache", "requests", "-o", pex1_path])
        res1.assert_success()
        pex2_path = os.path.join(output_dir, "pex2.pex")
        res2 = run_pex_command(["--disable-cache", "flask", "-o", pex2_path])
        res2.assert_success()
        pex_path = ":".join(os.path.join(output_dir, name) for name in ("pex1.pex", "pex2.pex"))

        # parameterize the pex arg for test.py
        pex_out_path = os.path.join(output_dir, "out.pex")
        # create test file test.py that attempts to import modules from pex1/pex2
        test_file_path = os.path.join(output_dir, "test.py")
        with open(test_file_path, "w") as fh:
            fh.write(
                dedent(
                    """
                    import requests
                    import flask
                    import sys
                    import os
                    import subprocess
                    if 'RAN_ONCE' in os.environ:
                        print('Success!')
                    else:
                        env = os.environ.copy()
                        env['RAN_ONCE'] = '1'
                        subprocess.call([sys.executable] + ['%s'] + sys.argv, env=env)
                        sys.exit()
                    """
                    % pex_out_path
                )
            )

        # build out.pex composed from pex1/pex1
        run_pex_command(
            ["--disable-cache", "--pex-path={}".format(pex_path), "wheel", "-o", pex_out_path]
        )

        # run test.py with composite env
        stdout, rc = run_simple_pex(pex_out_path, [test_file_path])
        assert rc == 0
        assert stdout == b"Success!\n"


def test_pex_path_in_pex_info_and_env():
    # type: () -> None
    with temporary_dir() as output_dir:

        # create 2 pex files for PEX-INFO pex_path
        pex1_path = os.path.join(output_dir, "pex1.pex")
        res1 = run_pex_command(["--disable-cache", "requests", "-o", pex1_path])
        res1.assert_success()
        pex2_path = os.path.join(output_dir, "pex2.pex")
        res2 = run_pex_command(["--disable-cache", "flask", "-o", pex2_path])
        res2.assert_success()
        pex_path = ":".join(os.path.join(output_dir, name) for name in ("pex1.pex", "pex2.pex"))

        # create a pex for environment PEX_PATH
        pex3_path = os.path.join(output_dir, "pex3.pex")
        res3 = run_pex_command(["--disable-cache", "wheel", "-o", pex3_path])
        res3.assert_success()
        env_pex_path = os.path.join(output_dir, "pex3.pex")

        # parameterize the pex arg for test.py
        pex_out_path = os.path.join(output_dir, "out.pex")
        # create test file test.py that attempts to import modules from pex1/pex2
        test_file_path = os.path.join(output_dir, "test.py")
        with open(test_file_path, "w") as fh:
            fh.write(
                dedent(
                    """
                    import requests
                    import flask
                    import wheel
                    import sys
                    import os
                    import subprocess
                    print('Success!')
                    """
                )
            )

        # build out.pex composed from pex1/pex1
        run_pex_command(["--disable-cache", "--pex-path={}".format(pex_path), "-o", pex_out_path])

        # load secondary PEX_PATH
        env = make_env(PEX_PATH=env_pex_path)

        # run test.py with composite env
        stdout, rc = run_simple_pex(pex_out_path, [test_file_path], env=env)
        assert rc == 0
        assert stdout == b"Success!\n"


def test_inherit_path_fallback():
    # type: () -> None
    inherit_path("=fallback")


def test_inherit_path_backwards_compatibility():
    # type: () -> None
    inherit_path("")


def test_inherit_path_prefer():
    # type: () -> None
    inherit_path("=prefer")


def inherit_path(inherit_path):
    # type: (str) -> None
    with temporary_dir() as output_dir:
        exe = os.path.join(output_dir, "exe.py")
        body = "import sys ; print('\\n'.join(sys.path))"
        with open(exe, "w") as f:
            f.write(body)

        pex_path = os.path.join(output_dir, "pex.pex")
        results = run_pex_command(
            [
                "--disable-cache",
                "msgpack_python",
                "--inherit-path{}".format(inherit_path),
                "-o",
                pex_path,
            ]
        )

        results.assert_success()

        env = make_env(PYTHONPATH="/doesnotexist")
        stdout, rc = run_simple_pex(
            pex_path,
            args=(exe,),
            env=env,
        )
        assert rc == 0

        stdout_lines = stdout.decode().split("\n")
        requests_paths = tuple(i for i, l in enumerate(stdout_lines) if "msgpack_python" in l)
        sys_paths = tuple(i for i, l in enumerate(stdout_lines) if "doesnotexist" in l)
        assert len(requests_paths) == 1
        assert len(sys_paths) == 1

        if inherit_path == "=fallback":
            assert requests_paths[0] < sys_paths[0]
        else:
            assert requests_paths[0] > sys_paths[0]


def test_pex_multi_resolve_2():
    # type: () -> None
    """Tests multi-interpreter + multi-platform resolution using extended platform notation."""
    with temporary_dir() as output_dir:
        pex_path = os.path.join(output_dir, "pex.pex")
        results = run_pex_command(
            [
                "--disable-cache",
                "lxml==3.8.0",
                "--no-build",
                "--platform=linux-x86_64-cp-36-m",
                "--platform=linux-x86_64-cp-27-m",
                "--platform=macosx-10.6-x86_64-cp-36-m",
                "--platform=macosx-10.6-x86_64-cp-27-m",
                "-o",
                pex_path,
            ]
        )
        results.assert_success()

        included_dists = get_dep_dist_names_from_pex(pex_path, "lxml")
        assert len(included_dists) == 4
        for dist_substr in ("-cp27-", "-cp36-", "-manylinux1_x86_64", "-macosx_"):
            assert any(
                dist_substr in f for f in included_dists
            ), "{} was not found in wheel".format(dist_substr)


if TYPE_CHECKING:
    TestResolveFn = Callable[[str, str, str, str, Optional[str]], None]
    EnsureFailureFn = Callable[[str, str, str, str], None]


@contextmanager
def pex_manylinux_and_tag_selection_context():
    # type: () -> Iterator[Tuple[TestResolveFn, EnsureFailureFn]]
    with temporary_dir() as output_dir:

        def do_resolve(req_name, req_version, platform, extra_flags=None):
            # type: (str, str, str, Optional[str]) -> Tuple[str, IntegResults]
            extra_flags = extra_flags or ""
            pex_path = os.path.join(output_dir, "test.pex")
            results = run_pex_command(
                [
                    "--disable-cache",
                    "--no-build",
                    "%s==%s" % (req_name, req_version),
                    "--platform=%s" % platform,
                    "-o",
                    pex_path,
                ]
                + extra_flags.split()
            )
            return pex_path, results

        def test_resolve(req_name, req_version, platform, substr, extra_flags=None):
            # type: (str, str, str, str, Optional[str]) -> None
            pex_path, results = do_resolve(req_name, req_version, platform, extra_flags)
            results.assert_success()
            included_dists = get_dep_dist_names_from_pex(pex_path, req_name.replace("-", "_"))
            assert any(substr in d for d in included_dists), "couldnt find {} in {}".format(
                substr, included_dists
            )

        def ensure_failure(req_name, req_version, platform, extra_flags):
            # type: (str, str, str, str) -> None
            pex_path, results = do_resolve(req_name, req_version, platform, extra_flags)
            results.assert_failure()

        yield test_resolve, ensure_failure


def test_pex_manylinux_and_tag_selection_linux_msgpack():
    # type: () -> None
    """Tests resolver manylinux support and tag targeting."""
    with pex_manylinux_and_tag_selection_context() as (test_resolve, ensure_failure):
        msgpack, msgpack_ver = "msgpack-python", "0.4.7"
        test_msgpack = functools.partial(test_resolve, msgpack, msgpack_ver)

        # Exclude 3.3, >=3.6 because no wheels exist for these versions on pypi.
        current_version = sys.version_info[:2]
        if current_version != (3, 3) and current_version < (3, 6):
            ver = "{}{}".format(*current_version)
            test_msgpack(
                "linux-x86_64-cp-{}-m".format(ver),
                "msgpack_python-0.4.7-cp{ver}-cp{ver}m-manylinux1_x86_64.whl".format(ver=ver),
            )

        test_msgpack(
            "linux-x86_64-cp-27-m", "msgpack_python-0.4.7-cp27-cp27m-manylinux1_x86_64.whl"
        )
        test_msgpack(
            "linux-x86_64-cp-27-mu", "msgpack_python-0.4.7-cp27-cp27mu-manylinux1_x86_64.whl"
        )
        test_msgpack("linux-i686-cp-27-m", "msgpack_python-0.4.7-cp27-cp27m-manylinux1_i686.whl")
        test_msgpack("linux-i686-cp-27-mu", "msgpack_python-0.4.7-cp27-cp27mu-manylinux1_i686.whl")
        test_msgpack(
            "linux-x86_64-cp-27-mu", "msgpack_python-0.4.7-cp27-cp27mu-manylinux1_x86_64.whl"
        )
        test_msgpack(
            "linux-x86_64-cp-34-m", "msgpack_python-0.4.7-cp34-cp34m-manylinux1_x86_64.whl"
        )
        test_msgpack(
            "linux-x86_64-cp-35-m", "msgpack_python-0.4.7-cp35-cp35m-manylinux1_x86_64.whl"
        )

        ensure_failure(msgpack, msgpack_ver, "linux-x86_64", "--no-manylinux")


def test_pex_manylinux_and_tag_selection_lxml_osx():
    # type: () -> None
    with pex_manylinux_and_tag_selection_context() as (test_resolve, ensure_failure):
        test_resolve(
            "lxml", "3.8.0", "macosx-10.6-x86_64-cp-27-m", "lxml-3.8.0-cp27-cp27m-macosx", None
        )
        test_resolve(
            "lxml", "3.8.0", "macosx-10.6-x86_64-cp-36-m", "lxml-3.8.0-cp36-cp36m-macosx", None
        )


@pytest.mark.skipif(NOT_CPYTHON27_OR_OSX, reason="Relies on a pre-built wheel for linux 2.7")
def test_pex_manylinux_runtime():
    # type: () -> None
    """Tests resolver manylinux support and runtime resolution (and --platform=current)."""
    test_stub = dedent(
        """
        import msgpack
        print(msgpack.unpackb(msgpack.packb([1, 2, 3])))
        """
    )

    with temporary_content({"tester.py": test_stub}) as output_dir:
        pex_path = os.path.join(output_dir, "test.pex")
        tester_path = os.path.join(output_dir, "tester.py")
        results = run_pex_command(
            [
                "--disable-cache",
                "--no-build",
                "msgpack-python==0.4.7",
                "--platform=current",
                "-o",
                pex_path,
            ]
        )
        results.assert_success()

        out = subprocess.check_output([pex_path, tester_path])
        assert out.strip() == b"[1, 2, 3]"


def test_pex_exit_code_propagation():
    # type: () -> None
    """Tests exit code propagation."""
    test_stub = dedent(
        """
        def test_fail():
            assert False
        """
    )

    with temporary_content({"tester.py": test_stub}) as output_dir:
        pex_path = os.path.join(output_dir, "test.pex")
        tester_path = os.path.join(output_dir, "tester.py")
        results = run_pex_command(["pytest", "-c", "pytest", "-o", pex_path])
        results.assert_success()

        assert subprocess.call([pex_path, os.path.realpath(tester_path)]) == 1


@pytest.mark.skipif(NOT_CPYTHON27, reason="Tests environment markers that select for python 2.7.")
def test_ipython_appnope_env_markers():
    # type: () -> None
    res = run_pex_command(["--disable-cache", "ipython==5.8.0", "-c", "ipython", "--", "--version"])
    res.assert_success()


def test_cross_platform_abi_targeting_behavior_exact():
    # type: () -> None
    with temporary_dir() as td:
        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(
            [
                "--disable-cache",
                "--no-pypi",
                "--platform=linux-x86_64-cp-27-mu",
                "--find-links=tests/example_packages/",
                "MarkupSafe==1.0",
                "-o",
                pex_out_path,
            ]
        )
        res.assert_success()


def test_pex_source_bundling():
    # type: () -> None
    with temporary_dir() as output_dir:
        with temporary_dir() as input_dir:
            with open(os.path.join(input_dir, "exe.py"), "w") as fh:
                fh.write(
                    dedent(
                        """
                        print('hello')
                        """
                    )
                )

            pex_path = os.path.join(output_dir, "pex1.pex")
            res = run_pex_command(
                [
                    "-o",
                    pex_path,
                    "-D",
                    input_dir,
                    "-e",
                    "exe",
                ]
            )
            res.assert_success()

            stdout, rc = run_simple_pex(pex_path)

            assert rc == 0
            assert stdout == b"hello\n"


def test_pex_source_bundling_pep420():
    # type: () -> None
    with temporary_dir() as output_dir:
        with temporary_dir() as input_dir:
            with safe_open(os.path.join(input_dir, "a/b/c.py"), "w") as fh:
                fh.write("GREETING = 'hello'")

            with open(os.path.join(input_dir, "exe.py"), "w") as fh:
                fh.write(
                    dedent(
                        """
                        from a.b.c import GREETING

                        print(GREETING)
                        """
                    )
                )

            pex_path = os.path.join(output_dir, "pex1.pex")
            py310 = ensure_python_interpreter(PY310)
            res = run_pex_command(["-o", pex_path, "-D", input_dir, "-e", "exe"], python=py310)
            res.assert_success()

            stdout, rc = run_simple_pex(pex_path, interpreter=PythonInterpreter.from_binary(py310))

            assert rc == 0
            assert stdout == b"hello\n"


def test_pex_resource_bundling():
    # type: () -> None
    with temporary_dir() as output_dir:
        with temporary_dir() as input_dir, temporary_dir() as resources_input_dir:
            with open(os.path.join(resources_input_dir, "greeting"), "w") as fh:
                fh.write("hello")
            pex_path = os.path.join(output_dir, "pex1.pex")

            with open(os.path.join(input_dir, "exe.py"), "w") as fh:
                fh.write(
                    dedent(
                        """
                        import pkg_resources
                        print(pkg_resources.resource_string('__main__', 'greeting').decode('utf-8'))
                        """
                    )
                )

            res = run_pex_command(
                [
                    "-o",
                    pex_path,
                    "-D",
                    input_dir,
                    "-R",
                    resources_input_dir,
                    "-e",
                    "exe",
                    "setuptools==44.0",
                ]
            )
            res.assert_success()

            stdout, rc = run_simple_pex(pex_path)

            assert rc == 0
            assert stdout == b"hello\n"


def test_entry_point_verification_3rdparty():
    # type: () -> None
    with temporary_dir() as td:
        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(
            ["Pillow==5.2.0", "-e", "PIL:Image", "-o", pex_out_path, "--validate-entry-point"]
        )
        res.assert_success()


def test_invalid_entry_point_verification_3rdparty():
    # type: () -> None
    with temporary_dir() as td:
        pex_out_path = os.path.join(td, "pex.pex")
        res = run_pex_command(
            ["Pillow==5.2.0", "-e", "PIL:invalid", "-o", pex_out_path, "--validate-entry-point"]
        )
        res.assert_failure()


def test_multiplatform_entrypoint():
    # type: () -> None
    with temporary_dir() as td:
        pex_out_path = os.path.join(td, "p537.pex")
        interpreter = ensure_python_interpreter(PY37)
        res = run_pex_command(
            [
                "p537==1.0.4",
                "--no-build",
                "--python={}".format(interpreter),
                "--python-shebang=#!{}".format(interpreter),
                "--platform=linux-x86_64-cp-37-m",
                "--platform=macosx-10.13-x86_64-cp-37-m",
                "-c",
                "p537",
                "-o",
                pex_out_path,
                "--validate-entry-point",
            ]
        )
        res.assert_success()

        greeting = subprocess.check_output([pex_out_path])
        assert b"Hello World!" == greeting.strip()


def test_pex_console_script_custom_setuptools_useable():
    # type: () -> None
    setup_py = dedent(
        """
        from setuptools import setup

        setup(
            name='my_app',
            version='0.0.0',
            zip_safe=True,
            packages=[''],
            install_requires=['setuptools==43.0.0'],
            entry_points={'console_scripts': ['my_app_function = my_app:do_something']},
        )
  """
    )

    my_app = dedent(
        """
        def do_something():
            import setuptools
            assert '43.0.0' == setuptools.__version__
  """
    )

    with temporary_content({"setup.py": setup_py, "my_app.py": my_app}) as project_dir:
        with temporary_dir() as out:
            pex = os.path.join(out, "pex.pex")
            pex_command = [
                "--validate-entry-point",
                "-c",
                "my_app_function",
                project_dir,
                "-o",
                pex,
            ]
            results = run_pex_command(pex_command)
            results.assert_success()

            stdout, rc = run_simple_pex(pex, env=make_env(PEX_VERBOSE=1))
            assert rc == 0, stdout


@contextmanager
def pex_with_no_entrypoints():
    # type: () -> Iterator[Tuple[str, bytes, str]]
    with temporary_dir() as out:
        pex = os.path.join(out, "pex.pex")
        run_pex_command(["setuptools==43.0.0", "-o", pex])
        test_script = dedent(
            """\
            import sys
            import setuptools

            sys.exit(0 if '43.0.0' == setuptools.__version__ else 1)
            """
        ).encode("utf-8")
        yield pex, test_script, out


def test_pex_interpreter_execute_custom_setuptools_useable():
    # type: () -> None
    with pex_with_no_entrypoints() as (pex, test_script, out):
        script = os.path.join(out, "script.py")
        with open(script, "wb") as fp:
            fp.write(test_script)
        stdout, rc = run_simple_pex(pex, args=(script,), env=make_env(PEX_VERBOSE=1))
        assert rc == 0, stdout


def test_pex_interpreter_interact_custom_setuptools_useable():
    # type: () -> None
    with pex_with_no_entrypoints() as (pex, test_script, _):
        stdout, rc = run_simple_pex(pex, env=make_env(PEX_VERBOSE=1), stdin=test_script)
        assert rc == 0, stdout


def test_setup_python():
    # type: () -> None
    interpreter = ensure_python_interpreter(PY27)
    with temporary_dir() as out:
        pex = os.path.join(out, "pex.pex")
        results = run_pex_command(
            ["jsonschema==2.6.0", "--disable-cache", "--python={}".format(interpreter), "-o", pex]
        )
        results.assert_success()
        subprocess.check_call([pex, "-c", "import jsonschema"])


def test_setup_interpreter_constraint():
    # type: () -> None
    interpreter = ensure_python_interpreter(PY27)
    with temporary_dir() as out:
        pex = os.path.join(out, "pex.pex")
        env = make_env(
            PEX_IGNORE_RCFILES="1",
            PATH=os.path.dirname(interpreter),
        )
        results = run_pex_command(
            [
                "jsonschema==2.6.0",
                "--disable-cache",
                "--interpreter-constraint=CPython=={}".format(PY27),
                "-o",
                pex,
            ],
            env=env,
        )
        results.assert_success()

        stdout, rc = run_simple_pex(pex, env=env, stdin=b"import jsonschema")
        assert rc == 0


def test_setup_python_path():
    # type: () -> None
    """Check that `--python-path` is used rather than the default $PATH."""
    py27_interpreter_dir = os.path.dirname(ensure_python_interpreter(PY27))
    py37_interpreter_dir = os.path.dirname(ensure_python_interpreter(PY37))
    with temporary_dir() as out:
        pex = os.path.join(out, "pex.pex")
        # Even though we set $PATH="", we still expect for both interpreters to be used when
        # building the PEX. Note that `more-itertools` has a distinct Py2 and Py3 wheel.
        results = run_pex_command(
            [
                "more-itertools==5.0.0",
                "--disable-cache",
                "--interpreter-constraint=CPython>={},<={}".format(PY27, PY37),
                "--python-path={}".format(
                    os.pathsep.join([py27_interpreter_dir, py37_interpreter_dir])
                ),
                "-o",
                pex,
            ],
            env=make_env(PEX_IGNORE_RCFILES="1", PATH=""),
        )
        results.assert_success()

        py310_interpreter = PythonInterpreter.from_binary(ensure_python_interpreter(PY310))

        py27_env = make_env(PEX_IGNORE_RCFILES="1", PATH=py27_interpreter_dir)
        stdout, rc = run_simple_pex(
            pex,
            interpreter=py310_interpreter,
            env=py27_env,
            stdin=b"import more_itertools, sys; print(sys.version_info[:2])",
        )
        assert rc == 0
        assert b"(2, 7)" in stdout

        py37_env = make_env(PEX_IGNORE_RCFILES="1", PATH=py37_interpreter_dir)
        stdout, rc = run_simple_pex(
            pex,
            interpreter=py310_interpreter,
            env=py37_env,
            stdin=b"import more_itertools, sys; print(sys.version_info[:2])",
        )
        assert rc == 0
        assert b"(3, 7)" in stdout


def test_setup_python_multiple_transitive_markers():
    # type: () -> None
    py27_interpreter = ensure_python_interpreter(PY27)
    py310_interpreter = ensure_python_interpreter(PY310)
    with temporary_dir() as out:
        pex = os.path.join(out, "pex.pex")
        results = run_pex_command(
            [
                "jsonschema==2.6.0",
                "--disable-cache",
                "--python-shebang=#!/usr/bin/env python",
                "--python={}".format(py27_interpreter),
                "--python={}".format(py310_interpreter),
                "-o",
                pex,
            ]
        )
        results.assert_success()

        pex_program = [pex, "-c"]
        py2_only_program = pex_program + ["import functools32"]
        both_program = pex_program + [
            "import jsonschema, os, sys; print(os.path.realpath(sys.executable))"
        ]

        py27_env = make_env(PATH=os.path.dirname(py27_interpreter))
        subprocess.check_call(py2_only_program, env=py27_env)

        stdout = subprocess.check_output(both_program, env=py27_env)
        assert to_bytes(os.path.realpath(py27_interpreter)) == stdout.strip()

        py38_env = make_env(PATH=os.path.dirname(py310_interpreter))
        with pytest.raises(subprocess.CalledProcessError) as err:
            subprocess.check_output(py2_only_program, stderr=subprocess.STDOUT, env=py38_env)
        assert b"ModuleNotFoundError: No module named 'functools32'" in err.value.output

        stdout = subprocess.check_output(both_program, env=py38_env)
        assert to_bytes(os.path.realpath(py310_interpreter)) == stdout.strip()


def test_setup_python_direct_markers():
    # type: () -> None
    py310_interpreter = ensure_python_interpreter(PY310)
    with temporary_dir() as out:
        pex = os.path.join(out, "pex.pex")
        results = run_pex_command(
            [
                'subprocess32==3.2.7; python_version<"3"',
                "--disable-cache",
                "--python-shebang=#!/usr/bin/env python",
                "--python={}".format(py310_interpreter),
                "-o",
                pex,
            ]
        )
        results.assert_success()

        py2_only_program = [pex, "-c", "import subprocess32"]

        with pytest.raises(subprocess.CalledProcessError) as err:
            subprocess.check_output(
                py2_only_program,
                stderr=subprocess.STDOUT,
                env=make_env(PATH=os.path.dirname(py310_interpreter)),
            )
        assert b"ModuleNotFoundError: No module named 'subprocess32'" in err.value.output


def test_setup_python_multiple_direct_markers():
    # type: () -> None
    py310_interpreter = ensure_python_interpreter(PY310)
    py27_interpreter = ensure_python_interpreter(PY27)
    with temporary_dir() as out:
        pex = os.path.join(out, "pex.pex")
        results = run_pex_command(
            [
                'subprocess32==3.2.7; python_version<"3"',
                "--disable-cache",
                "--python-shebang=#!/usr/bin/env python",
                "--python={}".format(py310_interpreter),
                "--python={}".format(py27_interpreter),
                "-o",
                pex,
            ]
        )
        results.assert_success()

        py2_only_program = [pex, "-c", "import subprocess32"]

        with pytest.raises(subprocess.CalledProcessError) as err:
            subprocess.check_output(
                py2_only_program,
                stderr=subprocess.STDOUT,
                env=make_env(PATH=os.path.dirname(py310_interpreter)),
            )
        assert (
            re.search(b"ModuleNotFoundError: No module named 'subprocess32'", err.value.output)
            is not None
        )

        subprocess.check_call(
            py2_only_program, env=make_env(PATH=os.path.dirname(py27_interpreter))
        )


def build_and_execute_pex_with_warnings(*extra_build_args, **extra_runtime_env):
    # type: (*str, **str) -> bytes
    with temporary_dir() as out:
        tcl_pex = os.path.join(out, "tcl.pex")
        run_pex_command(["twitter.common.lang==0.3.10", "-o", tcl_pex] + list(extra_build_args))

        cmd = [tcl_pex, "-c", "from twitter.common.lang import Singleton"]
        env = os.environ.copy()
        env.update(**extra_runtime_env)
        process = subprocess.Popen(cmd, env=env, stderr=subprocess.PIPE)
        _, stderr = process.communicate()
        return stderr


def test_emit_warnings_default():
    # type: () -> None
    stderr = build_and_execute_pex_with_warnings()
    assert stderr


def test_no_emit_warnings():
    # type: () -> None
    stderr = build_and_execute_pex_with_warnings("--no-emit-warnings")
    assert not stderr


def test_no_emit_warnings_emit_env_override():
    # type: () -> None
    stderr = build_and_execute_pex_with_warnings("--no-emit-warnings", PEX_EMIT_WARNINGS="true")
    assert stderr


def test_no_emit_warnings_verbose_override():
    # type: () -> None
    stderr = build_and_execute_pex_with_warnings("--no-emit-warnings", PEX_VERBOSE="1")
    assert stderr


def test_trusted_host_handling():
    # type: () -> None
    python = ensure_python_interpreter(PY27)
    # Since we explicitly ask Pex to find links at http://www.antlr3.org/download/Python, it should
    # implicitly trust the www.antlr3.org host.
    results = run_pex_command(
        args=[
            "--find-links=http://www.antlr3.org/download/Python",
            "antlr_python_runtime==3.1.3",
            "--",
            "-c",
            "import antlr3",
        ],
        python=python,
    )
    results.assert_success()


def test_pex_run_strip_env():
    # type: () -> None
    with temporary_dir() as td:
        src_dir = os.path.join(td, "src")
        with safe_open(os.path.join(src_dir, "print_pex_env.py"), "w") as fp:
            fp.write(
                dedent(
                    """
                    import json
                    import os

                    print(json.dumps({k: v for k, v in os.environ.items() if k.startswith('PEX_')}))
                    """
                )
            )

        pex_env = dict(PEX_ROOT=os.path.join(td, "pex_root"))
        env = make_env(**pex_env)

        stripped_pex_file = os.path.join(td, "stripped.pex")
        results = run_pex_command(
            args=[
                "--sources-directory={}".format(src_dir),
                "--entry-point=print_pex_env",
                "-o",
                stripped_pex_file,
            ],
        )
        results.assert_success()
        assert {} == json.loads(
            subprocess.check_output([stripped_pex_file], env=env).decode("utf-8")
        ), "Expected the entrypoint environment to be stripped of PEX_ environment variables."

        unstripped_pex_file = os.path.join(td, "unstripped.pex")
        results = run_pex_command(
            args=[
                "--sources-directory={}".format(src_dir),
                "--entry-point=print_pex_env",
                "--no-strip-pex-env",
                "-o",
                unstripped_pex_file,
            ],
        )
        results.assert_success()
        assert pex_env == json.loads(
            subprocess.check_output([unstripped_pex_file], env=env).decode("utf-8")
        ), "Expected the entrypoint environment to be left un-stripped."


def iter_distributions(pex_root, project_name):
    # type: (str, str) -> Iterator[pkg_resources.Distribution]
    found = set()
    for root, dirs, _ in os.walk(pex_root):
        for d in dirs:
            if not d.startswith(project_name):
                continue
            if not d.endswith(".whl"):
                continue
            wheel_path = os.path.realpath(os.path.join(root, d))
            if wheel_path in found:
                continue
            dist = DistributionHelper.distribution_from_path(wheel_path)
            assert dist is not None
            if dist.project_name == project_name:
                found.add(wheel_path)
                yield dist


def test_pex_cache_dir_and_pex_root():
    # type: () -> None
    python = ensure_python_interpreter(PY37)
    with temporary_dir() as td:
        cache_dir = os.path.join(td, "cache_dir")
        pex_root = os.path.join(td, "pex_root")

        # When the options both have the same value it should be accepted.
        pex_file = os.path.join(td, "pex_file")
        run_pex_command(
            python=python,
            args=["--cache-dir", cache_dir, "--pex-root", cache_dir, "p537==1.0.4", "-o", pex_file],
        ).assert_success()

        dists = list(iter_distributions(pex_root=cache_dir, project_name="p537"))
        assert 1 == len(dists), "Expected to find exactly one distribution, found {}".format(dists)

        for directory in cache_dir, pex_root:
            safe_rmtree(directory)

        # When the options have conflicting values they should be rejected.
        run_pex_command(
            python=python,
            args=["--cache-dir", cache_dir, "--pex-root", pex_root, "p537==1.0.4", "-o", pex_file],
        ).assert_failure()

        assert not os.path.exists(cache_dir)
        assert not os.path.exists(pex_root)


def test_disable_cache():
    # type: () -> None
    python = ensure_python_interpreter(PY37)
    with temporary_dir() as td:
        pex_root = os.path.join(td, "pex_root")
        pex_file = os.path.join(td, "pex_file")
        run_pex_command(
            python=python,
            args=["--disable-cache", "p537==1.0.4", "-o", pex_file],
            env=make_env(PEX_ROOT=pex_root),
        ).assert_success()

        assert not os.path.exists(pex_root)


def test_unzip_mode():
    # type: () -> None
    with temporary_dir() as td:
        pex_root = os.path.join(td, "pex_root")
        pex_file = os.path.join(td, "pex_file")
        src_dir = os.path.join(td, "src")
        with safe_open(os.path.join(src_dir, "example.py"), "w") as fp:
            fp.write(
                dedent(
                    """\
                    import os
                    import sys

                    if 'quit' == sys.argv[-1]:
                        print(os.path.realpath(sys.argv[0]))
                        sys.exit(0)

                    print(' '.join(sys.argv[1:]))
                    sys.stdout.flush()
                    sys.stderr.flush()
                    os.execv(sys.executable, [sys.executable] + sys.argv[:-1])
                    """
                )
            )
        result = run_pex_command(
            args=[
                "--sources-directory",
                src_dir,
                "--entry-point",
                "example",
                "--output-file",
                pex_file,
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "--no-strip-pex-env",
                "--unzip",
            ]
        )
        result.assert_success()
        assert "PEXWarning: The `--unzip/--no-unzip` option is deprecated." in result.error

        process1 = subprocess.Popen(
            args=[pex_file, "quit", "re-exec"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        output1, error1 = process1.communicate()
        assert 0 == process1.returncode

        pex_hash = PexInfo.from_pex(pex_file).pex_hash
        assert pex_hash is not None
        unzipped_cache = unzip_dir(pex_root, pex_hash)
        assert os.path.isdir(unzipped_cache)
        example_py_path = os.path.realpath(os.path.join(unzipped_cache, "example.py"))
        assert ["quit re-exec", example_py_path] == output1.decode("utf-8").splitlines()
        assert not error1

        shutil.rmtree(unzipped_cache)
        process2 = subprocess.Popen(
            args=[pex_file, "quit", "re-exec"],
            env=make_env(PEX_UNZIP=False),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        output2, error2 = process2.communicate()
        assert 0 == process2.returncode

        assert ["quit re-exec", example_py_path] == output2.decode("utf-8").splitlines()
        assert os.path.isdir(unzipped_cache)
        assert "PEXWarning: The `PEX_UNZIP` env var is deprecated." in error2.decode("utf-8")


def test_tmpdir_absolute(tmp_workdir):
    # type: (str) -> None
    result = run_pex_command(
        args=[
            "--tmpdir",
            ".",
            "--",
            "-c",
            dedent(
                """\
                import os
                import tempfile
                
                print(os.environ["TMPDIR"])
                print(tempfile.gettempdir())
                """
            ),
        ]
    )
    result.assert_success()
    assert [tmp_workdir, tmp_workdir] == result.output.strip().splitlines()


def test_tmpdir_dne(tmp_workdir):
    # type: (str) -> None
    tmpdir_dne = os.path.join(tmp_workdir, ".tmp")
    result = run_pex_command(args=["--tmpdir", ".tmp", "--", "-c", ""])
    result.assert_failure()
    assert tmpdir_dne in result.error
    assert "does not exist" in result.error


def test_tmpdir_file(tmp_workdir):
    # type: (str) -> None
    tmpdir_file = os.path.join(tmp_workdir, ".tmp")
    touch(tmpdir_file)
    result = run_pex_command(args=["--tmpdir", ".tmp", "--", "-c", ""])
    result.assert_failure()
    assert tmpdir_file in result.error
    assert "is not a directory" in result.error


EXAMPLE_PYTHON_REQUIREMENTS_URL = (
    "https://raw.githubusercontent.com/pantsbuild/example-python/"
    "c6052498f25a436f2639ccd0bc846cec1a55d7d5"
    "/requirements.txt"
)


def test_requirements_network_configuration(run_proxy, tmp_workdir):
    # type: (Callable[[Optional[str]], ContextManager[Tuple[int, str]]], str) -> None
    def req(
        contents,  # type: str
        line_no,  # type: int
    ):
        return PyPIRequirement(
            LogicalLine(
                "{}\n".format(contents),
                contents,
                source=EXAMPLE_PYTHON_REQUIREMENTS_URL,
                start_line=line_no,
                end_line=line_no,
            ),
            Requirement.parse(contents),
        )

    proxy_auth = "jake:jones"
    with run_proxy(proxy_auth) as (port, ca_cert):
        reqs = parse_requirement_file(
            EXAMPLE_PYTHON_REQUIREMENTS_URL,
            fetcher=URLFetcher(
                NetworkConfiguration(
                    proxy="http://{proxy_auth}@localhost:{port}".format(
                        proxy_auth=proxy_auth, port=port
                    ),
                    cert=ca_cert,
                )
            ),
        )
        assert [
            req("ansicolors>=1.0.2", 4),
            req("setuptools>=42.0.0", 5),
            req("translate>=3.2.1", 6),
            req("protobuf>=3.11.3", 7),
        ] == list(reqs)


@pytest.fixture
def isort_pex_args(tmpdir):
    # type: (Any) -> Tuple[str, List[str]]
    pex_file = os.path.join(str(tmpdir), "pex")

    requirements = [
        # For Python 2.7 and Python 3.5:
        "isort==4.3.21; python_version<'3.6'",
        "setuptools==44.1.1; python_version<'3.6'",
        # For Python 3.6+:
        "isort==5.6.4; python_version>='3.6'",
    ]
    return pex_file, requirements + ["-c", "isort", "-o", pex_file]


def test_venv_mode(
    tmpdir,  # type: Any
    isort_pex_args,  # type: Tuple[str, List[str]]
):
    # type: (...) -> None
    other_interpreter_version = PY310 if sys.version_info[0] == 2 else PY27
    other_interpreter = ensure_python_interpreter(other_interpreter_version)

    pex_file, args = isort_pex_args
    results = run_pex_command(
        args=args + ["--python", sys.executable, "--python", other_interpreter, "--venv"],
        quiet=True,
    )
    results.assert_success()

    def run_isort_pex(pex_python=None):
        # type: (Optional[str]) -> str
        pex_root = str(tmpdir)
        args = [pex_file] if pex_python else [sys.executable, pex_file]
        stdout = subprocess.check_output(
            args=args + ["-c", "import sys; print(sys.executable); print(sys.prefix)"],
            env=make_env(PEX_ROOT=pex_root, PEX_INTERPRETER=1, PEX_PYTHON=pex_python),
        )
        pex_interpreter, venv_home = cast(
            "Tuple[str, str]", stdout.decode("utf-8").strip().splitlines()
        )
        actual_venv_home = os.path.realpath(venv_home)
        assert venv_home != actual_venv_home, "Expected the venv home to be a symlink"
        assert len(venv_home) < len(
            actual_venv_home
        ), "Expected the venv home symlink path length to be shorter than the actual path length"

        with ENV.patch(PEX_PYTHON=pex_python):
            pex_info = PexInfo.from_pex(pex_file)
            pex_hash = pex_info.pex_hash
            assert pex_hash is not None
            expected_venv_home = venv_dir(
                pex_file=pex_file,
                pex_root=pex_root,
                pex_hash=pex_hash,
                has_interpreter_constraints=False,
            )
        assert expected_venv_home == os.path.commonprefix([actual_venv_home, expected_venv_home])
        return pex_interpreter

    isort_pex_interpreter1 = run_isort_pex()
    assert isort_pex_interpreter1 == run_isort_pex()

    isort_pex_interpreter2 = run_isort_pex(pex_python=other_interpreter)
    assert other_interpreter != isort_pex_interpreter2
    assert isort_pex_interpreter1 != isort_pex_interpreter2
    assert isort_pex_interpreter2 == run_isort_pex(pex_python=other_interpreter)


@pytest.mark.parametrize(
    "execution_mode_args", [pytest.param([], id="PEX"), pytest.param(["--venv"], id="VENV")]
)
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
def test_seed(
    isort_pex_args,  # type: Tuple[str, List[str]]
    execution_mode_args,  # type: List[str]
    layout,  # type: Layout.Value
):
    # type: (...) -> None
    pex_file, args = isort_pex_args
    results = run_pex_command(
        args=args + execution_mode_args + ["--layout", layout.value, "--seed"]
    )
    results.assert_success()

    # Setting posix=False works around this issue under pypy: https://bugs.python.org/issue1170.
    seed_argv = shlex.split(str(results.output), posix=False)
    isort_args = ["--version"]
    seed_stdout = subprocess.check_output(seed_argv + isort_args)
    pex_args = [pex_file] if os.path.isfile(pex_file) else [sys.executable, pex_file]
    pex_stdout = subprocess.check_output(pex_args + isort_args)
    assert pex_stdout == seed_stdout


@pytest.mark.parametrize(
    "execution_mode_args", [pytest.param([], id="PEX"), pytest.param(["--venv"], id="VENV")]
)
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
@pytest.mark.parametrize(
    "seeded_execute_args",
    [pytest.param(["python", "pex"], id="Python"), pytest.param(["pex"], id="Direct")],
)
def test_seed_verbose(
    isort_pex_args,  # type: Tuple[str, List[str]]
    execution_mode_args,  # type: List[str]
    layout,  # type: Layout.Value
    seeded_execute_args,  # type: List[str]
    tmpdir,  # type: Any
):
    # type: (...) -> None
    pex_root = str(tmpdir)
    pex_file, args = isort_pex_args
    results = run_pex_command(
        args=args + execution_mode_args + ["--layout", layout.value, "--seed", "verbose"],
        env=make_env(PEX_ROOT=pex_root, PEX_PYTHON_PATH=sys.executable),
    )
    results.assert_success()
    verbose_info = json.loads(results.output)
    seeded_argv0 = [verbose_info[arg] for arg in seeded_execute_args]

    assert pex_root == verbose_info.pop("pex_root")

    python = verbose_info.pop("python")
    assert PythonInterpreter.get() == PythonInterpreter.from_binary(python)

    verbose_info.pop("pex")
    assert {} == verbose_info

    isort_args = ["--version"]
    seed_stdout = subprocess.check_output(seeded_argv0 + isort_args)
    pex_args = [pex_file] if os.path.isfile(pex_file) else [python, pex_file]
    pex_stdout = subprocess.check_output(pex_args + isort_args)
    assert pex_stdout == seed_stdout


def test_pip_issues_9420_workaround():
    # type: () -> None

    # N.B.: isort 5.7.0 needs Python >=3.6
    python = ensure_python_interpreter(PY310)

    results = run_pex_command(
        args=["--resolver-version", "pip-2020-resolver", "isort[colors]==5.7.0", "colorama==0.4.1"],
        python=python,
        quiet=True,
    )
    results.assert_failure()
    normalized_stderr = "\n".join(line.strip() for line in results.error.strip().splitlines())
    assert normalized_stderr.startswith(
        dedent(
            """\
            ERROR: Cannot install colorama==0.4.1 and isort[colors]==5.7.0 because these package versions have conflicting dependencies.
            ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/en/latest/user_guide/#fixing-conflicting-dependencies
            """
        )
    )
    assert normalized_stderr.endswith(
        dedent(
            """\
            The conflict is caused by:
            The user requested colorama==0.4.1
            isort[colors] 5.7.0 depends on colorama<0.5.0 and >=0.4.3; extra == "colors"

            To fix this you could try to:
            1. loosen the range of package versions you've specified
            2. remove package versions to allow pip attempt to solve the dependency conflict
            """
        ).strip()
    )


def test_requirement_file_from_url(tmpdir):
    # type: (Any) -> None

    constraints = os.path.join(str(tmpdir), "constraints.txt")
    with open(constraints, "w") as fp:
        print("translate>=3.2.1,<3.6.0", file=fp)
        print("protobuf<=3.17.3", file=fp)
        print("setuptools<60", file=fp)

    pex_file = os.path.join(str(tmpdir), "pex")

    results = run_pex_command(
        args=["-r", EXAMPLE_PYTHON_REQUIREMENTS_URL, "--constraints", constraints, "-o", pex_file]
    )
    results.assert_success()
    output, returncode = run_simple_pex(
        pex_file, args=["-c", "import colors, google.protobuf, setuptools, translate"]
    )
    assert 0 == returncode, output
    assert b"" == output


def test_constraint_file_from_url(tmpdir):
    # type: (Any) -> None

    # N.B.: The fasteners library requires Python >=3.6.
    python = ensure_python_interpreter(PY310)

    pex_file = os.path.join(str(tmpdir), "pex")

    # N.B.: This requirements file has fasteners==0.15.0 but fasteners 0.16.0 is available.
    # N.B.: This requirements file has 28 requirements in addition to fasteners.
    pants_requirements_url = (
        "https://raw.githubusercontent.com/pantsbuild/pants/"
        "b0fbb76112dcb61b3004c2caf3a59d3f03e3f182"
        "/3rdparty/python/requirements.txt"
    )
    results = run_pex_command(
        args=["fasteners", "--constraints", pants_requirements_url, "-o", pex_file], python=python
    )
    results.assert_success()
    output, returncode = run_simple_pex(
        pex_file,
        args=["-c", "from fasteners.version import version_string; print(version_string())"],
        interpreter=PythonInterpreter.from_binary(python),
    )
    assert 0 == returncode, output

    # Strange but true: https://github.com/harlowja/fasteners/blob/0.15/fasteners/version.py
    assert (
        b"0.14.1" == output.strip()
    ), "Fasteners 0.15.0 is expected to report its version as 0.14.1"

    # N.B.: Fasteners 0.15.0 depends on six and monotonic>=0.1; neither of which are constrained by
    # `pants_requirements_url`.
    dist_paths = set(PexInfo.from_pex(pex_file).distributions.keys())
    assert len(dist_paths) == 3
    dist_paths.remove("fasteners-0.15-py2.py3-none-any.whl")
    for dist_path in dist_paths:
        assert dist_path.startswith(("six-", "monotonic-")) and dist_path.endswith(".whl")


def test_console_script_from_pex_path(tmpdir):
    # type: (Any) -> None
    pex_with_script = os.path.join(str(tmpdir), "script.pex")
    with built_wheel(
        name="my_project",
        entry_points={"console_scripts": ["my_app = my_project.my_module:do_something"]},
    ) as my_whl:
        run_pex_command(args=[my_whl, "-o", pex_with_script]).assert_success()

    pex_file = os.path.join(str(tmpdir), "app.pex")
    result = run_pex_command(args=["-c", "my_app", "--pex-path", pex_with_script, "-o", pex_file])
    result.assert_success()

    assert "hello world!\n" == subprocess.check_output(args=[pex_file]).decode("utf-8")


@pytest.mark.skipif(
    not IS_MAC, reason="This is a test of a problem specific to macOS interpreters."
)
def test_invalid_macosx_platform_tag(tmpdir):
    # type: (Any) -> None
    if not any((3, 8) == pi.version[:2] for pi in PythonInterpreter.iter()):
        pytest.skip("Test requires a system Python 3.8 interpreter.")

    repository_pex = os.path.join(str(tmpdir), "repository.pex")
    ic_args = ["--interpreter-constraint", "==3.8.*"]
    args = ic_args + ["setproctitle==1.2", "-o", repository_pex]
    run_pex_command(args=args).assert_success()

    setproctitle_pex = os.path.join(str(tmpdir), "setproctitle.pex")
    run_pex_command(
        args=ic_args + ["setproctitle", "--pex-repository", repository_pex, "-o", setproctitle_pex]
    ).assert_success()

    subprocess.check_call(args=[setproctitle_pex, "-c", "import setproctitle"])


def test_require_hashes(tmpdir):
    # type: (Any) -> None
    requirements = os.path.join(str(tmpdir), "requirements.txt")
    with open(requirements, "w") as fp:
        fp.write(
            dedent(
                """\
                # The --require-hashes flag puts Pip in a mode where all requirements must be both
                # pinned and have a --hash specified. More on Pip hash checking mode here:
                # https://pip.pypa.io/en/stable/reference/pip_install/#hash-checking-mode
                #
                # This mode causes Pip to verify that the resolved distributions have matching
                # hashes and that the resolve closure has not expanded. It's not needed however
                # since including even one requirement with --hash implicitly turns on hash
                # checking mode.
                --require-hashes

                # Pip requirement files support line continuation in the customary way.
                requests==2.25.1 \
                    --hash sha256:c210084e36a42ae6b9219e00e48287def368a26d03a048ddad7bfee44f75871e

                idna==2.10 \
                    --hash sha256:b97d804b1e9b523befed77c48dacec60e6dcb0b5391d57af6a65a312a90648c0

                # N.B.: Pip accepts flag values in either ` ` or `=` separated forms.
                chardet==4.0.0 \
                    --hash=sha256:f864054d66fd9118f2e67044ac8981a54775ec5b67aed0441892edb553d21da5

                certifi==2020.12.5 \
                    --hash sha256:719a74fb9e33b9bd44cc7f3a8d94bc35e4049deebe19ba7d8e108280cfd59830

                # Pip supports the following three hash algorithms and it need only find one
                # successful matching distribution.
                urllib3==1.26.4 \
                    --hash sha384:bad \
                    --hash sha512:worse \
                    --hash sha256:2f4da4594db7e1e110a944bb1b551fdf4e6c136ad42e4234131391e21eb5b0df
                """
            )
        )
    requests_pex = os.path.join(str(tmpdir), "requests.pex")

    run_pex_command(args=["-r", requirements, "-o", requests_pex]).assert_success()
    subprocess.check_call(args=[requests_pex, "-c", "import requests"])

    # The hash checking mode should also work in constraints context.
    run_pex_command(
        args=["--constraints", requirements, "requests", "-o", requests_pex]
    ).assert_success()
    subprocess.check_call(args=[requests_pex, "-c", "import requests"])

    with open(requirements, "w") as fp:
        fp.write(
            dedent(
                """\
                requests==2.25.1 \
                    --hash sha256:c210084e36a42ae6b9219e00e48287def368a26d03a048ddad7bfee44f75871e
                idna==2.10 \
                    --hash sha256:b97d804b1e9b523befed77c48dacec60e6dcb0b5391d57af6a65a312a90648c0
                chardet==4.0.0 \
                    --hash=sha256:f864054d66fd9118f2e67044ac8981a54775ec5b67aed0441892edb553d21da5
                certifi==2020.12.5 \
                    --hash sha256:719a74fb9e33b9bd44cc7f3a8d94bc35e4049deebe19ba7d8e108280cfd59830
                urllib3==1.26.4 \
                    --hash sha384:bad \
                    --hash sha512:worse \
                    --hash sha256:2f4da4594db7e1e110a944bb1b551fdf4e6c136ad42e4234131391e21eb5b0d0
                """
            )
        )
    as_requirements_result = run_pex_command(args=["-r", requirements])
    as_requirements_result.assert_failure()

    # The hash checking mode should also work in constraints context.
    as_constraints_result = run_pex_command(args=["--constraints", requirements, "requests"])
    as_constraints_result.assert_failure()

    error_lines = {
        re.sub(r"\s+", " ", line.strip()): index
        for index, line in enumerate(as_constraints_result.error.splitlines())
    }
    index = error_lines["Expected sha512 worse"]
    assert (
        index + 1
        == error_lines[
            "Got ca602ae6dd925648c8ff87ef00bcef2d0ebebf1090b44e8dd43b75403f07db50269e5078f709cbce8e"
            "7cfaedaf1b754d02dda08b6970b6a157cbf4c31ebc16a7"
        ]
    )

    index = error_lines["Expected sha384 bad"]
    assert (
        index + 1
        == error_lines[
            "Got 64ec6b63f74b7bdf161a9b38fabf59c0a691ba9ed325f0864fea984e0deabe648cbd12d619d3989b64"
            "24488349df3b30"
        ]
    )

    index = error_lines[
        "Expected sha256 2f4da4594db7e1e110a944bb1b551fdf4e6c136ad42e4234131391e21eb5b0d0"
    ]
    assert (
        index + 1
        == error_lines["Got 2f4da4594db7e1e110a944bb1b551fdf4e6c136ad42e4234131391e21eb5b0df"]
    )


@pytest.mark.parametrize(
    "execution_mode_args", [pytest.param([], id="PEX"), pytest.param(["--venv"], id="VENV")]
)
@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
def test_binary_scripts(
    tmpdir,  # type: Any
    execution_mode_args,  # type: List[str]
    layout,  # type: Layout.Value
):
    # type: (...) -> None

    # The py-spy distribution has a `py-spy` "script" that is a native executable that we should
    # not try to parse as a traditional script but should still be able to execute.
    py_spy_pex = os.path.join(str(tmpdir), "py-spy.pex")
    run_pex_command(
        args=["py-spy==0.3.8", "-c", "py-spy", "-o", py_spy_pex, "--layout", layout.value]
        + execution_mode_args
    ).assert_success()
    output = subprocess.check_output(args=[sys.executable, py_spy_pex, "-V"])
    assert output == b"py-spy 0.3.8\n"
