# Release Notes

## 2.90.2

This release also updates vendored Pip's vendored certifi's cacert.pem to that from
certifi 2026.2.25.

* Update vendored Pip's CA cert bundle. (#3108)

## 2.90.1

This release fixes a Pex caching bug when creating `--layout packed` PEXes and alternating between
the default (`--compress`) and `--no-compress`. Previously this could lead errors building the
packed PEX which necessitated clearing the PEX cache.

* Fix `--layout packed` bootstrap and wheel caches. (#3106)

## 2.90.0

This release adds support for wrapping PEP-660 `build_editable` to `pex_build.setuptools.build`
plugins and dogfoods this.

* Support wrapping `build_editable` in wrap. (#3105)

## 2.89.1

This release adds better diagnostics for certain Pex filesystem interaction errors.

* Add `safe_copy` failure diagnostic message. (#3103)

## 2.89.0

This release exports the path of the installed `.desktop` file as the `DESKTOP_FILE` environment
variable for commands in `--scie-icon` and `--scie-desktop-file` PEX scies. The `DESKTOP_FILE`
path may not exist, but if it does it can be used to implement desktop application uninstallation
in the PEX scie application code.

* Export `DESKTOP_FILE` for PEX scie .desktop apps. (#3100)

## 2.88.1

This release fixes `.desktop` files installed by `--scie-icon` and `--scie-desktop-file` PEX scies
to be more robust. They now work even if the original PEX scie they were installed by is (re)moved
as well as properly handling a `SCIE_BASE` with spaces in the path.

* Fix `.desktop` files installed by PEX scies. (#3099)

## 2.88.0

This release adds support for `--pip-version 26.0.1`.

* Add support for `--pip-version 26.0.1`. (#3098)

## 2.87.0

This release adds support for `--pip-version 26.0`.

* Add support for `--pip-version 26.0`. (#3091)

## 2.86.1

This release fixes a bug in constraints file requirement parsing. Previously, Pex tried to validate
constraints beyond its own needs, anticipating Pip's needs, leading to a failure to handle direct
reference URL requirements, including VCS requirements.

* Fix constraints file parsing for URL requirements. (#3090)

## 2.86.0

This release adds support for Linux PEX scies installing themselves with a desktop entry on first
run. This is enabled via either of `--scie-icon` or `--scie-desktop-file`. By default, the end-user
is prompted to approve a desktop install but this can be bypassed at build time with
`--no-scie-prompt-desktop-install` or at runtime using the `PEX_DESKTOP_INSTALL` environment
variable.

* Add PEX scie Linux .desktop install support. (#3087)

## 2.85.3

This release upgrades vendored `packaginged for Python>=3.8 to the latest release; bringing some bug
fixes and performance improvements.

* Upgrade vendored `packaging` to 26.0 for Python>=3.8. (#3083)

## 2.85.2

This release makes running a PEX using venv-execution and sh-bootstrapping (that is, build with
`--sh-boot --venv`) more likely to behave identically with a cold or warm `PEX_ROOT` cache. This
includes running with `PEX_PYTHON=...`,  `PEX_PYTHON_PATH=...`, `PEX_PATH=...`, `PEX_VENV=...` and
`PEX_IGNORE_RCFILES=...`.

* Avoid fast-path in `--sh-boot` script for more variables. (#2729)

## 2.85.1

This release upgrades the floor of `science` to 0.17.2 to pick up better handling for CPython 3.9
which was dropped in new [PBS][PBS] releases at the end of 2025.

* Upgrade science to 0.17.2 (#3081)

## 2.85.0

This release introduces a new `--interpreter-selection-strategy` option for use when building PEXes
that use `--interpreter-constraint`s. When multiple interpreters satisfy the specified
`--interpreter-constraint`s, the `--interpreter-selection-strategy` allows you to direct Pex to
select the `oldest` (the default and the existing behavior) or the `newest`. In either case, the
highest available patch version will be selected from amongst multiple interpeters with the same
major and minor versions.

* Support an `--interpreter-selection-strategy` option. (#3080)

## 2.84.0

This release causes `pex ...` to emit the output path of the generated PEX (and / or scies) on
STDOUT. If `--seed verbose` is set, then the output path of the PEX is included in the new
`"seeded_from"` field.

* Emit PEX output path to stdout. (#3079)

## 2.83.0

This release adds support for templating `{platform}` in PEX file names. When this substitution
token is found, it is replaced with the most specific platform tag(s) of wheels in the PEX. For
example:
```console
:; python -mpex ansicolors -o "ansicolors-{platform}.pex"

:; ./ansicolors-py2.py3-none-any.pex
Pex 2.83.0 hermetic environment with 1 requirement and 1 activated distribution.
Python 3.14.2 (main, Dec  5 2025, 14:39:48) [GCC 15.2.0] on linux
Type "help", "pex", "copyright", "credits" or "license" for more information.
>>> pex()
Running from PEX file: ./ansicolors-py2.py3-none-any.pex
Requirements:
  ansicolors
Activated Distributions:
  ansicolors-1.1.8-py2.py3-none-any.whl
>>>

:; python -mpex \
    --complete-platform package/complete-platforms/linux-x86_64.json \
    --complete-platform package/complete-platforms/macos-aarch64.json ansible \
    -o "ansible-{platform}.pex"

:; ./ansible-cp314-cp314-macosx_11_0_arm64.manylinux2014_x86_64.pex
Pex 2.83.0 hermetic environment with 1 requirement and 10 activated distributions.
Python 3.14.2 (main, Dec  5 2025, 14:39:48) [GCC 15.2.0] on linux
Type "help", "pex", "copyright", "credits" or "license" for more information.
>>> pex()
Running from PEX file: ./ansible-cp314-cp314-macosx_11_0_arm64.manylinux2014_x86_64.pex
Requirements:
  ansible
Activated Distributions:
  ansible-13.2.0-py3-none-any.whl
  ansible_core-2.20.1-py3-none-any.whl
  jinja2-3.1.6-py3-none-any.whl
  markupsafe-3.0.3-cp314-cp314-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl
  pyyaml-6.0.3-cp314-cp314-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl
  cryptography-46.0.3-cp311-abi3-manylinux_2_34_x86_64.whl
  cffi-2.0.0-cp314-cp314-manylinux2014_x86_64.manylinux_2_17_x86_64.whl
  pycparser-2.23-py3-none-any.whl
  packaging-25.0-py3-none-any.whl
  resolvelib-1.2.1-py3-none-any.whl
>>>
```

* Support a `{platform}` placeholder in PEX file names. (#3078)

## 2.82.1

This release fixes `pex3 scie create --dest-dir` to work when the specified PEX is a local file
path. Previously `--dest-dir` only worked when the specified PEX was an URL.

* Fix `pex3 scie create --dest-dir` handling. (#3076)

## 2.82.0

This release adds support for resource path bindings to plain PEXes as a follow-on to adding
resource binding support for PEX scies in the 2.81.0 release. Resource paths are bound to
environment variables with `--bind-resource-path`. Additionally, the existing `--inject-args` option
now supports replacement of `{pex.env.<env var name>}` placeholders with the corresponding
environment variable value. Notably, the combination of these features allows passing the paths of
files contained in a PEX to third party scripts without extra shim code.

* Support passing PEX file paths to 3rd party scripts.  (#3074)

## 2.81.0

This release adds the ability to set a custom scie entrypoint for PEX scies using `--scie-exe`,
`--scie-args` and `--scie-env`, as well as bind resource paths to environment variables using
`--scie-bind-resource-path`. The combination of these new features allows broad flexibility
defining a PEX scie's boot command.

Additionally, the `pex3 scie create` command gains the ability to use a URL for the PEX to convert
to a scie and optionally specify a size (via `#size=<expected size>`) and / or fingerprint (via
`#<algorithm>=<expected fingerprint>`) to verify the download against.

* Support converting existing Pants PEXes to performant scies. (#3072)

## 2.80.0

This release adds the `pex3 scie create` tool for creating scies from existing PEX files. This
works for PEXes created by Pex 2.1.25 (released on January 21st, 2021) and newer.

* Add a `pex3 scie create` command. (#3070)

## 2.79.0

This release adds the `CPython[free-threaded]` alias for `CPython+t` and the `CPython[gil]` alias
for `CPython-t` when writing interpreter constraints.

* Add `CPython[{free-threaded,gil}]` aliases for `CPython{+,-}t`. (#3068)

## 2.78.0

This release adds support for the `CPython+t` implementation name in interpreter constraints to
allow constraining selected interpreters to CPython interpreters built with free-threading support.
The existing `CPython` implementation selects from either classic GIL enabled `CPython` interpreters
or CPython free-threaded interpreters as was the case previously. The `CPython-t` implementation
name can be used to require classic GIL-only CPython interpreters.
-
* Support `CPython+t` in ICs to select free-threaded CPython. (#3067)

## 2.77.3

This release updates vendored Pip's vendored certifi's cacert.pem to that from certifi 2026.1.4.

* Update vendored Pip's CA cert bundle. (#3065)

## 2.77.2

This release fixes venv creation from PEXes to avoid declaring false collisions in `__init__.py`
files when the venv uses Python 3.9 or greater.

* Compare ASTs of colliding venv `__init__.py`. (#3063)

## 2.77.1

This release fixes a very old bug where the Pex PEX (or any other PEX created with
`--no-strip-pex-env`) would, in fact, strip `PEX_PYTHON` and `PEX_PYTHON_PATH`.

* Fix `PEX_PYTHON{,_PATH}` stripping on Pex re-exec. (#3062)

## 2.77.0

This release has no fixes or new features per-se, but just changes the set of distributions that
Pex releases to PyPI. Previously Pex released an sdist and a universal (`py2.py3-none-any`) `.whl`.
Pex now releases two wheels in addition to the sdist. The `py3.py312-none-any.whl` targets
Python>=3.12 and has un-needed vendored libraries elided making it bith a smaller `.whl` and less
prone to false-positive security scan issues since unused vendored code is now omitted. The other
wheel carries the same contents as prior and supports creating PEXes for Python 2.7 and
Python>=3.5,<3.12.

* Split Pex `.whl` into two `.whl`s. (#3057)

## 2.76.1

This release fixes bootstrapping of Pips specified via `--pip-version` to respect Pex Pip
configuration options (like custom indexes) under Python 3.12 and newer.

* Fix Pip bootstrap to respect Pip config for Python >= 3.12. (#3054)

## 2.76.0

This release adds support for `--no-scie-pex-entrypoint-env-passthrough` to trigger direct execution
of `--venv` PEX scie script entrypoints. This performance optimization mirrors the existing default
`--no-scie-busybox-pex-entrypoint-env-passthrough` for busybox scies, but must be selected by 
passing `--no-scie-pex-entrypoint-env-passthrough` explicitly. In addition, the `VIRTUAL_ENV` env
var is now guaranteed to be set for all `--venv` PEX scies.

* Add scie support for direct exec of venv scripts. (#3053)

## 2.75.2

This release updates vendored Pip's vendored certifi's cacert.pem to that from certifi 2025.11.12.

* Update vendored Pip's CA cert bundle. (#3052)

## 2.75.1

This release fixes Pex handling of wheels with bad RECORDs that record files that do not exist in
the `.whl` file.

* Warn when non-existent files in RECORD, but proceed. (#3051)

## 2.75.0

This release adds supoort for `--scie-load-dotenv` to enable `.env` file loading in PEX scies.

* Support scie-jump `.env` loading with `--scie-load-dotenv`. (#3046)

## 2.74.3

This release fixes a bug gracefully handling a request for `--validate-entry-point` when no
`--entry-point` was given.

* Error for missing entry point under `--validate-entry-point`. (#3048)

## 2.74.2

This release fixes building PEXes from direct URL requirements. Previously, the direct URL
requirement would be recorded incorrectly in PEX-INFO metadata leading to a failure to boot.

* Fix `str(req)` of direct URLs with known versions. (#3043)

## 2.74.1

This release upgrades the floor of `science` to 0.17.1 and `scie-jump` to 1.9.2 to fix a regression
in the breadth of Linux platforms `--scie {eager,lazy}` PEX scies were compatible with.

* Upgrade science to 0.17.1 & scie-jump to 1.9.2. (#3038)

## 2.74.0

This release adds support for setting custom PEX-INFO `build_properties` metadata via
`--build-property`, `--build-properties` and `--record-git-state`.

* Support custom PEX-INFO `build_properties`. (#3036)

## 2.73.1

This release fixes `--lock` and `--pylock` subsetting of direct reference and VCS requirements.
Previously, just the project name was matched when subsetting but now the normalized URL is matched.
The previous behavior could lead to subsets succeeding that should have otherwise failed. The new
behavior can lead to a subset failing when URLs differ, but both URLs point to the same content.
Although this too is a bug, it should be a much narrower use case in the wild; so this should be an
improvement.

* Fix URL requirement `--lock` & `--pylock` subsetting. (#3034)

## 2.73.0

This release upgrades the floor of `science` to 0.17.0 and `scie-jump` to 1.9.1 to pick up support
for producing PEX scies for Linux aarch64 & x86_64 that link against glibc. Previously the embedded
interpreter would link against glibc but the `scie-jump` at the PEX scie tip was a musl libc static
binary and this could cause problems in those areas where glibc and musl diverge.

* Upgrade science to 0.17.0 & scie-jump to 1.9.1. (#3033)

## 2.72.2

This release fixes a regression introduced in the Pex 2.60.0 release when installing wheels with
`*.data/` entries whose top-level name matches a top-level package in the wheel. This regression
only affected default `--venv` mode PEXes which populate site-packages using symlinks.

* Fix `--venv` (using symlinks) for some wheels. (#3031)

## 2.72.1

This release fixes Pex lock resolves (`--lock` and `--pylock`) to allow exceptions for `--no-wheel`
and `--no-build` as a follow-on to the 2.71.1 release fix that enabled the same for Pip resolves.

* Allow exceptions for `--no-{wheel,build}` with locks. (#3028)

## 2.72.0

This release adds support for building foreign platform musl Linux PEX scies and dogfoods this to
add musl Linux aarch64 & x86_64 Pex PEX scies to the Pex release.

* Support targeting foreign platform musl scies. (#3025)

## 2.71.1

This release fixes Pex to allow blanket disallowing builds but making targeted exceptions and
vice-versa. The underlying Pip machinery has always supported this, but Pex just got in the way for
no reason.

* Allow exceptions for `--no-wheel` & `--no-build`. (#3023)

## 2.71.0

This release upgrades the floor of `science` to 0.16.0 to pick up support for generating PEX scies
for musl Linux aarch64.

* Upgrade `science` to 0.16.0. (#3020)

## 2.70.0

This release adds a feature for Pex developers. If you want to experiment with a new version of Pip
you can now specify `_PEX_PIP_VERSION=adhoc _PEX_PIP_ADHOC_REQUIREMENT=...`. N.B.: This feature is
for Pex development only.

* Support adhoc Pip versions in development. (#3011)

## 2.69.2

This release fixes handling of scoped repos. Previously, validation against duplicate scopes was too
aggressive and disallowed multiple un-named indexes and find-links repositories.

* Allow multiple un-named indexes and find-links repos. (#3009)

## 2.69.1

This release fixes `--venv-repository` handling of top-level requirements that specify pre-releases.
Such resolves now imply `--pre`.

* Root reqs that specify prereleases imply `--pre`. (#3004)

## 2.69.0

This release adds a `pexec` console script as an alias for `pex3 run`.

* Add `pexec` script as a `pex3 run` alias. (#3001)

## 2.68.3

This release fixes Pex to handle installing a wider variety of whls violating various PyPA specs.

* Handle two cases of bad whl metadata. (#2999)

## 2.68.2

This release bumps the floor of `science` to 0.15.1 to ensure least surprise with no bad
`--scie-hash-alg` choices presented by the underlying science tool used to build Pex `--scie`s.

* Upgrade `science` to 0.15.1. (#2995)

## 2.68.1

This release fixes a regression extracting sdists on some Pythons older than 3.12.

* Fix sdist tar extraction filtering for old Pythons. (#2992)

## 2.68.0

This release adds support for `--project` pointing to local project sdist or wheel paths in addition
to the already supported local project directory path. The wheel case can be particularly useful
when building a project wheel out of band is very much faster than letting Pex obtain the project
metadata via a PEP-517 `prepare_metadata_for_build_wheel` call or via a wheel build via Pip, which
is what Pex falls back to.

* Support `--project` pointing at sdists and whls. (#2989)

## 2.67.3

This release brings Pex into compliance with sdist archive features as specified in
https://packaging.python.org/en/latest/specifications/source-distribution-format/#source-distribution-archive-features.

* Implement tar extraction data filtering. (#2987)

## 2.67.2

This release fixes a bug resolving editable projects from `--venv-repository`s.

* Fix resolve of editables from `--venv-repository`s. (#2984)

## 2.67.1

This release fixes a bug subsetting `--venv-repository` resolves when top-level requirements
had version specifiers; e.g.: `thing>2`.

* Fix `--venv-repository` subsetting. (#2981)

## 2.67.0

This release adds support for specifying multiple `--venv-repository`s when building a PEX. This
allows creating multi-platform PEXes from multiple venvs that all satisfy a resolve, but for
different interpreters.

* Multi-platform PEXes via multiple `--venv-repository`s. (#2977)

## 2.66.1

This release improves upon the local project directory hashing fix in [2.61.1](#2611) by
avoiding the hashing altogether unless creating a lock, where the resulting fingerprint is
needed.

* Avoid fingerprinting local projects. (#2975)

## 2.66.0

This release adds support for `--pip-version 25.3`.

* Add support for `--pip-version 25.3`. (#2968)

## 2.65.0

This release adds support for PEX scies using CPython free-threaded builds. Most such scies should
be able to auto-detect when a free-threaded CPython is needed, but new `--scie-pbs-free-threaded`
and `--scie-pbs-debug` options have been added to explicitly request the desired PBS CPython build
as well.

* Support free-threaded PEX scies. (#2967)

## 2.64.1

This release is a follow-up to 2.64.0 to fix a regression in locks for credentialed VCS
requirements.

* Fix redaction of VCS URL credentials in locks. (#2964)

## 2.64.0

This release adds support for `--avoid-downloads` / `--no-avoid-downloads` to `pex3 lock create`. By
default, when available, Pex now locks in `--avoid-downloads` mode using
`pip install --dry-run --ignore-installed --report` to power lock generation instead of
`pip download`. This saves time generating the lock at the expense of having to spend time
downloading distributions later when using the lock to create a PEX or venv. This new lock mode
produces byte-wise identical locks and is available for all Pip versions Pex supports save for
vendored Pip (`--pip-version {vendored,20.3.4-patched}`).

* Use Pip `--report` to avoid `pex3 lock create` downloads. (#2962)

## 2.63.0

This release adds population of a `pex` script to venvs created with `pex3 venv create`. This allows
for executing Python in the activated venv via `/path/to/venv/pex ...` instead of 
`source /path/to/venv/bin/activate && python ...`.

* Include `pex` script in `pex3 venv create`. (#2960)

## 2.62.1

This release improves performance when creating venvs by eliminating an un-necessary re-hash of
wheel files already installed in the Pex cache.

* Avoid re-hashing wheels when re-installing. (#2958)

## 2.62.0

This release brings full support for universal lock splitting. You can now declare conflicting
top-level requirements for different (marker) environments and these will be isolated in separate
lock resolves in the same universal lock file. These split resolves are performed in parallel and
the appropriate split lock is later selected automatically when building a PEX or a venv from the
lock.

As part of this work, locks also filter wheels more faithfully. If you supply interpreter
constraints that constrain to CPython, the resulting lock will now only contain `cp`
platform-specific wheels (and, for example, not PyPy wheels).

* Complete support for universal lock splitting. (#2940)

## 2.61.1

This release fixes a long-standing bug hashing local project directories when building PEXes. Pex
now hashes the content of an exploded sdist for the local project just like it does when hashing
local projects for a lock.

* Fix local project directory hashing. (#2954)

## 2.61.0

This release adds support for the Python 3.15 series early. Pex runs on 3.15.0a1, can produce scies
for 3.15.0a1, etc.

* Officially begin supporting Python 3.15. (#2952)

## 2.60.2

This release fixes a regression in the Pex 2.60.0 release when installing wheels with
`*.data/{purelib,platlib}` entries.

* Fix handling of whl `*.data/` dirs. (#2946)

## 2.60.1

This release fixes a backwards compatiility break in 2.60.0 where modern `pex-tools` would fail to
work on PEXes built with Pex prior to 2.60.

* Fix installed wheel re-installation for old PEXes. (#2943)

## 2.60.0

This release adds support for `--no-pre-install-wheels` to both the `--pex-repository` and
`--venv-repository` resolvers, meaning all forms of Pex resolution (including Pip, `--lock`,
`--pylock` and `--pre-resolved-dists`) now support this option.

In addition, adding this support improved the fidelity of `pex-tools repository extract` such that
extracted wheels are bytewise identical to the original wheel the PEX was built with. This fidelity
also extends to wheels extracted from `--pex-repository` PEXes and wheels extracted from venvs
created from PEXes.

* Implement `.whl` packing from chroots and venvs. (#2925)

## 2.59.5

This release optimizes `--venv-repository` installed wheel caching to only store one copy per
unique wheel even when that wheel is resolved from multiple `--venv-repository`s.

This release also updates vendored Pip's vendored certifi's cacert.pem to that from certifi
2025.10.5.

* Do not hash installed scripts from `--venv-repository`. (#2935)
* Update vendored Pip's CA cert bundle. (#2934)

## 2.59.4

This release fixes a bug in `--venv-repository` resolution that would lead to resolution failure
when the same wheel (that has console script entry points) is installed in multiple venvs and those
venvs are used as `--venv-repository` resolve sources.

* Fix `--venv-repository` wheel cache copy-pasta bug. (#2932)

## 2.59.3

This release fixes `--venv-repository` to work with venvs that have installed wheels with
non-conformant `WHEEL` metadata. Notably, from wheels built with maturin that have a compressed tag
set; e.g.: `hf-xet-1.1.10-cp37-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl`.

* Stabilize non-conformant WHEEL Tag metadata. (#2927)

## 2.59.2

This release fixes two bugs handling split universal resolves. Previously, when a universal resolve
was split by markers other than `python_version` and `python_full_version` and no interpreter
constraints were specified, locking would fail. Additionally, when a split lock had differing
transitive dependencies in splits, lock sub-setting would fail. Both issues are now corrected.

* Fix split universal lock corner cases. (#2922)

## 2.59.1

This release fixes a regression in VCS URL handling introduced by Pex 2.38.0 when VCS URLs included
user info in the authority.

* Fix `pex3 lock create/export` for VCS URLs with userinfo (#2918)

## 2.59.0

This release adds support for a `--venv-repository` resolution source. This allows creating a PEX
from a pre-existing venv. By default, all installed venv distributions are included in the PEX, but
by specifying requirements, the venv can be subset. The `--venv-repository` source is also supported
by `pex3 venv create` allowing subsetting an existing venv directly into a new venv as well.

* Add support for `--venv-repository` resolver. (#2916)

## 2.58.1

This release fixes a bug building source distributions from locks of local project directories when
the local project uses the `uv_build` backend.

* Fix sdist build of local projects using `uv_build`. (#2914)

## 2.58.0

This release adds `--derive-sources-from-requirements-files` to allow for scoping requirement
sources via the structure of requirements files. If any requirements files are specified that 
contain `-f` / `--find-links`, `-i` / `--index-url`, or `--extra-index-url` options,
`--derive-sources-from-requirements-files` will automatically map these repos as the `--source` for
the requirements (if any) declared in the same requirements file.

* Introduce `--derive-sources-from-requirements-files`. (#2909)

## 2.57.0

This release adds support for project name regexes to `--source` scopes for repos. For example, the
PyTorch example given in the 2.56.0 release notes can now be shortened to:
```console
pex3 lock create \
    --style universal \
    --target-system linux \
    --target-system mac \
    --elide-unused-requires-dist \
    --interpreter-constraint "CPython==3.13.*" \
    --index pytorch=https://download.pytorch.org/whl/cu129 \
    --source "pytorch=^torch(vision)?$; sys_platform != 'darwin'" \
    --source "pytorch=^nvidia-.*; sys_platform != 'darwin'" \
    --indent 2 \
    -o lock.json \
    torch \
    torchvision
```

* Support regexes for `--source` project matching. (#2906)

## 2.56.0

This release adds support for scoping `--index` and `--find-links` repos to only be used to resolve
certain projects, environments or a combination of the two. For example, to use the piwheels index
but restrict its use to resolves targeting armv7l machines, you can now say:
`--index piwheels=https://www.piwheels.org/simple --source piwheels=platform_machine == 'armv7l'`.
See the `--help` output for `--index` and `--find-links` for more syntax details.

Additionally, `--style universal` locks have been made aware of top-level inputs that can split the
lock resolve and such resolves are pre-split and performed in parallel to allow locking for multiple
non-overlapping universes at once. Splits can be caused by some scoped repos setups as well locks
with multiple differing top-level requirements for the same project. For example, the following will
create a universal lock with two locked resolves, one locking cowsay 5.0 for Python 2 and one
locking cowsay 6.0 for Python 3:
```console
pex3 lock create \
  --style universal \
  --indent 2 \
  -o lock.json
  "cowsay<6; python_version < '3'" \
  "cowsay==6; python_version >= '3'"
```

An important use case for this new set of features is creating a universal lock for PyTorch for
CUDA enabled Linux and Mac by adding the appropriate pytorch index appropriately scoped.
For example, this lock will contain two locked resolves, one for Mac sourced purely from PyPI and
one for CUDA 12.9 enabled Linux partially sourced from the PyTorch index for CUDA 12.9:
```console
pex3 lock create \
    --style universal \
    --target-system linux \
    --target-system mac \
    --elide-unused-requires-dist \
    --interpreter-constraint "CPython==3.13.*" \
    --index pytorch=https://download.pytorch.org/whl/cu129 \
    --source "pytorch=torch; sys_platform != 'darwin'" \
    --source "pytorch=torchvision; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-cublas-cu12; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-cuda-cupti-cu12; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-cuda-nvrtc-cu12; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-cuda-runtime-cu12; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-cudnn-cu11; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-cudnn-cu12; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-cufft-cu12; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-cufile-cu12; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-curand-cu12; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-cusolver-cu12; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-cusparse-cu12; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-cusparselt-cu12; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-nccl-cu12; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-nvjitlink-cu12; sys_platform != 'darwin'" \
    --source "pytorch=nvidia-nvtx-cu12; sys_platform != 'darwin'" \
    --indent 2 \
    -o lock.json \
    torch \
    torchvision
```

* Support scopes for `--index` and `--find-links`. (#2903)

## 2.55.2

This release improves Pex `--pylock` handling interoperability by accepting the minimum possible
dependency information likely to be provided; namely, the dependency `name`.

* More robust `pylock.toml` dependency handling. (#2901)

## 2.55.1

This release fixes a bug present since the inception of `pex3 lock create --style universal`
support. Previously, if the universal lock was created with `--interpreter-constraint`s, the
Python implementation information was discarded; so, for example, even with
`--interpreter-constraint CPython==3.13.*`, the lock resolve would consider PyPy in-play.

* Respect `--interpreter-constraint` impl in locks. (#2898)

## 2.55.0

This release adds support for `--override <project name>=<requirement>` wherever
`--override <requirement>` is currently accepted. This can be useful when you need to supply a
patch to an existing published project and would prefer to depend on wheels you pre-build instead
of using a VCS source dependency `--override`, which can be slow to build.

* Support dependency replacement with `--override`. (#2894)

## 2.54.2

This release fixes `pex3 lock create` when multiple `--index` are configured and they provide the
same wheel file name, but with different contents. This is a reality in the PyTorch ecosystem, for
example, prior to any fixes the [WheelNext][WheelNext] project may bring.

* Fix `pex3 lock create` for dup wheels with different hashes. (#2890)

[WheelNext]: https://wheelnext.dev/

## 2.54.1

This release fixes `--pylock` handling to tolerate locked packages with no artifacts and just warn
(if PEX warnings are enabled) that the package is being skipped for lack of artifacts.

* Handle `pylock.toml` packages with no artifacts. (#2888)

## 2.54.0

This release adds a Pex PEX scie for riscv64.

* Add a Pex PEX scie for riscv64. (#2883)

## 2.53.0

This release adds support to `pex3 run` for `--with-requirements` to complement `--with` for
specifying additional run requirements via a requirements file. In addition, `--constraints`
can now be specified to constrain versions with a constraints file.

* Support `-r` & `--constraints` in `pex3 run`. (#2879)

## 2.52.1

This release fixes some cases of creating PEXes from a `--pylock` when no requirements are
specified.

* Fix `--pylock` with no reqs roots calculation. (#2878)

## 2.52.0

This release adds `pex3 run --locked {auto,require}` support for both local and remote scripts. In
either case a sibling `pylock.<script name>.toml` and then a sibling `pylock.toml` are searched for
and, if found, are subsetted with PEP-723 script requirements or explicit `--with` or `--from`
requirements if present.

* Support sibling script locks in `pex3 run`. (#2870)

## 2.51.1

This release fixes a bug in Pex's HTTP server used for serving `pex --docs` and `pex3 docs` when
running on Python 2.7.

Also, `pylock.toml` subsets are now fixed to fully honor subset requirement specifiers and markers.

* Fix HTTP Server for Python 2.7. (#2871)
* Fix pylock.toml subsetting. (#2872)

## 2.51.0

This release augments `pex3 run` with the ability to run both local and remote scripts as well as
augmenting the run environment with additional requirements specified via `--with`.

* Support running both local & remote scripts. (#2861)

## 2.50.4

This release fixes a bug introduced by #2828 that would assign PEX scies a `SCIE_BASE` of the
current user's `PEX_ROOT` at PEX scie build time. PEX scies now only get a custom `SCIE_BASE`
when `--scie-base` or `--runtime-pex-root` are specified when building the PEX scie.

* Fix PEX scie `--runtime-pex-root` handling. (#2866)

## 2.50.3

This release fixes handling of cycles both when exporting Pex lock files to PEP-751 `pylock.toml`
format as well as when creating PEXes from `--pylock` locks with cycles. This should complete the
cycle-handling fix work started in #2835 by @pimdh.

* Fix `pylock.toml` cycle handling. (#2863)

## 2.50.2

This release fixes creating `--scie {eager,lazy}` PEX scies when no specific `--scie-pbs-release` is
specified by upgrading to `science` 0.12.9.

Pex's vendored Pip's vendored certifi's cacert.pem is also updated to that from certifi 2025.8.3
(Good luck parsing that!).

* Update vendored Pip's CA cert bundle. (#2857)
* Fix CPython scies with no `--scie-pbs-release`. (#2859)

## 2.50.1

This release fixes `pex3 run` handling of local project directory requirements. For example, you
can now `pex3 run . -V` in the Pex project directory successfully.

* Fix `pex3 run` for local projects. (#2854)

## 2.50.0

This release introduces the `pex.build_backend.wrap` build backend useable for embedding console
script locks in your project distributions for use by tools like `pex3 run` (see: #2841). Pex
dogfoods this backend to embed its own console script lock for its extras.

* Introduce `pex.build_backend.wrap` build backend. (#2850)

## 2.49.0

This release adds support for `--pip-version 25.2`

* Add support for `--pip-version 25.2`. (#2849)

## 2.48.2

This release brings a fix for Pex entry-point parsing. Previously, entry-points specifying an extra
like `blackd = blackd:patched_main [d]` would be parsed as having the extra as part of the module or
object reference leading to errors when executing the entry point.

* Fix Pex entry-point parsing. (#2846)

## 2.48.1

This release fixes the failure mode of `pex3 run --locked require`. Previously, subsequent runs
with `--locked auto` would not fall back to using no lock, but instead error with a malformed venv
from the failed run prior.

* Fix `pex3 run --locked require` failure mode. (#2843)

## 2.48.0

This release adds support for `pex3 run` akin to `pipx run` and `uvx`. By default,
`pex3 run <tool>` will look for an embedded [PEP-751 `pylock.toml`][PEP-751] in the wheel or sdist
`<tool>` is resolved from and, if found, use that lock to create the tool venv from. More
information is available in the `pex3 run --help` output for the `--locked` option. See the thread
here for the embedded lock idea and ongoing discussion:
https://discuss.python.org/t/pre-pep-add-ability-to-install-a-package-with-reproducible-dependencies

* Add `pex3 run`. (#2841)

## 2.47.0

Support for Python PI. Pex started testing against Python 3.14 on October 26th, 2024 and now
officially advertises support with the 3.14.0rc1 release candidate just published.

* Support Python PI. (#2838)

## 2.46.3

This release brings a fix from @pimdh for `--pylock` handling that allows Pex to work with
`pylock.toml` locks containing dependency cycles.

* Handle cyclic dependencies in pylock.toml (#2835)

## 2.46.2

This release updates vendored Pip's vendored certifi's cacert.pem to that from certifi 2025.7.14 and
fixes the default scie base when `--runtime-pex-root` is used to be a `pex3 cache` managed
directory.

* Update vendored Pip's CA cert bundle. (#2831)
* Re-organize default `--runtime-pex-root` scie base. (#2830)

## 2.46.1

This release follows up on 2.45.3 to ensure `--venv` PEXes also participate in temporary `PEX_ROOT`
cleanup. Previously these leaked the temporary `PEX_ROOT`.

* Fix `--venv` PEXes to clean fallback `PEX_ROOT`. (#2826)

## 2.46.0

This release adds support for setting a custom `--scie-base` when building PEX scies. The default
scie base is the same as used by the scie-jump natively; e.g. `~/.cache/nce` on Linux. When
specifying a custom `--runtime-pex-root`, the scie base now will live under it in the `scie-base`
directory. To specify a custom scie base, `--scie-base` can be used, and it will trump all these
defaults.

* Add `--scie-base` to control the PEX scie cache dir. (#2828)

## 2.45.3

This release fixes a bug introduced in 2.45.2 by #2820 that would cause a temporary `PEX_ROOT` (
these are created when the default `PEX_ROOT` directory is not writeable) to be cleaned up too
early, leading to PEX boot failures.

* Do not clean fallback `PEX_ROOT` prematurely. (#2823)

## 2.45.2

This release fixes a long-standing temporary directory resource leak when running PEXes built with
`--no-pre-install-wheels`.

* Fix temp dir leak on boot of `--no-pre-install-wheels` PEX. (#2820)

## 2.45.1

This release updates vendored Pip's vendored certifi's cacert.pem to that from certifi 2025.7.9.

* Update vendored Pip's CA cert bundle. (#2816)

## 2.45.0

This release adds support for `--scie-assets-base-url` if you've used `science download ...` to set
up a local repository for `ptex`, `scie-jump` and science interpreter providers.

This release also fixes PEX scie creation to use either of `--proxy` or `--cert` if set when
building scies. Previously, these options were only honored when downloading the `science` binary
itself but not when running it subsequently to build scies.

Finally, PEX scies built on Windows for Linux or Mac now should work more often. That said, Windows
is still not officially supported!

* Add `--scie-assets-base-url` & honor `--{proxy,cert}`. (#2811)

## 2.44.0

This release expands PEX scie support on Windows to more cases by changing how the `PEX_ROOT` is
handled for PEX scies on all operating systems. Previously, the `PEX_ROOT` was constrained to be
in a special location inside the scie `nce` cache direcgtory structure. Now PEX scies install their
PEXes inside the normal system `PEX_ROOT` like other PEXes do. This leads to shorted PEX cache paths
that work on more Windows systems in particular.

All that said, Windows is still not officially supported!

* Let PEX scies install PEXes in the `PEX_ROOT`. (#2807)

## 2.43.1

This release fixes PEP-723 script metadata parsing handling of the file encoding of the script.

* Fix PEP-723 script parsing file encoding handling. (#2806)

## 2.43.0

This release adds support for `pex3 wheel [--lock|--pylock] [requirements args] ...`. This
allows resolving and building wheels that satisfy a resolve directly or through a lock. Foreign
targets via `--platform` and `--complete-platform` are supported as well as sub-setting when a lock
is used. This compliments `pex3 download` introduced in Pex 2.41.0.

* Add pex3 wheel for resolving & building wheels. (#2803)

## 2.42.2

This release is a follow-up to 2.42.1 that again attempts a fix for missing `License-Expression`
METADATA in Pex distributions.

* Really fix `License-Expression` METADATA field. (#2800)

## 2.42.1

This release just fixes missing `License-Expression` METADATA in Pex distributions.

* Fix missing `License-Expression` METADATA field. (#2798)

## 2.42.0

This release expands `--platform` support to Windows. Windows is still not officially
supported though!

* Add `--platform` support for Windows. (#2794)

## 2.41.1

This release fixes `pex3 download` to require a `-d` / `--dest-dir` be set.

* Require `--dest-dir` is set for `pex3 download`. (#2793)

## 2.41.0

This release adds support for `pex3 download [--lock|--pylock] [requirements args] ...`. This
allows downloading distributions that satisfy a resolve directly or through a lock. Foreign targets
via `--platform` and `--complete-platform` are supported as well as sub-setting when a lock is
used.

* Add `pex3 download`. (#2791)

## 2.40.3

This release updates vendored Pip's vendored certifi's cacert.pem to that from certifi 2025.6.15.

* Update vendored Pip's CA cert bundle. (#2787)

## 2.40.2

This relase fixes Pex to work in more scenarios on Windows. Windows is still not officially
supported though!

* Fix some Windows cross-drive issues. (#2781)

## 2.40.1

This release fixes `pex --pylock` for locked sdist and wheel artifacts whose locked URL path
basename does not match the optional sdist or wheel `name` field when present. Notably, this fixes
interop with `uv` which appears to use the `name` field to store the normalized name of the wheel
when the wheel name is not normalized already in the index URL basename.

* Fix `--pylock` handling of sdist and wheel `name`. (#2775)

## 2.40.0

This release fills out `--pylock` support with `--pylock-extra` and `--pylock-group` to have Pex
resolve extras and dependency groups defined for a PEP-751 lock. This support only works when Pex
is run under Python 3.8 or newer.

* Support PEP-751 extras and dependency groups. (#2770)

## 2.39.0

This release adds support for `pex --pylock` and `pex3 venv create --pylock` for building PEXes and
venvs from [pylock.toml][PEP-751] locks. In both cases PEX supports subsetting the lock if it
provides `dependencies` metadata for its locked packages, but this metadata is optional in the spec;
so your mileage may vary. If the metadata is not available and was required, Pex will let you know
with an appropriate error post-resolve and pre-building the final PEX or venv.

* Add support for `pex --pylock`. (#2766)

## 2.38.1

This release fixes a long-standing bug parsing requirements files that included other requirements
files.

* Fix requirement file includes relative path handling. (#2764)

## 2.38.0

This release adds support for `pex3 lock export --format pep-751` to export Pex locks in the new
[pylock.toml][PEP-751] format. `pex3 lock export-subset` also supports `pylock.toml` and both
forms of export respect universal locks, leveraging the optional [marker][PEP-751-marker] package
field to make packages installable or not based on the environment the exported lock is used to
install in.

This release does _not_ include support for building PEXes using PEP-751 locks. Add your concrete
use case to [#2756](https://github.com/pex-tool/pex/issues/2756) if you have one.

* Add `pex3 lock export --format pep-751` support. (#2760)

[PEP-751]: https://packaging.python.org/en/latest/specifications/pylock-toml/#pylock-toml-spec
[PEP-751-marker]: https://packaging.python.org/en/latest/specifications/pylock-toml/#packages-marker

## 2.37.0

This release fixes a bug in lock file generation for `--pip-version` >= 25.1 that would omit some
abi3 wheels from locks.

In addition, support for the latest Pip 25.1.1 bugfix release is also added.

* Fix lock support for `--pip-version` >= 25.1. (#2754)

## 2.36.1

This release fixes a few issues with creating Pex locks when source requirements were involved.

Previously, locking VCS requirements would fail for projects with non-normalized project names,
e.g.: PySocks vs its normalized form of pysocks.

Additionally, locking would fail when the requirements were specified at least in part via
requirements files (`-r` / `--requirements`) and there was either a local project or a VCS
requirement contained in the requirements files.

* Fix Pex locking for source requirements. (#2750)

## 2.36.0

This release brings support for creating PEXes that target Android. The Pip 25.1 upgrade in Pex
2.34.0 brought support for resolving Android platform-specific wheels and this releases upgrade
of Pex's vendored packaging to 25.0 brings support for Pex properly dealing with those Android
platform-specific wheels when packaging PEXes and when booting up from a PEX.

* Upgrade to latest packaging for Python 3.8+. (#2748)

## 2.35.0

This release adds support for the `--resume-retries` option available in Pip 25.1. If you configure
Pex to use Pip 25.1 or newer, it will now try to resume incomplete downloads 3 times by default.

* Add support for `--resume-retries` in Pip 25.1. (#2746)

## 2.34.0

This release adds support for `--pip-version 25.1` as well as `--pip-version latest-compatible`. The
`latest-compatible` version will be the latest `--pip-version` supported by Pex compatible with the
current interpreter running Pex.

* Add support for `--pip-version 25.1`. (#2744)

## 2.33.10

This release follows up on the PEX scie argv0 fix in #2738 to further ensure the argv0 of a PEX scie
is the absolute path of the scie. In addition, a regression for PEX scies with no entry point is
fixed, allowing such PEX scies to be used as `--python` targets in Pex invocations.

* Fix PEX scie argv0 to be the scie absolute path. (#2741)
* Fix entrypoint-less PEX scies used as `--python`. (#2742)

## 2.33.9

Fix argv0 in PEX scies to point to the scie itself instead of the unpacked PEX in the nce cache.

* Fix argv0 in PEX scies to point to the scie itself. (#2738)

## 2.33.8

This release only upgrades the Pex PEX scies from Python 3.13.1 to 3.13.3.

The main thrust of the release is to kick the tires on Pex's new build system which is powered by
`uv` + `dev-cmd` and make sure all the action machinery is still working properly.

## 2.33.7

This release fixes `PEX_TOOLS=1 ./path/to/pex` for PEXes using venv-execution and sh-bootstrapping
(that is, built with `--sh-boot --venv=... --include-tools` ). Previously, the `PEX_TOOLS=1` was
ignored if the venv already existed in the `PEX_ROOT` (for instance, if the PEX had already been
run).

* Avoid fast-path in `--sh-boot` script when `PEX_TOOLS=1`. (#2726)

## 2.33.6

Fix PEP-723 script metadata parsing to skip metadata blocks found in multiline strings.

* Fix PEP-723 script metadata parsing. (#2722)

## 2.33.5

This release fixes rate limit issues building CPython Pex scies by bumping to science 0.12.2 which
is fixed to properly support bearer authentication via the `SCIENCE_AUTH_<normalized_host>_BEARER`
environment variable.

* Upgrade to `science` 0.12.2 to fix PBS rate limits. (#2720)

## 2.33.4

This release fixes PEX scies to exclude a ptex binary for `--scie eager` scies saving ~5MB on scies
targeting 64 bit systems.

* Do not include `ptex` in `--scie eager` scies. (#2717)

## 2.33.3

This release fixes Pex Zip64 support such that PEX zips do not use Zip64 extensions unless needed.
Previously, any zip between ~2GB and ~4GB that actually fell under Zip64 limits would still use
Zip64 extensions. This prevented the file from being bootable under Python before the 3.13 release
since the `zipimporter` was not fixed to support ZIp64 extensions until then.

The `--scie-only` option is fixed for the case when the `-o` / `--output-file` name does not end in
`.pex`. Previously there would be no scie (or PEX) output at all!

Finally, this release fixes PEX scies such that, when split, the embedded PEX is both executable and
retains the expected name as provided by `-o` / `--output-file`.

* Enable true Zip64 support. (#2714)
* Fix `--scie-only` for `-o` not ending in `.pex`. (#2715)
* Fix PEX scie contents when split. (#2713)

## 2.33.2

This release fixes PEXes build with root requirements like `foo[bar] foo[baz]` (vs. `foo[bar,baz]`,
which worked already).

* Fix dup requirement extra merging during PEX boot. (#2707)

## 2.33.1

This release fixes a bug in both `pex3 lock subset` and
`pex3 lock {create,sync,update} --elide-unused-requires-dist` for `--style universal` locks whose
locked requirements have dependencies de-selected by the following environment markers:
+ `os_name`
+ `platform_system`
+ `sys_platform`
+ `python_version`
+ `python_full_version`

The first three could lead to errors when the universal lock was generated with `--target-system`s
and the last two could lead to errors when the universal lock was generated with
`--interpreter-constraint`.

* Fix `pex3 lock subset`. (#2684)

## 2.33.0

This release adds support for Pip 25.0.1.

* Add support for `--pip-version 25.0.1`. (#2671)

## 2.32.1

This release fixes a long-standing bug handling development versions of
CPython (any non-tagged release of the interpreter). These interpreters
report a full version of `X.Y.Z+` and the trailing `+` leads to a non
PEP-440 compliant version number. This, in turn, causes issues with the
`packaging` library leading to failures to evaluate markers for these
interpreters which surface as inscrutable Pex errors.

* Fix support for CPython development releases. (#2655)

## 2.32.0

This release adds support for Pip 25.0.

* Add support for `--pip-version 25.0`. (#2652)

## 2.31.0

This release adds `pex3 lock subset <reqs...> --lock existing.lock` for
creating a subset of an existing lock file. This is a fast operation
that just trims un-used locked requirements from the lock but otherwise
leaves the lock unchanged.

* Add support for `pex3 lock subset`. (#2647)

## 2.30.0

This release brings `--sh-boot` support to PEXes with
`--layout {loose,packed}`. Previously, the `--sh-boot` option only took
effect for traditional PEX zip files. Now all PEX output and runtime
schemes, in any combination, can benefit from the reduced boot latency
`--sh-boot` brings on all runs of a PEX after the first.

* Support `--sh-boot` for `--layout {loose,packed}`. (#2645)

## 2.29.0

This release brings 1st class support for newer Pip's
`--keyring-provider` option. Previously you could only use `keyring`
based authentication via `--use-pip-config` and either the
`PIP_KEYRING_PROVIDER` environment variable or Pip config files.
Although using `--keyring-provider import` is generally unusable in the
face of Pex hermeticity strictures, `--keyring-provider subprocess` is
viable; just ensure you have a keyring provider on the `PATH`. You can
read more [here][Pip-KRP-subprocess].

This release also brings [PEP-723][PEP-723] support to Pex locks. You
can now pass `pex3 lock {create,sync,update} --exe <script> ...` to
include the PEP-723 declared script requirements in the lock.

* add `--keyring-provider` flag to configure keyring-based authentication (#2592)
* Support locking PEP-723 requirements. (#2642)

[Pip-KRP-subprocess]: https://pip.pypa.io/en/stable/topics/authentication/#using-keyring-as-a-command-line-application
[PEP-723]: https://peps.python.org/pep-0723

## 2.28.1

This release upgrades `science` for use in building PEX scies with
`--scie {eager,lazy}`. The upgraded `science` fixes issues dealing
handling failed Python distribution downloads and should now be more
robust and clear when downloads fail.

* Upgrade `science` minimum requirement to 0.10.1. (#2637)

## 2.28.0

This release adds Pex `--scie {eager,lazy}` support for Linux ppc64le
and s390x.

* Add `--scie` support for Linux ppc64le and s390x. (#2635)

## 2.27.1

This release fixes a bug in `PEX_ROOT` handling that could manifest
with symlinked `HOME` dirs or more generally symlinked dirs being
parents of the `PEX_ROOT`. Although this was claimed to be fixed in
the Pex 2.20.4 release by #2574, there was one missing case not handled.

* Ensure that the `PEX_ROOT` is always a realpath. (#2626)

## 2.27.0

This release adds a Pex PEX scie for armv7l.

* Add a Pex PEX scie for armv7l. (#2624)

## 2.26.0

This release adds Pex `--scie {eager,lazy}` support for Linux armv7l.

In addition, a spurious warning when using `PEX_PYTHON=pythonX.Y`
against a venv PEX has been fixed.

* Added support for armv7l (#2620)
* Fix incorrect regex for `PEX_PYTHON` precision warning (#2622)

## 2.25.2

This release fixes the `--elide-unused-requires-dist` lock option once
again. The fix in 2.25.1 could lead to locked requirements having only
a partial graph of extras which would allow a subsequent subset of those
partial extras to silently resolve an incomplete set of dependencies.

In addition, the Pex REPL for PEXes without entry points or else when
forced with `PEX_INTERPRETER=1` is now fixed such that readline support
always works. Previously, the yellow foreground color applied to the PS1
and PS2 prompts would interfere with the tracked cursor position in some
Pythons; so the yellow foreground color for those prompts is now
dropped.

* Fix `--elide-unused-requires-dist`: don't expose partial extras. (#2618)
* Fix Pex REPL prompt. (#2617)

## 2.25.1

This is a hotfix release that fixes a bug in the implementation of the
`--elide-unused-requires-dist` lock option introduced in Pex 2.25.0.

* Fix `--elide-unused-requires-dist` for unactivated deps. (#2615)
## 2.25.0

This release adds support for
`pex3 lock {create,sync} --elide-unused-requires-dist`. This new lock
option causes any dependencies of a locked requirement that can never
be activated to be elided from the lock file. This leads to no material
difference in lock file use, but it does cut down on the lock file size.

* Add `--elide-unused-requires-dist` lock option. (#2613)

## 2.24.3

This release fixes a long-standing bug in resolve checking. Previously,
only resolve dependency chains where checked, but not the resolved
distributions that satisfied the input root requirements.

In addition, the 2.24.2 release included a wheel with no compression
(~11MB instead of ~3.5MB). The Pex wheel is now fixed to be compressed.

* Fix resolve check to cover dists satisfying root reqs. (#2610)
* Fix build process to produce a compressed `.whl`. (#2609)

## 2.24.2

This release fixes a long-standing bug in "YOLO-mode" foreign platform
speculative wheel builds. Previously if the speculatively built wheel
had tags that did not match the foreign platform, the process errored
pre-emptively. This was correct for complete foreign platforms, where
all tag information is known, but not for all cases of abbreviated
platforms, where the failure was overly aggressive in some cases. Now
foreign abbreviated platform speculative builds are only rejected when
there is enough information to be sure the speculatively built wheel
definitely cannot work on the foreign abbreviated platform.

* Accept more foreign `--platform` "YOLO-mode" wheels. (#2607)

## 2.24.1

This release fixes `pex3 cache prune` handling of cached Pips.
Previously, performing a `pex3 cache prune` would bump the last access
time of all un-pruned cached Pips artificially. If you ran
`pex3 cache prune` in a daily or weekly cron job, this would mean Pips
would never be pruned.

* Fix `pex3 cache prune` handling of cached Pips. (#2589)

## 2.24.0

This release adds `pex3 cache prune` as a likely more useful Pex cache
management command than the existing `pex3 cache purge`. By default
`pex3 cache prune` prunes any cached items not used for the last 2
weeks and is likely suitable for use as a daily cron job to keep Pex
cache sizes down. The default age of 2 weeks can be overridden by
specifying `--older-than "1 week"` or `--last-access-before 14/3/2024`,
etc. See `pex3 cache prune --help` for more details.

* Support `pex3 cache prune --older-than ...`. (#2586)

## 2.23.0

This release adds support for drawing requirements from
[PEP-735][PEP-735] dependency groups when creating PEXes or lock files.
Groups are requested via `--group <name>@<project dir>` or just
`--group <name>` if the project directory is the current working
directory.

* Add support for PEP-735 dependency groups. (#2584)

[PEP-735]: https://peps.python.org/pep-0735/

## 2.22.0

This release adds support for `--pip-version 24.3.1`.

* Add support for `--pip-version 24.3.1`. (#2582)

## 2.21.0

This release adds support for `--pip-version 24.3`.

* Add support for `--pip-version 24.3`. (#2580)

## 2.20.4

This release carries several bug fixes and a performance improvement for
lock deletes.

Although there were no direct reports in the wild, @iritkatriel noticed
by inspection the Pex `safe_mkdir` utility function would mask any
`OSError` besides `EEXIST`. This is now fixed.

It was observed by @b-x that when `PEX_ROOT` was contained in a
symlinked path, PEXes would fail to execute. The most likely case
leading to this would be a symlinked `HOME` dir. This is now fixed.

This release also fixes a bug where `--pip-log <path>`, used multiple
times in a row against the same file could lead to `pex3 lock` errors.
Now the specified path is always truncated before use and a note has
been added to the option `--help` that using the same `--pip-log` path
in concurrent Pex runs is not supported.

In addition, `pex3 lock {update,sync}` is now optimized for the cases
where all the required updates are deletes. In this case neither Pip nor
the network are consulted leading to speed improvements proportional to
the size of the resolve.

* Fix `safe_mkdir` swallowing non-`EEXIST` errors. (#2575)
* Fix `PEX_ROOT` handling for symlinked paths. (#2574)
* Fix `--pip-log` re-use. (#2570)
* Optimize pure delete lock updates. (#2568)

## 2.20.3

This release fixes both PEX building and lock creation via
`pex3 lock {create,sync}` to be reproducible in more cases. Previously,
if a requirement only available in source form (an sdist, a local
project or a VCS requirement) had a build that was not reproducible due
to either file timestamps (where the `SOURCE_DATE_EPOCH` standard was
respected) or random iteration order (e.g.: the `setup.py` used sets in
certain in-opportune ways), Pex's outputs would mirror the problematic
requirement's non-reproducibility. Now Pex plumbs a fixed
`SOURCE_DATE_EPOCH` and `PYTHONHASHSEED` to all places sources are
built.

* Plumb reproducible build env vars more thoroughly. (#2554)

## 2.20.2

This release fixes an old bug handling certain sdist zips under
Python 2.7 as well missing support for Python 3.13's `PYTHON_COLORS`
env var.

* Fix Zip extraction UTF-8 handling for Python 2.7. (#2546)
* Add repl support for `PYTHON_COLORS`. (#2545)

## 2.20.1

This release fixes Pex `--interpreter-constraint` handling such that
any supplied interpreter constraints which are in principle
unsatisfiable either raise an error or else cause a warning to be issued
when other viable interpreter constraints have also been specified. For
example, `--interpreter-constraint ==3.11.*,==3.12.*` now errors and
`--interpreter-constraint '>=3.8,<3.8' --interpreter-constraint ==3.9.*`
now warns, culling `>3.8,<3.8` and continuing using only `==3.9.*`.

* Pre-emptively cull unsatisfiable interpreter constraints. (#2542)

## 2.20.0

This release adds the `--pip-log` alias for the existing
`--preserve-pip-download-log` option as well as the ability to specify
the log file path. So, to debug a resolve, you can now specify
`--pip-log log.txt` and Pex will deposit the Pip resolve log to
`log.txt` in the current directory for easy tailing or post-resolve
inspection. In addition, the log file itself is more useful in some
cases. When you specify any abbreviated `--platform` targets, those
targets calculated wheel compatibility tags are included in the Pip
log. Also, when multiple targets are specified, their log outputs are
now merged at the end of the resolve in a serialized fashion with
prefixes on each log line indicating which target the log line
corresponds to.

In addition, a race in Pex's PEP-517 implementation that could (rarely)
lead to spurious metadata generation errors or sdist creation errors is
fixed.

* Fix intermittent PEP-517 failures. (#2540)
* Plumb `--pip-version` to Platform tag calculation. (#2538)
* Add the ability to specify the `--pip-log` path. (#2536)

## 2.19.1

This release fixes a regression introduced by #2512 in the 2.19.0
release when building PEXes using abbreviated `--platform` targets.
Instead of failing certain builds that used to succeed, Pex now warns
that the resulting PEX may fail at runtime and that
`--complete-platform` should be used instead.

* Only warn when `--platform` resolves fail tag checks. (#2533)

## 2.19.0

This release adds support for a new `--pre-resolved-dists` resolver as
an alternative to the existing Pip resolver, `--lock` resolver and
`--pex-repository` resolvers. Using `--pre-resolved-dists dists/dir/`
behaves much like `--no-pypi --find-links dists/dir/` except that it is
roughly 3x faster.

* Support `--pre-resolved-dists` resolver. (#2512)

## 2.18.1

This release fixes `--scie-name-style platform-parent-dir` introduced in
#2523. Previously the target platform name also leaked into scies
targeting foreign platforms despite using this option.

* Fix `--scie-name-style platform-parent-dir`. (#2526)

## 2.18.0

This release adds support for `pex3 cache {dir,info,purge}` for
inspecting and managing the Pex cache. Notably, the `pex3 cache purge`
command is safe in the face of concurrent PEX runs, waiting for in
flight PEX runs to complete and blocking new runs from starting once the
purge is in progress. N.B.: when using `pex3 cache purge` it is best to
install Pex with the 'management' extra; e.g.:
`pip install pex[management]`. Alternatively, one of the new Pex scie
binary releases can be used.

In order to release a Pex binary that can support the new `pex3` cache
management commands first class, a set of enhancements to project
locking and scie generation were added. When using `--project` you can
now specify extras; e.g.: `--project ./the/project-dir[extra1,extra2]`.
When creating a Pex scie, you can now better control the output files
using `--scie-only` to ensure no PEX file is emitted and
`--scie-name-style` to control how the scie target platform name is
mixed into the scie output file name. Additionally, you can request one
or more shasum-compatible checksum files be emitted for each scie with
`--scie-hash-alg`.

On the locking front, an obscure bug locking project releases that
contain artifacts that mis-report their version number via their file
name has been fixed.

Finally, the vendored Pip has had its own vendored CA cert bundle
upgraded from that in certifi 2024.7.4 to that in certifi 2024.8.30.

* Fix locking of sdists rejected by Pip. (#2524)
* Add `--scie-only` & `--scie-name-style`. (#2523)
* Support `--project` extras. (#2522)
* Support shasum file gen via `--scie-hash-alg`. (#2520)
* Update vendored Pip's CA cert bundle. (#2517)
* Introduce `pex3 cache {dir,info,purge}`. (#2513)

## 2.17.0

This release brings support for overriding the versions of setuptools
and wheel Pex bootstraps for non-vendored Pip versions (the modern ones
you select with `--pip-version`) using the existing
`--extra-pip-requirement` option introduced in the [2.10.0 release](
https://github.com/pex-tool/pex/releases/tag/v2.10.0).

* Support custom setuptools & wheel versions. (#2514)

## 2.16.2

This release brings a slew of small fixes across the code base.

When creating locks for foreign platforms,
`pex3 lock {create,update,sync}` now allows locking sdists that use
PEP-517 build backends that do not support the
`prepare_metadata_for_build_wheel` hook and whose product is a wheel not
compatible with the foreign platform. This is decidedly a corner case,
but one encountered with the `mesonpy` build backend which seems to have
traction in the scientific computing world in particular.

The recent re-vamp of the PEX REPL is now fixed to respect common
conventions for controlling terminal output via the `NO_COLOR`,
`FORCE_COLOR` and `TERM` environment variables.

The examples in the [buildingpex docs](
https://docs.pex-tool.org/buildingpex.html) had bit-rotted. They have
been refreshed and now all work.

Finally, both the Pex CLI and PEX files support the ambient OS standards
for user cache directories. Instead of using `~/.pex` as the default
`PEX_ROOT` cache location, the default is now `~/.cache/pex` on Linux (
but respecting `XDG_CACHE_HOME` when set) and `~/Library/Caches/pex` on
Mac.

* Lock sdists in more cases for foreign platforms. (#2508)
* Respect `NO_COLOR`, `FORCE_COLOR` & `TERM=dumb`. (#2507)
* Fix `buildingpex.rst` examples. (#2506)
* Respect OS user cache location conventions. (#2505)

## 2.16.1

This release fixes the PEX repl for [Python Standalone Builds][PBS]
Linux CPython PEX scies. These PEXes ship using a version of libedit
for readline support that does not support naive use of ansi terminal
escape sequences for prompt colorization.

* Fix PEX repl prompt for Linux PBS libedit. (#2503)

## 2.16.0

This release adds support for `--venv-system-site-packages` when
creating a `--venv` PEX and `--system-site-packages` when creating a
venv using the `pex-tools` / `PEX_TOOLS=1` `venv` command or when using
the `pex3 venv create` command. Although this breaks PEX hermeticity, it
can be the most efficient way to ship partial PEX venvs created with
`--exclude`s to machines that have the excluded dependencies already
installed in the site packages of a compatible system interpreter.

* Support `--system-site-packages` when creating venvs. (#2500)

## 2.15.0

This release enhances the REPL your PEX drops into when it either
doesn't have an entry point or you force interpreter mode with the
`PEX_INTERPRETER` environment variable. There is now clear indication
you are running in a PEX hermetic environment and a `pex` command
added to the REPL that you can use to find out more details about the
current PEX environment.

* Add PEX info to the PEX repl. (#2496)

## 2.14.1

This release fixes `--inject-env` when used in combination with a
`--scie-busybox` so that the injected environment variable can be
overridden at runtime like it can form a traditional PEX.

In addition, running a PEX with the Python interpreter `-i` flag or
`PYTHONINSPECT=x` in the environment causes the PEX to enter the
Python REPL after evaluating the entry point, if any.

* Allow `--inject-env` overrides for `--scie-busybox`. (#2490)
* Fix PEXes for `-i` / `PYTHONINSPECT=x`. (#2491)

## 2.14.0

This release brings support for creating PEX scies for PEXes targeting
[PyPy][PyPy]. In addition, for PEX scies targeting CPython, you can now
specify `--scie-pbs-stripped` to select a stripped version of the
[Python Standalone Builds][PBS] CPython distribution embedded in your
scie to save transfer bandwidth and disk space at the cost of losing
Python debug symbols.

Finally, support is added for `--scie-busybox` to turn your PEX into a
multi-entrypoint [BusyBox][BusyBox]-like scie. This support is
documented in depth at https://docs.pex-tool.org/scie.html

* Support `--scie` for PyPy & support stripped CPython. (#2488)
* Add support for `--scie-busybox`. (#2468)

[PyPy]: https://pypy.org/
[BusyBox]: https://www.busybox.net/

## 2.13.1

This release fixes the `--scie` option to support building a Pex PEX
scie with something like `pex pex -c pex --venv --scie eager -o pex`.
Previously, due to the output filename of `pex` colliding with fixed
internal scie lift manifest file names, this would fail.

* Handle all output file names when building scies. (#2484)

## 2.13.0

This release improves error message detail when there are failures in
Pex sub-processes. In particular, errors that occur in `pip download`
when building a PEX or creating a lock file now give more clear
indication of what went wrong.

Additionally, this release adds support for `--pip-version 24.2`.

* Add more context for Job errors. (#2479)
* Add support for `--pip-version 24.2`. (#2481)

## 2.12.1

This release refreshes the root CA cert bundle used by
`--pip-version vendored` (which is the default Pip Pex uses for
Python `<3.12`) from [certifi 2019.9.11](
https://pypi.org/project/certifi/2019.9.11/)'s `cacert.pem` to
[certifi 2024.7.4](https://pypi.org/project/certifi/2024.7.4/)'s
`cacert.pem`. This refresh addresses at least [CVE-2023-37920](
https://nvd.nist.gov/vuln/detail/CVE-2023-37920) and was spearheaded by
a contribution from [Nash Kaminski](https://github.com/gs-kamnas) in
https://github.com/pex-tool/pip/pull/12. Thank you, Nash!

* Update vendored Pip's CA cert bundle. (#2476)

## 2.12.0

This release adds support for passing `--site-packages-copies` to both
`pex3 venv create ...` and `PEX_TOOLS=1 ./my.pex venv ...`. This is
similar to `pex --venv --venv-site-packages-copies ...` except that
instead of preferring hard links, a copy is always performed. This is
useful to disassociate venvs you create using Pex from Pex's underlying
`PEX_ROOT` cache.

This release also adds partial support for statically linked CPython. If
the statically linked CPython is `<3.12`, the default Pip (
`--pip-version vendored`) used by Pex will work. All newer Pips will not
though, until Pip 24.2 is released with the fix in
https://github.com/pypa/pip/pull/12716 and Pex releases with support for
`--pip-version 24.2`.

* Add `--site-packages-copies` for external venvs. (#2470)
* Support statically linked CPython. (#2472)

## 2.11.0

This release adds support for creating native PEX executables that
contain their own hermetic CPython interpreter courtesy of
[Python Standalone Builds][PBS] and the [Science project][scie].

You can now specify `--scie {eager,lazy}` when building a PEX file and
one or more native executable PEX scies will be produced (one for each
platform the PEX supports). These PEX scies are single file
executables that look and behave like traditional PEXes, but unlike
PEXes they can run on a machine with no Python interpreter available.

[PBS]: https://github.com/astral-sh/python-build-standalone
[scie]: https://github.com/a-scie

* Add `--scie` option to produce native PEX exes. (#2466)

## 2.10.1

This release fixes a long-standing bug in Pex parsing of editable
requirements. This bug caused PEXes containing local editable project
requirements to fail to import those local editable projects despite
the fact the PEX itself contained them.

* Fix editable requirement parsing. (#2464)

## 2.10.0

This release adds support for injecting requirements into the isolated
Pip PEXes Pex uses to resolve distributions. The motivating use case
for this is to use the feature Pip 23.1 introduced for forcing
`--keyring-provider import`.

Pex already supported using a combination of the following to force
non-interactive use of the keyring:
1. A `keyring` script installation that was on the `PATH`
2. A `--pip-version` 23.1 or newer.
3. Specifying `--use-pip-config` to pass `--keyring-provider subprocess`
   to Pip.

You could not force `--keyring-provider import` though, since the Pips
Pex uses are themselves hermetic PEXes without access to extra
installed  keyring requirements elsewhere on the system. With
`--extra-pip-requirement` you can now do this with the primary benefit
over `--keyring-provider subprocess` being that you do not need to add
the username to index URLs. This is ultimately because the keyring CLI
requires username whereas the API does not; but see
https://pip.pypa.io/en/stable/topics/authentication/#keyring-support for
more information.

* Add support for `--extra-pip-requirement`. (#2461)

## 2.9.0

This release adds support for Pip 24.1.2.

* Add support for `--pip-version 24.1.2`. (#2459)

## 2.8.1

This release fixes the `bdist_pex` distutils command to use the
`--project` option introduced by #2455 in the 2.8.0 release. This
change produces the same results for existing invocations of
`python setup.py bdist_pex` but allows new uses passing locked project
requirements (either hashed requirement files or Pex lock files) via
`--pex-args`.

* Fix `bdist_pex` to use `--project`. (#2457)

## 2.8.0

This release adds a new `--override` option to resolves that ultimately
use an `--index` or `--find-links`. This allows you to override
transitive dependencies when you have determined they are too narrow and
that expanding their range is safe to do. The new `--override`s and the
existing `--exclude`s can now also be specified when creating or syncing
a lock file to seal these dependency modifications into the lock.

This release also adds a new `--project` option to `pex` and
`pex3 lock {create,sync}` that improves the ergonomics of locking a
local Python project and then creating PEX executables for that project
using its locked requirements.

In addition, this release fixes the `bdist_pex` distutils command that
ships with Pex to work when run under `tox` and Python 3.12 by improving
Pex venv creation robustness when creating venvs that include Pip.

* Add support for `--override`. (#2431)
* Support `--project` locking and PEX building. (#2455)
* Improve venv creation robustness when adding Pip. (#2454)

## 2.7.0

This release adds support for Pip 24.1.1.

* Add support for `--pip-version 24.1.1`. (#2451)

## 2.6.3

There are no changes to Pex code or released artifacts over 2.6.1 or
2.6.2, just a further fix to the GitHub Releases release process which
#2442 broke and #2444 only partially fixed.

* Fix GitHub Releases deployment. (#2448)

## 2.6.2

> [!NOTE]
> Although 2.6.2 successfully released to [PyPI](
> https://pypi.org/project/pex/2.6.2/), it failed to release to GitHub
> Releases (neither the Pex PEX nor the pex.pdf were published.) You
> can use Pex 2.6.3 instead which has no Pex code changes over this
> release.

There are no changes to Pex code or released artifacts over 2.6.1, just
a fix to the GitHub Releases release process which #2442 broke.

* Fix GitHub Releases deployment. (#2444)

## 2.6.1

> [!NOTE]
> Although 2.6.1 successfully released to [PyPI](
> https://pypi.org/project/pex/2.6.1/), it failed to release to GitHub
> Releases (neither the Pex PEX nor the pex.pdf were published.) You
> can use Pex 2.6.3 instead which has no Pex code changes over this
> release.

This release improves error messages when attempting to read invalid
metadata from distributions such that the problematic distribution is
always identified.

* Improve errors for invalid distribution metadata. (#2443)

## 2.6.0

This release adds support for [PEP-723](
https://peps.python.org/pep-0723) script metadata in `--exe`s. For such
a script with metadata describing its dependencies or Python version
requirements, running the script is as simple as
`pex --exe <script> -- <script args>` and building a PEX encapsulating
it as simple as `pex --exe <script> --output <PEX file>`.

* Add support for PEP-723 script metadata to `--exe`. (#2436)

## 2.5.0

This release brings support for Python 3.13 and `--pip-version 24.1`,
which is the first Pip version to support it.

* Support `--pip-version 24.1` and Python 3.13. (#2435)

## 2.4.1

This release fixes `pex --only-binary X --lock ...` to work with lock
files also created with `--only-binary X`. The known case here is a
`--style universal` lock created with `--only-binary X` to achieve a
partially wheel-only universal lock.

* Fix `pex --only-binary X --lock ...`. (#2433)

## 2.4.0

This release brings new support for preserving arguments passed to the
Python interpreter (like `-u` or `-W ignore`) either via running a PEX
via Python from the command line like `python -u my.pex` or via a
shebang with embedded Python arguments like `#!/usr/bin/python -u`.

In addition, PEXes can now be built with `--inject-python-args` similar
to the existing `--inject-args` but sealing in arguments to pass to
Python instead. When both explicitly passed Python interpreter arguments
and injected Python interpreter arguments are specified, the injected
arguments appear first on the synthesized command line and the
explicitly passed arguments appear last so that the explicit arguments
can trump (which is how Python handles this).

Several bugs existing in the `--exclude` implementation since its
introduction are now fixed and the feature is greatly improved to act on
excludes eagerly, never traversing them in the resolve process; thus
avoiding downloads associated with them as well as potentially failing
metadata extraction & wheel builds for ill-behaved sdists.

Finally, a bug was fixed in `pex3 lock export` for lock files containing
either locked VCS requirements or locked local project directories.
Previously, these were exported with a `<project name>==<version>`
requirement, which lost fidelity with the input requirement. Now they
are exported with their original requirement form. Further, since the
`--hash` of these styles of locked requirement are unuseable outside
Pex, a new `--format` option of `pip-no-hashes` is introduced for the
adventurous.

* Implement support for preserving and injecting Python args. (#2427)
* Fix `--exclude`. (#2409)
* Fix `pex3 lock export` handling of exotic reqs. (#2423)

## 2.3.3

This release fixes `pex3 lock create` support for `--pip-version`s
23.3.1 and newer. Previously, when locking using indexes that serve
artifacts via re-directs, the resulting lock file would contain the
final re-directed URL instead of the originating index artifact URL.
This could lead to issues when the indexes re-direction scheme changed
or else if authentication parameters in the original index URL were
stripped in the Pip logs.

* Fix artifact URL recording for `pip>=23.3`. (#2421)

## 2.3.2

This release fixes a regression for users of gevent monkey patching. The
fix in #2356 released in Pex 2.1.163 lead to these users receiving
spurious warnings from the gevent monkey patch system about ssl being
patched too late.

* Delay import of ssl in `pex.fetcher`. (#2417)

## 2.3.1

This release fixes Pex to respect lock file interpreter constraints and
target systems when downloading artifacts.

* Fix lock downloads to use all lock info. (#2396)

## 2.3.0

This release introduces `pex3 lock sync` as a higher-level tool that
can be used to create and maintain a lock as opposed to using a
combination of `pex3 lock create` and `pex3 lock update`. When there is
no existing lock file, `pex3 lock sync --lock lock.json ...` is
equivalent to `pex3 lock create --output lock.json ...`, it creates a
new lock. On subsequent uses however,
`pex3 lock sync --lock lock.json ...` updates the lock file minimally to
meet any changed requirements or other changed lock settings.

This release also fixes `pex --no-build --lock ...` to work with lock
files also created with `--no-build`. The known case here is a
`--style universal` lock created with `--no-build` to achieve a
wheel-only universal lock.

This release includes a fix to clarify the conditions under which
`--requierements-pex` can be used to combine the third party
dependencies from a pre-built PEX into a new PEX; namely, that the PEXes
must use the same value for the `--pre-install-wheels` option.

Finally, this release fixes `pex3 venv` to handle venvs created by
Virtualenv on systems that distinguish `purelib` and `platlib`
site-packages directories. Red Hat distributions are a notable example
of this.

* Implement pex3 lock sync. (#2373)
* Guard against mismatched `--requirements-pex`. (#2392)
* Fix `pex --no-build --lock ...`. (#2390)
* Fix Pex to handle venvs with multiple site-packages dirs. (#2383)

## 2.2.2

This release fixes `pex3 lock create` to handle `.tar.bz2` and `.tgz`
sdists in addition to the officially sanctioned `.tar.gz` and (less
officially so) `.zip` sdists.

* Handle `.tar.bz2` & `.tgz` sdists when locking. (#2380)

## 2.2.1

This release trims down the size of the Pex wheel on PyPI and the
released Pex PEX by about 20KB by consolidating image resources.

This release also fixes the release process to remove a window of time
when several links would be dead on at https://docs.pex-tool.org that
pointed to release artifacts that were not yet fully deployed.

* Fix release ordering of the doc site deploy. (#2369)
* Trim embedded doc image assets. (#2368)

## 2.2.0

This release adds tools to interact with Pex's new embedded offline
documentation. You can browse those docs with `pex --docs` or, more
flexibly, with `pex3 docs`. See `pex3 docs --help` for all the options
available.

This release also returns to [SemVer](https://semver.org/) versioning
practices. Simply, you can expect 3 things from Pex version numbers:

+ The first component (the major version) will remain 2 as long as
  possible. Pex tries very hard to never break existing users and to
  allow them to upgrade without fear of breaking. This includes not
  breaking Python compatibility. In Pex 2, Python 2.7 is supported as
  well as Python 3.5+ for both CPython and PyPy. Pex will only continue
  to add support for new CPython and PyPy releases and never remove
  support for already supported Python versions while the major version
  remains 2.
+ The second component (the minor version) will be incremented whenever
  a release adds a feature. Since Pex is a command line tool only (not
  a library), this means you can expect a new subcommand, a new option,
  or a new allowable option value was added. Bugs might also have been
  fixed.
+ The third component (the patch version) indicates only bugs were
  fixed.

You can expect the minor version to get pretty big going forward!

* Add `pex --docs` and several `pex3 docs` options. (#2365)

## 2.1.164

This release moves Pex documentation from https://pex.readthedocs.io to
https://docs.pex-tool.org. While legacy versioned docs will remain
available at RTD in perpetuity, going forward only the latest Pex
release docs will be available online at the https://docs.pex-tool.org
site. If you want to see the Pex docs for the version you are currently
using, Pex now supports the `pex3 docs` command which will serve the
docs for your Pex version locally, offline, but with full functionality,
including search.

* Re-work Pex documentation. (#2362)

## 2.1.163

This release fixes Pex to work in certain OS / SSL environments where it
did not previously. In particular, under certain Fedora distributions
using certain Python Build Standalone interpreters.

* Create SSLContexts in the main thread. (#2356)

## 2.1.162

This release adds support for `--pip-version 24.0` as well as fixing a
bug in URL encoding for artifacts in lock files. Notably, torch's use of
local version identifiers (`+cpu`) combined with their find links page
at https://download.pytorch.org/whl/torch_stable.html would lead to
`pex3 lock create` errors.

* Add support for Pip 24.0. (#2350)
* Fix URL escaping for lock artifacts. (#2349)

## 2.1.161

This release adds support for `--only-wheel <project name>` and
`--only-build <project name>` to allow finer control over which
distribution artifacts are resolved when building a PEX or creating or
updating a lock file. These options correspond to Pip's `--only-binary`
and `--no-binary` options with project name arguments.

* Plumb Pip's `--{no,only}-binary`. (#2346)

## 2.1.160

This release adds the ability for `pex3 lock update` to replace
requirements in a lock or delete them from the lock using
`-R` / `--replace-project` and `-d` / `--delete-project`, respectively.

* Lock updates support deleting & replacing reqs. (#2335)

## 2.1.159

This release brings a fix for leaks of Pex's vendored `attrs` onto the
`sys.path` of PEXes during boot in common usage scenarios.

* Fix vendored attrs `sys.path` leak. (#2328)

## 2.1.158

This release adds support for tab completion to all PEX repls running
under Pythons with the `readline` module available. This tab completion
support is on-par with newer Python REPL out of the box tab completion
support.

* Add tab-completion support to PEX repls. (#2321)

## 2.1.157

This release fixes a bug in `pex3 lock update` for updates that leave
projects unchanged whose primary artifact is an sdist.

* Fix lock updates for locks with sdist bystanders. (#2325)

## 2.1.156

This release optimizes wheel install overhead for warm caches. Notably,
this speeds up warm boot for PEXes containing large distributions like
PyTorch as well as creating venvs from them.

* Lower noop wheel install overhead. (#2315)

## 2.1.155

This release brings support for `--pip-version 23.3.2` along with
optimizations that reduce built PEX size for both `--include-tools` and
`--venv` PEXes (which includes the Pex PEX) as well as reduce PEX build
time for `--pre-install-wheels` PEXes (the default) and PEX cold first
boot time for `--no-pre-install-wheels` PEXes that use more than one
parallel install job.

* Add support for Pip 23.3.2. (#2307)
* Remove `Pip.spawn_install_wheel` & optimize. (#2305)
* Since we no longer use wheel code, remove it. (#2302)

## 2.1.154

This release brings three new features:

1.  When creating PEXes without specifying an explicit
    `--python-shebang`, an appropriate shebang is chosen correctly in
    more cases than previously and a warning is emitted when the shebang
    chosen cannot be guaranteed to be correct. The common case this
    helps select the appropriate shebang for is PEXes built using
    `--platform` or `--complete-platform`.
2.  PEXes can now be created with `--no-pre-install-wheels` to cut down
    PEX build times with a tradeoff of roughly 10% greater boot overhead
    upon the 1st execution of the PEX file. For PEXes with very large
    dependency sets (machine learning provides common cases), the build
    time savings can be dramatic.
3.  PEXes can now be told to install dependencies at runtime on 1st
    execution using parallel processes using `--max-install-jobs` at PEX
    build time or by setting the `PEX_MAX_INSTALL_JOBS` environment
    variable at runtime.

The last two features come with complicated tradeoffs and are turned off
by default as a result. If you think they might help some of your use
cases, there is more detail in the command line help for
`--no-pre-install-wheels` and `--max-install-jobs` as well as in the
`pex --help-variables` output for `PEX_MAX_INSTALL_JOBS`. You can also
find a detailed performance analysis in #2292 for the extreme cases of
very small and very large PEXes. In the end though, experimenting is
probably your best bet.

* Use appropriate shebang for multi-platform PEXes. (#2296)
* Add support for --no-pre-install-wheels and --max-install-jobs. (#2298)

## 2.1.153

This release fixes Pex runtime `sys.path` scrubbing to do less work and
thus avoid errors parsing system installed distributions with bad
metadata.

* Remove Pex runtime scrubbing dist discovery. (#2290)

## 2.1.152

This release fixes the computation of the hash of the code within a PEX
when nested within directories, a bug introduced in 2.1.149.

* Exclude pyc dirs, not include, when hashing code (#2286)

## 2.1.151

This release brings support for a new `--exclude <req>` PEX build option
that allows eliding selected resolved distributions from the final PEX.
This is an advanced feature that will, in general, lead to broken PEXes
out of the box; so read up on the `--exclude` command line help to make
sure you understand the consequences.

This release also brings a fix for `--inject-env` that ensures the
specified environment variables are always injected to the PEX at
runtime regardless of the PEX entry point exercised.

* Implement support for `--exclude <req>`. (#2281)
* Relocate environment variable injection to before the interpreter is run (#2260)

## 2.1.150

This release brings support for `--pip-version 23.3.1`.

* Add support for Pip 23.3.1. (#2276)

## 2.1.149

Fix `--style universal` lock handing of `none` ABI wheels with a
specific Python minor version expressed in their wheel tag. There are
not many of these in the wild, but a user discovered the case of
python-forge 18.6.0 which supplies 1 file on PyPI:
`python_forge-18.6.0-py35-none-any.whl`.

* Fix universal lock handling of the none ABI. (#2270)

## 2.1.148

Add support to the Pex for checking if built PEXes are valid Python
zipapps. Currently, Python zipapps must reside in 32 bit zip files due
to limitations of the stdlib `zipimport` module's `zipimporter`; so this
check amounts to a check that the built PEX zip does not use ZIP64
extensions. The check is controlled with a new
`--check {none,warn,error}` option, defaulting to warn.

* Add --check support for zipapps. (#2253)

## 2.1.147

Add support for `--use-pip-config` to allow the Pip Pex calls to read
`PIP_*` env vars and Pip configuration files. This can be particularly
useful for picking up custom index configuration (including auth).

* Add support for --use-pip-config. (#2243)

## 2.1.146

This release brings a fix by new contributor @yjabri for the `__pex__`
import hook that gets it working properly for `--venv` mode PEXes.

* Fix non executable venv sys path bug (#2236)

## 2.1.145

This release broadens the range of the `flit-core` build system Pex uses
to include 3.x, which is known to work for modern Python versions and
Pex's existing build configuration.

* Raise the flit-core limit for Python 3 (#2229)

## 2.1.144

This release fixes Pex to build PEX files with deterministic file order
regardless of the operating system / file system the PEX was built on.

* Traverse directories in stable order when building a PEX (#2220)

## 2.1.143

This release fixes Pex to work by default under eCryptFS home dirs.

* Guard against too long filenames on eCryptFS. (#2217)

## 2.1.142

This release fixes Pex to handle Pip backtracking due to sdist build
errors when attempting to extract metadata.

* Handle backtracking due to sdist build errors. (#2213)

## 2.1.141

This release fixes the Pex CLI to work when run from a read-only
installation. A prominent example of this comes in certain nix setups.

* Fix the Pex CLI to work when installed read-only. (#2205)

## 2.1.140

This release fixes several spurious warnings emitted for Python 3.11 and
3.12 users and fixes a leak of Pex's vendored `attrs` when using the
`__pex__` import hook.

* Eliminate warnings for default use. (#2188)
* Cleanup sys.path after __pex__ is imported. (#2189)

## 2.1.139

This release brings support for Python 3.12 and Pip 23.2 which is the
minimum required Pip version for Python 3.12. N.B.: Since Pip 23.2
requires Python 3.7 or newer, multiplatform PEX files and locks that
support Python 3.12 will not also be able to support Python 2.7, 3.5
or 3.6 even though Pex continues to support those versions generally.

In addition, two new options for adding local project source files to
a pex are added: `-P/--package` and `-M/--module`. Importantly, you can
use the options instead of the existing `-D/--sources-directory` when
you have a project with code at the top level (i.e.: not in a `src/`
subdirectory for example) intermixed with other files you prefer not to
include in the PEX. See `pex --help` for more details on using these new
options.

Finally, an internal API is fixed that allows for Lambdex files to
include versions of `attrs` incompatible with Pex's own vendored version.

* Add official support for Python 3.12 / Pip 23.2. (#2176)
* Add support for selecting packages and modules. (#2181)
* Fix `pex.pex_bootstrapper.bootstrap_pex_env` leak. (#2184)

## 2.1.138

This release brings fixes for two obscure corner cases.

Previously, if you used `--venv` PEXes in the default symlinked
site-packages mode that contained first party code in a namespace
package shared with 3rd-party dependencies the first party code would
contaminate the Pex installed wheel cache for one of the 3rd-party
dependencies in PEX.

Even more obscure (the only known issue was in Pex's own CI), if you
ran the Pex CLI concurrently using two different `--pip-version`
arguments, you may have seen spurious Pip HTTP errors that found an
invalid `Content-Type: Unknown` header.

* Isolate the Pip cache per Pip version. (#2164)
* Fix symlinked venv ns-package calcs. (#2165)

## 2.1.137

This release fixes a long-standing bug in lock file creation for exotic
locking scenarios pulling the same project from multiple artifact
sources (any mix of URLs, VCS and local project directories).

* Fix inter-artifact comparisons. (#2152)

## 2.1.136

This release adds the `pex3 lock export-subset` command. This is a
version of `pex3 lock export` that also accepts requirements arguments
allowing just a subset of the lock satisfying the given requirements to
be exported.

* Add `pex3 lock export-subset`. (#2145)

## 2.1.135

This release brings support for `pex3 venv {inspect,create}` for working
with venvs directly using Pex. Previously, a PEX built with
`--include-tools` (or `--venv`) had the capability of turning itself
into a venv but the new `pex3 venv create` command can do this for any
PEX file with the addition of a few new features:

1.  The venv can now be created directly from requirements producing no
    intermediate PEX file.
2.  The venv can be created either from a PEX file or a lock file. A
    subset of either of those can be chosen by also supplying
    requirements.
3.  Instead of creating a full-fledged venv, just the site-packages can
    be exported (without creating an intermediate venv). This "flat"
    layout is used by several prominent runtimes - notably AWS Lambda
    -and emulates `pip install --target`. This style layout can also be
    zipped and prefixed. Additionally, it supports `--platform` and
    `--complete-platform` allowing creation of, for example, an AWS
    Lambda (or Lambda Layer) deployment zip on a non-Linux host.

Additionally, this release adds support for Pip 23.1.1 and 23.1.2.

* Add Support for Pip 23.1.1. (#2133)
* Introduce pex3 venv inspect. (#2135)
* Introduce pex3 venv create. (#2140)
* Add support for Pip 23.1.2. (#2142)

## 2.1.134

This release fixes `pex3 lock create` gathering of sdist metadata for
PEP-517 build backends with non-trivial `get-requires-for-build-wheel`
requirements.

* Use get_requires_for_build_wheel for metadata prep. (#2129)

## 2.1.133

This release fixes `--venv` mode PEX venv script shebangs for some
scenarios using Python `<=3.7` interpreters.

* Fix venv script shebangs. (#2122)

## 2.1.132

This release brings support for the latest Pip release with
`--pip-version 23.1` or by using new support for pinning to the latest
version of Pip supported by Pex with `--pip-version latest`.

* Add support for Pip 23.1 (#2114)
* Add support for `--pip-version latest`. (#2116)

## 2.1.131

This release fixes some inconsistencies in Pex JSON output across the
Python 2/3 boundary and in handling of venv collisions when using the
venv Pex tool.

* Stabilize JSON output format across Python 2/3. (#2106)
* Support `--pip` overrides via PEX deps. (#2107)

## 2.1.130

This release fixes a regression locking certain complex cases of direct
and transitive requirement interactions as exemplified in #2098.

* Guard lock analysis against Pip-cached artifacts. (#2103)

## 2.1.129

This release fixes a bug downloading a VCS requirement from a lock when
the ambient Python interpreter used to run Pex does not meet the
`Requires-Python` constraint of the VCS requirement.

* Fix VCS lock downloads to respect target. (#2094)

## 2.1.128

This release fixes a regression introduced in Pex 2.1.120 that caused
`--no-venv-site-packages-copies` (the default when using `--venv`) to
be ignored for both zipapp PEXes (the default) and `--layout packed`
PEXes.

* Fix regression in venv symlinking. (#2090)

## 2.1.127

This release fixes `--lock` resolve sub-setting for local project
requirements.

* Fix lock subsetting for local projects. (#2085)

## 2.1.126

This release fixes a long-standing (> 4 years old!) concurrency bug
when building the same sdist for the 1st time and racing another Pex
process doing the same sdist build.

* Guard against racing sdist builds. (#2080)

## 2.1.125

This release makes `--platform` and `--complete-platform` resolves and
locks as permissive as possible. If such a resolve or lock only has an
sdist available for a certain project, that sdist will now be used if it
builds to a wheel compatible with the specified foreign platform(s).

* Attempt "cross-builds" of sdists for foreign platforms. (#2075)

## 2.1.124

This release adds support for specifying `--non-hermetic-venv-scripts`
when building a `--venv` PEX. This can be useful when integrating with
frameworks that do setup via `PYTHONPATH` manipulation.

Support for Pip 23.0.1 and setuptools 67.4.0 is added via
`--pip-version 23.0.1`.

Additionally, more work towards hardening Pex against rare concurrency
issues in its atomic directory handling is included.

* Introduce `--non-hermetic-venv-scripts`. (#2068)
* Wrap inter-process locks in in-process locks. (#2070)
* Add support for Pip 23.0.1. (#2072)

## 2.1.123

This release fixes a few `pex3 lock create` bugs.

There was a regression introduced in Pex 2.1.122 where projects that
used a PEP-518 `[build-system] requires` but specified no corresponding
`build-backend` would fail to lock.

There were also two long-standing issues handling more exotic direct
reference URL requirements. Source archives with names not following the
standard Python sdist naming scheme of
`<project name>-<version>.{zip,tar.gz}` would cause a lock error. An
important class of these is provided by GitHub's magic source archive
download URLs. Also, although local projects addressed with Pip
proprietary support for pure local path requirements would lock, the
same local projects addressed via
`<project name> @ file://<local project path>` would also cause a lock
error. Both of these cases are now fixed and can be locked successfully.

When locking with an `--interpreter-constraint`, any resolve traversing
wheels using the `pypyXY` or `cpythonXY` python tags would cause the
lock to error. Wheels with this form of python tag are now handled
correctly.

* Handle `[build-system]` with no build-backend. (#2064)
* Handle locking all direct reference URL forms. (#2060)
* Fix python tag handling in IC locks. (#2061)

## 2.1.122

This release fixes posix file locks used by Pex internally and enhances
lock creation to support locking sdist-only C extension projects that do
not build on the current platform. Pex is also updated to support
`--pip-version 22.3.1` and `--pip-version 23.0`, bringing it up to date
with the latest Pip's available.

* Support the latest Pip releases: 22.3.1 & 23.0 (#2056)
* Lock sdists with `prepare-metadata-for-build-wheel`. (#2053)
* Fix `execute_parallel` "leaking" a thread. (#2052)

## 2.1.121

This release fixes two bugs brought to light trying to interoperate with
Poetry projects.

* Support space separated markers in URL reqs. (#2039)
* Handle `file://` URL deps in distributions. (#2041)

## 2.1.120

This release completes the `--complete-platform` fix started in Pex
2.1.116 by #1991. That fix did not work in all cases but now does.

PEXes run in interpreter mode now support command history when the
underlying interpreter being used to run the PEX does; use the
`PEX_INTERPRETER_HISTORY` bool env var to turn this on.

Additionally, PEXes built with the combination
`--layout loose --venv --no-venv-site-packages-copies` are fixed to be
robust to moves of the source loose PEX directory.

* Fix loose `--venv` PEXes to be robust to moves. (#2033)
* Fix interpreter resolution when using `--complete-platform` with
    `--resolve-local-platforms` (#2031)
* Support REPL command history. (#2018)

## 2.1.119

This release brings two new features. The venv pex tool now just warns
when using `--compile` and there is a `*.pyc` compile error instead of
failing to create the venv. Also, a new `PEX_DISABLE_VARIABLES` env var
knob is added to turn off reading all `PEX_*` env vars from the
environment.

* Ignore compile error for `PEX_TOOLS=1` (#2002)
* Add `PEX_DISABLE_VARIABLES` to lock down a PEX run. (#2014)

## 2.1.118

This is a very tardy hotfix release for a regression introduced in Pex
2.1.91 by #1785 that replaced `sys.argv[0]` with its fully resolved
path. This prevented introspecting the actual file path used to launch
the PEX which broke BusyBox-alike use cases.

There is also a new `--non-hermetic-scripts` option accepted by the
`venv` tool to allow running console scripts with `PYTHONPATH`
adjustments to the `sys.path`.

* Remove un-needed realpathing of `sys.argv[0]`. (#2007)
* Add `--non-hermetic-scripts` option to `venv` tool. (#2010)

## 2.1.117

This release fixes a bug introduced in Pex 2.1.109 where the released
Pex PEX could not be executed by PyPy interpreters. More generally, any
PEX created with interpreter constraints that did not specify the Python
implementation, e.g.: `==3.8.*`, were interpreted as being CPython
specific, i.e.: `CPython==3.8.*`. This is now fixed, but if the
intention of a constraint like `==3.8.*` was in fact to restrict to
CPython only, interpreter constraints need to say so now and use
`CPython==3.8.*` explicitly.

* Fix interpreter constraint parsing. (#1998)

## 2.1.116

This release fixes a bug in `--resolve-local-platforms` when
`--complete-platform` was used.

* Check for `--complete-platforms` match when
    `--resolve-local-platforms` (#1991)

## 2.1.115

This release brings some attention to the `pex3 lock export` subcommand
to make it more useful when interoperating with `pip-tools`.

* Sort requirements based on normalized project name when exporting
    (#1992)
* Use raw version when exporting (#1990)

## 2.1.114

This release brings two fixes for `--venv` mode PEXes.

* Only insert `""` to head of `sys.path` if a venv PEX runs in
    interpreter mode (#1984)
* Map pex python path interpreter to realpath when creating venv dir
    hash. (#1972)

## 2.1.113

This is a hotfix release that fixes errors installing wheels when there
is high parallelism in execution of Pex processes. These issues were a
regression introduced by #1961 included in the 2.1.112 release.

* Restore AtomicDirectory non-locked good behavior. (#1974)

## 2.1.112

This release brings support for the latest Pip release and includes some
internal changes to help debug intermittent issues some users are seeing
that implicate what may be file locking related bugs.

* Add support for `--pip-version 22.3`. (#1953)

## 2.1.111

This release fixes resolving requirements from a lock using arbitrary
equality (`===`).

In addition, you can now "inject" runtime environment variables and
arguments into PEX files such that, when run, the PEX runtime ensures
those environment variables and command line arguments are passed to the
PEXed application. See [PEX Recipes](
https://docs.pex-tool.org/recipes.html#uvicorn-and-other-customizable-application-servers
)
for more information.

* Fix lock resolution to handle arbitrary equality. (#1951)
* Support injecting args and env vars in a PEX. (#1948)

## 2.1.110

This release fixes Pex runtime `sys.path` scrubbing for cases where Pex
is not the main entry point. An important example of this is in Lambdex
where the AWS Lambda Python runtime packages (`boto3` and `botocore`)
are leaked into the PEX runtime `sys.path`.

* Fix `sys.path` scrubbing. (#1946)

## 2.1.109

This release brings musllinux wheel support and a fix for a regression
introduced in Pex 2.1.105 by #1902 that caused `PEX_PATH=` (an exported
`PEX_PATH` with an empty string value) to raise an error in almost all
use cases.

* Vendor latest packaging; support musllinux wheels. (#1937)
* Don't treat `PEX_PATH=` as `.` like other PATHS. (#1938)

## 2.1.108

This release fixes a latent PEX boot performance bug triggered by
requirements with large extras sets.

* Fix slow PEX boot time when there are many extras. (#1929)

## 2.1.107

This release fixes an issue handling credentials in git+ssh VCS urls
when creating locks.

* Fix locks for git+ssh with credentials. (#1923)

## 2.1.106

This release fixes a long-standing bug in handling direct reference
requirements with a local version component.

* Unquote path component of parsed url requirements (#1920)

## 2.1.105

This is a fix release which addresses issues related to build time
work_dir creation, virtualenv, and sh_boot support.

In the unlikely event of a UUID collision in atomic workdir creation,
pex could overwrite an existing directory and cause a corrupt state.
When building a shell bootable `--sh-boot` pex the `--runtime-pex-root`
was not always respected based on the condition of the build
environment, and the value of the PEX_ROOT.

* Fail on atomic_directory work_dir collision. (#1905)
* Use raw_pex_root when constructing sh_boot pexes. (#1906)
* Add support for offline downloads (#1898)

## 2.1.104

This release brings a long-awaited upgrade of the Pip Pex uses, but
behind a `--pip-version 22.2.2` flag you must opt in to. Pex will then
use that version of Pip if it can (your Pex operations target Python
`>=3.7`) and warn and fall back to the older vendored Pip (20.3.4) if it
can't. To turn the need to fall back to older Pip from a warning into a
hard error you can also specify `--no-allow-pip-version-fallback`.

The `pex3 lock update` command now gains the ability to update just the
index and find links repos the lock's artifacts originate from by using
a combination of `--no-pypi`, `--index` & `--find-links` along with
`--pin` to ensure the project versions stay pinned as they are in the
lockfile and just the repos they are downloaded from is altered. Consult
the CLI `--help` for `--fingerprint-mismatch {ignore,warn,error}` to
gain more control over repo migration behavior.

There are several bug fixes as well dealing with somewhat esoteric
corner cases involving changing a PEX `--layout` from one form to
another and building artifacts using certain interpreters on macOS 11.0
(aka: 10.16).

* Add support for Pip 22.2.2. (#1893)
* Make lock update sensitive to artifacts. (#1887)
* Ensure locally built wheel is consumable locally. (#1886)
* Ensure `--output` always overwrites destination. (#1883)

## 2.1.103

This release fixes things such that pex lockfiles can be created and
updated using the Pex PEX when local projects are involved.

* Fix `pex3 lock ...` when run from the Pex PEX. (#1874)

## 2.1.102

This is a hotfix release that fixes a further corner missed by #1863 in
the Pex 2.1.101 release whereby Pex would fail to install
platform-specific packages on Red Hat based OSes.

In addition, an old but only newly discovered bug in
`--inherit-path={prefer,fallback}` handling is fixed. Previously only
using `PEX_INHERIT_PATH={prefer,fallback}` at runtime worked properly.

In the process of fixing the old `--inherit-path={prefer,fallback}` bug,
also fix another old bug handling modern virtualenv venvs under Python
2.7 during zipapp execution mode PEX boots.

* Fix wheel installs: account for purelib & platlib. (#1867)
* Fix `--inhert-path` handling. (#1871)
* Error using pex + `virtualenv>=20.0.0` + python 2.7 (#992)

## 2.1.101

This release fixes a corner-case revealed by python-certifi-win32 1.6.1
that was not previously handled when installing certain distributions.

* Make wheel install `site-packages` detection robust. (#1863)

## 2.1.100

This release fixes a hole in the lock creation `--target-system` feature
added in #1823 in Pex 2.1.95.

* Fix lock creation `--target-system` handling. (#1858)

## 2.1.99

This release fixes a concurrency bug in the `pex --lock ...` artifact
downloading.

* Fix `pex --lock ...` concurrent download errors. (#1854)

## 2.1.98

This releases fixes regressions in foreign `--platform` handling and
artifact downloading introduced by #1787 in Pex 2.1.91 and #1811 in
2.1.93.

In addition, PEXes can now be used as `sys.path` entries. Once on the
`sys.path`, via `PYTHONPATH` or other means, the code in the PEX can be
made importable by first importing `__pex__` either as its own
stand-alone import statement; e.g.: `import __pex__; import psutil` or
as a prefix of the code to import from the PEX; e.g.:
`from __pex__ import psutil`.

* Tags should be patched for `--platform`. (#1846)
* Add support for importing from PEXes. (#1845)
* Fix artifact downloads for foreign platforms. #1851

## 2.1.97

This release patches a hole left by #1828 in the Pex 2.1.95 release
whereby, although you could run a PEX under a too-long PEX_ROOT you
could not build a PEX under a tool-long PEX_ROOT.

* Avoid ENOEXEC for Pex internal `--venv`s. (#1843)

## 2.1.96

This is a hotfix release that fixes `--venv` mode `PEX_EXTRA_SYS_PATH`
propagation introduced in Pex 2.1.95 to only apply to `sys.executable`
and not other Pythons.

* Fix `--venv` `PEX PEX_EXTRA_SYS_PATH` propagation. (#1837)

## 2.1.95

This release brings two new `pex3 lock` features for `--style universal`
locks.

By default, universal locks are created to target all operating systems.
This can cause problems when you only target a subset of operating
systems and a lock transitive dependency that is conditional on an OS
you do not target is not lockable. The new
`--target-system {linux,mac,windows}` option allows you to restrict the
set of targeted OSes to work around this sort of issue. Since PEX files
currently only support running on Linux and Mac, specifying
`--target-system linux --target-system mac` is a safe way to
pre-emptively avoid these sorts of locking issues when creating a
universal lock.

Previously you could not specify the `--platform`s or
`--complete-platform`s you would be using later to build PEXes with when
creating a universal lock. You now can, and Pex will verify the
universal lock can support all the specified platforms.

As is usual there are also several bug fixes including properly
propagating `PEX_EXTRA_SYS_PATH` additions to forked Python processes,
fixing `pex3 lock export` to only attempt to export for the selected
target and avoiding too long shebang errors for `--venv` mode PEXes in a
robust way.

* Fix `PEX_EXTRA_SYS_PATH` propagation. (#1832)
* Fix `pex3 lock export`: re-use `--lock` resolver. (#1831)
* Avoid ENOEXEC for `--venv` shebangs. (#1828)
* Check lock can resolve platforms at creation time. (#1824)
* Support restricting universal lock target os. (#1823)

## 2.1.94

This is a hotfix release that fixes a regression introduced in Pex
2.1.93 downloading certain sdists when using `pex --lock ...`.

* Fix `pex --lock ...` handling of sdists. (#1818)

## 2.1.93

This release brings several new features in addition to bug fixes.

When creating a PEX the entry point can now be any local python script
by passing `--exe path/to/python-script`.

The `pex3 lock update` command now supports a `-dry-dun check` mode that
exits non-zero to indicate that a lock needs updating and the
`-p / --project` targeted update arguments can now be new projects to
attempt to add to the lock.

On the bug fix front, traditional zipapp mode PEX files now properly
scrub `sys.displayhook` and `sys.excepthook` and their teardown sequence
has now been simplified fixing logging to stderr late in teardown.

Finally, `pex3 lock create` now logs when requirement resolution is
taking a long time to provide some sense of progress and suggest generic
remedies and `pex --lock` now properly handles authentication.

* Support adding new requirements in a lock update. (#1797)
* Add `pex3 lock update --dry-run check` mode. (#1799)
* Universal locks no longer record a `platform_tag`. (#1800)
* Support python script file executable. (#1807)
* Fix PEX scrubbing to account for sys.excepthook. (#1810)
* Simplify `PEX` teardown / leave stderr in tact. (#1813)
* Surface pip download logging. (#1808)
* Use pip download instead or URLFetcher. (#1811)

## 2.1.92

This release adds support for locking local projects.

* Add support for local project locking. #1792

## 2.1.91

This release fixes `--sh-boot` mode PEXes to have an argv0 and exported
`PEX` environment variable consistent with standard Python boot PEXes;
namely the absolute path of the originally invoked PEX.

* Fix `--sh-boot` argv0. (#1785)

## 2.1.90

This release fixes Pex handling of sdists to be atomic and also fixes
lock files to be emitted ending with a newline. In addition, many typos
in Pex documentation were fixed in a contribution by Kian-Meng Ang.

* Ensure Pip cache operations are atomic. (#1778)
* Ensure that lockfiles end in newlines. (#1774)
* Fix typos (#1773)

## 2.1.89

This release brings official support for CPython 3.11 and PyPy 3.9 as
well as long needed robust runtime interpreter selection.

* Select PEX runtime interpreter robustly. (#1770)
* Upgrade PyPy checking to latest. (#1767)
* Add 3.11 support. (#1766)

## 2.1.88

This release is a hotfix for 2.1.86 that handles unparseable `~/.netrc`
files gracefully.

* Just warn when `~/.netrc` can't be loaded. (#1763)

## 2.1.87

This release fixes `pex3 lock create` to handle relative `--tmpdir`.

* Fix lock save detection to be more robust. (#1760)

## 2.1.86

This release fixes an oversight in lock file use against secured custom
indexes and find links repos. Previously credentials were passed during
the lock creation process via either `~/.netrc` or via embedded
credentials in the custom indexes and find links URLs Pex was configured
with. But, at lock use time, these credentials were not used. Now
`~/.netrc` entries are always used and embedded credentials passed via
custom URLS at lock creation time can be passed in the same manner at
lock use time.

* Support credentials in URLFetcher. (#1754)

## 2.1.85

This PyCon US 2022 release brings full support for Python interpreter
emulation when a PEX is run in interpreter mode (without an entry point
or else when forced via `PEX_INTERPRETER=1`).

A special thank you to Loren Arthur for contributing the fix in the
Pantsbuild sprint at PyCon.

* PEX interpreters should support all underlying Python interpreter
    options. (#1745)

## 2.1.84

This release fixes a bug creating a PEX from a `--lock` when pre-release
versions are involved.

* Fix `--lock` handling of pre-release versions. (#1742)

## 2.1.83

This releases fixes a bug creating `--style universal` locks with
`--interpreter-constraint` configured when the ambient interpreter does
not match the constraints and the resolved lock includes sdist primary
artifacts.

* Fix universal lock creation for ICs. (#1738)

## 2.1.82

This is a hotfix release for a regression in prerelease version handling
introduced in the 2.1.81 release by #1727.

* Fix prerelease handling when checking resolves. (#1732)

## 2.1.81

This release brings a fix to Pex resolve checking for distributions
built by setuptools whose `Requires-Dist` metadata does not match a
distibutions project name exactly (i.e.: no PEP-503 `[._-]`
normalization was performed).

* Fix Pex resolve checking. (#1727)

## 2.1.80

This release brings another fix for pathologically slow cases of lock
creation as well as a new `--sh-boot` feature for creating PEXes that
boot via `/bin/sh` for more resilience across systems with differing
Python installations as well as offering lower boot latency.

* Support booting via `/bin/sh` with `--sh-boot`. (#1721)
* Fix more pathologic lock creation slowness. (#1723)

## 2.1.79

This release fixes `--lock` resolving for certain cases where extras are
involved as well as introducing support for generating and consuming
portable `--find-links` locks using `-path-mapping`.

* Fix `--lock` resolver extras handling. (#1719)
* Support canonicalizing absolute paths in locks. (#1716)

## 2.1.78

This release fixes missing artifacts in non-`strict` locks.

* Don't clear lock link database during analysis. (#1712)

## 2.1.77

This release fixes pathologically slow cases of lock creation as well as
introducing support for `--no-compression` to allow picking the
time-space tradeoff you want for your PEX zips.

* Fix pathologic lock creation slowness. (#1707)
* Support uncompressed PEXes. (#1705)

## 2.1.76

This release finalizes spurious deadlock handling in `--lock` resolves
worked around in #1694 in Pex 2.1.75.

* Fix lock_resolver to use BSD file locks. (#1702)

## 2.1.75

This release fixes a deadlock when building PEXes in parallel via the
new `--lock` flag.

* Avoid deadlock error when run in parallel. (#1694)

## 2.1.74

This release fixes multiplatform `--lock` resolves for sdists that are
built to multiple platform specific wheels, and it also introduces
support for VCS requirements in locks.

* Add support for locking VCS requirements. (#1687)
* Fix `--lock` for multiplatform via sdists. (#1689)

## 2.1.73

This is a hotfix for various PEX issues:

1.  `--requirements-pex` handling was broken by #1661 in the 2.1.71
    release and is now fixed.
2.  Creating `universal` locks now works using any interpreter when the
    resolver version is the `pip-2020-resolver`.
3.  Building PEXes with `--lock` resolves that contain wheels with build
    tags in their names now works.

* Fix `--requirements-pex`. (#1684)
* Fix universal locks for the `pip-2020-resolver`. (#1682)
* Fix `--lock` resolve wheel tag parsing. (#1678)

## 2.1.72

This release fixes an old bug with `--venv` PEXes initially executed
with either `PEX_MODULE` or `PEX_SCRIPT` active in the environment.

* Fix venv creation to ignore ambient PEX env vars. (#1669)

## 2.1.71

This release fixes the instability introduced in 2.1.68 by switching to
a more robust means of determining venv layouts. Along the way it
upgrades Pex internals to cache all artifacts with strong hashes (
previously sha1 was used). It's strongly recommended to upgrade or use
the exclude `!=2.1.68,!=2.1.69,!=2.1.70` when depending on an open-ended
Pex version range.

* Switch Pex installed wheels to `--prefix` scheme. (#1661)

## 2.1.70

This is another hotfix release for 2.1.68 that fixes a bug in `*.data/*`
file handling for installed wheels which is outlined in [PEP
427](https://peps.python.org/pep-0427/#installing-a-wheel-distribution-1-0-py32-none-any-whl)

* Handle `*.data/*` RECORD entries not existing. (#1644)

## 2.1.69

This is a hotfix release for a regression introduced in 2.1.68 for a
narrow class of `--venv` `--no-venv-site-packages-copies` mode PEXes
with special contents on the `PEX_PATH`.

* Fix venv creation for duplicate symlinked dists. (#1639)

## 2.1.68

This release brings a fix for installation of additional data files in
PEX venvs (More on additional data files
[here](https://setuptools.pypa.io/en/latest/deprecated/distutils/setupscript.html?highlight=data_files#installing-additional-files))
as well as a new venv install `--scope` that can be used to create fully
optimized container images with PEXed applications (See how to use this
feature
[here](https://docs.pex-tool.org/recipes.html#pex-app-in-a-container)).

* Support splitting venv creation into deps & srcs. (#1634)
* Fix handling of data files when creating venvs. (#1632)

## 2.1.67

This release brings support for `--platform` arguments with a
3-component PYVER portion. This supports working around
`python_full_version` environment marker evaluation failures for
`--platform` resolves by changing, for example, a platform of
`linux_x86_64-cp-38-cp38` to `linux_x86_64-cp-3.8.10-cp38`. This is
likely a simpler way to work around these issues than using the
`--complete-platform` facility introduced in 2.1.66 by #1609.

* Expand `--platform` syntax: support full versions. (#1614)

## 2.1.66

This release brings a new `--complete-platform` Pex CLI option that can
be used instead of `--platform` when more detailed foreign platform
specification is needed to satisfy a resolve (most commonly, when
`python_full_version` environment markers are in-play). This, paired
with the new `pex3 interpreter inspect` command that can be used to
generate complete platform data on the foreign platform machine being
targeted, should allow all foreign platform PEX builds to succeed
exactly as they would if run on that foreign platform as long as
pre-built wheels are available for that foreign platform.

Additionally, PEXes now know how to set a usable process name when the
PEX contains the `setproctitle` distribution. See
[here](https://docs.pex-tool.org/recipes.html#long-running-pex-applications-and-daemons)
for more information.

* Add support for `--complete-platform`. (#1609)
* Introduce `pex3 interpreter inspect`. (#1607)
* Use setproctitle to sanitize `ps` info. (#1605)
* Respect `PEX_ROOT` in `PEXEnvironment.mount`. (#1599)

## 2.1.65

This release really brings support for mac universal2 wheels. The fix
provided by 2.1.64 was partial; universal2 wheels could be resolved at
build time, but not at runtime.

* Upgrade vendored packaging to 20.9. (#1591)

## 2.1.64

This release brings support for mac universal2 wheels.

* Update vendored Pip to 386a54f0. (#1589)

## 2.1.63

This release fixes spurious collision warnings & errors when building
venvs from PEXes that contain multiple distributions contributing to the
same namespace package.

* Allow for duplicate files in venv population. (#1572)

## 2.1.62

This release exposes three Pip options as Pex options to allow building
PEXes for more of the Python distribution ecosystem:

1.  `--prefer-binary`: To prefer older wheels to newer sdists in a
    resolve which can help avoid problematic builds.
2.  `--[no]-use-pep517`: To control how sdists are built: always using
    PEP-517, always using setup.py or the default, always using
    whichever is appropriate.
3.  `--no-build-isolation`: To allow distributions installed in the
    environment to be seen during builds of sdists. This allows working
    around distributions with undeclared build dependencies by
    pre-installing them in the environment before running Pex.

* Expose more Pip options. (#1561)

## 2.1.61

This release fixes a regression in Pex `--venv` mode compatibility with
distributions that are members of a namespace package that was
introduced by #1532 in the 2.1.57 release.

* Merge packages for `--venv-site-packages-copies`. (#1557)

## 2.1.60

This release fixes a bug that prevented creating PEXes when duplicate
compatible requirements were specified using the pip-2020-resolver.

* Fix Pex to be duplicate requirement agnostic. (#1551)

## 2.1.59

This release adds the boolean option `--venv-site-packages-copies` to
control whether `--venv` execution mode PEXes create their venv with
copies (hardlinks when possible) or symlinks. It also fixes a bug that
prevented Python 3.10 interpreters from being discovered when
`--interpreter-constraint` was used.

* Add knob for `--venv` site-packages symlinking. (#1543)
* Fix Pex to identify Python 3.10 interpreters. (#1545)

## 2.1.58

This release fixes a bug handling relative `--cert` paths.

* Always pass absolute cert path to Pip. (#1538)

## 2.1.57

This release brings a few performance improvements and a new
`venv` pex-tools `--remove` feature that is useful for
creating optimized container images from PEX files.

* Do not re-hash installed wheels. (#1534)
* Improve space efficiency of `--venv` mode. (#1532)
* Add venv `--remove {pex,all}` option. (#1525)

## 2.1.56

* Fix wheel install hermeticity. (#1521)

## 2.1.55

This release brings official support for Python 3.10 as well as fixing
<https://docs.pex-tool.org> doc generation and fixing help for
`pex-tools` / `PEX_TOOLS=1 ./my.pex` pex tools invocations that have too
few arguments.

* Add official support for Python 3.10 (#1512)
* Always register global options. (#1511)
* Fix RTD generation by pinning docutils low. (#1509)

## 2.1.54

This release fixes a bug in `--venv` creation that could mask deeper
errors populating PEX venvs.

* Fix `--venv` mode short link creation. (#1505)

## 2.1.53

This release fixes a bug identifying certain interpreters on macOS
Monterey.

Additionally, Pex has two new features:

1.  It now exposes the `PEX` environment variable inside running PEXes
    to allow application code to both detect it's running from a PEX
    and determine where that PEX is located.
2.  It now supports a `--prompt` option in the `venv` tool to allow for
    customization of the venv activation prompt.

* Guard against fake interpreters. (#1500)
* Add support for setting custom venv prompts. (#1499)
* Introduce the `PEX` env var. (#1495)

## 2.1.52

This release makes a wider array of distributions resolvable for
`--platform` resolves by inferring the `platform_machine` environment
marker corresponding to the requested `--platform`.

* Populate `platform_machine` in `--platform` resolve. (#1489)

## 2.1.51

This release fixes both PEX creation and `--venv` creation to handle
distributions that contain scripts with non-ascii characters in them
when running in environments with a default encoding that does not
contain those characters under PyPy3, Python 3.5 and Python 3.6.

* Fix non-ascii script shebang re-writing. (#1480)

## 2.1.50

This is another hotfix of the 2.1.48 release's `--layout` feature that
fixes identification of `--layout zipapp` PEXes that have had their
execute mode bit turned off. A notable example is the Pex PEX when
downloaded from <https://github.com/pex-tool/pex/releases>.

* Fix zipapp layout identification. (#1448)

## 2.1.49

This is a hotfix release that fixes the new `--layout {zipapp,packed}`
modes for PEX files with no user code & just third party dependencies
when executed against a `$PEX_ROOT` where similar PEXes built with the
old `--not-zip-safe` option were run in the past.

* Avoid re-using old ~/.pex/code/ caches. (#1444)

## 2.1.48

This releases introduces the `--layout` flag for selecting amongst the
traditional zipapp layout as a single PEX zip file and two new directory
tree based formats that may be useful for more sophisticated deployment
scenarios.

The `--unzip` / `PEX_UNZIP` toggles for PEX runtime execution are now
the default and deprecated as explicit options as a result. You can
still select the venv runtime execution mode via the `--venv` /
`PEX_VENV` toggles though.

* Remove zipapp execution mode & introduce `--layout`. (#1438)

## 2.1.47

This is a hotfix release that fixes a regression for `--venv` mode PEXes
introduced in #1410. These PEXes were not creating new venvs when the
PEX was unconstrained and executed with any other interpreter than the
interpreter the venv was first created with.

* Fix `--venv` mode venv dir hash. (#1428)
* Clarify PEX_PYTHON & PEX_PYTHON_PATH interaction. (#1427)

## 2.1.46

This release improves PEX file build reproducibility and requirement
parsing of environment markers in Pip's proprietary URL format.

Also, the `-c` / `--script` / `--console-script` argument now supports
non-Python distribution scripts.

Finally, new contributor @blag improved the README.

* Fix Pip proprietary URL env marker handling. (#1417)
* Un-reify installed wheel script shebangs. (#1410)
* Support deterministic repository extract tool. (#1411)
* Improve examples and add example subsection titles (#1409)
* support any scripts specified in `setup(scripts=...)`
    from setup.py. (#1381)

## 2.1.45

This is a hotfix release that fixes the `--bdist-all` handling in the
`bdist_pex` distutils command that regressed in 2.1.43 to only create a
bdist for the first discovered entry point.

* Fix `--bdist-all` handling multiple console_scripts (#1396)

## 2.1.44

This is a hotfix release that fixes env var collisions (introduced in
the Pex 2.1.43 release by #1367) that could occur when invoking Pex with
environment variables like `PEX_ROOT` defined.

* Fix Pip handling of internal env vars. (#1388)

## 2.1.43

* Fix dist-info metadata discovery. (#1376)
* Fix `--platform` resolve handling of env markers. (#1367)
* Fix `--no-manylinux`. (#1365)
* Allow `--platform` resolves for current interpreter. (#1364)
* Do not suppress pex output in bdist_pex (#1358)
* Warn for PEX env vars unsupported by venv. (#1354)
* Fix execution modes. (#1353)
* Fix Pex emitting warnings about its Pip PEX venv. (#1351)
* Support more verbose output for interpreter info. (#1347)
* Fix typo in recipes.rst (#1342)

## 2.1.42

This release brings a bugfix for macOS interpreters when the
MACOSX_DEPLOYMENT_TARGET sysconfig variable is numeric as well as a
fix that improves Pip execution environment isolation.

* Fix MACOSX_DEPLOYMENT_TARGET handling. (#1338)
* Better isolate Pip. (#1339)

## 2.1.41

This release brings a hotfix from @kaos for interpreter identification
on macOS 11.

* Update interpreter.py (#1332)

## 2.1.40

This release brings proper support for pyenv shim interpreter
identification as well as a bug fix for venv mode.

* Fix Pex venv mode to respect `--strip-pex-env`. (#1329)
* Fix pyenv shim identification. (#1325)

## 2.1.39

A hotfix that fixes a bug present since 2.1.25 that results in infinite
recursion in PEX runtime resolves when handling dependency cycles.

* Guard against cyclic dependency graphs. (#1317)

## 2.1.38

A hotfix that finishes work started in 2.1.37 by #1304 to align Pip
based resolve results with `--pex-repository` based resolve results for
requirements with '.' in their names as allowed by PEP-503.

* Fix PEX direct requirements metadata. (#1312)

## 2.1.37

* Fix Pex isolation to avoid temporary pyc files. (#1308)
* Fix `--pex-repository` requirement canonicalization. (#1304)
* Spruce up `pex` and `pex-tools` CLIs with uniform `-V` / `--version`
    support and default value display in help. (#1301)

## 2.1.36

This release brings a fix for building sdists with certain macOS
interpreters when creating a PEX file that would then fail to resolve on
PEX startup.

* Add support for `--seed verbose`. (#1299)
* Fix bytecode compilation race in PEXBuilder.build. (#1298)
* Fix wheel building for certain macOS system interpreters. (#1296)

## 2.1.35

This release hardens a few aspects of `--venv` mode PEXes.
An infinite re-exec loop in venv `pex` scripts is fixed and
the `activate` family of scripts in the venv is fixed.

* Improve resolve error information. (#1287)
* Ensure venv pex does not enter a re-exec loop. (#1286)
* Expose Pex tools via a pex-tools console script. (#1279)
* Fix auto-created `--venv` core scripts. (#1278)

## 2.1.34

Beyond bugfixes for a few important edge cases, this release includes
new support for @argfiles on the command line from @jjhelmus. These
can be useful to overcome command line length limitations. See:
<https://docs.python.org/3/library/argparse.html#fromfile-prefix-chars>.

* Allow cli arguments to be specified in a file (#1273)
* Fix module entrypoints. (#1274)
* Guard against concurrent re-imports. (#1270)
* Ensure Pip logs to stderr. (#1268)

## 2.1.33

* Support console scripts found in the PEX_PATH. (#1265)
* Fix Requires metadata handling. (#1262)
* Fix PEX file reproducibility. (#1259)
* Fix venv script shebang rewriting. (#1260)
* Introduce the repository PEX_TOOL. (#1256)

## 2.1.32

This is a hotfix release that fixes `--venv` mode shebangs being too
long for some Linux environments.

* Guard against too long `--venv` mode shebangs. (#1254)

## 2.1.31

This release primarily hardens Pex venvs fixing several bugs.

* Fix Pex isolation. (#1250)
* Support pre-compiling a venv. (#1246)
* Support venv relocation. (#1247)
* Fix `--runtime-pex-root` leak in pex bootstrap. (#1244)
* Support venvs that can outlive their base python. (#1245)
* Harden Pex interpreter identification. (#1248)
* The `pex` venv script handles entrypoints like PEX.
    (#1242)
* Ensure PEX files aren't symlinked in venv. (#1240)
* Fix venv pex script for use with multiprocessing. (#1238)

## 2.1.30

This release fixes another bug in `--venv` mode when PEX_PATH is
exported in the environment.

* Fix `--venv` mode to respect PEX_PATH. (#1227)

## 2.1.29

This release fixes bugs in `--unzip` and `--venv` mode PEX file
execution and upgrades to the last release of Pip to support Python 2.7.

* Fix PyPy3 `--venv` mode. (#1221)
* Make `PexInfo.pex_hash` calculation more robust. (#1219)
* Upgrade to Pip 20.3.4 patched. (#1205)

## 2.1.28

This is another hotfix release to fix incorrect resolve post-processing
failing otherwise correct resolves.

* Pex resolver fails to evaluate markers when post-processing resolves
    to identify which dists satisfy direct requirements. (#1196)

## 2.1.27

This is another hotfix release to fix a regression in Pex
`--sources-directory` handling of relative paths.

* Support relative paths in `Chroot.symlink`. (#1194)

## 2.1.26

This is a hotfix release that fixes requirement parsing when there is a
local file in the CWD with the same name as the project name of a remote
requirement to be resolved.

* Requirement parsing handles local non-dist files. (#1190)

## 2.1.25

This release brings support for a `--venv` execution mode to complement
`--unzip` and standard unadorned PEX zip file execution modes. The
`--venv` execution mode will first install the PEX file into a virtual
environment under `${PEX_ROOT}/venvs` and then re-execute itself from
there. This mode of execution allows you to ship your PEXed application
as a single zipfile that automatically installs itself in a venv and
runs from there to eliminate all PEX startup overhead on subsequent runs
and work like a "normal" application.

There is also support for a new resolution mode when building PEX files
that allows you to use the results of a previous resolve by specifying
it as a `-pex-repository` to resolve from. If you have many applications
sharing a requirements.txt / constraints.txt, this can drastically speed
up resolves.

* Improve PEX repository error for local projects. (#1184)
* Use symlinks to add dists in the Pex CLI. (#1185)
* Suppress `pip debug` warning. (#1183)
* Support resolving from a PEX file repository. (#1182)
* PEXEnvironment for a DistributionTarget. (#1178)
* Fix plumbing of 2020-resolver to Pip. (#1180)
* Platform can report supported_tags. (#1177)
* Record original requirements in PEX-INFO. (#1171)
* Tighten requirements parsing. (#1170)
* Type BuildAndInstallRequest. (#1169)
* Type AtomicDirectory. (#1168)
* Type SpawnedJob. (#1167)
* Refresh and type OrderedSet. (#1166)
* PEXEnvironment recursive runtime resolve. (#1165)
* Add support for `-r` / `--constraints` URL to the CLI. (#1163)
* Surface Pip dependency conflict information. (#1162)
* Add support for parsing extras and specifiers. (#1161)
* Support project_name_and_version metadata. (#1160)
* docs: fix simple typo, original -> original (#1156)
* Support a `--venv` mode similar to `--unzip` mode. (#1153)
* Remove redundant dep edge label info. (#1152)
* Remove our reliance on packaging's LegacyVersion. (#1151)
* Implement PEX_INTERPRETER special mode support. (#1149)
* Fix PexInfo.copy. (#1148)

## 2.1.24

This release upgrades Pip to 20.3.3 + a patch to fix Pex resolves using
the `pip-legacy-resolver` and `--constraints`. The Pex package is also
fixed to install for Python 3.9.1+.

* Upgrade to a patched Pip 20.3.3. (#1143)
* Fix python requirement to include full 3.9 series. (#1142)

## 2.1.23

This release upgrades Pex to the latest Pip which includes support for
the new 2020-resolver (see:
<https://pip.pypa.io/en/stable/user_guide/#resolver-changes-2020>) as
well as support for macOS BigSur. Although this release defaults to the
legacy resolver behavior, the next release will deprecate the legacy
resolver and support for the legacy resolver will later be removed to
allow continuing Pip upgrades going forward. To switch to the new
resolver, use: `--resolver-version pip-2020-resolver`.

* Upgrade Pex to Pip 20.3.1. (#1133)

## 2.1.22

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
* Add a venv tool. (#1128)
* Remove long deprecated support for _pex module. (#1135)
* Add an interpreter tool. (#1131)
* Escape venvs unless PEX_INHERIT_PATH is requested. (#1130)
* Improve `PythonInterpreter` venv support. (#1129)
* Add support for PEX runtime tools & an info tool. (#1127)
* Exclusive atomic_directory always unlocks. (#1126)
* Fix `PythonInterpreter` binary normalization. (#1125)
* Add a `requires_dists` function. (#1122)
* Add an `is_exe` helper. (#1123)
* Fix req parsing for local archives & projects. (#1121)
* Improve PEXEnvironment constructor ergonomics. (#1120)
* Fix `safe_open` for single element relative paths.
    (#1118)
* Add URLFetcher IT. (#1116)
* Implement full featured requirement parsing. (#1114)
* Fix `--help-variables` docs. (#1113)
* Switch from optparse to argparse. (#1083)

## 2.1.21

* Fix `iter_compatible_interpreters` with `path`. (#1110)
* Fix `Requires-Python` environment marker mapping. (#1105)
* Fix spurious `InstalledDistribution` env markers. (#1104)
* Deprecate `-R`/`--resources-directory`. (#1103)
* Fix ResourceWarning for unclosed `/dev/null`. (#1102)
* Fix runtime vendoring bytecode compilation races. (#1099)

## 2.1.20

This release improves interpreter discovery to prefer more recent patch
versions, e.g. preferring Python 3.6.10 over 3.6.8.

We recently regained access to the docsite, and
<https://docs.pex-tool.org/> is now up-to-date.

* Prefer more recent patch versions in interpreter discovery. (#1088)
* Fix `--pex-python` when it's the same as the current interpreter.
    (#1087)
* Fix `dir_hash` vs. bytecode compilation races. (#1080)
* Fix readthedocs doc generation. (#1081)

## 2.1.19

This release adds the `--python-path` option, which allows controlling
the interpreter search paths when building a PEX.

The release also removes `--use-first-matching-interpreter`, which was a
misfeature. If you want to use fewer interpreters when building a PEX,
use more precise values for `--interpreter-constraint` and/or
`--python-path`, or use `--python` or `--platform`.

* Add `--python-path` to change interpreter search paths when building
    a PEX. (#1077)
* Remove `--use-first-matching-interpreter` misfeature. (#1076)
* Encapsulate `--inherit-path` handling. (#1072)

## 2.1.18

This release brings official support for Python 3.9 and adds a new
`--tmpdir` option to explicitly control the TMPDIR used by Pex and its
subprocesses. The latter is useful when building PEXes in
space-constrained environments in the face of large distributions.

The release also fixes `--cert` and `--client-cert` so that they work
with PEP-518 builds in addition to fixing bytecode compilation races in
highly parallel environments.

* Add a `--tmpdir` option to the Pex CLI. (#1068)
* Honor `sys.executable` unless macOS Framework. (#1065)
* Add Python 3.9 support. (#1064)
* Fix handling of `--cert` and `--client-cert`. (#1063)
* Add atomic_directory exclusive mode. (#1062)
* Fix `--cert` for PEP-518 builds. (#1060)

## 2.1.17

This release fixes a bug in `--resolve-local-platforms` handling that
made it unusable in 2.1.16 (#1043) as well as fixing a long-standing
file handle leak (#1050) and a bug when running under macOS framework
builds of Python (#1009).

* Fix `--unzip` performance regression. (#1056)
* Fix resource leak in Pex self-isolation. (#1052)
* Fix use of `iter_compatible_interpreters`. (#1048)
* Do not rely on `sys.executable` being accurate. (#1049)
* slightly demystify the relationship between platforms and
    interpreters in the library API and CLI (#1047)
* Path filter for PythonInterpreter.iter_candidates. (#1046)
* Add type hints to `util.py` and `tracer.py`
* Add type hints to variables.py and platforms.py (#1042)
* Add type hints to the remaining tests (#1040)
* Add type hints to most tests (#1036)
* Use MyPy via type comments (#1032)

## 2.1.16

This release fixes a bug in `sys.path` scrubbing / hermeticity (#1025)
and a bug in the `-D / --sources-directory` and
`-R / --resources-directory` options whereby PEP-420 implicit
(namespace) packages were not respected (#1021).

* Improve UnsatisfiableInterpreterConstraintsError. (#1028)
* Scrub direct `sys.path` manipulations by .pth files. (#1026)
* PEX zips now contain directory entries. (#1022)
* Fix UnsatisfiableInterpreterConstraintsError. (#1024)

## 2.1.15

A patch release to fix an issue with the
`--use-first-matching-interpreter` flag.

* Fix `--use-first-matching-interpreter` at runtime. (#1014)

## 2.1.14

This release adds the `--use-first-matching-interpreter` flag, which can
speed up performance when building a Pex at the expense of being
compatible with fewer interpreters at runtime.

* Add `--use-first-matching-interpreter`. (#1008)
* Autoformat with Black. (#1006)

## 2.1.13

The focus of this release is better support of the `--platform` CLI arg.
Platforms are now better documented and can optionally be resolved to
local interpreters when possible via `--resolve-local-platforms` to
better support creation of multiplatform PEXes.

* Add support for resolving `--platform` locally. (#1000)
* Improve `--platform` help. (#1002)
* Improve and fix `--platform` help. (#1001)
* Ensure pip download dir is uncontended. (#998)

## 2.1.12

A patch release to deploy the PEX_EXTRA_SYS_PATH feature.

* A PEX_EXTRA_SYS_PATH runtime variable. (#989)
* Fix typos (#986)
* Update link to avoid a redirect (#982)

## 2.1.11

A patch release to fix a symlink issue in remote execution environments.

* use relative paths within wheel cache (#979)
* Fix Tox not finding Python 3.8 on OSX. (#976)

## 2.1.10

This release focuses on the resolver API and resolution performance. Pex
2 resolving using Pip is now at least at performance parity with Pex 1
in all studied cases and most often is 5% to 10% faster.

As part of the resolution performance work, Pip networking configuration
is now exposed via Pex CLI options and the `NetworkConfiguration` API
type / new `resolver.resolve` API parameter.

With network configuration now wired up, the `PEX_HTTP_RETRIES` and
`PEX_HTTP_TIMEOUT` env var support in Pex 1 that was never wired into
Pex 2 is now dropped in favor of passing `--retries` and `--timeout` via
the CLI (See: #94)

* Expose Pip network configuration. (#974)
* Restore handling for bad wheel filenames to `.can_add()` (#973)
* Fix wheel filename parsing in PEXEnvironment.can_add (#965)
* Split Pex resolve API. (#970)
* Add a `--local` mode for packaging the Pex PEX. (#971)
* Constrain the virtualenv version used by tox. (#968)
* Improve Pex packaging. (#961)
* Make the interpreter cache deterministic. (#960)
* Fix deprecation warning for `rU` mode (#956)
* Fix runtime resolve error message generation. (#955)
* Kill dead code. (#954)

## 2.1.9

This release introduces the ability to copy requirements from an
existing PEX into a new one.

This can greatly speed up repeatedly creating a PEX when no requirements
have changed. A build tool (such as Pants) can create a "requirements
PEX" that contains just a static set of requirements, and build a final
PEX on top of that, without having to re-run pip to resolve
requirements.

* Support for copying requirements from an existing pex. (#948)

## 2.1.8

This release brings enhanced performance when using the Pex CLI or API
to resolve requirements and improved performance for many PEXed
applications when specifying the `--unzip` option. PEXes built with
`--unzip` will first unzip themselves into the Pex cache if not unzipped
there already and then re-execute themselves from there. This can
improve startup latency. Pex itself now uses this mode in our [PEX
release](
https://github.com/pex-tool/pex/releases/download/v2.1.8/pex).

* Better support unzip mode PEXes. (#941)
* Support an unzip toggle for PEXes. (#939)
* Ensure the interpreter path is a file (#938)
* Cache pip.pex. (#937)

## 2.1.7

This release brings more robust control of the Pex cache (PEX_ROOT).

The `--cache-dir` setting is deprecated in favor of build
time control of the cache location with `--pex-root` and
new support for control of the cache's runtime location with
`--runtime-pex-root` is added. As in the past, the
`PEX_ROOT` environment variable can still be used to
control the cache's runtime location.

Unlike in the past, the [Pex PEX](
https://github.com/pex-tool/pex/releases/download/v2.1.7/pex) we
release can now also be controlled via the `PEX_ROOT` environment
variable. Consult the CLI help for `--no-strip-pex-env`cto find out
more.

* Sanitize PEX_ROOT handling. (#929)
* Fix `PEX_*` env stripping and allow turning off. (#932)
* Remove second urllib import from compatibility (#931)
* Adding `--runtime-pex-root` option. (#780)
* Improve interpreter not found error messages. (#928)
* Add detail in interpreter selection error message. (#927)
* Respect `Requires-Python` in
    `PEXEnvironment`. (#923)
* Pin our tox version in CI for stability. (#924)

## 2.1.6

* Don't delete the root __init__.py when devendoring. (#915)
* Remove unused Interpreter.clear_cache. (#911)

## 2.1.5

* Silence pip warnings about Python 2.7. (#908)
* Kill `Pip.spawn_install_wheel` `overwrite` arg. (#907)
* Show pex-root from env as default in help output (#901)

## 2.1.4

This release fixes the hermeticity of pip resolver executions when the
resolver is called via the Pex API in an environment with PYTHONPATH
set.

* readme: adding a TOC (#900)
* Fix Pex resolver API PYTHONPATH hermeticity. (#895)
* Fixup resolve debug rendering. (#894)
* Convert `bdist_pex` tests to explicit cmdclass. (#897)

## 2.1.3

This release fixes a performance regression in which pip would
re-tokenize `--find-links` pages unnecessarily. The parsed pages are now
cached in a pip patch that has also been submitted upstream.

* Re-vendor pip (#890)
* Add a clear_cache() method to PythonInterpreter. (#885)
* Error eagerly if an interpreter binary doesn't exist. (#886)

## 2.1.2

This release fixes a bug in which interpreter discovery failed when
running from a zipped pex.

* Use pkg_resources when isolating a pex code chroot. (#881)

## 2.1.1

This release significantly improves performance and correctness of
interpreter discovery, particularly when pyenv is involved. It also
provides a workaround for EPERM issues when hard linking across devices,
by falling back to copying. Resolve error checking also now accounts for
environment markers.

* Revert "Fix the resolve check in the presence of platform
    constraints. (#877)" (#879)
* [resolver] Fix issue with wheel when using `--index-url` option
    (#865)
* Fix the resolve check in the presence of platform constraints.
    (#877)
* Check expected pex invocation failure reason in tests. (#874)
* Improve hermeticity of vendoring. (#873)
* Temporarily skip a couple of tests, to get CI green. (#876)
* Respect env markers when checking resolves. (#861)
* Ensure Pex PEX constraints match pex wheel / sdist. (#863)
* Delete unused pex/package.py. (#862)
* Introduce an interpreter cache. (#856)
* Re-enable pyenv interpreter tests under pypy. (#859)
* Harden PythonInterpreter against pyenv shims. (#860)
* Parallelize interpreter discovery. (#842)
* Explain hard link EPERM copy fallback. (#855)
* Handle EPERM when Linking (#852)
* Pin transitive dependencies of vendored code. (#854)
* Kill empty setup.py. (#849)
* Fix `tox -epackage` to create pex supporting 3.8. (#843)
* Fix Pex to handle empty ns package metadata. (#841)

## 2.1.0

This release restores and improves support for building and running
multiplatform pexes. Foreign `linux*` platform builds now
include `manylinux2014` compatible wheels by default and
foreign CPython pexes now resolve `abi3` wheels correctly.
In addition, error messages at both build-time and runtime related to
resolution of dependencies are more informative.

Pex 2.1.0 should be considered the first Pex 2-series release that fully
replaces and improves upon Pex 1-series functionality.

* Fix pex resolving for foreign platforms. (#835)
* Use pypa/packaging. (#831)
* Upgrade vendored setuptools to 42.0.2. (#832)
* De-vendor pex just once per version. (#833)
* Support VCS urls for vendoring. (#834)
* Support python 3.8 in CI. (#829)
* Fix pex resolution to respect `--ignore-errors`. (#828)
* Kill `pkg_resources` finders monkey-patching. (#827)
* Use flit to distribute pex. (#826)
* Cleanup extras_require. (#825)

## 2.0.3

This release fixes a regression in handling explicitly requested
`--index` or `--find-links` http (insecure) repos. In addition,
performance of the pex 2.x resolver is brought in line with the 1.x
resolver in all cases and improved in most cases.

* Unify PEX build-time and runtime wheel caches. (#821)
* Parallelize resolve. (#819)
* Use the resolve cache to skip installs. (#815)
* Implicitly trust explicitly requested repos. (#813)

## 2.0.2

This is a hotfix release that fixes a bug exposed when Pex was asked to
use an interpreter with a non-canonical path as well as fixes for
'current' platform handling in the resolver API.

* Fix current platform handling. (#801)
* Add a test of pypi index rendering. (#799)
* Fix `iter_compatible_interpreters` path biasing. (#798)

## 2.0.1

This is a hotfix release that fixes a bug when specifying a custom index
(`-i`/`--index`/`--index-url`) via the CLI.

* Fix #794 issue by add missing return statement in `__str__` (#795)

## 2.0.0

Pex 2.0.0 is cut on the advent of a large, mostly internal change for
typical use cases: it now uses vendored pip to perform resolves and
wheel builds. This fixes a large number of compatibility and correctness
bugs as well as gaining feature support from pip including handling
manylinux2010 and manylinux2014 as well as VCS requirements and support
for PEP-517 & PEP-518 builds.

API changes to be wary of:

* The egg distribution format is no longer supported.
* The deprecated `--interpreter-cache-dir` CLI option was removed.
* The `--cache-ttl` CLI option and `cache_ttl` resolver API argument
    were removed.
* The resolver API replaced `fetchers` with a list of `indexes` and a
    list of `find_links` repos.
* The resolver API removed (http) `context` which is now automatically
    handled.
* The resolver API removed `precedence` which is now pip default
    precedence: wheels when available and not ruled out via the
    `--no-wheel` CLI option or `use_wheel=False` API argument.
* The `--platform` CLI option and `platform` resolver API argument now
    must be full platform strings that include platform, implementation,
    version and abi; e.g.: `--platform=macosx-10.13-x86_64-cp-36-m`.
* The `--manylinux` CLI option and `use_manylinux` resolver API
    argument were removed. Instead, to resolve manylinux wheels for a
    foreign platform, specify the manylinux platform to target with an
    explicit `--platform` CLI flag or `platform` resolver API argument;
    e.g.: `--platform=manylinux2010-x86_64-cp-36-m`.

In addition, Pex 2.0.0 now builds reproducible pexes by default; ie:

* Python modules embedded in the pex are not pre-compiled (pass
    `--compile` if you want this).
* The timestamps for Pex file zip entries default to midnight on
    January 1, 1980 (pass `--use-system-time` to change this).

This finishes off the effort tracked by issue #716.

Changes in this release:

* Pex defaults to reproducible builds. (#791)
* Use pip for resolving and building distributions. (#788)
* Bias selecting the current interpreter. (#783)

## 1.6.12

This release adds the `--intransitive` option to support pre-resolved
requirements lists and allows for python binaries built under Gentoo
naming conventions.

* Add an `--intransitive` option. (#775)
* PythonInterpreter: support python binary names with single letter
    suffixes (#769)

## 1.6.11

This release brings a consistency fix to requirement resolution and an
isolation fix that scrubs all non-stdlib PYTHONPATH entries by default,
only pre-pending or appending them to the `sys.path` if the
corresponding `--inherit-path=(prefer|fallback)` is used.

* Avoid reordering of equivalent packages from multiple fetchers
    (#762)
* Include `PYTHONPATH` in `--inherit-path`
    logic. (#765)

## 1.6.10

This is a hotfix release for the bug detailed in #756 that was
introduced by #752 in python 3.7 interpreters.

* Guard against modules with a `__file__` of
    `None`. (#757)

## 1.6.9

* Fix `sys.path` scrubbing of pex extras modules. (#752)
* Fix pkg resource early import (#750)

## 1.6.8

* Fixup pex re-exec during bootstrap. (#741)
* Fix resolution of `setup.py` project extras. (#739)
* Tighten up namespace declaration logic. (#732)
* Fixup import sorting. (#731)

## 1.6.7

We now support reproducible builds when creating a pex via `pex -o
foo.pex`, meaning that if you were to run the command again
with the same inputs, the two generated pexes would be byte-for-byte
identical. To enable reproducible builds when building a pex, use the
flags `--no-use-system-time --no-compile`, which will use
a deterministic timestamp and not include `.pyc` files in
the Pex.

In Pex 1.7.0, we will default to reproducible builds.

* add delayed pkg_resources import fix from #713, with an
    integration test (#730)
* Fix reproducible builds sdist test by properly requiring building
    the wheel (#727)
* Fix reproducible build test improperly using the -c flag and add a
    new test for -c flag (#725)
* Fix PexInfo requirements using a non-deterministic data structure
    (#723)
* Add new `--no-use-system-time` flag to use a
    deterministic timestamp in built PEX (#722)
* Add timeout when using requests. (#726)
* Refactor reproducible build tests to assert that the original pex
    command succeeded (#724)
* Introduce new `--no-compile` flag to not include .pyc
    in built pex due to its non-determinism (#718)
* Document how Pex developers can run specific tests and run Pex from
    source (#720)
* Remove unused bdist_pex.py helper function (#719)
* Add failing acceptance tests for reproducible Pex builds (#717)
* Make a copy of globals() before updating it. (#715)
* Make sure `PexInfo` is isolated from
    `os.environ`. (#711)
* Fix import sorting. (#712)
* When iterating over Zipfiles, always use the Unix file separator to
    fix a Windows issue (#638)
* Fix pex file looses the executable permissions of binary files
    (#703)

## 1.6.6

This is the first release including only a single PEX pex, which
supports execution under all interpreters pex supports.

* Fix pex bootstrap interpreter selection. (#701)
* Switch releases to a single multi-pex. (#698)

## 1.6.5

This release fixes long-broken resolution of abi3 wheels.

* Use all compatible versions when calculating tags. (#692)

## 1.6.4

This release un-breaks [lambdex](https://github.com/wickman/lambdex).

* Restore `pex.pex_bootstrapper.is_compressed` API. (#685)
* Add the version of pex used to build a pex to build_properties.
    (#687)
* Honor interpreter constraints even when PEX_PYTHON and
    PEX_PYTHON_PATH not set (#668)

## 1.6.3

This release changes the behavior of the `--interpreter-constraint`
option. Previously, interpreter constraints were ANDed, which made it
impossible to express constraints like '>=2.7,<3' OR '>=3.6,<4';
ie: either python 2.7 or else any python 3 release at or above 3.6. Now
interpreter constraints are ORed, which is likely a breaking change if
you have scripts that pass multiple interpreter constraints. To
transition, use the native `,` AND operator in your constraint
expression, as used in the example above.

* Provide control over pex warning behavior. (#680)
* OR interpreter constraints when multiple given (#678)
* Pin isort version in CI (#679)
* Honor PEX_IGNORE_RCFILES in to_python_interpreter() (#673)
* Make `run_pex_command` more robust. (#670)

## 1.6.2

* Support de-vendoring for installs. (#666)
* Add User-Agent header when resolving via urllib (#663)
* Fix interpreter finding (#662)
* Add recipe to use PEX with requests module and proxies. (#659)
* Allow pex to be invoked using runpy (python -m pex). (#637)

## 1.6.1

* Make `tox -evendor` idempotent. (#651)
* Fix invalid regex and escape sequences causing DeprecationWarning
    (#646)
* Follow PEP 425 suggestions on distribution preference. (#640)
* Setup interpreter extras in InstallerBase. (#635)
* Ensure bootstrap demotion is complete. (#634)

## 1.6.0

* Fix pex force local to handle PEP 420. (#613)
* Vendor `setuptools` and `wheel`. (#624)

## 1.5.3

* Fixup PEXEnvironment extras resolution. (#617)
* Repair unhandled AttributeError during pex bootstrapping. (#599)

## 1.5.2

This release brings an exit code fix for pexes run via entrypoint as
well as a fix for finding scripts when building pexes from wheels with
dashes in their distribution name.

* Update PyPI default URL to pypi.org (#610)
* Pex exits with correct code when using entrypoint (#605)
* Fix *_custom_setuptools_usable ITs. (#606)
* Update pyenv if neccesary (#586)
* Fix script search in wheels. (#600)
* Small Docstring Fix (#595)

## 1.5.1

This release brings a fix to handle top-level requirements with
environment markers, fully completing environment marker support.

* Filter top-level requirements against env markers. (#592)

## 1.5.0

This release fixes pexes such that they fully support environment
markers, the canonical use case being a python 2/3 pex that needs to
conditionally load one or more python 2 backport libs when running under
a python 2 interpreter only.

* Revert "Revert "Support environment markers during pex activation.
    (#582)""

## 1.4.9

This is a hotfix release for 1.4.8 that fixes a regression in
interpreter setup that could lead to resolved distributions failing to
build or install.

* Cleanup `PexInfo` and `PythonInterpreter`.
    (#581)
* Fix resolve regressions introduced by the 1.4.8. (#580)
* Narrow the env marker test. (#578)
* Documentation for #569 (#574)

## 1.4.8

This release adds support for `-c` and `-m`
PEX file runtime options that emulate the behavior of the same arguments
to `python` as well a fix for handling the non-standard
platform reported by setuptools for Apple system interpreters in
addition to several other bug fixes.

* Fix PEXBuilder.clone. (#575)
* Fix PEXEnvironment platform determination. (#568)
* Apply more pinning to jupyter in IT. (#573)
* Minimize interpreter bootstrapping in tests. (#571)
* Introduce 3.7 to CI and release. (#567)
* Add OSX shards. (#565)
* Add support for `-m` and `-c` in interpreter
    mode. (#563)
* Ignore concurrent-rename failures. (#558)
* Fixup test_jupyter_appnope_env_markers. (#562)

## 1.4.7

This is a hotfix release for a regression in setuptools compatibility
introduced by #542.

* Fixup `PEX.demote_bootstrap`: fully unimport. (#554)

## 1.4.6

This release opens up setuptools support for more modern versions that
support breaking changes in `setup` used in the wild.

* Fix for super() usage on "old style class" ZipFile (#546)
* Cleanup bootstrap dependencies before handoff. (#542)
* Support -c for plat spec dists in multiplat pexes. (#545)
* Support `-` when running as an interpreter. (#543)
* Expand the range of supported setuptools. (#541)
* Preserve perms of files copied to pex chroots. (#540)
* Add more badges to README. (#535)
* Fixup CHANGES PR links for 1.4.5.

## 1.4.5

This release adds support for validating pex entrypoints at build time
in addition to several bugfixes.

* Fix PEX environment setup. (#531)
* Fix installers to be insensitive to extras iteration order. (#532)
* Validate entry point at build time (#521)
* Fix pex extraction perms. (#528)
* Simplify `.travis.yml`. (#524)
* Fix `PythonInterpreter` caching and ergonomics. (#518)
* Add missing git dep. (#519)
* Introduce a controlled env for pex testing. (#517)
* Bump wheel version to latest. (#515)
* Invoke test runner at a more granular level for pypy shard. (#513)

## 1.4.4

This release adds support for including sources and resources directly
in a produced pex - without the need to use pants.

* Add resource / source bundling to pex cli (#507)

## 1.4.3

Another bugfix release for the 1.4.x series.

* Repair environmental marker platform setting. (#500)
* Broaden abi selection for non-specified abi types. (#503)

## 1.4.2

This release repairs a tag matching regression for .egg dists that
inadvertently went out in 1.4.1.

* Improve tag generation for EggPackage. (#493)

## 1.4.1

A bugfix release for 1.4.x.

* Repair abi prefixing for PyPy. (#483)
* Repair .egg resolution for platform specific eggs. (#486)
* Eliminate the python3.3 shard. (#488)

## 1.4.0

This release includes full Manylinux support, improvements to wheel
resolution (including first class platform/abi tag targeting) and a
handful of other improvements and bugfixes. Enjoy!

Special thanks to Dan Blanchard (@dan-blanchard) for seeding the
initial PR for Manylinux support and wheel resolution improvements.

* Complete manylinux support in pex. (#480)
* Add manylinux wheel support and fix a few bugs along the way (#316)
* Skip failing tests on pypy shard. (#478)
* Bump travis image to Trusty. (#476)
* Mock PATH for problematic interpreter selection test in CI (#474)
* Skip two failing integration tests. (#472)
* Better error handling for missing setuptools. (#471)
* Add tracebacks to IntegResults. (#469)
* Fix failing tests in master (#466)
* Repair isort-check failure in master. (#465)
* Repair style issues in master. (#464)
* Fixup PATH handling in travis.yml. (#462)

## 1.3.2

* Add blacklist handling for skipping requirements in pex resolver
    (#457)

## 1.3.1

This is a bugfix release for a regression that inadvertently went out in
1.3.0.

* scrub path when not inheriting (#449)
* Fix up inherits_path tests to use new values (#450)

## 1.3.0

* inherit_path allows 'prefer', 'fallback', 'false' (#444)

## 1.2.16

* Change PEX re-exec variable from ENV to os.environ (#441)

## 1.2.15

* Bugfix for entry point targeting + integration test (#435)

## 1.2.14

* Add interpreter constraints option and use constraints to search for
    compatible interpreters at exec time (#427)

## 1.2.13

* Fix handling of pre-release option. (#424)
* Patch sys module using pex_path from PEX-INFO metadata (#421)

## 1.2.12

* Create `--pex-path` argument for pex cli and load pex path into
    pex-info metadata (#417)

## 1.2.11

* Leverage `subprocess32` when available. (#411)
* Kill support for python 2.6. (#408)

## 1.2.10

* Allow passing a preamble file to the CLI (#400)

## 1.2.9

* Add first-class support for multi-interpreter and multi-platform pex
    construction. (#394)

## 1.2.8

* Minimum setuptools version should be 20.3 (#391)
* Improve wheel support in pex. (#388)

## 1.2.7

* Sort keys in PEX-INFO file so the output is deterministic. (#384)
* Pass platform for SourceTranslator (#386)

## 1.2.6

* Fix for Ambiguous Resolvable bug in transitive dependency resolution
    (#367)

## 1.2.5

This release follows-up on 1.2.0 fixing bugs in the pre-release
resolving code paths.

* Resolving pre-release when explicitly requested (#372)
* Pass allow_prerelease to other iterators (Static, Caching) (#373)

## 1.2.4

* Fix bug in cached dependency resolution with exact resolvable.
    (#365)
* Treat .pth injected paths as extras. (#370)

## 1.2.3

* Follow redirects on HTTP requests (#361)
* Fix corner case in cached dependency resolution (#362)

## 1.2.2

* Fix CacheControl import. (#357)

## 1.2.1

This release is a quick fix for a bootstrapping bug that inadvertently
went out in 1.2.0 (Issue #354).

* Ensure `packaging` dependency is self-contained. (#355)

## 1.2.0

This release changes pex requirement resolution behavior. Only stable
requirements are resolved by default now. The previous behavior that
included pre-releases can be retained by passing `--pre` on the pex
command line or passing `allow_prereleases=True` via the API.

* Upgrade dependencies to modern version ranges. (#352)
* Add support for controlling prerelease resolution. (#350)

## 1.1.20

* Add dummy flush method for clean interpreter exit with python3.6
    (#343)

## 1.1.19

* Implement `--constraints` in pex (#335)
* Make sure namespace packages (e.g. virtualenvwrapper) don't break
    pex (#338)

## 1.1.18

* Expose a PEX instance's path. (#332)
* Check for scripts directory in get_script_from_egg (#328)

## 1.1.17

* Make PEX_PATH unify pex sources, as well as requirements. (#329)

## 1.1.16

* Adjust FileFinder import to work with Python 3.6. (#318)
* Kill zipmanifest monkeypatching. (#322)
* Bump setuptools range to latest. (#323)

## 1.1.15

* Fix #309 by de-duplicating output of the distribution finder. (#310)
* Update wheel dependency to `>0.26.0`. (#304)

## 1.1.14

* Repair Executor error handling for other classes of IOError/OSError.
    (#292)
* Fix bdist_pex `--pex-args`. (#285)
* Inherit user site with `--inherit-path`. (#284)

## 1.1.13

* Repair passing of stdio kwargs to `PEX.run()`. (#288)

## 1.1.12

* Fix bdist_pex interpreter cache directory. (#286)
* Normalize and edify subprocess execution. (#255)
* Don't ignore exit codes when using setuptools entry points. (#280)

## 1.1.11

* Update cache dir when `bdist_pex.run` is called directly.

## 1.1.10

* Improve failure modes for os.rename() as used in distribution
    caching.

## 1.1.9

* Bugfix: Open setup.py in binary mode.

## 1.1.8

* Bugfix: Repair a regression in `--disable-cache`.

## 1.1.7

* Add README and supported python versions to PyPI description.
* Use `open` with utf-8 support.
* Add `--pex-root` option.

## 1.1.6

This release is a quick fix for a regression that inadvertently went out
in 1.1.5 (Issue #243).

* Fix the `bdist_pex` `setuptools` command to work for python2.
* Upgrade pex dependencies on `setuptools` and `wheel`.

## 1.1.5

* Fix `PEXBuilder.clone` and thus `bdist_pex --pex-args` for
    `--python` and `--python-shebang`.
* Fix old `pkg_resources` egg version normalization.
* Fix the `inherit_path` handling.
* Fix handling of bad distribution script names when used as the pex
    entrypoint.

## 1.1.4

This release is a quick fix for a regression that inadvertently went out
in 1.1.3 (Issue #216).

* Add a test for the regression in `FixedEggMetadata._zipinfo_name`
    and revert the breaking commit.

## 1.1.3

This release includes an initial body of work towards Windows support,
ABI tag support for CPython 2.x and a fix for version number
normalization.

* Add python 2.x abi tag support.
* Add .idea to .gitignore.
* Don't normalize version numbers as names.
* More fixes for windows.
* Fixes to get pex to work on windows.

## 1.1.2

* Bump setuptools & wheel version pinning.
* Unescape html in PageParser.href_match_to_url.
* Memoize calls to Crawler.crawl() for performance win in find-links
    based resolution.

## 1.1.1

* Fix infinite recursion when `PEX_PYTHON` points at a symlink.
* Add `/etc/pexrc` to the list of pexrc locations to check.
* Improve error messaging for platform constrained Untranslateable
    errors.

## 1.1.0

* Add support for `.pexrc` files for influencing the pex environment.
    See the notes [here](
    https://github.com/pex-tool/pex/blob/master/docs/buildingpex.rst#tailoring-pex-execution-at-build-time
    ).
* Bug fix: PEX_PROFILE_FILENAME and PEX_PROFILE_SORT were not
    respected.
* Adds the `bdist_pex` command to setuptools.
* Bug fix: We did not normalize package names in `ResolvableSet`, so
    it was possible to depend on `sphinx` and `Sphinx-1.4a0.tar.gz` and
    get two versions build and included into the pex.
* Adds a pex-identifying User-Agent.

## 1.0.3

* Bug fix: Accommodate OSX `Python` python binaries. Previously the
    OSX python distributions shipped with OSX, XCode and available via
    https://www.python.org/downloads/ could fail to be detected using
    the `PythonInterpreter` class. Fixes
* Bug fix: PEX_SCRIPT failed when the script was from a not-zip-safe
    egg.
* Bug fix: `sys.exit` called without arguments would cause
    `None` to be printed on stderr since pex 1.0.1.

## 1.0.2

* Bug fix: PEX-INFO values were overridden by environment `Variables`
    with default values that were not explicitly set in the environment.
    Fixes #135.
* Bug fix: Since
    [69649c1](https://github.com/pex-tool/pex/commit/69649c1) we have
    been un-patching the side effects of `sys.modules` after
    `PEX.execute`. This takes all modules imported during the PEX
    lifecycle and sets all their attributes to `None`. Unfortunately,
    `sys.excepthook`, `atexit` and `__del__` may still try to operate
    using these tainted modules, causing exceptions on interpreter
    teardown. This reverts just the `sys` un-patching so that the
    above-mentioned teardown hooks behave more predictably.

## 1.0.1

* Allow PEXBuilder to optionally copy files into the PEX environment
    instead of hard-linking them.
* Allow PEXBuilder to optionally skip pre-compilation of .py files into
    .pyc files.
* Bug fix: PEXBuilder did not respect the target interpreter when
    compiling source to bytecode.
* Bug fix: Fix complex resolutions when using a cache.

## 1.0.0

The 1.0.0 release of pex introduces a few breaking changes: `pex -r` now
takes requirements.txt files instead of requirement specs, `pex -s` has
now been removed since source specs are accepted as arguments, and
`pex -p` has been removed in favor of its alias `pex -o`.

The pex *command line interface* now adheres to semver insofar as
backwards incompatible CLI changes will invoke a major version change.
Any backwards incompatible changes to the PEX environment variable
semantics will also result in a major version change. The pex *API*
adheres to semver insofar as backwards incompatible API changes will
invoke minor version changes.

For users of the PEX API, it is recommended to add minor version ranges,
e.g. `pex>=1.0,<1.1`. For users of the PEX CLI, major version ranges
such as `pex>=1,<2` should be sufficient.

* BREAKING CHANGE: Removes the `-s` option in favor of specifying
    directories directly as arguments to the pex command line.
* BREAKING CHANGE: `pex -r` now takes requirements.txt filenames and
    *not* requirement specs. Requirement specs are now passed as
    arguments to the pex tool. Use `--` to escape command line arguments
    passed to interpreters spawned by pex.
* Adds a number of flag aliases to be more compatible with pip command
    lines: `--no-index`, `-f`, `--find-links`, `--index-url`,
    `--no-use-wheel`. Removes `-p` in favor of `-o` exclusively.
* Adds `--python-shebang` option to the pex tool in order to set the
    `#!` shebang to an exact path.
* Adds support for `PEX_PYTHON` environment variable which will cause
    the pex file to re-invoke itself using the interpreter specified,
    e.g. `PEX_PYTHON=python3.4` or
    `PEX_PYTHON=/exact/path/to/interpreter`.
* Adds support for `PEX_PATH` environment variable which allows
    merging of PEX environments at runtime. This can be used to inject
    plugins or entry_points or modules from one PEX into another
    without explicitly building them together.
* Consolidates documentation of `PEX_` environment variables and adds
    the `--help-variables` option to the pex client.
* Adds helper method to dump a package subdirectory onto disk from
    within a zipped PEX file. This can be useful for applications that
    know they're running within a PEX and would prefer some static
    assets dumped to disk instead of running as an unzipped PEX file.
* Now supports extras for static URLs and installable directories.
* Adds `-m` and `--entry-point` alias to the existing `-e` option for
    entry points in the pex tool to evoke the similarity to `python -m`.
* Adds console script support via `-c/--script/--console-script` and
    `PEX_SCRIPT`. This allows you to reference the named entry point
    instead of the exact `module:name` pair. Also supports scripts
    defined in the `scripts` section of setup.py.
* Adds more debugging information when encountering unresolvable
    requirements.
* Bug fix: `PEX_COVERAGE` and `PEX_PROFILE` did not function correctly
    when SystemExit was raised.
* Bug fix: Fixes caching in the PEX tool since we don't cache the
    source distributions of installable directories.

## 0.9.0

This is the last release before the 1.0.0 development branch is started.

* Change the setuptools range to `>=2.2,<16` by handling EntryPoint
    changes as well as being flexible on whether `pkg_resources` is a
    package or a module.
* Adds option groups to the pex tool to make the help output slightly
    more readable.
* Bug fix: Make `pip install pex` work better by removing
    `extras_requires` on the `console_script` entry point.
* New feature: Adds an interpreter cache to the `pex` tool. If the
    user does not explicitly disable the wheel feature and attempts to
    build a pex with wheels but does not have the wheel package
    installed, pex will download it in order to make the feature work.

## 0.8.6

* Bug fix: Honor installed sys.excepthook in pex teardown.
* Bug fix: `UrllibContext` used `replace` as a keyword argument for
    `bytes.decode` but this only works on Python 3.

## 0.8.5

* Bug fix: Fixup string formatting in pex/bin/pex.py to support Python
    2.6

## 0.8.4

* Performance improvement: Speed up the best-case scenario of
    dependency resolution.
* Bug fix: Change from `uuid4().get_hex()` to `uuid4().hex` to
    maintain Python3 compatibility of pex.common.
* Bug fix: Actually cache the results of translation. Previously bdist
    translations would be created in a temporary directory even if a
    cache location was specified.
* Bug fix: Support all potential abi tag permutations when determining
    platform compatibility.

## 0.8.3

* Performance improvement: Don't always write packages to disk if
    they've already been cached. This can significantly speed up
    launching PEX files with a large number of non-zip-safe
    dependencies.

## 0.8.2

* Bug fix: Allow pex 0.8.x to parse pex files produced by earlier
    versions of pex and twitter.common.python.
* Pin pex to setuptools prior to 9.x until we have a chance to make
    changes related to PEP440 and the change of pkg_resources.py to a
    package.

## 0.8.1

* Bug fix: Fix issue where it'd be possible to `os.path.getmtime` on
    a remote `Link` object

## 0.8.0

* *API change*: Decouple translation from package iteration. This
    removes the Obtainer construct entirely, which likely means if
    you're using PEX as a library, you will need to change your code if
    you were doing anything nontrivial. This adds a couple new options
    to `resolve` but simplifies the story around how to cache packages.
* Refactor http handling in pex to allow for alternate http
    implementations. Adds support for
    [requests](https://github.com/kennethreitz/requests), improving both
    performance and security. For more information, read the commit
    notes at [91c7f32](
    https://github.com/pex-tool/pex/commit/91c7f324085c18af714d35947b603a5f60aeb682
    ).
* Improvements to API documentation throughout.
* Renamed `Tracer` to `TraceLogger` to prevent nondeterministic isort
    ordering.
* Refactor tox.ini to increase the number of environment combinations
    and improve coverage.
* Adds HTTP retry support for the RequestsContext.
* Make pex `--version` correct.
* Bug fix: Fix over-aggressive `sys.modules` scrubbing for namespace
    packages. Under certain circumstances, namespace packages in
    site-packages could conflict with packages within a PEX, causing
    them to fail importing.
* Bug fix: Replace uses of `os.unsetenv(...)` with
    `del os.environ[...]`
* Bug fix: Scrub `sys.path` and `sys.modules` based upon both supplied
    path and realpath of files and directories. Newer versions of
    virtualenv on Linux symlink site-packages which caused those
    packages to not be removed from `sys.path` correctly.
* Bug fix: The pex -s option was not correctly pulling in transitive
    dependencies.
* Bug fix: Adds `content` method to HTTP contexts that does HTML
    content decoding, fixing an encoding issue only experienced when
    using Python 3.

## 0.7.0

* Rename `twitter.common.python` to `pex` and split out from the
    [twitter/commons](http://github.com/twitter/commons) repo.

## 0.6.0

* Change the interpretation of `-i` (and of PyPIFetcher's pypi_base)
    to match pip's `-i`. This is useful for compatibility with devpi.

## 0.5.10

* Ensures that .egg/.whl distributions on disk have their mtime
    updated even though we no longer overwrite them. This gives them a
    new time lease against their ttl.

    Without this change, once a distribution aged past the ttl it would
    never be used again, and builds would re-create the same
    distributions in tmpdirs over and over again.

## 0.5.9

* Fixes an issue where SourceTranslator would overwrite .egg/.whl
    distributions already on disk. Instead, it should always check to see
    if a copy already exists and reuse if there.

    This ordinarily should not be a problem but the zipimporter caches
    metadata by filename instead of stat/sha, so if the underlying
    contents changed a runtime error would be thrown due to seemingly
    corrupt zip file offsets.

## 0.5.8

* Adds `-i/--index` option to the pex tool.

## 0.5.7

* Adds `twitter.common.python.pex_bootstrap` `bootstrap_pex_env`
    function in order to initialize a PEX environment from within a
    python interpreter. (Patch contributed by @kwlzn)
* Adds stdin=,stdout=,stderr= keyword parameters to the `PEX.run`
    function. (Patch from @benjy)

## 0.5.6

* The crawler now defaults to not follow links for security reasons.
    (Before the default behavior was to implicitly `--follow-links` for
    all requirements.)

## 0.5.5

* Improves scrubbing of site-packages from PEX environments.

0.5.1 - 0.5.4
=============

* Silences exceptions reported during interpreter teardown (the
    exceptions resulting from incorrect atexit handler behavior)
    introduced by 0.4.3
* Adds `__hash__` to `Link` so that Packages are hashed correctly in
    `twitter.common.python.resolver` `resolve`

## 0.5.0

* Adds wheel support to `twitter.common.python`

## 0.4.3

* Adds `twitter.common.python.finders` which are additional finders
    for setuptools including:

    - find eggs within a .zip
    - find wheels within a directory
    - find wheels within a .zip

* Adds a new Package abstraction by refactoring Link into Link and
    Package.

* Adds support for PEP425 tagging necessary for wheel support.

* Improves python environment isolation by correctly scrubbing
    namespace packages injected into module `__path__` attributes by
    nspkg pth files.

* Adds `twitter.common.python.resolver` `resolve` method that handles
    transitive dependency resolution better. This means that if the
    requirement `futures==2.1.2` and an unqualified `futures>=2` is
    pulled in transitively, our resolver will correctly resolve futures
    2.1.2 instead of reporting a VersionConflict if any version newer
    than 2.1.2 is available.

* Factors all `twitter.common.python` test helpers into
    `twitter.common.python.testing`

* Bug fix: Fix `OrderedSet` atexit exceptions

* Bug fix: Fix cross-device symlinking (patch from @benjy)

* Bug fix: Raise a `RuntimeError` if we fail to write `pkg_resources`
    into a .pex

## 0.4.2

* Upgrade to `setuptools>=1`

## 0.4.1

* `twitter.common.python` is no longer a namespace package

## 0.4.0

* Kill the egg distiller. We now delegate .egg generation to
    bdist_egg.

## 0.3.1

* Short-circuit resolving a distribution if a local exact match is
    found.
* Correctly patch the global `pkg_resources` `WorkingSet` for the
    lifetime of the Python interpreter.
* Fixes a performance regression in setuptools `build_zipmanifest`
    [Setuptools Issue #154](
    https://bitbucket.org/pypa/setuptools/issue/154/build_zipmanifest-results-should-be)

## 0.3.0

* Plumb through the `--zip-safe`, `--always-write-cache`,
    `--ignore-errors` and `--inherit-path` flags to the pex tool.
* Delete the unused `PythonDirWrapper` code.
* Split `PEXEnvironment` resolution into
    `twitter.common.python.environment` and de-conflate
    `WorkingSet`/`Environment` state.
* Removes the monkeypatched zipimporter in favor of keeping all eggs
    unzipped within PEX files. Refactors the PEX dependency cache in
    `util.py`
* Adds interpreter detection for Jython and PyPy.
* Dependency translation errors should be made uniform. (Patch
    from @johnsirois)
* Adds `PEX_PROFILE_ENTRIES` to limit the number of entries reported
    when `PEX_PROFILE` is enabled. (Patch from @rgs_)
* Bug fix: Several fixes to error handling in
    `twitter.common.python.http` (From Marc Abramowitz)
* Bug fix: PEX should not always assume that `$PATH` was available.
    (Patch from @jamesbroadhead)
* Bug fix: Filename should be part of the .pex cache key or else
    multiple identical versions will incorrectly resolve (Patch
    from @tc)
* Bug fix: Executed entry points shouldn't be forced to run in an
    environment with `__future__` imports enabled. (Patch
    from @lawson_patrick)
* Bug fix: Detect versionless egg links and fail fast. (Patch from
    @johnsirois.)
* Bug fix: Handle setuptools>=2.1 correctly in the zipimport
    monkeypatch (Patch from @johnsirois.)

## 0.2.3

* Bug fix: Fix handling of Fetchers with `file://` urls.

## 0.2.2

* Adds the pex tool as a standalone tool.

## 0.2.1

* Bug fix: Bootstrapped `twitter.common.python` should declare
    `twitter.common` as a namespace package.

## 0.2.0

* Make `twitter.common.python` fully standalone by consolidating
    external dependencies within `twitter.common.python.common`.

## 0.1.0

* Initial published version of `twitter.common.python`.
