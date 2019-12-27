from distutils import log
import distutils.command.register as orig

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from setuptools.errors import RemovedCommandError  # vendor:skip
else:
  from pex.third_party.setuptools.errors import RemovedCommandError



class register(orig.register):
    """Formerly used to register packages on PyPI."""

    def run(self):
        msg = (
            "The register command has been removed, use twine to upload "
            + "instead (https://pypi.org/p/twine)"
        )

        self.announce("ERROR: " + msg, log.ERROR)

        raise RemovedCommandError(msg)
