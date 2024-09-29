#!/usr/bin/env python3

from __future__ import annotations

import logging
import subprocess
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser
from pathlib import Path, PurePath

import coloredlogs
import yaml


def build_cache_image(
    tox_envs: list[str], tag: str, pex_repo: str, git_ref: str, push: bool = False
) -> None:
    image_tag = f"ghcr.io/pex-tool/pex/cache:{tag}"
    subprocess.run(
        args=[
            "docker",
            "build",
            "--progress",
            "plain",
            "--build-arg",
            f"PEX_REPO={pex_repo}",
            "--build-arg",
            f"GIT_REF={git_ref}",
            "--build-arg",
            f"TOX_ENVS={','.join(tox_envs)}",
            "--tag",
            image_tag,
            str(PurePath("docker") / "cache"),
        ],
        check=True,
    )
    if push:
        subprocess.run(args=["docker", "push", image_tag], check=True)


def main() -> None:
    parser = ArgumentParser(
        formatter_class=ArgumentDefaultsHelpFormatter,
        description=(
            "Builds (and optionally pushes) a data-only cache image for use with "
            "`CACHE_MODE=pull ./dtox.sh ...`."
        ),
    )
    parser.add_argument(
        "-l",
        "--log-level",
        type=lambda arg: arg.upper(),
        default="INFO",
        choices=["DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level (case insensitive).",
    )
    parser.add_argument("--color", default=None, action="store_true", help="Force colored logging.")
    parser.add_argument(
        "--tag",
        type=str,
        default="latest",
        help="The tag for the ghcr.io/pex-tool/pex/cache-all image.",
    )
    parser.add_argument(
        "--pex-repo",
        type=str,
        default="https://github.com/pex-tool/pex",
        help="The pex repo to clone and use for the docker/cache population.",
    )
    parser.add_argument(
        "--git-ref",
        type=str,
        default="HEAD",
        help="The git ref to use within `--pex-repo`.",
    )
    parser.add_argument(
        "--push",
        default=False,
        action="store_true",
        help="Push the image to the registry after building and tagging it.",
    )

    options = parser.parse_args()

    coloredlogs.install(
        level=options.log_level, fmt="%(levelname)s %(message)s", isatty=options.color
    )
    logger = logging.getLogger(parser.prog)
    logger.log(
        logging.root.level, "Logging configured at level {level}.".format(level=options.log_level)
    )

    with (Path(".github") / "workflows" / "ci.yml").open() as fp:
        data = yaml.full_load(fp)
    tox_envs = sorted(
        set(
            entry["tox-env"]
            for entry in data["jobs"]["linux-tests"]["strategy"]["matrix"]["include"]
        )
    )

    logger.info(f"Building caches for {len(tox_envs)} tox environments.")
    for tox_env in tox_envs:
        logger.debug(tox_env)

    build_cache_image(
        tox_envs,
        tag=options.tag,
        pex_repo=options.pex_repo,
        git_ref=options.git_ref,
        push=options.push,
    )


if __name__ == "__main__":
    main()
