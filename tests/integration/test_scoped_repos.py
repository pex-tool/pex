# Copyright 2025 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import shutil
import subprocess
import sys
from textwrap import dedent

import pytest

from pex import resolver
from pex.common import safe_mkdir, safe_open
from pex.dist_metadata import DistMetadata
from pex.enum import Enum
from pex.http.server import Server
from pex.pip.version import PipVersion
from pex.typing import TYPE_CHECKING
from testing import (
    IS_MAC,
    PY310,
    PY311,
    WheelBuilder,
    ensure_python_interpreter,
    make_env,
    run_pex_command,
)
from testing.pytest_utils import IS_CI
from testing.pytest_utils.tmp import Tempdir

if TYPE_CHECKING:
    from typing import Callable, Dict, Iterable, Iterator, List, Optional, Text, Union

    import attr  # vendor:skip
    import colors  # vendor:skip
else:
    from pex.third_party import attr, colors


def add_build_boilerplate(project_dir):
    # type: (str) -> None
    with safe_open(os.path.join(project_dir, "pyproject.toml"), "w") as fp:
        fp.write(
            dedent(
                """\
                [build-system]
                requires = ["setuptools"]
                build-backend = "setuptools.build_meta"
                """
            )
        )
    with safe_open(os.path.join(project_dir, "setup.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                from setuptools import setup


                setup()
                """
            )
        )


def build_wheel_for_project(project_dir):
    # type: (str) -> str
    add_build_boilerplate(project_dir)
    return WheelBuilder(source_dir=project_dir).bdist()


def alternate_ansicolors(
    project_dir,  # type: str
    sigil,  # type: str
):
    # type: (...) -> str

    with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = ansicolors
                version = 1.1.8

                [options]
                py_modules = colors

                [bdist_wheel]
                python_tag=py2.py3
                """
            )
        )
    with safe_open(os.path.join(project_dir, "colors.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                def green(text):
                    return "{{sigil}} {{text}} {{sigil}}".format(text=text, sigil="{sigil}")
                """.format(
                    sigil=sigil
                )
            )
        )
    return build_wheel_for_project(project_dir)


def alternate_cowsay(
    project_dir,  # type: str
    sigil,  # type: str
):
    # type: (...) -> str

    with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = cowsay
                version = 5.0

                [options]
                py_modules = cowsay

                [bdist_wheel]
                python_tag=py2.py3
                """
            )
        )
    with safe_open(os.path.join(project_dir, "cowsay.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                def tux(text):
                    print("{{sigil}} {{text}} {{sigil}}".format(text=text, sigil="{sigil}"))
                """.format(
                    sigil=sigil
                )
            )
        )
    return build_wheel_for_project(project_dir)


@pytest.fixture
def find_links(tmpdir):
    # type: (Tempdir) -> str

    alternate_ansicolors_wheel = alternate_ansicolors(tmpdir.join("ansicolors-asterisks"), "***")
    alternate_cowsay_wheel = alternate_cowsay(tmpdir.join("cowsay-asterisks"), "fl")

    find_links_dir = safe_mkdir(tmpdir.join("find-links"))
    for wheel in alternate_ansicolors_wheel, alternate_cowsay_wheel:
        shutil.move(wheel, os.path.join(find_links_dir, os.path.basename(wheel)))
    return find_links_dir


@pytest.fixture
def index(tmpdir):
    # type: (Tempdir) -> Iterator[str]

    alternate_ansicolors_wheel = alternate_ansicolors(tmpdir.join("ansicolors-asterisks"), "---")
    alternate_cowsay_wheel = alternate_cowsay(tmpdir.join("cowsay-asterisks"), "ix")

    index_dir = tmpdir.join("index")
    for wheel in alternate_ansicolors_wheel, alternate_cowsay_wheel:
        project_dir = safe_mkdir(
            os.path.join(index_dir, DistMetadata.load(wheel).project_name.normalized)
        )
        shutil.move(wheel, os.path.join(project_dir, os.path.basename(wheel)))

    server = Server(name="index", cache_dir=tmpdir.join("index-cache"))
    server_info = server.launch(index_dir).server_info
    try:
        yield server_info.url
    finally:
        server.shutdown()


@pytest.fixture
def app(tmpdir):
    # type: (Tempdir) -> str

    project_dir = tmpdir.join("app")
    with safe_open(os.path.join(project_dir, "setup.cfg"), "w") as fp:
        fp.write(
            dedent(
                """\
                [metadata]
                name = module
                version = 0.1.0

                [options]
                py_modules = module
                install_requires =
                    ansicolors
                    cowsay<6

                [options.entry_points]
                console_scripts =
                    script = module:tux_green

                [bdist_wheel]
                python_tag=py2.py3
                """
            )
        )
    with safe_open(os.path.join(project_dir, "module.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import sys

                import colors
                import cowsay


                def tux_green():
                    cowsay.tux(colors.green(" ".join(sys.argv[1:])))
                """
            )
        )
    add_build_boilerplate(project_dir)
    return project_dir


def assert_pypi_green(
    expected_message,  # type: str
    output,  # type: str
):
    # type: (...) -> None
    assert colors.green(expected_message) in output, output


class Source(Enum["Source.Value"]):
    class Value(Enum.Value):
        pass

    PYPI = Value("PyPI")
    INDEX = Value("index")
    FIND_LINKS = Value("find_links")


Source.seal()


EXPECTED_COWSAY_FNS = {
    Source.PYPI: lambda msg: "| {msg} |".format(msg=msg),
    Source.INDEX: lambda msg: "ix {msg} ix".format(msg=msg),
    Source.FIND_LINKS: lambda msg: "fl {msg} fl".format(msg=msg),
}

EXPECTED_ANSICOLORS_FNS = {
    Source.PYPI: colors.green,
    Source.INDEX: lambda msg: "--- {msg} ---".format(msg=msg),
    Source.FIND_LINKS: lambda msg: "*** {msg} ***".format(msg=msg),
}


def assert_app_output(
    expected_message,  # type: str
    expected_ansicolors_source,  # type: Source.Value
    expected_cowsay_source,  # type: Source.Value
    output,  # type: Text
):
    # type: (...) -> None
    wrap_cowsay = EXPECTED_COWSAY_FNS[expected_cowsay_source]
    wrap_ansicolors = EXPECTED_ANSICOLORS_FNS[expected_ansicolors_source]
    assert wrap_cowsay(wrap_ansicolors(expected_message)) in output, output


skip_index_for_mac_ci = pytest.mark.xfail(
    IS_CI and IS_MAC,
    reason=(
        "The index servers fail to start, at least on the macos-15 CI runners, and since this "
        "is not a multi-platform test (a universal lock can be created from any platform host), "
        "just checking on Linux is not ideal but good enough."
    ),
)


@attr.s(frozen=True)
class Expectations(object):
    cowsay_source = attr.ib(default=Source.PYPI)  # type: Source.Value
    ansicolors_source = attr.ib(default=Source.PYPI)  # type: Source.Value
    _extra_args = attr.ib(default=())  # type: Iterable[Union[str, Callable[[Tempdir], str]]]
    id_suffix = attr.ib(default="")  # type: str

    def extra_args(
        self,
        index=None,  # type: Optional[str]
        find_links=None,  # type: Optional[str]
        tmpdir=None,  # type: Optional[Tempdir]
    ):
        # type: (...) -> List[str]

        format_args = {}  # type: Dict[str, str]
        if index:
            format_args["index"] = index
        if find_links:
            format_args["find_links"] = find_links

        extra_args = []  # type: List[str]
        for arg in self._extra_args:
            if isinstance(arg, str):
                extra_args.append(arg.format(**format_args))
            else:
                assert tmpdir is not None, "tmpdir must be passed to extra_args(...)"
                extra_args.append(arg(tmpdir))
        return extra_args

    def __str__(self):
        # type: () -> str
        return "cowsay:{cowsay_source}-ansicolors:{ansicolors_source}{suffix}".format(
            cowsay_source=self.cowsay_source,
            ansicolors_source=self.ansicolors_source,
            suffix="-{suffix}".format(suffix=self.id_suffix) if self.id_suffix else "",
        )


def ansicolors_and_cowsay_index_requirements_txt(tmpdir):
    # type: (Tempdir) -> str
    with open(tmpdir.join("requirements.txt"), "w") as fp:
        fp.write(
            dedent(
                """\
                --extra-index-url ${INDEX}
                
                ansicolors
                cowsay
                """
            )
        )
    return fp.name


def ansicolors_and_cowsay_find_links_requirements_txt(tmpdir):
    # type: (Tempdir) -> str
    with open(tmpdir.join("requirements.txt"), "w") as fp:
        fp.write(
            dedent(
                """\
                --find-links ${FIND_LINKS}
                
                ansicolors
                cowsay
                """
            )
        )
    return fp.name


def ansicolors_find_links_requirements_txt(tmpdir):
    # type: (Tempdir) -> str
    with open(tmpdir.join("requirements.txt"), "w") as fp:
        fp.write(
            dedent(
                """\
                -f ${FIND_LINKS}
                
                ansicolors
                """
            )
        )
    return fp.name


@skip_index_for_mac_ci
@pytest.mark.parametrize(
    "expectations",
    [
        pytest.param(expectation, id=str(expectation))
        for expectation in (
            Expectations(),
            Expectations(
                cowsay_source=Source.INDEX,
                extra_args=["--index", "index={index}", "--source", "index=cowsay"],
            ),
            Expectations(
                ansicolors_source=Source.INDEX,
                extra_args=["--index", "index={index}", "--source", "index=ansicolors"],
            ),
            Expectations(
                cowsay_source=Source.INDEX,
                ansicolors_source=Source.INDEX,
                extra_args=["--index", "index={index}", "--source", "index=^(cowsay|ansicolors)$"],
            ),
            Expectations(
                cowsay_source=Source.INDEX,
                ansicolors_source=Source.INDEX,
                extra_args=[
                    "--derive-sources-from-requirements-files",
                    "-r",
                    ansicolors_and_cowsay_index_requirements_txt,
                ],
                id_suffix="requirements.txt",
            ),
            Expectations(
                cowsay_source=Source.FIND_LINKS,
                extra_args=["--find-links", "fl={find_links}", "--source", "fl=cowsay"],
            ),
            Expectations(
                ansicolors_source=Source.FIND_LINKS,
                extra_args=["--find-links", "fl={find_links}", "--source", "fl=ansicolors"],
            ),
            Expectations(
                ansicolors_source=Source.FIND_LINKS,
                extra_args=[
                    "--derive-sources-from-requirements-files",
                    "-r",
                    ansicolors_find_links_requirements_txt,
                ],
                id_suffix="requirements.txt",
            ),
            Expectations(
                cowsay_source=Source.FIND_LINKS,
                ansicolors_source=Source.FIND_LINKS,
                extra_args=["--find-links", "fl={find_links}", "--source", "fl=.*co[lw].*"],
            ),
            Expectations(
                cowsay_source=Source.FIND_LINKS,
                ansicolors_source=Source.FIND_LINKS,
                extra_args=[
                    "--derive-sources-from-requirements-files",
                    "-r",
                    ansicolors_and_cowsay_find_links_requirements_txt,
                ],
                id_suffix="requirements.txt",
            ),
            Expectations(
                cowsay_source=Source.FIND_LINKS,
                ansicolors_source=Source.INDEX,
                extra_args=[
                    "--find-links",
                    "fl={find_links}",
                    "--index",
                    "index={index}",
                    "--source",
                    "fl=cowsay",
                    "--source",
                    "index=ansicolors",
                ],
            ),
            Expectations(
                cowsay_source=Source.INDEX,
                ansicolors_source=Source.FIND_LINKS,
                extra_args=[
                    "--find-links",
                    "fl={find_links}",
                    "--index",
                    "index={index}",
                    "--source",
                    "index=cowsay",
                    "--source",
                    "fl=ansicolors",
                ],
            ),
        )
    ],
)
def test_scoped_project(
    tmpdir,  # type: Tempdir
    index,  # type: str
    find_links,  # type: str
    app,  # type: str
    expectations,  # type: Expectations
):
    # type: (...) -> None

    pex = tmpdir.join("pex")
    pex_root = tmpdir.join("pex-root")
    run_pex_command(
        args=(
            [
                "--pex-root",
                pex_root,
                "--runtime-pex-root",
                pex_root,
                app,
                "-c",
                "script",
                "-o",
                pex,
                "--pip-log",
                tmpdir.join("pip.log"),
            ]
            + expectations.extra_args(index=index, find_links=find_links, tmpdir=tmpdir)
        ),
        env=make_env(INDEX=index, FIND_LINKS=find_links),
    ).assert_success()

    assert_app_output(
        expected_message="Moo?",
        expected_cowsay_source=expectations.cowsay_source,
        expected_ansicolors_source=expectations.ansicolors_source,
        output=subprocess.check_output(args=[pex, "Moo?"]).decode("utf-8"),
    )


OTHER_INTERPRETER = (
    ensure_python_interpreter(PY311)
    if sys.version_info[:2] != (3, 11)
    else ensure_python_interpreter(PY310)
)

SCOPED_MARKER_ARGS = [
    "--find-links",
    "fl={find_links}",
    "--source",
    "fl=python_version == '{major}.{minor}'".format(
        major=sys.version_info[0], minor=sys.version_info[1]
    ),
]


@pytest.mark.parametrize(
    ["expectations", "python"],
    [
        pytest.param(
            Expectations(
                cowsay_source=Source.FIND_LINKS,
                ansicolors_source=Source.FIND_LINKS,
                extra_args=SCOPED_MARKER_ARGS,
            ),
            sys.executable,
            id="marker-match",
        ),
        pytest.param(
            Expectations(extra_args=SCOPED_MARKER_ARGS), OTHER_INTERPRETER, id="marker-miss"
        ),
    ],
)
def test_scoped_marker(
    tmpdir,  # type: Tempdir
    find_links,  # type: str
    app,  # type: str
    expectations,  # type: Expectations
    python,  # type: str
):
    # type: (...) -> None

    if expectations.cowsay_source is Source.FIND_LINKS:
        # N.B.: We need to make sure we have the Pip bootstrap we need when in pure find-links mode.
        if PipVersion.DEFAULT is PipVersion.VENDORED:
            requirements = [
                str(PipVersion.VENDORED.setuptools_requirement),
                str(PipVersion.VENDORED.wheel_requirement),
            ]
        else:
            requirements = list(map(str, PipVersion.DEFAULT.requirements))
        downloaded = resolver.download(requirements=requirements)
        for dist in downloaded.local_distributions:
            shutil.copy(dist.path, find_links)

    pex = tmpdir.join("pex")
    pex_root = tmpdir.join("pex-root")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            app,
            "-c",
            "script",
            "-o",
            pex,
            "--pip-log",
            tmpdir.join("pip.log"),
        ]
        + expectations.extra_args(find_links=find_links),
        python=python,
    ).assert_success()

    assert_app_output(
        expected_message="Moo!",
        expected_cowsay_source=expectations.cowsay_source,
        expected_ansicolors_source=expectations.ansicolors_source,
        output=subprocess.check_output(args=[python, pex, "Moo!"]).decode("utf-8"),
    )


SCOPED_PROJECT_NAME_AND_MARKER_ARGS = [
    "--find-links",
    "fl={find_links}",
    "--source",
    "fl=cowsay; python_version == '{major}.{minor}'".format(
        major=sys.version_info[0], minor=sys.version_info[1]
    ),
]

SCOPED_PROJECT_RE_AND_MARKER_ARGS = [
    "--find-links",
    "fl={find_links}",
    "--source",
    "fl=^cow.*; python_version == '{major}.{minor}'".format(
        major=sys.version_info[0], minor=sys.version_info[1]
    ),
]


@pytest.mark.parametrize(
    ["expectations", "python"],
    [
        pytest.param(
            Expectations(
                cowsay_source=Source.FIND_LINKS, extra_args=SCOPED_PROJECT_NAME_AND_MARKER_ARGS
            ),
            sys.executable,
            id="name-marker-match",
        ),
        pytest.param(
            Expectations(extra_args=SCOPED_PROJECT_NAME_AND_MARKER_ARGS),
            OTHER_INTERPRETER,
            id="name-marker-miss",
        ),
        pytest.param(
            Expectations(
                cowsay_source=Source.FIND_LINKS, extra_args=SCOPED_PROJECT_RE_AND_MARKER_ARGS
            ),
            sys.executable,
            id="re-marker-match",
        ),
        pytest.param(
            Expectations(extra_args=SCOPED_PROJECT_RE_AND_MARKER_ARGS),
            OTHER_INTERPRETER,
            id="re-marker-miss",
        ),
    ],
)
def test_scoped_project_and_marker(
    tmpdir,  # type: Tempdir
    find_links,  # type: str
    app,  # type: str
    expectations,  # type: Expectations
    python,  # type: str
):
    # type: (...) -> None

    pex = tmpdir.join("pex")
    pex_root = tmpdir.join("pex-root")
    run_pex_command(
        args=[
            "--pex-root",
            pex_root,
            "--runtime-pex-root",
            pex_root,
            app,
            "-c",
            "script",
            "-o",
            pex,
            "--pip-log",
            tmpdir.join("pip.log"),
        ]
        + expectations.extra_args(find_links=find_links),
        python=python,
    ).assert_success()

    assert_app_output(
        expected_message="Moo?!",
        expected_cowsay_source=expectations.cowsay_source,
        expected_ansicolors_source=expectations.ansicolors_source,
        output=subprocess.check_output(args=[python, pex, "Moo?!"]).decode("utf-8"),
    )
