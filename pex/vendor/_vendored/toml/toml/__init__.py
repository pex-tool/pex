"""Python module which parses and emits TOML.

Released under the MIT license.
"""

if "toml" in __import__("os").environ.get("__PEX_UNVENDORED__", ""):
    from toml import encoder  # vendor:skip
else:
    from pex.third_party.toml import encoder

if "toml" in __import__("os").environ.get("__PEX_UNVENDORED__", ""):
    from toml import decoder  # vendor:skip
else:
    from pex.third_party.toml import decoder


__version__ = "0.10.2"
_spec_ = "0.5.0"

load = decoder.load
loads = decoder.loads
TomlDecoder = decoder.TomlDecoder
TomlDecodeError = decoder.TomlDecodeError
TomlPreserveCommentDecoder = decoder.TomlPreserveCommentDecoder

dump = encoder.dump
dumps = encoder.dumps
TomlEncoder = encoder.TomlEncoder
TomlArraySeparatorEncoder = encoder.TomlArraySeparatorEncoder
TomlPreserveInlineDictEncoder = encoder.TomlPreserveInlineDictEncoder
TomlNumpyEncoder = encoder.TomlNumpyEncoder
TomlPreserveCommentEncoder = encoder.TomlPreserveCommentEncoder
TomlPathlibEncoder = encoder.TomlPathlibEncoder
