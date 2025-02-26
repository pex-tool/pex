# Copyright 2015 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import os
import shlex
import subprocess
import sys
from distutils import log
from distutils.core import Command
from io import StringIO

from pex.bin.pex import configure_clp
from pex.common import die
from pex.compatibility import ConfigParser, string, to_unicode
from pex.interpreter import PythonInterpreter
from pex.os import WINDOWS


# Suppress checkstyle violations due to distutils command requirements.
class bdist_pex(Command):  # noqa
    @staticmethod
    def get_log_level():
        # A hack to get the existing distutils logging level.
        existing_level = log.set_threshold(log.INFO)
        log.set_threshold(existing_level)

        return existing_level

    description = "create a PEX file from a source distribution"  # noqa

    user_options = [  # noqa
        ("bdist-all", None, "pexify all defined entry points"),
        ("bdist-dir=", None, "the directory into which pexes will be written, default: dist."),
        ("pex-args=", None, "additional arguments to the pex tool"),
    ]

    boolean_options = [  # noqa
        "bdist-all",
    ]

    def initialize_options(self):
        self.bdist_all = False
        self.bdist_dir = None
        self.pex_args = ""

    def finalize_options(self):
        self.pex_args = shlex.split(self.pex_args, posix=not WINDOWS)

    def parse_entry_points(self):
        def parse_entry_point_name(entry_point):
            script_name = entry_point.split("=", 1)[0]
            return script_name.strip()

        raw_entry_points = self.distribution.entry_points

        if isinstance(raw_entry_points, string):
            parser = ConfigParser()
            parser.readfp(StringIO(to_unicode(raw_entry_points)))
            if parser.has_section("console_scripts"):
                return tuple(parser.options("console_scripts"))
        elif isinstance(raw_entry_points, dict):
            try:
                return tuple(
                    parse_entry_point_name(script)
                    for script in raw_entry_points.get("console_scripts", [])
                )
            except ValueError:
                pass
        elif raw_entry_points is not None:
            die("When entry_points is provided, it must be a string or dict.")

        return ()

    def run(self):
        parser = configure_clp()
        options = parser.parse_args(self.pex_args)

        if options.entry_point or options.script or options.pex_name:
            die(
                "Must not specify entry point, script or output file to --pex-args, given: {}".format(
                    " ".join(self.pex_args)
                )
            )

        name = self.distribution.get_name()
        version = self.distribution.get_version()

        package_dir = os.path.dirname(
            os.path.realpath(os.path.expanduser(self.distribution.script_name))
        )
        if self.bdist_dir is None:
            self.bdist_dir = os.path.join(package_dir, "dist")

        console_scripts = self.parse_entry_points()

        pex_specs = []
        if self.bdist_all:
            # Write all entry points into unversioned pex files.
            pex_specs.extend(
                (script_name, os.path.join(self.bdist_dir, script_name))
                for script_name in console_scripts
            )
        else:
            target = os.path.join(self.bdist_dir, name + "-" + version + ".pex")
            pex_specs.append((name if name in console_scripts else None, target))

        args = ["-m", "pex", "--project", package_dir] + options.requirements + self.pex_args
        if self.get_log_level() < log.INFO and options.verbosity == 0:
            args.append("-v")

        for script_name, target in pex_specs:
            pex_cmd = args + ["--output-file", target]
            if script_name:
                log.info("Writing %s to %s" % (script_name, target))
                pex_cmd += ["--script", script_name]
            else:
                # The package has no namesake entry point, so build an environment pex.
                log.info("Writing environment pex into %s" % target)

            cmd, process = PythonInterpreter.get().open_process(
                args=pex_cmd,
                stderr=subprocess.PIPE,
                # In order for code to run to here, pex is on the sys.path - make sure to propagate the
                # sys.path so the subprocess can find us.
                pythonpath=sys.path,
            )
            _, stderr = process.communicate()
            result = process.returncode
            if result != 0:
                die(
                    "Failed to create pex via {}:\n{}".format(
                        " ".join(cmd), stderr.decode("utf-8")
                    ),
                    result,
                )
            else:
                log.debug(
                    "Successfully created pex via {}:\n{}".format(
                        " ".join(cmd), stderr.decode("utf-8")
                    )
                )
