# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from contextlib import contextmanager
from textwrap import dedent
from types import ModuleType

import pytest

from pex import resolver
from pex.common import safe_mkdir, safe_open, temporary_dir
from pex.compatibility import PY2, WINDOWS, to_bytes
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.testing import (
    IS_PYPY3,
    PY27,
    PY310,
    WheelBuilder,
    built_wheel,
    ensure_python_interpreter,
    environment_as,
    make_bdist,
    run_simple_pex,
    run_simple_pex_test,
    temporary_content,
    write_simple_pex,
)
from pex.third_party.pkg_resources import Distribution
from pex.typing import TYPE_CHECKING
from pex.util import named_temporary_file

try:
    from unittest import mock
except ImportError:
    import mock  # type: ignore[no-redef,import]

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import Dict, Iterable, Iterator, Union
else:
    from pex.third_party import attr


def test_pex_uncaught_exceptions():
    # type: () -> None
    body = "raise Exception('This is an exception')"
    so, rc = run_simple_pex_test(body)
    assert b"This is an exception" in so, "Standard out was: %r" % so
    assert rc == 1


def test_excepthook_honored():
    # type: () -> None
    body = textwrap.dedent(
        """
        import sys

        def excepthook(ex_type, ex, tb):
            print('Custom hook called with: {0}'.format(ex))
            sys.exit(42)

        sys.excepthook = excepthook

        raise Exception('This is an exception')
        """
    )

    so, rc = run_simple_pex_test(body)
    assert so == b"Custom hook called with: This is an exception\n", "Standard out was: %r" % so
    assert rc == 42


def _test_sys_exit(arg, expected_output, expected_rc):
    # type: (Union[str, int], bytes, int) -> None
    body = "import sys; sys.exit({arg})".format(arg=arg)
    so, rc = run_simple_pex_test(body)
    assert so == expected_output, "Should not print SystemExit traceback."
    assert rc == expected_rc


def test_pex_sys_exit_does_not_print_for_numeric_value():
    # type: () -> None
    _test_sys_exit(2, b"", 2)


def test_pex_sys_exit_prints_non_numeric_value_no_traceback():
    # type: () -> None
    text = "something went wrong"

    sys_exit_arg = '"' + text + '"'
    # encode the string somehow that's compatible with 2 and 3
    expected_output = to_bytes(text) + b"\n"
    _test_sys_exit(sys_exit_arg, expected_output, 1)


def test_pex_sys_exit_doesnt_print_none():
    # type: () -> None
    _test_sys_exit("", b"", 0)


def test_pex_sys_exit_prints_objects():
    # type: () -> None
    _test_sys_exit('Exception("derp")', b"derp\n", 1)


@pytest.mark.xfail(IS_PYPY3, reason="https://github.com/pantsbuild/pex/issues/1210")
def test_pex_atexit_swallowing():
    # type: () -> None
    body = textwrap.dedent(
        """
        import atexit

        def raise_on_exit():
            raise Exception('This is an exception')

        atexit.register(raise_on_exit)
        """
    )

    so, rc = run_simple_pex_test(body)
    assert so == b""
    assert rc == 0

    env_copy = os.environ.copy()
    env_copy.update(PEX_TEARDOWN_VERBOSE="1")
    so, rc = run_simple_pex_test(body, env=env_copy)
    assert b"This is an exception" in so
    assert rc == 0


def test_minimum_sys_modules():
    # type: () -> None
    # tainted modules evict
    tainted_module = ModuleType("tainted_module")
    tainted_module.__file__ = "bad_path"
    modules = {"tainted_module": tainted_module}
    new_modules = PEX.minimum_sys_modules(site_libs=[], modules=modules)
    assert new_modules == modules
    new_modules = PEX.minimum_sys_modules(site_libs=["bad_path"], modules=modules)
    assert new_modules == {}

    # builtins stay
    builtin_module = ModuleType("my_builtin")
    stdlib_module = ModuleType("my_stdlib")
    stdlib_module.__file__ = "good_path"
    modules = {"my_builtin": builtin_module, "my_stdlib": stdlib_module}
    new_modules = PEX.minimum_sys_modules(site_libs=[], modules=modules)
    assert new_modules == modules
    new_modules = PEX.minimum_sys_modules(site_libs=["bad_path"], modules=modules)
    assert new_modules == modules

    # tainted packages evict
    tainted_module = ModuleType("tainted_module")
    tainted_module.__path__ = ["bad_path"]  # type: ignore[attr-defined]
    modules = {"tainted_module": tainted_module}
    new_modules = PEX.minimum_sys_modules(site_libs=[], modules=modules)
    assert new_modules == modules
    new_modules = PEX.minimum_sys_modules(site_libs=["bad_path"], modules=modules)
    assert new_modules == {}
    assert tainted_module.__path__ == []  # type: ignore[attr-defined]

    # tainted packages cleaned
    tainted_module = ModuleType("tainted_module")
    tainted_module.__path__ = ["bad_path", "good_path"]  # type: ignore[attr-defined]
    modules = {"tainted_module": tainted_module}
    new_modules = PEX.minimum_sys_modules(site_libs=[], modules=modules)
    assert new_modules == modules
    new_modules = PEX.minimum_sys_modules(site_libs=["bad_path"], modules=modules)
    assert new_modules == modules
    assert tainted_module.__path__ == ["good_path"]  # type: ignore[attr-defined]

    # If __path__ is not a list the module is removed; typically this implies
    # it's a namespace package (https://www.python.org/dev/peps/pep-0420/) where
    # __path__ is a _NamespacePath.
    try:
        from importlib._bootstrap_external import _NamespacePath  # type: ignore

        bad_path = _NamespacePath("hello", "world", None)
    except ImportError:
        bad_path = {"hello": "world"}

    class FakeModule(object):
        pass

    tainted_module = FakeModule()  # type: ignore[assignment]
    tainted_module.__path__ = bad_path  # type: ignore[attr-defined] # Not a list as expected
    modules = {"tainted_module": tainted_module}
    new_modules = PEX.minimum_sys_modules(site_libs=["bad_path"], modules=modules)
    assert new_modules == {}

    # If __file__ is explicitly None we should gracefully proceed to __path__ checks.
    tainted_module = ModuleType("tainted_module")
    tainted_module.__file__ = None  # type: ignore[assignment]
    modules = {"tainted_module": tainted_module}
    new_modules = PEX.minimum_sys_modules(site_libs=[], modules=modules)
    assert new_modules == modules


def test_site_libs():
    # type: () -> None
    with mock.patch.object(
        PEX, "_get_site_packages"
    ) as mock_site_packages, temporary_dir() as tempdir:
        site_packages = os.path.join(tempdir, "site-packages")
        os.mkdir(site_packages)
        mock_site_packages.return_value = set([site_packages])
        site_libs = PEX.site_libs()
        assert site_packages in site_libs


@pytest.mark.skipif(WINDOWS, reason="No symlinks on windows")
def test_site_libs_symlink():
    # type: () -> None
    with mock.patch.object(
        PEX, "_get_site_packages"
    ) as mock_site_packages, temporary_dir() as tempdir:
        site_packages = os.path.join(tempdir, "site-packages")
        os.mkdir(site_packages)
        site_packages_link = os.path.join(tempdir, "site-packages-link")
        os.symlink(site_packages, site_packages_link)
        mock_site_packages.return_value = set([site_packages_link])

        site_libs = PEX.site_libs()
        assert os.path.realpath(site_packages) in site_libs
        assert site_packages_link in site_libs


def test_site_libs_excludes_prefix():
    # type: () -> None
    """Windows returns sys.prefix as part of getsitepackages().

    Make sure to exclude it.
    """

    with mock.patch.object(
        PEX, "_get_site_packages"
    ) as mock_site_packages, temporary_dir() as tempdir:
        site_packages = os.path.join(tempdir, "site-packages")
        os.mkdir(site_packages)
        mock_site_packages.return_value = set([site_packages, sys.prefix])
        site_libs = PEX.site_libs()
        assert site_packages in site_libs
        assert sys.prefix not in site_libs


@pytest.mark.parametrize("zip_safe", (False, True))
@pytest.mark.parametrize("project_name", ("my_project", "my-project"))
def test_pex_script(project_name, zip_safe):
    # type: (str, bool) -> None
    with built_wheel(name=project_name, zip_safe=zip_safe) as bdist_path:
        env_copy = os.environ.copy()
        env_copy["PEX_SCRIPT"] = "hello_world"
        so, rc = run_simple_pex_test("", env=env_copy)
        assert rc == 1, so.decode("utf-8")
        assert b"Could not find script 'hello_world'" in so

        so, rc = run_simple_pex_test("", env=env_copy, dists=[bdist_path])
        assert rc == 0, so.decode("utf-8")
        assert b"hello world" in so

        env_copy["PEX_SCRIPT"] = "shell_script"
        so, rc = run_simple_pex_test("", env=env_copy, dists=[bdist_path])
        assert rc == 0, so.decode("utf-8")
        assert b"hello world from shell script" in so


def test_pex_run():
    # type: () -> None
    with named_temporary_file() as fake_stdout:
        with temporary_dir() as temp_dir:
            pex = write_simple_pex(
                temp_dir,
                'import sys; sys.stdout.write("hello"); sys.stderr.write("hello"); sys.exit(0)',
            )
            rc = PEX(pex.path()).run(stdin=None, stdout=fake_stdout, stderr=fake_stdout)
            assert rc == 0

            fake_stdout.seek(0)
            assert fake_stdout.read() == b"hellohello"


def test_pex_run_extra_sys_path():
    # type: () -> None
    with named_temporary_file() as fake_stdout:
        with temporary_dir() as temp_dir:
            pex = write_simple_pex(
                temp_dir, 'import sys; sys.stdout.write(":".join(sys.path)); sys.exit(0)'
            )
            rc = PEX(pex.path()).run(
                stdin=None,
                stdout=fake_stdout,
                stderr=None,
                env={"PEX_EXTRA_SYS_PATH": "extra/syspath/entry1:extra/syspath/entry2"},
            )
            assert rc == 0

            fake_stdout.seek(0)
            syspath = fake_stdout.read().split(b":")
            assert b"extra/syspath/entry1" in syspath
            assert b"extra/syspath/entry2" in syspath


@attr.s(frozen=True)
class PythonpathIsolationTest(object):
    @staticmethod
    def pex_info(inherit_path):
        # type: (Union[str, bool]) -> PexInfo
        return PexInfo.from_json(json.dumps({"inherit_path": inherit_path}))

    pythonpath = attr.ib()  # type: str
    dists = attr.ib()  # type: Iterable[Distribution]
    exe = attr.ib()  # type: str

    def assert_isolation(self, inherit_path, expected_output):
        # type: (Union[str, bool], str) -> None
        env = dict(PYTHONPATH=self.pythonpath)
        with named_temporary_file() as fake_stdout:
            with temporary_dir() as temp_dir:
                pex_builder = write_simple_pex(
                    temp_dir,
                    pex_info=self.pex_info(inherit_path),
                    dists=self.dists,
                    exe_contents=self.exe,
                )

                # Test the PEX.run API.
                rc = PEX(pex_builder.path()).run(stdout=fake_stdout, env=env)
                assert rc == 0

                fake_stdout.seek(0)
                assert expected_output == fake_stdout.read().decode("utf-8")

                # Test direct PEX execution.
                assert expected_output == subprocess.check_output(
                    [sys.executable, pex_builder.path()], env=env
                ).decode("utf-8")


@pytest.fixture(scope="module")
def pythonpath_isolation_test():
    # type: () -> Iterator[PythonpathIsolationTest]
    with temporary_dir() as temp_dir:
        pythonpath = os.path.join(temp_dir, "one")
        with safe_open(os.path.join(pythonpath, "foo.py"), "w") as fp:
            fp.write("BAR = 42")
        with safe_open(os.path.join(pythonpath, "bar.py"), "w") as fp:
            fp.write("FOO = 137")

        dist_content = {
            "setup.py": textwrap.dedent(
                """
                from setuptools import setup

                setup(
                    name='foo',
                    version='0.0.0',
                    zip_safe=True,
                    packages=['foo'],
                    install_requires=[],
                )
                """
            ),
            "foo/__init__.py": "BAR = 137",
        }

        with temporary_content(dist_content) as project_dir:
            installer = WheelBuilder(project_dir)
            foo_bdist = installer.bdist()

            exe_contents = textwrap.dedent(
                """
                import sys

                try:
                    import bar
                except ImportError:
                    import collections
                    bar = collections.namedtuple('bar', ['FOO'])(None)

                import foo

                sys.stdout.write("foo.BAR={} bar.FOO={}".format(foo.BAR, bar.FOO))
                """
            )

            yield PythonpathIsolationTest(
                pythonpath=pythonpath, dists=[foo_bdist], exe=exe_contents
            )


def test_pythonpath_isolation_inherit_path_false(pythonpath_isolation_test):
    # type: (PythonpathIsolationTest) -> None
    pythonpath_isolation_test.assert_isolation(
        inherit_path="false", expected_output="foo.BAR=137 bar.FOO=None"
    )
    # False should map to 'false'.
    pythonpath_isolation_test.assert_isolation(
        inherit_path=False, expected_output="foo.BAR=137 bar.FOO=None"
    )


def test_pythonpath_isolation_inherit_path_fallback(pythonpath_isolation_test):
    # type: (PythonpathIsolationTest) -> None
    pythonpath_isolation_test.assert_isolation(
        inherit_path="fallback", expected_output="foo.BAR=137 bar.FOO=137"
    )


def test_pythonpath_isolation_inherit_path_prefer(pythonpath_isolation_test):
    # type: (PythonpathIsolationTest) -> None
    pythonpath_isolation_test.assert_isolation(
        inherit_path="prefer", expected_output="foo.BAR=42 bar.FOO=137"
    )

    # True should map to 'prefer'.
    pythonpath_isolation_test.assert_isolation(
        inherit_path=True, expected_output="foo.BAR=42 bar.FOO=137"
    )


def test_pex_executable():
    # type: () -> None
    # Tests that pex keeps executable permissions
    with temporary_dir() as temp_dir:
        pex_dir = os.path.join(temp_dir, "pex_dir")
        safe_mkdir(pex_dir)

        with open(os.path.join(pex_dir, "exe.py"), "w") as fp:
            fp.write(
                textwrap.dedent(
                    """
                    import subprocess
                    import os
                    import sys
                    import my_package
                    path = os.path.join(os.path.dirname(my_package.__file__), 'bin/start.sh')
                    sys.stdout.write(subprocess.check_output([path]).decode('utf-8'))      
                    """
                )
            )

        project_content = {
            "setup.py": textwrap.dedent(
                """
                from setuptools import setup

                setup(
                    name='my_project',
                    version='0.0.0.0',
                    zip_safe=True,
                    packages=['my_package'],
                    package_data={'my_package': ['bin/*']},
                    install_requires=[],
                )
                """
            ),
            "my_package/__init__.py": 0,
            "my_package/bin/start.sh": (
                "#!/usr/bin/env bash\n" "echo 'hello world from start.sh!'"
            ),
            "my_package/my_module.py": 'def do_something():\n  print("hello world!")\n',
        }  # type: Dict[str, Union[str, int]]
        pex_builder = PEXBuilder(path=pex_dir)
        with temporary_content(project_content, perms=0o755) as project_dir:
            installer = WheelBuilder(project_dir)
            bdist = installer.bdist()
            pex_builder.add_dist_location(bdist)
            pex_builder.set_executable(os.path.join(pex_dir, "exe.py"))
            pex_builder.freeze()

            app_pex = os.path.join(os.path.join(temp_dir, "out_pex_dir"), "app.pex")
            pex_builder.build(app_pex)
            std_out, rc = run_simple_pex(app_pex, env={"PEX_ROOT": os.path.join(temp_dir, ".pex")})
            assert rc == 0
            assert std_out.decode("utf-8") == "hello world from start.sh!\n"


def test_pex_paths():
    # type: () -> None
    # Tests that PEX_PATH allows importing sources from the referenced pex.
    with named_temporary_file() as fake_stdout:
        with temporary_dir() as temp_dir:
            pex1_path = os.path.join(temp_dir, "pex1")
            write_simple_pex(
                pex1_path,
                sources=[
                    ("foo_pkg/__init__.py", ""),
                    ("foo_pkg/foo_module.py", 'def foo_func():\n  return "42"'),
                ],
            )

            pex2_path = os.path.join(temp_dir, "pex2")
            pex2 = write_simple_pex(
                pex2_path,
                "import sys; from bar_pkg.bar_module import bar_func; "
                "sys.stdout.write(bar_func()); sys.exit(0)",
                sources=[
                    ("bar_pkg/__init__.py", ""),
                    (
                        "bar_pkg/bar_module.py",
                        "from foo_pkg.foo_module import foo_func\ndef bar_func():\n  return foo_func()",
                    ),
                ],
            )

            rc = PEX(pex2.path()).run(stdin=None, stdout=fake_stdout, env={"PEX_PATH": pex1_path})
            assert rc == 0

            fake_stdout.seek(0)
            assert fake_stdout.read() == b"42"


@contextmanager
def _add_test_hello_to_pex(ep):
    # type: (str) -> Iterator[PEXBuilder]
    with tempfile.NamedTemporaryFile() as tf:
        tf.write(b'def hello(): print("hello")')
        tf.flush()

        pex_builder = PEXBuilder()
        pex_builder.add_source(tf.name, "test.py")
        pex_builder.set_entry_point(ep)
        pex_builder.freeze()
        yield pex_builder


def test_pex_verify_entry_point_method_should_pass():
    # type: () -> None
    with _add_test_hello_to_pex("test:hello") as pex_builder:
        # No error should happen here because `test:hello` is correct
        PEX(pex_builder.path(), interpreter=pex_builder.interpreter, verify_entry_point=True)


def test_pex_verify_entry_point_module_should_pass():
    # type: () -> None
    with _add_test_hello_to_pex("test") as pex_builder:
        # No error should happen here because `test` is correct
        PEX(pex_builder.path(), interpreter=pex_builder.interpreter, verify_entry_point=True)


def test_pex_verify_entry_point_method_should_fail():
    # type: () -> None
    with _add_test_hello_to_pex("test:invalid_entry_point") as pex_builder:
        # Expect InvalidEntryPoint due to invalid entry point method
        with pytest.raises(PEX.InvalidEntryPoint):
            PEX(pex_builder.path(), interpreter=pex_builder.interpreter, verify_entry_point=True)


def test_pex_verify_entry_point_module_should_fail():
    # type: () -> None
    with _add_test_hello_to_pex("invalid.module") as pex_builder:
        # Expect InvalidEntryPoint due to invalid entry point module
        with pytest.raises(PEX.InvalidEntryPoint):
            PEX(pex_builder.path(), interpreter=pex_builder.interpreter, verify_entry_point=True)


def test_activate_interpreter_different_from_current():
    # type: () -> None
    with temporary_dir() as pex_root:
        interp_version = PY310 if PY2 else PY27
        custom_interpreter = PythonInterpreter.from_binary(
            ensure_python_interpreter(interp_version)
        )
        pex_info = PexInfo.default(custom_interpreter)
        pex_info.pex_root = pex_root
        with temporary_dir() as pex_chroot:
            pex_builder = PEXBuilder(
                path=pex_chroot, interpreter=custom_interpreter, pex_info=pex_info
            )
            with make_bdist(interpreter=custom_interpreter) as bdist:
                pex_builder.add_distribution(bdist)
                pex_builder.set_entry_point("sys:exit")
                pex_builder.freeze()

                pex = PEX(pex_builder.path(), interpreter=custom_interpreter)
                try:
                    pex._activate()
                except SystemExit as e:
                    pytest.fail("PEX activation of %s failed with %s" % (pex, e))


def test_execute_interpreter_dashc_program():
    # type: () -> None
    with temporary_dir() as pex_chroot:
        pex_builder = PEXBuilder(path=pex_chroot)
        pex_builder.freeze()
        process = PEX(pex_chroot).run(
            args=["-c", 'import sys; print(" ".join(sys.argv))', "one"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            blocking=False,
        )
        stdout, stderr = process.communicate()

        assert 0 == process.returncode
        assert b"-c one\n" == stdout
        assert b"" == stderr


def test_execute_interpreter_dashm_module():
    # type: () -> None
    with temporary_dir() as pex_chroot:
        pex_builder = PEXBuilder(path=pex_chroot)
        pex_builder.add_source(None, "foo/__init__.py")
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write(
                dedent(
                    """\
                    import os
                    import sys

                    print("{} {}".format(os.path.realpath(sys.argv[0]), " ".join(sys.argv[1:])))
                    """
                )
            )
            fp.flush()
            pex_builder.add_source(fp.name, "foo/bar.py")
        pex_builder.freeze()
        pex = PEX(pex_chroot)
        process = pex.run(
            args=["-m", "foo.bar", "one", "two"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            blocking=False,
        )
        stdout, stderr = process.communicate()

        assert 0 == process.returncode
        assert "{} one two\n".format(
            os.path.realpath(os.path.join(pex_chroot, "foo/bar.py"))
        ) == stdout.decode("utf-8")
        assert b"" == stderr


def test_execute_interpreter_stdin_program():
    # type: () -> None
    with temporary_dir() as pex_chroot:
        pex_builder = PEXBuilder(path=pex_chroot)
        pex_builder.freeze()
        process = PEX(pex_chroot).run(
            args=["-", "one", "two"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            blocking=False,
        )
        stdout, stderr = process.communicate(input=b'import sys; print(" ".join(sys.argv))')

        assert 0 == process.returncode
        assert b"- one two\n" == stdout
        assert b"" == stderr


def test_execute_interpreter_file_program():
    # type: () -> None
    with temporary_dir() as pex_chroot:
        pex_builder = PEXBuilder(path=pex_chroot)
        pex_builder.freeze()
        with tempfile.NamedTemporaryFile() as fp:
            fp.write(b'import sys; print(" ".join(sys.argv))')
            fp.flush()
            process = PEX(pex_chroot).run(
                args=[fp.name, "one", "two"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                blocking=False,
            )
            stdout, stderr = process.communicate()

            assert 0 == process.returncode
            assert "{} one two\n".format(fp.name).encode("utf-8") == stdout
            assert b"" == stderr


def test_pex_run_strip_env():
    # type: () -> None
    with temporary_dir() as pex_root:
        pex_env = dict(PEX_MODULE="does_not_exist_in_sub_pex", PEX_ROOT=pex_root)
        with environment_as(**pex_env), temporary_dir() as pex_chroot:
            pex_builder = PEXBuilder(path=pex_chroot)
            with tempfile.NamedTemporaryFile(mode="w") as fp:
                fp.write(
                    dedent(
                        """
                        import json
                        import os

                        print(json.dumps({k: v for k, v in os.environ.items() if k.startswith("PEX_")}))
                        """
                    )
                )
                fp.flush()
                pex_builder.set_executable(fp.name, "print_pex_env.py")
            pex_builder.freeze()

            stdout, returncode = run_simple_pex(pex_chroot)
            assert 0 == returncode
            assert {} == json.loads(
                stdout.decode("utf-8")
            ), "Expected the entrypoint environment to be stripped of PEX_ environment variables."
            assert pex_env == {
                k: v for k, v in os.environ.items() if k.startswith("PEX_")
            }, "Expected the parent environment to be left un-stripped."


def test_pex_run_custom_setuptools_useable():
    # type: () -> None
    result = resolver.resolve(["setuptools==43.0.0"])
    dists = [installed_dist.distribution for installed_dist in result.installed_distributions]
    with temporary_dir() as temp_dir:
        pex = write_simple_pex(
            temp_dir,
            "import setuptools, sys; sys.exit(0 if '43.0.0' == setuptools.__version__ else 1)",
            dists=dists,
        )
        rc = PEX(pex.path()).run()
        assert rc == 0


def test_pex_run_conflicting_custom_setuptools_useable():
    # type: () -> None
    # Here we use our vendored, newer setuptools to build the pex which has an older setuptools
    # requirement.

    result = resolver.resolve(["setuptools==43.0.0"])
    dists = [installed_dist.distribution for installed_dist in result.installed_distributions]
    with temporary_dir() as temp_dir:
        pex = write_simple_pex(
            temp_dir,
            exe_contents=textwrap.dedent(
                """
                import sys
                import setuptools

                sys.exit(0 if '43.0.0' == setuptools.__version__ else 1)
                """
            ),
            dists=dists,
        )
        rc = PEX(pex.path()).run(env={"PEX_VERBOSE": "9"})
        assert rc == 0


def test_pex_run_custom_pex_useable():
    # type: () -> None
    old_pex_version = "0.7.0"
    result = resolver.resolve(["pex=={}".format(old_pex_version), "setuptools==40.6.3"])
    dists = [installed_dist.distribution for installed_dist in result.installed_distributions]
    with temporary_dir() as temp_dir:
        from pex.version import __version__

        pex = write_simple_pex(
            temp_dir,
            exe_contents=textwrap.dedent(
                """
                import sys

                try:
                  # The 0.7.0 release embedded the version directly in setup.py so it should only be
                  # available via distribution metadata.
                  from pex.version import __version__
                  sys.exit(1)
                except ImportError:
                  import pkg_resources
                  dist = pkg_resources.working_set.find(pkg_resources.Requirement.parse('pex'))
                  print(dist.version)
                """
            ),
            dists=dists,
        )
        process = PEX(pex.path()).run(blocking=False, stdout=subprocess.PIPE)
        stdout, _ = process.communicate()
        assert process.returncode == 0
        assert old_pex_version == stdout.strip().decode("utf-8")
        assert old_pex_version != __version__


@pytest.mark.skipif(PY2, reason="ResourceWarning was only introduced in Python 3.2.")
def test_interpreter_teardown_dev_null_unclosed_resource_warning_suppressed():
    # type: () -> None

    # See https://github.com/pantsbuild/pex/issues/1101 and
    # https://github.com/pantsbuild/pants/issues/11058 for the motivating issue.
    with temporary_dir() as pex_chroot:
        pex_builder = PEXBuilder(path=pex_chroot)
        pex_builder.freeze()

        output = subprocess.check_output(
            args=[sys.executable, "-W", "error::ResourceWarning", pex_chroot, "-c", ""],
            stderr=subprocess.STDOUT,
        )
        assert b"" == output
