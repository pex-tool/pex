# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pex.common import temporary_dir
from pex.compatibility import to_bytes
from pex.pth import iter_pth_paths
from pex.typing import TYPE_CHECKING

try:
    from unittest import mock
except ImportError:
    import mock  # type: ignore[no-redef,import]

if TYPE_CHECKING:
    from typing import Any, Dict, List


@mock.patch("os.path.exists", autospec=True, spec_set=True)
def test_iter_pth_paths(mock_exists):
    # type: (Any) -> None
    # Ensure path checking always returns True for dummy paths.
    mock_exists.return_value = True

    with temporary_dir() as tmpdir:
        in_tmp = lambda f: os.path.join(tmpdir, f)

        PTH_TEST_MAPPING = {
            # A mapping of .pth file content -> expected paths.
            "/System/Library/Frameworks/Python.framework/Versions/2.7/Extras/lib/python\n": [
                "/System/Library/Frameworks/Python.framework/Versions/2.7/Extras/lib/python"
            ],
            "relative_path\nrelative_path2\n\nrelative_path3": [
                in_tmp("relative_path"),
                in_tmp("relative_path2"),
                in_tmp("relative_path3"),
            ],
            "duplicate_path\nduplicate_path": [in_tmp("duplicate_path")],
            "randompath\nimport nosuchmodule\n": [in_tmp("randompath")],
            "import sys\nfoo\n/bar/baz": [in_tmp("foo"), "/bar/baz"],
            "import nosuchmodule\nfoo": [],
            "import nosuchmodule\n": [],
            "import bad)syntax\n": [],
        }  # type: Dict[str, List[str]]

        for i, pth_content in enumerate(PTH_TEST_MAPPING):
            pth_tmp_path = os.path.abspath(os.path.join(tmpdir, "test%s.pth" % i))
            with open(pth_tmp_path, "wb") as f:
                f.write(to_bytes(pth_content))
            assert sorted(PTH_TEST_MAPPING[pth_content]) == sorted(
                list(iter_pth_paths(pth_tmp_path))
            )
