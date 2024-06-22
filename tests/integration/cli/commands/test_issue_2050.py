# Copyright 2023 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
import os
import re
import subprocess
import sys
import tempfile
from textwrap import dedent

import pytest

from pex.build_system import pep_517
from pex.dist_metadata import Requirement
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.locked_resolve import LockedRequirement
from pex.resolve.lockfile import json_codec
from pex.resolve.path_mappings import PathMapping, PathMappings
from pex.result import try_
from pex.sorted_tuple import SortedTuple
from pex.targets import LocalInterpreter
from pex.third_party.packaging.specifiers import SpecifierSet
from pex.typing import TYPE_CHECKING
from testing import IS_LINUX, PY310, PY_VER, ensure_python_interpreter, make_env, run_pex_command
from testing.cli import run_pex3

if TYPE_CHECKING:
    from typing import Any, Callable, Dict

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class Repo(object):
    find_links = attr.ib()  # type: str
    path_mapping = attr.ib()  # type: PathMapping
    path_mappings = attr.ib(init=False)  # type: PathMappings
    path_mapping_arg = attr.ib(init=False)  # type: str

    @path_mappings.default
    def _mappings(self):
        # type: () -> PathMappings
        return PathMappings((self.path_mapping,))

    @path_mapping_arg.default
    def _mapping_arg(self):
        # type: () -> str
        return "{name}|{path}".format(name=self.path_mapping.name, path=self.path_mapping.path)


@pytest.fixture
def build_sdist(tmpdir):
    # type: (Any) -> Callable[[str], Repo]

    def func(project_directory):
        find_links = os.path.join(str(tmpdir), "find-links")
        os.makedirs(find_links)
        try_(
            pep_517.build_sdist(
                project_directory=project_directory,
                dist_dir=find_links,
                target=LocalInterpreter.create(),
                resolver=ConfiguredResolver.default(),
            )
        )
        return Repo(find_links=find_links, path_mapping=PathMapping(path=find_links, name="FL"))

    return func


@pytest.mark.skipif(
    sys.version_info[0] < 3,
    reason="Encoding of setup.py files for Python 2 is tricky and not worth the trouble.",
)
def test_lock_uncompilable_sdist(
    tmpdir,  # type: Any
    build_sdist,  # type: Callable[[str], Repo]
):
    # type: (...) -> None

    project = os.path.join(str(tmpdir), "project")
    os.mkdir(project)
    with open(os.path.join(project, "bad.c"), "w") as fp:
        fp.write("This is not valid C code.")

    with open(os.path.join(project, "README"), "w") as fp:
        fp.write("This is a Python C-extension project that does not compile.")

    with open(os.path.join(project, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import json
                import os

                from setuptools import setup, Extension


                setup_kwargs = dict(
                    name="pex_tests_bad_c_extension",
                    version="0.1.0+test",
                    author="John Sirois",
                    author_email="js@example.com",
                    url="http://example.com/bad",
                    ext_modules=[Extension("bad", sources=["bad.c"])],
                )
                setup_kwargs.update(json.loads(os.environ.get("SETUP_KWARGS_JSON", "{}")))
                setup(**setup_kwargs)
                """
            )
        )

    repo = build_sdist(project)

    lock = os.path.join(str(tmpdir), "lock.json")
    run_pex3(
        "lock",
        "create",
        "-f",
        repo.find_links,
        "pex_tests_bad_c_extension",
        "--path-mapping",
        repo.path_mapping_arg,
        "--indent",
        "2",
        "-o",
        lock,
        env=make_env(
            SETUP_KWARGS_JSON=json.dumps(
                dict(install_requires=["ansicolors==1.1.8"], python_requires=">=3.5")
            )
        ),
    ).assert_success()

    lockfile = json_codec.load(lockfile_path=lock, path_mappings=repo.path_mappings)
    assert len(lockfile.locked_resolves) == 1
    locked_resolve = lockfile.locked_resolves[0]
    locked_requirements = {
        locked_requirement.pin.project_name: locked_requirement
        for locked_requirement in locked_resolve.locked_requirements
    }  # type: Dict[ProjectName, LockedRequirement]
    bad = locked_requirements.pop(ProjectName("pex_tests_bad_c_extension"))
    assert Version("0.1.0+test") == bad.pin.version
    assert SpecifierSet(">=3.5") == bad.requires_python
    assert SortedTuple([Requirement.parse("ansicolors==1.1.8")]) == bad.requires_dists
    assert locked_requirements.pop(ProjectName("ansicolors")) is not None
    assert not locked_requirements

    result = run_pex_command(args=["--lock", lock, "--path-mapping", repo.path_mapping_arg])
    result.assert_failure()
    assert "pex_tests_bad_c_extension-0.1.0+test.tar.gz" in result.error, result.error
    assert "ERROR: Failed to build one or more wheels" in result.error, result.error


@pytest.mark.skipif(
    not IS_LINUX or PY_VER < (3, 7),
    reason=(
        "The evdev project requires Linux and Python 3 and we use a setuptools in our in-tree "
        "build backend that requires Python 3.7+."
    ),
)
def test_pep_517_prepare_metadata_for_build_wheel_fallback(
    tmpdir,  # type: Any
    build_sdist,  # type: Callable[[str], Repo]
):
    # type: (...) -> None

    python = ensure_python_interpreter(PY310)

    evdev = os.path.join(str(tmpdir), "python-evdev")
    os.mkdir(evdev)
    subprocess.check_call(args=["git", "init"], cwd=evdev)
    evdev_1_6_1_sha = "2dd6ce6364bb67eedb209f6aa0bace0c18a3a40a"
    subprocess.check_call(
        args=[
            "git",
            "fetch",
            "--depth",
            "1",
            "https://github.com/gvalkov/python-evdev",
            evdev_1_6_1_sha,
        ],
        cwd=evdev,
    )
    subprocess.check_call(args=["git", "reset", "--hard", evdev_1_6_1_sha], cwd=evdev)
    with tempfile.NamedTemporaryFile() as fp:
        fp.write(
            dedent(
                """\
                diff --git a/builder/delegate_to_setuptools.py b/builder/delegate_to_setuptools.py
                new file mode 100644
                index 0000000..9a4d93d
                --- /dev/null
                +++ b/builder/delegate_to_setuptools.py
                @@ -0,0 +1,6 @@
                +from setuptools import build_meta
                +
                +
                +build_sdist = build_meta.build_sdist
                +build_wheel = build_meta.build_wheel
                +
                diff --git a/pyproject.toml b/pyproject.toml
                new file mode 100644
                index 0000000..7c52595
                --- /dev/null
                +++ b/pyproject.toml
                @@ -0,0 +1,5 @@
                +[build-system]
                +requires = ["setuptools==67.2.0", "wheel==0.38.4"]
                +backend-path = ["builder"]
                +build-backend = "delegate_to_setuptools"
                +
                diff --git a/setup.py b/setup.py
                index 73ba1f5..c19fa76 100755
                --- a/setup.py
                +++ b/setup.py
                @@ -41,7 +41,7 @@ ecodes_c = Extension('evdev._ecodes', sources=['evdev/ecodes.c'], extra_compile_
                 #-----------------------------------------------------------------------------
                 kw = {
                     'name':                 'evdev',
                -    'version':              '1.6.1',
                +    'version':              '1.6.1+test',

                     'description':          'Bindings to the Linux input handling subsystem',
                     'long_description':     (curdir / 'README.rst').read_text(),
                @@ -53,7 +53,7 @@ kw = {
                     'url':                  'https://github.com/gvalkov/python-evdev',
                     'classifiers':          classifiers,

                -    'packages':             ['evdev'],
                +    'packages':             ['evdev', 'builder'],
                     'ext_modules':          [input_c, uinput_c, ecodes_c],
                     'include_package_data': False,
                     'zip_safe':             True,
                """
            ).encode("utf-8")
        )
        fp.flush()
        subprocess.check_call(args=["git", "apply", fp.name], cwd=evdev)

    repo = build_sdist(evdev)

    lock = os.path.join(str(tmpdir), "lock.json")
    result = run_pex3(
        "lock",
        "create",
        "-vvv",
        "--python",
        python,
        "-f",
        repo.find_links,
        "evdev==1.6.1+test",
        "--path-mapping",
        repo.path_mapping_arg,
        "--indent",
        "2",
        "-o",
        lock,
    )
    result.assert_success()

    assert re.search(
        r"Failed to prepare metadata for .+{}, trying to build a wheel instead: ".format(
            re.escape("evdev-1.6.1+test.tar.gz")
        ),
        result.error,
    ), result.error
