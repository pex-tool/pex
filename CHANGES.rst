Release Notes
=============

2.1.59
------

This release adds the boolean option ``--venv-site-packages-copies`` to
control whether ``--venv`` execution mode PEXes create their venv with
copies (hardlinks when possible) or symlinks. It also fixes a bug that
prevented Python 3.10 interpreters from being discovered when
``--interpreter-constraint`` was used.

* Add knob for --venv site-packages symlinking. (#1543)
  `PR #1543 <https://github.com/pantsbuild/pex/pull/1543>`_

* Fix Pex to identify Python 3.10 interpreters. (#1545)
  `PR #1545 <https://github.com/pantsbuild/pex/pull/1545>`_

2.1.58
------

This release fixes a bug handling relative ``--cert`` paths.

* Always pass absolute cert path to Pip. (#1538)
  `PR #1538 <https://github.com/pantsbuild/pex/pull/1538>`_

2.1.57
------

This release brings a few performance improvements and a new `venv`
pex-tools ``--remove`` feature that is useful for creating optimized
container images from PEX files.

* Do not re-hash installed wheels. (#1534)
  `PR #1534 <https://github.com/pantsbuild/pex/pull/1534>`_

* Improve space efficiency of ``--venv`` mode. (#1532)
  `PR #1532 <https://github.com/pantsbuild/pex/pull/1532>`_

* Add venv ``--remove {pex,all}`` option. (#1525)
  `PR #1525 <https://github.com/pantsbuild/pex/pull/1525>`_

2.1.56
------

* Fix wheel install hermeticity. (#1521)
  `PR #1521 <https://github.com/pantsbuild/pex/pull/1521>`_

2.1.55
------

This release brings official support for Python 3.10 as well as fixing
https://pex.readthedocs.io doc generation and fixing help for
``pex-tools`` / ``PEX_TOOLS=1 ./my.pex`` pex tools invocations that have
too few arguments.

* Add official support for Python 3.10 (#1512)
  `PR #1512 <https://github.com/pantsbuild/pex/pull/1512>`_

* Always register global options. (#1511)
  `PR #1511 <https://github.com/pantsbuild/pex/pull/1511>`_

* Fix RTD generation by pinning docutils low. (#1509)
  `PR #1509 <https://github.com/pantsbuild/pex/pull/1509>`_

2.1.54
------

This release fixes a bug in ``--venv`` creation that could mask deeper
errors populating PEX venvs.

* Fix ``--venv`` mode short link creation. (#1505)
  `PR #1505 <https://github.com/pantsbuild/pex/pull/1505>`_

2.1.53
------

This release fixes a bug identifying certain interpreters on macOS
Monterey.

Additionally, Pex has two new features:

#. It now exposes the ``PEX`` environment variable inside running PEXes
   to allow application code to both detect it's running from a PEX and
   determine where that PEX is located.
#. It now supports a ``--prompt`` option in the ``venv`` tool to allow
   for customization of the venv activation prompt.

* Guard against fake interpreters. (#1500)
  `PR #1500 <https://github.com/pantsbuild/pex/pull/1500>`_

* Add support for setting custom venv prompts. (#1499)
  `PR #1499 <https://github.com/pantsbuild/pex/pull/1499>`_

* Introduce the ``PEX`` env var. (#1495)
  `PR #1495 <https://github.com/pantsbuild/pex/pull/1495>`_

2.1.52
------

This release makes a wider array of distributions resolvable for
``--platform`` resolves by inferring the ``platform_machine``
environment marker corresponding to the requested ``--platform``.

* Populate ``platform_machine`` in ``--platform`` resolve. (#1489)
  `PR #1489 <https://github.com/pantsbuild/pex/pull/1489>`_

2.1.51
------

This release fixes both PEX creation and ``--venv`` creation to handle
distributions that contain scripts with non-ascii characters in them
when running in environments with a default encoding that does not
contain those characters under PyPy3, Python 3.5 and Python 3.6.

* Fix non-ascii script shebang re-writing. (#1480)
  `PR #1480 <https://github.com/pantsbuild/pex/pull/1480>`_

2.1.50
------

This is another hotfix of the 2.1.48 release's ``--layout`` feature that
fixes identification of ``--layout zipapp`` PEXes that have had their
execute mode bit turned off. A notable example is the Pex PEX when
downloaded from https://github.com/pantsbuild/pex/releases.

* Fix zipapp layout identification. (#1448)
  `PR #1448 <https://github.com/pantsbuild/pex/pull/1448>`_

2.1.49
------

This is a hotfix release that fixes the new ``--layout {zipapp,packed}``
modes for PEX files with no user code & just third party dependencies
when executed against a ``$PEX_ROOT`` where similar PEXes built with the
old ``--not-zip-safe`` option were were run in the past.

* Avoid re-using old ~/.pex/code/ caches. (#1444)
  `PR #1444 <https://github.com/pantsbuild/pex/pull/1444>`_

2.1.48
------

This releases introduces the ``--layout`` flag for selecting amongst the
traditional zipapp layout as a single PEX zip file and two new directory
tree based formats that may be useful for more sophisticated deployment
sceanrios.

The ``--unzip`` / ``PEX_UNZIP`` toggles for PEX runtime execution are
now the default and deprecated as explicit options as a result. You can
still select the venv runtime execution mode via the
``--venv`` / ``PEX_VENV`` toggles though.

* Remove zipapp execution mode & introduce ``--layout``. (#1438)
  `PR #1438 <https://github.com/pantsbuild/pex/pull/1438>`_

2.1.47
------

This is a hotfix release that fixes a regression for ``--venv`` mode
PEXes introduced in #1410. These PEXes were not creating new venvs when
the PEX was unconstrained and executed with any other interpreter than
the interpreter the venv was first created with.

* Fix ``--venv`` mode venv dir hash. (#1428)
  `PR #1428 <https://github.com/pantsbuild/pex/pull/1428>`_

* Clarify PEX_PYTHON & PEX_PYTHON_PATH interaction. (#1427)
  `PR #1427 <https://github.com/pantsbuild/pex/pull/1427>`_

2.1.46
------

This release improves PEX file build reproducibility and requirement
parsing of environment markers in Pip's proprietary URL format.

Also, the `-c` / `--script` / `--console-script` argument now supports
non-Python distribution scripts.

Finally, new contributor @blag improved the README.

* Fix Pip proprietary URL env marker handling. (#1417)
  `PR #1417 <https://github.com/pantsbuild/pex/pull/1417>`_

* Un-reify installed wheel script shebangs. (#1410)
  `PR #1410 <https://github.com/pantsbuild/pex/pull/1410>`_

* Support deterministic repository extract tool. (#1411)
  `PR #1411 <https://github.com/pantsbuild/pex/pull/1411>`_

* Improve examples and add example subsection titles (#1409)
  `PR #1409 <https://github.com/pantsbuild/pex/pull/1409>`_

* support any scripts specified in `setup(scripts=...)` from setup.py. (#1381)
  `PR #1381 <https://github.com/pantsbuild/pex/pull/1381>`_

2.1.45
------

This is a hotfix release that fixes the ``--bdist-all`` handling in the
``bdist_pex`` distutils command that regressed in 2.1.43 to only create
a bdist for the first discovered entry point.

* Fix --bdist-all handling multiple console_scripts (#1396)
  `PR #1396 <https://github.com/pantsbuild/pex/pull/1396>`_

2.1.44
------

This is a hotfix release that fixes env var collisions (introduced in
the Pex 2.1.43 release by
`PR #1367 <https://github.com/pantsbuild/pex/pull/1367>`_) that could
occur when invoking Pex with environment variables like ``PEX_ROOT``
defined.

* Fix Pip handling of internal env vars. (#1388)
  `PR #1388 <https://github.com/pantsbuild/pex/pull/1388>`_

2.1.43
------

* Fix dist-info metadata discovery. (#1376)
  `PR #1376 <https://github.com/pantsbuild/pex/pull/1376>`_

* Fix ``--platform`` resolve handling of env markers. (#1367)
  `PR #1367 <https://github.com/pantsbuild/pex/pull/1367>`_

* Fix ``--no-manylinux``. (#1365)
  `PR #1365 <https://github.com/pantsbuild/pex/pull/1365>`_

* Allow ``--platform`` resolves for current interpreter. (#1364)
  `PR #1364 <https://github.com/pantsbuild/pex/pull/1364>`_

* Do not suppress pex output in bidst_pex (#1358)
  `PR #1358 <https://github.com/pantsbuild/pex/pull/1358>`_

* Warn for PEX env vars unsupported by venv. (#1354)
  `PR #1354 <https://github.com/pantsbuild/pex/pull/1354>`_

* Fix execution modes. (#1353)
  `PR #1353 <https://github.com/pantsbuild/pex/pull/1353>`_

* Fix Pex emitting warnings about its Pip PEX venv. (#1351)
  `PR #1351 <https://github.com/pantsbuild/pex/pull/1351>`_

* Support more verbose output for interpreter info. (#1347)
  `PR #1347 <https://github.com/pantsbuild/pex/pull/1347>`_

* Fix typo in recipes.rst (#1342)
  `PR #1342 <https://github.com/pantsbuild/pex/pull/1342>`_

2.1.42
------

This release brings a bugfix for macOS interpreters when the
MACOSX_DEPLOYMENT_TARGET sysconfig variable is numeric as well as a fix
that improves Pip execution environment isolation.

* Fix MACOSX_DEPLOYMENT_TARGET handling. (#1338)
  `PR #1338 <https://github.com/pantsbuild/pex/pull/1338>`_

* Better isolate Pip. (#1339)
  `PR #1339 <https://github.com/pantsbuild/pex/pull/1339>`_

2.1.41
------

This release brings a hotfix from @kaos for interpreter identification
on macOS 11.

* Update interpreter.py (#1332)
  `PR #1332 <https://github.com/pantsbuild/pex/pull/1332>`_

2.1.40
------

This release brings proper support for pyenv shim interpreter
identification as well as a bug fix for venv mode.

* Fix Pex venv mode to respect ``--strip-pex-env``. (#1329)
  `PR #1329 <https://github.com/pantsbuild/pex/pull/1329>`_

* Fix pyenv shim identification. (#1325)
  `PR #1325 <https://github.com/pantsbuild/pex/pull/1325>`_

2.1.39
------

A hotfix that fixes a bug present since 2.1.25 that results in infinite
recursion in PEX runtime resolves when handling dependency cycles.

* Guard against cyclic dependency graphs. (#1317)
  `PR #1317 <https://github.com/pantsbuild/pex/pull/1317>`_

2.1.38
------

A hotfix that finishes work started in 2.1.37 by #1304 to align Pip
based resolve results with ``--pex-repository`` based resolve results
for requirements with '.' in their names as allowed by PEP-503.

* Fix PEX direct requirements metadata. (#1312)
  `PR #1312 <https://github.com/pantsbuild/pex/pull/1312>`_

2.1.37
------

* Fix Pex isolation to avoid temporary pyc files. (#1308)
  `PR #1308 <https://github.com/pantsbuild/pex/pull/1308>`_

* Fix --pex-repository requirement canonicalization. (#1304)
  `PR #1304 <https://github.com/pantsbuild/pex/pull/1304>`_

* Spruce up ``pex`` and ``pex-tools`` CLIs with uniform ``-V`` /
  ``--version`` support and default value display in help. (#1301)
  `PR #1301 <https://github.com/pantsbuild/pex/pull/1301>`_

2.1.36
------

This release brings a fix for building sdists with certain macOS
interpreters when creating a PEX file that would then fail to resolve
on PEX startup.

* Add support for ``--seed verbose``. (#1299)
  `PR #1299 <https://github.com/pantsbuild/pex/pull/1299>`_

* Fix bytecode compilation race in PEXBuilder.build. (#1298)
  `PR #1298 <https://github.com/pantsbuild/pex/pull/1298>`_

* Fix wheel building for certain macOS system interpreters. (#1296)
  `PR #1296 <https://github.com/pantsbuild/pex/pull/1296>`_

2.1.35
------

This release hardens a few aspects of `--venv` mode PEXes. An infinite
re-exec loop in venv `pex` scripts is fixed and the `activate` family
of scripts in the venv is fixed.

* Improve resolve error information. (#1287)
  `PR #1287 <https://github.com/pantsbuild/pex/pull/1287>`_

* Ensure venv pex does not enter a re-exec loop. (#1286)
  `PR #1286 <https://github.com/pantsbuild/pex/pull/1286>`_

* Expose Pex tools via a pex-tools console script. (#1279)
  `PR #1279 <https://github.com/pantsbuild/pex/pull/1279>`_

* Fix auto-created `--venv` core scripts. (#1278)
  `PR #1278 <https://github.com/pantsbuild/pex/pull/1278>`_

2.1.34
------

Beyond bugfixes for a few important edge cases, this release includes
new support for @argfiles on the command line from @jjhelmus. These
can be useful to overcome command line length limitations. See:
https://docs.python.org/3/library/argparse.html#fromfile-prefix-chars.

* Allow cli arguments to be specified in a file (#1273)
  `PR #1273 <https://github.com/pantsbuild/pex/pull/1273>`_

* Fix module entrypoints. (#1274)
  `PR #1274 <https://github.com/pantsbuild/pex/pull/1274>`_

* Guard against concurrent re-imports. (#1270)
  `PR #1270 <https://github.com/pantsbuild/pex/pull/1270>`_

* Ensure Pip logs to stderr. (#1268)
  `PR #1268 <https://github.com/pantsbuild/pex/pull/1268>`_

2.1.33
------

* Support console scripts found in the PEX_PATH. (#1265)
  `PR #1265 <https://github.com/pantsbuild/pex/pull/1265>`_

* Fix Requires metadata handling. (#1262)
  `PR #1262 <https://github.com/pantsbuild/pex/pull/1262>`_

* Fix PEX file reproducibility. (#1259)
  `PR #1259 <https://github.com/pantsbuild/pex/pull/1259>`_

* Fix venv script shebang rewriting. (#1260)
  `PR #1260 <https://github.com/pantsbuild/pex/pull/1260>`_

* Introduce the repository PEX_TOOL. (#1256)
  `PR #1256 <https://github.com/pantsbuild/pex/pull/1256>`_

2.1.32
------

This is a hotfix release that fixes ``--venv`` mode shebangs being too long for some Linux
environments.

* Guard against too long ``--venv`` mode shebangs. (#1254)
  `PR #1254 <https://github.com/pantsbuild/pex/pull/1254>`_

2.1.31
------

This release primarily hardens Pex venvs fixing several bugs.

* Fix Pex isolation. (#1250)
  `PR #1250 <https://github.com/pantsbuild/pex/pull/1250>`_

* Support pre-compiling a venv. (#1246)
  `PR #1246 <https://github.com/pantsbuild/pex/pull/1246>`_

* Support venv relocation. (#1247)
  `PR #1247 <https://github.com/pantsbuild/pex/pull/1247>`_

* Fix `--runtime-pex-root` leak in pex bootstrap. (#1244)
  `PR #1244 <https://github.com/pantsbuild/pex/pull/1244>`_

* Support venvs that can outlive their base python. (#1245)
  `PR #1245 <https://github.com/pantsbuild/pex/pull/1245>`_

* Harden Pex interpreter identification. (#1248)
  `PR #1248 <https://github.com/pantsbuild/pex/pull/1248>`_

* The `pex` venv script handles entrypoints like PEX. (#1242)
  `PR #1242 <https://github.com/pantsbuild/pex/pull/1242>`_

* Ensure PEX files aren't symlinked in venv. (#1240)
  `PR #1240 <https://github.com/pantsbuild/pex/pull/1240>`_

* Fix venv pex script for use with multiprocessing. (#1238)
  `PR #1238 <https://github.com/pantsbuild/pex/pull/1238>`_

2.1.30
------

This release fixes another bug in --venv mode when PEX_PATH is exported in the environment.

* Fix --venv mode to respect PEX_PATH. (#1227)
  `PR #1227 <https://github.com/pantsbuild/pex/pull/1227>`_

2.1.29
------

This release fixes bugs in `--unzip` and `--venv` mode PEX file execution and upgrades to the last
release of Pip to support Python 2.7.

* Fix PyPy3 `--venv` mode. (#1221)
  `PR #1221 <https://github.com/pantsbuild/pex/pull/1221>`_

* Make `PexInfo.pex_hash` calculation more robust.  (#1219)
  `PR #1219 <https://github.com/pantsbuild/pex/pull/1219>`_

* Upgrade to Pip 20.3.4 patched. (#1205)
  `PR #1205 <https://github.com/pantsbuild/pex/pull/1205>`_

2.1.28
------

This is another hotfix release to fix incorrect resolve post-processing failing otherwise correct
resolves.

* Pex resolver fails to evaluate markers when post-processing resolves to identify which dists
  satisfy direct requirements. (#1196)
  `PR #1196 <https://github.com/pantsbuild/pex/pull/1196>_`

2.1.27
------

This is another hotfix release to fix a regression in Pex ``--sources-directory`` handling of
relative paths.

* Support relative paths in `Chroot.symlink`. (#1194)
  `PR #1194 <https://github.com/pantsbuild/pex/pull/1194>_`

2.1.26
------

This is a hotfix release that fixes requirement parsing when there is a local file in the CWD with
the same name as the project name of a remote requirement to be resolved.

* Requirement parsing handles local non-dist files. (#1190)
  `PR #1190 <https://github.com/pantsbuild/pex/pull/1190>`_

2.1.25
------

This release brings support for a ``--venv`` execution mode to complement ``--unzip`` and standard
unadorned PEX zip file execution modes. The ``--venv`` execution mode will first install the PEX
file into a virtual environment under ``${PEX_ROOT}/venvs`` and then re-execute itself from there.
This mode of execution allows you to ship your PEXed application as a single zipfile that
automatically installs itself in a venv and runs from there to eliminate all PEX startup overhead
on subsequent runs and work like a "normal" application.

There is also support for a new resolution mode when building PEX files that allows you to use the
results of a previous resolve by specifying it as a ``-pex-repository`` to resolve from. If you have
many applications sharing a requirements.txt / constraints.txt, this can drastically speed up
resolves.

* Improve PEX repository error for local projects. (#1184)
  `PR #1184 <https://github.com/pantsbuild/pex/pull/1184>`_

* Use symlinks to add dists in the Pex CLI. (#1185)
  `PR #1185 <https://github.com/pantsbuild/pex/pull/1185>`_

* Suppress ``pip debug`` warning. (#1183)
  `PR #1183 <https://github.com/pantsbuild/pex/pull/1183>`_

* Support resolving from a PEX file repository. (#1182)
  `PR #1182 <https://github.com/pantsbuild/pex/pull/1182>`_

* PEXEnvironment for a DistributionTarget. (#1178)
  `PR #1178 <https://github.com/pantsbuild/pex/pull/1178>`_

* Fix plumbing of 2020-resolver to Pip. (#1180)
  `PR #1180 <https://github.com/pantsbuild/pex/pull/1180>`_

* Platform can report supported_tags. (#1177)
  `PR #1177 <https://github.com/pantsbuild/pex/pull/1177>`_

* Record original requirements in PEX-INFO. (#1171)
  `PR #1171 <https://github.com/pantsbuild/pex/pull/1171>`_

* Tighten requirements parsing. (#1170)
  `PR #1170 <https://github.com/pantsbuild/pex/pull/1170>`_

* Type BuildAndInstallRequest. (#1169)
  `PR #1169 <https://github.com/pantsbuild/pex/pull/1169>`_

* Type AtomicDirectory. (#1168)
  `PR #1168 <https://github.com/pantsbuild/pex/pull/1168>`_

* Type SpawnedJob. (#1167)
  `PR #1167 <https://github.com/pantsbuild/pex/pull/1167>`_

* Refresh and type OrderedSet. (#1166)
  `PR #1166 <https://github.com/pantsbuild/pex/pull/1166>`_

* PEXEnvironment recursive runtime resolve. (#1165)
  `PR #1165 <https://github.com/pantsbuild/pex/pull/1165>`_

* Add support for -r / --constraints URL to the CLI. (#1163)
  `PR #1163 <https://github.com/pantsbuild/pex/pull/1163>`_

* Surface Pip dependency conflict information. (#1162)
  `Issue #9420 <https://github.com/pypa/pip/issues/9420>`_
  `PR #1162 <https://github.com/pantsbuild/pex/pull/1162>`_

* Add support for parsing extras and specifiers. (#1161)
  `PR #1161 <https://github.com/pantsbuild/pex/pull/1161>`_

* Support project_name_and_version metadata. (#1160)
  `PR #1160 <https://github.com/pantsbuild/pex/pull/1160>`_

* docs: fix simple typo, orignal -> original (#1156)
  `PR #1156 <https://github.com/pantsbuild/pex/pull/1156>`_

* Support a --venv mode similar to --unzip mode. (#1153)
  `PR #1153 <https://github.com/pantsbuild/pex/pull/1153>`_

* Remove redundant dep edge label info. (#1152)
  `PR #1152 <https://github.com/pantsbuild/pex/pull/1152>`_

* Remove our reliance on packaging's LegacyVersion. (#1151)
  `PR #1151 <https://github.com/pantsbuild/pex/pull/1151>`_

* Implement PEX_INTERPRETER special mode support. (#1149)
  `PR #1149 <https://github.com/pantsbuild/pex/pull/1149>`_

* Fix PexInfo.copy. (#1148)
  `PR #1148 <https://github.com/pantsbuild/pex/pull/1148>`_

2.1.24
------

This release upgrades Pip to 20.3.3 + a patch to fix Pex resolves using
the ``pip-legacy-resolver`` and ``--constraints``. The Pex package is
also fixed to install for Python 3.9.1+.

* Upgrade to a patched Pip 20.3.3. (#1143)
  `Issue #9283 <https://github.com/pypa/pip/issues/9283>`_
  `PR #1143 <https://github.com/pantsbuild/pex/pull/1143>`_

* Fix python requirement to include full 3.9 series. (#1142)
  `PR #1142 <https://github.com/pantsbuild/pex/pull/1142>`_

2.1.23
------

This release upgrades Pex to the latest Pip which includes support for
the new 2020-resolver (see:
https://pip.pypa.io/en/stable/user_guide/#resolver-changes-2020) as well
as support for macOS BigSur. Although this release defaults to the
legacy resolver behavior, the next release will deprecate the legacy
resolver and support for the legacy resolver will later be removed to
allow continuing Pip upgrades going forward. To switch to the new
resolver, use: `--resolver-version pip-2020-resolver`.

* Upgrade Pex to Pip 20.3.1. (#1133)
  `PR #1133 <https://github.com/pantsbuild/pex/pull/1133>`_

2.1.22
------

This release fixes a deadlock that could be experienced when building
PEX files in highly concurrent environments in addition to fixing
`pex --help-variables` output.

A new suite of PEX tools is now available in Pex itself and any PEXes
built with the new `--include-tools` option. Use
`PEX_TOOLS=1 pex --help` to find out more about the available tools and
their usage.

Finally, the long deprecated exposure of the Pex APIs through `_pex` has
been removed. To use the Pex APIs you must include pex as a dependency
in your PEX file.

* Add a dependency graph tool. (#1132)
  `PR #1132 <https://github.com/pantsbuild/pex/pull/1132>`_

* Add a venv tool. (#1128)
  `PR #1128 <https://github.com/pantsbuild/pex/pull/1128>`_

* Remove long deprecated support for _pex module. (#1135)
  `PR #1135 <https://github.com/pantsbuild/pex/pull/1135>`_

* Add an interpreter tool. (#1131)
  `PR #1131 <https://github.com/pantsbuild/pex/pull/1131>`_

* Escape venvs unless PEX_INHERIT_PATH is requested. (#1130)
  `PR #1130 <https://github.com/pantsbuild/pex/pull/1130>`_

* Improve `PythonInterpreter` venv support. (#1129)
  `PR #1129 <https://github.com/pantsbuild/pex/pull/1129>`_

* Add support for PEX runtime tools & an info tool. (#1127)
  `PR #1127 <https://github.com/pantsbuild/pex/pull/1127>`_

* Exclusive atomic_directory always unlocks. (#1126)
  `PR #1126 <https://github.com/pantsbuild/pex/pull/1126>`_

* Fix `PythonInterpreter` binary normalization. (#1125)
  `PR #1125 <https://github.com/pantsbuild/pex/pull/1125>`_

* Add a `requires_dists` function. (#1122)
  `PR #1122 <https://github.com/pantsbuild/pex/pull/1122>`_

* Add an `is_exe` helper. (#1123)
  `PR #1123 <https://github.com/pantsbuild/pex/pull/1123>`_

* Fix req parsing for local archives & projects. (#1121)
  `PR #1121 <https://github.com/pantsbuild/pex/pull/1121>`_

* Improve PEXEnvironment constructor ergonomics. (#1120)
  `PR #1120 <https://github.com/pantsbuild/pex/pull/1120>`_

* Fix `safe_open` for single element relative paths. (#1118)
  `PR #1118 <https://github.com/pantsbuild/pex/pull/1118>`_

* Add URLFetcher IT. (#1116)
  `PR #1116 <https://github.com/pantsbuild/pex/pull/1116>`_

* Implement full featured requirment parsing. (#1114)
  `PR #1114 <https://github.com/pantsbuild/pex/pull/1114>`_

* Fix `--help-variables` docs. (#1113)
  `PR #1113 <https://github.com/pantsbuild/pex/pull/1113>`_

* Switch from optparse to argparse. (#1083)
  `PR #1083 <https://github.com/pantsbuild/pex/pull/1083>`_

2.1.21
------

* Fix ``iter_compatible_interpreters`` with ``path``. (#1110)
  `PR #1110 <https://github.com/pantsbuild/pex/pull/1110>`_

* Fix ``Requires-Python`` environment marker mapping. (#1105)
  `PR #1105 <https://github.com/pantsbuild/pex/pull/1105>`_

* Fix spurious ``InstalledDistribution`` env markers. (#1104)
  `PR #1104 <https://github.com/pantsbuild/pex/pull/1104>`_

* Deprecate ``-R``/``--resources-directory``. (#1103)
  `PR #1103 <https://github.com/pantsbuild/pex/pull/1103>`_

* Fix ResourceWarning for unclosed ``/dev/null``. (#1102)
  `PR #1102 <https://github.com/pantsbuild/pex/pull/1102>`_

* Fix runtime vendoring bytecode compilation races. (#1099)
  `PR #1099 <https://github.com/pantsbuild/pex/pull/1099>`_

2.1.20
------

This release improves interpreter discovery to prefer more recent patch versions, e.g. preferring
Python 3.6.10 over 3.6.8.

We recently regained access to the docsite, and https://pex.readthedocs.io/en/latest/ is now
up-to-date.

* Prefer more recent patch versions in interpreter discovery. (#1088)
  `PR #1088 <https://github.com/pantsbuild/pex/pull/1088>`_

* Fix ``--pex-python`` when it's the same as the current interpreter. (#1087)
  `PR #1087 <https://github.com/pantsbuild/pex/pull/1087>`_

* Fix `dir_hash` vs. bytecode compilation races. (#1080)
  `PR #1080 <https://github.com/pantsbuild/pex/pull/1080>`_

* Fix readthedocs doc generation. (#1081)
  `PR #1081 <https://github.com/pantsbuild/pex/pull/1081>`_

2.1.19
------

This release adds the ``--python-path`` option, which allows controlling the
interpreter search paths when building a PEX.

The release also removes ``--use-first-matching-interpreter``, which was a misfeature. If you want to use
fewer interpreters when building a PEX, use more precise values for ``--interpreter-constraint`` and/or
``--python-path``, or use ``--python`` or ``--platform``.

* Add ``--python-path`` to change interpreter search paths when building a PEX. (#1077)
  `PR #1077 <https://github.com/pantsbuild/pex/pull/1077>`_

* Remove ``--use-first-matching-interpreter`` misfeature. (#1076)
  `PR #1076 <https://github.com/pantsbuild/pex/pull/1076>`_

* Encapsulate ``--inherit-path`` handling. (#1072)
  `PR #1072 <https://github.com/pantsbuild/pex/pull/1072>`_

2.1.18
------

This release brings official support for Python 3.9 and adds a new ``--tmpdir`` option to explicitly
control the TMPDIR used by Pex and its subprocesses. The latter is useful when building PEXes in
space-constrained environments in the face of large distributions.

The release also fixes ``--cert`` and ``--client-cert`` so that they work with PEP-518 builds in
addition to fixing bytecode compilation races in highly parallel environments.

* Add a ``--tmpdir`` option to the Pex CLI. (#1068)
  `PR #1068 <https://github.com/pantsbuild/pex/pull/1068>`_

* Honor ``sys.executable`` unless macOS Framework. (#1065)
  `PR #1065 <https://github.com/pantsbuild/pex/pull/1065>`_

* Add Python 3.9 support. (#1064)
  `PR #1064 <https://github.com/pantsbuild/pex/pull/1064>`_

* Fix handling of ``--cert`` and ``--client-cert``. (#1063)
  `PR #1063 <https://github.com/pantsbuild/pex/pull/1063>`_

* Add atomic_directory exclusive mode. (#1062)
  `PR #1062 <https://github.com/pantsbuild/pex/pull/1062>`_

* Fix ``--cert`` for PEP-518 builds. (#1060)
  `PR #1060 <https://github.com/pantsbuild/pex/pull/1060>`_

2.1.17
------

This release fixes a bug in ``--resolve-local-platforms`` handling that made it unusable in 2.1.16
(#1043) as well as fixing a long standing file handle leak (#1050) and a bug when running under
macOS framework builds of Python (#1009).

* Fix `--unzip` performance regression. (#1056)
  `PR #1056 <https://github.com/pantsbuild/pex/pull/1056>`_

* Fix resource leak in Pex self-isolation. (#1052)
  `PR #1052 <https://github.com/pantsbuild/pex/pull/1052>`_

* Fix use of `iter_compatible_interpreters`. (#1048)
  `PR #1048 <https://github.com/pantsbuild/pex/pull/1048>`_

* Do not rely on `sys.executable` being accurate. (#1049)
  `PR #1049 <https://github.com/pantsbuild/pex/pull/1049>`_

* slightly demystify the relationship between platforms and interpreters in the library API and CLI (#1047)
  `PR #1047 <https://github.com/pantsbuild/pex/pull/1047>`_

* Path filter for PythonInterpreter.iter_candidates. (#1046)
  `PR #1046 <https://github.com/pantsbuild/pex/pull/1046>`_

* Add type hints to `util.py` and `tracer.py` (#1044)
  `PR #1044 <https://github.com/pantsbuild/pex/pull/1044>`_

* Add type hints to variables.py and platforms.py (#1042)
  `PR #1042 <https://github.com/pantsbuild/pex/pull/1042>`_

* Add type hints to the remaining tests (#1040)
  `PR #1040 <https://github.com/pantsbuild/pex/pull/1040>`_

* Add type hints to most tests (#1036)
  `PR #1036 <https://github.com/pantsbuild/pex/pull/1036>`_

* Use MyPy via type comments (#1032)
  `PR #1032 <https://github.com/pantsbuild/pex/pull/1032>`_

2.1.16
------

This release fixes a bug in sys.path scrubbing / hermeticity (#1025)
and a bug in the ``-D / --sources-directory`` and
``-R / --resources-directory`` options whereby PEP-420 implicit
(namespace) packages were not respected (#1021).

* Improve UnsatisfiableInterpreterConstraintsError. (#1028)
  `PR #1028 <https://github.com/pantsbuild/pex/pull/1028>`_

* Scrub direct sys.path manipulations by .pth files. (#1026)
  `PR #1026 <https://github.com/pantsbuild/pex/pull/1026>`_

* PEX zips now contain directory entries. (#1022)
  `PR #1022 <https://github.com/pantsbuild/pex/pull/1022>`_

* Fix UnsatisfiableInterpreterConstraintsError. (#1024)
  `PR #1024 <https://github.com/pantsbuild/pex/pull/1024>`_

2.1.15
------

A patch release to fix an issue with the ``--use-first-matching-interpreter`` flag.

* Fix --use-first-matching-interpreter at runtime. (#1014)
  `PR #1014 <https://github.com/pantsbuild/pex/pull/1014>`_

2.1.14
------

This release adds the ``--use-first-matching-interpreter`` flag, which
can speed up performance when building a Pex at the expense of being
compatible with fewer interpreters at runtime.

* Add ``--use-first-matching-interpreter``. (#1008)
  `PR #1008 <https://github.com/pantsbuild/pex/pull/1008>`_

* Autoformat with Black. (#1006)
  `PR #1006 <https://github.com/pantsbuild/pex/pull/1006>`_

2.1.13
------

The focus of this release is better support of the ``--platform`` CLI
arg. Platforms are now better documented and can optionally be resolved
to local interpreters when possible via ``--resolve-local-platforms`` to
better support creation of multiplatform PEXes.

* Add support for resolving --platform locally. (#1000)
  `PR #1000 <https://github.com/pantsbuild/pex/pull/1000>`_

* Improve --platform help. (#1002)
  `PR #1002 <https://github.com/pantsbuild/pex/pull/1002>`_

* Improve and fix --platform help. (#1001)
  `PR #1001 <https://github.com/pantsbuild/pex/pull/1001>`_

* Ensure pip download dir is uncontended. (#998)
  `PR #998 <https://github.com/pantsbuild/pex/pull/998>`_

2.1.12
------

A patch release to deploy the PEX_EXTRA_SYS_PATH feature.

* A PEX_EXTRA_SYS_PATH runtime variable. (#989)
  `PR #989 <https://github.com/pantsbuild/pex/pull/989>`_

* Fix typos (#986)
  `PR #986 <https://github.com/pantsbuild/pex/pull/986>`_

* Update link to avoid a redirect (#982)
  `PR #982 <https://github.com/pantsbuild/pex/pull/982>`_

2.1.11
------

A patch release to fix a symlink issue in remote execution environments.

* use relative paths within wheel cache (#979)
  `PR #979 <https://github.com/pantsbuild/pex/pull/979>`_

* Fix Tox not finding Python 3.8 on OSX. (#976)
  `PR #976 <https://github.com/pantsbuild/pex/pull/976>`_

2.1.10
------

This release focuses on the resolver API and resolution performance. Pex 2 resolving using Pip is
now at least at performance parity with Pex 1 in all studied cases and most often is 5% to 10%
faster.

As part of the resolution performance work, Pip networking configuration is now exposed via Pex CLI
options and the ``NetworkConfiguration`` API type / new ``resolver.resolve`` API parameter.

With network configuration now wired up, the ``PEX_HTTP_RETRIES`` and ``PEX_HTTP_TIMEOUT`` env var
support in Pex 1 that was never wired into Pex 2 is now dropped in favor of passing ``--retries``
and ``--timeout`` via the CLI (See: `Issue #94 <https://github.com/pantsbuild/pex/issues/94>`_)

* Expose Pip network configuration. (#974)
  `PR #974 <https://github.com/pantsbuild/pex/pull/974>`_

* Restore handling for bad wheel filenames to ``.can_add()`` (#973)
  `PR #973 <https://github.com/pantsbuild/pex/pull/973>`_

* Fix wheel filename parsing in PEXEnvironment.can_add (#965)
  `PR #965 <https://github.com/pantsbuild/pex/pull/965>`_

* Split Pex resolve API. (#970)
  `PR #970 <https://github.com/pantsbuild/pex/pull/970>`_

* Add a ``--local`` mode for packaging the Pex PEX. (#971)
  `PR #971 <https://github.com/pantsbuild/pex/pull/971>`_

* Constrain the virtualenv version used by tox. (#968)
  `PR #968 <https://github.com/pantsbuild/pex/pull/968>`_

* Improve Pex packaging. (#961)
  `PR #961 <https://github.com/pantsbuild/pex/pull/961>`_

* Make the interpreter cache deterministic. (#960)
  `PR #960 <https://github.com/pantsbuild/pex/pull/960>`_

* Fix deprecation warning for ``rU`` mode (#956)
  `PR #956 <https://github.com/pantsbuild/pex/pull/956>`_

* Fix runtime resolve error message generation. (#955)
  `PR #955 <https://github.com/pantsbuild/pex/pull/955>`_

* Kill dead code. (#954)
  `PR #954 <https://github.com/pantsbuild/pex/pull/954>`_

2.1.9
-----

This release introduces the ability to copy requirements from an existing PEX into a new one.

This can greatly speed up repeatedly creating a PEX when no requirements have changed.
A build tool (such as Pants) can create a "requirements PEX" that contains just a static
set of requirements, and build a final PEX on top of that, without having to re-run pip
to resolve requirements.

* Support for copying requirements from an existing pex. (#948)
  `PR #948 <https://github.com/pantsbuild/pex/pull/948>`_


2.1.8
-----

This release brings enhanced performance when using the Pex CLI or API to resolve requirements and
improved performance for many PEXed applications when specifying the `--unzip` option. PEXes built
with `--unzip` will first unzip themselves into the Pex cache if not unzipped there already and
then re-execute themselves from there. This can improve startup latency. Pex itself now uses this
mode in our [PEX release](https://github.com/pantsbuild/pex/releases/download/v2.1.8/pex).

* Better support unzip mode PEXes. (#941)
  `PR #941 <https://github.com/pantsbuild/pex/pull/941>`_

* Support an unzip toggle for PEXes. (#939)
  `PR #939 <https://github.com/pantsbuild/pex/pull/939>`_

* Ensure the interpreter path is a file (#938)
  `PR #938 <https://github.com/pantsbuild/pex/pull/938>`_

* Cache pip.pex. (#937)
  `PR #937 <https://github.com/pantsbuild/pex/pull/937>`_

2.1.7
-----

This release brings more robust control of the Pex cache (PEX_ROOT).

The `--cache-dir` setting is deprecated in favor of build time control of the cache location with
`--pex-root` and new support for control of the cache's runtime location with `--runtime-pex-root`
is added. As in the past, the `PEX_ROOT` environment variable can still be used to control the
cache's runtime location.

Unlike in the past, the [Pex PEX](https://github.com/pantsbuild/pex/releases/download/v2.1.7/pex)
we release can now also be controlled via the `PEX_ROOT` environment variable. Consult the CLI help
for `--no-strip-pex-env` to find out more.

* Sanitize PEX_ROOT handling. (#929)
  `PR #929 <https://github.com/pantsbuild/pex/pull/929>`_

* Fix `PEX_*` env stripping and allow turning off. (#932)
  `PR #932 <https://github.com/pantsbuild/pex/pull/932>`_

* Remove second urllib import from compatibility (#931)
  `PR #931 <https://github.com/pantsbuild/pex/pull/931>`_

* Adding `--runtime-pex-root` option. (#780)
  `PR #780 <https://github.com/pantsbuild/pex/pull/780>`_

* Improve interpreter not found error messages. (#928)
  `PR #928 <https://github.com/pantsbuild/pex/pull/928>`_

* Add detail in interpreter selection error message. (#927)
  `PR #927 <https://github.com/pantsbuild/pex/pull/927>`_

* Respect `Requires-Python` in `PEXEnvironment`. (#923)
  `PR #923 <https://github.com/pantsbuild/pex/pull/923>`_

* Pin our tox version in CI for stability. (#924)
  `PR #924 <https://github.com/pantsbuild/pex/pull/924>`_

2.1.6
-----

* Don't delete the root __init__.py when devendoring. (#915)
  `PR #915 <https://github.com/pantsbuild/pex/pull/915>`_

* Remove unused Interpreter.clear_cache. (#911)
  `PR #911 <https://github.com/pantsbuild/pex/pull/911>`_

2.1.5
-----

* Silence pip warnings about Python 2.7. (#908)
  `PR #908 <https://github.com/pantsbuild/pex/pull/908>`_

* Kill `Pip.spawn_install_wheel` `overwrite` arg. (#907)
  `PR #907 <https://github.com/pantsbuild/pex/pull/907>`_

* Show pex-root from env as default in help output (#901)
  `PR #901 <https://github.com/pantsbuild/pex/pull/901>`_

2.1.4
-----

This release fixes the hermeticity of pip resolver executions when the
resolver is called via the Pex API in an environment with PYTHONPATH
set.

* readme: adding a TOC (#900)
  `PR #900 <https://github.com/pantsbuild/pex/pull/900>`_

* Fix Pex resolver API PYTHONPATH hermeticity. (#895)
  `PR #895 <https://github.com/pantsbuild/pex/pull/895>`_

* Fixup resolve debug rendering. (#894)
  `PR #894 <https://github.com/pantsbuild/pex/pull/894>`_

* Convert `bdist_pex` tests to explicit cmdclass. (#897)
  `PR #897 <https://github.com/pantsbuild/pex/pull/897>`_

2.1.3
-----

This release fixes a performance regression in which pip
would re-tokenize --find-links pages unnecessarily.
The parsed pages are now cached in a pip patch that has
also been submitted upstream.

* Revendor pip (#890)
  `PR #890 <https://github.com/pantsbuild/pex/pull/890>`_

* Add a clear_cache() method to PythonInterpreter. (#885)
  `PR #885 <https://github.com/pantsbuild/pex/pull/885>`_

* Error eagerly if an interpreter binary doesn't exist. (#886)
  `PR #886 <https://github.com/pantsbuild/pex/pull/886>`_

2.1.2
-----

This release fixes a bug in which interpreter discovery failed
when running from a zipped pex.

* Use pkg_resources when isolating a pex code chroot. (#881)
  `PR #881 <https://github.com/pantsbuild/pex/pull/881>`_

2.1.1
-----

This release significantly improves performance and correctness of
interpreter discovery, particularly when pyenv is involved.
It also provides a workaround for EPERM issues when hard linking
across devices, by falling back to copying.
Resolve error checking also now accounts for environment markers.

* Revert "Fix the resolve check in the presence of platform constraints. (#877)" (#879)
  `PR #879 <https://github.com/pantsbuild/pex/pull/879>`_

* [resolver] Fix issue with wheel when using --index-url option (#865)
  `PR #865 <https://github.com/pantsbuild/pex/pull/865>`_

* Fix the resolve check in the presence of platform constraints. (#877)
  `PR #877 <https://github.com/pantsbuild/pex/pull/877>`_

* Check expected pex invocation failure reason in tests. (#874)
  `PR #874 <https://github.com/pantsbuild/pex/pull/874>`_

* Improve hermeticity of vendoring. (#873)
  `PR #873 <https://github.com/pantsbuild/pex/pull/873>`_

* Temporarily skip a couple of tests, to get CI green. (#876)
  `PR #876 <https://github.com/pantsbuild/pex/pull/876>`_

* Respect env markers when checking resolves. (#861)
  `PR #861 <https://github.com/pantsbuild/pex/pull/861>`_

* Ensure Pex PEX contraints match pex wheel / sdist. (#863)
  `PR #863 <https://github.com/pantsbuild/pex/pull/863>`_

* Delete unused pex/package.py. (#862)
  `PR #862 <https://github.com/pantsbuild/pex/pull/862>`_

* Introduce an interpreter cache. (#856)
  `PR #856 <https://github.com/pantsbuild/pex/pull/856>`_

* Re-enable pyenv interpreter tests under pypy. (#859)
  `PR #859 <https://github.com/pantsbuild/pex/pull/859>`_

* Harden PythonInterpreter against pyenv shims. (#860)
  `PR #860 <https://github.com/pantsbuild/pex/pull/860>`_

* Parallelize interpreter discovery. (#842)
  `PR #842 <https://github.com/pantsbuild/pex/pull/842>`_

* Explain hard link EPERM copy fallback. (#855)
  `PR #855 <https://github.com/pantsbuild/pex/pull/855>`_

* Handle EPERM when Linking (#852)
  `PR #852 <https://github.com/pantsbuild/pex/pull/852>`_

* Pin transitive dependencies of vendored code. (#854)
  `PR #854 <https://github.com/pantsbuild/pex/pull/854>`_

* Kill empty setup.py. (#849)
  `PR #849 <https://github.com/pantsbuild/pex/pull/849>`_

* Fix `tox -epackage` to create pex supporting 3.8. (#843)
  `PR #843 <https://github.com/pantsbuild/pex/pull/843>`_

* Fix Pex to handle empty ns package metadata. (#841)
  `PR #841 <https://github.com/pantsbuild/pex/pull/841>`_


2.1.0
-----

This release restores and improves support for building and running
multiplatform pexes. Foreign `linux*` platform builds now include
`manylinux2014` compatible wheels by default and foreign CPython pexes now
resolve `abi3` wheels correctly. In addition, error messages at both buildtime
and runtime related to resolution of dependencies are more informative.

Pex 2.1.0 should be considered the first Pex 2-series release that fully
replaces and improves upon Pex 1-series functionality.

* Fix pex resolving for foreign platforms. (#835)
  `PR #835 <https://github.com/pantsbuild/pex/pull/835>`_

* Use pypa/packaging. (#831)
  `PR #831 <https://github.com/pantsbuild/pex/pull/831>`_

* Upgrade vendored setuptools to 42.0.2. (#832)
  `PR #832 <https://github.com/pantsbuild/pex/pull/832>`_
  `PR #1830 <https://github.com/pypa/setuptools/pull/1830>`_

* De-vendor pex just once per version. (#833)
  `PR #833 <https://github.com/pantsbuild/pex/pull/833>`_

* Support VCS urls for vendoring. (#834)
  `PR #834 <https://github.com/pantsbuild/pex/pull/834>`_

* Support python 3.8 in CI. (#829)
  `PR #829 <https://github.com/pantsbuild/pex/pull/829>`_

* Fix pex resolution to respect --ignore-errors. (#828)
  `PR #828 <https://github.com/pantsbuild/pex/pull/828>`_

* Kill `pkg_resources` finders monkey-patching. (#827)
  `PR #827 <https://github.com/pantsbuild/pex/pull/827>`_

* Use flit to distribute pex. (#826)
  `PR #826 <https://github.com/pantsbuild/pex/pull/826>`_

* Cleanup extras_require. (#825)
  `PR #825 <https://github.com/pantsbuild/pex/pull/825>`_

2.0.3
-----

This release fixes a regression in handling explicitly requested `--index` or
`--find-links` http (insecure) repos. In addition, performance of the pex 2.x
resolver is brought in line with the 1.x resolver in all cases and improved in
most cases.

* Unify PEX buildtime and runtime wheel caches. #821
  `PR #821 <https://github.com/pantsbuild/pex/pull/821>`_

* Parallelize resolve. (#819)
  `PR #819 <https://github.com/pantsbuild/pex/pull/819>`_

* Use the resolve cache to skip installs. (#815)
  `PR #815 <https://github.com/pantsbuild/pex/pull/815>`_

* Implicitly trust explicitly requested repos. (#813)
  `PR #813 <https://github.com/pantsbuild/pex/pull/813>`_

2.0.2
-----

This is a hotfix release that fixes a bug exposed when Pex was asked to use an
interpreter with a non-canonical path as well as fixes for 'current' platform
handling in the resolver API.

* Fix current platform handling. (#801)
  `PR #801 <https://github.com/pantsbuild/pex/pull/801>`_

* Add a test of pypi index rendering. (#799)
  `PR #799 <https://github.com/pantsbuild/pex/pull/799>`_

* Fix `iter_compatible_interpreters` path biasing. (#798)
  `PR #798 <https://github.com/pantsbuild/pex/pull/798>`_

2.0.1
-----

This is a htofix release that fixes a bug when specifying a custom index
(`-i`/`--index`/`--index-url`) via the CLI.

* Fix #794 issue by add missing return statement in __str__ (#795)
  `PR #795 <https://github.com/pantsbuild/pex/pull/795>`_

2.0.0
-----

Pex 2.0.0 is cut on the advent of a large, mostly internal change for typical
use cases: it now uses vendored pip to perform resolves and wheel builds. This
fixes a large number of compatibility and correctness bugs as well as gaining
feature support from pip including handling manylinux2010 and manylinux2014 as
well as VCS requirements and support for PEP-517 & PEP-518 builds.

API changes to be wary of:

* The egg distribution format is no longer supported.
* The deprecated ``--interpreter-cache-dir`` CLI option was removed.
* The ``--cache-ttl`` CLI option and ``cache_ttl`` resolver API argument were
  removed.
* The resolver API replaced ``fetchers`` with a list of ``indexes`` and a list
  of ``find_links`` repos.
* The resolver API removed (http) ``context`` which is now automatically
  handled.
* The resolver API removed ``precedence`` which is now pip default precedence:
  wheels when available and not ruled out via the ``--no-wheel`` CLI option or
  ``use_wheel=False`` API argument.
* The ``--platform`` CLI option and ``platform`` resolver API argument now must
  be full platform strings that include platform, implementation, version and
  abi; e.g.: ``--platform=macosx-10.13-x86_64-cp-36-m``.
* The ``--manylinux`` CLI option and ``use_manylinux`` resolver API argument
  were removed. Instead, to resolve manylinux wheels for a foreign platform,
  specify the manylinux platform to target with an explicit ``--platform`` CLI
  flag or ``platform`` resolver API argument; e.g.:
  ``--platform=manylinux2010-x86_64-cp-36-m``.

In addition, Pex 2.0.0 now builds reproduceable pexes by default; ie:

* Python modules embedded in the pex are not pre-compiled (pass --compile if
  you want this).
* The timestamps for Pex file zip entries default to midnight on
  January 1, 1980 (pass --use-system-time to change this).

This finishes off the effort tracked by
`Issue #716 <https://github.com/pantsbuild/pex/pull/718>`_

Changes in this release:

* Pex defaults to reproduceable builds. (#791)
  `PR #791 <https://github.com/pantsbuild/pex/pull/791>`_

* Use pip for resolving and building distributions. (#788)
  `PR #788 <https://github.com/pantsbuild/pex/pull/788>`_

* Bias selecting the current interpreter. (#783)
  `PR #783 <https://github.com/pantsbuild/pex/pull/783>`_

1.6.12
------

This release adds the `--intransitive` option to support pre-resolved requirements
lists and allows for python binaries built under Gentoo naming conventions.

* Add an --intransitive option. (#775)
  `PR #775 <https://github.com/pantsbuild/pex/pull/775>`_

* PythonInterpreter: support python binary names with single letter suffixes (#769)
  `PR #769 <https://github.com/pantsbuild/pex/pull/769>`_

1.6.11
------

This release brings a consistency fix to requirement resolution and an
isolation fix that scrubs all non-stdlib PYTHONPATH entries by default,
only pre-pending or appending them to the `sys.path` if the
corresponding `--inherit-path=(prefer|fallback)` is used.

* Avoid reordering of equivalent packages from multiple fetchers (#762)
  `PR #762 <https://github.com/pantsbuild/pex/pull/762>`_

* Include `PYTHONPATH` in `--inherit-path` logic. (#765)
  `PR #765 <https://github.com/pantsbuild/pex/pull/765>`_

1.6.10
------

This is a hotfix release for the bug detailed in #756 that was
introduced by #752 in python 3.7 interpreters.

* Guard against modules with a `__file__` of `None`. (#757)
  `Issue #756 <https://github.com/pantsbuild/pex/issues/756>`_
  `PR #757 <https://github.com/pantsbuild/pex/pull/757>`_

1.6.9
-----

* Fix `sys.path` scrubbing of pex extras modules. (#752)
  `PR #752 <https://github.com/pantsbuild/pex/pull/752>`_

* Fix pkg resource early import (#750)
  `PR #750 <https://github.com/pantsbuild/pex/pull/750>`_

1.6.8
-----

* Fixup pex re-exec during bootstrap. (#741)
  `PR #741 <https://github.com/pantsbuild/pex/pull/741>`_

* Fix resolution of `setup.py` project extras. (#739)
  `PR #739 <https://github.com/pantsbuild/pex/pull/739>`_

* Tighten up namespace declaration logic. (#732)
  `PR #732 <https://github.com/pantsbuild/pex/pull/732>`_

* Fixup import sorting. (#731)
  `PR #731 <https://github.com/pantsbuild/pex/pull/731>`_

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
  `PR #692 <https://github.com/pantsbuild/pex/pull/692>`_

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
