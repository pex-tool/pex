# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
import pkgutil
import shutil
import subprocess
import sys
from argparse import ArgumentParser
from collections import OrderedDict, defaultdict

from colors import bold, green, yellow
from redbaron import CommentNode, LiteralyEvaluable, NameNode, RedBaron

from pex.common import (
    find_site_packages,
    safe_delete,
    safe_mkdir,
    safe_mkdtemp,
    safe_open,
    safe_rmtree,
)
from pex.vendor import VendorSpec, iter_vendor_specs


class ImportRewriter(object):
    """Rewrite imports of a set of root modules to be prefixed.

    Rewriting imports in this way is often referred to as shading. In combination with a PEP-302
    importer that can keep shaded code isolated from the normal ``sys.path`` robust vendoring of
    third party code can be achieved.
    """

    @staticmethod
    def _parse(python_file):
        with open(python_file) as fp:
            # NB: RedBaron is used instead of ``ast`` since it can round-trip from source code without
            # losing formatting. See: https://github.com/PyCQA/redbaron
            return RedBaron(fp.read())

    @staticmethod
    def _skip(node):
        next_node = node.next_recursive
        if isinstance(next_node, CommentNode) and next_node.value.strip() == "# vendor:skip":
            print("Skipping {} as directed by {}".format(node, next_node))
            return True
        return False

    @staticmethod
    def _find_literal_node(statement, call_argument):
        # The list of identifiers is large and they represent disjoint types:
        #   'StringNode'
        #   'BinaryStringNode'
        #   'RawStringNode'
        #   'InterpolatedRawStringNode'
        #   ...
        # Instead of trying to keep track of that, since we're specialized to the context of __import__,
        # Just accept any LiteralyEvaluable node (a mixin the above all implement) that python
        # accepts - except NameNode which we don't want and whose existence as a LiteralyEvaluable is
        # questionable to boot. In other words, we do not want to attempt to transform:
        #   variable = 'bob'
        #   __import__(variable, ...)
        # We just accept we'll miss more complex imports like this and have to fix by hand.

        if isinstance(call_argument.value, NameNode):
            print(yellow("WARNING: Skipping {}".format(statement)), file=sys.stderr)
        elif isinstance(call_argument.value, LiteralyEvaluable):
            return call_argument.value

    @staticmethod
    def _modify_import(original, modified):
        indent = " " * (modified.absolute_bounding_box.top_left.column - 1)
        return os.linesep.join(
            indent + line
            for line in (
                'if "__PEX_UNVENDORED__" in __import__("os").environ:',
                "  {}  # vendor:skip".format(original),
                "else:",
                "  {}".format(modified),
            )
        )

    @classmethod
    def for_path_items(cls, prefix, path_items):
        pkg_names = frozenset(pkg_name for _, pkg_name, _ in pkgutil.iter_modules(path=path_items))
        return cls(prefix=prefix, packages=pkg_names)

    def __init__(self, prefix, packages):
        self._prefix = prefix
        self._packages = packages

    def rewrite(self, python_file):
        modififications = OrderedDict()

        red_baron = self._parse(python_file)
        modififications.update(self._modify__import__calls(red_baron))
        modififications.update(self._modify_import_statements(red_baron))
        modififications.update(self._modify_from_import_statements(red_baron))

        if modififications:
            with open(python_file, "w") as fp:
                fp.write(red_baron.dumps())
            return modififications

    def _modify__import__calls(self, red_baron):  # noqa: We want __import__ as part of the name.
        for call_node in red_baron.find_all("CallNode"):
            if call_node.previous and call_node.previous.value == "__import__":
                if self._skip(call_node):
                    continue

                parent = call_node.parent_find("AtomtrailersNode")
                original = parent.copy()
                first_argument = call_node[0]
                raw_value = self._find_literal_node(parent, first_argument)
                if raw_value:
                    value = raw_value.to_python()
                    root_package = value.split(".")[0]
                    if root_package in self._packages:
                        raw_value.replace("{!r}".format(self._prefix + "." + value))

                        parent.replace(self._modify_import(original, parent))
                        yield original, parent

    def _modify_import_statements(self, red_baron):
        for import_node in red_baron.find_all("ImportNode"):
            modified = False
            if self._skip(import_node):
                continue

            original = import_node.copy()
            for index, import_module in enumerate(import_node):
                root_package = import_module[0]
                if root_package.value not in self._packages:
                    continue

                # We need to handle 4 possible cases:
                # 1. a -> pex.third_party.a as a
                # 2. a.b -> pex.third_party.a.b, pex.third_party.a as a
                # 3. a as b -> pex.third_party.a as b
                # 4. a.b as c -> pex.third_party.a.b as c
                #
                # Of these, 2 is the interesting case. The code in question would be like:
                # ```
                # import a.b.c
                # ...
                # a.b.c.func()
                # ```
                # So we need to have imported `a.b.c` but also exposed the root of that package path, `a`
                # under the name expected by code. The import of the `a.b.c` leaf ensures all parent
                # packages have been imported (getting the middle `b` in this case which is not explicitly
                # imported). This ensures the code can traverse from the re-named root - `a` in this
                # example, through middle nodes (`a.b`) all the way to the leaf target (`a.b.c`).

                modified = True

                def prefixed_fullname():
                    return "{prefix}.{module}".format(
                        prefix=self._prefix, module=".".join(map(str, import_module))
                    )

                if import_module.target:  # Cases 3 and 4.
                    import_module.value = prefixed_fullname()
                else:
                    if len(import_module) > 1:  # Case 2.
                        import_node.insert(index, prefixed_fullname())

                    # Cases 1 and 2.
                    import_module.value = "{prefix}.{root}".format(
                        prefix=self._prefix, root=root_package.value
                    )
                    import_module.target = root_package.value

            if modified:
                import_node.replace(self._modify_import(original, import_node))
                yield original, import_node

    def _modify_from_import_statements(self, red_baron):
        for from_import_node in red_baron.find_all("FromImportNode"):
            if self._skip(from_import_node):
                continue

            if len(from_import_node) == 0:
                # NB: `from . import ...` has length 0, but we don't care about relative imports which will
                # point back into vendored code if the origin is within vendored code.
                continue

            original = from_import_node.copy()
            root_package = from_import_node[0]
            if root_package.value in self._packages:
                root_package.replace(
                    "{prefix}.{root}".format(prefix=self._prefix, root=root_package.value)
                )

                from_import_node.replace(self._modify_import(original, from_import_node))
                yield original, from_import_node


class VendorizeError(Exception):
    """Indicates an error was encountered updating vendored libraries."""


def vendorize(root_dir, vendor_specs, prefix, update):
    # There is bootstrapping catch-22 here. In order for `pex.third_party` to work, all 3rdparty
    # importable code must lie at the top of its vendored chroot. Although
    # `pex.pep_376.Record.fixup_install` encodes the logic to achieve this layout, we can't run
    # that without 1st approximating that layout!. We take the tack of doing the --prefix
    # install off into a temp dir, moving the site-packages importables into the vendor chroot,
    # importing the code we'll need, then moving the importables back.
    moved = {}

    prefix_dir_by_vendor_spec = defaultdict(safe_mkdtemp)
    for vendor_spec in vendor_specs:
        # NB: We set --no-build-isolation to prevent pip from installing the requirements listed in
        # its [build-system] config in its pyproject.toml.
        #
        # Those requirements are (currently) the unpinned ["setuptools", "wheel"], which will cause pip
        # to use the latest version of those packages.  This is a hermeticity problem: re-vendoring a
        # package at a later time may yield a different result.  At the very least the result will
        # differ in the version embedded in the WHEEL metadata file, which causes issues with our
        # tests.
        #
        # Setting --no-build-isolation means that versions of setuptools and wheel must be provided
        # in the environment in which we run the pip command, which is the environment in which we run
        # pex.vendor. Since we document that pex.vendor should be run via tox, that environment will
        # contain pinned versions of setuptools and wheel. As a result, vendoring (at least via tox)
        # is hermetic.
        requirement = vendor_spec.prepare()
        cmd = [
            "pip",
            "install",
            "--no-compile",
            "--prefix",
            prefix_dir_by_vendor_spec[vendor_spec],
            # In `--prefix` scheme, Pip warns about installed scripts not being on $PATH. We fix
            # this when a PEX is turned into a venv.
            "--no-warn-script-location",
            # In `--prefix` scheme, Pip normally refuses to install a dependency already in the
            # `sys.path` of Pip itself since the requirement is already satisfied. Since `pip`,
            # `setuptools` and `wheel` are always in that `sys.path` (Our `pip.pex` venv PEX), we
            # force installation so that PEXes with dependencies on those projects get them properly
            # installed instead of skipped.
            "--force-reinstall",
            "--ignore-installed",
            requirement,
        ]

        constraints_file = os.path.join(vendor_spec.target_dir, "constraints.txt")
        if update and (vendor_spec.constrain or vendor_spec.constraints):
            safe_delete(constraints_file)
            if vendor_spec.constraints:
                with safe_open(constraints_file, "w") as fp:
                    for constraint in vendor_spec.constraints:
                        print(constraint, file=fp)
                cmd.extend(["--constraint", constraints_file])
        elif vendor_spec.constrain:
            # Use the last checked-in constraints if any.
            subprocess.call(["git", "checkout", "--", constraints_file])
            if os.path.isfile(constraints_file):
                cmd.extend(["--constraint", constraints_file])

        result = subprocess.call(cmd)
        if result != 0:
            raise VendorizeError("Failed to vendor {!r}".format(vendor_spec))

        # Temporarily move importable code into the vendor chroot for importing tools later.
        site_packages = find_site_packages(prefix_dir=prefix_dir_by_vendor_spec[vendor_spec])
        safe_mkdir(vendor_spec.target_dir)
        for item in os.listdir(site_packages):
            src = os.path.join(site_packages, item)
            dst = os.path.join(vendor_spec.target_dir, item)
            shutil.move(src, dst)
            moved[dst] = src

        if vendor_spec.constrain:
            cmd = ["pip", "freeze", "--all", "--path", vendor_spec.target_dir]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
            stdout, _ = process.communicate()
            if process.returncode != 0:
                raise VendorizeError("Failed to freeze vendoring of {!r}".format(vendor_spec))
            with open(constraints_file, "wb") as fp:
                fp.write(stdout)

        vendor_spec.create_packages()

    vendored_path = [vendor_spec.target_dir for vendor_spec in vendor_specs if vendor_spec.rewrite]
    import_rewriter = ImportRewriter.for_path_items(prefix=prefix, path_items=vendored_path)

    rewrite_paths = [os.path.join(root_dir, c) for c in ("pex", "tests")] + vendored_path
    for rewrite_path in rewrite_paths:
        for root, dirs, files in os.walk(rewrite_path):
            if root == os.path.join(root_dir, "pex", "vendor"):
                dirs[:] = [d for d in dirs if d != "_vendored"]
            for f in files:
                if f.endswith(".py"):
                    python_file = os.path.join(root, f)
                    print(green("Examining {python_file}...".format(python_file=python_file)))
                    modifications = import_rewriter.rewrite(python_file)
                    if modifications:
                        num_mods = len(modifications)
                        print(
                            bold(
                                green(
                                    "  Vendorized {count} import{plural} in {python_file}".format(
                                        count=num_mods,
                                        plural="s" if num_mods > 1 else "",
                                        python_file=python_file,
                                    )
                                )
                            )
                        )
                        for _from, _to in modifications.items():
                            print("    {} -> {}".format(_from, _to))

    # Import all code needed below now before we move any vendored bits it depends on temporarily
    # back to the prefix site-packages dir.
    from pex.pep_376 import Record
    from pex.third_party.pkg_resources import find_distributions

    dist_by_vendor_spec = OrderedDict()
    for vendor_spec in vendor_specs:
        for dist in find_distributions(vendor_spec.target_dir):
            if dist.key == vendor_spec.key:
                dist_by_vendor_spec[vendor_spec] = dist
                break
        if vendor_spec not in dist_by_vendor_spec:
            raise RuntimeError("Failed to find a distribution for {}.".format(vendor_spec))

    # Move the importables back to their temporary dir chroot original locations.
    for dst, src in moved.items():
        shutil.move(dst, src)

    for vendor_spec in vendor_specs:
        print(
            bold(
                green(
                    "Fixing up scripts and distribution metadata for {requirement}".format(
                        requirement=vendor_spec.requirement
                    )
                )
            )
        )
        # Move the `pip install --prefix` temporary dir chroot into the vendor chroot.
        prefix_dir = prefix_dir_by_vendor_spec[vendor_spec]
        for item in os.listdir(prefix_dir):
            shutil.move(os.path.join(prefix_dir, item), os.path.join(vendor_spec.target_dir, item))
        dist = dist_by_vendor_spec[vendor_spec]

        # Finally, let Record fixup the chroot to its final importable form.
        record = Record.from_prefix_install(
            prefix_dir=vendor_spec.target_dir,
            project_name=dist.project_name,
            version=dist.version,
        )
        record.fixup_install(exclude=("constraints.txt", "__init__.py", "__pycache__"))


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--no-update",
        dest="update",
        default=True,
        action="store_false",
        help="Do not update vendored project versions, just vendorize the existing versions afresh.",
    )
    options = parser.parse_args()

    root_directory = VendorSpec.ROOT
    try:
        safe_rmtree(VendorSpec.vendor_root())
        vendorize(
            root_dir=root_directory,
            vendor_specs=list(iter_vendor_specs()),
            prefix="pex.third_party",
            update=options.update,
        )
        sys.exit(0)
    except VendorizeError as e:
        print("Problem encountered vendorizing: {}".format(e), file=sys.stderr)
        sys.exit(1)
