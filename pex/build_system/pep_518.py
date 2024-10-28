# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os.path
import subprocess

from pex import toml
from pex.build_system import DEFAULT_BUILD_BACKEND
from pex.common import REPRODUCIBLE_BUILDS_ENV, CopyMode
from pex.dist_metadata import Distribution
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_bootstrapper import VenvPex, ensure_venv
from pex.pex_builder import PEXBuilder
from pex.resolve.resolvers import Resolver
from pex.result import Error
from pex.targets import LocalInterpreter, Target, Targets
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from pex.venv.bin_path import BinPath
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import Iterable, Mapping, Optional, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


@attr.s(frozen=True)
class BuildSystemTable(object):
    requires = attr.ib()  # type: Tuple[str, ...]
    build_backend = attr.ib(default=DEFAULT_BUILD_BACKEND)  # type: str
    backend_path = attr.ib(default=())  # type: Tuple[str, ...]


def _read_build_system_table(
    pyproject_toml,  # type: str
):
    # type: (...) -> Union[Optional[BuildSystemTable], Error]
    try:
        data = toml.load(pyproject_toml)
    except toml.TomlDecodeError as e:
        return Error(
            "Problem parsing toml in {pyproject_toml}: {err}".format(
                pyproject_toml=pyproject_toml, err=e
            )
        )

    build_system = data.get("build-system")
    if not build_system:
        return None

    requires = build_system.get("requires")
    if not requires:
        return None

    return BuildSystemTable(
        requires=tuple(requires),
        build_backend=build_system.get("build-backend", DEFAULT_BUILD_BACKEND),
        backend_path=tuple(
            os.path.join(os.path.dirname(pyproject_toml), entry)
            for entry in build_system.get("backend-path", ())
        ),
    )


@attr.s(frozen=True)
class BuildSystem(object):
    @classmethod
    def create(
        cls,
        interpreter,  # type: PythonInterpreter
        requires,  # type: Iterable[str]
        resolved,  # type: Iterable[Distribution]
        build_backend,  # type: str
        backend_path,  # type: Tuple[str, ...]
        extra_requirements=None,  # type: Optional[Iterable[str]]
        use_system_time=False,  # type: bool
        **extra_env  # type: str
    ):
        # type: (...) -> Union[BuildSystem, Error]
        pex_builder = PEXBuilder(copy_mode=CopyMode.SYMLINK)
        pex_builder.info.venv = True
        pex_builder.info.venv_site_packages_copies = True
        pex_builder.info.venv_bin_path = BinPath.PREPEND
        # Allow REPRODUCIBLE_BUILDS_ENV PYTHONHASHSEED env var to take effect.
        pex_builder.info.venv_hermetic_scripts = False
        for req in requires:
            pex_builder.add_requirement(req)
        for dist in resolved:
            pex_builder.add_distribution(dist)
        pex_builder.freeze(bytecode_compile=False)
        venv_pex = ensure_venv(PEX(pex_builder.path(), interpreter=interpreter))
        if extra_requirements:
            # N.B.: We install extra requirements separately instead of having them resolved and
            # handed in with the `resolved` above because there are cases in the wild where the
            # build system requires (PEP-518) and the results of PEP-517 `get_requires_for_*` can
            # return overlapping requirements. Pip will error for overlaps complaining of duplicate
            # requirements if we attempt to resolve all the requirements at once; so we instead
            # resolve and install in two phases. This obviously has problems! That said, it is, in
            # fact, how Pip's internal PEP-517 build frontend works; so we emulate that.
            virtualenv = Virtualenv(venv_pex.venv_dir)
            # Python 3.5 comes with Pip 9.0.1 which is pretty broken: it doesn't work with our test
            # cases; so we upgrade.
            # For Python 2.7 we use virtualenv (there is no -m venv built into Python) and that
            # comes with Pip 22.0.2, Python 3.6 comes with Pip 18.1 and Python 3.7 comes with
            # Pip 22.04 and the default Pips only get newer with newer version of Pythons. These all
            # work well enough for our test cases and, in general, they should work well enough with
            # the Python they come paired with.
            upgrade_pip = virtualenv.interpreter.version[:2] == (3, 5)
            virtualenv.ensure_pip(upgrade=upgrade_pip)
            with open(os.devnull, "wb") as dev_null:
                _, process = virtualenv.interpreter.open_process(
                    args=[
                        "-m",
                        "pip",
                        "install",
                        "--ignore-installed",
                        "--no-user",
                        "--no-warn-script-location",
                    ]
                    + list(extra_requirements),
                    stdout=dev_null,
                    stderr=subprocess.PIPE,
                )
                _, stderr = process.communicate()
                if process.returncode != 0:
                    return Error(
                        "Failed to install extra requirement in venv at {venv_dir}: "
                        "{extra_requirements}\nSTDERR:\n{stderr}".format(
                            venv_dir=venv_pex.venv_dir,
                            extra_requirements=", ".join(extra_requirements),
                            stderr=stderr.decode("utf-8"),
                        )
                    )

        # Ensure all PEX* env vars are stripped except for PEX_ROOT and PEX_VERBOSE. We want folks
        # to be able to steer the location of the cache and the logging verbosity, but nothing else.
        # We control the entry-point, etc. of the PEP-518 build backend venv for internal use.
        with ENV.strip().patch(PEX_ROOT=ENV.PEX_ROOT, PEX_VERBOSE=str(ENV.PEX_VERBOSE)) as env:
            if extra_env:
                env.update(extra_env)
            if backend_path:
                env.update(PEX_EXTRA_SYS_PATH=os.pathsep.join(backend_path))
            if not use_system_time:
                env.update(REPRODUCIBLE_BUILDS_ENV)
            return cls(
                venv_pex=venv_pex, build_backend=build_backend, requires=tuple(requires), env=env
            )

    venv_pex = attr.ib()  # type: VenvPex
    build_backend = attr.ib()  # type: str
    requires = attr.ib()  # type: Tuple[str, ...]
    env = attr.ib()  # type: Mapping[str, str]


def load_build_system(
    target,  # type: Target
    resolver,  # type: Resolver
    project_directory,  # type: str
    extra_requirements=None,  # type: Optional[Iterable[str]]
):
    # type: (...) -> Union[Optional[BuildSystem], Error]

    # The interface is spec'd here: https://peps.python.org/pep-0518/
    pyproject_toml = os.path.join(project_directory, "pyproject.toml")
    if not os.path.isfile(pyproject_toml):
        return None

    maybe_build_system_table_or_error = _read_build_system_table(pyproject_toml)
    if not isinstance(maybe_build_system_table_or_error, BuildSystemTable):
        return maybe_build_system_table_or_error
    build_system_table = maybe_build_system_table_or_error

    with TRACER.timed(
        "Building {build_backend} build_backend PEX".format(
            build_backend=build_system_table.build_backend
        )
    ):
        result = resolver.resolve_requirements(
            targets=Targets.from_target(LocalInterpreter.create(target.get_interpreter())),
            requirements=build_system_table.requires,
        )
        return BuildSystem.create(
            interpreter=target.get_interpreter(),
            requires=build_system_table.requires,
            resolved=tuple(
                resolved_distribution.distribution for resolved_distribution in result.distributions
            ),
            build_backend=build_system_table.build_backend,
            backend_path=build_system_table.backend_path,
            extra_requirements=extra_requirements,
            use_system_time=resolver.use_system_time(),
        )
