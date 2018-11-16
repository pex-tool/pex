import pex.third_party.pkg_resources as pkg_resources

try:
    __version__ = pkg_resources.get_distribution('setuptools').version
except Exception:
    __version__ = 'unknown'
