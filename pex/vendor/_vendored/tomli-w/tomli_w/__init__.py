__all__ = ("dumps", "dump")
__version__ = "1.0.0"  # DO NOT EDIT THIS LINE MANUALLY. LET bump2version UTILITY DO IT

if "tomli-w" in __import__("os").environ.get("__PEX_UNVENDORED__", ""):
    from tomli_w._writer import dump, dumps  # vendor:skip
else:
    from pex.third_party.tomli_w._writer import dump, dumps

