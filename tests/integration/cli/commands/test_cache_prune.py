# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from textwrap import dedent
from typing import Dict, Tuple, Union

import attr  # vendor:skip
import colors  # vendor:skip
import pytest

from pex.cache import access
from pex.cache.dirs import (
    BootstrapDir,
    CacheDir,
    InstalledWheelDir,
    InterpreterDir,
    PipPexDir,
    UnzipDir,
    UserCodeDir,
    VenvDirs,
)
from pex.cli.commands.cache.du import DiskUsage
from pex.common import environment_as, safe_open
from pex.pep_503 import ProjectName
from pex.pex_info import PexInfo
from pex.pip.version import PipVersion, PipVersionValue
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from testing import run_pex_command
from testing.cli import run_pex3
from testing.pytest.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Iterable, Iterator, Optional


@pytest.fixture(autouse=True)
def pex_root(tmpdir):
    # type: (Tempdir) -> Iterator[str]
    _pex_root = tmpdir.join("pex_root")
    with ENV.patch(PEX_ROOT=_pex_root) as env, environment_as(**env):
        yield _pex_root


@pytest.fixture
def pex(tmpdir):
    # type: (Tempdir) -> str
    return tmpdir.join("pex")


@pytest.fixture
def lock(tmpdir):
    # type: (Tempdir) -> str
    return tmpdir.join("lock.json")


def du(cache_dir):
    # type: (Union[CacheDir.Value, str]) -> DiskUsage
    return DiskUsage.collect(
        cache_dir.path() if isinstance(cache_dir, CacheDir.Value) else cache_dir
    )


def test_nothing_prunable(
    pex,  # type: str
    pex_root,  # type: str
):
    # type: (...) -> None

    run_pex_command(args=["-o", pex]).assert_success()
    pex_size = os.path.getsize(pex)

    subprocess.check_call(args=[pex, "-c", ""])
    pre_prune_du = du(pex_root)
    assert (
        pre_prune_du.size > pex_size
    ), "Expected the unzipped PEX to be larger than the zipped pex."

    # The default prune threshold should be high enough to never trigger in a test run (it's 2
    # weeks old at the time of writing).
    run_pex3("cache", "prune").assert_success()
    assert pre_prune_du == du(pex_root)


def test_installed_wheel_prune_build_time(pex):
    # type: (str) -> None

    run_pex_command(args=["ansicolors==1.1.8", "-o", pex]).assert_success()
    installed_wheels_size = du(CacheDir.INSTALLED_WHEELS).size
    assert installed_wheels_size > 0
    assert 0 == du(CacheDir.UNZIPPED_PEXES).size
    assert 0 == du(CacheDir.BOOTSTRAPS).size
    assert 0 == du(CacheDir.USER_CODE).size

    run_pex3("cache", "prune", "--older-than", "0 seconds").assert_success()
    assert 0 == du(CacheDir.UNZIPPED_PEXES).size
    assert 0 == du(CacheDir.INSTALLED_WHEELS).size
    assert 0 == du(CacheDir.BOOTSTRAPS).size
    assert 0 == du(CacheDir.USER_CODE).size


def test_installed_wheel_prune_run_time(
    pex,  # type: str
    pex_root,  # type: str
):
    # type: (...) -> None

    run_pex_command(args=["cowsay==5.0", "-c", "cowsay", "-o", pex]).assert_success()
    pex_size = os.path.getsize(pex)

    shutil.rmtree(pex_root)
    assert 0 == du(pex_root).size

    assert b"| Moo! |" in subprocess.check_output(args=[pex, "Moo!"])
    pre_prune_du = du(pex_root)
    assert du(CacheDir.INSTALLED_WHEELS).size > 0
    assert du(CacheDir.UNZIPPED_PEXES).size > 0
    assert du(CacheDir.BOOTSTRAPS).size > 0
    assert 0 == du(CacheDir.USER_CODE).size, "There is no user code in the PEX."
    assert (
        pre_prune_du.size > pex_size
    ), "Expected the unzipped PEX to be larger than the zipped pex."

    run_pex3("cache", "prune", "--older-than", "0 seconds").assert_success()
    assert 0 == du(CacheDir.UNZIPPED_PEXES).size
    assert 0 == du(CacheDir.INSTALLED_WHEELS).size
    assert 0 == du(CacheDir.BOOTSTRAPS).size
    assert 0 == du(CacheDir.USER_CODE).size


@attr.s(frozen=True)
class AnsicolorsPex(object):
    path = attr.ib()  # type: str


def write_app_py(path):
    # type: (str) -> None
    with safe_open(path, "w") as fp:
        fp.write(
            dedent(
                """\
                try:
                    from colors import green
                except ImportError:
                    def green(text):
                        return text


                if __name__ == "__main__":
                    print(green("Hello Cache!"))
                """
            )
        )


def create_ansicolors_pex(
    tmpdir,  # type: Tempdir
    *extra_args  # type: str
):
    # type: (...) -> AnsicolorsPex
    pex = tmpdir.join("ansicolors.pex")
    write_app_py(tmpdir.join("src", "app.py"))
    run_pex_command(
        args=["ansicolors==1.1.8", "-D", "src", "-m" "app", "-o", pex] + list(extra_args),
        cwd=tmpdir.path,
    ).assert_success()
    return AnsicolorsPex(pex)


@pytest.fixture
def ansicolors_zipapp_pex(tmpdir):
    # type: (Tempdir) -> AnsicolorsPex

    return create_ansicolors_pex(tmpdir)


def execute_ansicolors_pex(pex):
    # type: (AnsicolorsPex) -> AnsicolorsPex

    assert (
        colors.green("Hello Cache!")
        == subprocess.check_output(args=[pex.path]).decode("utf-8").strip()
    )
    return pex


def test_app_prune(
    pex_root,  # type: str
    ansicolors_zipapp_pex,  # type: AnsicolorsPex
    tmpdir,  # type: Tempdir
):
    # type: (...) -> None

    pex_size = os.path.getsize(ansicolors_zipapp_pex.path)
    installed_wheels_size = du(CacheDir.INSTALLED_WHEELS).size
    assert installed_wheels_size > 0
    assert 0 == du(CacheDir.UNZIPPED_PEXES).size
    assert 0 == du(CacheDir.BOOTSTRAPS).size
    assert 0 == du(CacheDir.USER_CODE).size

    execute_ansicolors_pex(ansicolors_zipapp_pex)
    pre_prune_du = du(pex_root)
    assert (
        du(CacheDir.INSTALLED_WHEELS).size > installed_wheels_size
    ), "Expected .pyc files to be compiled leading to more disk space usage"
    assert du(CacheDir.UNZIPPED_PEXES).size > 0
    assert du(CacheDir.BOOTSTRAPS).size > 0
    assert du(CacheDir.USER_CODE).size > 0
    assert (
        pre_prune_du.size > pex_size
    ), "Expected the unzipped PEX to be larger than the zipped pex."

    run_pex3("cache", "prune", "--older-than", "0 seconds").assert_success()
    assert 0 == du(CacheDir.UNZIPPED_PEXES).size
    assert 0 == du(CacheDir.INSTALLED_WHEELS).size
    assert 0 == du(CacheDir.BOOTSTRAPS).size
    assert 0 == du(CacheDir.USER_CODE).size


def set_last_access_ago(
    pex,  # type: str
    ago,  # type: timedelta
):
    # type: (...) -> None

    one_day_ago = time.mktime((datetime.now() - ago).timetuple())
    pex_info = PexInfo.from_pex(pex)
    if pex_info.venv:
        pex_dir = pex_info.runtime_venv_dir(pex)
        assert pex_dir is not None
        access.record_access(pex_dir, one_day_ago)
    else:
        assert pex_info.pex_hash is not None
        access.record_access(UnzipDir.create(pex_info.pex_hash), one_day_ago)


def set_last_access_one_day_ago(pex):
    # type: (str) -> None
    set_last_access_ago(pex, timedelta(days=1))


def set_last_access_one_second_ago(pex):
    # type: (str) -> None
    set_last_access_ago(pex, timedelta(seconds=1))


def assert_installed_wheels(
    names,  # type: Iterable[str]
    message=None,  # type: Optional[str]
):
    expected = set(map(ProjectName, names))
    actual = {iwd.project_name for iwd in InstalledWheelDir.iter_all()}
    if message:
        assert expected == actual, message
    else:
        assert expected == actual


def expected_pip_wheels():
    # type: () -> Iterable[str]
    if PipVersion.DEFAULT is PipVersion.VENDORED:
        return "pip", "setuptools"
    else:
        return "pip", "setuptools", "wheel"


def expected_pip_wheels_plus(*names):
    # type: (*str) -> Iterable[str]
    wheels = list(expected_pip_wheels())
    wheels.extend(names)
    return wheels


def test_zipapp_prune_shared_bootstrap(
    ansicolors_zipapp_pex,  # type: AnsicolorsPex
    tmpdir,  # type: Tempdir
):
    # type: (...) -> None

    execute_ansicolors_pex(ansicolors_zipapp_pex)

    empty_pex = tmpdir.join("empty.pex")
    run_pex_command(args=["-o", empty_pex]).assert_success()
    subprocess.check_call(args=[empty_pex, "-c", ""])

    bootstraps = list(BootstrapDir.iter_all())
    assert len(bootstraps) == 1, "Expected a shared bootstrap between pex and empty.pex."
    bootstrap = bootstraps[0]

    assert_installed_wheels(
        expected_pip_wheels_plus("ansicolors"),
        message=(
            "There should be an ansicolors wheel for the pex as well as pip, setuptools and wheel wheels "
            "for at least 1 Pip."
        ),
    )

    set_last_access_one_day_ago(ansicolors_zipapp_pex.path)
    run_pex3("cache", "prune", "--older-than", "1 hour").assert_success()
    assert [bootstrap] == list(BootstrapDir.iter_all())
    assert_installed_wheels(expected_pip_wheels())


def test_zipapp_prune_shared_code(
    ansicolors_zipapp_pex,  # type: AnsicolorsPex
    tmpdir,  # type: Tempdir
):
    # type: (...) -> None

    execute_ansicolors_pex(ansicolors_zipapp_pex)
    code_hash = PexInfo.from_pex(ansicolors_zipapp_pex.path).code_hash
    assert code_hash is not None

    all_user_code = list(UserCodeDir.iter_all())
    assert len(all_user_code) == 1
    assert code_hash == all_user_code[0].code_hash

    write_app_py(tmpdir.join("app.py"))
    no_colors_pex = tmpdir.join("no-colors.pex")
    run_pex_command(
        args=["-M" "app", "-m", "app", "-o", no_colors_pex], cwd=tmpdir.path
    ).assert_success()
    assert b"Hello Cache!\n" == subprocess.check_output(args=[no_colors_pex])
    assert all_user_code == list(
        UserCodeDir.iter_all()
    ), "Expected the shared code cache to be re-used since the code is the same for both PEXes."

    set_last_access_one_day_ago(ansicolors_zipapp_pex.path)
    run_pex3("cache", "prune", "--older-than", "1 hour").assert_success()
    assert all_user_code == list(
        UserCodeDir.iter_all()
    ), "Expected the shared code cache to be un-pruned since no_colors_pex still needs it."

    run_pex3("cache", "prune", "--older-than", "0 seconds").assert_success()
    assert len(list(UserCodeDir.iter_all())) == 0, (
        "Expected the shared code cache to be pruned since the last remaining user, no_colors_pex,"
        "is now pruned."
    )


@attr.s(frozen=True)
class CowsayPex(object):
    path = attr.ib()  # type: str


def execute_cowsay_pex(pex):
    # type: (CowsayPex) -> CowsayPex

    assert "| {msg} |".format(msg=colors.yellow("Moo?!")) in subprocess.check_output(
        args=[pex.path, "Moo?!"]
    ).decode("utf-8")
    return pex


@pytest.fixture
def cowsay_pex(tmpdir):
    # type: (Tempdir) -> CowsayPex

    cowsay_pex = tmpdir.join("cowsay.pex")
    with safe_open(tmpdir.join("exe.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import sys

                import colors
                import cowsay


                if __name__ == "__main__":
                    cowsay.tux(colors.yellow(" ".join(sys.argv[1:])))
                """
            )
        )
    run_pex_command(
        args=["ansicolors==1.1.8", "cowsay==5.0", "--exe", fp.name, "-o", cowsay_pex]
    ).assert_success()
    return execute_cowsay_pex(CowsayPex(cowsay_pex))


def test_zipapp_prune_shared_deps(
    ansicolors_zipapp_pex,  # type: AnsicolorsPex
    cowsay_pex,  # type: CowsayPex
    tmpdir,  # type: Tempdir
):
    # type: (...) -> None

    execute_ansicolors_pex(ansicolors_zipapp_pex)
    assert_installed_wheels(expected_pip_wheels_plus("ansicolors", "cowsay"))

    set_last_access_one_day_ago(cowsay_pex.path)
    run_pex3("cache", "prune", "--older-than", "1 hour").assert_success()
    assert_installed_wheels(expected_pip_wheels_plus("ansicolors"))

    # The PEXes should still work post-prune.
    execute_ansicolors_pex(ansicolors_zipapp_pex)
    execute_cowsay_pex(cowsay_pex)


def test_venv_prune_wheel_symlinks(
    tmpdir,  # type: Tempdir
    cowsay_pex,  # type: CowsayPex
):
    # type: (...) -> None

    # By default, a --venv PEX uses symlinks from site-packages to installed wheel chroot contents
    # which means a --venv PEX should hold a strong dependency on the installed wheels it symlinks.

    ansicolors_venv_pex = execute_ansicolors_pex(create_ansicolors_pex(tmpdir, "--venv"))
    assert_installed_wheels(expected_pip_wheels_plus("ansicolors", "cowsay"))

    set_last_access_one_day_ago(cowsay_pex.path)
    run_pex3("cache", "prune", "--older-than", "1 hour").assert_success()
    assert_installed_wheels(expected_pip_wheels_plus("ansicolors"))
    assert 0 == len(
        list(UnzipDir.iter_all())
    ), "Expected the cowsay unzip dir and the --venv intermediary unzip dir to be removed."

    # And the --venv PEX should still run after a prune, but without creating the intermediary
    # unzipped PEX.
    execute_ansicolors_pex(ansicolors_venv_pex)
    assert 0 == len(list(UnzipDir.iter_all()))

    # The cowsay PEX should also work post-prune.
    execute_cowsay_pex(cowsay_pex)


def test_venv_prune_wheel_copies(
    tmpdir,  # type: Tempdir
    cowsay_pex,  # type: CowsayPex
):
    # type: (...) -> None

    # A --venv --venv-site-packages-copies PEX uses hard links (or copies) of installed wheel chroot
    # contents and so has no dependencies on those.

    ansicolors_venv_pex = execute_ansicolors_pex(
        create_ansicolors_pex(tmpdir, "--venv", "--venv-site-packages-copies")
    )
    assert_installed_wheels(expected_pip_wheels_plus("ansicolors", "cowsay"))

    set_last_access_one_day_ago(cowsay_pex.path)
    run_pex3("cache", "prune", "--older-than", "1 hour").assert_success()
    assert_installed_wheels(expected_pip_wheels())
    assert 0 == len(
        list(UnzipDir.iter_all())
    ), "Expected the cowsay unzip dir and the --venv intermediary unzip dir to be removed."

    # And the --venv PEX should still run after a prune, but without creating the intermediary
    # unzipped PEX.
    execute_ansicolors_pex(ansicolors_venv_pex)
    assert 0 == len(list(UnzipDir.iter_all()))

    # The cowsay PEX should also work post-prune.
    execute_cowsay_pex(cowsay_pex)


def test_venv_prune_interpreter(tmpdir):
    # type: (Tempdir) -> None

    ansicolors_venv_pex = create_ansicolors_pex(tmpdir, "--venv")
    pre_execute_interpreters = set(InterpreterDir.iter_all())
    assert len(pre_execute_interpreters) > 0
    ansicolors_pex_info = PexInfo.from_pex(ansicolors_venv_pex.path)

    execute_ansicolors_pex(ansicolors_venv_pex)
    post_execute_interpreters = set(InterpreterDir.iter_all())
    venv_interpreters = post_execute_interpreters - pre_execute_interpreters
    assert len(venv_interpreters) == 1
    venv_interpreter = venv_interpreters.pop()

    assert (
        ansicolors_pex_info.runtime_venv_dir(ansicolors_venv_pex.path)
        == venv_interpreter.interpreter.prefix
    )

    run_pex3("cache", "prune", "--older-than", "0 seconds").assert_success()
    assert venv_interpreter not in set(
        InterpreterDir.iter_all()
    ), "Expected the venv interpreter to be pruned when the venv was pruned."


@pytest.fixture
def applicable_non_vendored_pips():
    # type: () -> Tuple[PipVersionValue, ...]
    return tuple(
        pv
        for pv in PipVersion.values()
        if pv is not PipVersion.VENDORED and pv.requires_python_applies()
    )


@pytest.fixture
def pip1(applicable_non_vendored_pips):
    # type: (Tuple[PipVersionValue, ...]) -> PipVersionValue
    if not applicable_non_vendored_pips:
        pytest.skip(
            "This test requires 1 non-vendored Pip `--version`s be applicable, but none are"
        )
    return applicable_non_vendored_pips[0]


@pytest.fixture
def pip2(applicable_non_vendored_pips):
    # type: (Tuple[PipVersionValue, ...]) -> PipVersionValue
    if len(applicable_non_vendored_pips) < 2:
        pytest.skip(
            "This test requires 2 non-vendored Pip `--version`s be applicable, but only the "
            "following are: {pips}".format(pips=" ".join(map(str, applicable_non_vendored_pips)))
        )
    return applicable_non_vendored_pips[1]


@pytest.fixture
def pip3(applicable_non_vendored_pips):
    # type: (Tuple[PipVersionValue, ...]) -> PipVersionValue
    if len(applicable_non_vendored_pips) < 3:
        pytest.skip(
            "This test requires 3 non-vendored Pip `--version`s be applicable, but only the "
            "following are: {pips}".format(pips=" ".join(map(str, applicable_non_vendored_pips)))
        )
    return applicable_non_vendored_pips[2]


def test_pip_prune(
    tmpdir,  # type: Tempdir
    pip1,  # type: PipVersionValue
    pip2,  # type: PipVersionValue
    pip3,  # type: PipVersionValue
):
    # type: (...) -> None

    create_ansicolors_pex(tmpdir, "--pip-version", str(pip1))
    create_ansicolors_pex(tmpdir, "--pip-version", str(pip2))
    create_ansicolors_pex(tmpdir, "--pip-version", str(pip3), "--no-wheel")

    pips_by_version = {pip_dir.version: pip_dir for pip_dir in PipPexDir.iter_all()}
    assert {pip1, pip2, pip3}.issubset(pips_by_version)

    pip_venvs_by_version = {}  # type: Dict[PipVersionValue, VenvDirs]
    venv_dirs_by_pex_hash = {venv_dirs.pex_hash: venv_dirs for venv_dirs in VenvDirs.iter_all()}
    for pip_dir in pips_by_version.values():
        pex_info = PexInfo.from_pex(pip_dir.path)
        assert pex_info.pex_hash is not None
        pip_venvs_by_version[pip_dir.version] = venv_dirs_by_pex_hash.pop(pex_info.pex_hash)
    assert not venv_dirs_by_pex_hash, "Expected all venv dirs to be Pip venv dirs."

    for pip_version, venv_dirs in pip_venvs_by_version.items():
        if pip_version is pip1:
            set_last_access_one_day_ago(venv_dirs.path)
        else:
            set_last_access_one_second_ago(venv_dirs.path)
    pex_dir_to_last_access = dict(access.iter_all_cached_pex_dirs())

    pip2_du = du(pips_by_version[pip2].base_dir)
    pip3_du = du(pips_by_version[pip3].base_dir)
    run_pex3("cache", "prune", "--older-than", "1 hour").assert_success()
    assert not os.path.exists(pips_by_version[pip1].base_dir), "Expected a full prune of pip1"
    assert pip2_du.size == du(pips_by_version[pip2].base_dir).size
    post_prune_pip3_du = du(pips_by_version[pip3].base_dir)
    assert (
        post_prune_pip3_du.size < pip3_du.size
    ), "Expected pip3 to have a built ansicolors wheel in its cache pruned."
    assert (
        post_prune_pip3_du.files == pip3_du.files - 1
    ), "Expected pip3 to have a built ansicolors wheel in its cache pruned."

    pip1_venv_dirs = pip_venvs_by_version.pop(pip1)
    pex_dir_to_last_access.pop(pip1_venv_dirs)
    assert pex_dir_to_last_access == dict(access.iter_all_cached_pex_dirs()), (
        "Expected other Pips to have their last access reset after calling `pip cache ...` to "
        "prune Pip wheels."
    )
    assert set(pip_venvs_by_version) == {
        pip_dir.version for pip_dir in PipPexDir.iter_all()
    }, "Expected pip1 to be pruned along with the pip1 venv."
    assert set(pip_venvs_by_version.values()) == set(
        VenvDirs.iter_all()
    ), "Expected the pip1 venv to be pruned along with pip1 itself."
