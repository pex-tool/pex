#!/bin/bash

coverage run -p -m py.test tests
coverage run -p -m pex.bin.pex -v --help >&/dev/null
coverage run -p -m pex.bin.pex -v -- scripts/do_nothing.py
coverage run -p -m pex.bin.pex -v requests -- scripts/do_nothing.py
coverage run -p -m pex.bin.pex -v . 'setuptools>=20.2,<28.7.1' -- scripts/do_nothing.py
