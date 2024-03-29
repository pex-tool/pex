# Copyright 2015 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

from pex.compatibility import to_bytes
from pex.executor import Executor
from pex.interpreter import PythonInterpreter
from pex.typing import TYPE_CHECKING, cast
from pex.util import named_temporary_file

if TYPE_CHECKING:
    from typing import Iterable, List, Text


_COMPILER_MAIN = """
from __future__ import print_function

import os
import py_compile
import sys


def compile(root, relpaths):
  compiled = []
  errored = {}
  for relpath in relpaths:
    abspath = os.path.join(root, relpath)
    # NB: We give the compiled bytecode file a `.pyc` extension, but if PYTHONOPTIMIZE is in play
    # the generated bytecode will be optimized.  Traditionally these optimized bytecode files would
    # have a `.pyo` extension, but the extension only matters for location of the file to execute
    # for a given module and not on the interpretation of its bytecode contents.  As such we're
    # safe to pick the `.pyc` extension for all bytecode file cases without a need to interpret the
    # current optimization setting for the active python interpreter.
    pyc_relpath = relpath + 'c'
    pyc_abspath = os.path.join(root, pyc_relpath)
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
        pass

    # N.B. This subclasses `Error` only for backwards compatibility.
    class CompilationFailure(Error):
        """Indicates an error compiling one or more python source files."""

    def __init__(self, interpreter):
        # type: (PythonInterpreter) -> None
        """Creates a bytecode compiler for the given `interpreter`.

        :param interpreter: The interpreter to use to compile sources with.
        """
        self._interpreter = interpreter

    def compile(self, root, relpaths):
        # type: (str, Iterable[str]) -> List[Text]
        """Compiles the given python source files using this compiler's interpreter.

        :param root: The root path all the source files are found under.
        :param relpaths: The relative paths from the `root` of the source files to compile.
        :returns: A list of relative paths of the compiled bytecode files.
        :raises: A :class:`Compiler.Error` if there was a problem bytecode compiling any of the files.
        """
        with named_temporary_file() as fp:
            fp.write(
                to_bytes(_COMPILER_MAIN % {"root": root, "relpaths": relpaths}, encoding="utf-8")
            )
            fp.flush()

            try:
                _, out, _ = self._interpreter.execute(args=[fp.name])
            except Executor.NonZeroExit as e:
                raise self.CompilationFailure(
                    "encountered %r during bytecode compilation.\nstderr was:\n%s\n" % (e, e.stderr)
                )

            return cast("Text", out).splitlines()
