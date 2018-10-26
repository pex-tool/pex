# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys


# We may be executed from outside the project dir: `python pex/setup.py ...`, so ensure the
# `setup.py` dir is on the path.
__HERE = os.path.realpath(os.path.dirname(__file__))
sys.path.append(__HERE)

from pex import vendor
vendor.adjust_sys_path(include_wheel=True)


os.chdir(__HERE)
from setuptools import find_packages, setup


with open(os.path.join(__HERE, 'README.rst')) as fp:
  LONG_DESCRIPTION = fp.read() + '\n'

with open(os.path.join(__HERE, 'CHANGES.rst')) as fp:
  LONG_DESCRIPTION += fp.read()


from pex.version import __version__


setup(
  name='pex',
  version=__version__,
  description="The PEX packaging toolchain.",
  long_description=LONG_DESCRIPTION,
  long_description_content_type="text/x-rst",
  url='https://github.com/pantsbuild/pex',
  license='Apache License, Version 2.0',
  zip_safe=False,
  classifiers=[
    'Intended Audience :: Developers',
    'License :: OSI Approved :: Apache Software License',
    'Operating System :: Unix',
    'Operating System :: POSIX :: Linux',
    'Operating System :: MacOS :: MacOS X',
    'Programming Language :: Python',
    'Programming Language :: Python :: 2',
    'Programming Language :: Python :: 2.7',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.4',
    'Programming Language :: Python :: 3.5',
    'Programming Language :: Python :: 3.6',
    'Programming Language :: Python :: 3.7',
  ],
  packages=find_packages(),
  include_package_data=True,
  extras_require={
    # For improved subprocess robustness under python2.7.
    'subprocess': ['subprocess32>=3.2.7'],
    # For improved requirement resolution and fetching robustness.
    'requests': ['requests>=2.8.14'],
    # For improved requirement resolution and fetching performance.
    'cachecontrol': ['CacheControl>=0.12.3'],
  },
  entry_points={
    'distutils.commands': [
      'bdist_pex = pex.commands.bdist_pex:bdist_pex',
    ],
    'console_scripts': [
      'pex = pex.bin.pex:main',
    ],
  },
)
