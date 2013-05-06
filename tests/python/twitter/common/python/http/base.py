import contextlib
import os
from twitter.common.contextutil import temporary_dir

@contextlib.contextmanager
def create_layout(*filelist):
  with temporary_dir() as td:
    for fl in filelist:
      for fn in fl:
        with open(os.path.join(td, fn), 'w') as fp:
          fp.write('junk')
    yield td
