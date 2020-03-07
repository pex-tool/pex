"""
Boolean Algebra.

This module defines a Boolean Algebra over the set {TRUE, FALSE} with boolean
variables and the boolean functions AND, OR, NOT. For extensive documentation
look either into the docs directory or view it online, at
https://booleanpy.readthedocs.org/en/latest/.

Copyright (c) 2009-2017 Sebastian Kraemer, basti.kr@gmail.com
Released under revised BSD license.
"""

from __future__ import absolute_import
from __future__ import unicode_literals
from __future__ import print_function

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import BooleanAlgebra  # vendor:skip
else:
  from pex.third_party.boolean.boolean import BooleanAlgebra


if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import Expression  # vendor:skip
else:
  from pex.third_party.boolean.boolean import Expression

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import Symbol  # vendor:skip
else:
  from pex.third_party.boolean.boolean import Symbol

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import ParseError  # vendor:skip
else:
  from pex.third_party.boolean.boolean import ParseError

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import PARSE_ERRORS  # vendor:skip
else:
  from pex.third_party.boolean.boolean import PARSE_ERRORS


if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import AND  # vendor:skip
else:
  from pex.third_party.boolean.boolean import AND

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import NOT  # vendor:skip
else:
  from pex.third_party.boolean.boolean import NOT

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import OR  # vendor:skip
else:
  from pex.third_party.boolean.boolean import OR


if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import TOKEN_TRUE  # vendor:skip
else:
  from pex.third_party.boolean.boolean import TOKEN_TRUE

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import TOKEN_FALSE  # vendor:skip
else:
  from pex.third_party.boolean.boolean import TOKEN_FALSE

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import TOKEN_SYMBOL  # vendor:skip
else:
  from pex.third_party.boolean.boolean import TOKEN_SYMBOL


if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import TOKEN_AND  # vendor:skip
else:
  from pex.third_party.boolean.boolean import TOKEN_AND

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import TOKEN_OR  # vendor:skip
else:
  from pex.third_party.boolean.boolean import TOKEN_OR

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import TOKEN_NOT  # vendor:skip
else:
  from pex.third_party.boolean.boolean import TOKEN_NOT


if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import TOKEN_LPAR  # vendor:skip
else:
  from pex.third_party.boolean.boolean import TOKEN_LPAR

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import TOKEN_RPAR  # vendor:skip
else:
  from pex.third_party.boolean.boolean import TOKEN_RPAR

