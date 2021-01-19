# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import os
import re
import sys
import warnings
from distutils import sysconfig
from site import USER_SITE
from types import ModuleType

from pex import third_party
from pex.bootstrap import Bootstrap
from pex.common import die
from pex.compatibility import PY3
from pex.distribution_target import DistributionTarget
from pex.environment import PEXEnvironment
from pex.executor import Executor
from pex.finders import get_entry_point_from_console_script, get_script_from_distributions
from pex.inherit_path import InheritPath
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.pex_info import PexInfo
from pex.third_party.pkg_resources import Distribution, EntryPoint, find_distributions
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.util import iter_pth_paths, named_temporary_file
from pex.variables import ENV, Variables

if TYPE_CHECKING:
    from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Set, Tuple, TypeVar

    _K = TypeVar("_K")
    _V = TypeVar("_V")


class PEX(object):  # noqa: T000
    """PEX, n.

    A self-contained python environment.
    """

    class Error(Exception):
        pass

    class NotFound(Error):
        pass

    class InvalidEntryPoint(Error):
        pass

    @classmethod
    def _clean_environment(cls, env=None, strip_pex_env=True):
        env = env or os.environ

        try:
            del env["MACOSX_DEPLOYMENT_TARGET"]
        except KeyError:
            pass

        if strip_pex_env:
            for key in list(env):
                if key.startswith("PEX_"):
                    del env[key]

    def __init__(
        self,
        pex=sys.argv[0],  # type: str
        interpreter=None,  # type: Optional[PythonInterpreter]
        env=ENV,  # type: Variables
        verify_entry_point=False,  # type: bool
    ):
        # type: (...) -> None
        self._pex = pex
        self._interpreter = interpreter or PythonInterpreter.get()
        self._pex_info = PexInfo.from_pex(self._pex)
        self._pex_info_overrides = PexInfo.from_env(env=env)
        self._vars = env
        self._envs = []  # type: List[PEXEnvironment]
        self._activated_dists = None  # type: Optional[Iterable[Distribution]]
        if verify_entry_point:
            self._do_entry_point_verification()

    def pex_info(self):
        # type: () -> PexInfo
        pex_info = self._pex_info.copy()
        pex_info.update(self._pex_info_overrides)
        pex_info.merge_pex_path(self._vars.PEX_PATH)
        return pex_info

    @property
    def interpreter(self):
        # type: () -> PythonInterpreter
        return self._interpreter

    def _activate(self):
        # type: () -> Iterable[Distribution]

        # set up the local .pex environment
        pex_info = self.pex_info()
        target = DistributionTarget.for_interpreter(self._interpreter)
        self._envs.append(PEXEnvironment(self._pex, pex_info, target=target))
        # N.B. by this point, `pex_info.pex_path` will contain a single pex path
        # merged from pex_path in `PEX-INFO` and `PEX_PATH` set in the environment.
        # `PEX_PATH` entries written into `PEX-INFO` take precedence over those set
        # in the environment.
        if pex_info.pex_path:
            # set up other environments as specified in pex_path
            for pex_path in filter(None, pex_info.pex_path.split(os.pathsep)):
                pex_info = PexInfo.from_pex(pex_path)
                pex_info.update(self._pex_info_overrides)
                self._envs.append(PEXEnvironment(pex_path, pex_info, target=target))

        # activate all of them
        activated_dists = []  # type: List[Distribution]
        for env in self._envs:
            activated_dists.extend(env.activate())

        # Ensure that pkg_resources is not imported until at least every pex environment
        # (i.e. PEX_PATH) has been merged into the environment
        PEXEnvironment._declare_namespace_packages(activated_dists)
        return activated_dists

    def activate(self):
        # type: () -> Iterable[Distribution]
        if self._activated_dists is None:
            # 1. Scrub the sys.path to present a minimal Python environment.
            self.patch_sys()
            # 2. Activate all code and distributions in the PEX.
            self._activated_dists = self._activate()
        return self._activated_dists

    @classmethod
    def _extras_paths(cls):
        # type: () -> Iterator[str]
        standard_lib = sysconfig.get_python_lib(standard_lib=True)

        try:
            makefile = sysconfig.parse_makefile(  # type: ignore[attr-defined]
                sysconfig.get_makefile_filename()
            )
        except (AttributeError, IOError):
            # This is not available by default in PyPy's distutils.sysconfig or it simply is
            # no longer available on the system (IOError ENOENT)
            makefile = {}

        extras_paths = filter(
            None, makefile.get("EXTRASPATH", "").split(":")
        )  # type: Iterable[str]
        for path in extras_paths:
            yield os.path.join(standard_lib, path)

        # Handle .pth injected paths as extras.
        sitedirs = cls._get_site_packages()
        for pth_path in cls._scan_pth_files(sitedirs):
            TRACER.log("Found .pth file: %s" % pth_path, V=3)
            for extras_path in iter_pth_paths(pth_path):
                yield extras_path

    @staticmethod
    def _scan_pth_files(dir_paths):
        """Given an iterable of directory paths, yield paths to all .pth files within."""
        for dir_path in dir_paths:
            if not os.path.exists(dir_path):
                continue

            pth_filenames = (f for f in os.listdir(dir_path) if f.endswith(".pth"))
            for pth_filename in pth_filenames:
                yield os.path.join(dir_path, pth_filename)

    @staticmethod
    def _get_site_packages():
        # type: () -> Set[str]
        try:
            from site import getsitepackages

            return set(getsitepackages())
        except ImportError:
            return set()

    @classmethod
    def site_libs(cls):
        # type: () -> Set[str]
        site_libs = cls._get_site_packages()
        site_libs.update(
            [
                sysconfig.get_python_lib(plat_specific=False),
                sysconfig.get_python_lib(plat_specific=True),
            ]
        )
        # On windows getsitepackages() returns the python stdlib too.
        if sys.prefix in site_libs:
            site_libs.remove(sys.prefix)
        real_site_libs = set(os.path.realpath(path) for path in site_libs)
        return site_libs | real_site_libs

    @classmethod
    def _tainted_path(cls, path, site_libs):
        # type: (str, Iterable[str]) -> bool
        paths = frozenset([path, os.path.realpath(path)])
        return any(path.startswith(site_lib) for site_lib in site_libs for path in paths)

    @classmethod
    def minimum_sys_modules(cls, site_libs, modules=None):
        # type: (Iterable[str], Optional[Mapping[str, ModuleType]]) -> Mapping[str, ModuleType]
        """Given a set of site-packages paths, return a "clean" sys.modules.

        When importing site, modules within sys.modules have their __path__'s populated with
        additional paths as defined by *-nspkg.pth in site-packages, or alternately by distribution
        metadata such as *.dist-info/namespace_packages.txt.  This can possibly cause namespace
        packages to leak into imports despite being scrubbed from sys.path.

        NOTE: This method mutates modules' __path__ attributes in sys.modules, so this is currently an
        irreversible operation.
        """

        modules = modules or sys.modules
        new_modules = {}

        for module_name, module in modules.items():
            # Tainted modules should be dropped.
            module_file = getattr(module, "__file__", None)
            if module_file and cls._tainted_path(module_file, site_libs):
                TRACER.log("Dropping %s" % (module_name,), V=3)
                continue

            module_path = getattr(module, "__path__", None)
            # Untainted non-packages (builtin modules) need no further special handling and can stay.
            if module_path is None:
                new_modules[module_name] = module
                continue

            # Unexpected objects, e.g. PEP 420 namespace packages, should just be dropped.
            if not isinstance(module_path, list):
                TRACER.log("Dropping %s" % (module_name,), V=3)
                continue

            # Drop tainted package paths.
            for k in reversed(range(len(module_path))):
                if cls._tainted_path(module_path[k], site_libs):
                    TRACER.log("Scrubbing %s.__path__: %s" % (module_name, module_path[k]), V=3)
                    module_path.pop(k)

            # The package still contains untainted path elements, so it can stay.
            if module_path:
                new_modules[module_name] = module

        return new_modules

    _PYTHONPATH = "PYTHONPATH"
    _STASHED_PYTHONPATH = "_PEX_PYTHONPATH"

    @classmethod
    def stash_pythonpath(cls):
        # type: () -> Optional[str]
        pythonpath = os.environ.pop(cls._PYTHONPATH, None)
        if pythonpath is not None:
            os.environ[cls._STASHED_PYTHONPATH] = pythonpath
        return pythonpath

    @classmethod
    def unstash_pythonpath(cls):
        # type: () -> Optional[str]
        pythonpath = os.environ.pop(cls._STASHED_PYTHONPATH, None)
        if pythonpath is not None:
            os.environ[cls._PYTHONPATH] = pythonpath
        return pythonpath

    @classmethod
    def minimum_sys_path(cls, site_libs, inherit_path):
        # type: (Iterable[str], InheritPath.Value) -> Tuple[List[str], Mapping[str, Any]]
        scrub_paths = OrderedSet()  # type: OrderedSet[str]
        site_distributions = OrderedSet()  # type: OrderedSet[str]
        user_site_distributions = OrderedSet()  # type: OrderedSet[str]

        def all_distribution_paths(path):
            # type: (Optional[str]) -> Iterable[str]
            if path is None:
                return ()
            locations = set(dist.location for dist in find_distributions(path))
            return {path} | locations | set(os.path.realpath(path) for path in locations)

        for path_element in sys.path:
            if cls._tainted_path(path_element, site_libs):
                TRACER.log("Tainted path element: %s" % path_element)
                site_distributions.update(all_distribution_paths(path_element))
            else:
                TRACER.log("Not a tainted path element: %s" % path_element, V=2)

        user_site_distributions.update(all_distribution_paths(USER_SITE))

        if inherit_path == InheritPath.FALSE:
            scrub_paths = OrderedSet(site_distributions)
            scrub_paths.update(user_site_distributions)
            for path in user_site_distributions:
                TRACER.log("Scrubbing from user site: %s" % path)
            for path in site_distributions:
                TRACER.log("Scrubbing from site-packages: %s" % path)

        scrubbed_sys_path = list(OrderedSet(sys.path) - scrub_paths)

        pythonpath = cls.unstash_pythonpath()
        if pythonpath is not None:
            original_pythonpath = pythonpath.split(os.pathsep)
            user_pythonpath = list(OrderedSet(original_pythonpath) - set(sys.path))
            if original_pythonpath == user_pythonpath:
                TRACER.log("Unstashed PYTHONPATH of %s" % pythonpath, V=2)
            else:
                TRACER.log(
                    "Extracted user PYTHONPATH of %s from unstashed PYTHONPATH of %s"
                    % (os.pathsep.join(user_pythonpath), pythonpath),
                    V=2,
                )

            if inherit_path == InheritPath.FALSE:
                for path in user_pythonpath:
                    TRACER.log("Scrubbing user PYTHONPATH element: %s" % path)
            elif inherit_path == InheritPath.PREFER:
                TRACER.log("Prepending user PYTHONPATH: %s" % os.pathsep.join(user_pythonpath))
                scrubbed_sys_path = user_pythonpath + scrubbed_sys_path
            elif inherit_path == InheritPath.FALLBACK:
                TRACER.log("Appending user PYTHONPATH: %s" % os.pathsep.join(user_pythonpath))
                scrubbed_sys_path = scrubbed_sys_path + user_pythonpath

        scrub_from_importer_cache = filter(
            lambda key: any(key.startswith(path) for path in scrub_paths),
            sys.path_importer_cache.keys(),
        )
        scrubbed_importer_cache = dict(
            (key, value)
            for (key, value) in sys.path_importer_cache.items()
            if key not in scrub_from_importer_cache
        )

        for importer_cache_entry in scrub_from_importer_cache:
            TRACER.log("Scrubbing from path_importer_cache: %s" % importer_cache_entry, V=2)

        return scrubbed_sys_path, scrubbed_importer_cache

    @classmethod
    def minimum_sys(cls, inherit_path):
        # type: (InheritPath.Value) -> Tuple[List[str], Mapping[str, Any], Mapping[str, ModuleType]]
        """Return the minimum sys necessary to run this interpreter, a la python -S.

        :returns: (sys.path, sys.path_importer_cache, sys.modules) tuple of a
          bare python installation.
        """
        site_libs = cls.site_libs()
        for site_lib in site_libs:
            TRACER.log("Found site-library: %s" % site_lib)
        for extras_path in cls._extras_paths():
            TRACER.log("Found site extra: %s" % extras_path)
            site_libs.add(extras_path)
        site_libs = set(os.path.normpath(path) for path in site_libs)

        sys_path, sys_path_importer_cache = cls.minimum_sys_path(site_libs, inherit_path)
        sys_modules = cls.minimum_sys_modules(site_libs)

        return sys_path, sys_path_importer_cache, sys_modules

    # Thar be dragons -- when this function exits, the interpreter is potentially in a wonky state
    # since the patches here (minimum_sys_modules for example) actually mutate global state.
    def patch_sys(self):
        # type: () -> None
        """Patch sys with all site scrubbed."""
        inherit_path = self._vars.PEX_INHERIT_PATH
        if inherit_path == InheritPath.FALSE:
            inherit_path = self._pex_info.inherit_path

        def patch_dict(old_value, new_value):
            # type: (Dict[_K, _V], Mapping[_K, _V]) -> None
            old_value.clear()
            old_value.update(new_value)

        def patch_all(path, path_importer_cache, modules):
            # type: (List[str], Mapping[str, Any], Mapping[str, ModuleType]) -> None
            sys.path[:] = path
            patch_dict(sys.path_importer_cache, path_importer_cache)
            patch_dict(sys.modules, modules)

        new_sys_path, new_sys_path_importer_cache, new_sys_modules = self.minimum_sys(inherit_path)

        if self._vars.PEX_EXTRA_SYS_PATH:
            TRACER.log("Adding %s to sys.path" % self._vars.PEX_EXTRA_SYS_PATH)
            new_sys_path.extend(self._vars.PEX_EXTRA_SYS_PATH.split(":"))
        TRACER.log("New sys.path: %s" % new_sys_path)

        patch_all(new_sys_path, new_sys_path_importer_cache, new_sys_modules)

    def _wrap_coverage(self, runner, *args):
        if not self._vars.PEX_COVERAGE and self._vars.PEX_COVERAGE_FILENAME is None:
            return runner(*args)

        try:
            import coverage
        except ImportError:
            die("Could not bootstrap coverage module, aborting.")

        pex_coverage_filename = self._vars.PEX_COVERAGE_FILENAME
        if pex_coverage_filename is not None:
            cov = coverage.coverage(data_file=pex_coverage_filename)
        else:
            cov = coverage.coverage(data_suffix=True)

        TRACER.log("Starting coverage.")
        cov.start()

        try:
            return runner(*args)
        finally:
            TRACER.log("Stopping coverage")
            cov.stop()

            # TODO(wickman) Post-process coverage to elide $PEX_ROOT and make
            # the report more useful/less noisy.  #89
            if pex_coverage_filename:
                cov.save()
            else:
                cov.report(show_missing=False, ignore_errors=True, file=sys.stdout)

    def _wrap_profiling(self, runner, *args):
        if not self._vars.PEX_PROFILE and self._vars.PEX_PROFILE_FILENAME is None:
            return runner(*args)

        pex_profile_filename = self._vars.PEX_PROFILE_FILENAME
        pex_profile_sort = self._vars.PEX_PROFILE_SORT
        try:
            import cProfile as profile
        except ImportError:
            import profile

        profiler = profile.Profile()

        try:
            return profiler.runcall(runner, *args)
        finally:
            if pex_profile_filename is not None:
                profiler.dump_stats(pex_profile_filename)
            else:
                profiler.print_stats(sort=pex_profile_sort)

    def path(self):
        # type: () -> str
        """Return the path this PEX was built at."""
        return self._pex

    def execute(self):
        # type: () -> None
        """Execute the PEX.

        This function makes assumptions that it is the last function called by the interpreter.
        """
        teardown_verbosity = self._vars.PEX_TEARDOWN_VERBOSE

        # N.B.: This is set in `__main__.py` of the executed PEX by `PEXBuilder` when we've been
        # executed from within a PEX zip file in `--unzip` mode.  We replace `sys.argv[0]` to avoid
        # confusion and allow the user code we hand off to to provide useful messages and fully
        # valid re-execs that always re-directed through the PEX file.
        sys.argv[0] = os.environ.pop("__PEX_EXE__", sys.argv[0])

        try:
            if self._vars.PEX_TOOLS:
                try:
                    from pex.tools import main as tools
                except ImportError as e:
                    die(
                        "The PEX_TOOLS environment variable was set, but this PEX was not built "
                        "with tools (Re-build the PEX file with `pex --include-tools ...`):"
                        " {}".format(e)
                    )

                exit_code = tools.main(pex=self, pex_prog_path=sys.argv[0])
            else:
                self.activate()
                exit_code = self._wrap_coverage(self._wrap_profiling, self._execute)
            if exit_code:
                sys.exit(exit_code)
        except Exception:
            # Allow the current sys.excepthook to handle this app exception before we tear things
            # down in finally, then reraise so that the exit status is reflected correctly.
            sys.excepthook(*sys.exc_info())
            raise
        except SystemExit as se:
            # Print a SystemExit error message, avoiding a traceback in python3.
            # This must happen here, as sys.stderr is about to be torn down
            if not isinstance(se.code, int) and se.code is not None:  # type: ignore[unreachable]
                print(se.code, file=sys.stderr)  # type: ignore[unreachable]
            raise
        finally:
            # squash all exceptions on interpreter teardown -- the primary type here are
            # atexit handlers failing to run because of things such as:
            #   http://stackoverflow.com/questions/2572172/referencing-other-modules-in-atexit
            if not teardown_verbosity:
                sys.stderr.flush()
                sys.stderr = open(os.devnull, "w")
                if PY3:
                    # Python 3 warns about unclosed resources. In this case we intentionally do not
                    # close `/dev/null` since we want all stderr to flow there until the latest
                    # stages of Python interpreter shutdown when the Python runtime will `del` the
                    # open file and thus finally close the underlying file descriptor. As such,
                    # suppress the warning.
                    warnings.filterwarnings(
                        action="ignore",
                        message=r"unclosed file {}".format(re.escape(str(sys.stderr))),
                        category=ResourceWarning,
                    )
                sys.excepthook = lambda *a, **kw: None

    def _execute(self):
        force_interpreter = self._vars.PEX_INTERPRETER

        self._clean_environment(strip_pex_env=self._pex_info.strip_pex_env)

        if force_interpreter:
            TRACER.log("PEX_INTERPRETER specified, dropping into interpreter")
            return self.execute_interpreter()

        if self._pex_info_overrides.script and self._pex_info_overrides.entry_point:
            die("Cannot specify both script and entry_point for a PEX!")

        if self._pex_info.script and self._pex_info.entry_point:
            die("Cannot specify both script and entry_point for a PEX!")

        if self._pex_info_overrides.script:
            return self.execute_script(self._pex_info_overrides.script)
        elif self._pex_info_overrides.entry_point:
            return self.execute_entry(self._pex_info_overrides.entry_point)
        elif self._pex_info.script:
            return self.execute_script(self._pex_info.script)
        elif self._pex_info.entry_point:
            return self.execute_entry(self._pex_info.entry_point)
        else:
            TRACER.log("No entry point specified, dropping into interpreter")
            return self.execute_interpreter()

    @classmethod
    def demote_bootstrap(cls):
        TRACER.log("Bootstrap complete, performing final sys.path modifications...")

        should_log = {level: TRACER.should_log(V=level) for level in range(1, 10)}

        def log(msg, V=1):
            if should_log.get(V, False):
                print("pex: {}".format(msg), file=sys.stderr)

        # Remove the third party resources pex uses and demote pex bootstrap code to the end of
        # sys.path for the duration of the run to allow conflicting versions supplied by user
        # dependencies to win during the course of the execution of user code.
        third_party.uninstall()

        bootstrap = Bootstrap.locate()
        log("Demoting code from %s" % bootstrap, V=2)
        for module in bootstrap.demote():
            log("un-imported {}".format(module), V=9)

        import pex

        log("Re-imported pex from {}".format(pex.__path__), V=3)

        log("PYTHONPATH contains:")
        for element in sys.path:
            log("  %c %s" % (" " if os.path.exists(element) else "*", element))
        log("  * - paths that do not exist or will be imported via zipimport")

    def execute_interpreter(self):
        args = sys.argv[1:]
        if args:
            # NB: We take care here to setup sys.argv to match how CPython does it for each case.
            arg = args[0]
            if arg == "-c":
                content = args[1]
                sys.argv = ["-c"] + args[2:]
                self.execute_content("-c <cmd>", content, argv0="-c")
            elif arg == "-m":
                module = args[1]
                sys.argv = args[1:]
                self.execute_module(module)
            else:
                try:
                    if arg == "-":
                        content = sys.stdin.read()
                    else:
                        with open(arg) as fp:
                            content = fp.read()
                except IOError as e:
                    die("Could not open %s in the environment [%s]: %s" % (arg, sys.argv[0], e))
                sys.argv = args
                self.execute_content(arg, content)
        else:
            self.demote_bootstrap()

            import code

            code.interact()

    def execute_script(self, script_name):
        dists = list(self.activate())

        dist, entry_point = get_entry_point_from_console_script(script_name, dists)
        if entry_point:
            TRACER.log("Found console_script %r in %r" % (entry_point, dist))
            sys.exit(self.execute_entry(entry_point))

        dist_script = get_script_from_distributions(script_name, dists)
        if not dist_script:
            raise self.NotFound("Could not find script %r in pex!" % script_name)
        TRACER.log("Found script %r in %r" % (script_name, dist))
        return self.execute_content(
            dist_script.path, dist_script.read_contents(), argv0=script_name
        )

    @classmethod
    def execute_content(cls, name, content, argv0=None):
        argv0 = argv0 or name
        try:
            ast = compile(content, name, "exec", flags=0, dont_inherit=1)
        except SyntaxError:
            die("Unable to parse %s. PEX script support only supports Python scripts." % name)

        cls.demote_bootstrap()

        from pex.compatibility import exec_function

        sys.argv[0] = argv0
        globals_map = globals().copy()
        globals_map["__name__"] = "__main__"
        globals_map["__file__"] = name
        exec_function(ast, globals_map)

    @classmethod
    def execute_entry(cls, entry_point):
        runner = cls.execute_pkg_resources if ":" in entry_point else cls.execute_module
        return runner(entry_point)

    @classmethod
    def execute_module(cls, module_name):
        cls.demote_bootstrap()

        import runpy

        runpy.run_module(module_name, run_name="__main__")

    @classmethod
    def execute_pkg_resources(cls, spec):
        entry = EntryPoint.parse("run = {}".format(spec))
        cls.demote_bootstrap()

        runner = entry.resolve()
        return runner()

    def cmdline(self, args=()):
        """The commandline to run this environment.

        :keyword args: Additional arguments to be passed to the application being invoked by the
          environment.
        """
        cmds = [self._interpreter.binary]
        cmds.append(self._pex)
        cmds.extend(args)
        return cmds

    def run(self, args=(), with_chroot=False, blocking=True, setsid=False, env=None, **kwargs):
        """Run the PythonEnvironment in an interpreter in a subprocess.

        :keyword args: Additional arguments to be passed to the application being invoked by the
          environment.
        :keyword with_chroot: Run with cwd set to the environment's working directory.
        :keyword blocking: If true, return the return code of the subprocess.
          If false, return the Popen object of the invoked subprocess.
        :keyword setsid: If true, run the PEX in a separate operating system session.
        :keyword env: An optional environment dict to use as the PEX subprocess environment. If none is
                      passed, the ambient environment is inherited.
        Remaining keyword arguments are passed directly to subprocess.Popen.
        """
        if env is not None:
            # If explicit env vars are passed, we don't want clean any of these.
            env = env.copy()
        else:
            env = os.environ.copy()
            self._clean_environment(env=env)

        cmdline = self.cmdline(args)
        TRACER.log("PEX.run invoking %s" % " ".join(cmdline))
        process = Executor.open_process(
            cmdline,
            cwd=self._pex if with_chroot else os.getcwd(),
            preexec_fn=os.setsid if setsid else None,
            stdin=kwargs.pop("stdin", None),
            stdout=kwargs.pop("stdout", None),
            stderr=kwargs.pop("stderr", None),
            env=env,
            **kwargs
        )
        return process.wait() if blocking else process

    def _do_entry_point_verification(self):

        entry_point = self._pex_info.entry_point
        ep_split = entry_point.split(":")

        # a.b.c:m ->
        # ep_module = 'a.b.c'
        # ep_method = 'm'

        # Only module is specified
        if len(ep_split) == 1:
            ep_module = ep_split[0]
            import_statement = "import {}".format(ep_module)
        elif len(ep_split) == 2:
            ep_module = ep_split[0]
            ep_method = ep_split[1]
            import_statement = "from {} import {}".format(ep_module, ep_method)
        else:
            raise self.InvalidEntryPoint("Failed to parse: `{}`".format(entry_point))

        with named_temporary_file() as fp:
            fp.write(import_statement.encode("utf-8"))
            fp.close()
            retcode = self.run([fp.name], env={"PEX_INTERPRETER": "1"})
            if retcode != 0:
                raise self.InvalidEntryPoint(
                    "Invalid entry point: `{}`\n"
                    "Entry point verification failed: `{}`".format(entry_point, import_statement)
                )
