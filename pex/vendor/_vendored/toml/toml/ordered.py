from collections import OrderedDict
if "toml" in __import__("os").environ.get("__PEX_UNVENDORED__", ""):
    from toml import TomlEncoder  # vendor:skip
else:
    from pex.third_party.toml import TomlEncoder

if "toml" in __import__("os").environ.get("__PEX_UNVENDORED__", ""):
    from toml import TomlDecoder  # vendor:skip
else:
    from pex.third_party.toml import TomlDecoder



class TomlOrderedDecoder(TomlDecoder):

    def __init__(self):
        super(self.__class__, self).__init__(_dict=OrderedDict)


class TomlOrderedEncoder(TomlEncoder):

    def __init__(self):
        super(self.__class__, self).__init__(_dict=OrderedDict)
