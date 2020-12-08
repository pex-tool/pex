The [Venv](venv.py) command uses the [virtualenv](https://github.com/pypa/virtualenv) project to
suppport creating Python 2.7 virtual environments (The Python `venv` stdlib module was added only
in Python 3).

We use the last virtualenv version to support Python 2.7, embedding it as the
[virtualenv_16.7.10_py](virtualenv_16.7.10_py) resource via the
[embed_virtualenv.sh](/scripts/embed_virtualenv.sh) script.

