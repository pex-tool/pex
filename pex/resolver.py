# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import functools
import json
import os
import shutil
import subprocess
from collections import defaultdict, namedtuple
from textwrap import dedent

from pex import third_party
from pex.common import safe_mkdir, safe_mkdtemp
from pex.interpreter import PythonInterpreter
from pex.orderedset import OrderedSet
from pex.pip import PipError, build_wheels, download_distributions, install_wheel
from pex.requirements import local_project_from_requirement, local_projects_from_requirement_file
from pex.third_party.pkg_resources import Distribution, Environment, Requirement
from pex.tracer import TRACER


class Untranslateable(Exception):
  pass


class Unsatisfiable(Exception):
  pass


class ResolvedDistribution(namedtuple('ResolvedDistribution', ['requirement', 'distribution'])):
  """A requirement and the resolved distribution that satisfies it."""

  def __new__(cls, requirement, distribution):
    assert isinstance(requirement, Requirement)
    assert isinstance(distribution, Distribution)
    return super(ResolvedDistribution, cls).__new__(cls, requirement, distribution)


def _calculate_dependency_markers(distributions, interpreter=None):
  search_path = [dist.location for dist in distributions]
  program = dedent("""
    import json
    import sys
    from collections import defaultdict
    from pkg_resources import Environment
    
    
    env = Environment(search_path={search_path!r})
    dependency_requirements = []
    for key in env:
      for dist in env[key]:
        dependency_requirements.extend(str(req) for req in dist.requires())
    json.dump(dependency_requirements, sys.stdout)
  """.format(search_path=search_path))

  env = os.environ.copy()
  env['__PEX_UNVENDORED__'] = '1'

  pythonpath = third_party.expose(['setuptools'])

  interpreter = interpreter or PythonInterpreter.get()
  _, process = interpreter.open_process(args=['-c', program],
                                        stdout=subprocess.PIPE,
                                        pythonpath=pythonpath,
                                        env=env)
  stdout, _ = process.communicate()
  if process.returncode != 0:
    raise Untranslateable('Could not determine dependency environment markers for {}'
                          .format(distributions))

  dependency_requirements = json.loads(stdout.decode('utf-8'))
  markers_by_req_key = defaultdict(OrderedSet)
  for requirement in dependency_requirements:
    req = Requirement.parse(requirement)
    if req.marker:
      markers_by_req_key[req.key].add(req.marker)
  return markers_by_req_key


def resolve(requirements=None,
            requirement_files=None,
            constraint_files=None,
            allow_prereleases=False,
            transitive=True,
            interpreter=None,
            platform=None,
            indexes=None,
            find_links=None,
            cache=None,
            build=True,
            use_wheel=True,
            compile=False):
  """Produce all distributions needed to meet all specified requirements.

  :keyword requirements: A sequence of requirement strings.
  :type requirements: list of str
  :keyword requirement_files: A sequence of requirement file paths.
  :type requirement_files: list of str
  :keyword constraint_files: A sequence of constraint file paths.
  :type constraint_files: list of str
  :keyword bool allow_prereleases: Whether to include pre-release and development versions when
    resolving requirements. Defaults to ``False``, but any requirements that explicitly request
    prerelease or development versions will override this setting.
  :keyword bool transitive: Whether to resolve transitive dependencies of requirements.
    Defaults to ``True``.
  :keyword interpreter: The interpreter to use for building distributions and for testing
    distribution compatibility. Defaults to the current interpreter.
  :type interpreter: :class:`pex.interpreter.PythonInterpreter`
  :keyword str platform: The exact target platform to resolve distributions for. If ``None`` or
    ``'current'``, use the local system platform.
  :keyword indexes: A list of urls or paths pointing to PEP 503 compliant repositories to search for
    distributions. Defaults to ``None`` which indicates to use the default pypi index. To turn off
    use of all indexes, pass an empty list.
  :type indexes: list of str
  :keyword find_links: A list or URLs, paths to local html files or directory paths. If URLs or
    local html file paths, these are parsed for links to distributions. If a local directory path,
    its listing is used to discover distributons.
  :type find_links: list of str
  :keyword str cache: A directory path to use to cache distributions locally.
  :keyword bool build: Whether to allow building source distributions when no wheel is found.
    Defaults to ``True``.
  :keyword bool use_wheel: Whether to allow resolution of pre-built wheel distributions.
    Defaults to ``True``.
  :keyword bool compile: Whether to pre-compile resolved distribution python sources.
    Defaults to ``False``.
  :returns: List of :class:`ResolvedDistribution` instances meeting ``requirements``.
  :raises Unsatisfiable: If ``requirements`` is not transitively satisfiable.
  :raises Untranslateable: If no compatible distributions could be acquired for
    a particular requirement.
  """

  # This function has three stages: 1) resolve, 2) build, and 3) chroot.
  #
  # You'd think we might be able to just pip install all the requirements, but pexes can be
  # multi-platform / multi-interpreter, in which case only a subset of distributions resolved into
  # the PEX should be activated for the runtime interpreter. Sometimes there are platform specific
  # wheels and sometimes python version specific dists (backports being the common case). As such,
  # we need to be able to add each resolved distribution to the `sys.path` individually
  # (`PEXEnvironment` handles this selective activation at runtime). Since pip install only accepts
  # a single location to install all resolved dists, that won't work.
  #
  # This means we need to seperately resolve all distributions, then install each in their own
  # chroot. To do this we use `pip download` for the resolve and download of all needed
  # distributions and then `pip install` to install each distribution in its own chroot.
  #
  # As a complicating factor, the runtime activation scheme relies on PEP 425 tags; i.e.: wheel
  # names. Some requirements are only available or applicable in source form - either via sdist, VCS
  # URL or local projects. As such we need to insert a `pip wheel` step to generate wheels for all
  # requirements resolved in source form via `pip download` / inspection of requirements to
  # discover those that are local directories (local setup.py or pyproject.toml python projects).

  if not requirements and not requirement_files:
    # Nothing to resolve.
    return []

  workspace = safe_mkdtemp()
  resolved_dists = os.path.join(workspace, 'resolved')
  built_wheels = os.path.join(workspace, 'wheels')
  installed_chroots = os.path.join(workspace, 'chroots')

  # 1. Resolve
  try:
    download_distributions(target=resolved_dists,
                           requirements=requirements,
                           requirement_files=requirement_files,
                           constraint_files=constraint_files,
                           allow_prereleases=allow_prereleases,
                           transitive=transitive,
                           interpreter=interpreter,
                           platform=platform,
                           indexes=indexes,
                           find_links=find_links,
                           cache=cache,
                           build=build,
                           use_wheel=use_wheel)
  except PipError as e:
    raise Unsatisfiable(str(e))

  # 2. Build
  to_build = []
  if requirements:
    for req in requirements:
      local_project = local_project_from_requirement(req)
      if local_project:
        to_build.append(local_project)
  if requirement_files:
    for requirement_file in requirement_files:
      to_build.extend(local_projects_from_requirement_file(requirement_file))

  to_copy = []
  if os.path.exists(resolved_dists):
    for distribution in os.listdir(resolved_dists):
      path = os.path.join(resolved_dists, distribution)
      if os.path.isfile(path) and path.endswith('.whl'):
        to_copy.append(path)
      else:
        to_build.append(path)

  if not any((to_build, to_copy)):
    # Nothing to build or install.
    return []

  safe_mkdir(built_wheels)

  if to_build:
    try:
      build_wheels(distributions=to_build,
                   target=built_wheels,
                   cache=cache,
                   interpreter=interpreter)
    except PipError as e:
      raise Untranslateable('Failed to build at least one of {}:\n\t{}'.format(to_build, str(e)))

  if to_copy:
    for wheel in to_copy:
      dest = os.path.join(built_wheels, os.path.basename(wheel))
      TRACER.log('Copying downloaded wheel from {} to {}'.format(wheel, dest))
      shutil.copy(wheel, dest)

  # 3. Chroot
  resolved_distributions = []

  for wheel_file in os.listdir(built_wheels):
    chroot = os.path.join(installed_chroots, wheel_file)
    try:
      install_wheel(wheel=os.path.join(built_wheels, wheel_file),
                    target=chroot,
                    compile=compile,
                    overwrite=True,
                    cache=cache,
                    interpreter=interpreter)
    except PipError as e:
      raise Untranslateable('Failed to install {}:\n\t{}'.format(wheel_file, str(e)))

    environment = Environment(search_path=[chroot])
    for dist_project_name in environment:
      resolved_distributions.extend(environment[dist_project_name])

  markers_by_req_key = _calculate_dependency_markers(resolved_distributions,
                                                     interpreter=interpreter)

  def to_requirement(dist):
    req = dist.as_requirement()
    markers = markers_by_req_key.get(req.key)
    if not markers:
      return req

    if len(markers) == 1:
      marker = next(iter(markers))
      req.marker = marker
      return req

    # Here we have a resolve with multiple paths to the dependency represented by dist. At least
    # two of those paths had (different) conditional requirements for dist based on environment
    # marker predicates. Since the pip resolve succeeded, the implication is that the environment
    # markers are compatible; i.e.: their intersection selects the target interpreter. Here we
    # make that intersection explicit.
    # See: https://www.python.org/dev/peps/pep-0496/#micro-language
    marker = ' and '.join('({})'.format(marker) for marker in markers)
    return Requirement.parse('{}; {}'.format(req, marker))

  return [ResolvedDistribution(to_requirement(dist), dist) for dist in resolved_distributions]


def resolve_multi(requirements=None,
                  requirement_files=None,
                  constraint_files=None,
                  allow_prereleases=False,
                  transitive=True,
                  interpreters=None,
                  platforms=None,
                  indexes=None,
                  find_links=None,
                  cache=None,
                  build=True,
                  use_wheel=True,
                  compile=True):
  """A generator function that produces all distributions needed to meet `requirements`
  for multiple interpreters and/or platforms.

  :keyword requirements: A sequence of requirement strings.
  :type requirements: list of str
  :keyword requirement_files: A sequence of requirement file paths.
  :type requirement_files: list of str
  :keyword constraint_files: A sequence of constraint file paths.
  :type constraint_files: list of str
  :keyword bool allow_prereleases: Whether to include pre-release and development versions when
    resolving requirements. Defaults to ``False``, but any requirements that explicitly request
    prerelease or development versions will override this setting.
  :keyword bool transitive: Whether to resolve transitive dependencies of requirements.
    Defaults to ``True``.
  :keyword interpreters: The interpreters to use for building distributions and for testing
    distribution compatibility. Defaults to the current interpreter.
  :type interpreters: list of :class:`pex.interpreter.PythonInterpreter`
  :keyword platforms: An iterable of PEP425-compatible platform strings to resolve distributions
    for. If ``None`` (the default) or an empty iterable, use the platforms of the given
    interpreters.
  :type platforms: list of str
  :keyword indexes: A list of urls or paths pointing to PEP 503 compliant repositories to search for
    distributions. Defaults to ``None`` which indicates to use the default pypi index. To turn off
    use of all indexes, pass an empty list.
  :type indexes: list of str
  :keyword find_links: A list or URLs, paths to local html files or directory paths. If URLs or
    local html file paths, these are parsed for links to distributions. If a local directory path,
    its listing is used to discover distributons.
  :type find_links: list of str
  :keyword str cache: A directory path to use to cache distributions locally.
  :keyword bool build: Whether to allow building source distributions when no wheel is found.
    Defaults to ``True``.
  :keyword bool use_wheel: Whether to allow resolution of pre-built wheel distributions.
    Defaults to ``True``.
  :keyword bool compile: Whether to pre-compile resolved distribution python sources.
    Defaults to ``False``.
  :yields: All :class:`ResolvedDistribution` instances meeting ``requirements`` for all
    specifed interpreters and platforms.
  :raises Unsatisfiable: If ``requirements`` is not transitively satisfiable.
  :raises Untranslateable: If no compatible distributions could be acquired for
    a particular requirement.
  """

  curried_resolve = functools.partial(resolve,
                                      requirements=requirements,
                                      requirement_files=requirement_files,
                                      constraint_files=constraint_files,
                                      allow_prereleases=allow_prereleases,
                                      transitive=transitive,
                                      indexes=indexes,
                                      find_links=find_links,
                                      cache=cache,
                                      build=build,
                                      use_wheel=use_wheel,
                                      compile=compile)

  def iter_kwargs():
    if not interpreters and not platforms:
      yield dict(interpreter=None, platform=None)
      return

    if interpreters:
      for interpreter in interpreters:
        yield dict(interpreter=interpreter)

    if platforms:
      for platform in platforms:
        yield dict(platform=platform)

  seen = set()
  for kwargs in iter_kwargs():
    for resolvable in curried_resolve(**kwargs):
      if resolvable not in seen:
        seen.add(resolvable)
        yield resolvable
