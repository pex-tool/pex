# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools
import logging
import os
import re
import shutil
import subprocess
from argparse import ArgumentParser, _SubParsersAction
from contextlib import contextmanager
from textwrap import dedent
from threading import Thread

from pex import dist_metadata
from pex.commands.command import JsonMixin, OutputMixin
from pex.common import (
    DETERMINISTIC_DATETIME_TIMESTAMP,
    pluralize,
    safe_mkdir,
    safe_mkdtemp,
    safe_open,
)
from pex.compatibility import Queue
from pex.environment import PEXEnvironment
from pex.interpreter import PythonIdentity, PythonInterpreter, spawn_python_job
from pex.jobs import Retain, SpawnedJob, execute_parallel
from pex.pex import PEX
from pex.result import Error, Ok, Result
from pex.third_party.pkg_resources import Distribution
from pex.tools.command import PEXCommand
from pex.typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import IO, Callable, Iterable, Iterator, Text, Tuple

    import attr  # vendor:skip

    RepositoryFunc = Callable[["Repository", PEX], Result]
else:
    from pex.third_party import attr


logger = logging.getLogger(__name__)


@attr.s(frozen=True)
class FindLinksRepo(object):
    @classmethod
    def serve(
        cls,
        interpreter,  # type: PythonInterpreter
        port,  # type: int
        directory,  # type: str
    ):
        # type: (...) -> FindLinksRepo
        http_server_module = "SimpleHTTPServer" if interpreter.version[0] == 2 else "http.server"

        cmd, http_server_process = interpreter.open_process(
            # N.B.: Running Python in unbuffered mode here is critical to being able to read stdout.
            args=["-u", "-m", http_server_module, str(port)],
            cwd=directory,
            stdout=subprocess.PIPE,
        )

        real_port = Queue()  # type: Queue[int]

        def read_data():
            try:
                data = http_server_process.stdout.readline()
                match = re.match(br"^Serving HTTP on [^\s]+ port (?P<port>\d+)[^\d]", data)
                real_port.put(int(match.group("port")))
            finally:
                real_port.task_done()

        reader = Thread(target=read_data)
        reader.daemon = True
        reader.start()
        real_port.join()
        reader.join()

        return cls(cmd=cmd, port=real_port.get(), server_process=http_server_process)

    cmd = attr.ib()  # type: Iterable[str]
    port = attr.ib()  # type: int
    _server_process = attr.ib()  # type: subprocess.Popen

    @property
    def pid(self):
        # type: () -> int
        return self._server_process.pid

    def join(self):
        # type: () -> int
        return self._server_process.wait()

    def kill(self):
        # type: () -> None
        self._server_process.kill()


class Repository(JsonMixin, OutputMixin, PEXCommand):
    """Interact with the Python distribution repository contained in a PEX file."""

    @classmethod
    def _add_info_arguments(cls, subparsers):
        # type: (_SubParsersAction) -> ArgumentParser
        info_parser = cast(
            ArgumentParser,
            subparsers.add_parser(
                name="info", help="Print information about the distributions in a PEX file."
            ),
        )
        info_parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="Print the distributions requirements in addition to its name version and path.",
        )
        cls.add_json_options(info_parser, entity="verbose output")
        cls.register_global_arguments(info_parser, include_verbosity=False)
        return info_parser

    @classmethod
    def _add_extract_arguments(cls, subparsers):
        # type: (_SubParsersAction) -> ArgumentParser
        extract_parser = cast(
            ArgumentParser,
            subparsers.add_parser(
                name="extract", help="Extract all distributions from a PEX file."
            ),
        )
        extract_parser.add_argument(
            "-f",
            "--dest-dir",
            "--find-links",
            "--repo",
            metavar="PATH",
            help="The path to extract distribution as wheels to.",
        )
        extract_parser.add_argument(
            "-D",
            "--sources",
            action="store_true",
            help="Also extract a wheel for the PEX file sources.",
        )
        extract_parser.add_argument(
            "--use-system-time",
            dest="use_system_time",
            default=False,
            action="store_true",
            help=(
                "Use the current system time to generate timestamps for the extracted "
                "distributions. Otherwise, Pex will use midnight on January 1, 1980. By using "
                "system time, the extracted distributions will not be reproducible, meaning that "
                "if you were to re-run extraction against the same PEX file then the newly "
                "extracted distributions would not be byte-for-byte identical distributions "
                "extracted in prior runs."
            ),
        )
        extract_parser.add_argument(
            "--serve",
            action="store_true",
            help="Serve the --find-links repo.",
        )
        extract_parser.add_argument(
            "--port",
            type=int,
            default=0,
            metavar="PORT",
            help="The port to serve the --find-links repo on.",
        )
        extract_parser.add_argument(
            "--pid-file",
            metavar="PATH",
            help="The path of a file to write the <pid>:<port> of the find links server to.",
        )
        cls.register_global_arguments(extract_parser)
        return extract_parser

    @classmethod
    def add_arguments(cls, parser):
        # type: (ArgumentParser) -> None
        cls.add_output_option(parser, entity="distribution information")
        parser.set_defaults(repository_func=functools.partial(cls.show_help, parser))

        subparsers = parser.add_subparsers(
            description=(
                "A PEX distribution repository can be operated on using any of the following "
                "subcommands."
            )
        )
        cls._add_info_arguments(subparsers).set_defaults(repository_func=cls._info)
        cls._add_extract_arguments(subparsers).set_defaults(repository_func=cls._extract)

    def run(self, pex):
        # type: (PEX) -> Result
        repository_func = cast("RepositoryFunc", self.options.repository_func)
        return repository_func(self, pex)

    @contextmanager
    def _distributions_output(self, pex):
        # type: (PEX) -> Iterator[Tuple[Iterable[Distribution], IO]]
        with self.output(self.options) as out:
            yield tuple(pex.resolve()), out

    def _info(self, pex):
        # type: (PEX) -> Result
        with self._distributions_output(pex) as (distributions, output):
            for distribution in distributions:
                if self.options.verbose:
                    requires_python = dist_metadata.requires_python(distribution)
                    requires_dists = list(dist_metadata.requires_dists(distribution))
                    self.dump_json(
                        self.options,
                        dict(
                            project_name=distribution.project_name,
                            version=distribution.version,
                            requires_python=str(requires_python) if requires_python else None,
                            requires_dists=[str(dist) for dist in requires_dists],
                            location=distribution.location,
                        ),
                        output,
                    )
                else:
                    output.write(
                        "{project_name} {version} {location}".format(
                            project_name=distribution.project_name,
                            version=distribution.version,
                            location=distribution.location,
                        )
                    )
                output.write("\n")
        return Ok()

    def _extract(self, pex):
        # type: (PEX) -> Result
        if not self.options.serve and not self.options.dest_dir:
            return Error("Specify a --find-links directory to extract wheels to.")

        dest_dir = (
            os.path.abspath(os.path.expanduser(self.options.dest_dir))
            if self.options.dest_dir
            else safe_mkdtemp()
        )
        safe_mkdir(dest_dir)

        if self.options.sources:
            self._extract_sdist(pex, dest_dir)

        def spawn_extract(distribution):
            # type: (Distribution) -> SpawnedJob[Text]
            env = os.environ.copy()
            if not self.options.use_system_time:
                # N.B.: The `SOURCE_DATE_EPOCH` env var is semi-standard magic for controlling
                # build tools. Wheel has supported this since 2016.
                # See:
                # + https://reproducible-builds.org/docs/source-date-epoch/
                # + https://github.com/pypa/wheel/blob/1b879e53fed1f179897ed47e55a68bc51df188db/wheel/archive.py#L36-L39
                env.update(SOURCE_DATE_EPOCH=str(int(DETERMINISTIC_DATETIME_TIMESTAMP)))
            job = spawn_python_job(
                args=["-m", "wheel", "pack", "--dest-dir", dest_dir, distribution.location],
                interpreter=pex.interpreter,
                expose=["wheel"],
                stdout=subprocess.PIPE,
                env=env,
            )
            return SpawnedJob.stdout(
                job, result_func=lambda out: "{}: {}".format(distribution, out.decode())
            )

        with self._distributions_output(pex) as (distributions, output):
            errors = []
            for result in execute_parallel(distributions, spawn_extract, error_handler=Retain()):
                if isinstance(result, tuple):
                    distribution, error = result
                    errors.append(distribution)
                    output.write(
                        "Failed to build a wheel for {distribution}: {error}\n".format(
                            distribution=distribution, error=error
                        )
                    )
                else:
                    output.write(result)
            if errors:
                return Error(
                    "Failed to build wheels for {count} {distributions}.".format(
                        count=len(errors), distributions=pluralize(errors, "distribution")
                    )
                )

        if not self.options.serve:
            return Ok()

        repo = FindLinksRepo.serve(
            interpreter=pex.interpreter, port=self.options.port, directory=dest_dir
        )
        output.write(
            "Serving find-links repo of {pex} via {find_links} at http://localhost:{port}\n".format(
                pex=os.path.normpath(pex.path()), find_links=dest_dir, port=repo.port
            )
        )
        if self.options.pid_file:
            with safe_open(self.options.pid_file, "w") as fp:
                fp.write("{}:{}".format(repo.pid, repo.port))
        try:
            return Result(exit_code=repo.join(), message=" ".join(repo.cmd))
        except KeyboardInterrupt:
            repo.kill()
            return Ok("Shut down server for find links repo at {}.".format(dest_dir))

    @staticmethod
    def _extract_sdist(
        pex,  # type: PEX
        dest_dir,  # type: str
    ):
        # type: (...) -> None
        pex_info = pex.pex_info()

        chroot = safe_mkdtemp()
        pex_path = pex.path()
        src = os.path.join(chroot, "src")
        excludes = ["__main__.py", pex_info.PATH, pex_info.bootstrap, pex_info.internal_cache]
        shutil.copytree(
            PEXEnvironment.mount(pex_path).path, src, ignore=lambda _dir, _names: excludes
        )

        name, _ = os.path.splitext(os.path.basename(pex_path))
        version = "0.0.0+{}".format(pex_info.code_hash)
        zip_safe = False  # Since PEX files never require code to be zip safe, assume it isn't.
        py_modules = [os.path.splitext(f)[0] for f in os.listdir(src) if f.endswith(".py")]
        packages = [
            os.path.relpath(os.path.join(root, d), src).replace(os.sep, ".")
            for root, dirs, _ in os.walk(src)
            for d in dirs
        ]
        install_requires = [str(req) for req in pex_info.requirements]

        python_requires = None
        if len(pex_info.interpreter_constraints) == 1:
            python_requires = str(
                PythonIdentity.parse_requirement(pex_info.interpreter_constraints[0]).specifier
            )
        elif pex_info.interpreter_constraints:
            logger.warning(
                "Omitting `python_requires` for {name} sdist since {pex} has multiple "
                "interpreter constraints:\n{interpreter_constraints}".format(
                    name=name,
                    pex=os.path.normpath(pex_path),
                    interpreter_constraints="\n".join(
                        "{index}.) {constraint}".format(index=index, constraint=constraint)
                        for index, constraint in enumerate(
                            pex_info.interpreter_constraints, start=1
                        )
                    ),
                )
            )

        entry_points = []
        if pex_info.entry_point and ":" in pex_info.entry_point:
            entry_points = [(name, pex_info.entry_point)]

        with open(os.path.join(chroot, "setup.cfg"), "w") as fp:
            fp.write(
                dedent(
                    """\
                    [metadata]
                    name = {name}
                    version = {version}

                    [options]
                    zip_safe = {zip_safe}
                    {py_modules}
                    {packages}
                    package_dir =
                        =src
                    include_package_data = True

                    {python_requires}
                    {install_requires}

                    [options.entry_points]
                    {entry_points}
                    """
                ).format(
                    name=name,
                    version=version,
                    zip_safe=zip_safe,
                    py_modules=(
                        "py_modules =\n  {}".format("\n  ".join(py_modules)) if py_modules else ""
                    ),
                    packages=(
                        "packages = \n  {}".format("\n  ".join(packages)) if packages else ""
                    ),
                    install_requires=(
                        "install_requires =\n  {}".format("\n  ".join(install_requires))
                        if install_requires
                        else ""
                    ),
                    python_requires=(
                        "python_requires = {}".format(python_requires) if python_requires else ""
                    ),
                    entry_points=(
                        "console_scripts =\n  {}".format(
                            "\n  ".join(
                                "{} = {}".format(name, entry_point)
                                for name, entry_point in entry_points
                            )
                        )
                        if entry_points
                        else ""
                    ),
                )
            )

        with open(os.path.join(chroot, "MANIFEST.in"), "w") as fp:
            fp.write("recursive-include src *")

        with open(os.path.join(chroot, "setup.py"), "w") as fp:
            fp.write("import setuptools; setuptools.setup()")

        spawn_python_job(
            args=["setup.py", "sdist", "--dist-dir", dest_dir],
            interpreter=pex.interpreter,
            expose=["setuptools"],
            cwd=chroot,
        ).wait()
