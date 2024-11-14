# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import json
import os
import re

from pex import compatibility
from pex.atomic_directory import atomic_directory
from pex.cache.dirs import CacheDir
from pex.common import safe_open, safe_rmtree
from pex.exceptions import production_assert
from pex.jobs import SpawnedJob
from pex.pep_425 import CompatibilityTags
from pex.pip.installation import get_pip
from pex.platforms import Platform, PlatformSpec
from pex.resolve.configured_resolver import ConfiguredResolver
from pex.resolve.resolver_configuration import PipConfiguration
from pex.third_party.packaging import tags
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Iterator, List, Optional

    import attr  # vendor:skip
else:
    from pex.third_party import attr


def _calculate_tags(
    pip_configuration,  # type: PipConfiguration
    platform_spec,  # type: PlatformSpec
    manylinux=None,  # type: Optional[str]
):
    # type: (...) -> Iterator[tags.Tag]

    def parse_tags(output):
        # type: (bytes) -> Iterator[tags.Tag]
        count = None  # type: Optional[int]
        try:
            for line in output.decode("utf-8").splitlines():
                if count is None:
                    match = re.match(r"^Compatible tags: (?P<count>\d+)\s+", line)
                    if match:
                        count = int(match.group("count"))
                    continue
                count -= 1
                if count < 0:
                    raise AssertionError("Expected {} tags but got more.".format(count))
                for tag in tags.parse_tag(line.strip()):
                    yield tag
        finally:
            if count != 0:
                raise AssertionError("Finished with count {}.".format(count))

    pip = get_pip(
        version=pip_configuration.version,
        resolver=ConfiguredResolver(pip_configuration=pip_configuration),
    )
    job = SpawnedJob.stdout(
        job=pip.spawn_debug(
            platform_spec=platform_spec,
            manylinux=manylinux,
            log=pip_configuration.log.path if pip_configuration.log else None,
        ),
        result_func=parse_tags,
    )
    return job.await_result()


class CompatibilityTagsParseError(ValueError):
    pass


def _parse_tags(path):
    # type: (str) -> CompatibilityTags

    with open(path) as fp:
        try:
            data = json.load(fp)
        except ValueError as e:
            raise CompatibilityTagsParseError(
                "Regenerating the platform info file at {} since it did not contain parsable "
                "JSON data: {}".format(fp.name, e)
            )

    if not isinstance(data, dict):
        raise CompatibilityTagsParseError(
            "Regenerating the platform info file at {} since it did not contain a "
            "configuration object. Found: {!r}".format(fp.name, data)
        )

    sup_tags = data.get("supported_tags")
    if not isinstance(sup_tags, list):
        raise CompatibilityTagsParseError(
            "Regenerating the platform info file at {} since it was missing a valid "
            "`supported_tags` list. Found: {!r}".format(fp.name, sup_tags)
        )

    count = len(sup_tags)

    def parse_tag(
        index,  # type: int
        tag,  # type: List[Any]
    ):
        # type: (...) -> tags.Tag
        if len(tag) != 3 or not all(
            isinstance(component, compatibility.string) for component in tag
        ):
            raise CompatibilityTagsParseError(
                "Serialized platform tags should be lists of three strings. Tag {index} of "
                "{count} was: {tag!r}.".format(index=index, count=count, tag=tag)
            )
        interpreter, abi, platform = tag
        return tags.Tag(interpreter=interpreter, abi=abi, platform=platform)

    try:
        return CompatibilityTags(tags=[parse_tag(index, tag) for index, tag in enumerate(sup_tags)])
    except ValueError as e:
        raise CompatibilityTagsParseError(
            "Regenerating the platform info file at {} since it did not contain parsable "
            "tag data: {}".format(fp.name, e)
        )


PLAT_INFO_FILE = "PLAT-INFO"


def create(
    platform,  # type: str
    manylinux=None,  # type: Optional[str]
    pip_configuration=PipConfiguration(),  # type: PipConfiguration
):
    # type: (...) -> Platform

    platform_spec = PlatformSpec.parse(platform)
    components = [str(platform_spec)]
    if manylinux:
        components.append(manylinux)
    disk_cache_key = CacheDir.PLATFORMS.path(
        "pip-{version}".format(version=pip_configuration.version), PlatformSpec.SEP.join(components)
    )

    with atomic_directory(target_dir=disk_cache_key) as cache_dir:
        if cache_dir.is_finalized():
            cached = True
        else:
            cached = False
            plat_info = attr.asdict(platform_spec)
            plat_info.update(
                supported_tags=[
                    (tag.interpreter, tag.abi, tag.platform)
                    for tag in _calculate_tags(
                        pip_configuration, platform_spec, manylinux=manylinux
                    )
                ],
            )
            with safe_open(os.path.join(cache_dir.work_dir, PLAT_INFO_FILE), "w") as fp:
                json.dump(plat_info, fp)

    platform_info_file = os.path.join(disk_cache_key, PLAT_INFO_FILE)
    try:
        compatibility_tags = _parse_tags(path=platform_info_file)
    except CompatibilityTagsParseError as e:
        production_assert(
            cached,
            "Unexpectedly generated invalid abbreviated platform compatibility tags from "
            "{platform}: {err}",
            platform=platform,
            err=e,
        )
        TRACER.log(str(e))
        safe_rmtree(disk_cache_key)
        return create(platform, manylinux=manylinux, pip_configuration=pip_configuration)

    if cached and pip_configuration.log:
        # When not cached and the Pip log is being retained, the tags are logged directly by our
        # call to `pip -v debug ...` in _calculate_tags above. We do the same for the cached case
        # since this can be very useful information when investigating why Pip did not select a
        # particular wheel for an abbreviated --platform.
        with safe_open(pip_configuration.log.path, "a") as fp:
            print(
                "Read {count} compatible tags for abbreviated --platform {platform} from:".format(
                    count=len(compatibility_tags), platform=platform
                ),
                file=fp,
            )
            print("    {cache_file}".format(cache_file=platform_info_file), file=fp)
            for tag in compatibility_tags:
                print(tag, file=fp)

    return Platform(
        platform=platform_spec.platform,
        impl=platform_spec.impl,
        version=platform_spec.version,
        version_info=platform_spec.version_info,
        abi=platform_spec.abi,
        supported_tags=compatibility_tags,
    )
