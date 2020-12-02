import hashlib
import itertools
import os

from pathlib import Path


SCRIPT_TEMPLATE = """#!/bin/sh

{pex_var}={entry} exec {executable} {pex_path} $@
"""


def get_hash(shebang, pex_path, entry_points, scripts):
    entry_points = sorted(entry_points)
    scripts = sorted(scripts)

    hasher = hashlib.md5()
    hasher.update(shebang.encode("utf-8"))
    hasher.update(pex_path.encode("utf-8"))
    for item in itertools.chain(entry_points, scripts):
        hasher.update(item.encode("utf-8"))

    return hasher.hexdigest()


def render_wrapper_scripts(shebang, pex_path, bin_path, entry_points, scripts):
    executable = shebang[2:]
    bin_path.mkdir(mode=0o750, parents=True, exist_ok=True)
    # TODO: what should be the script name for entry_points?
    for item in entry_points:
        item_path = bin_path / item
        contents = SCRIPT_TEMPLATE.format(
            pex_var="PEX_MODULE", entry=item, executable=executable, pex_path=pex_path
        )
        with item_path.open("w") as f:
            f.write(contents)
        item_path.chmod(0o770)

    for item in scripts:
        item_path = bin_path / item
        contents = SCRIPT_TEMPLATE.format(
            pex_var="PEX_SCRIPT", entry=item, executable=executable, pex_path=pex_path
        )
        with item_path.open("w") as f:
            f.write(contents)
        item_path.chmod(0o770)


def expose_scripts(pex_path, pex_info):
    shebang = pex_info.shebang
    exposed_entry_points = pex_info.exposed_entry_points
    exposed_scripts = pex_info.exposed_scripts

    if len(exposed_entry_points) == 0 and len(exposed_scripts) == 0:
        return

    pex_path = Path(pex_path).resolve()
    pex_path_str = str(pex_path)
    bin_hash = get_hash(shebang, pex_path_str, exposed_entry_points, exposed_scripts)
    bin_path = Path(pex_info.pex_root) / "bin" / bin_hash
    render_wrapper_scripts(
        shebang,
        pex_path_str,
        bin_path,
        exposed_entry_points,
        exposed_scripts,
    )
    env_path = os.environ.get("PATH", default="")
    os.environ["PATH"] = f"{bin_path}:{env_path}"
