# SPDX-License-Identifier: MIT

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from attr.validators import *    # vendor:skip
else:
  from pex.third_party.attr.validators import *  
# noqa
