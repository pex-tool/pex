# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import contextlib
import marshal
import os

import pytest
from twitter.common.contextutil import temporary_dir

from pex import compatibility
from pex.common import safe_open
from pex.compatibility import to_bytes
from pex.compiler import Compiler
from pex.interpreter import PythonInterpreter


def write_source(path, valid=True):
  with safe_open(path, 'wb') as fp:
    fp.write(to_bytes('basename = %r\n' % os.path.basename(path)))
    if not valid:
      fp.write(to_bytes('invalid!\n'))


@contextlib.contextmanager
def compilation(valid_paths=None, invalid_paths=None, compile_paths=None):
  with temporary_dir() as root:
    for path in valid_paths:
      write_source(os.path.join(root, path))
    for path in invalid_paths:
      write_source(os.path.join(root, path), valid=False)
    compiler = Compiler(PythonInterpreter.get())
    yield root, compiler.compile(root, compile_paths)


def test_compile_success():
  with compilation(valid_paths=['a.py', 'c/c.py'],
                   invalid_paths=['b.py', 'd/d.py'],
                   compile_paths=['a.py', 'c/c.py']) as (root, compiled_relpaths):

    assert 2 == len(compiled_relpaths)

    results = {}
    for compiled in compiled_relpaths:
      compiled_abspath = os.path.join(root, compiled)
      with open(compiled_abspath, 'rb') as fp:
        fp.read(4)  # Skip the magic header.
        fp.read(4)  # Skip the timestamp.
        if compatibility.PY3:
          fp.read(4)  # Skip the size.
        code = marshal.load(fp)
      local_symbols = {}
      exec(code, {}, local_symbols)
      results[compiled] = local_symbols

    assert {'basename': 'a.py'} == results.pop('a.pyc')
    assert {'basename': 'c.py'} == results.pop('c/c.pyc')
    assert 0 == len(results)


def test_compile_failure():
  with pytest.raises(Compiler.Error) as e:
    with compilation(valid_paths=['a.py', 'c/c.py'],
                     invalid_paths=['b.py', 'd/d.py'],
                     compile_paths=['a.py', 'b.py', 'c/c.py', 'd/d.py']):
      raise AssertionError('Should not reach here.')

  message = str(e.value)
  assert 'a.py' not in message
  assert 'b.py' in message
  assert 'c/c.py' not in message
  assert 'd/d.py' in message
