# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import re
import subprocess
from textwrap import dedent

import pytest

import pex.cli.commands.lockfile
from pex.cli.commands.lockfile import Lockfile, json_codec
from pex.compatibility import PY2
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import (
    Artifact,
    Fingerprint,
    LockedRequirement,
    LockedResolve,
    LockStyle,
    Pin,
    Version,
)
from pex.resolve.resolver_configuration import ResolverVersion
from pex.third_party.packaging import tags
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    import attr  # vendor:skip
    from typing import Any
else:
    if "__PEX_UNVENDORED__" in __import__("os").environ:
        import attr  # vendor:skip
    else:
        import pex.third_party.attr as attr


def test_roundtrip(tmpdir):
    # type: (Any) -> None

    lockfile = Lockfile.create(
        pex_version="1.2.3",
        style=LockStyle.STRICT,
        resolver_version=ResolverVersion.PIP_2020,
        requirements=(
            Requirement.parse("ansicolors"),
            Requirement.parse("requests>=2; sys_platform == 'darwin'"),
        ),
        constraints=(Requirement.parse("ansicolors==1.1.8"),),
        allow_prereleases=True,
        allow_wheels=False,
        allow_builds=False,
        transitive=False,
        locked_resolves=[
            LockedResolve.from_platform_tag(
                platform_tag=tags.Tag("cp36", "cp36m", "macosx_10_13_x86_64"),
                locked_requirements=[
                    LockedRequirement.create(
                        pin=Pin(project_name=ProjectName("ansicolors"), version=Version("1.1.8")),
                        artifact=Artifact(
                            url="https://example.org/colors-1.1.8-cp36-cp36m-macosx_10_6_x86_64.whl",
                            fingerprint=Fingerprint(algorithm="blake256", hash="cafebabe"),
                        ),
                        requirement=Requirement.parse("ansicolors"),
                        additional_artifacts=(),
                        via=(),
                    ),
                    LockedRequirement.create(
                        pin=Pin(project_name=ProjectName("requests"), version=Version("2.0.0")),
                        artifact=Artifact(
                            url="https://example.org/requests-2.0.0-py2.py3-none-any.whl",
                            fingerprint=Fingerprint(algorithm="sha256", hash="456"),
                        ),
                        requirement=Requirement.parse("requests>=2; sys_platform == 'darwin'"),
                        additional_artifacts=(
                            Artifact(
                                url="file://find-links/requests-2.0.0.tar.gz",
                                fingerprint=Fingerprint(algorithm="sha512", hash="123"),
                            ),
                        ),
                        via=("direct", "from", "a", "test"),
                    ),
                ],
            ),
            LockedResolve.from_platform_tag(
                platform_tag=tags.Tag("cp37", "cp37m", "manylinux1_x86_64"),
                locked_requirements=[
                    LockedRequirement.create(
                        pin=Pin(project_name=ProjectName("ansicolors"), version=Version("1.1.8")),
                        artifact=Artifact(
                            url="https://example.org/colors-1.1.8-cp37-cp37m-manylinux1_x86_64.whl",
                            fingerprint=Fingerprint(algorithm="md5", hash="hackme"),
                        ),
                        requirement=Requirement.parse("ansicolors"),
                        additional_artifacts=(),
                        via=(),
                    ),
                ],
            ),
        ],
    )
    assert lockfile == json_codec.loads(json.dumps(json_codec.as_json_data(lockfile)))

    with open(os.path.join(str(tmpdir), "lock.json"), "w") as fp:
        json.dump(json_codec.as_json_data(lockfile), fp)
    assert lockfile == json_codec.load(fp.name)


VALID_LOCK = """\
{
  "allow_builds": true,
  "allow_prereleases": false,
  "allow_wheels": true,
  "constraints": [],
  "locked_resolves": [
    {
      "locked_requirements": [
        {
          "artifacts": [
            {
              "algorithm": "md5",
              "hash": "f357aa02db2466bc24ff1815cff1aeb3",
              "url": "http://localhost:9999/ansicolors-1.1.8-py2.py3-none-any.whl"
            },
            {
              "algorithm": "md5",
              "hash": "9ca7e2396ffa2e20af023c6b83ab7b14",
              "url": "http://localhost:9999/ansicolors-1.1.8.zip"
            }
          ],
          "project_name": "ansicolors",
          "requirement": "ansicolors",
          "version": "1.1.8",
          "via": []
        }
      ],
      "platform_tag": [
        "cp39",
        "cp39",
        "manylinux_2_33_x86_64"
      ]
    }
  ],
  "pex_version": "2.1.50",
  "requirements": [
    "ansicolors"
  ],
  "resolver_version": "pip-legacy-resolver",
  "style": "sources",
  "transitive": true
}
"""


@attr.s(frozen=True)
class PatchTool(object):
    tmpdir = attr.ib()  # type: str

    def apply(self, patch):
        # type: (str) -> str
        lock_file = os.path.join(self.tmpdir, "lock.json")
        with open(lock_file, "w") as fp:
            fp.write(VALID_LOCK)
        patch = dedent(
            """\
            --- a/{lock_file}	
            +++ b/{lock_file}
            {patch}
            """
        ).format(lock_file=os.path.basename(lock_file), patch=patch)
        process = subprocess.Popen(args=["git", "apply"], cwd=self.tmpdir, stdin=subprocess.PIPE)
        process.communicate(input=patch.encode("utf-8"))
        assert 0 == process.returncode, "Applying patch failed with exit code {}".format(
            process.returncode
        )
        with open(lock_file) as fp:
            return fp.read()


@pytest.fixture
def patch_tool(tmpdir):
    # type: (Any) -> PatchTool
    return PatchTool(str(tmpdir))


def assert_parse_error(
    patch_tool,  # type: PatchTool
    patch,  # type: str
    match,  # type: str
):
    with pytest.raises(pex.cli.commands.lockfile.ParseError, match=match):
        json_codec.loads(patch_tool.apply(patch))


def test_load_invalid_json(patch_tool):
    # type: (PatchTool) -> None

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -1,2 +1,2 @@
            -{
            +[
               "allow_builds": true,
            """
        ),
        "The lock file at <string> does not contain valid JSON:",
    )


def test_load_invalid_type(patch_tool):
    # type: (PatchTool) -> None

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -1,3 +1,3 @@
             {
            -  "allow_builds": true,
            +  "allow_builds": 42,
               "allow_prereleases": false,
            """
        ),
        re.escape(
            "Expected '.[\"allow_builds\"]' in <string> to be of type bool but given int with "
            "value 42."
        ),
    )


def test_load_invalid_key_not_found(patch_tool):
    # type: (PatchTool) -> None

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -11,3 +11,2 @@
                         {
            -              "algorithm": "md5",
                           "hash": "f357aa02db2466bc24ff1815cff1aeb3",
            """
        ),
        match=re.escape(
            "The object at '.locked_resolves[0][0][\"artifacts\"][0]' in <string> did not have the "
            "expected key 'algorithm'."
        ),
    )
    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -12,3 +12,3 @@
                           "algorithm": "md5",
            -              "hash": "f357aa02db2466bc24ff1815cff1aeb3",
            +              "HASH": "f357aa02db2466bc24ff1815cff1aeb3",
                           "url": "http://localhost:9999/ansicolors-1.1.8-py2.py3-none-any.whl"
            """
        ),
        match=re.escape(
            "The object at '.locked_resolves[0][0][\"artifacts\"][0]' in <string> did not have the "
            "expected key 'hash'."
        ),
    )


FORMAT_ARGS = dict(
    str_type="unicode" if PY2 else "str",
    str_prefix="u" if PY2 else "",
)


def test_load_invalid_parent_not_json_object(patch_tool):
    # type: (PatchTool) -> None

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -10,7 +10,3 @@
                       "artifacts": [
            -            {
            -              "algorithm": "md5",
            -              "hash": "f357aa02db2466bc24ff1815cff1aeb3",
            -              "url": "http://localhost:9999/ansicolors-1.1.8-py2.py3-none-any.whl"
            -            },
            +            "foo",
                         {
            """
        ),
        match=re.escape(
            'Cannot retrieve \'.locked_resolves[0][0]["artifacts"][0]["url"]\' in <string> '
            "because '.locked_resolves[0][0][\"artifacts\"][0]' is not a JSON object but a "
            "{str_type} with value foo.".format(**FORMAT_ARGS)
        ),
    )


def test_load_invalid_requirement(patch_tool):
    # type: (PatchTool) -> None

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -36,3 +36,4 @@
               "requirements": [
            -    "ansicolors"
            +    "ansicolors",
            +    "@invalid requirement"
               ],
            """
        ),
        match=re.escape("The requirement string at '.requirements[1]' is invalid:"),
    )

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -4,3 +4,3 @@
               "allow_wheels": true,
            -  "constraints": [],
            +  "constraints": ["@invalid requirement"],
               "locked_resolves": [
            """
        ),
        match=re.escape("The requirement string at '.constraints[0]' is invalid:"),
    )

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -22,3 +22,3 @@
                       "project_name": "ansicolors",
            -          "requirement": "ansicolors",
            +          "requirement": "@invalid requirement",
                       "version": "1.1.8",
            """
        ),
        match=re.escape(
            "The requirement string at '.locked_resolves[0][0][\"requirement\"]' is invalid: "
        ),
    )


def test_load_invalid_resolver_version(patch_tool):
    # type: (PatchTool) -> None

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -38,3 +38,3 @@
               ],
            -  "resolver_version": "pip-legacy-resolver",
            +  "resolver_version": "apache-ivy",
               "style": "sources",
            """
        ),
        match=re.escape("The '.[\"resolver_version\"]' is invalid: "),
    )


def test_load_invalid_style(patch_tool):
    # type: (PatchTool) -> None

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -39,3 +39,3 @@
               "resolver_version": "pip-legacy-resolver",
            -  "style": "sources",
            +  "style": "foo",
               "transitive": true
            """
        ),
        match=re.escape("The '.[\"style\"]' is invalid: "),
    )


def test_load_invalid_platform_tag(patch_tool):
    # type: (PatchTool) -> None

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -28,3 +28,2 @@
                   "platform_tag": [
            -        "cp39",
                     "cp39",
            """
        ),
        match=re.escape(
            "The tag at '.locked_resolves[0][\"platform_tag\"]' must have 3 string components. "
            "Given 2 with types [{str_type}, {str_type}]: [{str_prefix}'cp39', "
            "{str_prefix}'manylinux_2_33_x86_64']".format(**FORMAT_ARGS)
        ),
    )

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -29,3 +29,3 @@
                     "cp39",
            -        "cp39",
            +        42,
                     "manylinux_2_33_x86_64"
            """
        ),
        match=re.escape(
            "The tag at '.locked_resolves[0][\"platform_tag\"]' must have 3 string components. "
            "Given 3 with types [{str_type}, int, {str_type}]: [{str_prefix}'cp39', 42, "
            "{str_prefix}'manylinux_2_33_x86_64']".format(**FORMAT_ARGS)
        ),
    )


def test_load_invalid_no_requirements(patch_tool):
    # type: (PatchTool) -> None

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -36,3 +36,2 @@
               "requirements": [
            -    "ansicolors"
               ],
            """
        ),
        match=re.escape("Expected '.requirements' in <string> to have at least one requirement."),
    )


def test_load_invalid_no_artifacts(patch_tool):
    # type: (PatchTool) -> None

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -10,12 +10,2 @@
                       "artifacts": [
            -            {
            -              "algorithm": "md5",
            -              "hash": "f357aa02db2466bc24ff1815cff1aeb3",
            -              "url": "http://localhost:9999/ansicolors-1.1.8-py2.py3-none-any.whl"
            -            },
            -            {
            -              "algorithm": "md5",
            -              "hash": "9ca7e2396ffa2e20af023c6b83ab7b14",
            -              "url": "http://localhost:9999/ansicolors-1.1.8.zip"
            -            }
                       ],
            """
        ),
        match=re.escape(
            "Expected '.locked_resolves[0][0]' in <string> to have at least one artifact."
        ),
    )


def test_load_invalid_no_locked_requirements(patch_tool):
    # type: (PatchTool) -> None

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -8,20 +8,2 @@
                   "locked_requirements": [
            -        {
            -          "artifacts": [
            -            {
            -              "algorithm": "md5",
            -              "hash": "f357aa02db2466bc24ff1815cff1aeb3",
            -              "url": "http://localhost:9999/ansicolors-1.1.8-py2.py3-none-any.whl"
            -            },
            -            {
            -              "algorithm": "md5",
            -              "hash": "9ca7e2396ffa2e20af023c6b83ab7b14",
            -              "url": "http://localhost:9999/ansicolors-1.1.8.zip"
            -            }
            -          ],
            -          "project_name": "ansicolors",
            -          "requirement": "ansicolors",
            -          "version": "1.1.8",
            -          "via": []
            -        }
                   ],
            """
        ),
        match=re.escape(
            "Expected '.locked_resolves[0][\"locked_requirements\"]' in <string> to have at least "
            "one locked requirement."
        ),
    )


def test_load_invalid_no_locked_resolves(patch_tool):
    # type: (PatchTool) -> None

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -6,29 +6,2 @@
               "locked_resolves": [
            -    {
            -      "locked_requirements": [
            -        {
            -          "artifacts": [
            -            {
            -              "algorithm": "md5",
            -              "hash": "f357aa02db2466bc24ff1815cff1aeb3",
            -              "url": "http://localhost:9999/ansicolors-1.1.8-py2.py3-none-any.whl"
            -            },
            -            {
            -              "algorithm": "md5",
            -              "hash": "9ca7e2396ffa2e20af023c6b83ab7b14",
            -              "url": "http://localhost:9999/ansicolors-1.1.8.zip"
            -            }
            -          ],
            -          "project_name": "ansicolors",
            -          "requirement": "ansicolors",
            -          "version": "1.1.8",
            -          "via": []
            -        }
            -      ],
            -      "platform_tag": [
            -        "cp39",
            -        "cp39",
            -        "manylinux_2_33_x86_64"
            -      ]
            -    }
               ],
            """
        ),
        match=re.escape("Expected '.locked_resolves' in <string> to have at least one resolve."),
    )
