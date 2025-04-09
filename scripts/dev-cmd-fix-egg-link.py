from __future__ import print_function

import hashlib
import os
import sys

sys.path.insert(0, "")
from pex import hashing
from pex.common import safe_delete
from pex.compatibility import ConfigParser
from pex.dist_metadata import Distribution
from pex.interpreter import PythonInterpreter
from pex.pep_376 import Hash, InstalledFile, Record
from pex.pep_427 import InstallPaths, install_scripts
from pex.version import __version__

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import Any, List


def main():
    # type: () -> Any

    if len(sys.argv) != 2:
        return "Usage: {prog} [SITE_PACKAGES_DIR]".format(prog=sys.argv[0])

    site_packages_dir = sys.argv[1]

    safe_delete(os.path.join(site_packages_dir, "pex.egg-link"))

    dist_info_dir = os.path.join(
        site_packages_dir, "pex-{version}.dist-info".format(version=__version__)
    )
    os.mkdir(dist_info_dir)

    installed_files = []  # type: List[InstalledFile]

    def record_installed_file(path):
        # type: (str) -> None

        hasher = hashlib.sha256()
        hashing.file_hash(path, digest=hasher)
        installed_files.append(
            InstalledFile(
                path=os.path.relpath(path, site_packages_dir),
                hash=Hash.create(hasher),
                size=os.stat(path).st_size,
            )
        )

    config_parser = ConfigParser()
    config_parser.read("setup.cfg")

    python_requires = os.environ.get(
        "_PEX_REQUIRES_PYTHON", config_parser.get("options", "python_requires")
    )
    with open(os.path.join(dist_info_dir, "METADATA"), "w") as metadata_fp:
        print("Metadata-Version: 2.1", file=metadata_fp)
        print("Name: pex", file=metadata_fp)
        print("Version:", __version__, file=metadata_fp)
        print("Requires-Python:", python_requires, file=metadata_fp)
    record_installed_file(metadata_fp.name)

    console_scripts = config_parser.get("options.entry_points", "console_scripts")

    with open(os.path.join(dist_info_dir, "entry_points.txt"), "w") as entry_points_write_fp:
        print("[console_scripts]", file=entry_points_write_fp)
        print(console_scripts, file=entry_points_write_fp)
    record_installed_file(entry_points_write_fp.name)

    with open(entry_points_write_fp.name, "rb") as entry_points_read_fp:
        current_interpreter = PythonInterpreter.get()
        for script_abspath in install_scripts(
            install_paths=InstallPaths.interpreter(current_interpreter),
            entry_points=Distribution.parse_entry_map(entry_points_read_fp.read()),
            interpreter=current_interpreter,
        ):
            record_installed_file(script_abspath)

    with open(
        os.path.join(
            site_packages_dir, "__editable__.pex-{version}.pth".format(version=__version__)
        ),
        "w",
    ) as pth_fp:
        print(os.path.relpath(os.path.abspath("."), site_packages_dir), file=pth_fp)
    record_installed_file(pth_fp.name)

    Record.write(os.path.join(dist_info_dir, "RECORD"), installed_files)


if __name__ == "__main__":
    sys.exit(main())
