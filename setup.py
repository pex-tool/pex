# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from setuptools import setup

with open(os.path.join(os.path.dirname(__file__), 'README.rst')) as fp:
  LONG_DESCRIPTION = fp.read() + '\n'

with open(os.path.join(os.path.dirname(__file__), 'CHANGES.rst')) as fp:
  LONG_DESCRIPTION += fp.read()


# This seems to be a fairly standard version file pattern.
#
# Populates the following variables:
#   __version__
#   __setuptools_requirement
#   __wheel_requirement
__version__ = ''
version_py_file = os.path.join(os.path.dirname(__file__), 'pex', 'version.py')
with open(version_py_file) as version_py:
  exec(compile(version_py.read(), version_py_file, 'exec'))


setup(
  name = 'pex',
  version = __version__,
  description = "The PEX packaging toolchain.",
  long_description = LONG_DESCRIPTION,
  url = 'https://github.com/pantsbuild/pex',
  license = 'Apache License, Version 2.0',
  zip_safe = True,
  classifiers = [
    'Intended Audience :: Developers',
    'License :: OSI Approved :: Apache Software License',
    'Operating System :: Unix',
    'Operating System :: POSIX :: Linux',
    'Operating System :: MacOS :: MacOS X',
    'Programming Language :: Python',
    'Programming Language :: Python :: 2',
    'Programming Language :: Python :: 2.7',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.3',
    'Programming Language :: Python :: 3.4',
    'Programming Language :: Python :: 3.5',
    'Programming Language :: Python :: 3.6',
  ],
  packages = [
    'pex',
    'pex.bin',
    'pex.commands',
  ],
  install_requires = [
    SETUPTOOLS_REQUIREMENT,
    WHEEL_REQUIREMENT,
  ],
  extras_require={
    # For improved subprocess robustness under python2.7.
    'subprocess': ['subprocess32>=3.2.7'],
    # For improved requirement resolution and fetching robustness.
    'requests': ['requests>=2.8.14'],
    # For improved requirement resolution and fetching performance.
    'cachecontrol': ['CacheControl>=0.12.3'],
  },
  tests_require = [
    'mock',
    'twitter.common.contextutil>=0.3.1,<0.4.0',
    'twitter.common.lang>=0.3.1,<0.4.0',
    'twitter.common.testing>=0.3.1,<0.4.0',
    'twitter.common.dirutil>=0.3.1,<0.4.0',
    'pytest',
  ],
  entry_points = {
    'distutils.commands': [
      'bdist_pex = pex.commands.bdist_pex:bdist_pex',
    ],
    'console_scripts': [
      'pex = pex.bin.pex:main',
    ],
  },
)
