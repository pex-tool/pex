# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import warnings

from pex.variables import ENV


class PEXWarning(Warning):
  """Indicates a warning from PEX about suspect buildtime or runtime configuration."""


def configure_warnings(pex_info, env=None):
  env = env or ENV
  if env.PEX_VERBOSE > 0:
    emit_warnings = True
  elif env.PEX_EMIT_WARNINGS is not None:
    emit_warnings = env.PEX_EMIT_WARNINGS
  else:
    emit_warnings = pex_info.emit_warnings

  action = 'default' if emit_warnings else 'ignore'
  warnings.filterwarnings(action, category=PEXWarning)


def warn(message):
  warnings.warn(message, category=PEXWarning, stacklevel=2)
