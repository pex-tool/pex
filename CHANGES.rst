Release Notes
=============

1.6.7
-----

We now support reproducible builds when creating a pex via `pex -o foo.pex`, meaning that if
you were to run the command again with the same inputs, the two generated pexes would be
byte-for-byte identical. To enable reproducible builds when building a pex, use the flags
`--no-use-system-time --no-compile`, which will use a deterministic timestamp and not include
`.pyc` files in the Pex.

In Pex 1.7.0, we will default to reproducible builds.

* add delayed pkg_resources import fix from #713, with an integration test (#730)
  `PR #730 <https://github.com/pantsbuild/pex/pull/730>`_

* Fix reproducible builds sdist test by properly requiring building the wheel (#727)
  `PR #727 <https://github.com/pantsbuild/pex/pull/727>`_

* Fix reproducible build test improperly using the -c flag and add a new test for -c flag (#725)
  `PR #725 <https://github.com/pantsbuild/pex/pull/725>`_

* Fix PexInfo requirements using a non-deterministic data structure (#723)
  `PR #723 <https://github.com/pantsbuild/pex/pull/723>`_

* Add new `--no-use-system-time` flag to use a deterministic timestamp in built PEX (#722)
  `PR #722 <https://github.com/pantsbuild/pex/pull/722>`_

* Add timeout when using requests. (#726)
  `PR #726 <https://github.com/pantsbuild/pex/pull/726>`_

* Refactor reproducible build tests to assert that the original pex command succeeded (#724)
  `PR #724 <https://github.com/pantsbuild/pex/pull/724>`_

* Introduce new `--no-compile` flag to not include .pyc in built pex due to its non-determinism (#718)
  `PR #718 <https://github.com/pantsbuild/pex/pull/718>`_

* Document how Pex developers can run specific tests and run Pex from source (#720)
  `PR #720 <https://github.com/pantsbuild/pex/pull/720>`_

* Remove unused bdist_pex.py helper function (#719)
  `PR #719 <https://github.com/pantsbuild/pex/pull/719>`_

* Add failing acceptance tests for reproducible Pex builds (#717)
  `PR #717 <https://github.com/pantsbuild/pex/pull/717>`_

* Make a copy of globals() before updating it. (#715)
  `PR #715 <https://github.com/pantsbuild/pex/pull/715>`_

* Make sure `PexInfo` is isolated from `os.environ`. (#711)
  `PR #711 <https://github.com/pantsbuild/pex/pull/711>`_

* Fix import sorting. (#712)
  `PR #712 <https://github.com/pantsbuild/pex/pull/712>`_

* When iterating over Zipfiles, always use the Unix file separator to fix a Windows issue (#638)
  `PR #638 <https://github.com/pantsbuild/pex/pull/638>`_

* Fix pex file looses the executable permissions of binary files (#703)
  `PR #703 <https://github.com/pantsbuild/pex/pull/703>`_

1.6.6
-----

This is the first release including only a single PEX pex, which
supports execution under all interpreters pex supports.

* Fix pex bootstrap interpreter selection. (#701)
  `PR #701 <https://github.com/pantsbuild/pex/pull/701>`_

* Switch releases to a single multi-pex. (#698)
  `PR #698 <https://github.com/pantsbuild/pex/pull/698>`_

1.6.5
-----

This release fixes long-broken resolution of abi3 wheels.

* Use all compatible versions when calculating tags. (#692)
  `PR #692 <https://github.com/pantsbuild/pants/pull/692>`_

1.6.4
-----

This release un-breaks `lambdex <https://github.com/wickman/lambdex>`_.

* Restore ``pex.pex_bootstrapper.is_compressed`` API. (#685)
  `PR #685 <https://github.com/pantsbuild/pex/pull/685>`_

* Add the version of pex used to build a pex to build_properties. (#687)
  `PR #687 <https://github.com/pantsbuild/pex/pull/687>`_

* Honor interpreter constraints even when PEX_PYTHON and PEX_PYTHON_PATH not set (#668)
  `PR #668 <https://github.com/pantsbuild/pex/pull/668>`_

1.6.3
-----

This release changes the behavior of the ``--interpreter-constraint`` option.
Previously, interpreter constraints were ANDed, which made it impossible to
express constraints like '>=2.7,<3' OR '>=3.6,<4'; ie: either python 2.7 or
else any python 3 release at or above 3.6. Now interpreter constraints are
ORed, which is likely a breaking change if you have scripts that pass multiple
interpreter constraints. To transition, use the native ``,`` AND operator in
your constraint expression, as used in the example above.

* Provide control over pex warning behavior. (#680)
  `PR #680 <https://github.com/pantsbuild/pex/pull/680>`_

* OR interpreter constraints when multiple given (#678)
  `Issue #655 <https://github.com/pantsbuild/pex/issues/655>`_
  `PR #678 <https://github.com/pantsbuild/pex/pull/678>`_

* Pin isort version in CI (#679)
  `PR #679 <https://github.com/pantsbuild/pex/pull/679>`_

* Honor PEX_IGNORE_RCFILES in to_python_interpreter() (#673)
  `PR #673 <https://github.com/pantsbuild/pex/pull/673>`_

* Make `run_pex_command` more robust. (#670)
  `PR #670 <https://github.com/pantsbuild/pex/pull/670>`_

1.6.2
-----

* Support de-vendoring for installs. (#666)
  `PR #666 <https://github.com/pantsbuild/pex/pull/666>`_

* Add User-Agent header when resolving via urllib (#663)
  `PR #663 <https://github.com/pantsbuild/pex/pull/663>`_

* Fix interpreter finding (#662)
  `PR #662 <https://github.com/pantsbuild/pex/pull/662>`_

* Add recipe to use PEX with requests module and proxies. (#659)
  `PR #659 <https://github.com/pantsbuild/pex/pull/659>`_

* Allow pex to be invoked using runpy (python -m pex). (#637)
  `PR #637 <https://github.com/pantsbuild/pex/pull/637>`_

1.6.1
-----

* Make tox -evendor idempotent. (#651)
  `PR #651 <https://github.com/pantsbuild/pex/pull/651>`_

* Fix invalid regex and escape sequences causing DeprecationWarning (#646)
  `PR #646 <https://github.com/pantsbuild/pex/pull/646>`_

* Follow PEP 425 suggestions on distribution preference. (#640)
  `PR #640 <https://github.com/pantsbuild/pex/pull/640>`_

* Setup interpreter extras in InstallerBase. (#635)
  `PR #635 <https://github.com/pantsbuild/pex/pull/635>`_

* Ensure bootstrap demotion is complete. (#634)
  `PR #634 <https://github.com/pantsbuild/pex/pull/634>`_

1.6.0
-----

* Fix pex force local to handle PEP 420. (#613)
  `PR #613 <https://github.com/pantsbuild/pex/pull/613>`_

* Vendor ``setuptools`` and ``wheel``. (#624)
  `PR #624 <https://github.com/pantsbuild/pex/pull/624>`_

1.5.3
-----

* Fixup PEXEnvironment extras resolution. (#617)
  `PR #617 <https://github.com/pantsbuild/pex/pull/617>`_

* Repair unhandled AttributeError during pex bootstrapping. (#599)
  `PR #599 <https://github.com/pantsbuild/pex/pull/599>`_

1.5.2
-----

This release brings an exit code fix for pexes run via entrypoint as well as a fix for finding
scripts when building pexes from wheels with dashes in their distribution name.

* Update PyPI default URL to pypi.org (#610)
  `PR #610 <https://github.com/pantsbuild/pex/pull/610>`_

* Pex exits with correct code when using entrypoint (#605)
  `PR #605 <https://github.com/pantsbuild/pex/pull/605>`_

* Fix \*_custom_setuptools_useable ITs. (#606)
  `PR #606 <https://github.com/pantsbuild/pex/pull/606>`_

* Update pyenv if neccesary (#586)
  `PR #586 <https://github.com/pantsbuild/pex/pull/586>`_

* Fix script search in wheels. (#600)
  `PR #600 <https://github.com/pantsbuild/pex/pull/600>`_

* Small Docstring Fix (#595)
  `PR #595 <https://github.com/pantsbuild/pex/pull/595>`_

1.5.1
-----

This release brings a fix to handle top-level requirements with environment markers, fully
completing environment marker support.

* Filter top-level requirements against env markers. (#592)
  `PR #592 <https://github.com/pantsbuild/pex/pull/592>`_

1.5.0
-----

This release fixes pexes such that they fully support environment markers, the canonical use case
being a python 2/3 pex that needs to conditionally load one or more python 2 backport libs when
running under a python 2 interpreter only.

* Revert "Revert "Support environment markers during pex activation. (#582)""
  `PR #582 <https://github.com/pantsbuild/pex/pull/582>`_

1.4.9
-----

This is a hotfix release for 1.4.8 that fixes a regression in interpreter setup that could lead to
resolved distributions failing to build or install.

* Cleanup `PexInfo` and `PythonInterpreter`. (#581)
  `PR #581 <https://github.com/pantsbuild/pex/pull/581>`_

* Fix resolve regressions introduced by the 1.4.8. (#580)
  `PR #580 <https://github.com/pantsbuild/pex/pull/580>`_

* Narrow the env marker test. (#578)
  `PR #578 <https://github.com/pantsbuild/pex/pull/578>`_

* Documentation for #569 (#574)
  `PR #574 <https://github.com/pantsbuild/pex/pull/574>`_

1.4.8
-----

This release adds support for `-c` and `-m` pexfile runtime options that emulate the behavior of the
same arguments to `python` as well a fix for handling the non-standard platform reported by
setuptools for Apple system interpreters in addition to several other bug fixes.

* Fix PEXBuilder.clone. (#575)
  `PR #575 <https://github.com/pantsbuild/pex/pull/575>`_

* Fix PEXEnvironment platform determination. (#568)
  `PR #568 <https://github.com/pantsbuild/pex/pull/568>`_

* Apply more pinning to jupyter in IT. (#573)
  `PR #573 <https://github.com/pantsbuild/pex/pull/573>`_

* Minimize interpreter bootstrapping in tests. (#571)
  `PR #571 <https://github.com/pantsbuild/pex/pull/571>`_

* Introduce 3.7 to CI and release. (#567)
  `PR #567 <https://github.com/pantsbuild/pex/pull/567>`_

* Add OSX shards. (#565)
  `PR #565 <https://github.com/pantsbuild/pex/pull/565>`_

* Add support for `-m` and `-c` in interpreter mode. (#563)
  `PR #563 <https://github.com/pantsbuild/pex/pull/563>`_

* Ignore concurrent-rename failures. (#558)
  `PR #558 <https://github.com/pantsbuild/pex/pull/558>`_

* Fixup test_jupyter_appnope_env_markers. (#562)
  `PR #562 <https://github.com/pantsbuild/pex/pull/562>`_

1.4.7
-----

This is a hotfix release for a regression in setuptools compatibility introduced by #542.

* Fixup `PEX.demote_bootstrap`: fully unimport. (#554)
  `PR #554 <https://github.com/pantsbuild/pex/pull/554>`_

1.4.6
-----

This release opens up setuptools support for more modern versions that support breaking changes in
`setup` used in the wild.

* Fix for super() usage on "old style class" ZipFile (#546)
  `PR #546 <https://github.com/pantsbuild/pex/pull/546>`_

* Cleanup bootstrap dependencies before handoff. (#542)
  `PR #542 <https://github.com/pantsbuild/pex/pull/542>`_

* Support -c for plat spec dists in multiplat pexes. (#545)
  `PR #545 <https://github.com/pantsbuild/pex/pull/545>`_

* Support `-` when running as an interpreter. (#543)
  `PR #543 <https://github.com/pantsbuild/pex/pull/543>`_

* Expand the range of supported setuptools. (#541)
  `PR #541 <https://github.com/pantsbuild/pex/pull/541>`_

* Preserve perms of files copied to pex chroots. (#540)
  `PR #540 <https://github.com/pantsbuild/pex/pull/540>`_

* Add more badges to README. (#535)
  `PR #535 <https://github.com/pantsbuild/pex/pull/535>`_

* Fixup CHANGES PR links for 1.4.5.

1.4.5
-----

This release adds support for validating pex entrypoints at build time in addition to several bugfixes.

* Fix PEX environment setup. (#531)
  `#531 <https://github.com/pantsbuild/pex/pull/531>`_

* Fix installers to be insensitive to extras iteration order. (#532)
  `#532 <https://github.com/pantsbuild/pex/pull/532>`_

* Validate entry point at build time (#521)
  `#521 <https://github.com/pantsbuild/pex/pull/521>`_

* Fix pex extraction perms. (#528)
  `#528 <https://github.com/pantsbuild/pex/pull/528>`_

* Simplify `.travis.yml`. (#524)
  `#524 <https://github.com/pantsbuild/pex/pull/524>`_

* Fix `PythonInterpreter` caching and ergonomics. (#518)
  `#518 <https://github.com/pantsbuild/pex/pull/518>`_

* Add missing git dep. (#519)
  `#519 <https://github.com/pantsbuild/pex/pull/519>`_

* Introduce a controlled env for pex testing. (#517)
  `#517 <https://github.com/pantsbuild/pex/pull/517>`_

* Bump wheel version to latest. (#515)
  `#515 <https://github.com/pantsbuild/pex/pull/515>`_

* Invoke test runner at a more granular level for pypy shard. (#513)
  `#513 <https://github.com/pantsbuild/pex/pull/513>`_

1.4.4
-----

This release adds support for including sources and resources directly in a produced pex - without the need to use pants.

* Add resource / source bundling to pex cli (#507)
  `#507 <https://github.com/pantsbuild/pex/pull/507>`_

1.4.3
-----

Another bugfix release for the 1.4.x series.

* Repair environmental marker platform setting. (#500)
  `#500 <https://github.com/pantsbuild/pex/pull/500>`_

* Broaden abi selection for non-specified abi types. (#503)
  `#503 <https://github.com/pantsbuild/pex/pull/503>`_

1.4.2
-----

This release repairs a tag matching regression for .egg dists that inadvertently went out in 1.4.1.

* Improve tag generation for EggPackage. (#493)
  `#493 <https://github.com/pantsbuild/pex/pull/493>`_

1.4.1
-----

A bugfix release for 1.4.x.

* Repair abi prefixing for PyPy. (#483)
  `#483 <https://github.com/pantsbuild/pex/pull/483>`_

* Repair .egg resolution for platform specific eggs. (#486)
  `#486 <https://github.com/pantsbuild/pex/pull/486>`_

* Eliminate the python3.3 shard. (#488)
  `#488 <https://github.com/pantsbuild/pex/pull/488>`_

1.4.0
-----

This release includes full Manylinux support, improvements to wheel resolution (including first class platform/abi tag targeting) and a handful of other improvements and bugfixes. Enjoy!

Special thanks to Dan Blanchard (@dan-blanchard) for seeding the initial PR for Manylinux support and wheel resolution improvements.

* Complete manylinux support in pex. (#480)
  `#480 <https://github.com/pantsbuild/pex/pull/480>`_

* Add manylinux wheel support and fix a few bugs along the way (#316)
  `#316 <https://github.com/pantsbuild/pex/pull/316>`_

* Skip failing tests on pypy shard. (#478)
  `#478 <https://github.com/pantsbuild/pex/pull/478>`_

* Bump travis image to Trusty. (#476)
  `#476 <https://github.com/pantsbuild/pex/pull/476>`_

* Mock PATH for problematic interpreter selection test in CI (#474)
  `#474 <https://github.com/pantsbuild/pex/pull/474>`_

* Skip two failing integration tests. (#472)
  `#472 <https://github.com/pantsbuild/pex/pull/472>`_

* Better error handling for missing setuptools. (#471)
  `#471 <https://github.com/pantsbuild/pex/pull/471>`_

* Add tracebacks to IntegResults. (#469)
  `#469 <https://github.com/pantsbuild/pex/pull/469>`_

* Fix failing tests in master (#466)
  `#466 <https://github.com/pantsbuild/pex/pull/466>`_

* Repair isort-check failure in master. (#465)
  `#465 <https://github.com/pantsbuild/pex/pull/465>`_

* Repair style issues in master. (#464)
  `#464 <https://github.com/pantsbuild/pex/pull/464>`_

* Fixup PATH handling in travis.yml. (#462)
  `#462 <https://github.com/pantsbuild/pex/pull/462>`_

1.3.2
-----

* Add blacklist handling for skipping requirements in pex resolver #457
  `#457 <https://github.com/pantsbuild/pex/pull/457>`_

1.3.1
-----

This is a bugfix release for a regression that inadvertently went out in 1.3.0.

* scrub path when not inheriting (#449)
  `#449 <https://github.com/pantsbuild/pex/pull/449>`_

* Fix up inherits_path tests to use new values (#450)
  `#450 <https://github.com/pantsbuild/pex/pull/450>`_

1.3.0
-----

* inherit_path allows 'prefer', 'fallback', 'false' (#444)
  `#444 <https://github.com/pantsbuild/pex/pull/444>`_

1.2.16
------

* Change PEX re-exec variable from ENV to os.environ (#441)
  `#441 <https://github.com/pantsbuild/pex/pull/441>`_

1.2.15
------

* Bugfix for entry point targeting + integration test (#435)
  `#435 <https://github.com/pantsbuild/pex/pull/435>`_

1.2.14
------

* Add interpreter constraints option and use constraints to search for compatible interpreters at exec time (#427)
  `#427 <https://github.com/pantsbuild/pex/pull/427>`_

1.2.13
------

* Fix handling of pre-release option. (#424)
  `#424 <https://github.com/pantsbuild/pex/pull/424>`_

* Patch sys module using pex_path from PEX-INFO metadata (#421)
  `#421 <https://github.com/pantsbuild/pex/pull/421>`_

1.2.12
------

* Create --pex-path argument for pex cli and load pex path into pex-info metadata (#417)
  `#417 <https://github.com/pantsbuild/pex/pull/417>`_

1.2.11
------

* Leverage `subprocess32` when available. (#411)
  `#411 <https://github.com/pantsbuild/pex/pull/411>`_

* Kill support for python 2.6. (#408)
  `#405 <https://github.com/pantsbuild/pex/issues/405>`_
  `#408 <https://github.com/pantsbuild/pex/pull/408>`_

1.2.10
------

* Allow passing a preamble file to the CLI (#400)
  `#400 <https://github.com/pantsbuild/pex/pull/400>`_

1.2.9
-----

* Add first-class support for multi-interpreter and multi-platform pex construction. (#394)
  `#394 <https://github.com/pantsbuild/pex/pull/394>`_

1.2.8
-----

* Minimum setuptools version should be 20.3 (#391)
  `#391 <https://github.com/pantsbuild/pex/pull/391>`_

* Improve wheel support in pex. (#388)
  `#388 <https://github.com/pantsbuild/pex/pull/388>`_

1.2.7
-----

* Sort keys in PEX-INFO file so the output is deterministic. (#384)
  `#384 <https://github.com/pantsbuild/pex/pull/384>`_

* Pass platform for SourceTranslator (#386)
  `#386 <https://github.com/pantsbuild/pex/pull/386>`_

1.2.6
-----

* Fix for Ambiguous Resolvable bug in transitive dependency resolution (#367)
  `#367 <https://github.com/pantsbuild/pex/pull/367>`_

1.2.5
-----

This release follows-up on 1.2.0 fixing bugs in the pre-release resolving code paths.

* Resolving pre-release when explicitly requested (#372)
  `#374 <https://github.com/pantsbuild/pex/pull/374>`_

* Pass allow_prerelease to other iterators (Static, Caching) (#373)
  `#373 <https://github.com/pantsbuild/pex/pull/373>`_

1.2.4
-----

* Fix bug in cached dependency resolution with exact resolvable. (#365)
  `#365 <https://github.com/pantsbuild/pex/pull/365>`_

* Treat .pth injected paths as extras. (#370)
  `#370 <https://github.com/pantsbuild/pex/pull/370>`_

1.2.3
-----

* Follow redirects on HTTP requests (#361)
  `#361 <https://github.com/pantsbuild/pex/pull/361>`_

* Fix corner case in cached dependency resolution (#362)
  `#362 <https://github.com/pantsbuild/pex/pull/362>`_

1.2.2
-----

* Fix CacheControl import. (#357)
  `#357 <https://github.com/pantsbuild/pex/pull/357>`_

1.2.1
-----

This release is a quick fix for a bootstrapping bug that inadvertently went out in 1.2.0 (Issue
#354).

* Ensure `packaging` dependency is self-contained. (#355)
  `#355 <https://github.com/pantsbuild/pex/pull/355>`_
  `Fixes #354 <https://github.com/pantsbuild/pex/issues/354>`_

1.2.0
-----

This release changes pex requirement resolution behavior. Only stable requirements are resolved by
default now. The previous behavior that included pre-releases can be retained by passing `--pre` on
the pex command line or passing `allow_prereleases=True` via the API.

* Upgrade dependencies to modern version ranges. (#352)
  `#352 <https://github.com/pantsbuild/pex/pull/352>`_

* Add support for controlling prerelease resolution. (#350)
  `#350 <https://github.com/pantsbuild/pex/pull/350>`_
  `Fixes #28 <https://github.com/pantsbuild/pex/issues/28>`_

1.1.20
------

* Add dummy flush method for clean interpreter exit with python3.6 (#343)
  `#343 <https://github.com/pantsbuild/pex/pull/343>`_

1.1.19
------

* Implement --constraints in pex (#335)
  `#335 <https://github.com/pantsbuild/pex/pull/335>`_

* Make sure namespace packages (e.g. virtualenvwrapper) don't break pex (#338)
  `#338 <https://github.com/pantsbuild/pex/pull/338>`_

1.1.18
------

* Expose a PEX instance's path. (#332)
  `#332 <https://github.com/pantsbuild/pex/pull/332>`_

* Check for scripts directory in get_script_from_egg (#328)
  `#328 <https://github.com/pantsbuild/pex/pull/328>`_

1.1.17
------

* Make PEX_PATH unify pex sources, as well as requirements. (#329)
  `#329 <https://github.com/pantsbuild/pex/pull/329>`_

1.1.16
------

* Adjust FileFinder import to work with Python 3.6. (#318)
  `#318 <https://github.com/pantsbuild/pex/pull/318>`_

* Kill zipmanifest monkeypatching. (#322)
  `#322 <https://github.com/pantsbuild/pex/pull/322>`_

* Bump setuptools range to latest. (#323)
  `#323 <https://github.com/pantsbuild/pex/pull/323>`_

1.1.15
------

* Fix #309 by deduplicating output of the distribution finder. (#310)
  `#310 <https://github.com/pantsbuild/pex/pull/310>`_

* Update wheel dependency to >0.26.0. (#304)
  `#304 <https://github.com/pantsbuild/pex/pull/304>`_

1.1.14
------

* Repair Executor error handling for other classes of IOError/OSError. (#292)
  `#292 <https://github.com/pantsbuild/pex/pull/292>`_

* Fix bdist_pex --pex-args. (#285)
  `#285 <https://github.com/pantsbuild/pex/pull/285>`_

* Inherit user site with --inherit-path. (#284)
  `#284 <https://github.com/pantsbuild/pex/pull/284>`_

1.1.13
------

* Repair passing of stdio kwargs to PEX.run(). (#288)
  `#288 <https://github.com/pantsbuild/pex/pull/288>`_

1.1.12
------

* Fix bdist_pex interpreter cache directory. (#286)
  `#286 <https://github.com/pantsbuild/pex/pull/286>`_

* Normalize and edify subprocess execution. (#255)
  `#255 <https://github.com/pantsbuild/pex/pull/255>`_

* Don't ignore exit codes when using setuptools entry points. (#280)
  `#280 <https://github.com/pantsbuild/pex/pull/280>`_
  `Fixes #137 <https://github.com/pantsbuild/pex/issues/137>`_

1.1.11
------

* Update cache dir when bdist_pex.run is called directly.
  `#278 <https://github.com/pantsbuild/pex/pull/278>`_
  `Fixes #274 <https://github.com/pantsbuild/pex/issues/274>`_

1.1.10
------

* Improve failure modes for os.rename() as used in distribution caching.
  `#271 <https://github.com/pantsbuild/pex/pull/271>`_
  `Fixes #265 <https://github.com/pantsbuild/pex/issues/265>`_

1.1.9
-----

* Bugfix: Open setup.py in binary mode.
  `#264 <https://github.com/pantsbuild/pex/pull/264>`_
  `Fixes #263 <https://github.com/pantsbuild/pex/issues/263>`_

1.1.8
-----

* Bugfix: Repair a regression in `--disable-cache`.
  `#261 <https://github.com/pantsbuild/pex/pull/261>`_
  `Fixes #260 <https://github.com/pantsbuild/pex/issues/260>`_

1.1.7
-----

* Add README and supported python versions to PyPI description.
  `#258 <https://github.com/pantsbuild/pex/pull/258>`_

* Use `open` with utf-8 support.
  `#231 <https://github.com/pantsbuild/pex/pull/231>`_

* Add `--pex-root` option.
  `#206 <https://github.com/pantsbuild/pex/pull/206>`_

1.1.6
-----

This release is a quick fix for a regression that inadvertently went out in 1.1.5 (Issue #243).

* Fix the ``bdist_pex`` ``setuptools`` command to work for python2.
  `#246 <https://github.com/pantsbuild/pex/pull/246>`_
  `Fixes #243 <https://github.com/pantsbuild/pex/issues/243>`_

* Upgrade pex dependencies on ``setuptools`` and ``wheel``.
  `#244 <https://github.com/pantsbuild/pex/pull/244>`_
  `Fixes #238 <https://github.com/pantsbuild/pex/issues/238>`_

1.1.5
-----

* Fix ``PEXBuilder.clone`` and thus ``bdist_pex --pex-args`` for ``--python`` and ``--python-shebang``.
  `#234 <https://github.com/pantsbuild/pex/pull/234>`_
  `Fixes #233 <https://github.com/pantsbuild/pex/issues/233>`_

* Fix old ``pkg_resources`` egg version normalization.
  `#227 <https://github.com/pantsbuild/pex/pull/227>`_
  `Fixes #226 <https://github.com/pantsbuild/pex/issues/226>`_

* Fix the ``inherit_path`` handling.
  `#224 <https://github.com/pantsbuild/pex/pull/224>`_

* Fix handling of bad distribution script names when used as the pex entrypoint.
  `#221 <https://github.com/pantsbuild/pex/issues/221>`_
  `Fixes #220 <https://github.com/pantsbuild/pex/issues/220>`_

1.1.4
-----

This release is a quick fix for a regression that inadvertently went out in 1.1.3 (Issue #216).

* Add a test for the regression in ``FixedEggMetadata._zipinfo_name`` and revert the breaking commit.
  `Fixes #216 <https://github.com/pantsbuild/pex/issues/216>`_

1.1.3
-----

This release includes an initial body of work towards Windows support, ABI tag support for CPython 2.x and a fix for version number normalization.

* Add python 2.x abi tag support.
  `#214 <https://github.com/pantsbuild/pex/pull/214>`_
  `Fixes #213 <https://github.com/pantsbuild/pex/issues/213>`_

* Add .idea to .gitignore.
  `#205 <https://github.com/pantsbuild/pex/pull/205>`_

* Don't normalize version numbers as names.
  `#204 <https://github.com/pantsbuild/pex/pull/204>`_

* More fixes for windows.
  `#202 <https://github.com/pantsbuild/pex/pull/202>`_

* Fixes to get pex to work on windows.
  `#198 <https://github.com/pantsbuild/pex/pull/198>`_

1.1.2
-----

* Bump setuptools & wheel version pinning.
  `#194 <https://github.com/pantsbuild/pex/pull/194>`_

* Unescape html in PageParser.href_match_to_url.
  `#191 <https://github.com/pantsbuild/pex/pull/191>`_

* Memoize calls to Crawler.crawl() for performance win in find-links based resolution.
  `#187 <https://github.com/pantsbuild/pex/pull/187>`_

1.1.1
-----

* Fix infinite recursion when ``PEX_PYTHON`` points at a symlink.
  `#182 <https://github.com/pantsbuild/pex/pull/182>`_

* Add ``/etc/pexrc`` to the list of pexrc locations to check.
  `#183 <https://github.com/pantsbuild/pex/pull/183>`_

* Improve error messaging for platform constrained Untranslateable errors.
  `#179 <https://github.com/pantsbuild/pex/pull/179>`_

1.1.0
-----

* Add support for ``.pexrc`` files for influencing the pex environment. See the notes `here
  <https://github.com/pantsbuild/pex/blob/master/docs/buildingpex.rst#tailoring-pex-execution-at-build-time>`_.
  `#128 <https://github.com/pantsbuild/pex/pull/128>`_.

* Bug fix: PEX_PROFILE_FILENAME and PEX_PROFILE_SORT were not respected.
  `#154 <https://github.com/pantsbuild/pex/issues/154>`_.

* Adds the ``bdist_pex`` command to setuptools.
  `#99 <https://github.com/pantsbuild/pex/issues/99>`_.

* Bug fix: We did not normalize package names in ``ResolvableSet``, so it was possible to depend on
  ``sphinx`` and ``Sphinx-1.4a0.tar.gz`` and get two versions build and included into the pex.
  `#147 <https://github.com/pantsbuild/pex/issues/147>`_.

* Adds a pex-identifying User-Agent. `#101 <https://github.com/pantsbuild/pex/issues/101>`_.

1.0.3
-----

* Bug fix: Accommodate OSX ``Python`` python binaries.  Previously the OSX python distributions shipped
  with OSX, XCode and available via https://www.python.org/downloads/ could fail to be detected using
  the ``PythonInterpreter`` class.
  Fixes `#144 <https://github.com/pantsbuild/pex/issues/144>`_.

* Bug fix: PEX_SCRIPT failed when the script was from a not-zip-safe egg.
  Original PR `#139 <https://github.com/pantsbuild/pex/pull/139>`_.

* Bug fix: ``sys.exit`` called without arguments would cause `None` to be printed on stderr since pex 1.0.1.
  `#143 <https://github.com/pantsbuild/pex/pull/143>`_.

1.0.2
-----

* Bug fix: PEX-INFO values were overridden by environment ``Variables`` with default values that were
  not explicitly set in the environment.
  Fixes `#135 <https://github.com/pantsbuild/pex/issues/135>`_.

* Bug fix: Since `69649c1 <https://github.com/pantsbuild/pex/commit/69649c1>`_ we have been unpatching
  the side-effects of ``sys.modules`` after ``PEX.execute``.  This takes all modules imported during
  the PEX lifecycle and sets all their attributes to ``None``.  Unfortunately, ``sys.excepthook``,
  ``atexit`` and ``__del__`` may still try to operate using these tainted modules, causing exceptions
  on interpreter teardown.  This reverts just the ``sys`` unpatching so that the abovementioned
  teardown hooks behave more predictably.
  Fixes `#141 <https://github.com/pantsbuild/pex/issues/141>`_.

1.0.1
-----

* Allow PEXBuilder to optionally copy files into the PEX environment instead of hard-linking them.

* Allow PEXBuilder to optionally skip precompilation of .py files into .pyc files.

* Bug fix: PEXBuilder did not respect the target interpreter when compiling source to bytecode.
  Fixes `#127 <https://github.com/pantsbuild/pex/issues/127>`_.

* Bug fix: Fix complex resolutions when using a cache.
  Fixes: `#120 <https://github.com/pantsbuild/pex/issues/120>`_.

1.0.0
-----

The 1.0.0 release of pex introduces a few breaking changes: ``pex -r`` now takes requirements.txt files
instead of requirement specs, ``pex -s`` has now been removed since source specs are accepted as arguments,
and ``pex -p`` has been removed in favor of its alias ``pex -o``.

The pex *command line interface* now adheres to semver insofar as backwards incompatible CLI
changes will invoke a major version change.  Any backwards incompatible changes to the PEX
environment variable semantics will also result in a major version change.  The pex *API* adheres
to semver insofar as backwards incompatible API changes will invoke minor version changes.

For users of the PEX API, it is recommended to add minor version ranges, e.g. ``pex>=1.0,<1.1``.
For users of the PEX CLI, major version ranges such as ``pex>=1,<2`` should be sufficient.

* BREAKING CHANGE: Removes the ``-s`` option in favor of specifying directories directly as
  arguments to the pex command line.

* BREAKING CHANGE: ``pex -r`` now takes requirements.txt filenames and *not* requirement
  specs.  Requirement specs are now passed as arguments to the pex tool.  Use ``--`` to escape
  command line arguments passed to interpreters spawned by pex.  Implements
  `#5 <https://github.com/pantsbuild/pex/issues/5>`_.

* Adds a number of flag aliases to be more compatible with pip command lines: ``--no-index``,
  ``-f``, ``--find-links``, ``--index-url``, ``--no-use-wheel``.  Removes ``-p`` in favor of
  ``-o`` exclusively.

* Adds ``--python-shebang`` option to the pex tool in order to set the ``#!`` shebang to an exact
  path.  `#53 <https://github.com/pantsbuild/pex/issues/53>`_.

* Adds support for ``PEX_PYTHON`` environment variable which will cause the pex file to reinvoke
  itself using the interpreter specified, e.g. ``PEX_PYTHON=python3.4`` or
  ``PEX_PYTHON=/exact/path/to/interpreter``.  `#27 <https://github.com/pantsbuild/pex/issues/27>`_.

* Adds support for ``PEX_PATH`` environment variable which allows merging of PEX environments at
  runtime.  This can be used to inject plugins or entry_points or modules from one PEX into
  another without explicitly building them together. `#30 <https://github.com/pantsbuild/pex/issues/30>`_.

* Consolidates documentation of ``PEX_`` environment variables and adds the ``--help-variables`` option
  to the pex client.  Partially addresses `#13 <https://github.com/pantsbuild/pex/issues/13>`_.

* Adds helper method to dump a package subdirectory onto disk from within a zipped PEX file.  This
  can be useful for applications that know they're running within a PEX and would prefer some
  static assets dumped to disk instead of running as an unzipped PEX file.
  `#12 <https://github.com/pantsbuild/pex/pull/12>`_.

* Now supports extras for static URLs and installable directories.
  `#65 <https://github.com/pantsbuild/pex/issues/65>`_.

* Adds ``-m`` and ``--entry-point`` alias to the existing ``-e`` option for entry points in
  the pex tool to evoke the similarity to ``python -m``.

* Adds console script support via ``-c/--script/--console-script`` and ``PEX_SCRIPT``.  This allows
  you to reference the named entry point instead of the exact ``module:name`` pair.  Also supports
  scripts defined in the ``scripts`` section of setup.py.
  `#59 <https://github.com/pantsbuild/pex/issues/59>`_.

* Adds more debugging information when encountering unresolvable requirements.
  `#79 <https://github.com/pantsbuild/pex/issues/79>`_.

* Bug fix: ``PEX_COVERAGE`` and ``PEX_PROFILE`` did not function correctly when SystemExit was raised.
  Fixes `#81 <https://github.com/pantsbuild/pex/issues/81>`_.

* Bug fix: Fixes caching in the PEX tool since we don't cache the source distributions of installable
  directories.  `#24 <https://github.com/pantsbuild/pex/issues/24>`_.

0.9.0
-----

This is the last release before the 1.0.0 development branch is started.

* Change the setuptools range to >=2.2,<16 by handling EntryPoint changes as well as
  being flexible on whether ``pkg_resources`` is a package or a module.  Fixes
  `#55 <https://github.com/pantsbuild/pex/issues/55>`_ and
  `#34 <https://github.com/pantsbuild/pex/issues/34>`_.

* Adds option groups to the pex tool to make the help output slightly more readable.

* Bug fix: Make ``pip install pex`` work better by removing ``extras_requires`` on the
  ``console_script`` entry point.  Fixes `#48 <https://github.com/pantsbuild/pex/issues/48>`_

* New feature: Adds an interpreter cache to the ``pex`` tool.  If the user does not explicitly
  disable the wheel feature and attempts to build a pex with wheels but does not have the wheel
  package installed, pex will download it in order to make the feature work.
  Implements `#47 <https://github.com/pantsbuild/pex/issues/47>`_ in order to
  fix `#48 <https://github.com/pantsbuild/pex/issues/48>`_

0.8.6
-----

* Bug fix: Honor installed sys.excepthook in pex teardown.
  `RB #1733 <https://rbcommons.com/s/twitter/r/1733>`_

* Bug fix: ``UrllibContext`` used ``replace`` as a keyword argument for ``bytes.decode``
  but this only works on Python 3.  `Pull Request #46 <https://github.com/pantsbuild/pex/pull/46>`_

0.8.5
-----

* Bug fix: Fixup string formatting in pex/bin/pex.py to support Python 2.6
  `Pull Request #40 <https://github.com/pantsbuild/pex/pull/40>`_

0.8.4
-----

* Performance improvement: Speed up the best-case scenario of dependency resolution.
  `RB #1685 <https://rbcommons.com/s/twitter/r/1685>`_

* Bug fix: Change from ``uuid4().get_hex()`` to ``uuid4().hex`` to maintain Python3
  compatibility of pex.common.
  `Pull Request #39 <https://github.com/pantsbuild/pex/pull/39>`_

* Bug fix: Actually cache the results of translation.  Previously bdist translations
  would be created in a temporary directory even if a cache location was specified.
  `RB #1666 <https://rbcommons.com/s/twitter/r/1666>`_

* Bug fix: Support all potential abi tag permutations when determining platform
  compatibility.
  `Pull Request #33 <https://github.com/pantsbuild/pex/pull/33>`_

0.8.3
-----

* Performance improvement: Don't always write packages to disk if they've already been
  cached.  This can significantly speed up launching PEX files with a large
  number of non-zip-safe dependencies.
  `RB #1642 <https://rbcommons.com/s/twitter/r/1642>`_

0.8.2
-----

* Bug fix: Allow pex 0.8.x to parse pex files produced by earlier versions of
  pex and twitter.common.python.

* Pin pex to setuptools prior to 9.x until we have a chance to make changes
  related to PEP440 and the change of pkg_resources.py to a package.

0.8.1
-----

* Bug fix: Fix issue where it'd be possible to ``os.path.getmtime`` on a remote ``Link`` object
  `Issue #29 <https://github.com/pantsbuild/pex/issues/29>`_

0.8.0
-----

* *API change*: Decouple translation from package iteration.  This removes
  the Obtainer construct entirely, which likely means if you're using PEX as
  a library, you will need to change your code if you were doing anything
  nontrivial.  This adds a couple new options to ``resolve`` but simplifies
  the story around how to cache packages.
  `RB #785 <https://rbcommons.com/s/twitter/r/785/>`_

* Refactor http handling in pex to allow for alternate http implementations.  Adds support
  for `requests <https://github.com/kennethreitz/requests>`_,
  improving both performance and security.   For more information, read the commit notes at
  `91c7f32 <https://github.com/pantsbuild/pex/commit/91c7f324085c18af714d35947b603a5f60aeb682>`_.
  `RB #778 <https://rbcommons.com/s/twitter/r/778/>`_

* Improvements to API documentation throughout.

* Renamed ``Tracer`` to ``TraceLogger`` to prevent nondeterministic isort ordering.

* Refactor tox.ini to increase the number of environment combinations and improve coverage.

* Adds HTTP retry support for the RequestsContext.
  `RB #1303 <https://rbcommons.com/s/twitter/r/1303/>`_

* Make pex --version correct.
  `Issue #19 <https://github.com/pantsbuild/pex/issues/19>`_

* Bug fix: Fix over-aggressive sys.modules scrubbing for namespace packages.  Under
  certain circumstances, namespace packages in site-packages could conflict with packages
  within a PEX, causing them to fail importing.
  `RB #1378 <https://rbcommons.com/s/twitter/r/1378/>`_

* Bug fix: Replace uses of ``os.unsetenv(...)`` with ``del os.environ[...]``
  `Pull Request #11 <https://github.com/pantsbuild/pex/pull/11>`_

* Bug fix: Scrub sys.path and sys.modules based upon both supplied path and
  realpath of files and directories.  Newer versions of virtualenv on Linux symlink site-packages
  which caused those packages to not be removed from sys.path correctly.
  `Issue #21 <https://github.com/pantsbuild/pex/issues/21>`_

* Bug fix: The pex -s option was not correctly pulling in transitive dependencies.
  `Issue #22 <https://github.com/pantsbuild/pex/issues/22>`_

* Bug fix: Adds ``content`` method to HTTP contexts that does HTML content decoding, fixing
  an encoding issue only experienced when using Python 3.
  `Issue #10 <https://github.com/pantsbuild/pex/issues/10>`_

0.7.0
-----

* Rename ``twitter.common.python`` to ``pex`` and split out from the
  `twitter/commons <http://github.com/twitter/commons>`_ repo.

0.6.0
-----

* Change the interpretation of ``-i`` (and of PyPIFetcher's pypi_base)
  to match pip's ``-i``.  This is useful for compatibility with devpi.

0.5.10
------

* Ensures that .egg/.whl distributions on disk have their mtime updated
  even though we no longer overwrite them. This gives them a new time
  lease against their ttl.

  Without this change, once a distribution aged past the ttl it would
  never be used again, and builds would re-create the same distributions
  in tmpdirs over and over again.

0.5.9
-----

* Fixes an issue where SourceTranslator would overwrite .egg/.whl
  distributions already on disk.  Instead it should always check to see if
  a copy already exists and reuse if there.

  This ordinarily should not be a problem but the zipimporter caches
  metadata by filename instead of stat/sha, so if the underlying contents
  changed a runtime error would be thrown due to seemingly corrupt zip file
  offsets. `RB #684 <https://rbcommons.com/s/twitter/r/684/>`_

0.5.8
-----

* Adds ``-i/--index`` option to the pex tool.

0.5.7
-----

* Adds ``twitter.common.python.pex_bootstrap`` ``bootstrap_pex_env`` function in
  order to initialize a PEX environment from within a python interpreter.
  (Patch contributed by @kwlzn)

* Adds stdin=,stdout=,stderr= keyword parameters to the ``PEX.run`` function.
  (Patch from @benjy)

0.5.6
-----

* The crawler now defaults to not follow links for security reasons.
  (Before the default behavior was to implicitly ``--follow-links`` for all
  requirements.) `RB #293 <https://rbcommons.com/s/twitter/r/293/>`_

0.5.5
-----

* Improves scrubbing of site-packages from PEX environments.
  `RB #289 <https://rbcommons.com/s/twitter/r/289/>`_

0.5.1 - 0.5.4
-------------

* Silences exceptions reported during interpreter teardown (the exceptions
  resulting from incorrect atexit handler behavior) introduced by 0.4.3
  `RB #253 <https://rbcommons.com/s/twitter/r/253/>`_
  `RB #249 <https://rbcommons.com/s/twitter/r/249/>`_

* Adds ``__hash__`` to ``Link`` so that Packages are hashed correctly in
  ``twitter.common.python.resolver`` ``resolve``

0.5.0
-----

* Adds wheel support to ``twitter.common.python``
  `RB #94 <https://rbcommons.com/s/twitter/r/94/>`_
  `RB #154 <https://rbcommons.com/s/twitter/r/154/>`_
  `RB #148 <https://rbcommons.com/s/twitter/r/148/>`_

0.4.3
-----

* Adds ``twitter.common.python.finders`` which are additional finders for
  setuptools including:
  - find eggs within a .zip
  - find wheels within a directory
  - find wheels within a .zip
  `RB #86 <https://rbcommons.com/s/twitter/r/86/>`_

* Adds a new Package abstraction by refactoring Link into Link and Package.
  `RB #92 <https://rbcommons.com/s/twitter/r/92/>`_

* Adds support for PEP425 tagging necessary for wheel support.
  `RB #87 <https://rbcommons.com/s/twitter/r/87/>`_

* Improves python environment isolation by correctly scrubbing namespace
  packages injected into module ``__path__`` attributes by nspkg pth files.
  `RB #116 <https://rbcommons.com/s/twitter/r/116/>`_

* Adds ``twitter.common.python.resolver`` ``resolve`` method that handles
  transitive dependency resolution better.  This means that if the
  requirement ``futures==2.1.2`` and an unqualified ``futures>=2`` is pulled in
  transitively, our resolver will correctly resolve futures 2.1.2 instead
  of reporting a VersionConflict if any version newer than 2.1.2 is
  available. `RB #129 <https://rbcommons.com/s/twitter/r/129/>`_

* Factors all ``twitter.common.python`` test helpers into
  ``twitter.common.python.testing``
  `RB #91 <https://rbcommons.com/s/twitter/r/91/>`_

* Bug fix: Fix ``OrderedSet`` atexit exceptions
  `RB #147 <https://rbcommons.com/s/twitter/r/147/>`_

* Bug fix: Fix cross-device symlinking (patch from @benjy)

* Bug fix: Raise a ``RuntimeError`` if we fail to write ``pkg_resources`` into a .pex
  `RB #115 <https://rbcommons.com/s/twitter/r/115/>`_

0.4.2
-----

* Upgrade to ``setuptools>=1``

0.4.1
-----

* ``twitter.common.python`` is no longer a namespace package

0.4.0
-----

* Kill the egg distiller.  We now delegate .egg generation to bdist_egg.
  `RB #55 <https://rbcommons.com/s/twitter/r/55/>`_

0.3.1
-----

* Short-circuit resolving a distribution if a local exact match is found.
  `RB #47 <https://rbcommons.com/s/twitter/r/47/>`_

* Correctly patch the global ``pkg_resources`` ``WorkingSet`` for the lifetime
  of the Python interpreter. `RB #52 <https://rbcommons.com/s/twitter/r/52/>`_

* Fixes a performance regression in setuptools ``build_zipmanifest``
  `Setuptools Issue #154 <https://bitbucket.org/pypa/setuptools/issue/154/build_zipmanifest-results-should-be>`_
  `RB #53 <https://rbcommons.com/s/twitter/r/53/>`_

0.3.0
-----

* Plumb through the ``--zip-safe``, ``--always-write-cache``, ``--ignore-errors``
  and ``--inherit-path`` flags to the pex tool.

* Delete the unused ``PythonDirWrapper`` code.

* Split ``PEXEnvironment`` resolution into ``twitter.common.python.environment``
  and deconflate ``WorkingSet``/``Environment`` state.

* Removes the monkeypatched zipimporter in favor of keeping all eggs
  unzipped within PEX files.  Refactors the PEX dependency cache in
  ``util.py``

* Adds interpreter detection for Jython and PyPy.

* Dependency translation errors should be made uniform.
  (Patch from @johnsirois)

* Adds ``PEX_PROFILE_ENTRIES`` to limit the number of entries reported when
  ``PEX_PROFILE`` is enabled. (Patch from @rgs_)

* Bug fix: Several fixes to error handling in ``twitter.common.python.http``
  (From Marc Abramowitz)

* Bug fix: PEX should not always assume that ``$PATH`` was available.
  (Patch from @jamesbroadhead)

* Bug fix: Filename should be part of the .pex cache key or else multiple
  identical versions will incorrectly resolve (Patch from @tc)

* Bug fix: Executed entry points shouldn't be forced to run in an
  environment with ``__future__`` imports enabled. (Patch from
  @lawson_patrick)

* Bug fix: Detect versionless egg links and fail fast. (Patch from
  @johnsirois.)

* Bug fix: Handle setuptools>=2.1 correctly in the zipimport monkeypatch
  (Patch from @johnsirois.)

0.2.3
-----

* Bug fix: Fix handling of Fetchers with ``file://`` urls.

0.2.2
-----

* Adds the pex tool as a standalone tool.

0.2.1
-----

* Bug fix: Bootstrapped ``twitter.common.python`` should declare ``twitter.common``
  as a namespace package.

0.2.0
-----

* Make ``twitter.common.python`` fully standalone by consolidating
  external dependencies within ``twitter.common.python.common``.

0.1.0
-----

* Initial published version of ``twitter.common.python``.
