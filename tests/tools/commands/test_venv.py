# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import errno
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
from subprocess import CalledProcessError
from textwrap import dedent

import pytest

from pex.common import safe_mkdtemp, safe_open, temporary_dir, touch
from pex.compatibility import PY2
from pex.executor import Executor
from pex.interpreter import PythonInterpreter
from pex.layout import Layout
from pex.pex_builder import CopyMode, PEXBuilder
from pex.testing import IS_PYPY, PY310, PY_VER, ensure_python_interpreter, run_pex_command
from pex.typing import TYPE_CHECKING, cast
from pex.util import named_temporary_file
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import Any, Dict, Iterable, Iterator, List, Optional, Protocol, Set, Text, Tuple

    class CreatePexVenv(Protocol):
        def __call__(self, *options):
            # type: (*str) -> Virtualenv
            pass


FABRIC_VERSION = "2.5.0"


@pytest.fixture(scope="module")
def pex():
    # type: () -> Iterator[str]
    with temporary_dir() as tmpdir:
        pex_path = os.path.join(tmpdir, "fabric.pex")

        src_dir = os.path.join(tmpdir, "src")
        touch(os.path.join(src_dir, "user/__init__.py"))
        touch(os.path.join(src_dir, "user/package/__init__.py"))

        # Fabric dips into Invoke vendored code. It depends on "invoke<2.0,>=1.3", but in version
        # 1.7.0, the vendored `decorator` module Fabric depends on inside Invoke no longer is
        # importable under Python 2.7; so we pin low.
        constraints = os.path.join(tmpdir, "constraints.txt")
        with open(constraints, "w") as fp:
            fp.write("Invoke==1.6.0")

        # N.B.: --unzip just speeds up runs 2+ of the pex file and is otherwise not relevant to
        # these tests.
        run_pex_command(
            args=[
                "fabric=={}".format(FABRIC_VERSION),
                "--constraints",
                constraints,
                "-c",
                "fab",
                "--sources-directory",
                src_dir,
                "-o",
                pex_path,
                "--include-tools",
            ]
        )
        yield os.path.realpath(pex_path)


def make_env(**kwargs):
    # type: (**Any) -> Dict[str, str]
    env = os.environ.copy()
    env.update((k, str(v)) for k, v in kwargs.items())
    return env


@pytest.fixture
def create_pex_venv(pex):
    # type: (str) -> Iterator[CreatePexVenv]
    with temporary_dir() as tmpdir:
        venv_dir = os.path.join(tmpdir, "venv")

        def _create_pex_venv(*options):
            # type: (*str) -> Virtualenv
            subprocess.check_call(
                args=[pex, "venv", venv_dir] + list(options or ()), env=make_env(PEX_TOOLS="1")
            )
            return Virtualenv(venv_dir)

        yield _create_pex_venv


def test_force(create_pex_venv):
    # type: (CreatePexVenv) -> None
    venv = create_pex_venv("--pip")
    venv.interpreter.execute(args=["-m", "pip", "install", "ansicolors==1.1.8"])
    venv.interpreter.execute(args=["-c", "import colors"])

    with pytest.raises(CalledProcessError):
        create_pex_venv()

    venv_force = create_pex_venv("--force")
    # The re-created venv should have no ansicolors installed like the prior venv.
    with pytest.raises(Executor.NonZeroExit):
        venv_force.interpreter.execute(args=["-c", "import colors"])
    # The re-created venv should have no pip installed either.
    with pytest.raises(Executor.NonZeroExit):
        venv.interpreter.execute(args=["-m", "pip", "install", "ansicolors==1.1.8"])


def execute_venv_pex_interpreter(
    venv,  # type: Virtualenv
    code=None,  # type: Optional[str]
    extra_args=(),  # type: Iterable[str]
    **extra_env  # type: Any
):
    # type: (...) -> Tuple[int, Text, Text]
    process = subprocess.Popen(
        args=[venv.join_path("pex")] + list(extra_args),
        env=make_env(PEX_INTERPRETER=True, **extra_env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
    )
    stdout, stderr = process.communicate(input=None if code is None else code.encode())
    return process.returncode, stdout.decode("utf-8"), stderr.decode("utf-8")


def expected_file_path(
    venv,  # type: Virtualenv
    package,  # type: str
):
    # type: (...) -> str
    return os.path.realpath(
        os.path.join(
            venv.site_packages_dir,
            os.path.sep.join(package.split(".")),
            "__init__.{ext}".format(ext="pyc" if venv.interpreter.version[0] == 2 else "py"),
        )
    )


def parse_fabric_version_output(output):
    # type: (Text) -> Dict[Text, Text]
    return dict(cast("Tuple[Text, Text]", line.split(" ", 1)) for line in output.splitlines())


def test_venv_pex(create_pex_venv):
    # type: (CreatePexVenv) -> None
    venv = create_pex_venv()
    venv_pex = venv.join_path("pex")

    fabric_output = subprocess.check_output(args=[venv_pex, "-V"])

    # N.B.: `fab -V` output looks like so:
    # $ fab -V
    # Fabric 2.5.0
    # Paramiko 2.7.2
    # Invoke 1.4.1
    versions = parse_fabric_version_output(fabric_output.decode("utf-8"))
    assert FABRIC_VERSION == versions["Fabric"]

    invoke_version = "Invoke {}".format(versions["Invoke"])
    invoke_script_output = subprocess.check_output(
        args=[venv_pex, "-V"], env=make_env(PEX_SCRIPT="invoke")
    )
    assert invoke_version == invoke_script_output.decode("utf-8").strip()

    invoke_entry_point_output = subprocess.check_output(
        args=[venv_pex, "-V"],
        env=make_env(PEX_MODULE="invoke.main:program.run"),
    )
    assert invoke_version == invoke_entry_point_output.decode("utf-8").strip()

    pex_extra_sys_path = ["/dev/null", "Bob"]
    returncode, _, stderr = execute_venv_pex_interpreter(
        venv,
        code=dedent(
            """\
            from __future__ import print_function

            import os
            import sys


            def assert_equal(test_num, expected, actual):
                if expected == actual:
                    return
                print(
                    "[{{}}] Expected {{}} but got {{}}".format(test_num, expected, actual),
                    file=sys.stderr,
                )
                sys.exit(test_num)

            assert_equal(1, {pex_extra_sys_path!r}, sys.path[-2:])

            import fabric
            assert_equal(2, {fabric!r}, os.path.realpath(fabric.__file__))

            import user.package
            assert_equal(3, {user_package!r}, os.path.realpath(user.package.__file__))
            """.format(
                pex_extra_sys_path=pex_extra_sys_path,
                fabric=expected_file_path(venv, "fabric"),
                user_package=expected_file_path(venv, "user.package"),
            )
        ),
        PEX_EXTRA_SYS_PATH=os.pathsep.join(pex_extra_sys_path),
    )
    assert 0 == returncode, stderr


def test_binary_path(create_pex_venv):
    # type: (CreatePexVenv) -> None
    code = dedent(
        """\
        import errno
        import subprocess
        import sys

        # PEXed code should be able to find all (console) scripts on the $PATH when the venv is
        # created with --bin-path set, and the scripts should all run with the venv interpreter in
        # order to find their code.

        def try_invoke(*args):
            try:
                subprocess.check_call(list(args))
                return 0
            except OSError as e:
                if e.errno == errno.ENOENT:
                    # This is what we expect when scripts are not set up on PATH via --bin-path.
                    return 1
                return 2

        exit_code = try_invoke("fab", "-V")
        exit_code += 10 * try_invoke("inv", "-V")
        exit_code += 100 * try_invoke("invoke", "-V")
        sys.exit(exit_code)
        """
    )

    venv = create_pex_venv()
    returncode, stdout, stderr = execute_venv_pex_interpreter(
        venv, code=code, PATH=tempfile.gettempdir()
    )
    assert 111 == returncode, stdout + stderr

    venv_bin_path = create_pex_venv("-f", "--bin-path", "prepend")
    returncode, _, _ = execute_venv_pex_interpreter(
        venv_bin_path, code=code, PATH=tempfile.gettempdir()
    )
    assert 0 == returncode


def test_venv_pex_interpreter_special_modes(create_pex_venv):
    # type: (CreatePexVenv) -> None
    venv = create_pex_venv()

    # special mode execute module: -m module
    returncode, stdout, stderr = execute_venv_pex_interpreter(venv, extra_args=["-m"])
    assert 2 == returncode, stderr
    assert "" == stdout

    returncode, stdout, stderr = execute_venv_pex_interpreter(
        venv, extra_args=["-m", "fabric", "--version"]
    )
    assert 0 == returncode, stderr
    versions = parse_fabric_version_output(stdout)
    assert FABRIC_VERSION == versions["Fabric"]

    # special mode execute code string: -c <str>
    returncode, stdout, stderr = execute_venv_pex_interpreter(venv, extra_args=["-c"])
    assert 2 == returncode, stderr
    assert "" == stdout

    fabric_file_code = "import fabric, os; print(os.path.realpath(fabric.__file__))"
    expected_fabric_file_path = expected_file_path(venv, "fabric")

    returncode, stdout, stderr = execute_venv_pex_interpreter(
        venv, extra_args=["-c", fabric_file_code]
    )
    assert 0 == returncode, stderr
    assert expected_fabric_file_path == stdout.strip()

    # special mode execute stdin: -
    returncode, stdout, stderr = execute_venv_pex_interpreter(
        venv, code=fabric_file_code, extra_args=["-"]
    )
    assert 0 == returncode, stderr
    assert expected_fabric_file_path == stdout.strip()

    # special mode execute python file: <py file name>
    with named_temporary_file(prefix="code", suffix=".py", mode="w") as fp:
        fp.write(fabric_file_code)
        fp.close()
        returncode, stdout, stderr = execute_venv_pex_interpreter(
            venv, code=fabric_file_code, extra_args=[fp.name]
        )
        assert 0 == returncode, stderr
        assert expected_fabric_file_path == stdout.strip()


@pytest.mark.parametrize(
    "start_method", getattr(multiprocessing, "get_all_start_methods", lambda: [None])()
)
def test_venv_multiprocessing_issues_1236(
    tmpdir,  # type: Any
    start_method,  # type: Optional[str]
):
    # type: (...) -> None
    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "foo.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                def bar():
                    print('hello')
                """
            )
        )
    with safe_open(os.path.join(src, "main.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import multiprocessing
                from foo import bar

                if __name__ == '__main__':
                    if {start_method!r}:
                        multiprocessing.set_start_method({start_method!r})
                    p = multiprocessing.Process(target=bar)
                    p.start()
                """.format(
                    start_method=start_method
                )
            )
        )

    pex_file = os.path.join(str(tmpdir), "mp.pex")
    result = run_pex_command(args=["-D", src, "-m", "main", "-o", pex_file, "--include-tools"])
    result.assert_success()

    # Confirm multiprocessing works via normal PEX file execution.
    output = subprocess.check_output(args=[pex_file])
    assert "hello" == output.decode("utf-8").strip()

    # Confirm multiprocessing works via the `pex` venv script.
    venv = os.path.join(str(tmpdir), "venv")
    subprocess.check_call(args=[pex_file, "venv", venv], env=make_env(PEX_TOOLS=True))
    output = subprocess.check_output(args=[os.path.join(venv, "pex")])
    assert "hello" == output.decode("utf-8").strip()


def test_venv_symlinked_source_issues_1239(tmpdir):
    # type: (Any) -> None
    src = os.path.join(str(tmpdir), "src")
    main = os.path.join(src, "main.py")
    with safe_open(main, "w") as fp:
        fp.write("import sys; sys.exit(42)")

    pex_builder = PEXBuilder(copy_mode=CopyMode.SYMLINK)
    pex_builder.set_executable(main)
    pex_file = os.path.join(str(tmpdir), "a.pex")
    pex_builder.build(pex_file, bytecode_compile=False)
    assert 42 == subprocess.Popen(args=[pex_file]).wait()

    venv = os.path.join(str(tmpdir), "a.venv")
    subprocess.check_call(
        args=[sys.executable, "-m", "pex.tools", pex_builder.path(), "venv", venv]
    )
    venv_pex = os.path.join(venv, "pex")
    shutil.rmtree(src)
    assert 42 == subprocess.Popen(args=[venv_pex]).wait()


def test_venv_entrypoint_function_exit_code_issue_1241(tmpdir):
    # type: (Any) -> None

    pex_file = os.path.join(str(tmpdir), "ep-function.pex")
    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "module.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import sys


                def target():
                    args = sys.argv[1:]
                    if args:
                        exit = args[0]
                        try:
                            return int(exit)
                        except ValueError:
                            return exit
                """
            )
        )
    result = run_pex_command(
        args=["-D", src, "-e", "module:target", "--include-tools", "-o", pex_file]
    )
    result.assert_success()

    venv = os.path.join(str(tmpdir), "ep-function.venv")
    subprocess.check_call(args=[pex_file, "venv", venv], env=make_env(PEX_TOOLS=1))

    venv_pex = os.path.join(venv, "pex")
    assert 0 == subprocess.Popen(args=[venv_pex]).wait()

    def assert_venv_process(
        args,  # type: List[str]
        expected_returncode,  # type: int
        expected_stdout="",  # type: str
        expected_stderr="",  # type: str
    ):
        # type: (...) -> None
        process = subprocess.Popen(
            args=[venv_pex] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()
        assert expected_returncode == process.returncode
        assert expected_stdout == stdout.decode("utf-8")
        assert expected_stderr == stderr.decode("utf-8")

    assert_venv_process(args=["bob"], expected_returncode=1, expected_stderr="bob\n")
    assert_venv_process(args=["42"], expected_returncode=42)


def test_venv_copies(tmpdir):
    # type: (Any) -> None

    python310 = ensure_python_interpreter(PY310)

    pex_file = os.path.join(str(tmpdir), "venv.pex")
    result = run_pex_command(args=["-o", pex_file, "--include-tools"], python=python310)
    result.assert_success()

    PEX_TOOLS = make_env(PEX_TOOLS=1)

    venv_symlinks = os.path.join(str(tmpdir), "venv.symlinks")
    subprocess.check_call(args=[python310, pex_file, "venv", venv_symlinks], env=PEX_TOOLS)
    venv_symlinks_interpreter = PythonInterpreter.from_binary(
        os.path.join(venv_symlinks, "bin", "python")
    )
    assert os.path.islink(venv_symlinks_interpreter.binary)

    venv_copies = os.path.join(str(tmpdir), "venv.copies")
    subprocess.check_call(
        args=[python310, pex_file, "venv", "--copies", venv_copies], env=PEX_TOOLS
    )
    venv_copies_interpreter = PythonInterpreter.from_binary(
        os.path.join(venv_copies, "bin", "python")
    )
    assert not os.path.islink(venv_copies_interpreter.binary)


def test_relocatable_venv(tmpdir):
    # type: (Any) -> None

    pex_file = os.path.join(str(tmpdir), "relocatable.pex")
    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "main.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import sys
                from colors import blue


                print(blue(sys.executable))
                """
            )
        )
    result = run_pex_command(
        args=["-D", src, "ansicolors==1.1.8", "-m", "main", "--include-tools", "-o", pex_file]
    )
    result.assert_success()

    venv = os.path.join(str(tmpdir), "relocatable.venv")
    subprocess.check_call(args=[pex_file, "venv", venv], env=make_env(PEX_TOOLS=1))
    subprocess.check_call(args=[os.path.join(venv, "pex")])

    relocated_relpath = "relocated.venv"
    relocated_venv = os.path.join(str(tmpdir), relocated_relpath)

    # Since the venv pex script contains a shebang with an absolute path to the venv python
    # interpreter, a move of the venv makes the script un-runnable directly.
    shutil.move(venv, relocated_venv)
    with pytest.raises(OSError) as exec_info:
        subprocess.check_call(args=[os.path.join(relocated_venv, "pex")])
    assert errno.ENOENT == exec_info.value.errno

    # But we should be able to run the script using the moved venv's interpreter.
    subprocess.check_call(
        args=[
            os.path.join(relocated_relpath, "bin", "python"),
            os.path.join(relocated_relpath, "pex"),
        ],
        cwd=str(tmpdir),
    )


def test_compile(tmpdir):
    # type: (Any) -> None

    def collect_files(
        root_dir,  # type: str
        extension,  # type: str
    ):
        # type: (...) -> Set[str]
        return {
            os.path.relpath(os.path.join(root, f), root_dir)
            for root, _, files in os.walk(root_dir, followlinks=False)
            for f in files
            if f.endswith(extension)
        }

    pex_file = os.path.join(str(tmpdir), "compile.pex")
    src = os.path.join(str(tmpdir), "src")
    with safe_open(os.path.join(src, "main.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from colors import yellow

            
                print(yellow("Slartibartfast"))
                """
            )
        )
    result = run_pex_command(
        args=["-D", src, "ansicolors==1.0.2", "-m", "main", "--include-tools", "-o", pex_file]
    )
    result.assert_success()

    venv = os.path.join(str(tmpdir), "venv")
    subprocess.check_call(args=[pex_file, "venv", venv], env=make_env(PEX_TOOLS=1))
    # N.B.: The right way to discover the site-packages dir is via site.getsitepackages().
    # Unfortunately we use an old version of virtualenv to create PyPy and CPython 2.7 venvs and it
    # does not add a getsitepackages function to site.py; so we cheat.
    if IS_PYPY:
        site_packages = "site-packages"
    else:
        site_packages = os.path.join(
            "lib", "python{}.{}".format(sys.version_info[0], sys.version_info[1]), "site-packages"
        )

    # Ensure we have at least the basic direct dependency python files we expect.
    venv_py_files = collect_files(venv, ".py")
    assert os.path.join(site_packages, "main.py") in venv_py_files
    assert os.path.join(site_packages, "colors.py") in venv_py_files
    assert "__main__.py" in venv_py_files

    compile_venv = os.path.join(str(tmpdir), "compile.venv")
    subprocess.check_call(
        args=[pex_file, "venv", "--compile", compile_venv], env=make_env(PEX_TOOLS=1)
    )
    # Ensure all original py files have a compiled counterpart.
    for py_file in venv_py_files:
        if PY2:
            assert os.path.exists(os.path.join(compile_venv, py_file + "c"))
        else:
            name, _ = os.path.splitext(os.path.basename(py_file))
            assert os.path.exists(
                os.path.join(
                    compile_venv,
                    os.path.dirname(py_file),
                    "__pycache__",
                    "{name}.{cache_tag}.pyc".format(
                        name=name, cache_tag=sys.implementation.cache_tag
                    ),
                )
            )

    compile_venv_pyc_files = collect_files(compile_venv, ".pyc")
    subprocess.check_call(args=[os.path.join(compile_venv, "pex")])
    assert compile_venv_pyc_files == collect_files(
        compile_venv, ".pyc"
    ), "Expected no new compiled python files."


def test_strip_pex_env(tmpdir):
    # type: (Any) -> None

    def create_pex_venv(strip_pex_env):
        # type: (bool) -> str
        pex = os.path.join(str(tmpdir), "strip_{}.pex".format(strip_pex_env))
        run_pex_command(
            args=[
                "--strip-pex-env" if strip_pex_env else "--no-strip-pex-env",
                "--include-tools",
                "-o",
                pex,
            ]
        ).assert_success()

        venv = os.path.join(str(tmpdir), "strip_{}.venv".format(strip_pex_env))
        subprocess.check_call(args=[pex, "venv", venv], env=make_env(PEX_TOOLS=1))
        return venv

    check_pex_env_vars_code = dedent(
        """\
        from __future__ import print_function

        import os
        import sys


        pex_env_vars = 0
        for name, value in os.environ.items():
            if name.startswith("PEX_"):
                pex_env_vars += 1
                print(
                    "Un-stripped: {name}={value}".format(name=name, value=value), file=sys.stderr
                )
        sys.exit(pex_env_vars)
        """
    )

    two_pex_env_vars = {
        name: value
        for name, value in make_env(PEX_ROOT="42", PEX_TOOLS=1).items()
        if name in ("PEX_ROOT", "PEX_TOOLS") or not name.startswith("PEX_")
    }
    assert 2 == len([name for name in two_pex_env_vars if name.startswith("PEX_")])

    strip_venv = create_pex_venv(strip_pex_env=True)
    subprocess.check_call(
        args=[os.path.join(strip_venv, "pex"), "-c", check_pex_env_vars_code], env=two_pex_env_vars
    )

    no_strip_venv = create_pex_venv(strip_pex_env=False)
    process = subprocess.Popen(
        args=[os.path.join(no_strip_venv, "pex"), "-c", check_pex_env_vars_code],
        env=two_pex_env_vars,
    )
    assert 2 == process.wait()


def test_warn_unused_pex_env_vars():
    # type: () -> None
    # N.B.: We don't use the pytest tmpdir fixture here since it creates fairly length paths under
    # /tmp and under macOS, where TMPDIR is already fairly deeply nested, we trigger Pex warinings
    # about script shebang length. Those warnings pollute stderr.
    tmpdir = safe_mkdtemp()
    venv_pex = os.path.join(tmpdir, "venv.pex")
    run_pex_command(["--venv", "-o", venv_pex]).assert_success()

    def assert_execute_venv_pex(expected_stderr, **env_vars):
        env = os.environ.copy()
        env.update(env_vars)
        process = subprocess.Popen(
            [venv_pex, "-c", ""], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
        )
        stdout, stderr = process.communicate()
        assert 0 == process.returncode
        assert not stdout
        assert expected_stderr.strip() == stderr.decode("utf-8").strip()

    assert_execute_venv_pex(expected_stderr="")
    assert_execute_venv_pex(expected_stderr="", PEX_ROOT=os.path.join(tmpdir, "pex_root"))
    assert_execute_venv_pex(expected_stderr="", PEX_VENV="1")
    assert_execute_venv_pex(expected_stderr="", PEX_EXTRA_SYS_PATH="more")
    assert_execute_venv_pex(expected_stderr="", PEX_VERBOSE="0")

    assert_execute_venv_pex(
        expected_stderr=dedent(
            """\
            Ignoring the following environment variables in Pex venv mode:
            PEX_INHERIT_PATH=fallback
            """
        ),
        PEX_INHERIT_PATH="fallback",
    )

    assert_execute_venv_pex(
        expected_stderr=dedent(
            """\
            Ignoring the following environment variables in Pex venv mode:
            PEX_COVERAGE=1
            PEX_INHERIT_PATH=fallback
            """
        ),
        PEX_COVERAGE="1",
        PEX_INHERIT_PATH="fallback",
        PEX_VERBOSE="0",
    )


def test_custom_prompt(tmpdir):
    # type: (Any) -> None
    pex_root = os.path.join(str(tmpdir), "pex_root")
    venv_pex = os.path.join(str(tmpdir), "venv.pex")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            "-o",
            venv_pex,
            "--include-tools",
        ]
    ).assert_success()

    venv_dir = os.path.join(str(tmpdir), "venv_dir")
    subprocess.check_call(
        args=[venv_pex, "venv", "--prompt", "jane", venv_dir], env=make_env(PEX_TOOLS=True)
    )

    if PY_VER == (2, 7) or IS_PYPY:
        # Neither CPython 2.7 not PyPy interpreters have (functioning) venv modules; so we create
        # their venvs with an old copy of virtualenv that does not surround the prompt with parens.
        expected_prompt = "jane"
    elif PY_VER == (3, 5):
        # We can't set the prompt for CPython 3.5 so we expect the name of the venv dir.
        expected_prompt = "(venv_dir)"
    else:
        expected_prompt = "(jane)"

    output = subprocess.check_output(
        args=[
            "/usr/bin/env",
            "bash",
            "-c",
            "source {} && echo $PS1".format(os.path.join(venv_dir, "bin", "activate")),
        ],
        env=make_env(TERM="dumb", COLS=80),
    )
    assert expected_prompt == output.decode("utf-8").strip()


@pytest.mark.parametrize(
    "layout", [pytest.param(layout, id=layout.value) for layout in Layout.values()]
)
def test_remove(
    tmpdir,
    layout,  # type: Layout.Value
):
    # type: (...) -> None
    pex_root = os.path.join(str(tmpdir), "pex_root")

    def create_venv_pex():
        # type: () -> str
        venv_pex = os.path.join(str(tmpdir), "venv.pex")
        run_pex_command(
            args=[
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                "-o",
                venv_pex,
                "--include-tools",
            ]
        ).assert_success()
        return venv_pex

    venv_dir = os.path.join(str(tmpdir), "venv_dir")
    assert not os.path.exists(venv_dir)

    venv_pex = create_venv_pex()
    subprocess.check_call(args=[venv_pex, "venv", venv_dir], env=make_env(PEX_TOOLS=True))
    assert os.path.exists(venv_dir)
    assert os.path.exists(venv_pex)
    assert os.path.exists(pex_root)

    shutil.rmtree(venv_dir)
    assert not os.path.exists(venv_dir)

    subprocess.check_call(
        args=[venv_pex, "venv", "--rm", "pex", venv_dir], env=make_env(PEX_TOOLS=True)
    )
    assert os.path.exists(venv_dir)
    assert not os.path.exists(venv_pex)
    assert os.path.exists(pex_root)

    shutil.rmtree(venv_dir)
    assert not os.path.exists(venv_dir)
    venv_pex = create_venv_pex()

    subprocess.check_call(
        args=[venv_pex, "venv", "--rm", "all", venv_dir], env=make_env(PEX_TOOLS=True)
    )
    assert os.path.exists(venv_dir)
    assert not os.path.exists(venv_pex)
    assert not os.path.exists(pex_root)
