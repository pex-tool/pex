import os
import subprocess
import sys

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import Any


def main():
    # type: () -> Any

    if len(sys.argv) != 2:
        return "Usage: {prog} [_PEX_REQUIRES_PYTHON_VALUE]".format(prog=sys.argv[0])

    return subprocess.call(
        args=[sys.executable, "-m", "pip", "install", "-e", "."],
        env={**os.environ, "_PEX_REQUIRES_PYTHON": sys.argv[1]},
    )


if __name__ == "__main__":
    sys.exit(main())
