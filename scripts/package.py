#!/usr/bin/env python3

import subprocess
import sys
from pathlib import Path

import pytoml as toml

PROJECT_METADATA = Path('pyproject.toml')


def python_requires() -> str:
  project_metadata = toml.loads(PROJECT_METADATA.read_text())
  return project_metadata['tool']['flit']['metadata']['requires-python'].strip()


def build_pex_pex() -> None:
  # NB: We do not include the subprocess extra (which would be spelled: `.[subprocess]`) since we
  # would then produce a pex that would not be consumable by all python interpreters otherwise
  # meeting `python_requires`; ie: we'd need to then come up with a deploy environment / deploy
  # tooling, that built subprocess32 for linux cp27m, cp27mu, pypy, ... etc. Even with all the work
  # expended to do this, we'd still miss some platform someone wanted to run the Pex PEX on. As
  # such, we just ship unadorned Pex which is pure-python and universal. Any user wanting the extra
  # is encouraged to build a Pex PEX for their particular platform themselves.
  pex_requirement = '.'

  args = [
    sys.executable,
    '-m', 'pex',
    '-v',
    '--disable-cache',
    '--no-build',
    '--no-compile',
    '--no-use-system-time',
    '--interpreter-constraint', python_requires(),
    '--python-shebang', '/usr/bin/env python',
    '-o', 'dist/pex',
    '-c', 'pex',
    pex_requirement
  ]
  subprocess.run(args, check=True)


if __name__ == '__main__':
  if not PROJECT_METADATA.is_file():
    print('This script must be run from the root of the Pex repo.', file=sys.stderr)
    sys.exit(1)

  build_pex_pex()
