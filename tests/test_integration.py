# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from twitter.common.contextutil import temporary_dir, temporary_file

from pex.compatibility import nested
from pex.pex_builder import PEXBuilder
from pex.testing import run_simple_pex, run_simple_pex_test, temporary_content


def test_pex_execute():
  body = "print('Hello')"
  _, rc = run_simple_pex_test(body, coverage=True)
  assert rc == 0


def test_pex_raise():
  body = "raise Exception('This will improve coverage.')"
  run_simple_pex_test(body, coverage=True)


def test_pex_interpreter():
  with temporary_file() as fp:
    fp.write(b"print('Hello world')")
    fp.flush()

    env = os.environ.copy()
    env['PEX_INTERPRETER'] = '1'

    so, rc = run_simple_pex_test("", args=(fp.name,), coverage=True, env=env)
    assert so == b'Hello world\n'
    assert rc == 0


def test_pex_library_path():
  with nested(temporary_dir(),
              temporary_content({'_ext.so': 125}),
              temporary_dir()) as (pb_dir, lib, out_dir):
    main_py = os.path.join(pb_dir, 'exe.py')
    with open(main_py, 'w') as pyfile:
      pyfile.write("""
import os
import os.path

var_name = 'DYLD_LIBRARY_PATH' if os.uname()[0] == 'Darwin' else 'LD_LIBRARY_PATH'
print(any(os.path.exists(os.path.join(p, '_ext.so'))
          for p in os.environ[var_name].split(':')))
""")

    pb = PEXBuilder(path=pb_dir)
    pb.add_native_library(os.path.join(lib, '_ext.so'))
    pb.set_executable(main_py)
    pb.freeze()
    assert not pb.info.zip_safe
    pex = os.path.join(out_dir, 'app.pex')
    pb.build(pex)
    out, rc = run_simple_pex(pex)
    assert rc == 0
    assert out == b'True\n'
