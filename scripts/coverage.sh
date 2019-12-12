#!/usr/bin/env bash

coverage run -p -m pytest tests
coverage run -p -m pex.bin.pex -v --help >&/dev/null
coverage run -p -m pex.bin.pex -v -- scripts/do_nothing.py
coverage run -p -m pex.bin.pex -v requests -- scripts/do_nothing.py
coverage run -p -m pex.bin.pex -v . 'setuptools>=5.7,<31.0' -- scripts/do_nothing.py
