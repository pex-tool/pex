# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import re
import subprocess
from textwrap import dedent

import pytest

import pex.resolve.lockfile
from pex.compatibility import PY2
from pex.pep_440 import Version
from pex.pep_503 import ProjectName
from pex.resolve.locked_resolve import Artifact, LockedRequirement, LockedResolve, LockStyle
from pex.resolve.lockfile import Lockfile, json_codec
from pex.resolve.resolved_requirement import Fingerprint, Pin
from pex.resolve.resolver_configuration import ResolverVersion
from pex.sorted_tuple import SortedTuple
from pex.third_party.packaging import tags
from pex.third_party.pkg_resources import Requirement
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    import attr  # vendor:skip
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
        requires_python=(),
        resolver_version=ResolverVersion.PIP_2020,
        requirements=(
            Requirement.parse("ansicolors"),
            Requirement.parse("requests>=2; sys_platform == 'darwin'"),
        ),
        constraints=(Requirement.parse("ansicolors==1.1.8"),),
        allow_prereleases=True,
        allow_wheels=False,
        allow_builds=False,
        prefer_older_binary=False,
        use_pep517=None,
        build_isolation=True,
        transitive=False,
        locked_resolves=[
            LockedResolve(
                platform_tag=tags.Tag("cp36", "cp36m", "macosx_10_13_x86_64"),
                locked_requirements=SortedTuple(
                    [
                        LockedRequirement.create(
                            pin=Pin(
                                project_name=ProjectName("ansicolors"), version=Version("1.1.8")
                            ),
                            artifact=Artifact.from_url(
                                url="https://example.org/colors-1.1.8-cp36-cp36m-macosx_10_6_x86_64.whl",
                                fingerprint=Fingerprint(algorithm="blake256", hash="cafebabe"),
                            ),
                            additional_artifacts=(),
                        ),
                        LockedRequirement.create(
                            pin=Pin(project_name=ProjectName("requests"), version=Version("2.0.0")),
                            artifact=Artifact.from_url(
                                url="https://example.org/requests-2.0.0-py2.py3-none-any.whl",
                                fingerprint=Fingerprint(algorithm="sha256", hash="456"),
                            ),
                            additional_artifacts=(
                                Artifact.from_url(
                                    url="file://find-links/requests-2.0.0.tar.gz",
                                    fingerprint=Fingerprint(algorithm="sha512", hash="123"),
                                ),
                            ),
                        ),
                    ]
                ),
            ),
            LockedResolve(
                platform_tag=tags.Tag("cp37", "cp37m", "manylinux1_x86_64"),
                locked_requirements=SortedTuple(
                    [
                        LockedRequirement.create(
                            pin=Pin(
                                project_name=ProjectName("ansicolors"), version=Version("1.1.8")
                            ),
                            artifact=Artifact.from_url(
                                url="https://example.org/colors-1.1.8-cp37-cp37m-manylinux1_x86_64.whl",
                                fingerprint=Fingerprint(algorithm="md5", hash="hackme"),
                            ),
                            additional_artifacts=(),
                        ),
                    ]
                ),
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
  "build_isolation": true,
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
          "requires_dists": [],
          "requires_python": null,
          "version": "1.1.8"
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
  "prefer_older_binary": false,
  "requirements": [
    "ansicolors"
  ],
  "requires_python": [],
  "resolver_version": "pip-legacy-resolver",
  "style": "sources",
  "transitive": true,
  "use_pep517": null
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
    with pytest.raises(pex.resolve.lockfile.ParseError, match=match):
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
            @@ -38,3 +38,4 @@
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
            @@ -5,3 +5,3 @@
               "build_isolation": true,
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
            @@ -23,3 +23,6 @@
                       "project_name": "ansicolors",
            -          "requires_dists": [],
            +          "requires_dists": [
            +            "valid_requirement",
            +            "@invalid_requirement"
            +          ],
                       "requires_python": null,
            """
        ),
        match=re.escape(
            "The requirement string at '.locked_resolves[0][0][\"requires_dists\"][1]' is invalid:"
        ),
    )


def test_load_invalid_requires_python(patch_tool):
    # type: (PatchTool) -> None

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            --- lock.orig.json	2022-01-23 16:25:23.099399463 -0800
            +++ lock.json	2022-01-23 16:39:35.547488554 -0800
            @@ -24,3 +24,3 @@
                       "requires_dists": [],
            -          "requires_python": null,
            +          "requires_python": "@invalid specifier",
                       "version": "1.1.8"
            """
        ),
        match=re.escape(
            "The version specifier at '.locked_resolves[0][0][\"requires_python\"]' is invalid:"
        ),
    )


def test_load_invalid_resolver_version(patch_tool):
    # type: (PatchTool) -> None

    assert_parse_error(
        patch_tool,
        dedent(
            """\
            @@ -39,3 +39,3 @@
               "requires_python": [],
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
            @@ -41,3 +41,3 @@
               "resolver_version": "pip-legacy-resolver",
            -  "style": "sources",
            +  "style": "foo",
               "transitive": true,
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
