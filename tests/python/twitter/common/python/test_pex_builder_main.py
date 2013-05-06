from collections import namedtuple
import logging
import os
import pytest
import shutil
import subprocess
import tempfile
import time
import urllib2

FileSpec = namedtuple("FileSpec", ["filename", "contents"])

class PexPexRun(object):
  def __init__(self, **kwargs):
    self.__dict__.update(kwargs)
    self.pexpex = os.path.join("dist", "pex.pex")
    self.logger = logging.getLogger(__name__)

  def _ensure_dir(self, dirname):
    try:
      os.makedirs(dirname)
    except OSError as e:
      if e.errno != os.errno.EEXIST:
        raise e

  def __enter__(self):
    self.pkg_dir = pkg_dir = os.path.join(self.working_dir, self.pkg_name)
    self.pex_name = os.path.join(self.pkg_dir, self.pkg_name)

    self.source_dir_fullpath = self.pkg_dir
    files = self.files[:]
    if self.requirements_txt is not None:
      self.requirements_txt_fullpath = os.path.join(pkg_dir, self.requirements_txt.filename)
      files.append(self.requirements_txt)
    for _file in files:
      logging.info("Processing file: {0}".format(str(_file.filename)))
      fullpath = os.path.join(pkg_dir, _file.filename)
      container_dir = os.path.dirname(fullpath)
      logging.info("Ensuring directory: {0}".format(container_dir))
      self._ensure_dir(container_dir)
      logging.info("Ensuring file: {0}".format(os.path.basename(fullpath)))
      with open(fullpath, "w+") as f:
        f.write(_file.contents)
    return self

  def run(self):
    cmd = [
      self.pexpex,
      "--source-dir={0}".format(self.source_dir_fullpath),
      "--entry-point={0}".format(self.entry_point),
      "--pex-name={0}".format(self.pex_name),
      "--log-level=info",
    ]
    if not os.path.isfile(self.pexpex):
      logging.warn("pex.pex not found at {0}. Creating.".format(self.pexpex))
      assert subprocess.check_call("./pants src/python/twitter/common/python:pex", shell=True) == 0
    if self.requirements_txt is not None:
      cmd.append("--requirements-txt={0}".format(self.requirements_txt_fullpath))
    cmd_str = " ".join(cmd) # No special quoting is needed
    return subprocess.check_call(cmd_str, shell=True)

  def __exit__(self, type, value, traceback):
    logging.info("Deleting tree {0}".format(self.pkg_dir))
    shutil.rmtree(self.pkg_dir)
    logging.info("Deleted tree {0}".format(self.pkg_dir))

# ---------- Test Data ---------->

_mybottle_requirements_txt = FileSpec(
  filename="requirements.txt",
  contents="\n".join(["mako >= 0.7.0", "bottle"])
)

_mybottle_setup_py = FileSpec(
  filename="setup.py",
  contents="""
from distutils.core import setup

setup(name="mybottle",
     version="0.1.0",
     description="My bottle server",
     author="No name",
     author_email="no@email.com",
     package_dir={"": "src"},
     package_data={"mybottle": ["resources/*/*"]},
     url="http://dev.twitter.com/python/",
     packages=["mybottle"],
     )
""")

_mybottle_setup_py_with_requires = FileSpec(
  filename="setup.py",
  contents="""
from distutils.core import setup

setup(name="mybottle",
     version="0.1.0",
     description="My bottle server",
     author="No name",
     author_email="no@email.com",
     package_dir={"": "src"},
     package_data={"mybottle": ["resources/*/*"]},
     url="http://dev.twitter.com/python/",
     packages=["mybottle"],
     requires=["mako", "bottle"],
     )
""")

_mybottle_src_mybottle_server_py = FileSpec(
  filename=os.path.join("src", "mybottle", "server.py"),
  contents="""
from bottle import route, run
from mako.template import Template
from pkg_resources import resource_string

@route("/hello/:name")
def index(name="World"):
  return Template(resource_string(__package__, "resources/en_US/hello.mako")).render(data=name)

def main(args=[]):
  try:
    port = args[0]
  except IndexError as e:
    port = 8080
  run(host='0.0.0.0', port=port)

if __name__ == "__main__":
  main()
""")

_mybottle_src_mybottle_init_py = FileSpec(
  filename=os.path.join("src", "mybottle", "__init__.py"),
  contents=""
)

_mybottle_src_mybottle_resources_en_US_hello_mako = FileSpec(
  filename=os.path.join("src", "mybottle", "resources", "en_US", "hello.mako"),
  contents="Hello ${data}!"
)

# <--------- Test Data ----------

@pytest.mark.skipif("True")
class TestPEXBuilderMain(object):
  def _ensure_mybottle_pex_runs(self, mybottle_pex_path):
    max_wait_time = 10 # seconds
    step_wait_interval = 0.05
    server_process = subprocess.Popen(mybottle_pex_path, shell=True)
    for i in range(int(max_wait_time/step_wait_interval)):
      try:
        time.sleep(step_wait_interval)
        response = urllib2.urlopen("http://localhost:8080/hello/world").read()
        assert "Hello world!" in response
        break
      except urllib2.URLError as e:
        pass # retry until max_wait_time
    server_process.kill()

  def _ensure_mybottle_pex_properly_built(self, setup_py, requirements_txt):
    logging.basicConfig(level=getattr(logging, "INFO", None))
    files=[
      setup_py,
      _mybottle_src_mybottle_init_py,
      _mybottle_src_mybottle_server_py,
      _mybottle_src_mybottle_resources_en_US_hello_mako,
    ]
    with PexPexRun(working_dir=tempfile.mkdtemp(),
                   pkg_name="mybottle",
                   source_dir="mybottle",
                   requirements_txt=requirements_txt,
                   files=files,
                   entry_point="mybottle.server:main"
                  ) as pex_pex_run:
      pex_pex_run.run()
      self._ensure_mybottle_pex_runs(pex_pex_run.pex_name + ".pex")

  def test_pex_with_sources_resources_requirements(self):
    self._ensure_mybottle_pex_properly_built(
      setup_py=_mybottle_setup_py,
      requirements_txt=_mybottle_requirements_txt
    )

  def test_pex_with_sources_resources_dependencies(self):
    self._ensure_mybottle_pex_properly_built(
      setup_py=_mybottle_setup_py_with_requires,
      requirements_txt=None
    )
