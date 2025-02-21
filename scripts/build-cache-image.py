#!/usr/bin/env python3

from __future__ import annotations

import atexit
import glob
import hashlib
import itertools
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
from argparse import ArgumentDefaultsHelpFormatter, ArgumentParser
from enum import Enum
from pathlib import Path, PurePath
from subprocess import CalledProcessError
from tempfile import mkdtemp
from typing import Any, Iterable, Iterator

import coloredlogs
import colors
import yaml


class BuildStyle(Enum):
    BUILD = "build"
    MERGE = "merge"

    def __str__(self) -> str:
        return self.value


class PostBuildAction(Enum):
    PUSH = "push"
    EXPORT = "export"

    def __str__(self) -> str:
        return self.value


_CACHE_INPUTS = (
    Path("docker") / "cache",
    Path("testing") / "__init__.py",  # Sets up fixed set of pyenv interpreters for ITs.
    Path("testing") / "devpi.py",
    Path("testing") / "devpi-server.lock",
)


def fingerprint_cache_inputs(image_id: str | None = None) -> str:
    def iter_files(path: Path) -> Iterator[Path]:
        if path.is_dir():
            for root, dirs, files in os.walk(path):
                for f in files:
                    yield Path(root) / f
        else:
            yield path

    hashes = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(
            itertools.chain.from_iterable(iter_files(cache_input) for cache_input in _CACHE_INPUTS)
        )
    }

    return hashlib.sha256(
        json.dumps({"image_id": image_id, "hashes": hashes}, sort_keys=True).encode("utf-8")
    ).hexdigest()


def export_tarball_path(sub_image: str | None = None) -> Path:
    path = Path(mkdtemp()) / f"cache-{sub_image or 'all'}.tar"
    atexit.register(shutil.rmtree, str(path), ignore_errors=True)
    return path


def create_image_tag(tag: str, sub_image: str | None = None) -> str:
    image = "ghcr.io/pex-tool/pex/cache"
    if sub_image:
        image = f"{image}/{sub_image}"
    return f"{image}:{tag}"


def build_cache_image(
    tox_envs: Iterable[str],
    image_id: str | None,
    image_tag: str,
    pex_repo: str,
    git_ref: str,
) -> None:
    subprocess.run(
        args=[
            "docker",
            "buildx",
            "build",
            "--build-arg",
            f"FINGERPRINT={fingerprint_cache_inputs(image_id=image_id)}",
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


def list_tox_envs() -> list[str]:
    with (Path(".github") / "workflows" / "ci.yml").open() as fp:
        data = yaml.full_load(fp)
    return sorted(
        dict.fromkeys(
            entry["tox-env"]
            for entry in data["jobs"]["linux-tests"]["strategy"]["matrix"]["include"]
        )
    )


def main() -> Any:
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
        "--list-tox-envs",
        default=False,
        action="store_true",
        help="Emit the list of tox environment names that should be cached.",
    )
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
        "--build-style",
        default=BuildStyle.BUILD,
        choices=BuildStyle,
        type=BuildStyle,
        help="The method to use to build the cache image.",
    )
    parser.add_argument(
        "--post-action",
        dest="post_build_action",
        default=None,
        choices=PostBuildAction,
        type=PostBuildAction,
        help="An action to execute after building and tagging the cache image.",
    )
    parser.add_argument(
        "--dist-dir",
        default=Path("dist"),
        type=Path,
        help="The directory to import and export image tarballs.",
    )
    parser.add_argument(
        "--tox-env",
        dest="tox_envs",
        action="append",
        default=[],
        help=(
            "The tox environments to execute to build the cache image. By default, all Linux test "
            "environments run in CI are selected. The option can either be repeated or environment "
            "names can be joined by commas."
        ),
    )
    options = parser.parse_args()

    if options.list_tox_envs:
        for tox_env in list_tox_envs():
            print(tox_env)
        return 0

    coloredlogs.install(
        level=options.log_level, fmt="%(levelname)s %(message)s", isatty=options.color
    )
    logger = logging.getLogger(parser.prog)
    logger.log(
        logging.root.level, "Logging configured at level {level}.".format(level=options.log_level)
    )

    sub_image: str | None = None
    if options.build_style is BuildStyle.MERGE:
        image_tag = create_image_tag(options.tag)
        chroot = Path(mkdtemp())
        atexit.register(shutil.rmtree, str(chroot), ignore_errors=True)

        tarballs = glob.glob(str(options.dist_dir / "cache-*.tar"))
        if not tarballs:
            return colors.red(f"No cache-*.tar files found under {options.dist_dir}!")
        elif len(tarballs) == 1:
            merged_tarball = Path(tarballs[0])
        else:
            for index, tarball in enumerate(tarballs, start=1):
                logger.info(f"Extracting {index} of {len(tarballs)} tarballs at {tarball}...")
                with tarfile.open(tarball) as tf:
                    while True:
                        tar_info = tf.next()
                        if not tar_info:
                            break
                        if not tar_info.isdir() and (chroot / tar_info.name).exists():
                            logger.debug(f"Skipping already extracted {tar_info.name}")
                            continue
                        tf.extract(tar_info, chroot)

            logger.info(f"Merging {len(tarballs)} extracted tarballs...")
            merged_tarball = export_tarball_path()
            with tarfile.open(merged_tarball, "w") as tf:
                tf.add(chroot, arcname="/")

        logger.info(f"Importing merged tarball to {image_tag}...")
        subprocess.run(args=["docker", "import", merged_tarball, image_tag], check=True)
    else:
        all_tox_envs = frozenset(list_tox_envs())
        selected_tox_envs = (
            frozenset(
                itertools.chain.from_iterable(tox_envs.split(",") for tox_envs in options.tox_envs)
            )
            if options.tox_envs
            else all_tox_envs
        )
        bad_tox_envs = selected_tox_envs - all_tox_envs
        if bad_tox_envs:
            return colors.red(
                "\n".join(
                    (
                        "The following selected tox envs are not used in Linux CI test shards:",
                        *(f"  {bad_tox_env}" for bad_tox_env in sorted(bad_tox_envs)),
                        "Valid tox envs are:",
                        *(f"  {valid_tox_env}" for valid_tox_env in sorted(all_tox_envs)),
                    )
                )
            )
        tox_envs = sorted(selected_tox_envs)

        if options.tox_envs:
            sub_image = (
                tox_envs[0]
                if len(tox_envs) == 1
                else hashlib.sha256("|".join(tox_envs).encode("utf-8")).hexdigest()
            )

        image_tag = create_image_tag(options.tag, sub_image=sub_image)
        logger.info(f"Building caches for {len(tox_envs)} tox environments.")
        for tox_env in tox_envs:
            logger.debug(tox_env)

        build_cache_image(
            tox_envs,
            image_id=sub_image,
            image_tag=image_tag,
            pex_repo=options.pex_repo,
            git_ref=options.git_ref,
        )

    if options.post_build_action is PostBuildAction.EXPORT:
        cache_tar = export_tarball_path(sub_image=sub_image)

        container_name = cache_tar.stem
        subprocess.run(args=["docker", "remove", "--force", container_name])
        subprocess.run(
            args=["docker", "create", "--name", container_name, image_tag, "true"], check=True
        )

        subprocess.run(args=["docker", "export", container_name, "--output", cache_tar], check=True)
        subprocess.run(args=["docker", "remove", container_name])

        options.dist_dir.mkdir(parents=True, exist_ok=True)
        dst = options.dist_dir / cache_tar.name
        shutil.move(cache_tar, dst)
        os.chmod(dst, 0o644)
        logger.info(f"Exported cache image to {dst}.")

    if options.post_build_action is PostBuildAction.PUSH:
        subprocess.run(args=["docker", "push", image_tag], check=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except CalledProcessError as e:
        sys.exit(colors.red(str(e)))
