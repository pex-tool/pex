# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from argparse import ArgumentParser
from contextlib import contextmanager
from tempfile import NamedTemporaryFile

import pytest

from pex.bin.pex import (
    build_pex,
    compute_indexes,
    configure_clp,
    configure_clp_pex_options,
    configure_clp_pex_resolution,
)
from pex.common import safe_copy, temporary_dir
from pex.compatibility import nested, to_bytes
from pex.interpreter import PythonInterpreter
from pex.testing import (
    PY27,
    built_wheel,
    ensure_python_interpreter,
    run_pex_command,
    run_simple_pex,
)
from pex.typing import TYPE_CHECKING
from pex.venv_bin_path import BinPath

if TYPE_CHECKING:
    from typing import Iterator, List, Optional, Text


@contextmanager
def option_parser():
    # type: () -> Iterator[ArgumentParser]
    yield ArgumentParser()


def test_clp_no_pypi_option():
    # type: () -> None
    with option_parser() as parser:
        configure_clp_pex_resolution(parser)
        options = parser.parse_args(args=[])
        assert len(compute_indexes(options)) == 1
        options = parser.parse_args(args=["--no-pypi"])
        assert len(compute_indexes(options)) == 0, "--no-pypi should remove the pypi index."


def test_clp_pypi_option_duplicate():
    # type: () -> None
    with option_parser() as parser:
        configure_clp_pex_resolution(parser)
        options = parser.parse_args(args=[])
        indexes = compute_indexes(options)
        assert len(indexes) == 1
        options2 = parser.parse_args(args=["--pypi"])
        indexes2 = compute_indexes(options2)
        assert len(indexes2) == 1
        assert indexes == indexes2


def test_clp_find_links_option():
    # type: () -> None
    with option_parser() as parser:
        configure_clp_pex_resolution(parser)
        options = parser.parse_args(args=["-f", "http://www.example.com"])
        assert len(compute_indexes(options)) == 1
        assert len(options.find_links) == 1


def test_clp_index_option():
    # type: () -> None
    with option_parser() as parser:
        configure_clp_pex_resolution(parser)
        options = parser.parse_args(args=[])
        indexes = compute_indexes(options)
        assert len(indexes) == 1
        options2 = parser.parse_args(args=["-i", "http://www.example.com"])
        indexes2 = compute_indexes(options2)
        assert len(indexes2) == 2
        assert indexes2[0] == indexes[0]
        assert indexes2[1] == "http://www.example.com"


def test_clp_index_option_render():
    # type: () -> None
    with option_parser() as parser:
        configure_clp_pex_resolution(parser)
        options = parser.parse_args(args=["--index", "http://www.example.com"])
        assert ["https://pypi.org/simple", "http://www.example.com"] == compute_indexes(options)


def test_clp_build_precedence():
    # type: () -> None
    with option_parser() as parser:
        configure_clp_pex_resolution(parser)

        options = parser.parse_args(args=["--no-build"])
        assert not options.build
        options = parser.parse_args(args=["--build"])
        assert options.build

        options = parser.parse_args(args=["--no-wheel"])
        assert not options.use_wheel

        options = parser.parse_args(args=["--wheel"])
        assert options.use_wheel


# Make sure that we're doing append and not replace
def test_clp_requirements_txt():
    # type: () -> None
    parser = configure_clp()
    options = parser.parse_args(args="-r requirements1.txt -r requirements2.txt".split())
    assert options.requirement_files == ["requirements1.txt", "requirements2.txt"]


def test_clp_constraints_txt():
    # type: () -> None
    parser = configure_clp()
    options = parser.parse_args(args="--constraint requirements1.txt".split())
    assert options.constraint_files == ["requirements1.txt"]


def test_clp_preamble_file():
    # type: () -> None
    with NamedTemporaryFile() as tmpfile:
        tmpfile.write(to_bytes('print "foo!"'))
        tmpfile.flush()

        parser = configure_clp()
        options = parser.parse_args(args=["--preamble-file", tmpfile.name])
        assert options.preamble_file == tmpfile.name

        pex_builder = build_pex(options.requirements, options)
        assert pex_builder._preamble == 'print "foo!"'


def test_clp_prereleases():
    # type: () -> None
    with option_parser() as parser:
        configure_clp_pex_resolution(parser)

        options = parser.parse_args(args=[])
        assert not options.allow_prereleases

        options = parser.parse_args(args=["--no-pre"])
        assert not options.allow_prereleases

        options = parser.parse_args(args=["--pre"])
        assert options.allow_prereleases


def test_clp_prereleases_resolver():
    # type: () -> None
    with nested(
        built_wheel(name="prerelease-dep", version="1.2.3b1"),
        built_wheel(name="transitive-dep", install_reqs=["prerelease-dep"]),
        built_wheel(name="dep", install_reqs=["prerelease-dep>=1.2", "transitive-dep"]),
        temporary_dir(),
        temporary_dir(),
    ) as (prerelease_dep, transitive_dep, dep, dist_dir, cache_dir):

        for dist in (prerelease_dep, transitive_dep, dep):
            safe_copy(dist, os.path.join(dist_dir, os.path.basename(dist)))

        parser = configure_clp()

        options = parser.parse_args(
            args=[
                "--no-index",
                "--find-links",
                dist_dir,
                "--cache-dir",
                cache_dir,  # Avoid dangling {pex_root}.
                "--no-pre",
                "dep",
            ]
        )
        assert not options.allow_prereleases

        with pytest.raises(SystemExit, message="Should have failed to resolve prerelease dep"):
            build_pex(options.requirements, options)

        # When we specify `--pre`, allow_prereleases is True
        options = parser.parse_args(
            args=[
                "--no-index",
                "--find-links",
                dist_dir,
                "--cache-dir",
                cache_dir,  # Avoid dangling {pex_root}.
                "--pre",
                "dep",
            ]
        )
        assert options.allow_prereleases

        # Without a corresponding fix in pex.py, this test failed for a dependency requirement of
        # dep==1.2.3b1 from one package and just dep (any version accepted) from another package.
        # The failure was an exit from build_pex() with the message:
        #
        # Could not satisfy all requirements for dep==1.2.3b1:
        #     dep==1.2.3b1, dep
        #
        # With a correct behavior the assert line is reached and pex_builder object created.
        pex_builder = build_pex(options.requirements, options)
        assert pex_builder is not None
        assert len(pex_builder.info.distributions) == 3, "Should have resolved deps"


def test_clp_pex_options():
    with option_parser() as parser:
        configure_clp_pex_options(parser)

        options = parser.parse_args(args=[])
        assert options.venv == False

        options = parser.parse_args(args=["--venv"])
        assert options.venv == BinPath.FALSE

        options = parser.parse_args(args=["--venv", "append"])
        assert options.venv == BinPath.APPEND

        options = parser.parse_args(args=["--venv", "prepend"])
        assert options.venv == BinPath.PREPEND


def test_build_pex():
    # type: () -> None
    with temporary_dir() as sandbox:
        pex_path = os.path.join(sandbox, "pex")
        results = run_pex_command(["ansicolors==1.1.8", "--output-file", pex_path])
        results.assert_success()
        stdout, returncode = run_simple_pex(
            pex=pex_path, args=["-c", 'import colors; print(" ".join(colors.COLORS))']
        )
        assert 0 == returncode
        assert b"black red green yellow blue magenta cyan white" == stdout.strip()


def test_run_pex():
    # type: () -> None

    def assert_run_pex(python=None, pex_args=None):
        # type: (Optional[str], Optional[List[str]]) -> List[str]
        pex_args = list(pex_args) if pex_args else []
        results = run_pex_command(
            python=python,
            args=pex_args
            + ["ansicolors==1.1.8", "--", "-c", 'import colors; print(" ".join(colors.COLORS))'],
            quiet=True,
        )
        results.assert_success()
        assert "black red green yellow blue magenta cyan white" == results.output.strip()
        return results.error.splitlines()

    incompatible_platforms_warning_msg = (
        "WARNING: attempting to run PEX with incompatible platforms!"
    )

    assert incompatible_platforms_warning_msg not in assert_run_pex()
    assert incompatible_platforms_warning_msg not in assert_run_pex(pex_args=["--platform=current"])
    assert incompatible_platforms_warning_msg not in assert_run_pex(
        pex_args=["--platform={}".format(PythonInterpreter.get().platform)]
    )

    py27 = ensure_python_interpreter(PY27)
    stderr_lines = assert_run_pex(python=py27, pex_args=["--platform=macosx-10.13-x86_64-cp-37-m"])
    assert incompatible_platforms_warning_msg in stderr_lines
