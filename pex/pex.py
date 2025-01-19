# Copyright 2014 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import ast
import itertools
import os
import sys
from site import USER_SITE
from types import ModuleType

from pex import bootstrap, repl
from pex.bootstrap import Bootstrap
from pex.common import die
from pex.dist_metadata import CallableEntryPoint, Distribution, ModuleEntryPoint, parse_entry_point
from pex.environment import PEXEnvironment
from pex.executor import Executor
from pex.finders import get_entry_point_from_console_script, get_script_from_distributions
from pex.fingerprinted_distribution import FingerprintedDistribution
from pex.globals import Globals
from pex.inherit_path import InheritPath
from pex.interpreter import PythonIdentity, PythonInterpreter
from pex.layout import Layout
from pex.orderedset import OrderedSet
from pex.pex_info import PexInfo
from pex.targets import LocalInterpreter
from pex.tracer import TRACER
from pex.typing import TYPE_CHECKING
from pex.util import named_temporary_file
from pex.variables import ENV, Variables

if TYPE_CHECKING:
    from typing import (
        Any,
        Dict,
        Iterable,
        Iterator,
        List,
        Mapping,
        NoReturn,
        Optional,
        Sequence,
        Tuple,
        TypeVar,
        Union,
    )

    _K = TypeVar("_K")
    _V = TypeVar("_V")


class IsolatedSysPath(object):
    @staticmethod
    def _expand_paths(*paths):
        # type: (*str) -> OrderedSet[str]
        def iter_synonyms(path):
            yield path
            yield os.path.abspath(path)
            yield os.path.realpath(path)

        return OrderedSet(itertools.chain.from_iterable(iter_synonyms(path) for path in paths))

    @classmethod
    def for_pex(
        cls,
        interpreter,  # type: Union[PythonInterpreter, PythonIdentity]
        pex,  # type: str
        pex_pex=None,  # type: Optional[str]
    ):
        # type: (...) -> IsolatedSysPath
        ident = interpreter.identity if isinstance(interpreter, PythonInterpreter) else interpreter
        sys_path = OrderedSet(ident.sys_path)
        sys_path.add(pex)
        sys_path.add(Bootstrap.locate().path)
        if pex_pex:
            sys_path.add(pex_pex)

        site_packages = OrderedSet()  # type: OrderedSet[str]
        for site_lib in ident.site_packages:
            TRACER.log("Discarding site packages path: {site_lib}".format(site_lib=site_lib))
            site_packages.add(site_lib.path)

        extras_paths = OrderedSet()  # type: OrderedSet[str]
        for extras_path in ident.extras_paths:
            TRACER.log("Discarding site extras path: {extras_path}".format(extras_path=extras_path))
            extras_paths.add(extras_path)

        return cls(
            sys_path=sys_path,
            site_packages=site_packages,
            extras_paths=extras_paths,
            is_venv=ident.is_venv,
        )

    def __init__(
        self,
        sys_path,  # type: Iterable[str]
        site_packages,  # type: Iterable[str]
        extras_paths=(),  # type: Iterable[str]
        is_venv=False,  # type: bool
    ):
        # type: (...) -> None
        self._sys_path_entries = tuple(self._expand_paths(*sys_path))
        self._site_packages_entries = tuple(self._expand_paths(*site_packages))
        self._extras_paths_entries = tuple(self._expand_paths(*extras_paths))
        self._is_venv = is_venv

    @property
    def is_venv(self):
        # type: () -> bool
        return self._is_venv

    def __contains__(self, entry):
        # type: (str) -> bool
        for path in self._expand_paths(entry):
            # N.B.: Since site packages is contained in sys.path, process rejections 1st to ensure
            # they never sneak by.
            if path.startswith(self._site_packages_entries):
                return False
            if path.startswith(self._extras_paths_entries):
                return False
            if path.startswith(self._sys_path_entries):
                return True

        # A sys.path entry injected by calling code. This can happen when a PEX is used as a
        # sys.path entry via the __pex__ importer mechanism or via the old pex_bootstrapper
        # bootstrap_pex_env API used by at least lambdex and pyuwsgi_pex. Pointedly, the AWS lambda
        # does this, adding /var/runtime to sys.path before executing user code.
        return False


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
        self._envs = None  # type: Optional[Sequence[PEXEnvironment]]
        self._activated_dists = None  # type: Optional[Sequence[Distribution]]
        self._layout = None  # type: Optional[Layout.Value]
        if verify_entry_point:
            self._do_entry_point_verification()

    @property
    def layout(self):
        # type: () -> Layout.Value
        if self._layout is None:
            self._layout = Layout.identify_original(self._pex)
        return self._layout

    def pex_info(self, include_env_overrides=True):
        # type: (bool) -> PexInfo
        pex_info = self._pex_info.copy()
        if include_env_overrides:
            pex_info.update(self._pex_info_overrides)
            pex_info.merge_pex_path(self._vars.PEX_PATH)
        return pex_info

    @property
    def interpreter(self):
        # type: () -> PythonInterpreter
        return self._interpreter

    @property
    def _loaded_envs(self):
        # type: () -> Sequence[PEXEnvironment]
        if self._envs is None:
            # set up the local .pex environment
            pex_info = self.pex_info()
            target = LocalInterpreter.create(self._interpreter)
            envs = [PEXEnvironment.mount(self._pex, pex_info, target=target)]
            # N.B. by this point, `pex_info.pex_path` will contain a single pex path
            # merged from pex_path in `PEX-INFO` and `PEX_PATH` set in the environment.
            # `PEX_PATH` entries written into `PEX-INFO` take precedence over those set
            # in the environment.
            for pex_path in pex_info.pex_path:
                # Set up other environments as specified in pex_path.
                pex_info = PexInfo.from_pex(pex_path)
                pex_info.update(self._pex_info_overrides)
                envs.append(PEXEnvironment.mount(pex_path, pex_info, target=target))
            self._envs = envs
        return self._envs

    def resolve(self):
        # type: () -> Iterator[Distribution]
        """Resolves all distributions loadable from this PEX by the current interpreter."""
        seen = set()
        for env in self._loaded_envs:
            for dist in env.resolve():
                # N.B.: Since there can be more than one PEX env on the PEX_PATH we take care to
                # de-dup distributions they have in common.
                if dist in seen:
                    continue
                seen.add(dist)
                yield dist

    def iter_distributions(self, result_type_wheel_file=False):
        # type: (bool) -> Iterator[FingerprintedDistribution]
        """Iterates all distributions loadable from this PEX."""
        seen = set()
        for env in self._loaded_envs:
            for dist in env.iter_distributions(result_type_wheel_file=result_type_wheel_file):
                # N.B.: Since there can be more than one PEX env on the PEX_PATH we take care to
                # de-dup distributions they have in common.
                if dist in seen:
                    continue
                seen.add(dist)
                yield dist

    def _activate(self):
        # type: () -> Sequence[Distribution]

        activated_dists = []  # type: List[Distribution]
        for env in self._loaded_envs:
            activated_dists.extend(env.activate())

        # Ensure that pkg_resources is not imported until at least every pex environment
        # (i.e. PEX_PATH) has been merged into the environment
        PEXEnvironment._declare_namespace_packages(activated_dists)
        return activated_dists

    def activate(self):
        # type: () -> Sequence[Distribution]
        if self._activated_dists is None:
            # 1. Scrub the sys.path to present a minimal Python environment.
            self.patch_sys()
            # 2. Activate all code and distributions in the PEX.
            self._activated_dists = self._activate()
        return self._activated_dists

    @classmethod
    def minimum_sys_modules(
        cls,
        isolated_sys_path,  # type: IsolatedSysPath
        modules=None,  # type: Optional[Mapping[str, ModuleType]]
    ):
        # type: (...) -> Mapping[str, ModuleType]
        """Given a set of site-packages paths, return a "clean" sys.modules.

        When importing site, modules within `sys.modules` have their `__path__`s populated with
        additional paths as defined by `*-nspkg.pth` in `site-packages`, or alternately by
        distribution metadata such as `*.dist-info/namespace_packages.txt`. This can possibly cause
        namespace packages to leak into imports despite being scrubbed from `sys.path`.

        NOTE: This method mutates modules' `__path__` attributes in `sys.modules`, so this is
        currently an irreversible operation.
        """

        is_venv = isolated_sys_path.is_venv
        modules = modules or sys.modules
        new_modules = {}

        for module_name, module in modules.items():
            # Tainted modules should be dropped.
            module_file = getattr(module, "__file__", None)
            if (
                # The `_virtualenv` module is a known special case provided by the virtualenv
                # project. It should not be un-imported or else the virtualenv importer it installs
                # for performing needed patches to the `distutils` stdlib breaks.
                #
                # See:
                # + https://github.com/pex-tool/pex/issues/992
                # + https://github.com/pypa/virtualenv/pull/1688
                (not is_venv or module_name != "_virtualenv")
                and module_file
                and module_file not in isolated_sys_path
            ):
                TRACER.log("Dropping %s" % (module_name,), V=3)
                continue

            module_path = getattr(module, "__path__", None)
            # Untainted non-packages (builtin modules) need no further special handling and can
            # stay.
            if module_path is None:
                new_modules[module_name] = module
                continue

            # Unexpected objects, e.g. PEP 420 namespace packages, should just be dropped.
            if not isinstance(module_path, list):
                TRACER.log("Dropping %s" % (module_name,), V=3)
                continue

            # Drop tainted package paths.
            for k in reversed(range(len(module_path))):
                if module_path[k] not in isolated_sys_path:
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
    def minimum_sys_path(
        cls,
        isolated_sys_path,  # type: IsolatedSysPath
        inherit_path,  # type: InheritPath.Value
    ):
        # type: (...) -> Tuple[List[str], Mapping[str, Any]]
        scrub_paths = OrderedSet()  # type: OrderedSet[str]
        site_paths = OrderedSet()  # type: OrderedSet[str]
        user_site_paths = OrderedSet()  # type: OrderedSet[str]

        def all_paths(path):
            # type: (Optional[str]) -> Iterable[str]
            if path is None:
                return ()
            return path, os.path.realpath(path)

        for path_element in sys.path:
            if path_element not in isolated_sys_path:
                TRACER.log("Tainted path element: %s" % path_element)
                site_paths.update(all_paths(path_element))
            else:
                TRACER.log("Not a tainted path element: %s" % path_element, V=2)

        user_site_paths.update(all_paths(USER_SITE))

        if inherit_path == InheritPath.FALSE:
            scrub_paths = OrderedSet(site_paths)
            scrub_paths.update(user_site_paths)
            for path in user_site_paths:
                TRACER.log("Scrubbing from user site: %s" % path)
            for path in site_paths:
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

    def minimum_sys(self, inherit_path):
        # type: (InheritPath.Value) -> Tuple[List[str], Mapping[str, Any], Mapping[str, ModuleType]]
        """Return the minimum sys necessary to run this interpreter, a la python -S.

        :returns: (sys.path, sys.path_importer_cache, sys.modules) tuple of a
          bare python installation.
        """
        isolated_sys_path = IsolatedSysPath.for_pex(
            interpreter=self._interpreter, pex=self._pex, pex_pex=self._vars.PEX
        )
        sys_path, sys_path_importer_cache = self.minimum_sys_path(isolated_sys_path, inherit_path)
        sys_modules = self.minimum_sys_modules(isolated_sys_path)

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

            # N.B.: These hooks may contain custom code set via site.py or `.pth` files that we've
            # just scrubbed. Reset them to factory defaults to avoid scrubbed code.
            sys.displayhook = sys.__displayhook__
            sys.excepthook = sys.__excepthook__  # type: ignore[assignment] # Builtin typeshed bug.

        new_sys_path, new_sys_path_importer_cache, new_sys_modules = self.minimum_sys(inherit_path)

        if self._vars.PEX_EXTRA_SYS_PATH:
            TRACER.log(
                "Adding {} to sys.path".format(os.pathsep.join(self._vars.PEX_EXTRA_SYS_PATH))
            )
            extra_sys_path = self._vars.PEX_EXTRA_SYS_PATH
            new_sys_path.extend(extra_sys_path)

            # Let Python subprocesses see the same sys.path additions we see. If those Python
            # subprocesses are PEX subprocesses, they'll do their own (re-)scrubbing as needed.
            if inherit_path is InheritPath.FALSE:
                pythonpath_entries = extra_sys_path
            else:
                raw_pythonpath = os.environ.get(self._PYTHONPATH)
                pythonpath = tuple(raw_pythonpath.split(os.pathsep)) if raw_pythonpath else ()
                pythonpath_entries = pythonpath + extra_sys_path
            os.environ[self._PYTHONPATH] = os.pathsep.join(pythonpath_entries)

        TRACER.log("New sys.path: {}".format(new_sys_path))

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
        # type: () -> Any
        """Execute the PEX.

        This function makes assumptions that it is the last function called by the interpreter.
        """
        pex_file = self._vars.PEX
        if self._vars.PEX_TOOLS:
            if not self._pex_info.includes_tools:
                die(
                    "The PEX_TOOLS environment variable was set, but this PEX was not built "
                    "with tools (Re-build the PEX file with `pex --include-tools ...`)"
                )

            from pex.tools import main as tools

            sys.exit(tools.main(pex=PEX(pex_file or sys.argv[0])))

        self.activate()

        if pex_file:
            try:
                from setproctitle import setproctitle  # type: ignore[import]

                setproctitle(
                    "{python} {pex_file} {args}".format(
                        python=sys.executable,
                        pex_file=pex_file,
                        args=" ".join(sys.argv[1:]),
                    )
                )
            except ImportError:
                TRACER.log(
                    "Not setting process title since setproctitle is not available in "
                    "{pex_file}".format(pex_file=pex_file),
                    V=3,
                )

        result = self._wrap_coverage(self._wrap_profiling, self._execute)
        if "PYTHONINSPECT" not in os.environ:
            sys.exit(0 if isinstance(result, Globals) else result)
        else:
            return result

    def _execute(self):
        # type: () -> Any
        force_interpreter = self._vars.PEX_INTERPRETER

        self._clean_environment(strip_pex_env=self._pex_info.strip_pex_env)

        for name, value in self._pex_info.inject_env.items():
            os.environ.setdefault(name, value)

        if force_interpreter:
            TRACER.log("PEX_INTERPRETER specified, dropping into interpreter")
            return self.execute_interpreter()

        if not any(
            (
                self._pex_info_overrides.script,
                self._pex_info_overrides.entry_point,
                self._pex_info.script,
                self._pex_info.entry_point,
            )
        ):
            TRACER.log("No entry point specified, dropping into interpreter")
            return self.execute_interpreter()

        if self._pex_info_overrides.script and self._pex_info_overrides.entry_point:
            return "Cannot specify both script and entry_point for a PEX!"

        if self._pex_info.script and self._pex_info.entry_point:
            return "Cannot specify both script and entry_point for a PEX!"

        if self._pex_info_overrides.script:
            return self.execute_script(self._pex_info_overrides.script)
        if self._pex_info_overrides.entry_point:
            return self.execute_entry(parse_entry_point(self._pex_info_overrides.entry_point))

        sys.argv[1:1] = list(self._pex_info.inject_args)

        if self._pex_info.script:
            return self.execute_script(self._pex_info.script)
        else:
            return self.execute_entry(parse_entry_point(self._pex_info.entry_point))

    def execute_interpreter(self):
        # type: () -> Any

        # A Python interpreter always inserts the CWD at the head of the sys.path.
        # See https://docs.python.org/3/library/sys.html#sys.path
        sys.path.insert(0, "")

        args = sys.argv[1:]
        python_options = []
        for index, arg in enumerate(args):
            # Check if the arg is an expected startup arg.
            if arg.startswith("-") and arg not in ("-", "-c", "-m"):
                python_options.append(arg)
            else:
                args = args[index:]
                break
        else:
            # All the args were python options
            args = []

        # The pex was called with Python interpreter options
        if python_options:
            return self.execute_with_options(python_options, args)

        if args:
            # NB: We take care here to setup sys.argv to match how CPython does it for each case.
            arg = args[0]
            if arg == "-c":
                content = args[1]
                sys.argv = ["-c"] + args[2:]
                return self.execute_content("-c <cmd>", content, argv0="-c")
            elif arg == "-m":
                module = args[1]
                sys.argv = args[1:]
                return self.execute_module(module)
            else:
                try:
                    if arg == "-":
                        content = sys.stdin.read()
                    else:
                        file_path = arg if os.path.isfile(arg) else os.path.join(arg, "__main__.py")
                        with open(file_path) as fp:
                            content = fp.read()
                except IOError as e:
                    return "Could not open {} in the environment [{}]: {}".format(
                        arg, sys.argv[0], e
                    )
                sys.argv = args
                return self.execute_content(arg, content)
        else:
            pex_repl = repl.create_pex_repl(
                pex_info=self.pex_info(),
                requirements=(
                    tuple(
                        OrderedSet(
                            itertools.chain.from_iterable(
                                env.pex_info.requirements for env in self._envs
                            )
                        )
                    )
                    if self._envs
                    else ()
                ),
                activated_dists=self._activated_dists or (),
            )

            bootstrap.demote()

            return Globals(pex_repl())

    @staticmethod
    def execute_with_options(
        python_options,  # type: List[str]
        args,  # List[str]
    ):
        # type: (...) -> Union[NoReturn, Any]
        """
        Restart the process passing the given options to the python interpreter
        """
        # Find the installed (unzipped) PEX entry point.
        main = sys.modules.get("__main__")
        if not main or not main.__file__:
            # N.B.: This should never happen.
            return "Unable to resolve PEX __main__ module file: {}".format(main)

        python = sys.executable
        cmdline = [python] + python_options + [main.__file__] + args
        TRACER.log(
            "Re-executing with Python interpreter options: cmdline={cmdline!r}".format(
                cmdline=" ".join(cmdline)
            )
        )
        if any(
            arg.startswith("-") and not arg.startswith("--") and "i" in arg
            for arg in python_options
        ):
            os.environ["PYTHONINSPECT"] = "1"
        os.execv(python, cmdline)

    def execute_script(self, script_name):
        # type: (str) -> Any
        dists = list(self.activate())

        dist_entry_point = get_entry_point_from_console_script(script_name, dists)
        if dist_entry_point:
            TRACER.log(
                "Found {console_script}.".format(
                    console_script=dist_entry_point.render_description()
                )
            )
            return self.execute_entry(dist_entry_point.entry_point)

        dist_script = get_script_from_distributions(script_name, dists)
        if not dist_script:
            return "Could not find script {!r} in pex!".format(script_name)

        TRACER.log("Found script {!r} in {!r}.".format(script_name, dist_script.dist))
        ast = dist_script.python_script()
        if ast:
            return self.execute_ast(dist_script.path, ast, argv0=script_name)
        else:
            return self.execute_external(dist_script.path)

    @staticmethod
    def execute_external(binary):
        # type: (str) -> Any
        args = [binary] + sys.argv[1:]
        try:
            return Executor.open_process(args).wait()
        except Executor.ExecutionError as e:
            return "Could not invoke script {}: {}".format(binary, e)

    @classmethod
    def execute_content(
        cls,
        name,  # type: str
        content,  # type: str
        argv0=None,  # type: Optional[str]
    ):
        # type: (...) -> Any
        try:
            program = compile(content, name, "exec", flags=0, dont_inherit=1)
        except SyntaxError as e:
            return "Unable to parse {}: {}".format(name, e)
        return cls.execute_ast(name, program, argv0=argv0)

    @classmethod
    def execute_ast(
        cls,
        name,  # type: str
        program,  # type: ast.AST
        argv0=None,  # type: Optional[str]
    ):
        # type: (...) -> Any
        bootstrap.demote()

        from pex.compatibility import exec_function

        sys.argv[0] = argv0 or name
        globals_map = globals().copy()
        globals_map["__name__"] = "__main__"
        globals_map["__file__"] = name
        return Globals(exec_function(program, globals_map))

    def execute_entry(self, entry_point):
        # type: (Union[ModuleEntryPoint, CallableEntryPoint]) -> Any
        if isinstance(entry_point, CallableEntryPoint):
            return self.execute_entry_point(entry_point)

        return self.execute_module(entry_point.module)

    def execute_module(self, module_name):
        # type: (str) -> Any
        bootstrap.demote()

        import runpy

        return Globals(runpy.run_module(module_name, run_name="__main__", alter_sys=True))

    @classmethod
    def execute_entry_point(cls, entry_point):
        # type: (CallableEntryPoint) -> Any
        bootstrap.demote()

        runner = entry_point.resolve()
        return runner()

    def cmdline(self, args=()):
        """The commandline to run this environment.

        :keyword args: Additional arguments to be passed to the application being invoked by the
          environment.
        """
        cmd, _ = self._interpreter.create_isolated_cmd([self._pex] + list(args))
        return cmd

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
            # If explicit env vars are passed, we don't want to clean any of these.
            env = env.copy()
        else:
            env = os.environ.copy()
            self._clean_environment(env=env)

        TRACER.log("PEX.run invoking {}".format(" ".join(self.cmdline(args))))
        _, process = self._interpreter.open_process(
            [self._pex] + list(args),
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
