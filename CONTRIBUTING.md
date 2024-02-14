# Contributing

First, thank you in advance for your time and effort!

## Constraints

Pex provides the `pex`, `pex3` and `pex-tools` tools via the [`pex` distribution on PyPI](
https://pypi.org/project/pex/) and the [`pex` PEX released on GitHub](
https://github.com/pex-tool/pex/releases/latest). Although there is no public code API (Pex is
supported as a CLI tool only), its stability guarantees for these scripts are paramount. Pex should
strictly adhere to [SEMVER 2.0](https://semver.org/) and never bump the major version. In other
words, changes should only fix bugs or add new features, never change existing features / the CLI
API (option names, meanings, etc.). As part of this guaranty, Pex must maintain support for all the
Pythons it has ever supported, namely CPython and PyPy for versions 2.7 and 3.5+. This means Pex
contributions are limited to Python 2.7 syntax and type hints using the comment style.

These hard constraints aside, Pex stays abreast of the latest as best as possible in the Python
packaging world. It always strives to support the latest Python and Pip releases either before they
reach a stable release or within a few days of one. As such, coverage of both Python interpreters
and Pip versions is broad in CI and most changes can proceed with confidence if CI goes green.

## Development Environment

You'll need just a few tools to hack on Pex:
+ The [`tox`](https://tox.wiki) tool.
+ (Optionally) Docker, or a Docker CLI clone like podman.

## Development Cycle

You might want to open a [discussion](https://github.com/pex-tool/pex/discussions) or [issue](
https://github.com/pex-tool/pex/issues) to vet your idea first. It can often save overall effort and
lead to a better end result.

Before sending off changes you should run `tox -e fmt,lint,check`. This formats, lints and type
checks the code.

If you've made `docs/` changes, you should run `tox -e docs -- --linkcheck --pdf --serve` which
will build the full doc site including its downloadable PDF version as well as the search index.
You can browse to the URL printed out at the end of the output to view the site on your local
machine.

In addition, you should run tests, which are divided into integration tests (those under
`tests/integration/`) and unit tests (those under `tests/` but not under `tests/integration/`).
Unit tests have a tox environment name that matches the desired interpreter to test against. So, to
run unit tests against CPython 3.11 (which you must have installed), use `tox -e py311`. For
CPython 2.7 use `tox -e py27` and for PyPy 3.10 `tox -e pypy310`, etc. Integration tests follow the
same scheme with `-integration` appended to the environment name; so `tox -e py311-integration`,
`tox -epy27-integration`, `tox -e pypy310-integration`, etc. Both sets of test environments support
passing additional args to the test runner, which is a small shim around pytest. The shim supports
a `--devpi` option to have tests use a local [devpi server](https://pypi.org/project/devpi-server/)
caching proxy server. This generally helps with network flakes and is a friendly thing to do for
the PyPI maintainers. For example, `tox -e py312 -- --devpi -k just_this_test` would run unit tests
against CPython 3.12 using a devpi server and additionally just run the `just_this_test` test by
using pytest's `-k` test selector option.

If you have `docker` installed, you can use `./dtox.sh` in place of `tox` for any of the commands
described above. This will transparently pull or build a docker image on first execution that
contains all the Pythons Pex supports; so you can run the now exotic `./dtox.sh -e pypy27...`
without having to actually install PyPy 2.7 on your machine.

When you're ready to get additional eyes on your changes, submit a [pull request](
https://github.com/pex-tool/pex/pulls).

If you've made documentation changes you can render the site in the fork you used for the pull
request by navigating to the "Deploy Doc Site" action in your fork and running the workflow
manually. You do this using the "Run workflow" widget in the top row of the workflow run list,
selecting your PR branch and clicking "Run workflow". This will fail your first time doing this due
to a branch protection rule the "Deploy Doc Site" action automatically establishes to restrict doc
site deployments to the main branch. To fix this, navigate to "Environments" in your fork settings
and edit the "github-pages" branch protection rule, changing "Deployment Branches" from
"Selected branches" to "All branches" and then save the protection rules. You can now re-run the
workflow and should be able to browse to https://<your github id>.github.io/pex to browse the
deployed site with your changes incorporated. N.B.: The site will be destroyed when you delete your
PR branch.
