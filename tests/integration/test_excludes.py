# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import print_function

import glob
import json
import os.path
import re
import shutil
import subprocess
from os.path import commonprefix
from textwrap import dedent
from typing import Iterator

import pytest

from pex.common import safe_open
from pex.compatibility import PY2, commonpath
from pex.dist_metadata import Requirement
from pex.executor import Executor
from pex.pep_503 import ProjectName
from pex.pex import PEX
from pex.pex_info import PexInfo
from pex.pip.version import PipVersion, PipVersionValue
from pex.resolve.lockfile import json_codec
from pex.resolve.resolver_configuration import ResolverVersion
from pex.sorted_tuple import SortedTuple
from pex.typing import TYPE_CHECKING
from pex.venv.virtualenv import InstallationChoice, Virtualenv
from testing import PY_VER, data, make_env, run_pex_command
from testing.cli import run_pex3
from testing.lock import extract_lock_option_args, index_lock_artifacts
from testing.pytest.tmp import TempdirFactory

if TYPE_CHECKING:
    from typing import Any

    import attr  # vendor:skip
else:
    from pex.third_party import attr


REQUESTS_LOCK = data.path("locks", "requests.lock.json")


def assert_certifi_is_excluded(pex):
    # type: (str) -> None

    assert ["certifi"] == list(PexInfo.from_pex(pex).excluded)
    assert ProjectName("certifi") not in frozenset(
        dist.metadata.project_name for dist in PEX(pex).resolve()
    )


def requests_certifi_excluded_pex(tmpdir):
    # type: (Any) -> str

    pex_root = os.path.join(str(tmpdir), "pex_root")
    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[
            "--lock",
            REQUESTS_LOCK,
            "--exclude",
            "certifi",
            "--include-tools",
            "-o",
            pex,
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
        ]
    ).assert_success()
    assert_certifi_is_excluded(pex)
    return pex


REQUESTS_CMD = [
    "-c",
    "import os, requests, sys; print(os.path.realpath(sys.modules['certifi'].__file__))",
]
EXPECTED_IMPORT_ERROR_MSG = "ModuleNotFoundError: No module named 'certifi'"


@pytest.fixture(scope="module")
def certifi_venv(
    tmpdir_factory,  # type: TempdirFactory
    request,  # type: Any
):
    # type: (...) -> Virtualenv

    venv = Virtualenv.create(
        venv_dir=str(tmpdir_factory.mktemp("venv", request=request)),
        install_pip=InstallationChoice.YES,
    )
    pip = venv.bin_path("pip")

    # N.B.: The constraining lock requirement is the one expressed by requests: certifi>=2017.4.17
    # The actual locked version is 2023.7.22; so we stress this crease and use a different, but
    # allowed, version.
    subprocess.check_call(args=[pip, "install", "certifi==2017.4.17"])

    return venv


skip_unless_compatible_with_requests_lock = pytest.mark.skipif(
    PY_VER < (3, 7) or PY_VER >= (3, 13), reason="The lock used is for >=3.7,<3.13"
)


def assert_certifi_import_behavior(
    pex,  # type: str
    certifi_venv,  # type: Virtualenv
):
    requests_cmd = [pex] + REQUESTS_CMD

    # Although the venv has certifi available, a PEX is hermetic by default; so it shouldn't be
    # used.
    with pytest.raises(Executor.NonZeroExit) as exc:
        certifi_venv.interpreter.execute(args=requests_cmd)
    assert EXPECTED_IMPORT_ERROR_MSG in exc.value.stderr

    # Allowing the `sys.path` to be inherited should allow the certifi hole to be filled in.
    _, stdout, _ = certifi_venv.interpreter.execute(
        args=requests_cmd, env=make_env(PEX_INHERIT_PATH="fallback")
    )
    assert certifi_venv.site_packages_dir == commonprefix(
        [certifi_venv.site_packages_dir, stdout.strip()]
    )


def assert_requests_certifi_excluded_pex(
    pex,  # type: str
    certifi_venv,  # type: Virtualenv
):
    # type: (...) -> None

    requests_cmd = [pex] + REQUESTS_CMD

    # The exclude option is buyer beware. A PEX using this option will not work if the excluded
    # distributions carry modules that are, in fact, needed at run time.
    process = subprocess.Popen(args=requests_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, stderr = process.communicate()
    assert process.returncode != 0
    assert EXPECTED_IMPORT_ERROR_MSG in stderr.decode("utf-8"), stderr.decode("utf-8")

    assert_certifi_import_behavior(pex, certifi_venv)


@skip_unless_compatible_with_requests_lock
def test_exclude(
    tmpdir,  # type: Any
    certifi_venv,  # type: Virtualenv
):
    # type: (...) -> None

    pex = requests_certifi_excluded_pex(tmpdir)
    assert_requests_certifi_excluded_pex(pex, certifi_venv)


@skip_unless_compatible_with_requests_lock
def test_pre_resolved_dists_exclude(
    tmpdir,  # type: Any
    certifi_venv,  # type: Virtualenv
):
    # type: (...) -> None

    pex_repository = requests_certifi_excluded_pex(tmpdir)
    dists = os.path.join(str(tmpdir), "dists")
    subprocess.check_call(
        args=[pex_repository, "repository", "extract", "-f", dists], env=make_env(PEX_TOOLS=1)
    )

    pex_root = PexInfo.from_pex(pex_repository).pex_root
    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[
            "--pre-resolved-dists",
            dists,
            "--exclude",
            "certifi",
            "requests",
            "-o",
            pex,
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
        ]
    ).assert_success()
    assert_requests_certifi_excluded_pex(pex, certifi_venv)


@skip_unless_compatible_with_requests_lock
def test_requirements_pex_exclude(
    tmpdir,  # type: Any
    certifi_venv,  # type: Virtualenv
):
    # type: (...) -> None

    requirements_pex = requests_certifi_excluded_pex(tmpdir)
    pex_root = PexInfo.from_pex(requirements_pex).pex_root
    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=[
            "--requirements-pex",
            requirements_pex,
            "ansicolors==1.1.8",
            "-o",
            pex,
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
        ]
    ).assert_success()

    # Shouldn't need the certifi hole filled to import colors.
    output = subprocess.check_output(args=[pex, "-c", "import colors; print(colors.__file__)"])
    assert pex_root == commonprefix([pex_root, output.decode("utf-8").strip()])

    assert_certifi_import_behavior(pex, certifi_venv)


@skip_unless_compatible_with_requests_lock
def test_lock_exclude(
    tmpdir,  # type: Any
    certifi_venv,  # type: Virtualenv
):
    # type: (...) -> None

    lock = os.path.join(str(tmpdir), "lock.json")
    shutil.copy(REQUESTS_LOCK, lock)

    run_pex3(
        *(["lock", "sync", "--exclude", "certifi", "--lock", lock] + extract_lock_option_args(lock))
    ).assert_success(
        expected_error_re=r"^.*{expected_message}.*$".format(
            expected_message=re.escape(
                dedent(
                    """\
                    Updates for lock generated by universal:
                      Deleted certifi 2023.7.22
                    """
                )
            ),
        ),
        re_flags=re.DOTALL,
    )

    lockfile = json_codec.load(lock)
    assert SortedTuple([Requirement.parse("certifi")]) == lockfile.excluded
    assert ProjectName("certifi") not in index_lock_artifacts(lockfile)

    pex = os.path.join(str(tmpdir), "pex")
    pex_root = os.path.join(str(tmpdir), "pex_root")
    run_pex_command(
        args=[
            "--lock",
            lock,
            "-o",
            pex,
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
        ]
    ).assert_success()

    assert_certifi_is_excluded(pex)
    assert_requests_certifi_excluded_pex(pex, certifi_venv)


@attr.s(frozen=True)
class PipOptions(object):
    @classmethod
    def iter(cls):
        # type: () -> Iterator[PipOptions]
        for pip_version in PipVersion.values():
            if not pip_version.requires_python_applies():
                continue
            for resolver_version in ResolverVersion.values():
                if not ResolverVersion.applies(resolver_version, pip_version):
                    continue
                yield cls(pip_version=pip_version, resolver_version=resolver_version)

    pip_version = attr.ib()  # type: PipVersionValue
    resolver_version = attr.ib()  # type: ResolverVersion.Value

    def iter_args(self):
        # type: () -> Iterator[str]
        yield "--pip-version"
        yield str(self.pip_version)
        yield "--resolver-version"
        yield str(self.resolver_version)

    def __str__(self):
        # type: () -> str
        return "-".join(
            (
                str(self.pip_version),
                "legacy" if self.resolver_version is ResolverVersion.PIP_LEGACY else "resolvelib",
            )
        )


@pytest.mark.parametrize(
    "pip_options",
    [pytest.param(pip_options, id=str(pip_options)) for pip_options in PipOptions.iter()],
)
def test_exclude_deep(
    tmpdir,  # type: Any
    pip_options,  # type: PipOptions
):
    # type: (...) -> None

    # Bootstrap the Pip version being used if needed before we turn off PyPI.
    if pip_options.pip_version is not PipVersion.VENDORED:
        run_pex_command(
            args=list(pip_options.iter_args()) + ["ansicolors==1.1.8", "--", "-c", ""]
        ).assert_success()

    venv = Virtualenv.create(
        os.path.join(str(tmpdir), "venv"),
        install_pip=InstallationChoice.UPGRADED,
        install_setuptools=InstallationChoice.UPGRADED,
        install_wheel=InstallationChoice.UPGRADED,
    )
    pip = venv.bin_path("pip")

    find_links = os.path.join(str(tmpdir), "find_links")
    project_dir = os.path.join(str(tmpdir), "projects")

    foo_dir = os.path.join(project_dir, "foo")
    with safe_open(os.path.join(foo_dir, "foo.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from bar import BAR


                def foo():
                    return BAR * 42
                """
            )
        )
    with safe_open(os.path.join(foo_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup


                setup(
                    name="foo",
                    version="0.1.0",
                    install_requires=["bar"],
                    py_modules=["foo"],
                )
                """
            )
        )
    venv.interpreter.execute(
        args=["setup.py", "bdist_wheel", "--dist-dir", find_links], cwd=foo_dir
    )

    bar_dir = os.path.join(project_dir, "bar")
    with safe_open(os.path.join(bar_dir, "bar.py"), "w") as fp:
        print("BAR=1", file=fp)
    with safe_open(os.path.join(bar_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import os
                import sys

                from setuptools import setup


                if "BEHAVE" not in os.environ:
                    sys.exit("I'm an evil package.")


                setup(
                    name="bar",
                    version="0.1.0",
                    py_modules=["bar"],
                )
                """
            )
        )

    def assert_stderr_contains(
        expected,  # type: bytes
        *args,  # type: str
        **kwargs  # type: Any
    ):
        # type: (...) -> None
        process = subprocess.Popen(args=args, stderr=subprocess.PIPE, **kwargs)
        _, stderr = process.communicate()
        assert process.returncode != 0
        assert expected in stderr, stderr.decode()

    # The bar package should aggressively blow up in normal circumstances.
    assert_stderr_contains(
        b"I'm an evil package.",
        venv.interpreter.binary,
        "setup.py",
        "bdist_wheel",
        "--dist-dir",
        os.path.join(bar_dir, "dist"),
        cwd=bar_dir,
    )

    venv.interpreter.execute(
        args=["setup.py", "bdist_wheel", "--dist-dir", os.path.join(bar_dir, "dist")],
        cwd=bar_dir,
        env=make_env(BEHAVE=1),
    )
    wheels = glob.glob(os.path.join(bar_dir, "dist", "*.whl"))
    assert len(wheels) == 1
    bar_whl = wheels[0]

    venv.interpreter.execute(
        args=["setup.py", "sdist", "--dist-dir", find_links], cwd=bar_dir, env=make_env(BEHAVE=1)
    )

    # Building a Pex that requires bar should (transitively) aggressively blow up in normal
    # circumstances.
    run_pex_command(
        args=list(pip_options.iter_args()) + ["-f", find_links, "--no-pypi", "foo", "-vv"]
    ).assert_failure(expected_error_re=r".*I'm an evil package\..*", re_flags=re.DOTALL)

    # But an `--exclude bar` should solve this by never resolving bar at all.
    exe = os.path.join(str(tmpdir), "exe.py")
    with safe_open(exe, "w") as fp:
        fp.write(
            dedent(
                """\
                import json
                import os
                import sys

                import bar
                from foo import foo


                json.dump({"foo": foo(), "bar": os.path.realpath(bar.__file__)}, sys.stdout)
                """
            )
        )
    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(
        args=list(pip_options.iter_args())
        + ["-f", find_links, "--no-pypi", "foo", "--exclude", "bar", "-o", pex, "--exe", exe]
    ).assert_success()

    # The `--exclude bar` should hobble the PEX by default though, since bar is needed but missing.
    assert_stderr_contains(
        b"ImportError: No module named bar"
        if PY2
        else b"ModuleNotFoundError: No module named 'bar'",
        pex,
    )

    # But leaking in an externally installed bar should solve things.
    subprocess.check_call(args=[pip, "install", bar_whl])
    data = json.loads(
        subprocess.check_output(args=[pex], env=make_env(PEX_EXTRA_SYS_PATH=venv.site_packages_dir))
    )
    assert 42 == data.pop("foo")
    bar_module_path = data.pop("bar")
    assert venv.site_packages_dir == commonpath(
        (venv.site_packages_dir, bar_module_path)
    ), bar_module_path
    assert not data
