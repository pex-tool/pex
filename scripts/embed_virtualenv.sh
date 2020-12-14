#!/usr/bin/env bash

VIRTUALENV_16_7_10_RELEASE_SHA=941d218accf5e8b5672b3c528a73f7d5e2aa18bb

cd $(git rev-parse --show-toplevel)

curl --fail -L \
  https://raw.githubusercontent.com/pypa/virtualenv/${VIRTUALENV_16_7_10_RELEASE_SHA}/virtualenv.py \
  > pex/tools/commands/virtualenv_16.7.10_py

