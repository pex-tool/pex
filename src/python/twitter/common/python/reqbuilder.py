# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

from __future__ import print_function

import os
import sys
import tempfile
import subprocess

from twitter.common.dirutil import safe_mkdir
from twitter.common.contextutil import environment_as, temporary_file, mutable_sys
from twitter.common.python.interpreter import PythonInterpreter

import pkg_resources

class ReqBuilder(object):
  @staticmethod
  def run_easy_install(pythonpath, arguments, interpreter):
    """
      Run easy_install with the given arguments.
    """
    if not isinstance(interpreter, PythonInterpreter):
      raise ValueError("Expected interpreter to be a PythonInterpreter!")
    with temporary_file() as fp:
      cmdline = [interpreter.binary(), '-m', 'easy_install'] + arguments
      rc = subprocess.Popen(cmdline, env = {'PYTHONPATH': ':'.join(pythonpath)},
        stdout=fp, stderr=fp).wait()
      if rc != 0:
        fp.seek(0)
        print('Failed to build!', file=sys.stderr)
        print('Error output\n%s' % fp.read(), file=sys.stderr)
      return rc == 0

  @staticmethod
  def install_requirement(req,
                          path=None,
                          extra_site_dirs=[],
                          index='http://pypi.python.org/simple',
                          repositories=['http://pypi.python.org/simple'],
                          interpreter=PythonInterpreter.get()):
    """
      Install the requirement "req" to path "path" with extra_site_dirs put
      onto the PYTHONPATH.  Returns the set of newly added Distributions
      (of type pkg_resource.Distribution.)

      "req" can either be a pkg_resources.Requirement object (e.g. created by
        pkg_resources.Requirement.parse("MySQL-python==1.2.2")) or an installable
        package (e.g. a tar.gz source distribution, a source or binary .egg)

      "path" is the into which we install the requirements.  if path is None,
      we'll create one for you.
    """

    # TODO(wickman)  Consider importing the easy_install Command class directly and
    # manipulating it with initialize/finalize options + run.

    if not isinstance(req, pkg_resources.Requirement):
      if not os.path.exists(req):
        try:
          req = pkg_resources.Requirement.parse(req)
        except:
          raise TypeError(
            "req should either be an installable file, a pkg_resources.Requirement "
            "or a valid requirement string.  got %s" % req)

    if path is None:
      path = tempfile.mkdtemp()

    if not os.path.exists(path):
      safe_mkdir(path)

    easy_install_args = [
      '--install-dir=%s' % path,
      '--site-dirs=%s' % ','.join([path] + extra_site_dirs),
      '--always-copy',
      '--multi-version',
      '--exclude-scripts',
      '-i', index]
    for repo in reversed(repositories):
      easy_install_args.extend(['-f', repo])
    easy_install_args.append(str(req))

    distributions_backup = set(pkg_resources.find_distributions(path))

    rc = ReqBuilder.run_easy_install([path] + extra_site_dirs + sys.path,
      easy_install_args, interpreter)

    distributions = set(pkg_resources.find_distributions(path))
    new_distributions = distributions - distributions_backup
    return new_distributions if rc else set()
