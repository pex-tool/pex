#!/usr/bin/env bash

if [[ -n "${_PEX_TOX_INSTALL_COMMAND_PIP_REQUIREMENT}"  ]]; then
  python -sE -m pip install -U "${_PEX_TOX_INSTALL_COMMAND_PIP_REQUIREMENT}"
fi

exec python -sE -m pip install "$@"
