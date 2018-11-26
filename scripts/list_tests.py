#!/usr/bin/env python

from __future__ import absolute_import, print_function

import sys
import pytest


class Collector(object):

  RUN_INDIVIDUALLY = ['tests/test_pex.py']

  def __init__(self):
    self._collected = set()

  def iter_collected(self):
    for collected in sorted(self._collected):
      yield collected

  def pytest_collectreport(self, report):
    if report.failed:
      raise pytest.UsageError('Errors during collection, aborting!')

  def pytest_collection_modifyitems(self, items):
    for item in items:
      test_file = item.location[0]
      if test_file in self.RUN_INDIVIDUALLY:
        self._collected.add(item.nodeid)
      else:
        self._collected.add(test_file)


collector = Collector()
rv = pytest.main(['--collect-only'] + sys.argv[1:], plugins=[collector])

for test_target in collector.iter_collected():
  print('RUNNABLE\t"{}"'.format(test_target))

sys.exit(rv)
