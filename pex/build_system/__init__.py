# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import json
import os
import subprocess
from textwrap import dedent

from pex.common import REPRODUCIBLE_BUILDS_ENV, CopyMode, safe_mkdtemp
from pex.dist_metadata import Distribution
from pex.interpreter import PythonInterpreter
from pex.jobs import Job, SpawnedJob
from pex.pex import PEX
from pex.pex_bootstrapper import VenvPex, ensure_venv
from pex.pex_builder import PEXBuilder
from pex.result import Error
from pex.typing import TYPE_CHECKING
from pex.variables import ENV
from pex.venv.bin_path import BinPath
from pex.venv.virtualenv import Virtualenv

if TYPE_CHECKING:
    from typing import Any, Iterable, Mapping, Optional, Tuple, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


# The split of PEP-517 / PEP-518 is quite awkward. PEP-518 doesn't really work without also
# specifying a build backend or knowing a default value for one, but the concept is not defined
# until PEP-517. As such, we break this historical? strange division and define the default outside
# both PEPs.
#
# See: https://peps.python.org/pep-0517/#source-trees
DEFAULT_BUILD_BACKEND = "setuptools.build_meta:__legacy__"
DEFAULT_BUILD_REQUIRES = ("setuptools",)


@attr.s(frozen=True)
class BuildSystemTable(object):
    requires = attr.ib()  # type: Tuple[str, ...]
    build_backend = attr.ib(default=DEFAULT_BUILD_BACKEND)  # type: str
    backend_path = attr.ib(default=())  # type: Tuple[str, ...]


DEFAULT_BUILD_SYSTEM_TABLE = BuildSystemTable(
    requires=DEFAULT_BUILD_REQUIRES, build_backend=DEFAULT_BUILD_BACKEND
)


# Exit code 75 is EX_TEMPFAIL defined in /usr/include/sysexits.h
# this seems an appropriate signal of DNE vs execute and fail.
_HOOK_UNAVAILABLE_EXIT_CODE = 75


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

    def invoke_build_hook(
        self,
        project_directory,  # type: str
        hook_method,  # type: str
        hook_args=(),  # type: Iterable[Any]
        hook_kwargs=None,  # type: Optional[Mapping[str, Any]]
    ):
        # type: (...) -> Union[SpawnedJob[Any], Error]

        # The interfaces are spec'd here: https://peps.python.org/pep-0517
        build_backend_module, _, _ = self.build_backend.partition(":")
        build_backend_object = self.build_backend.replace(":", ".")
        build_hook_result = os.path.join(
            safe_mkdtemp(prefix="pex-pep-517."), "build_hook_result.json"
        )
        args = self.venv_pex.execute_args(
            additional_args=(
                "-c",
                dedent(
                    """\
                    import json
                    import sys
    
                    import {build_backend_module}
    
    
                    if not hasattr({build_backend_object}, {hook_method!r}):
                        sys.exit({hook_unavailable_exit_code})
    
                    result = {build_backend_object}.{hook_method}(*{hook_args!r}, **{hook_kwargs!r})
                    with open({result_file!r}, "w") as fp:
                        json.dump(result, fp)
                    """
                ).format(
                    build_backend_module=build_backend_module,
                    build_backend_object=build_backend_object,
                    hook_method=hook_method,
                    hook_args=tuple(hook_args),
                    hook_kwargs=dict(hook_kwargs) if hook_kwargs else {},
                    hook_unavailable_exit_code=_HOOK_UNAVAILABLE_EXIT_CODE,
                    result_file=build_hook_result,
                ),
            )
        )
        process = subprocess.Popen(
            args=args,
            env=self.env,
            cwd=project_directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return SpawnedJob.file(
            Job(
                command=args,
                process=process,
                context="PEP-517:{hook_method} at {project_directory}".format(
                    hook_method=hook_method, project_directory=project_directory
                ),
            ),
            output_file=build_hook_result,
            result_func=lambda file_content: json.loads(file_content.decode("utf-8")),
        )
