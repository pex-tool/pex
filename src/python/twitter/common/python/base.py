from collections import Iterable

from twitter.common.lang import Compatibility

from pkg_resources import Requirement


def maybe_requirement(req):
  if isinstance(req, Requirement):
    return req
  elif isinstance(req, Compatibility.string):
    return Requirement.parse(req)
  raise ValueError('Unknown requirement %r' % (req,))


def maybe_requirement_list(reqs):
  if isinstance(reqs, (Compatibility.string, Requirement)):
    return [maybe_requirement(reqs)]
  elif isinstance(reqs, Iterable):
    return [maybe_requirement(req) for req in reqs]
  raise ValueError('Unknown requirement list %r' % (reqs,))
