#!/bin/bash

coverage run -p -m py.test tests
coverage run -p -m pex.bin.pex --help >&/dev/null
coverage run -p -m pex.bin.pex scripts/do_nothing.py
coverage run -p -m pex.bin.pex -r requests scripts/do_nothing.py
coverage run -p -m pex.bin.pex -r setuptools -s . scripts/do_nothing.py
