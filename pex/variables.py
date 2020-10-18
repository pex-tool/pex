# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Due to the PEX_ properties, disable checkstyle.
# checkstyle: noqa

from __future__ import absolute_import

import os
import sys
from contextlib import contextmanager

from pex import pex_warnings
from pex.common import can_write_dir, die, safe_mkdtemp
from pex.inherit_path import InheritPath
from pex.typing import TYPE_CHECKING, Generic, overload

if TYPE_CHECKING:
    from typing import Callable, Dict, Iterator, Optional, Tuple, TypeVar, Type, Union

    _O = TypeVar("_O")
    _P = TypeVar("_P")


class NoValueError(Exception):
    """Indicates a property has no value set.

    When raised from a method decorated with `@defaulted_property(default)` indicates the default
    value should be used.
    """


class DefaultedProperty(Generic["_O", "_P"]):
    """Represents a property with a default value.

    To determine the value of the property without the default value applied, access it through the
    class and call the `strip_default` method, passing the instance in question.
    """

    def __init__(
        self,
        func,  # type: Callable[[_O], _P]
        default,  # type: _P
    ):
        # type: (...) -> None
        self._func = func  # type: Callable[[_O], _P]
        self._default = default  # type: _P
        self._validator = None  # type: Optional[Callable[[_O, _P], _P]]

    @overload
    def __get__(
        self,
        instance,  # type: None
        owner_class=None,  # type: Optional[Type[_O]]
    ):
        # type: (...) -> DefaultedProperty[_O, _P]
        pass

    @overload
    def __get__(
        self,
        instance,  # type: _O
        owner_class=None,  # type: Optional[Type[_O]]
    ):
        # type: (...) -> _P
        pass

    def __get__(
        self,
        instance,  # type: Optional[_O]
        owner_class=None,  # type: Optional[Type[_O]]
    ):
        # type: (...) -> Union[DefaultedProperty[_O, _P], _P]
        if instance is None:  # The descriptor was accessed from the class.
            return self
        try:
            return self._validate(instance, self._func(instance))
        except NoValueError:
            return self._validate(instance, self._default)

    def strip_default(self, instance):
        # type: (_O) -> Optional[_P]
        """Return the value of this property without the default value applied.

        If the property is not set `None` will be returned and if there is an associated @validator
        that validator will be skipped.

        :param instance: The instance to check for the non-defaulted property value.
        :return: The property value or `None` if not set.
        """
        try:
            return self._validate(instance, self._func(instance))
        except NoValueError:
            return None

    def validator(self, func):
        # type: (Callable[[_O, _P], _P]) -> Callable[[_O, _P], _P]
        """Associate a validation function with this defaulted property.

        The function will be used to validate this property's final computed value.

        :param func: The validation function to associate with this property descriptor.
        """
        self._validator = func
        return func

    def _validate(self, instance, value):
        # type: (_O, _P) -> _P
        if self._validator is None:
            return value
        return self._validator(instance, value)


def defaulted_property(
    default,  # type: _P
):
    # type: (...) -> Callable[[Callable[[_O], _P]], DefaultedProperty[_O, _P]]
    """Creates a `@property` with a `default` value.

    Accessors decorated with this function should raise `NoValueError` to indicate the `default`
    value should be used.
    """

    def wrapped(func):
        # type: (Callable[[_O], _P]) -> DefaultedProperty[_O, _P]
        return DefaultedProperty(func, default)

    return wrapped


class Variables(object):
    """Environment variables supported by the PEX runtime."""

    @classmethod
    def process_pydoc(cls, pydoc):
        # type: (Optional[str]) -> Tuple[str, str]
        if pydoc is None:
            return "Unknown", "Unknown"
        pydoc_lines = pydoc.splitlines()
        variable_type = pydoc_lines[0]
        variable_text = " ".join(filter(None, (line.strip() for line in pydoc_lines[2:])))
        return variable_type, variable_text

    @classmethod
    def iter_help(cls):
        # type: () -> Iterator[Tuple[str, str, str]]
        for variable_name, value in sorted(cls.__dict__.items()):
            if not variable_name.startswith("PEX_"):
                continue
            variable_type, variable_text = cls.process_pydoc(getattr(value, "__doc__"))
            yield variable_name, variable_type, variable_text

    @classmethod
    def from_rc(cls, rc=None):
        # type: (Optional[str]) -> Dict[str, str]
        """Read pex runtime configuration variables from a pexrc file.

        :param rc: an absolute path to a pexrc file.
        :return: A dict of key value pairs found in processed pexrc files.
        """
        ret_vars = {}  # type: Dict[str, str]
        rc_locations = [
            "/etc/pexrc",
            "~/.pexrc",
            os.path.join(os.path.dirname(sys.argv[0]), ".pexrc"),
        ]
        if rc:
            rc_locations.append(rc)
        for filename in rc_locations:
            try:
                with open(os.path.expanduser(filename)) as fh:
                    rc_items = map(cls._get_kv, fh)
                    ret_vars.update(dict(filter(None, rc_items)))
            except IOError:
                continue
        return ret_vars

    @classmethod
    def _get_kv(cls, variable):
        kv = variable.strip().split("=")
        if len(list(filter(None, kv))) == 2:
            return kv

    def __init__(self, environ=None, rc=None):
        # type: (Optional[Dict[str, str]], Optional[str]) -> None
        self._environ = (
            environ.copy() if environ is not None else os.environ.copy()
        )  # type: Dict[str, str]
        if not self.PEX_IGNORE_RCFILES:
            rc_values = self.from_rc(rc).copy()
            rc_values.update(self._environ)
            self._environ = rc_values

    def copy(self):
        # type: () -> Dict[str, str]
        return self._environ.copy()

    def _maybe_get_string(self, variable):
        # type: (str) -> Optional[str]
        return self._environ.get(variable)

    def _get_string(self, variable):
        # type: (str) -> str
        value = self._maybe_get_string(variable)
        if value is None:
            raise NoValueError(variable)
        return value

    def _maybe_get_bool(self, variable):
        # type: (str) -> Optional[bool]
        value = self._maybe_get_string(variable)
        if value is None:
            return None
        if value.lower() in ("0", "false"):
            return False
        if value.lower() in ("1", "true"):
            return True
        die("Invalid value for %s, must be 0/1/false/true, got %r" % (variable, value))

    def _get_bool(self, variable):
        # type: (str) -> bool
        value = self._maybe_get_bool(variable)
        if value is None:
            raise NoValueError(variable)
        return value

    def _maybe_get_path(self, variable):
        # type: (str) -> Optional[str]
        value = self._maybe_get_string(variable)
        if value is None:
            return None
        return os.path.realpath(os.path.expanduser(value))

    def _get_path(self, variable):
        # type: (str) -> str
        value = self._maybe_get_path(variable)
        if value is None:
            raise NoValueError(variable)
        return value

    def _get_int(self, variable):
        # type: (str) -> int
        value = self._get_string(variable)
        try:
            return int(value)
        except ValueError:
            die(
                "Invalid value for %s, must be an integer, got %r"
                % (variable, self._environ[variable])
            )

    def strip(self):
        # type: () -> Variables
        stripped_environ = {
            k: v for k, v in self.copy().items() if not k.startswith(("PEX_", "__PEX_"))
        }
        return Variables(environ=stripped_environ)

    @contextmanager
    def patch(self, **kw):
        # type: (**str) -> Iterator[Dict[str, str]]
        """Update the environment for the duration of a context."""
        old_environ = self._environ
        self._environ = self._environ.copy()
        self._environ.update(kw)
        yield self._environ
        self._environ = old_environ

    @defaulted_property(default=False)
    def PEX_ALWAYS_CACHE(self):
        # type: () -> bool
        """Boolean.

        Always write PEX dependencies to disk prior to invoking regardless whether or not the
        dependencies are zip-safe.  For certain dependencies that are very large such as numpy, this
        can reduce the RAM necessary to launch the PEX.  The data will be written into $PEX_ROOT,
        which by default is $HOME/.pex.

        Default: false.
        """
        return self._get_bool("PEX_ALWAYS_CACHE")

    @defaulted_property(default=False)
    def PEX_COVERAGE(self):
        # type: () -> bool
        """Boolean.

        Enable coverage reporting for this PEX file.  This requires that the "coverage" module is
        available in the PEX environment.

        Default: false.
        """
        return self._get_bool("PEX_COVERAGE")

    @property
    def PEX_COVERAGE_FILENAME(self):
        # type: () -> Optional[str]
        """Filename.

        Write the coverage data to the specified filename.  If PEX_COVERAGE_FILENAME is not
        specified but PEX_COVERAGE is, coverage information will be printed to stdout and not saved.
        """
        return self._maybe_get_path("PEX_COVERAGE_FILENAME")

    @defaulted_property(default=False)
    def PEX_FORCE_LOCAL(self):
        # type: () -> bool
        """Boolean.

        Force this PEX to be not-zip-safe. This forces all code and dependencies to be written into
        $PEX_ROOT prior to invocation.  This is an option for applications with static assets that
        refer to paths relative to __file__ instead of using pkgutil/pkg_resources.  Also see
        PEX_UNZIP which will cause the complete PEX file to be unzipped and re-executed which can
        often improve startup latency in addition to providing support for __file__ access.

        Default: false.
        """
        return self._get_bool("PEX_FORCE_LOCAL")

    @defaulted_property(default=False)
    def PEX_UNZIP(self):
        # type: () -> bool
        """Boolean.

        Force this PEX to unzip itself to $PEX_ROOT and re-execute from there.  If the pex file will
        be run multiple times under a stable $PEX_ROOT the unzipping will only be performed once and
        subsequent runs will enjoy lower startup latency.

        Default: false.
        """
        return self._get_bool("PEX_UNZIP")

    @defaulted_property(default=False)
    def PEX_IGNORE_ERRORS(self):
        # type: () -> bool
        """Boolean.

        Ignore any errors resolving dependencies when invoking the PEX file. This can be useful if
        you know that a particular failing dependency is not necessary to run the application.

        Default: false.
        """
        return self._get_bool("PEX_IGNORE_ERRORS")

    @defaulted_property(default=InheritPath.FALSE)
    def PEX_INHERIT_PATH(self):
        # type: () -> InheritPath.Value
        """String (false|prefer|fallback)

        Allow inheriting packages from site-packages, user site-packages and the PYTHONPATH. By
        default, PEX scrubs any non stdlib packages from sys.path prior to invoking the application.
        Using 'prefer' causes PEX to shift any non-stdlib packages before the pex environment on
        sys.path and using 'fallback' shifts them after instead.

        Using this option is generally not advised, but can help in situations when certain
        dependencies do not conform to standard packaging practices and thus cannot be bundled into
        PEX files.

        See also PEX_EXTRA_SYS_PATH for how to *add* to the sys.path.

        Default: false.
        """
        try:
            return InheritPath.for_value(self._get_string("PEX_INHERIT_PATH"))
        except ValueError as e:
            die("Invalid value for PEX_INHERIT_PATH: {}".format(e))

    @defaulted_property(default=False)
    def PEX_INTERPRETER(self):
        # type: () -> bool
        """Boolean.

        Drop into a REPL instead of invoking the predefined entry point of this PEX. This can be
        useful for inspecting the PEX environment interactively.  It can also be used to treat the PEX
        file as an interpreter in order to execute other scripts in the context of the PEX file, e.g.
        "PEX_INTERPRETER=1 ./app.pex my_script.py".  Equivalent to setting PEX_MODULE to empty.

        Default: false.
        """
        return self._get_bool("PEX_INTERPRETER")

    @property
    def PEX_MODULE(self):
        # type: () -> Optional[str]
        """String.

        Override the entry point into the PEX file.  Can either be a module, e.g.
        'SimpleHTTPServer', or a specific entry point in module:symbol form, e.g.  "myapp.bin:main".
        """
        return self._maybe_get_string("PEX_MODULE")

    @defaulted_property(default=False)
    def PEX_PROFILE(self):
        # type: () -> bool
        """Boolean.

        Enable application profiling.  If specified and PEX_PROFILE_FILENAME is not specified, PEX
        will print profiling information to stdout.
        """
        return self._get_bool("PEX_PROFILE")

    @property
    def PEX_PROFILE_FILENAME(self):
        # type: () -> Optional[str]
        """Filename.

        Profile the application and dump a profile into the specified filename in the standard
        "profile" module format.
        """
        return self._maybe_get_path("PEX_PROFILE_FILENAME")

    @defaulted_property(default="cumulative")
    def PEX_PROFILE_SORT(self):
        # type: () -> str
        """String.

        Toggle the profile sorting algorithm used to print out profile columns.

        Default: 'cumulative'.
        """
        return self._get_string("PEX_PROFILE_SORT")

    @property
    def PEX_PYTHON(self):
        # type: () -> Optional[str]
        """String.

        Override the Python interpreter used to invoke this PEX.  Can be either an absolute path to
        an interpreter or a base name e.g.  "python3.3".  If a base name is provided, the $PATH will
        be searched for an appropriate match.
        """
        return self._maybe_get_string("PEX_PYTHON")

    @property
    def PEX_PYTHON_PATH(self):
        # type: () -> Optional[str]
        """String.

        A colon-separated string containing paths of blessed Python interpreters
        for overriding the Python interpreter used to invoke this PEX. Can be absolute paths to
        interpreters or standard $PATH style directory entries that are searched for child files that
        are python binaries.

        Ex: "/path/to/python27:/path/to/python36-distribution/bin"
        """
        return self._maybe_get_string("PEX_PYTHON_PATH")

    @property
    def PEX_EXTRA_SYS_PATH(self):
        # type: () -> Optional[str]
        """String.

        A colon-separated string containing paths to add to the runtime sys.path.

        Should be used sparingly, e.g., if you know that code inside this PEX needs to
        interact with code outside it.

        Ex: "/path/to/lib1:/path/to/lib2"

        This is distinct from PEX_INHERIT_PATH, which controls how the interpreter's
        existing sys.path (which you may not have control over) is scrubbed.

        See also PEX_PATH for how to merge packages from other pexes into the current environment.
        """
        return self._maybe_get_string("PEX_EXTRA_SYS_PATH")

    @defaulted_property(default=os.path.expanduser("~/.pex"))
    def PEX_ROOT(self):
        # type: () -> str
        """Directory.

        The directory location for PEX to cache any dependencies and code.  PEX must write not-zip-
        safe eggs and all wheels to disk in order to activate them.

        Default: ~/.pex
        """
        return self._get_path("PEX_ROOT")

    @PEX_ROOT.validator
    def _ensure_writeable_pex_root(self, pex_root):
        if not can_write_dir(pex_root):
            tmp_root = os.path.realpath(safe_mkdtemp())
            pex_warnings.warn(
                "PEX_ROOT is configured as {pex_root} but that path is un-writeable, "
                "falling back to a temporary PEX_ROOT of {tmp_root} which will hurt "
                "performance.".format(pex_root=pex_root, tmp_root=tmp_root)
            )
            pex_root = self._environ["PEX_ROOT"] = tmp_root
        return pex_root

    @defaulted_property(default="")
    def PEX_PATH(self):
        # type: () -> str
        """A set of one or more PEX files.

        Merge the packages from other PEX files into the current environment.  This allows you to
        do things such as create a PEX file containing the "coverage" module or create PEX files
        containing plugin entry points to be consumed by a main application.  Paths should be
        specified in the same manner as $PATH, e.g. PEX_PATH=/path/to/pex1.pex:/path/to/pex2.pex
        and so forth.

        See also PEX_EXTRA_SYS_PATH for how to add arbitrary entries to the sys.path.
        """
        return self._get_string("PEX_PATH")

    @property
    def PEX_SCRIPT(self):
        # type: () -> Optional[str]
        """String.

        The script name within the PEX environment to execute.  This must either be an entry point
        as defined in a distribution's console_scripts, or a script as defined in a distribution's
        scripts section.  While Python supports any script including shell scripts, PEX only
        supports invocation of Python scripts in this fashion.
        """
        return self._maybe_get_string("PEX_SCRIPT")

    @defaulted_property(default=False)
    def PEX_TEARDOWN_VERBOSE(self):
        # type: () -> bool
        """Boolean.

        Enable verbosity for when the interpreter shuts down.  This is mostly only useful for
        debugging PEX itself.

        Default: false.
        """
        return self._get_bool("PEX_TEARDOWN_VERBOSE")

    @defaulted_property(default=0)
    def PEX_VERBOSE(self):
        # type: () -> int
        """Integer.

        Set the verbosity level of PEX debug logging.  The higher the number, the more logging, with
        0 being disabled.  This environment variable can be extremely useful in debugging PEX
        environment issues.

        Default: 0
        """
        return self._get_int("PEX_VERBOSE")

    @defaulted_property(default=False)
    def PEX_IGNORE_RCFILES(self):
        # type: () -> bool
        """Boolean.

        Explicitly disable the reading/parsing of pexrc files (~/.pexrc).

        Default: false.
        """
        return self._get_bool("PEX_IGNORE_RCFILES")

    @property
    def PEX_EMIT_WARNINGS(self):
        # type: () -> Optional[bool]
        """Boolean.

        Emit UserWarnings to stderr. When false, warnings will only be logged at PEX_VERBOSE >= 1.
        When unset the build-time value of `--emit-warnings` will be used.

        Default: unset.
        """
        return self._maybe_get_bool("PEX_EMIT_WARNINGS")

    def __repr__(self):
        return "{}({!r})".format(type(self).__name__, self._environ)


# Global singleton environment
ENV = Variables()
