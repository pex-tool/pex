# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import contextlib
import importlib
import os
import shutil
import tempfile
from site import makepath  # type: ignore[attr-defined]

from pex.common import safe_delete, safe_mkdir, safe_mkdtemp
from pex.compatibility import (  # type: ignore[attr-defined]  # `exec_function` is defined dynamically
    PY2,
    exec_function,
)
from pex.orderedset import OrderedSet
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import IO, Any, Iterator, Optional


class DistributionHelper(object):
    # TODO(#584: This appears unused, but clients might still use it. We cannot remove until we
    #  have a deprecation policy.
    @classmethod
    def access_zipped_assets(cls, static_module_name, static_path, dir_location=None):
        # type: (str, str, Optional[str]) -> str
        """Create a copy of static resource files as we can't serve them from within the pex file.

        :param static_module_name: Module name containing module to cache in a tempdir
        :param static_path: Module name, for example 'serverset'
        :param dir_location: create a new temporary directory inside, or None to have one created
        :returns temp_dir: Temporary directory with the zipped assets inside
        """
        if dir_location is None:
            temp_dir = safe_mkdtemp()
        else:
            temp_dir = dir_location

        module = importlib.import_module(static_module_name)
        # N.B.: This handles namespace packages new and old.
        paths = OrderedSet(os.path.realpath(d) for d in getattr(module, "__path__", []))
        if module.__file__:
            # And this handles old-style __init__.py packages.
            paths.add(os.path.realpath(module.__file__))

        safe_mkdir(temp_dir)
        for path in paths:
            resource_dir = os.path.realpath(os.path.join(path, static_path))
            if os.path.isdir(resource_dir):
                for root, dirs, files in os.walk(resource_dir):
                    for d in dirs:
                        safe_mkdir(
                            os.path.join(
                                temp_dir, os.path.relpath(os.path.join(root, d), resource_dir)
                            )
                        )
                    for f in files:
                        src = os.path.join(root, f)
                        shutil.copy(src, os.path.join(temp_dir, os.path.relpath(src, resource_dir)))
        return temp_dir


@contextlib.contextmanager
def named_temporary_file(**kwargs):
    # type: (**Any) -> Iterator[IO]
    """Due to a bug in python (https://bugs.python.org/issue14243), we need this to be able to use
    the temporary file without deleting it."""
    assert "delete" not in kwargs
    kwargs["delete"] = False
    fp = tempfile.NamedTemporaryFile(**kwargs)
    try:
        with fp:
            yield fp
    finally:
        safe_delete(fp.name)
