# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import subprocess
import tempfile

from .compatibility import to_bytes


_COMPILER_MAIN = """
from __future__ import print_function

import os
import py_compile
import sys


def ensure_dir(file_path):
  parent = os.path.dirname(file_path)
  if not os.path.exists(parent):
    os.makedirs(parent)


def compile(root, relpaths):
  compiled = []
  errored = {}
  for relpath in relpaths:
    abspath = os.path.join(root, relpath)
    pyc_relpath = relpath + 'c'
    pyc_abspath = os.path.join(root, pyc_relpath)
    ensure_dir(pyc_abspath)
    try:
      py_compile.compile(abspath, cfile=pyc_abspath, dfile=relpath, doraise=True)
      compiled.append(pyc_relpath)
    except py_compile.PyCompileError as e:
      errored[e.file] = e.msg
  return compiled, errored


def main(root, relpaths):
  compiled, errored = compile(root, relpaths)
  if not errored:
    for path in compiled:
      print(path)
    sys.exit(0)

  print('Encountered %%d errors compiling %%d files:' %% (len(errored), len(relpaths)),
        file=sys.stderr)
  for file, msg in errored.items():
    print('  %%s: %%s' %% (file, msg), file=sys.stderr)
  sys.exit(1)

root = %(root)r
relpaths = %(relpaths)r

main(root, relpaths)
"""


class Compiler(object):
  class Error(Exception):
    """Indicates an error compiling one or more python source files."""

  def __init__(self, interpreter):
    """Creates a bytecode compiler for the given `interpreter`.

    :param interpreter: The interpreter to use to compile sources with.
    :type interpreter: :class:`pex.interpreter.PythonInterpreter`
    """
    self._interpreter = interpreter

  def compile(self, root, relpaths):
    """Compiles the given python source files using this compiler's interpreter.

    :param string root: The root path all the source files are found under.
    :param list relpaths: The realtive paths from the `root` of the source files to compile.
    :returns: A list of relative paths of the compiled bytecode files.
    :raises: A :class:`Compiler.Error` if there was a problem bytecode compiling any of the files.
    """
    with tempfile.NamedTemporaryFile() as fp:
      fp.write(to_bytes(_COMPILER_MAIN % {'root': root, 'relpaths': relpaths}, encoding='utf-8'))
      fp.flush()
      process = subprocess.Popen([self._interpreter.binary, fp.name],
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
      out, err = process.communicate()
      if process.returncode != 0:
        raise self.Error(err)
      return [pyc_relpath.decode('utf-8') for pyc_relpath in out.splitlines()]
