if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._vendor.packaging.version import parse as parse_version  # vendor:skip
else:
  from pex.third_party.pip._vendor.packaging.version import parse as parse_version


if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.utils.models import KeyBasedCompareMixin  # vendor:skip
else:
  from pex.third_party.pip._internal.utils.models import KeyBasedCompareMixin

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._internal.utils.typing import MYPY_CHECK_RUNNING  # vendor:skip
else:
  from pex.third_party.pip._internal.utils.typing import MYPY_CHECK_RUNNING


if MYPY_CHECK_RUNNING:
    if "__PEX_UNVENDORED__" in __import__("os").environ:
      from pip._vendor.packaging.version import _BaseVersion  # vendor:skip
    else:
      from pex.third_party.pip._vendor.packaging.version import _BaseVersion

    if "__PEX_UNVENDORED__" in __import__("os").environ:
      from pip._internal.models.link import Link  # vendor:skip
    else:
      from pex.third_party.pip._internal.models.link import Link

    from typing import Any


class InstallationCandidate(KeyBasedCompareMixin):
    """Represents a potential "candidate" for installation.
    """

    def __init__(self, project, version, link):
        # type: (Any, str, Link) -> None
        self.project = project
        self.version = parse_version(version)  # type: _BaseVersion
        self.link = link

        super(InstallationCandidate, self).__init__(
            key=(self.project, self.version, self.link),
            defining_class=InstallationCandidate
        )

    def __repr__(self):
        # type: () -> str
        return "<InstallationCandidate({!r}, {!r}, {!r})>".format(
            self.project, self.version, self.link,
        )

    def __str__(self):
        return '{!r} candidate (version {} at {})'.format(
            self.project, self.version, self.link,
        )
