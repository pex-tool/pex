#!/usr/bin/env bash

VIRTUALENV_16_7_12_RELEASE_SHA=fdfec65ff031997503fb409f365ee3aeb4c2c89f

cd $(git rev-parse --show-toplevel)

curl --fail -L \
  https://raw.githubusercontent.com/pypa/virtualenv/${VIRTUALENV_16_7_12_RELEASE_SHA}/virtualenv.py \
  > pex/tools/commands/virtualenv_16.7.12_py

