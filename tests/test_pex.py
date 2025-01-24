# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import site
import subprocess
import sys
import sysconfig
import tempfile
import textwrap
from contextlib import contextmanager
from textwrap import dedent
from types import ModuleType

import pytest

from pex import resolver
from pex.common import environment_as, safe_mkdir, safe_open, temporary_dir
from pex.compatibility import PY2, WINDOWS, commonpath, to_bytes
from pex.dist_metadata import Distribution
from pex.interpreter import PythonIdentity, PythonInterpreter
from pex.pex import PEX, IsolatedSysPath
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.typing import TYPE_CHECKING
from pex.util import named_temporary_file
from pex.version import __version__
from testing import (
    PY39,
    PY310,
    PY_VER,
    WheelBuilder,
    ensure_python_interpreter,
    install_wheel,
    make_bdist,
    run_simple_pex,
    run_simple_pex_test,
    temporary_content,
    write_simple_pex,
)

try:
    from unittest import mock
except ImportError:
    import mock  # type: ignore[no-redef,import]

if TYPE_CHECKING:
    from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Union

    import attr  # vendor:skip
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

        sys.excepthook = excepthook

        raise Exception('This is an exception')
        """
    )

    so, rc = run_simple_pex_test(body)
    assert so == b"Custom hook called with: This is an exception\n", "Standard out was: %r" % so
    assert rc == 1


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
    assert b"This is an exception" in so
    assert rc == 0


def test_minimum_sys_modules():
    # type: () -> None

    def minimum_sys_modules(
        sys_path=(),  # type: Iterable[str]
        site_libs=(),  # type: Iterable[str]
        modules=None,  # type: Optional[Mapping[str, ModuleType]]
    ):
        # type: (...) -> Mapping[str, ModuleType]
        return PEX.minimum_sys_modules(
            IsolatedSysPath(sys_path=sys_path, site_packages=site_libs), modules=modules
        )

    # tainted modules evict
    tainted_module = ModuleType("tainted_module")
    tainted_module.__file__ = "bad_path"
    modules = {"tainted_module": tainted_module}
    new_modules = minimum_sys_modules(sys_path=["bad_path"], modules=modules)
    assert new_modules == modules
    new_modules = minimum_sys_modules(site_libs=["bad_path"], modules=modules)
    assert new_modules == {}

    # builtins stay
    builtin_module = ModuleType("my_builtin")
    stdlib_module = ModuleType("my_stdlib")
    stdlib_module.__file__ = "good_path"
    modules = {"my_builtin": builtin_module, "my_stdlib": stdlib_module}
    new_modules = minimum_sys_modules(sys_path=["good_path"], modules=modules)
    assert new_modules == modules
    new_modules = minimum_sys_modules(
        sys_path=["good_path"], site_libs=["bad_path"], modules=modules
    )
    assert new_modules == modules

    # tainted packages evict
    tainted_module = ModuleType("tainted_module")
    tainted_module.__path__ = ["bad_path"]  # type: ignore[attr-defined]
    modules = {"tainted_module": tainted_module}
    new_modules = minimum_sys_modules(sys_path=["bad_path"], modules=modules)
    assert new_modules == modules
    new_modules = minimum_sys_modules(site_libs=["bad_path"], modules=modules)
    assert new_modules == {}
    assert tainted_module.__path__ == []  # type: ignore[attr-defined]

    # tainted packages cleaned
    tainted_module = ModuleType("tainted_module")
    tainted_module.__path__ = ["bad_path", "good_path"]  # type: ignore[attr-defined]
    modules = {"tainted_module": tainted_module}
    new_modules = minimum_sys_modules(sys_path=["good_path"], site_libs=[], modules=modules)
    assert new_modules == modules
    new_modules = minimum_sys_modules(
        sys_path=["good_path"], site_libs=["bad_path"], modules=modules
    )
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
    new_modules = minimum_sys_modules(site_libs=["bad_path"], modules=modules)
    assert new_modules == {}

    # If __file__ is explicitly None we should gracefully proceed to __path__ checks.
    tainted_module = ModuleType("tainted_module")
    tainted_module.__file__ = None  # type: ignore[assignment]
    modules = {"tainted_module": tainted_module}
    new_modules = minimum_sys_modules(site_libs=[], modules=modules)
    assert new_modules == modules


def test_site_libs(tmpdir):
    # type: (Any) -> None
    with mock.patch.object(site, "getsitepackages") as mock_site_packages:
        site_packages = os.path.join(str(tmpdir), "site-packages")
        os.mkdir(site_packages)
        mock_site_packages.return_value = {site_packages}
        site_libs = frozenset(entry.path for entry in PythonIdentity.get().site_packages)
        assert site_packages in site_libs


@pytest.mark.skipif(WINDOWS, reason="No symlinks on windows")
def test_site_libs_symlink(tmpdir):
    # type: (Any) -> None

    # N.B.: PythonIdentity.get() used below in the core test ends up consulting
    # `packaging.tags.sys_tags()` which in turn consults `sysconfig`; so we need to make sure that
    # bit of stdlib is on the sys.path. We get this by grabbing its sys.path entry, which contains
    # the whole stdlib in addition to it.
    assert sysconfig.__file__

    sys_path_entries = tuple(
        entry
        for entry in PythonIdentity.get().sys_path
        if entry == commonpath((entry, sysconfig.__file__))
    )
    assert len(sys_path_entries) == 1
    sys_path_entry = sys_path_entries[0]

    sys_path_entry_link = os.path.join(str(tmpdir), "lib-link")
    os.symlink(sys_path_entry, sys_path_entry_link)

    with mock.patch.object(site, "getsitepackages") as mock_site_packages, mock.patch(
        "sys.path", new=[sys_path_entry_link]
    ):
        site_packages = os.path.join(str(tmpdir), "site-packages")
        os.mkdir(site_packages)
        site_packages_link = os.path.join(str(tmpdir), "site-packages-link")
        os.symlink(site_packages, site_packages_link)
        mock_site_packages.return_value = [site_packages_link]

        isolated_sys_path = IsolatedSysPath.for_pex(
            interpreter=PythonIdentity.get(), pex=os.devnull
        )
        assert os.path.join(sys_path_entry, "module.py") in isolated_sys_path
        assert os.path.realpath(site_packages) not in isolated_sys_path
        assert site_packages_link not in isolated_sys_path


def test_site_libs_excludes_prefix():
    # type: () -> None
    """Windows returns sys.prefix as part of getsitepackages().

    Make sure to exclude it.
    """

    with mock.patch.object(
        site, "getsitepackages"
    ) as mock_site_packages, temporary_dir() as tempdir:
        site_packages = os.path.realpath(os.path.join(tempdir, "site-packages"))
        os.mkdir(site_packages)
        mock_site_packages.return_value = [site_packages, sys.prefix]
        site_libs = tuple(entry.path for entry in PythonIdentity.get().site_packages)
        assert site_packages in site_libs
        assert sys.prefix not in site_libs


@pytest.mark.parametrize("zip_safe", (False, True))
@pytest.mark.parametrize("project_name", ("my_project", "my-project"))
def test_pex_script(project_name, zip_safe):
    # type: (str, bool) -> None
    with make_bdist(name=project_name, zip_safe=zip_safe) as bdist:
        env_copy = os.environ.copy()
        env_copy["PEX_SCRIPT"] = "hello_world"
        so, rc = run_simple_pex_test("", env=env_copy)
        assert rc == 1, so.decode("utf-8")
        assert b"Could not find script 'hello_world'" in so

        so, rc = run_simple_pex_test("", env=env_copy, dists=[bdist])
        assert rc == 0, so.decode("utf-8")
        assert b"hello world" in so

        env_copy["PEX_SCRIPT"] = "shell_script"
        so, rc = run_simple_pex_test("", env=env_copy, dists=[bdist])
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
        with temporary_dir() as temp_dir:
            pex_builder = write_simple_pex(
                temp_dir,
                pex_info=self.pex_info(inherit_path),
                dists=self.dists,
                exe_contents=self.exe,
            )

            # Test the PEX.run API.
            process = PEX(pex_builder.path()).run(
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                blocking=False,
            )
            stdout, stderr = process.communicate()
            assert process.returncode == 0, stderr.decode("utf-8")
            assert expected_output == stdout.decode("utf-8")

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
            foo_bdist = install_wheel(WheelBuilder(project_dir).bdist())

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
            bdist = install_wheel(WheelBuilder(project_dir).bdist())
            pex_builder.add_dist_location(bdist.location)
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
        interp_version = PY310 if PY_VER == (3, 9) else PY39
        custom_interpreter = PythonInterpreter.from_binary(
            ensure_python_interpreter(interp_version)
        )
        pex_info = PexInfo.default()
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


def test_execute_interpreter_dashc_program_with_python_options():
    with temporary_dir() as pex_chroot:
        pex_builder = PEXBuilder(path=pex_chroot)
        pex_builder.freeze()
        # To test with interpreter options we add an "assert False"
        # that we would expect to fail.
        # adding the -O option will ignore that assertion
        # see: https://docs.python.org/3/using/cmdline.html#cmdoption-O
        process = PEX(pex_chroot).run(
            args=["-O", "-c", 'assert False; import sys; print(" ".join(sys.argv))', "one"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            blocking=False,
        )
        stdout, stderr = process.communicate()

        assert b"" == stderr
        assert b"-c one\n" == stdout
        assert 0 == process.returncode


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


def test_execute_interpreter_dashm_module_with_python_options():
    # type: () -> None
    with temporary_dir() as pex_chroot:
        pex_builder = PEXBuilder(path=pex_chroot)
        pex_builder.add_source(None, "foo/__init__.py")
        # To test with interpreter options we add an "assert False"
        # that we would expect to fail.
        # adding the -O option will ignore that assertion
        # see: https://docs.python.org/3/using/cmdline.html#cmdoption-O
        with tempfile.NamedTemporaryFile(mode="w") as fp:
            fp.write(
                dedent(
                    """\
                    import os
                    import sys

                    assert False
                    print("{} {}".format(os.path.realpath(sys.argv[0]), " ".join(sys.argv[1:])))
                    """
                )
            )
            fp.flush()
            pex_builder.add_source(fp.name, "foo/bar.py")
        pex_builder.freeze()
        pex = PEX(pex_chroot)
        process = pex.run(
            args=["-O", "-m", "foo.bar", "one", "two"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            blocking=False,
        )
        stdout, stderr = process.communicate()

        assert b"" == stderr
        assert "{} one two\n".format(
            os.path.realpath(os.path.join(pex_chroot, "foo/bar.py"))
        ) == stdout.decode("utf-8")
        assert 0 == process.returncode


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


def test_execute_interpreter_stdin_program_with_python_options():
    # type: () -> None
    with temporary_dir() as pex_chroot:
        pex_builder = PEXBuilder(path=pex_chroot)
        pex_builder.freeze()
        # To test with interpreter options we add an "assert False"
        # that we would expect to fail.
        # adding the -O option will ignore that assertion
        # see: https://docs.python.org/3/using/cmdline.html#cmdoption-O
        process = PEX(pex_chroot).run(
            args=["-O", "-", "one", "two"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            blocking=False,
        )
        stdout, stderr = process.communicate(
            input=b'import sys; assert False; print(" ".join(sys.argv))'
        )

        assert b"" == stderr
        assert b"- one two\n" == stdout
        assert 0 == process.returncode


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


EXPECTED_REPL_BANNER_NO_DEPS = (
    dedent(
        """\
        Pex {pex_version} hermetic environment with no dependencies.
        Python {python_version} on {platform}
        Type "help", "pex", "copyright", "credits" or "license" for more information.
        """
    )
    .format(python_version=sys.version, platform=sys.platform, pex_version=__version__)
    .encode("utf-8")
)


def test_execute_repl():
    with temporary_dir() as pex_chroot:
        pex_builder = PEXBuilder(path=pex_chroot)
        pex_builder.freeze()
        process = PEX(pex_chroot).run(
            args=[],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            blocking=False,
        )
        commands = dedent(
            """
            assert False
            20 + 103
            quit()
            """
        )
        stdout, stderr = process.communicate(input=commands.encode("utf-8"))

        assert stderr.startswith(EXPECTED_REPL_BANNER_NO_DEPS), stderr
        assert b"AssertionError" in stderr
        assert b">>> " in stdout
        assert b"123" in stdout
        assert 0 == process.returncode


def test_execute_repl_with_python_options():
    with temporary_dir() as pex_chroot:
        pex_builder = PEXBuilder(path=pex_chroot)
        pex_builder.freeze()
        process = PEX(pex_chroot).run(
            args=["-O"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            blocking=False,
        )
        # adding the -O option will ignore that assertion
        # see: https://docs.python.org/3/using/cmdline.html#cmdoption-O
        # We should not see the AssertionError in the output anymore.
        commands = dedent(
            """
            assert False
            20 + 103
            quit()
            """
        )
        stdout, stderr = process.communicate(input=commands.encode("utf-8"))

        assert stderr.startswith(EXPECTED_REPL_BANNER_NO_DEPS), stderr
        assert b"AssertionError" not in stderr
        assert b">>> " in stdout
        assert b"123" in stdout
        assert 0 == process.returncode


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


@pytest.fixture
def setuptools_version():
    # type: () -> str
    return "67.8.0" if sys.version_info[:2] >= (3, 12) else "43.0.0"


@pytest.fixture
def setuptools_requirement(setuptools_version):
    # type: (str) -> str
    return "setuptools=={version}".format(version=setuptools_version)


def test_pex_run_custom_setuptools_useable(
    setuptools_requirement,  # type: str
    setuptools_version,  # type: str
):
    # type: (...) -> None
    result = resolver.resolve(
        requirements=[setuptools_requirement],
        resolver=ConfiguredResolver.default(),
    )
    dists = [resolved_dist.distribution for resolved_dist in result.distributions]
    with temporary_dir() as temp_dir:
        pex = write_simple_pex(
            temp_dir,
            "import setuptools, sys; sys.exit(0 if '{version}' == setuptools.__version__ else 1)".format(
                version=setuptools_version
            ),
            dists=dists,
        )
        rc = PEX(pex.path()).run()
        assert rc == 0


def test_pex_run_conflicting_custom_setuptools_useable(
    setuptools_requirement,  # type: str
    setuptools_version,  # type: str
):
    # type: (...) -> None
    # Here we use our vendored, newer setuptools to build the pex which has an older setuptools
    # requirement.

    result = resolver.resolve(
        requirements=[setuptools_requirement],
        resolver=ConfiguredResolver.default(),
    )
    dists = [resolved_dist.distribution for resolved_dist in result.distributions]
    with temporary_dir() as temp_dir:
        pex = write_simple_pex(
            temp_dir,
            exe_contents=textwrap.dedent(
                """
                import sys
                import setuptools

                sys.exit(0 if '{version}' == setuptools.__version__ else 1)
                """.format(
                    version=setuptools_version
                )
            ),
            dists=dists,
        )
        rc = PEX(pex.path()).run(env={"PEX_VERBOSE": "9"})
        assert rc == 0


def test_pex_run_custom_pex_useable():
    # type: () -> None
    old_pex_version = "0.7.0"
    result = resolver.resolve(
        requirements=["pex=={}".format(old_pex_version), "setuptools==40.6.3"],
        resolver=ConfiguredResolver.default(),
    )
    dists = [resolved_dist.distribution for resolved_dist in result.distributions]
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
                  # N.B.: pkg_resources is not supported by Python >= 3.12.
                  if sys.version_info[:2] >= (3, 12):
                      from importlib.metadata import distribution
                      dist = distribution('pex')
                  else:
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

    # See https://github.com/pex-tool/pex/issues/1101 and
    # https://github.com/pantsbuild/pants/issues/11058 for the motivating issue.
    with temporary_dir() as pex_chroot:
        pex_builder = PEXBuilder(path=pex_chroot)
        pex_builder.freeze()

        output = subprocess.check_output(
            args=[sys.executable, "-W", "error::ResourceWarning", pex_chroot, "-c", ""],
            stderr=subprocess.STDOUT,
        )
        assert b"" == output
