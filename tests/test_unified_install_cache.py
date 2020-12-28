# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import subprocess
from subprocess import CalledProcessError
from textwrap import dedent

import pytest

from pex.common import safe_mkdir, safe_mkdtemp, safe_open, safe_rmtree
from pex.pex_info import PexInfo
from pex.pip import get_pip
from pex.testing import run_pex_command
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Dict


def test_issues_789_demo():
    # type: () -> None
    tmpdir = safe_mkdtemp()
    pex_project_dir = (
        subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode("utf-8").strip()
    )

    # 1. Imagine we've pre-resolved the requirements needed in our wheel house.
    requirements = [
        "ansicolors",
        "isort",
        "setuptools",  # N.B.: isort doesn't declare its setuptools dependency.
    ]

    wheelhouse = os.path.join(tmpdir, "wheelhouse")
    get_pip().spawn_download_distributions(
        download_dir=wheelhouse, requirements=requirements
    ).wait()

    # 2. Also imagine this configuration is passed to a tool (PEX or a wrapper as in this test
    # example) via the CLI or other configuration data sources. For example, Pants has a `PythonSetup`
    # that combines with BUILD target data to get you this sort of configuration info outside pex.
    resolver_settings = dict(
        indexes=[],  # Turn off pypi.
        find_links=[wheelhouse],  # Use our wheel house.
        build=False,  # Use only pre-built wheels.
    )  # type: Dict[str, Any]

    # 3. That same configuration was used to build a standard pex:
    resolver_args = []
    if len(resolver_settings["find_links"]) == 0:
        resolver_args.append("--no-index")
    else:
        for index in resolver_settings["indexes"]:
            resolver_args.extend(["--index", index])

    for repo in resolver_settings["find_links"]:
        resolver_args.extend(["--find-links", repo])

    resolver_args.append("--build" if resolver_settings["build"] else "--no-build")

    project_code_dir = os.path.join(tmpdir, "project_code_dir")
    with safe_open(os.path.join(project_code_dir, "colorized_isort.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import colors
                import os
                import subprocess
                import sys


                def run():
                    env = os.environ.copy()
                    env.update(PEX_MODULE='isort')
                    isort_process = subprocess.Popen(
                        sys.argv,
                        env=env,
                        stdout = subprocess.PIPE,
                        stderr = subprocess.PIPE
                    )
                    stdout, stderr = isort_process.communicate()
                    print(colors.green(stdout.decode('utf-8')))
                    print(colors.red(stderr.decode('utf-8')))
                    sys.exit(isort_process.returncode)
    """
            )
        )

    colorized_isort_pex = os.path.join(tmpdir, "colorized_isort.pex")
    args = [
        "--sources-directory",
        project_code_dir,
        "--entry-point",
        "colorized_isort:run",
        "--output-file",
        colorized_isort_pex,
    ]
    result = run_pex_command(args + resolver_args + requirements)
    result.assert_success()

    # 4. Now the tool builds a "dehydrated" PEX using the standard pex + resolve settings as the
    # template.
    ptex_cache = os.path.join(tmpdir, ".ptex")

    colorized_isort_pex_info = PexInfo.from_pex(colorized_isort_pex)
    colorized_isort_pex_info.pex_root = ptex_cache

    # Force the standard pex to extract its code. An external tool like Pants would already know the
    # original source code file paths, but we need to discover here.
    code_hash = colorized_isort_pex_info.code_hash
    assert code_hash is not None
    colorized_isort_pex_code_dir = os.path.join(
        colorized_isort_pex_info.zip_unsafe_cache, code_hash
    )
    env = os.environ.copy()
    env.update(PEX_ROOT=ptex_cache, PEX_INTERPRETER="1", PEX_FORCE_LOCAL="1")
    subprocess.check_call([colorized_isort_pex, "-c", ""], env=env)

    colorized_isort_ptex_code_dir = os.path.join(tmpdir, "colorized_isort_ptex_code_dir")
    safe_mkdir(colorized_isort_ptex_code_dir)

    code = []
    for root, dirs, files in os.walk(colorized_isort_pex_code_dir):
        rel_root = os.path.relpath(root, colorized_isort_pex_code_dir)
        for f in files:
            # Don't ship compiled python from the code extract above, the target interpreter will not
            # match ours in general.
            if f.endswith(".pyc"):
                continue
            rel_path = os.path.normpath(os.path.join(rel_root, f))
            # The root __main__.py is special for any zipapp including pex, let it write its own
            # __main__.py bootstrap. Similarly. PEX-INFO is special to pex and we want the PEX-INFO for
            # The ptex pex, not the pex being ptexed.
            if rel_path in ("__main__.py", PexInfo.PATH):
                continue
            os.symlink(os.path.join(root, f), os.path.join(colorized_isort_ptex_code_dir, rel_path))
            code.append(rel_path)

    ptex_code_dir = os.path.join(tmpdir, "ptex_code_dir")

    ptex_info = dict(code=code, resolver_settings=resolver_settings)
    with safe_open(os.path.join(ptex_code_dir, "PTEX-INFO"), "w") as fp:
        json.dump(ptex_info, fp)

    with safe_open(os.path.join(ptex_code_dir, "IPEX-INFO"), "w") as fp:
        fp.write(colorized_isort_pex_info.dump())

    with safe_open(os.path.join(ptex_code_dir, "ptex.py"), "w") as fp:
        fp.write(
            dedent(
                """\
                import json
                import os
                import sys

                from pex import resolver
                from pex.common import open_zip
                from pex.pex_builder import PEXBuilder
                from pex.pex_info import PexInfo
                from pex.util import CacheHelper
                from pex.variables import ENV

                self = sys.argv[0]
                ipex_file = '{}.ipex'.format(os.path.splitext(self)[0])

                if not os.path.isfile(ipex_file):
                    print('Hydrating {} to {}'.format(self, ipex_file))

                    ptex_pex_info = PexInfo.from_pex(self)
                    code_root = os.path.join(ptex_pex_info.zip_unsafe_cache, ptex_pex_info.code_hash)
                    with open_zip(self) as zf:
                        # Populate the pex with the pinned requirements and distribution names & hashes.
                        ipex_info = PexInfo.from_json(zf.read('IPEX-INFO'))
                        ipex_builder = PEXBuilder(pex_info=ipex_info)

                        # Populate the pex with the needed code.
                        ptex_info = json.loads(zf.read('PTEX-INFO').decode('utf-8'))
                        for path in ptex_info['code']:
                            ipex_builder.add_source(os.path.join(code_root, path), path)

                    # Perform a fully pinned intransitive resolve to hydrate the install cache (not the
                    # pex!).
                    resolver_settings = ptex_info['resolver_settings']
                    resolved_distributions = resolver.resolve(
                        requirements=[str(req) for req in ipex_info.requirements],
                        cache=ipex_info.pex_root,
                        transitive=False,
                        **resolver_settings
                    )

                    ipex_builder.build(ipex_file)

                os.execv(ipex_file, [ipex_file] + sys.argv[1:])
                """
            )
        )

    colorized_isort_ptex = os.path.join(tmpdir, "colorized_isort.ptex")

    result = run_pex_command(
        [
            "--not-zip-safe",
            "--always-write-cache",
            "--pex-root",
            ptex_cache,
            pex_project_dir,  # type: ignore[list-item]  # This is unicode in Py2, whereas everthing else is bytes. That's fine.
            "--sources-directory",
            ptex_code_dir,
            "--sources-directory",
            colorized_isort_ptex_code_dir,
            "--entry-point",
            "ptex",
            "--output-file",
            colorized_isort_ptex,
        ]
    )
    result.assert_success()

    subprocess.check_call([colorized_isort_ptex, "--version"])
    with pytest.raises(CalledProcessError):
        subprocess.check_call([colorized_isort_ptex, "--not-a-flag"])

    safe_rmtree(ptex_cache)

    # The dehydrated pex now fails since it lost its hydration from the cache.
    with pytest.raises(CalledProcessError):
        subprocess.check_call([colorized_isort_ptex, "--version"])
