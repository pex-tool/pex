# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import glob
import os.path
import shutil
import subprocess
import sys
from textwrap import dedent

import colors  # vendor:skip
import pytest

from pex import dist_metadata
from pex.cli.commands.venv import InstallLayout
from pex.common import open_zip, safe_open
from pex.compatibility import commonpath
from pex.dist_metadata import Distribution
from pex.interpreter import PythonInterpreter
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.resolve import abbreviated_platforms
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import Virtualenv
from testing import IS_MAC, PY39, PY310, ensure_python_interpreter, make_env, run_pex_command
from testing.cli import run_pex3
from testing.pytest.tmp import Tempdir, TempdirFactory

if TYPE_CHECKING:
    from typing import Any


@pytest.fixture(scope="module")
def td(
    tmpdir_factory,  # type: TempdirFactory
    request,  # type: Any
):
    # type: (...) -> Tempdir

    return tmpdir_factory.mktemp("td", request=request)


@pytest.fixture(scope="module")
def lock(td):
    # type: (Any) -> str

    lock = str(td.join("lock.json"))
    run_pex3(
        "lock", "create", "cowsay==5.0", "ansicolors==1.1.8", "-o", lock, "--indent", "2"
    ).assert_success()
    return lock


@pytest.fixture(scope="module")
def cowsay_pex(
    td,  # type: Any
    lock,  # type: str
):
    # type: (...) -> str

    pex = str(td.join("pex"))
    run_pex_command(args=["--lock", lock, "--include-tools", "-o", pex]).assert_success()
    assert sorted(
        [(ProjectName("cowsay"), Version("5.0")), (ProjectName("ansicolors"), Version("1.1.8"))]
    ) == [(dist.metadata.project_name, dist.metadata.version) for dist in PEX(pex).resolve()]
    return pex


@pytest.fixture(scope="module")
def pre_resolved_dists(
    td,  # type: Any
    cowsay_pex,  # type: str
):
    # type: (...) -> str

    dists_dir = str(td.join("dists"))
    subprocess.check_call(
        args=[cowsay_pex, "repository", "extract", "-f", dists_dir], env=make_env(PEX_TOOLS=1)
    )
    assert sorted(
        [(ProjectName("cowsay"), Version("5.0")), (ProjectName("ansicolors"), Version("1.1.8"))]
    ) == sorted(
        [
            (dist.metadata.project_name, dist.metadata.version)
            for dist in map(Distribution.load, glob.glob(os.path.join(dists_dir, "*.whl")))
        ]
    )
    return dists_dir


def test_venv_empty(tmpdir):
    # type: (Any) -> None

    dest = os.path.join(str(tmpdir), "dest")
    run_pex3("venv", "create", "-d", dest).assert_success()
    venv = Virtualenv(dest)
    assert (
        PythonInterpreter.get().resolve_base_interpreter()
        == venv.interpreter.resolve_base_interpreter()
    )
    assert [] == list(venv.iter_distributions())


def assert_venv(
    tmpdir,  # type: Any
    *extra_args  # type: str
):
    # type: (...) -> None

    dest = os.path.join(str(tmpdir), "dest")
    run_pex3("venv", "create", "cowsay==5.0", "-d", dest, *extra_args).assert_success()

    venv = Virtualenv(dest)
    _, stdout, _ = venv.interpreter.execute(
        args=["-c", "import cowsay, os; print(os.path.realpath(cowsay.__file__))"]
    )
    assert venv.site_packages_dir == commonpath([venv.site_packages_dir, stdout.strip()])

    _, stdout, _ = venv.interpreter.execute(args=["-m", "cowsay", "--version"])
    assert "5.0" == stdout.strip()

    assert (
        "5.0"
        == subprocess.check_output(args=[venv.bin_path("cowsay"), "--version"])
        .decode("utf-8")
        .strip()
    )

    assert [(ProjectName("cowsay"), Version("5.0"))] == [
        (dist.metadata.project_name, dist.metadata.version) for dist in venv.iter_distributions()
    ]


def test_venv(
    tmpdir,  # type: Any
    lock,  # type: str
    cowsay_pex,  # type: str
    pre_resolved_dists,  # type: str
):
    # type: (...) -> None

    assert_venv(tmpdir)
    assert_venv(tmpdir, "--lock", lock)
    assert_venv(tmpdir, "--pex-repository", cowsay_pex)
    assert_venv(tmpdir, "--pre-resolved-dists", pre_resolved_dists)


def test_flat_empty(tmpdir):
    # type: (Any) -> None

    dest = os.path.join(str(tmpdir), "dest")
    run_pex3("venv", "create", "--layout", "flat", "-d", dest).assert_success()
    assert [] == list(dist_metadata.find_distributions(search_path=[dest]))


def test_flat_zipped_empty(tmpdir):
    # type: (Any) -> None

    dest = os.path.join(str(tmpdir), "dest")
    run_pex3("venv", "create", "--layout", "flat-zipped", "-d", dest).assert_success()
    assert [] == list(dist_metadata.find_distributions(search_path=[dest]))
    with open_zip("{dest}.zip".format(dest=dest)) as zf:
        assert [] == zf.namelist()


def assert_flat(
    tmpdir,  # type: Any
    layout,  # type: InstallLayout.Value
    *extra_args  # type: str
):
    # type: (...) -> None

    dest = os.path.join(str(tmpdir), "dest")
    run_pex3(
        "venv", "create", "--layout", str(layout), "cowsay==5.0", "-d", dest, *extra_args
    ).assert_success()

    sys_path_entry = dest if layout is InstallLayout.FLAT else "{dest}.zip".format(dest=dest)
    env = make_env(PYTHONPATH=sys_path_entry)

    assert sys_path_entry == commonpath(
        [
            sys_path_entry,
            subprocess.check_output(
                args=[sys.executable, "-c", "import cowsay; print(cowsay.__file__)"], env=env
            )
            .decode("utf-8")
            .strip(),
        ]
    )

    assert (
        "5.0"
        == subprocess.check_output(args=[sys.executable, "-m", "cowsay", "--version"], env=env)
        .decode("utf-8")
        .strip()
    )

    if layout is InstallLayout.FLAT_ZIPPED:
        search_path_entry = os.path.join(str(tmpdir), "zip_contents")
        with open_zip(sys_path_entry) as zf:
            zf.extractall(search_path_entry)
    else:
        search_path_entry = dest

    assert [(ProjectName("cowsay"), Version("5.0"))] == [
        (dist.metadata.project_name, dist.metadata.version)
        for dist in dist_metadata.find_distributions(search_path=[search_path_entry])
    ]


@pytest.mark.parametrize(
    "layout",
    [
        pytest.param(layout, id=str(layout))
        for layout in (InstallLayout.FLAT, InstallLayout.FLAT_ZIPPED)
    ],
)
def test_flat(
    tmpdir,  # type: Any
    layout,  # type: InstallLayout.Value
    lock,  # type: str
    cowsay_pex,  # type: str
):
    # type: (...) -> None

    assert_flat(tmpdir, layout)
    assert_flat(tmpdir, layout, "--lock", lock)
    assert_flat(tmpdir, layout, "--pex-repository", cowsay_pex)


def test_flat_zipped_prefix(
    tmpdir,  # type: Any
    lock,  # type: str
):
    # type: (...) -> None

    dest = os.path.join(str(tmpdir), "dest")
    run_pex3(
        "venv",
        "create",
        "ansicolors",
        "--lock",
        lock,
        "--layout",
        "flat-zipped",
        "--prefix",
        "python",
        "-d",
        dest,
    ).assert_success()

    sys_path_entry = os.path.join("{dest}.zip".format(dest=dest), "python")
    assert (
        colors.cyan("ide")
        == subprocess.check_output(
            args=[sys.executable, "-c", "import colors; print(colors.cyan('ide'))"],
            env=make_env(PYTHONPATH=sys_path_entry),
        )
        .decode("utf-8")
        .strip()
    )


def test_venv_pip(tmpdir):
    # type: (Any) -> None

    dest = os.path.join(str(tmpdir), "dest")
    run_pex3("venv", "create", "-d", dest).assert_success()

    venv = Virtualenv(dest)
    assert "pip" not in [os.path.basename(exe) for exe in venv.iter_executables()]
    assert [] == list(venv.iter_distributions())

    run_pex3("venv", "create", "-d", dest, "--pip").assert_success()
    assert "pip" in [os.path.basename(exe) for exe in venv.iter_executables()]
    distributions = {
        dist.metadata.project_name: dist.metadata.version
        for dist in venv.iter_distributions(rescan=True)
    }
    pip_version = distributions[ProjectName("pip")]
    expected_prefix = "pip {version} from {prefix}".format(version=pip_version.raw, prefix=dest)
    assert (
        subprocess.check_output(args=[venv.bin_path("pip"), "--version"])
        .decode("utf-8")
        .startswith(expected_prefix)
    )


@pytest.fixture(scope="module")
def colors_pex(
    td,  # type: Any
    lock,  # type: str
):
    # type: (...) -> str

    src = str(td.join("src"))
    with safe_open(os.path.join(src, "exe.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import colors


                print(colors.magenta("Red Dwarf"))
                """
            )
        )
    pex = str(td.join("pex"))
    run_pex_command(
        args=["--lock", lock, "ansicolors", "-D", src, "-m", "exe", "-o", pex]
    ).assert_success()
    return pex


def assert_deps_only(
    interpreter,  # type: PythonInterpreter
    expected_prefix,  # type: str
    **extra_env  # type: str
):
    # type: (...) -> None

    assert expected_prefix == commonpath(
        [
            expected_prefix,
            subprocess.check_output(
                args=[
                    interpreter.binary,
                    "-c",
                    dedent(
                        """\
                        import os
                        import sys

                        import colors

                        try:
                            import exe
                            sys.exit("The deps scope should not have included the exe.py src.")
                        except ImportError:
                            pass

                        print(os.path.realpath(colors.__file__))
                        """
                    ),
                ],
                env=make_env(**extra_env),
            )
            .decode("utf-8")
            .strip(),
        ]
    )


def assert_srcs_only(
    sys_path_entry,  # type: str
    *extra_srcs  # type: str
):
    # type: (...) -> None

    assert sorted(list(extra_srcs) + ["exe.py"]) == sorted(
        os.path.relpath(os.path.join(root, f), sys_path_entry)
        for root, _, files in os.walk(sys_path_entry)
        for f in files
    )


def test_pex_scope_venv(
    tmpdir,  # type: Any
    colors_pex,  # type: str
):
    # type: (...) -> None

    dest = os.path.join(str(tmpdir), "dest")
    run_pex3(
        "venv", "create", "-d", dest, "--pex-repository", colors_pex, "--scope", "deps"
    ).assert_success()

    venv_pex_script = os.path.join(dest, "pex")
    assert not os.path.exists(venv_pex_script)

    venv = Virtualenv(dest)
    assert_deps_only(interpreter=venv.interpreter, expected_prefix=venv.site_packages_dir)

    def install_srcs():
        # type: () -> None
        run_pex3(
            "venv", "create", "-d", dest, "--pex-repository", colors_pex, "--scope", "srcs"
        ).assert_success()

    install_srcs()
    assert (
        colors.magenta("Red Dwarf")
        == subprocess.check_output(args=[venv_pex_script]).decode("utf-8").strip()
    )

    shutil.rmtree(dest)
    install_srcs()
    assert_srcs_only(
        venv.site_packages_dir,
        # Any venv created from a PEX supports the PEX_EXTRA_SYS_PATH runtime env var via this
        # `.pth` file.
        "PEX_EXTRA_SYS_PATH.pth",
    )


def test_pex_scope_flat(
    tmpdir,  # type: Any
    colors_pex,  # type: str
):
    # type: (...) -> None

    dest = os.path.join(str(tmpdir), "dest")
    run_pex3(
        "venv",
        "create",
        "-d",
        dest,
        "--pex-repository",
        colors_pex,
        "--scope",
        "deps",
        "--layout",
        "flat",
    ).assert_success()

    venv_pex_script = os.path.join(dest, "pex")
    assert not os.path.exists(venv_pex_script)
    assert_deps_only(interpreter=PythonInterpreter.get(), expected_prefix=dest, PYTHONPATH=dest)

    def install_srcs():
        # type: () -> None
        run_pex3(
            "venv",
            "create",
            "-d",
            dest,
            "--pex-repository",
            colors_pex,
            "--scope",
            "srcs",
            "--layout",
            "flat",
        ).assert_success()

    install_srcs()
    assert not os.path.exists(venv_pex_script)
    assert (
        colors.magenta("Red Dwarf")
        == subprocess.check_output(
            args=[sys.executable, "-m", "exe"], env=make_env(PYTHONPATH=dest)
        )
        .decode("utf-8")
        .strip()
    )

    shutil.rmtree(dest)
    install_srcs()
    assert_srcs_only(sys_path_entry=dest)


@pytest.fixture
def foreign_platform():
    # type: () -> str
    return "linux_x86_64-cp-310-cp310" if IS_MAC else "macosx_10.9_x86_64-cp-310-cp310"


def test_foreign_target(
    tmpdir,  # type: Any
    foreign_platform,  # type: str
):
    # type: (...) -> None

    dest = os.path.join(str(tmpdir), "dest")
    result = run_pex3(
        "venv",
        "create",
        "psutil==5.9.5",
        "-d",
        dest,
        "--platform",
        foreign_platform,
    )
    result.assert_failure()
    assert (
        "Cannot create a local venv for foreign platform {platform}.".format(
            platform=abbreviated_platforms.create(foreign_platform)
        )
        == result.error.strip()
    )

    run_pex3(
        "venv",
        "create",
        "--layout",
        "flat",
        "psutil==5.9.5",
        "-d",
        dest,
        "--platform",
        foreign_platform,
    ).assert_success()

    distributions = list(dist_metadata.find_distributions(search_path=[dest]))
    assert 1 == len(distributions)

    dist = distributions[0]
    assert ProjectName("psutil") == dist.metadata.project_name
    assert Version("5.9.5") == dist.metadata.version


def test_venv_update_target_mismatch(
    tmpdir,  # type: Any
    foreign_platform,  # type: str
):
    # type: (...) -> None

    dest = os.path.join(str(tmpdir), "dest")
    run_pex3("venv", "create", "-d", dest).assert_success()

    result = run_pex3(
        "venv", "create", "ansicolors==1.1.8", "-d", dest, "--platform", foreign_platform
    )
    result.assert_failure()
    assert (
        "Cannot update a local venv using a foreign platform. Given: {foreign_platform}.".format(
            foreign_platform=abbreviated_platforms.create(foreign_platform)
        )
        == result.error.strip()
    ), result.error

    python = ensure_python_interpreter(PY310 if sys.version_info[:2] != (3, 10) else PY39)
    result = run_pex3("venv", "create", "ansicolors==1.1.8", "-d", dest, "--python", python)
    result.assert_failure()
    assert (
        "Cannot update venv at {dest} created with {created_with} using {using}".format(
            dest=dest,
            created_with=PythonInterpreter.get().resolve_base_interpreter().binary,
            using=PythonInterpreter.from_binary(python).resolve_base_interpreter().binary,
        )
        in result.error.strip()
    ), result.error

    venv = Virtualenv(dest)
    assert [] == list(venv.iter_distributions())
    run_pex3("venv", "create", "ansicolors==1.1.8", "-d", dest).assert_success()
    assert [(ProjectName("ansicolors"), Version("1.1.8"))] == [
        (dist.metadata.project_name, dist.metadata.version)
        for dist in venv.iter_distributions(rescan=True)
    ]
