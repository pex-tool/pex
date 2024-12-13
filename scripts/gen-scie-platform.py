#!/usr/bin/env python3

from __future__ import annotations

import argparse
import itertools
import json
import logging
import os.path
import subprocess
import sys
import tempfile
import time
import zipfile
from argparse import ArgumentError, ArgumentTypeError
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent
from typing import IO, Collection, Iterable, Iterator

import github
import httpx
from github import Github
from github.WorkflowRun import WorkflowRun

from package.scie_config import PlatformConfig, ScieConfig

logger = logging.getLogger(__name__)


class GitHubError(Exception):
    """Indicates an error interacting with the GitHub API."""


PACKAGE_DIR = Path("package")
GEN_SCIE_PLATFORMS_WORKFLOW = "gen-scie-platforms.yml"


def create_all_complete_platforms(
    dest_dir: Path,
    scie_config: ScieConfig,
    out: IO[str] = sys.stderr,
) -> Iterator[Path]:

    # TODO: Support more auth forms if a Pex developer that doesn't use ~/.netrc comes along.
    gh = Github(auth=github.Auth.NetrcAuth())
    repo = gh.get_repo("pex-tool/pex")

    workflow_url = (
        f"https://github.com/pex-tool/pex/actions/workflows/{GEN_SCIE_PLATFORMS_WORKFLOW}"
    )
    workflow = repo.get_workflow(GEN_SCIE_PLATFORMS_WORKFLOW)
    encoded_scie_config = scie_config.encode()
    if not workflow.create_dispatch(
        ref="main", inputs={"encoded-scie-config": encoded_scie_config}
    ):
        raise GitHubError(
            dedent(
                f"""\
                Failed to dispatch {GEN_SCIE_PLATFORMS_WORKFLOW} with parameters:
                + encoded-scie-config={encoded_scie_config[:16]}...
                """
            )
        )
    print(f"Dispatched workflow {GEN_SCIE_PLATFORMS_WORKFLOW}.", file=out)

    max_time = time.time() + 30
    print(f"Waiting up to 30 seconds for workflow run to show up.", file=out)
    runs: list[WorkflowRun] = []
    while time.time() < max_time:
        runs.extend(r for r in workflow.get_runs(actor=gh.get_user().login) if not r.conclusion)
        if not runs:
            time.sleep(1)
            print(".", end="", flush=True, file=out)
            continue
        print(file=out)
        break
    if not runs:
        raise GitHubError(
            f"The {GEN_SCIE_PLATFORMS_WORKFLOW} workflow was dispatched but no pending or "
            "in-flight run was found.\n"
            f"You can investigate at {workflow_url}"
        )
    run = runs[0]

    print(f"Monitoring workflow run at {run.html_url}.", file=out)

    # The long pole job currently takes ~4 minutes; so 10 minutes should cover things.
    max_time = time.time() + (60 * 10)
    print(f"Waiting up to 10 minutes for run to complete.", file=out)
    while time.time() < max_time:
        run = repo.get_workflow_run(run.id)
        if not run.conclusion:
            time.sleep(10)
            print(".", end="", flush=True, file=out)
            continue
        if "success" != run.conclusion:
            raise GitHubError(
                f"The workflow run {run.html_url} completed unsuccessfully with status "
                f"{run.status}."
            )
        print(file=out)
        break

    artifacts = list(run.get_artifacts())
    if not artifacts:
        raise GitHubError(f"No artifacts were found for workflow run {run.html_url}.")
    if len(artifacts) != len(scie_config.platforms):
        logger.warning(
            f"Expected to find {len(scie_config.platforms)} workflow run artifacts, but only "
            f"found {len(artifacts)}."
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    for artifact in artifacts:
        print(f"Downloading {artifact.archive_download_url} to {dest_dir}...", file=out)
        with httpx.stream(
            "GET", artifact.archive_download_url, follow_redirects=True
        ) as response, tempfile.SpooledTemporaryFile(max_size=1_000_000) as tmp_fp:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                tmp_fp.write(chunk)
            tmp_fp.flush()
            tmp_fp.seek(0)
            with zipfile.ZipFile(tmp_fp) as zip_fp:
                zip_fp.extractall(dest_dir)
                for name in zip_fp.namelist():
                    yield dest_dir / name


def ensure_all_complete_platforms(
    dest_dir: Path,
    scie_config: ScieConfig,
    force: bool = False,
    out: IO[str] = sys.stderr,
) -> Iterable[Path]:

    complete_platform_files: list[Path] = []
    if dest_dir.exists():
        complete_platforms = list(dest_dir.glob("*.json"))
        if complete_platforms and force:
            print("Force regenerating complete platform files.", file=out)
        else:
            for platform in scie_config.platforms:
                complete_platform_file = dest_dir / f"{platform.name}.json"
                if not complete_platform_file.exists():
                    continue
                with complete_platform_file.open() as fp:
                    meta_data = json.load(fp).get("__meta_data__")
                    if (
                        not meta_data
                        or platform.pbs_release != meta_data["pbs-release"]
                        or platform.python_version != meta_data["python-version"]
                    ):
                        print(
                            "The complete platform file "
                            f"{complete_platform_file.relative_to(PACKAGE_DIR)} is out of date, "
                            "re-generating...",
                            file=out,
                        )
                        continue
                    complete_platform_files.append(complete_platform_file)
            if len(scie_config.platforms) == len(complete_platform_files):
                print(f"The complete platform files are up to date. Not re-generating.", file=out)
                return complete_platform_files

    return list(create_all_complete_platforms(dest_dir, scie_config, out=out))


def create_lock(
    lock_file: Path,
    complete_platforms: Collection[Path],
    scie_config: ScieConfig,
    out: IO[str] = sys.stderr,
) -> None:
    print(f"Generating strict wheel-only lock for {len(complete_platforms)} platforms...", file=out)
    args = [
        sys.executable,
        "-m",
        "pex.cli",
        "lock",
        "sync",
        "--project",
        f".[{','.join(scie_config.pex_extras)}]",
        "--no-build",
        *itertools.chain.from_iterable(
            ("--complete-platform", str(complete_platform))
            for complete_platform in sorted(complete_platforms)
        ),
        "--pip-version",
        "latest",
        "--elide-unused-requires-dist",
        "--indent",
        "2",
        "--lock",
        str(lock_file),
    ]
    args.extend(scie_config.extra_lock_args)
    subprocess.run(args=args, check=True)


@contextmanager
def pex3_binary(platform: PlatformConfig) -> Iterator[str]:
    with tempfile.TemporaryDirectory() as td:
        pex3 = os.path.join(td, "pex3")
        subprocess.run(
            args=[
                sys.executable,
                "-m",
                "pex",
                ".",
                "-c",
                "pex3",
                "--scie",
                "lazy",
                "--scie-pbs-release",
                platform.pbs_release,
                "--scie-python-version",
                platform.python_version,
                "-o",
                pex3,
            ],
            check=True,
        )
        yield pex3


def create_complete_platform(complete_platform_file: Path, platform: PlatformConfig) -> None:
    with pex3_binary(platform=platform) as pex3:
        complete_platform = json.loads(
            subprocess.run(
                args=[pex3, "interpreter", "inspect", "--markers", "--tags"],
                stdout=subprocess.PIPE,
                check=True,
            ).stdout
        )
        path = complete_platform.pop("path")

        complete_platform["__meta_data__"] = {
            "comment": (
                "DO NOT EDIT - Generated via: `tox -e gen-scie-platform -- "
                "--pbs-release {pbs_release} --python-version {python_version}`.".format(
                    pbs_release=platform.pbs_release,
                    python_version=platform.python_version,
                )
            ),
            "pbs-release": platform.pbs_release,
            "python-version": platform.python_version,
        }

        logger.info(f"Generating {complete_platform_file} using Python at:\n{path}")

        complete_platform_file.parent.mkdir(parents=True, exist_ok=True)
        with complete_platform_file.open("w") as fp:
            json.dump(complete_platform, fp, indent=2, sort_keys=True)


def main(out: IO[str]) -> str | int | None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--dest-dir", type=Path, default=PACKAGE_DIR / "complete-platforms")
    parser.add_argument("--pbs-release")
    parser.add_argument("--python-version")
    parser.add_argument("--encoded-scie-config")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("-f", "--force", action="store_true")
    parser.add_argument("--lock-file", type=Path, default=PACKAGE_DIR / "pex-scie.lock")
    sync_lock_options = parser.add_mutually_exclusive_group()
    sync_lock_options.add_argument("-L", "--only-sync-lock", default=False, action="store_true")
    sync_lock_options.add_argument(
        "--no-sync-lock", dest="sync_lock", default=True, action="store_false"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    try:
        options = parser.parse_args()
    except (ArgumentError, ArgumentTypeError) as e:
        return str(e)

    scie_config = ScieConfig.load(
        pbs_release=options.pbs_release,
        python_version=options.python_version,
        encoded_config=options.encoded_scie_config,
    )

    logging.basicConfig(level=logging.INFO if options.verbose else logging.WARNING)

    generated_files: list[Path] = []
    if not options.only_sync_lock:
        if options.all:
            try:
                generated_files.extend(
                    ensure_all_complete_platforms(
                        dest_dir=options.dest_dir, scie_config=scie_config, force=options.force
                    )
                )
            except (
                GitHubError,
                github.GithubException,
                github.BadAttributeException,
                httpx.HTTPError,
            ) as e:
                return str(e)
        else:
            current_platform = scie_config.current_platform()
            complete_platform_file = options.dest_dir / f"{current_platform.name}.json"
            try:
                create_complete_platform(
                    complete_platform_file=complete_platform_file, platform=current_platform
                )
            except subprocess.CalledProcessError as e:
                return str(e)
            generated_files.append(complete_platform_file)

    if options.only_sync_lock or options.sync_lock:
        try:
            create_lock(
                lock_file=options.lock_file,
                complete_platforms=tuple(options.dest_dir.glob("*.json")),
                scie_config=scie_config,
            )
        except subprocess.CalledProcessError as e:
            return str(e)
        generated_files.append(options.lock_file)

    for file in generated_files:
        print(str(file), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main(out=sys.stdout))
