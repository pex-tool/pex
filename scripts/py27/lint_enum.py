#!/usr/bin/env python2.7

from __future__ import absolute_import, print_function

import ast
import logging
import os
import sys
from argparse import ArgumentParser
from collections import OrderedDict

from pex.common import pluralize
from pex.interpreter_constraints import InterpreterConstraint
from pex.typing import cast

# When running under MyPy, this will be set to True for us automatically; so we can use it as a
# typing module import guard to protect Python 2 imports of typing - which is not normally available
# in Python 2.
TYPE_CHECKING = False

if TYPE_CHECKING:
    from typing import Any, Iterator, List, Optional

    import colors  # vendor:skip
else:
    from pex.third_party import colors


logger = logging.getLogger(__name__)


def lint_enum(python_file):
    # type: (str) -> Iterator[str]

    with open(python_file) as fp:
        root = ast.parse(fp.read(), python_file)

    unsealed_enums = OrderedDict()  # type: OrderedDict[str, str]
    for top_level_node in ast.iter_child_nodes(root):
        if (
            unsealed_enums
            and isinstance(top_level_node, ast.Expr)
            and isinstance(top_level_node.value, ast.Call)
            and isinstance(top_level_node.value.func, ast.Attribute)
            and isinstance(top_level_node.value.func.value, ast.Name)
            and top_level_node.value.func.value.id in unsealed_enums
            and "seal" == top_level_node.value.func.attr
        ):
            unsealed_enums.pop(top_level_node.value.func.value.id)
            logger.debug(
                "Linted Enum {name} in {file} successfully.".format(
                    name=colors.green(top_level_node.value.func.value.id),
                    file=colors.cyan(python_file),
                )
            )
            continue

        if not isinstance(top_level_node, ast.ClassDef):
            continue

        if any(isinstance(base, ast.Name) and "Enum" == base.id for base in top_level_node.bases):
            yield (
                "line {line} col {col}: class {name} subclasses Enum but does not parametrize the "
                "Enum.Value type.".format(
                    line=top_level_node.lineno,
                    col=top_level_node.col_offset,
                    name=top_level_node.name,
                )
            )
        else:
            enum_bases = [
                base
                for base in top_level_node.bases
                if isinstance(base, ast.Subscript)
                and isinstance(base.value, ast.Name)
                and "Enum" == base.value.id
            ]
            if not enum_bases:
                continue
            if len(enum_bases) > 1:
                yield (
                    "line {line} col {col}: class {name} subclasses Enum multiple times but only "
                    "one Enum base is allowed.".format(
                        line=top_level_node.lineno,
                        col=top_level_node.col_offset,
                        name=top_level_node.name,
                    )
                )
            enum_base = enum_bases[0]
            if not isinstance(enum_base.slice, ast.Index):
                yield (
                    "line {line} col {col}: class {name} subclasses Enum but its type parameter is "
                    "not a single Enum.Value type name item.".format(
                        line=top_level_node.lineno,
                        col=top_level_node.col_offset,
                        name=top_level_node.name,
                    )
                )
            else:
                unsealed_enums[
                    top_level_node.name
                ] = "line {line} col {col}: class {name} subclasses Enum but {name}.seal() is " "never called.".format(
                    line=top_level_node.lineno,
                    col=top_level_node.col_offset,
                    name=top_level_node.name,
                )

    for unsealed_enum in unsealed_enums.values():
        yield unsealed_enum


def lint():
    # type: () -> Optional[str]

    top = os.getcwd()
    vendored = os.path.join(os.getcwd(), "pex", "vendor", "_vendored")
    errors = []  # type: List[str]
    for root, dirs, files in os.walk(top):
        if root == top:
            dirs[:] = [d for d in dirs if d in ("pex", "testing", "tests")]
        else:
            dirs[:] = [d for d in dirs if os.path.join(root, d) != vendored]

        for f in files:
            if f.endswith(".py"):
                python_file = os.path.join(root, f)
                for error in lint_enum(python_file):
                    errors.append(
                        "{file}: {error}".format(
                            file=os.path.relpath(python_file, top), error=error
                        )
                    )
    if errors:
        return cast(
            str,
            colors.red(
                "Found {count} bad Enum {subclasses}:\n{errors}".format(
                    count=len(errors),
                    subclasses=pluralize(errors, "subclass"),
                    errors="\n".join(
                        "{index}. {error}".format(index=index, error=error)
                        for index, error in enumerate(errors, start=1)
                    ),
                )
            ),
        )

    return None


def main():
    # type: () -> Any

    parser = ArgumentParser()
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Log information about Enums processed."
    )
    parser.add_argument(
        "--require-py27",
        action="store_true",
        help="Fail if no Python 2.7 can be found to run the script instead of just warning.",
    )
    options = parser.parse_args()

    if options.verbose:
        logging.basicConfig(level=logging.DEBUG)

    if sys.version_info[:2] != (2, 7):
        pythons = list(InterpreterConstraint.parse("==2.7.*").iter_matching())
        if not pythons:
            print(
                colors.color(
                    "Python 2.7 is required to run this script but no Python 2.7 was found on the "
                    "`PATH`.",
                    "red" if options.require_py27 else "yellow",
                ),
                file=sys.stderr,
            )
            return 1 if options.require_py27 else 0

        python = pythons[0]
        os.environ["PYTHONPATH"] = os.getcwd()
        os.execv(python.binary, [python.binary] + sys.argv)
    return lint()


if __name__ == "__main__":
    sys.exit(main())
