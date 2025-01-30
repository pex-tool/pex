# Copyright 2018 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import glob
import os
import pkgutil
import re
import subprocess
import sys
from argparse import ArgumentParser
from collections import OrderedDict, defaultdict
from typing import FrozenSet, Iterator, List

import libcst
from colors import bold, green, yellow  # vendor:skip
from libcst import (
    Arg,
    AsName,
    Attribute,
    BaseCompoundStatement,
    BaseExpression,
    BaseStatement,
    Call,
    Comment,
    CSTNode,
    CSTTransformer,
    CSTVisitor,
    FlattenSentinel,
    If,
    Module,
    Name,
    RemovalSentinel,
    SimpleStatementLine,
    SimpleString,
)

from pex.common import safe_delete, safe_mkdir, safe_mkdtemp, safe_open, safe_rmtree
from pex.typing import TYPE_CHECKING
from pex.vendor import VendorSpec, iter_vendor_specs

if TYPE_CHECKING:
    from typing import Union

    from libcst import BaseSmallStatement, Import, ImportAlias, ImportFrom


class _VendorSkipVisitor(CSTVisitor):
    @classmethod
    def skipped(cls, node):
        # type: (CSTNode) -> bool

        visitor = cls()
        node.visit(visitor)
        return visitor._skipped

    def __init__(self):
        # type: () -> None
        super(_VendorSkipVisitor, self).__init__()
        self._skipped = False

    def visit_Comment(self, node):
        # type: (Comment) -> None
        if node.value.strip() == "# vendor:skip":
            self._skipped = True


class _ImportRewriter(CSTTransformer):
    # The leading indents surrounding the if/else import blocks we inject can be wrong in some
    # cases. We work around this by letting these comment lines suffer the mis-indenting and then
    # removing these lines from the final output.
    _VENDORED_IMPORT_SENTINEL = "#__vendored_import_begin__"

    @classmethod
    def iter_lines(cls, module):
        # type: (Module) -> Iterator[str]
        for line in module.code.splitlines(keepends=True):
            if line.strip() != cls._VENDORED_IMPORT_SENTINEL:
                yield line

    def __init__(
        self,
        module,  # type: Module
        project_name,  # type: str
        prefix,  # type: str
        packages,  # type: FrozenSet[str]
    ):
        # type: (...) -> None
        super(_ImportRewriter, self).__init__()
        self._module = module
        self._project_name = project_name
        self._raw_prefix = prefix
        self._prefix = libcst.parse_expression(prefix, config=self._module.config_for_parsing)
        self._packages = packages
        self.modifications = OrderedDict()  # type: OrderedDict[str, str]
        self._skipping = False

    def visit_SimpleStatementLine(self, node):
        # type: (SimpleStatementLine) -> None

        if _VendorSkipVisitor.skipped(node):
            print(
                "Skipping {line} as directed by # vendor:skip".format(
                    line=self._module.code_for_node(node).strip()
                )
            )
            self._skipping = True

    def leave_SimpleStatementLine(
        self,
        original_node,  # type: SimpleStatementLine
        updated_node,  # type: SimpleStatementLine
    ):
        # type: (...) -> Union[BaseStatement, FlattenSentinel[BaseStatement], RemovalSentinel]

        self._skipping = False

        # libcst parses an import as part of a simple statement, but an `If` can't be in a
        # `SimpleStatementLine`. Use `FlattenSentinel` to fix it.
        if any(isinstance(b, If) for b in updated_node.body):
            nodes = list(updated_node.leading_lines)  # type: List[CSTNode]
            nodes.extend(updated_node.body)
            nodes.append(updated_node.trailing_whitespace)
            return FlattenSentinel(nodes=nodes)  # type: ignore[arg-type]
        return updated_node

    def leave_Call(
        self,
        original_node,  # type: Call
        updated_node,  # type: Call
    ):
        # type: (...) -> BaseExpression

        if self._skipping:
            return updated_node

        if not isinstance(updated_node.func, Name) or updated_node.func.value != "__import__":
            return updated_node

        original = self._module.code_for_node(original_node)

        def warn_skip():
            # type: () -> BaseExpression
            print(
                yellow("WARNING: Skipping {statement}".format(statement=original)), file=sys.stderr
            )
            return updated_node

        if len(updated_node.args) != 1:
            return warn_skip()

        arg0 = updated_node.args[0].value
        if not isinstance(arg0, SimpleString):
            return warn_skip()

        if arg0.raw_value.split(".")[0] not in self._packages:
            return updated_node

        updated = self._module.code_for_node(
            updated_node.with_changes(
                args=tuple(
                    [
                        Arg(  # type: ignore[call-arg]
                            arg0.with_changes(
                                value="{quote}{prefix}.{value}{quote}".format(
                                    quote=arg0.quote, prefix=self._raw_prefix, value=arg0.raw_value
                                )
                            )
                        )
                    ]
                )
            )
        )
        modified = self._modify_import(original, updated)
        self.modifications[original] = self._module.code_for_node(modified)
        return modified  # type: ignore[return-value]

    def leave_Import(
        self,
        original_node,  # type: Import
        updated_node,  # type: Import
    ):
        # type: (...) -> Union[BaseSmallStatement, FlattenSentinel[BaseSmallStatement], RemovalSentinel]

        if self._skipping:
            return updated_node

        names = []  # type: List[ImportAlias]
        modified = False
        for index, import_alias in enumerate(updated_node.names):
            root_package = import_alias.name
            while isinstance(root_package, Attribute):
                root_package = root_package.value  # type: ignore[assignment]
            assert isinstance(root_package, Name)
            if root_package.value not in self._packages:
                names.append(import_alias)
                continue

            modified = True

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

            def prefixed_fullname():
                # type: () -> ImportAlias
                return import_alias.with_changes(
                    name=Attribute(
                        self._prefix, import_alias.name  # type: ignore[arg-type, call-arg]
                    )
                )

            if import_alias.asname:  # Cases 3 and 4.
                names.append(prefixed_fullname())
            else:
                if isinstance(import_alias.name, Attribute):  # Case 2.
                    names.insert(index, prefixed_fullname())

                # Cases 1 and 2.
                names.append(
                    import_alias.with_changes(
                        name=Attribute(self._prefix, root_package),  # type: ignore[call-arg]
                        asname=AsName(root_package),  # type: ignore[call-arg]
                    )
                )

        if not modified:
            return updated_node

        original = self._module.code_for_node(original_node)
        updated = self._module.code_for_node(updated_node.with_changes(names=tuple(names)))
        modified_import = self._modify_import(original, updated)
        self.modifications[original] = self._module.code_for_node(modified_import)
        return modified_import  # type: ignore[return-value]

    def leave_ImportFrom(
        self,
        original_node,  # type: ImportFrom
        updated_node,  # type: ImportFrom
    ):
        # type: (...) -> Union[BaseSmallStatement, FlattenSentinel[BaseSmallStatement], RemovalSentinel]

        if self._skipping:
            return updated_node

        # We don't care about relative imports which will point back into vendored code if the
        # origin is within vendored code.
        if not original_node.module or original_node.relative:
            return updated_node

        package = original_node.module
        while isinstance(package, Attribute):
            package = package.value  # type: ignore[assignment]
        assert isinstance(package, Name)
        if package.value not in self._packages:
            return updated_node

        original = self._module.code_for_node(original_node)
        updated = self._module.code_for_node(
            updated_node.with_changes(
                module=Attribute(
                    self._prefix, original_node.module  # type: ignore[arg-type, call-arg]
                )
            )
        )
        modified = self._modify_import(original, updated)
        self.modifications[original] = self._module.code_for_node(modified)
        return modified  # type: ignore[return-value]

    def _modify_import(
        self,
        original,  # type: str
        modified,  # type: str
    ):
        # type: (...) -> Union[SimpleStatementLine, BaseCompoundStatement]

        lines = (
            self._VENDORED_IMPORT_SENTINEL,
            'if "{project_name}" in __import__("os").environ.get("__PEX_UNVENDORED__", ""):'.format(
                project_name=self._project_name
            ),
            "{indent}{original_import}  # vendor:skip".format(
                indent=self._module.default_indent, original_import=original
            ),
            "else:",
            "{indent}{modified_import}".format(
                indent=self._module.default_indent, modified_import=modified
            ),
        )
        return libcst.parse_statement(
            self._module.default_newline.join(lines), config=self._module.config_for_parsing
        )


class ImportRewriter(object):
    """Rewrite imports of a set of root modules to be prefixed.

    Rewriting imports in this way is often referred to as shading. In combination with a PEP-302
    importer that can keep shaded code isolated from the normal ``sys.path`` robust vendoring of
    third party code can be achieved.
    """

    @classmethod
    def for_path_items(cls, prefix, path_items):
        pkg_names = frozenset(pkg_name for _, pkg_name, _ in pkgutil.iter_modules(path=path_items))
        return cls(prefix=prefix, packages=pkg_names)

    def __init__(self, prefix, packages):
        self._prefix = prefix
        self._packages = packages

    def rewrite(self, project_name, python_file):
        with open(python_file) as fp:
            module = libcst.parse_module(fp.read())
        import_rewriter = _ImportRewriter(
            module=module,
            project_name=project_name,
            prefix=self._prefix,
            packages=self._packages,
        )
        rewritten_module = module.visit(import_rewriter)
        if import_rewriter.modifications:
            with open(python_file, "w") as fp:
                for line in _ImportRewriter.iter_lines(rewritten_module):
                    fp.write(line)
            return import_rewriter.modifications


class VendorizeError(Exception):
    """Indicates an error was encountered updating vendored libraries."""


def find_site_packages(prefix_dir):
    for root, dirs, _ in os.walk(prefix_dir):
        for d in dirs:
            if "site-packages" == d:
                return os.path.join(root, d)

    raise VendorizeError(
        "Failed to locate a site-packages directory within installation prefix "
        "{prefix_dir}.".format(prefix_dir=prefix_dir)
    )


def vendorize(root_dir, vendor_specs, prefix, update):
    # There is bootstrapping catch-22 here. In order for `pex.third_party` to work, all 3rdparty
    # importable code must lie at the top of its vendored chroot. Although
    # `pex.pep_472.install_wheel_chroot` encodes the logic to achieve this layout, we can't run
    # that without 1st approximating that layout!. We take the tack of performing an importable
    # installation using `pip wheel ...` + `wheel unpack ...`. Although simply un-packing a wheel
    # does not make it importable in general, it works for our pure-python vendored code.

    unpacked_wheel_chroots_by_vendor_spec = defaultdict(list)
    for vendor_spec in vendor_specs:
        # NB: We set --no-build-isolation to prevent pip from installing the requirements listed in
        # its [build-system] config in its pyproject.toml.
        #
        # Those requirements are (currently) the unpinned ["setuptools", "wheel"], which will cause
        # pip to use the latest version of those packages.  This is a hermeticity problem:
        # re-vendoring a package at a later time may yield a different result.  At the very least
        # the result will differ in the version embedded in the WHEEL metadata file, which causes
        # issues with our tests.
        #
        # Setting --no-build-isolation means that versions of setuptools and wheel must be provided
        # in the environment in which we run the pip command, which is the environment in which we
        # run pex.vendor. Since we document that pex.vendor should be run via tox, that environment
        # will contain pinned versions of setuptools and wheel. We further set `--no-cache-dir` so
        # that Pip finds no newer versions of wheel in its cache. As a result, vendoring (at least
        # via tox) is hermetic.
        requirement = vendor_spec.prepare()
        wheels_dir = safe_mkdtemp()
        cmd = [
            "pip",
            "wheel",
            "--no-build-isolation",
            "--no-cache-dir",
            "--wheel-dir",
            wheels_dir,
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

        # Temporarily make importable code available in the vendor chroot for importing Pex code
        # later.
        safe_mkdir(vendor_spec.target_dir)
        for wheel_file in glob.glob(os.path.join(wheels_dir, "*.whl")):
            extract_dir = os.path.join(wheels_dir, ".extracted")
            output = subprocess.check_output(
                ["wheel", "unpack", "--dest", extract_dir, wheel_file]
            ).decode("utf-8")
            match = re.match(r"^Unpacking to: (?P<unpack_dir>.+)\.\.\.OK$", output)
            assert match is not None, (
                "Failed to determine {wheel_file} unpack dir from wheel unpack output:\n"
                "{output}".format(wheel_file=wheel_file, output=output)
            )
            unpacked_to_dir = os.path.join(extract_dir, match["unpack_dir"])
            unpacked_wheel_dir = os.path.join(extract_dir, os.path.basename(wheel_file))
            os.rename(unpacked_to_dir, unpacked_wheel_dir)
            unpacked_wheel_chroots_by_vendor_spec[vendor_spec].append(unpacked_wheel_dir)
            for path in os.listdir(unpacked_wheel_dir):
                os.symlink(
                    os.path.join(unpacked_wheel_dir, path),
                    os.path.join(vendor_spec.target_dir, path),
                )

        if vendor_spec.constrain:
            cmd = ["pip", "freeze", "--all", "--path", vendor_spec.target_dir]
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
            stdout, _ = process.communicate()
            if process.returncode != 0:
                raise VendorizeError("Failed to freeze vendoring of {!r}".format(vendor_spec))
            with open(constraints_file, "wb") as fp:
                fp.write(stdout)

        vendor_spec.create_packages()

    vendored_path = [
        (vendor_spec.key, vendor_spec.target_dir)
        for vendor_spec in vendor_specs
        if vendor_spec.rewrite
    ]
    import_rewriter = ImportRewriter.for_path_items(
        prefix=prefix, path_items=[rewrite_path for _, rewrite_path in vendored_path]
    )

    rewrite_paths = [(c, os.path.join(root_dir, c)) for c in ("pex", "tests")] + vendored_path
    for project_name, rewrite_path in rewrite_paths:
        for root, dirs, files in os.walk(rewrite_path, followlinks=True):
            if root == os.path.join(root_dir, "pex", "vendor"):
                dirs[:] = [d for d in dirs if d != "_vendored"]
            for f in files:
                if f.endswith(".py"):
                    python_file = os.path.join(root, f)
                    print(green("Examining {python_file}...".format(python_file=python_file)))
                    modifications = import_rewriter.rewrite(project_name, python_file)
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
    from pex.dist_metadata import ProjectNameAndVersion, Requirement
    from pex.pep_427 import install_wheel_chroot

    for vendor_spec in vendor_specs:
        print(
            bold(
                green(
                    "Finalizing vendoring of {requirement}".format(
                        requirement=vendor_spec.requirement
                    )
                )
            )
        )

        # With Pex code needed for the final vendor installs imported, we can safely clear out the
        # vendor install dirs.
        for name in os.listdir(vendor_spec.target_dir):
            if name.endswith(".pyc") or name in ("__init__.py", "__pycache__", "constraints.txt"):
                continue
            path = os.path.join(vendor_spec.target_dir, name)
            assert os.path.islink(path), (
                "Expected {target_dir} to be composed ~purely of top-level symlinks but {path} "
                "is not.".format(target_dir=vendor_spec.target_dir, path=path)
            )
            os.unlink(path)

        # We want the primary artifact to own any special Pex wheel chroot metadata; so we arrange
        # a list of installs that place it last.
        primary_project = Requirement.parse(vendor_spec.requirement).project_name
        wheel_chroots_by_project_name = {
            ProjectNameAndVersion.from_filename(
                wheel_chroot
            ).canonicalized_project_name: wheel_chroot
            for wheel_chroot in unpacked_wheel_chroots_by_vendor_spec[vendor_spec]
        }
        primary_wheel_chroot = wheel_chroots_by_project_name.pop(primary_project)
        wheels_chroots_to_install = list(wheel_chroots_by_project_name.values())
        wheels_chroots_to_install.append(primary_wheel_chroot)

        for wheel_chroot in wheels_chroots_to_install:
            dest_dir = safe_mkdtemp()
            subprocess.check_call(["wheel", "pack", "--dest-dir", dest_dir, wheel_chroot])
            wheel_files = glob.glob(os.path.join(dest_dir, "*.whl"))
            assert len(wheel_files) == 1, (
                "Expected re-packing {wheel_chroot} to produce one `.whl` file but found {count}:\n"
                "{wheel_files}"
            ).format(
                wheel_chroot=wheel_chroot,
                count=len(wheel_files),
                wheel_files="\n".join(os.path.basename(wheel_file) for wheel_file in wheel_files),
            )
            install_wheel_chroot(wheel_path=wheel_files[0], destination=vendor_spec.target_dir)


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
