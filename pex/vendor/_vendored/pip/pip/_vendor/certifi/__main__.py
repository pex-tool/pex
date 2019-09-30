if "__PEX_UNVENDORED__" in __import__("os").environ:
  from pip._vendor.certifi import where  # vendor:skip
else:
  from pex.third_party.pip._vendor.certifi import where

print(where())
