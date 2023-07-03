#!/usr/bin/env bash

if [[ "3.12" = "$(python -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')" ]]
then
  python -sE -m pip install -U \
    "pip @ git+https://github.com/pypa/pip@8a1eea4aaedb1fb1c6b4c652cd0c43502f05ff37" \
    setuptools \
    wheel
fi

exec python -sE -m pip install "$@"
