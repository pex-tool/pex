#!/bin/bash

coverage run -p -m py.test tests
coverage run -p -m pex.bin.pex -v --help >&/dev/null
coverage run -p -m pex.bin.pex -v -- scripts/do_nothing.py
coverage run -p -m pex.bin.pex -v requests -- scripts/do_nothing.py
coverage run -p -m pex.bin.pex -v . 'setuptools>=2.2,<20' -- scripts/do_nothing.py
