if "__PEX_UNVENDORED__" in __import__("os").environ:
  import pkg_resources  # vendor:skip
else:
  import pex.third_party.pkg_resources as pkg_resources


try:
    __version__ = pkg_resources.get_distribution('setuptools').version
except Exception:
    __version__ = 'unknown'
