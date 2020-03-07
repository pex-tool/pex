"""
Boolean Algebra.

Tests

Copyright (c) 2009-2017 Sebastian Kraemer, basti.kr@gmail.com and others
Released under revised BSD license.
"""

from __future__ import absolute_import
from __future__ import unicode_literals
from __future__ import print_function
if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import PARSE_UNKNOWN_TOKEN  # vendor:skip
else:
  from pex.third_party.boolean.boolean import PARSE_UNKNOWN_TOKEN


# Python 2 and 3
try:
    basestring  # NOQA
except NameError:
    basestring = str  # NOQA

import unittest
from unittest.case import expectedFailure

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean import BooleanAlgebra  # vendor:skip
else:
  from pex.third_party.boolean import BooleanAlgebra

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean import ParseError  # vendor:skip
else:
  from pex.third_party.boolean import ParseError

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean import Symbol  # vendor:skip
else:
  from pex.third_party.boolean import Symbol

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean import TOKEN_NOT  # vendor:skip
else:
  from pex.third_party.boolean import TOKEN_NOT

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean import TOKEN_AND  # vendor:skip
else:
  from pex.third_party.boolean import TOKEN_AND

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean import TOKEN_OR  # vendor:skip
else:
  from pex.third_party.boolean import TOKEN_OR

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean import TOKEN_TRUE  # vendor:skip
else:
  from pex.third_party.boolean import TOKEN_TRUE

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean import TOKEN_FALSE  # vendor:skip
else:
  from pex.third_party.boolean import TOKEN_FALSE

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean import TOKEN_SYMBOL  # vendor:skip
else:
  from pex.third_party.boolean import TOKEN_SYMBOL

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean import TOKEN_LPAR  # vendor:skip
else:
  from pex.third_party.boolean import TOKEN_LPAR

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean import TOKEN_RPAR  # vendor:skip
else:
  from pex.third_party.boolean import TOKEN_RPAR

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import PARSE_INVALID_SYMBOL_SEQUENCE  # vendor:skip
else:
  from pex.third_party.boolean.boolean import PARSE_INVALID_SYMBOL_SEQUENCE

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import PARSE_INVALID_EXPRESSION  # vendor:skip
else:
  from pex.third_party.boolean.boolean import PARSE_INVALID_EXPRESSION

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import PARSE_INVALID_NESTING  # vendor:skip
else:
  from pex.third_party.boolean.boolean import PARSE_INVALID_NESTING

if "__PEX_UNVENDORED__" in __import__("os").environ:
  from boolean.boolean import PARSE_INVALID_OPERATOR_SEQUENCE  # vendor:skip
else:
  from pex.third_party.boolean.boolean import PARSE_INVALID_OPERATOR_SEQUENCE



class BooleanAlgebraTestCase(unittest.TestCase):

    def test_creation(self):
        algebra = BooleanAlgebra()
        expr_str = '(a|b|c)&d&(~e|(f&g))'
        expr = algebra.parse(expr_str)
        self.assertEqual(expr_str, str(expr))

    def test_parse_with_mixed_operators_multilines_and_custom_symbol(self):

        class MySymbol(Symbol):
            pass

        expr_str = '''(a or ~ b +_c  ) and
                      d & ( ! e_
                      | (my * g OR 1 or 0) ) AND that '''

        algebra = BooleanAlgebra(Symbol_class=MySymbol)
        expr = algebra.parse(expr_str)

        expected = algebra.AND(
            algebra.OR(
                algebra.Symbol('a'),
                algebra.NOT(algebra.Symbol('b')),
                algebra.Symbol('_c'),
            ),
            algebra.Symbol('d'),
            algebra.OR(
                algebra.NOT(algebra.Symbol('e_')),
                algebra.OR(
                    algebra.AND(
                        algebra.Symbol('my'),
                        algebra.Symbol('g'),
                    ),
                    algebra.TRUE,
                    algebra.FALSE,
                ),
            ),
            algebra.Symbol('that'),
        )

        self.assertEqual(expected.pretty(), expr.pretty())
        self.assertEqual(expected, expr)

    def test_parse_recognizes_trueish_and_falsish_symbol_tokens(self):
        expr_str = 'True or False or None or 0 or 1 or TRue or FalSE or NONe'
        algebra = BooleanAlgebra()
        expr = algebra.parse(expr_str)
        expected = algebra.OR(
            algebra.TRUE,
            algebra.FALSE,
            algebra.FALSE,
            algebra.FALSE,
            algebra.TRUE,
            algebra.TRUE,
            algebra.FALSE,
            algebra.FALSE,
        )
        self.assertEqual(expected, expr)

    def test_parse_can_use_iterable_from_alternative_tokenizer(self):

        class CustomSymbol(Symbol):
            pass

        class CustomAlgebra(BooleanAlgebra):
            def __init__(self, Symbol_class=CustomSymbol):
                super(CustomAlgebra, self).__init__(Symbol_class=CustomSymbol)

            def tokenize(self, s):
                "Sample tokenizer using custom operators and symbols"
                ops = {
                    'WHY_NOT': TOKEN_OR,
                    'ALSO': TOKEN_AND,
                    'NEITHER': TOKEN_NOT,
                    '(': TOKEN_LPAR,
                    ')': TOKEN_RPAR,
                }

                for row, line in enumerate(s.splitlines(False)):
                    for col, tok in enumerate(line.split()):
                        if tok in ops:
                            yield ops[tok], tok, (row, col)
                        elif tok == 'Custom':
                            yield self.Symbol(tok), tok, (row, col)
                        else:
                            yield TOKEN_SYMBOL, tok, (row, col)

        expr_str = '''( Custom WHY_NOT regular ) ALSO NEITHER  (
                      not_custom ALSO standard )
                   '''

        algebra = CustomAlgebra()
        expr = algebra.parse(expr_str)
        expected = algebra.AND(
            algebra.OR(
                algebra.Symbol('Custom'),
                algebra.Symbol('regular'),
            ),
            algebra.NOT(
                algebra.AND(
                    algebra.Symbol('not_custom'),
                    algebra.Symbol('standard'),
                ),
            ),
        )
        self.assertEqual(expected, expr)

    def test_parse_with_advanced_tokenizer_example(self):
        import tokenize

        try:
            from io import StringIO
        except ImportError:
            try:
                from cStringIO import StringIO
            except ImportError:
                from StringIO import StringIO


        class PlainVar(Symbol):
            "Plain boolean variable"

        class ColonDotVar(Symbol):
            "Colon and dot-separated string boolean variable"

        class AdvancedAlgebra(BooleanAlgebra):
            def tokenize(self, expr):
                """
                Example custom tokenizer derived from the standard Python tokenizer
                with a few extra features: #-style comments are supported and a
                colon- and dot-separated string is recognized and stored in custom
                symbols. In contrast with the standard tokenizer, only these
                boolean operators are recognized : & | ! and or not.

                For more advanced tokenization you could also consider forking the
                `tokenize` standard library module.
                """

                if not isinstance(expr, basestring):
                    raise TypeError('expr must be string but it is %s.' % type(expr))

                # mapping of lowercase token strings to a token object instance for
                # standard operators, parens and common true or false symbols
                TOKENS = {
                    '&': TOKEN_AND,
                    'and': TOKEN_AND,
                    '|': TOKEN_OR,
                    'or': TOKEN_OR,
                    '!': TOKEN_NOT,
                    'not': TOKEN_NOT,
                    '(': TOKEN_LPAR,
                    ')': TOKEN_RPAR,
                    'true': TOKEN_TRUE,
                    '1': TOKEN_TRUE,
                    'false': TOKEN_FALSE,
                    '0': TOKEN_FALSE,
                    'none': TOKEN_FALSE,
                }

                ignored_token_types = (
                    tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT,
                    tokenize.INDENT, tokenize.DEDENT,
                    tokenize.ENDMARKER
                )

                # note: an unbalanced expression may raise a TokenError here.
                tokens = ((toktype, tok, row, col,) for toktype, tok, (row, col,), _, _
                          in tokenize.generate_tokens(StringIO(expr).readline)
                          if tok and tok.strip())

                COLON_DOT = (':', '.',)

                def build_symbol(current_dotted):
                    if current_dotted:
                        if any(s in current_dotted for s in COLON_DOT):
                            sym = ColonDotVar(current_dotted)
                        else:
                            sym = PlainVar(current_dotted)
                        return sym

                # accumulator for dotted symbols that span several `tokenize` tokens
                dotted, srow, scol = '', None, None

                for toktype, tok, row, col in tokens:
                    if toktype in ignored_token_types:
                        # we reached a break point and should yield the current dotted
                        symbol = build_symbol(dotted)
                        if symbol is not None:
                            yield symbol, dotted, (srow, scol)
                            dotted, srow, scol = '', None, None

                        continue

                    std_token = TOKENS.get(tok.lower())
                    if std_token is not None:
                        # we reached a break point and should yield the current dotted
                        symbol = build_symbol(dotted)
                        if symbol is not None:
                            yield symbol, dotted, (srow, scol)
                            dotted, srow, scol = '', 0, 0

                        yield std_token, tok, (row, col)

                        continue

                    if toktype == tokenize.NAME or (toktype == tokenize.OP and tok in COLON_DOT):
                        if not dotted:
                            srow = row
                            scol = col
                        dotted += tok

                    else:
                        raise TypeError('Unknown token: %(tok)r at line: %(row)r, column: %(col)r' % locals())

        test_expr = '''
            (colon1:dot1.dot2 or colon2_name:col_on3:do_t1.do_t2.do_t3 )
            and
            ( plain_symbol & !Custom )
        '''

        algebra = AdvancedAlgebra()
        expr = algebra.parse(test_expr)
        expected = algebra.AND(
            algebra.OR(
                ColonDotVar('colon1:dot1.dot2'),
                ColonDotVar('colon2_name:col_on3:do_t1.do_t2.do_t3')
            ),
            algebra.AND(
                PlainVar('plain_symbol'),
                algebra.NOT(PlainVar('Custom'))
            )
        )
        self.assertEqual(expected, expr)

    def test_allowing_additional_characters_in_tokens(self):
        algebra = BooleanAlgebra(allowed_in_token=('.', '_', '-', '+'))
        test_expr = 'l-a AND b+c'

        expr = algebra.parse(test_expr)
        expected = algebra.AND(
            algebra.Symbol('l-a'),
            algebra.Symbol('b+c')
        )
        self.assertEqual(expected, expr)

    def test_parse_raise_ParseError1(self):
        algebra = BooleanAlgebra()
        expr = 'l-a AND none'

        try:
            algebra.parse(expr)
            self.fail("Exception should be raised when parsing '%s'" % expr)
        except ParseError as pe:
            assert pe.error_code == PARSE_UNKNOWN_TOKEN

    def test_parse_raise_ParseError2(self):
        algebra = BooleanAlgebra()
        expr = '(l-a + AND l-b'
        try:
            algebra.parse(expr)
            self.fail("Exception should be raised when parsing '%s'" % expr)
        except ParseError as pe:
            assert pe.error_code == PARSE_UNKNOWN_TOKEN

    def test_parse_raise_ParseError3(self):
        algebra = BooleanAlgebra()
        expr = '(l-a + AND l-b)'
        try:
            algebra.parse(expr)
            self.fail("Exception should be raised when parsing '%s'" % expr)
        except ParseError as pe:
            assert pe.error_code == PARSE_UNKNOWN_TOKEN

    def test_parse_raise_ParseError4(self):
        algebra = BooleanAlgebra()
        expr = '(l-a AND l-b'
        try:
            algebra.parse(expr)
            self.fail("Exception should be raised when parsing '%s'" % expr)
        except ParseError as pe:
            assert pe.error_code == PARSE_UNKNOWN_TOKEN

    def test_parse_raise_ParseError5(self):
        algebra = BooleanAlgebra()
        expr = '(l-a + AND l-b))'
        try:
            algebra.parse(expr)
            self.fail("Exception should be raised when parsing '%s'" % expr)
        except ParseError as pe:
            assert pe.error_code == PARSE_UNKNOWN_TOKEN

    def test_parse_raise_ParseError6(self):
        algebra = BooleanAlgebra()
        expr = '(l-a  AND l-b))'
        try:
            algebra.parse(expr)
            self.fail("Exception should be raised when parsing '%s'" % expr)
        except ParseError as pe:
            assert pe.error_code == PARSE_UNKNOWN_TOKEN

    def test_parse_raise_ParseError7(self):
        algebra = BooleanAlgebra()
        expr = 'l-a AND'
        try:
            algebra.parse(expr)
            self.fail("Exception should be raised when parsing '%s'" % expr)
        except ParseError as pe:
            assert pe.error_code == PARSE_UNKNOWN_TOKEN

    def test_parse_raise_ParseError8(self):
        algebra = BooleanAlgebra()
        expr = 'OR l-a'
        try:
            algebra.parse(expr)
            self.fail("Exception should be raised when parsing '%s'" % expr)
        except ParseError as pe:
            assert pe.error_code == PARSE_INVALID_OPERATOR_SEQUENCE

    def test_parse_raise_ParseError9(self):
        algebra = BooleanAlgebra()
        expr = '+ l-a'
        try:
            algebra.parse(expr)
            self.fail("Exception should be raised when parsing '%s'" % expr)
        except ParseError as pe:
            assert pe.error_code == PARSE_INVALID_OPERATOR_SEQUENCE

    def test_parse_side_by_side_symbols_should_raise_exception_but_not(self):
        algebra = BooleanAlgebra()
        expr_str = 'a or b c'
        try:
            algebra.parse(expr_str)
        except ParseError as pe:
            assert pe.error_code == PARSE_INVALID_SYMBOL_SEQUENCE

    def test_parse_side_by_side_symbols_should_raise_exception_but_not2(self):
        algebra = BooleanAlgebra()
        expr_str = '(a or b) c'
        try:
            algebra.parse(expr_str)
        except ParseError as pe:
            assert pe.error_code == PARSE_INVALID_EXPRESSION

    def test_parse_side_by_side_symbols_raise_exception(self):
        algebra = BooleanAlgebra()
        expr_str = 'a b'
        try:
            algebra.parse(expr_str)
        except ParseError as pe:
            assert pe.error_code == PARSE_INVALID_SYMBOL_SEQUENCE

    def test_parse_side_by_side_symbols_with_parens_raise_exception(self):
        algebra = BooleanAlgebra()
        expr_str = '(a) (b)'
        try:
            algebra.parse(expr_str)
        except ParseError as pe:
            assert pe.error_code == PARSE_INVALID_NESTING

class BaseElementTestCase(unittest.TestCase):

    def test_creation(self):
        if "__PEX_UNVENDORED__" in __import__("os").environ:
          from boolean.boolean import BaseElement  # vendor:skip
        else:
          from pex.third_party.boolean.boolean import BaseElement

        algebra = BooleanAlgebra()
        self.assertEqual(algebra.TRUE, algebra.TRUE)
        BaseElement()
        self.assertRaises(TypeError, BaseElement, 2)
        self.assertRaises(TypeError, BaseElement, 'a')
        self.assertTrue(algebra.TRUE is algebra.TRUE)
        self.assertTrue(algebra.TRUE is not algebra.FALSE)
        self.assertTrue(algebra.FALSE is algebra.FALSE)
        self.assertTrue(bool(algebra.TRUE) is True)
        self.assertTrue(bool(algebra.FALSE) is False)
        self.assertEqual(algebra.TRUE, True)
        self.assertEqual(algebra.FALSE, False)

    def test_literals(self):
        algebra = BooleanAlgebra()
        self.assertEqual(algebra.TRUE.literals, set())
        self.assertEqual(algebra.FALSE.literals, set())

    def test_literalize(self):
        algebra = BooleanAlgebra()
        self.assertEqual(algebra.TRUE.literalize(), algebra.TRUE)
        self.assertEqual(algebra.FALSE.literalize(), algebra.FALSE)

    def test_simplify(self):
        algebra = BooleanAlgebra()
        self.assertEqual(algebra.TRUE.simplify(), algebra.TRUE)
        self.assertEqual(algebra.FALSE.simplify(), algebra.FALSE)

    def test_simplify_two_algebra(self):
        algebra1 = BooleanAlgebra()
        algebra2 = BooleanAlgebra()
        self.assertEqual(algebra1.TRUE.simplify(), algebra2.TRUE)
        self.assertEqual(algebra1.FALSE.simplify(), algebra2.FALSE)

    def test_dual(self):
        algebra = BooleanAlgebra()
        self.assertEqual(algebra.TRUE.dual, algebra.FALSE)
        self.assertEqual(algebra.FALSE.dual, algebra.TRUE)

    def test_equality(self):
        algebra = BooleanAlgebra()
        self.assertEqual(algebra.TRUE, algebra.TRUE)
        self.assertEqual(algebra.FALSE, algebra.FALSE)
        self.assertNotEqual(algebra.TRUE, algebra.FALSE)

    def test_order(self):
        algebra = BooleanAlgebra()
        self.assertTrue(algebra.FALSE < algebra.TRUE)
        self.assertTrue(algebra.TRUE > algebra.FALSE)

    def test_printing(self):
        algebra = BooleanAlgebra()
        self.assertEqual(str(algebra.TRUE), '1')
        self.assertEqual(str(algebra.FALSE), '0')
        self.assertEqual(repr(algebra.TRUE), 'TRUE')
        self.assertEqual(repr(algebra.FALSE), 'FALSE')


class SymbolTestCase(unittest.TestCase):

    def test_init(self):
        Symbol(1)
        Symbol('a')
        Symbol(None)
        Symbol(sum)
        Symbol((1, 2, 3))
        Symbol([1, 2])

    def test_isliteral(self):
        self.assertTrue(Symbol(1).isliteral is True)

    def test_literals(self):
        l1 = Symbol(1)
        l2 = Symbol(1)
        self.assertTrue(l1 in l1.literals)
        self.assertTrue(l1 in l2.literals)
        self.assertTrue(l2 in l1.literals)
        self.assertTrue(l2 in l2.literals)
        self.assertRaises(AttributeError, setattr, l1, 'literals', 1)

    def test_literalize(self):
        s = Symbol(1)
        self.assertEqual(s.literalize(), s)

    def test_simplify(self):
        s = Symbol(1)
        self.assertEqual(s.simplify(), s)

    def test_simplify_different_instances(self):
        s1 = Symbol(1)
        s2 = Symbol(1)
        self.assertEqual(s1.simplify(), s2.simplify())

    def test_equal_symbols(self):
        algebra = BooleanAlgebra()
        a = algebra.Symbol('a')
        a2 = algebra.Symbol('a')

        c = algebra.Symbol('b')
        d = algebra.Symbol('d')
        e = algebra.Symbol('e')

        # Test __eq__.
        self.assertTrue(a == a)
        self.assertTrue(a == a2)
        self.assertFalse(a == c)
        self.assertFalse(a2 == c)
        self.assertTrue(d == d)
        self.assertFalse(d == e)
        self.assertFalse(a == d)
        # Test __ne__.
        self.assertFalse(a != a)
        self.assertFalse(a != a2)
        self.assertTrue(a != c)
        self.assertTrue(a2 != c)

    def test_order(self):
        S = Symbol
        self.assertTrue(S('x') < S('y'))
        self.assertTrue(S('y') > S('x'))
        self.assertTrue(S(1) < S(2))
        self.assertTrue(S(2) > S(1))

    def test_printing(self):
        self.assertEqual('a', str(Symbol('a')))
        self.assertEqual('1', str(Symbol(1)))
        self.assertEqual("Symbol('a')", repr(Symbol('a')))
        self.assertEqual('Symbol(1)', repr(Symbol(1)))


class NOTTestCase(unittest.TestCase):

    def test_init(self):
        algebra = BooleanAlgebra()
        self.assertRaises(TypeError, algebra.NOT)
        self.assertRaises(TypeError, algebra.NOT, 'a', 'b')
        algebra.NOT(algebra.Symbol('a'))
        self.assertEqual(algebra.FALSE, (algebra.NOT(algebra.TRUE)).simplify())
        self.assertEqual(algebra.TRUE, (algebra.NOT(algebra.FALSE)).simplify())

    def test_isliteral(self):
        algebra = BooleanAlgebra()
        s = algebra.Symbol(1)
        self.assertTrue(algebra.NOT(s).isliteral)
        self.assertFalse(algebra.parse('~(a|b)').isliteral)

    def test_literals(self):
        algebra = BooleanAlgebra()
        a = algebra.Symbol('a')
        l = ~a
        self.assertTrue(l.isliteral)
        self.assertTrue(l in l.literals)
        self.assertEqual(len(l.literals), 1)

        l = algebra.parse('~(a&a)')
        self.assertFalse(l.isliteral)
        self.assertTrue(a in l.literals)
        self.assertEqual(len(l.literals), 1)

        l = algebra.parse('~(a&a)', simplify=True)
        self.assertTrue(l.isliteral)

    def test_literalize(self):
        parse = BooleanAlgebra().parse
        self.assertEqual(parse('~a').literalize(), parse('~a'))
        self.assertEqual(parse('~(a&b)').literalize(), parse('~a|~b'))
        self.assertEqual(parse('~(a|b)').literalize(), parse('~a&~b'))

    def test_simplify(self):
        algebra = BooleanAlgebra()
        a = algebra.Symbol('a')
        self.assertEqual(~a, ~a)
        assert algebra.Symbol('a') == algebra.Symbol('a')
        self.assertNotEqual(a, algebra.parse('~~a'))
        self.assertEqual(a, (~~a).simplify())
        self.assertEqual(~a, (~~ ~a).simplify())
        self.assertEqual(a, (~~ ~~a).simplify())
        self.assertEqual((~(a & a & a)).simplify(), (~(a & a & a)).simplify())
        self.assertEqual(a, algebra.parse('~~a', simplify=True))
        algebra2 = BooleanAlgebra()
        self.assertEqual(a, algebra2.parse('~~a', simplify=True))

    def test_cancel(self):
        algebra = BooleanAlgebra()
        a = algebra.Symbol('a')
        self.assertEqual(~a, (~a).cancel())
        self.assertEqual(a, algebra.parse('~~a').cancel())
        self.assertEqual(~a, algebra.parse('~~~a').cancel())
        self.assertEqual(a, algebra.parse('~~~~a').cancel())

    def test_demorgan(self):
        algebra = BooleanAlgebra()
        a = algebra.Symbol('a')
        b = algebra.Symbol('b')
        c = algebra.Symbol('c')
        self.assertEqual(algebra.parse('~(a&b)').demorgan(), ~a | ~b)
        self.assertEqual(algebra.parse('~(a|b|c)').demorgan(), algebra.parse('~a&~b&~c'))
        self.assertEqual(algebra.parse('~(~a&b)').demorgan(), a | ~b)
        self.assertEqual((~~(a&b|c)).demorgan(), a&b|c)
        self.assertEqual((~~~(a&b|c)).demorgan(), ~(a&b)&~c)
        self.assertEqual(algebra.parse('~'*10 + '(a&b|c)').demorgan(), a&b|c)
        self.assertEqual(algebra.parse('~'*11 + '(a&b|c)').demorgan(), (~(a&b|c)).demorgan())

    def test_order(self):
        algebra = BooleanAlgebra()
        x = algebra.Symbol(1)
        y = algebra.Symbol(2)
        self.assertTrue(x < ~x)
        self.assertTrue(~x > x)
        self.assertTrue(~x < y)
        self.assertTrue(y > ~x)

    def test_printing(self):
        algebra = BooleanAlgebra()
        a = algebra.Symbol('a')
        self.assertEqual(str(~a), '~a')
        self.assertEqual(repr(~a), "NOT(Symbol('a'))")
        expr = algebra.parse('~(a&a)')
        self.assertEqual(str(expr), '~(a&a)')
        self.assertEqual(repr(expr), "NOT(AND(Symbol('a'), Symbol('a')))")


class DualBaseTestCase(unittest.TestCase):

    maxDiff = None

    def test_init(self):
        if "__PEX_UNVENDORED__" in __import__("os").environ:
          from boolean.boolean import DualBase  # vendor:skip
        else:
          from pex.third_party.boolean.boolean import DualBase

        a, b, c = Symbol('a'), Symbol('b'), Symbol('c')
        t1 = DualBase(a, b)
        t2 = DualBase(a, b, c)
        t3 = DualBase(a, a)
        t4 = DualBase(a, b, c)

        self.assertRaises(TypeError, DualBase)
        for term in (t1, t2, t3, t4):
            self.assertTrue(isinstance(term, DualBase))

    def test_isliteral(self):
        if "__PEX_UNVENDORED__" in __import__("os").environ:
          from boolean.boolean import DualBase  # vendor:skip
        else:
          from pex.third_party.boolean.boolean import DualBase

        a, b, c = Symbol('a'), Symbol('b'), Symbol('c')
        t1 = DualBase(a, b)
        t2 = DualBase(a, b, c)

        self.assertFalse(t1.isliteral)
        self.assertFalse(t2.isliteral)

    def test_literals(self):
        if "__PEX_UNVENDORED__" in __import__("os").environ:
          from boolean.boolean import DualBase  # vendor:skip
        else:
          from pex.third_party.boolean.boolean import DualBase

        a, b, c = Symbol('a'), Symbol('b'), Symbol('c')
        t1 = DualBase(a, b)
        t2 = DualBase(a, b, c)
        t3 = DualBase(a, a)
        t4 = DualBase(a, b, c)

        for term in (t1, t2, t3, t4):
            self.assertTrue(a in term.literals)
        for term in (t1, t2, t4):
            self.assertTrue(b in term.literals)
        for term in (t2, t4):
            self.assertTrue(c in term.literals)

    def test_literalize(self):
        parse = BooleanAlgebra().parse
        self.assertEqual(parse('a|~(b|c)').literalize(), parse('a|(~b&~c)'))

    def test_annihilator(self):
        algebra = BooleanAlgebra()
        self.assertEqual(algebra.parse('a&a').annihilator, algebra.FALSE)
        self.assertEqual(algebra.parse('a|a').annihilator, algebra.TRUE)

    def test_identity(self):
        algebra = BooleanAlgebra()
        self.assertEqual(algebra.parse('a|b').identity, algebra.FALSE)
        self.assertEqual(algebra.parse('a&b').identity, algebra.TRUE)

    def test_dual(self):
        algebra = BooleanAlgebra()
        self.assertEqual(algebra.AND(algebra.Symbol('a'), algebra.Symbol('b')).dual, algebra.OR)
        self.assertEqual(algebra.OR(algebra.Symbol('a'), algebra.Symbol('b')).dual, algebra.AND)

        self.assertEqual(algebra.parse('a|b').dual, algebra.AND)
        self.assertEqual(algebra.parse('a&b').dual, algebra.OR)

    def test_simplify(self):
        algebra1 = BooleanAlgebra()
        algebra2 = BooleanAlgebra()
        a = algebra1.Symbol('a')
        b = algebra1.Symbol('b')
        c = algebra1.Symbol('c')

        _0 = algebra1.FALSE
        _1 = algebra1.TRUE
        # Idempotence
        self.assertEqual(a, (a & a).simplify())
        # Idempotence + Associativity
        self.assertEqual(a | b, (a | (a | b)).simplify())
        # Annihilation
        self.assertEqual(_0, (a & _0).simplify())
        self.assertEqual(_1, (a | _1).simplify())
        # Identity
        self.assertEqual(a, (a & _1).simplify())
        self.assertEqual(a, (a | _0).simplify())
        # Complementation
        self.assertEqual(_0, (a & ~a).simplify())
        self.assertEqual(_1, (a | ~a).simplify())
        # Absorption
        self.assertEqual(a, (a & (a | b)).simplify())
        self.assertEqual(a, (a | (a & b)).simplify())
        self.assertEqual(b & a, ((b & a) | (b & a & c)).simplify())

        # Elimination
        self.assertEqual(a, ((a & ~b) | (a & b)).simplify())

        # Commutativity + Non-Commutativity 
        sorted_expression = (b & b & a).simplify()
        unsorted_expression = (b & b & a).simplify(sort=False)
        self.assertEqual(sorted_expression, unsorted_expression)
        self.assertNotEqual(sorted_expression.pretty(), unsorted_expression.pretty())

        sorted_expression = (b | b | a).simplify()
        unsorted_expression = (b | b | a).simplify(sort=False)
        self.assertEqual(sorted_expression, unsorted_expression)
        self.assertNotEqual(sorted_expression.pretty(), unsorted_expression.pretty())

        expected = algebra1.parse('(a&b)|(b&c)|(a&c)')
        result = algebra1.parse('(~a&b&c) | (a&~b&c) | (a&b&~c) | (a&b&c)', simplify=True)
        self.assertEqual(expected, result)

        expected = algebra1.parse('(a&b)|(b&c)|(a&c)')
        result = algebra2.parse('(~a&b&c) | (a&~b&c) | (a&b&~c) | (a&b&c)', simplify=True)
        self.assertEqual(expected, result)

        expected = algebra1.parse('b&d')
        result = algebra1.parse('(a&b&c&d) | (b&d)', simplify=True)
        self.assertEqual(expected, result)

        expected = algebra1.parse('b&d')
        result = algebra2.parse('(a&b&c&d) | (b&d)', simplify=True)
        self.assertEqual(expected, result)

        expected = algebra1.parse('(~b&~d&a) | (~c&~d&b) | (a&c&d)', simplify=True)
        result = algebra1.parse('''(~a&b&~c&~d) | (a&~b&~c&~d) | (a&~b&c&~d) |
                          (a&~b&c&d) | (a&b&~c&~d) | (a&b&c&d)''', simplify=True)
        self.assertEqual(expected.pretty(), result.pretty())

        expected = algebra1.parse('(~b&~d&a) | (~c&~d&b) | (a&c&d)', simplify=True)
        result = algebra2.parse('''(~a&b&~c&~d) | (a&~b&~c&~d) | (a&~b&c&~d) |
                          (a&~b&c&d) | (a&b&~c&~d) | (a&b&c&d)''', simplify=True)
        self.assertEqual(expected.pretty(), result.pretty())

    @expectedFailure
    def test_parse_complex_expression_should_create_same_expression_as_python(self):
        algebra = BooleanAlgebra()
        a, b, c = algebra.symbols(*'abc')

        test_expression_str = '''(~a | ~b | ~c)'''
        parsed = algebra.parse(test_expression_str)
        test_expression = (~a | ~b | ~c)  # & ~d
        # print()
        # print('parsed')
        # print(parsed.pretty())
        # print('python')
        # print(test_expression.pretty())
        # we have a different behavior for expressions built from python expressions
        # vs. expression built from an object tree vs. expression built from a parse
        self.assertEqual(parsed.pretty(), test_expression.pretty())
        self.assertEqual(parsed, test_expression)

    @expectedFailure
    def test_simplify_complex_expression_parsed_with_simplify(self):
        # FIXME: THIS SHOULD NOT FAIL
        algebra = BooleanAlgebra()
        a = algebra.Symbol('a')
        b = algebra.Symbol('b')
        c = algebra.Symbol('c')
        d = algebra.Symbol('d')

        test_expression_str = '''
            (~a&~b&~c&~d) | (~a&~b&~c&d) | (~a&b&~c&~d) |
            (~a&b&c&d) | (~a&b&~c&d) | (~a&b&c&~d) |
            (a&~b&~c&d) | (~a&b&c&d) | (a&~b&c&d) | (a&b&c&d)
            '''

        parsed = algebra.parse(test_expression_str, simplify=True)

        test_expression = (
            (~a & ~b & ~c & ~d) | (~a & ~b & ~c & d) | (~a & b & ~c & ~d) |
            (~a & b & c & d) | (~a & b & ~c & d) | (~a & b & c & ~d) |
            (a & ~b & ~c & d) | (~a & b & c & d) | (a & ~b & c & d) | (a & b & c & d)
        ).simplify()

        # we have a different simplify behavior for expressions built from python expressions
        # vs. expression built from an object tree vs. expression built from a parse
        self.assertEqual(parsed.pretty(), test_expression.pretty())

    @expectedFailure
    def test_complex_expression_without_parens_parsed_or_built_in_python_should_be_identical(self):
        # FIXME: THIS SHOULD NOT FAIL
        algebra = BooleanAlgebra()
        a = algebra.Symbol('a')
        b = algebra.Symbol('b')
        c = algebra.Symbol('c')
        d = algebra.Symbol('d')

        test_expression_str = '''
            ~a&~b&~c&~d | ~a&~b&~c&d | ~a&b&~c&~d |
            ~a&b&c&d | ~a&b&~c&d | ~a&b&c&~d |
            a&~b&~c&d | ~a&b&c&d | a&~b&c&d | a&b&c&d
            '''

        parsed = algebra.parse(test_expression_str)

        test_expression = (
            ~a & ~b & ~c & ~d | ~a & ~b & ~c & d | ~a & b & ~c & ~d |
            ~ a & b & c & d | ~a & b & ~c & d | ~a & b & c & ~d |
            a & ~b & ~c & d | ~a & b & c & d | a & ~b & c & d | a & b & c & d
        )

        self.assertEqual(parsed.pretty(), test_expression.pretty())

    @expectedFailure
    def test_simplify_complex_expression_parsed_then_simplified(self):
        # FIXME: THIS SHOULD NOT FAIL

        algebra = BooleanAlgebra()
        a = algebra.Symbol('a')
        b = algebra.Symbol('b')
        c = algebra.Symbol('c')
        d = algebra.Symbol('d')
        parse = algebra.parse

        test_expression_str = ''.join('''
            (~a&~b&~c&~d) | (~a&~b&~c&d) | (~a&b&~c&~d) |
            (~a&b&c&d) | (~a&b&~c&d) | (~a&b&c&~d) |
            (a&~b&~c&d) | (~a&b&c&d) | (a&~b&c&d) | (a&b&c&d)
        '''.split())

        test_expression = (
            (~a & ~b & ~c & ~d) | (~a & ~b & ~c & d) | (~a & b & ~c & ~d) |
            (~a & b & c & d) | (~a & b & ~c & d) | (~a & b & c & ~d) |
            (a & ~b & ~c & d) | (~a & b & c & d) | (a & ~b & c & d) | (a & b & c & d)
        )

        parsed = parse(test_expression_str)
        self.assertEqual(test_expression_str, str(parsed))

        expected = (a & ~b & d) | (~a & b) | (~a & ~c) | (b & c & d)
        self.assertEqual(expected.pretty(), test_expression.simplify().pretty())

        parsed = parse(test_expression_str, simplify=True)

        # FIXME: THIS SHOULD NOT FAIL
        # we have a different simplify behavior for expressions built from python expressions
        # vs. expression built from an object tree vs. expression built from a parse
        self.assertEqual(expected.simplify().pretty(), parsed.simplify().pretty())

        expected_str = '(a&~b&d)|(~a&b)|(~a&~c)|(b&c&d)'
        self.assertEqual(expected_str, str(parsed))

        parsed2 = parse(test_expression_str)
        self.assertEqual(expected.pretty(), parsed2.simplify().pretty())

        self.assertEqual(expected_str, str(parsed2.simplify()))

        expected = algebra.OR(
            algebra.AND(
                algebra.NOT(algebra.Symbol('a')),
                algebra.NOT(algebra.Symbol('b')),
                algebra.NOT(algebra.Symbol('c')),
                algebra.NOT(algebra.Symbol('d'))
            ),
            algebra.AND(
                algebra.NOT(algebra.Symbol('a')),
                algebra.NOT(algebra.Symbol('b')),
                algebra.NOT(algebra.Symbol('c')),
                algebra.Symbol('d')
            ),
            algebra.AND(
                algebra.NOT(algebra.Symbol('a')),
                algebra.Symbol('b'),
                algebra.NOT(algebra.Symbol('c')),
                algebra.NOT(algebra.Symbol('d'))
            ),
            algebra.AND(
                algebra.NOT(algebra.Symbol('a')),
                algebra.Symbol('b'),
                algebra.Symbol('c'),
                algebra.Symbol('d')),
            algebra.AND(
                algebra.NOT(algebra.Symbol('a')),
                algebra.Symbol('b'),
                algebra.NOT(algebra.Symbol('c')),
                algebra.Symbol('d')
            ),
            algebra.AND(
                algebra.NOT(algebra.Symbol('a')),
                algebra.Symbol('b'),
                algebra.Symbol('c'),
                algebra.NOT(algebra.Symbol('d'))
            ),
            algebra.AND(
                algebra.Symbol('a'),
                algebra.NOT(algebra.Symbol('b')),
                algebra.NOT(algebra.Symbol('c')),
                algebra.Symbol('d')
            ),
            algebra.AND(
                algebra.NOT(algebra.Symbol('a')),
                algebra.Symbol('b'),
                algebra.Symbol('c'),
                algebra.Symbol('d')
            ),
            algebra.AND(
                algebra.Symbol('a'),
                algebra.NOT(algebra.Symbol('b')),
                algebra.Symbol('c'),
                algebra.Symbol('d')
            ),
            algebra.AND(
                algebra.Symbol('a'),
                algebra.Symbol('b'),
                algebra.Symbol('c'),
                algebra.Symbol('d')
            )
        )

        result = parse(test_expression_str)
        result = result.simplify()
        self.assertEqual(expected, result)

    def test_parse_invalid_nested_and_should_raise_a_proper_exception(self):
        algebra = BooleanAlgebra()
        expr = '''a (and b)'''

        with self.assertRaises(ParseError) as context:
            algebra.parse(expr)

            self.assertEqual(
                context.exception.error_code, PARSE_INVALID_NESTING
            )

    def test_subtract(self):
        parse = BooleanAlgebra().parse
        expr = parse('a&b&c')
        p1 = parse('b&d')
        p2 = parse('a&c')
        result = parse('b')
        self.assertEqual(expr.subtract(p1, simplify=True), expr)
        self.assertEqual(expr.subtract(p2, simplify=True), result)

    def test_flatten(self):
        parse = BooleanAlgebra().parse

        t1 = parse('a & (b&c)')
        t2 = parse('a&b&c')
        self.assertNotEqual(t1, t2)
        self.assertEqual(t1.flatten(), t2)

        t1 = parse('a | ((b&c) | (a&c)) | b')
        t2 = parse('a | (b&c) | (a&c) | b')
        self.assertNotEqual(t1, t2)
        self.assertEqual(t1.flatten(), t2)

    def test_distributive(self):
        algebra = BooleanAlgebra()
        a = algebra.Symbol('a')
        b = algebra.Symbol('b')
        c = algebra.Symbol('c')
        d = algebra.Symbol('d')
        e = algebra.Symbol('e')
        self.assertEqual((a & (b | c)).distributive(), (a & b) | (a & c))
        t1 = algebra.AND(a, (b | c), (d | e))
        t2 = algebra.OR(algebra.AND(a, b, d), algebra.AND(a, b, e), algebra.AND(a, c, d), algebra.AND(a, c, e))
        self.assertEqual(t1.distributive(), t2)

    def test_equal(self):
        if "__PEX_UNVENDORED__" in __import__("os").environ:
          from boolean.boolean import DualBase  # vendor:skip
        else:
          from pex.third_party.boolean.boolean import DualBase

        a, b, c = Symbol('a'), Symbol('b'), Symbol('c')
        t1 = DualBase(a, b)
        t1_2 = DualBase(b, a)

        t2 = DualBase(a, b, c)
        t2_2 = DualBase(b, c, a)

        # Test __eq__.
        self.assertTrue(t1 == t1)
        self.assertTrue(t1_2 == t1)
        self.assertTrue(t2_2 == t2)
        self.assertFalse(t1 == t2)
        self.assertFalse(t1 == 1)
        self.assertFalse(t1 is True)
        self.assertFalse(t1 is None)

        # Test __ne__.
        self.assertFalse(t1 != t1)
        self.assertFalse(t1_2 != t1)
        self.assertFalse(t2_2 != t2)
        self.assertTrue(t1 != t2)
        self.assertTrue(t1 != 1)
        self.assertTrue(t1 is not True)
        self.assertTrue(t1 is not None)

    def test_order(self):
        algebra = BooleanAlgebra()
        x, y, z = algebra.Symbol(1), algebra.Symbol(2), algebra.Symbol(3)
        self.assertTrue(algebra.AND(x, y) < algebra.AND(x, y, z))
        self.assertTrue(not algebra.AND(x, y) > algebra.AND(x, y, z))
        self.assertTrue(algebra.AND(x, y) < algebra.AND(x, z))
        self.assertTrue(not algebra.AND(x, y) > algebra.AND(x, z))
        self.assertTrue(algebra.AND(x, y) < algebra.AND(y, z))
        self.assertTrue(not algebra.AND(x, y) > algebra.AND(y, z))
        self.assertTrue(not algebra.AND(x, y) < algebra.AND(x, y))
        self.assertTrue(not algebra.AND(x, y) > algebra.AND(x, y))

    def test_printing(self):
        parse = BooleanAlgebra().parse
        self.assertEqual(str(parse('a&a')), 'a&a')
        self.assertEqual(repr(parse('a&a')), "AND(Symbol('a'), Symbol('a'))")
        self.assertEqual(str(parse('a|a')), 'a|a')
        self.assertEqual(repr(parse('a|a')), "OR(Symbol('a'), Symbol('a'))")
        self.assertEqual(str(parse('(a|b)&c')), '(a|b)&c')
        self.assertEqual(repr(parse('(a|b)&c')), "AND(OR(Symbol('a'), Symbol('b')), Symbol('c'))")


class OtherTestCase(unittest.TestCase):

    def test_class_order(self):
        # FIXME: this test is cryptic: what does it do?
        algebra = BooleanAlgebra()
        order = (
            (algebra.TRUE, algebra.FALSE),
            (algebra.Symbol('y'), algebra.Symbol('x')),
            (algebra.parse('x&y'),),
            (algebra.parse('x|y'),),
        )
        for i, tests in enumerate(order):
            for case1 in tests:
                for j in range(i + 1, len(order)):
                    for case2 in order[j]:

                        self.assertTrue(case1 < case2)
                        self.assertTrue(case2 > case1)

    def test_parse(self):
        algebra = BooleanAlgebra()
        a, b, c = algebra.Symbol('a'), algebra.Symbol('b'), algebra.Symbol('c')
        self.assertEqual(algebra.parse('0'), algebra.FALSE)
        self.assertEqual(algebra.parse('(0)'), algebra.FALSE)
        self.assertEqual(algebra.parse('1') , algebra.TRUE)
        self.assertEqual(algebra.parse('(1)'), algebra.TRUE)
        self.assertEqual(algebra.parse('a'), a)
        self.assertEqual(algebra.parse('(a)'), a)
        self.assertEqual(algebra.parse('(a)'), a)
        self.assertEqual(algebra.parse('~a'), algebra.parse('~(a)'))
        self.assertEqual(algebra.parse('~(a)'), algebra.parse('(~a)'))
        self.assertEqual(algebra.parse('~a'), ~a)
        self.assertEqual(algebra.parse('(~a)'), ~a)
        self.assertEqual(algebra.parse('~~a', simplify=True), (~~a).simplify())
        self.assertEqual(algebra.parse('a&b'), a & b)
        self.assertEqual(algebra.parse('~a&b'), ~a & b)
        self.assertEqual(algebra.parse('a&~b'), a & ~b)
        self.assertEqual(algebra.parse('a&b&c'), algebra.parse('a&b&c'))
        self.assertEqual(algebra.parse('a&b&c'), algebra.AND(a, b, c))
        self.assertEqual(algebra.parse('~a&~b&~c'), algebra.parse('~a&~b&~c'))
        self.assertEqual(algebra.parse('~a&~b&~c'), algebra.AND(~a, ~b, ~c))
        self.assertEqual(algebra.parse('a|b'), a | b)
        self.assertEqual(algebra.parse('~a|b'), ~a | b)
        self.assertEqual(algebra.parse('a|~b'), a | ~b)
        self.assertEqual(algebra.parse('a|b|c'), algebra.parse('a|b|c'))
        self.assertEqual(algebra.parse('a|b|c'), algebra.OR(a, b, c))
        self.assertEqual(algebra.parse('~a|~b|~c'), algebra.OR(~a, ~b, ~c))
        self.assertEqual(algebra.parse('(a|b)'), a | b)
        self.assertEqual(algebra.parse('a&(a|b)', simplify=True), (a & (a | b)).simplify())
        self.assertEqual(algebra.parse('a&(a|~b)', simplify=True), (a & (a | ~b)).simplify())
        self.assertEqual(algebra.parse('(a&b)|(b&((c|a)&(b|(c&a))))', simplify=True), ((a & b) | (b & ((c | a) & (b | (c & a))))).simplify())
        self.assertEqual(algebra.parse('(a&b)|(b&((c|a)&(b|(c&a))))', simplify=True), algebra.parse('a&b | b&(c|a)&(b|c&a)', simplify=True))

    def test_subs(self):
        algebra = BooleanAlgebra()
        a, b, c = algebra.Symbol('a'), algebra.Symbol('b'), algebra.Symbol('c')
        expr = a & b | c
        self.assertEqual(expr.subs({a: b}).simplify(), b | c)
        self.assertEqual(expr.subs({a: a}).simplify(), expr)
        self.assertEqual(expr.subs({a: b | c}).simplify(), algebra.parse('(b|c)&b|c').simplify())
        self.assertEqual(expr.subs({a & b: a}).simplify(), a | c)
        self.assertEqual(expr.subs({c: algebra.TRUE}).simplify(), algebra.TRUE)

    def test_subs_default(self):
        algebra = BooleanAlgebra()
        a, b, c = algebra.Symbol('a'), algebra.Symbol('b'), algebra.Symbol('c')
        expr = a & b | c
        self.assertEqual(expr.subs({}, default=algebra.TRUE).simplify(), algebra.TRUE)
        self.assertEqual(expr.subs({a: algebra.FALSE, c: algebra.FALSE}, default=algebra.TRUE).simplify(), algebra.FALSE)
        self.assertEqual(algebra.TRUE.subs({}, default=algebra.FALSE).simplify(), algebra.TRUE)
        self.assertEqual(algebra.FALSE.subs({}, default=algebra.TRUE).simplify(), algebra.FALSE)

    def test_normalize(self):
        algebra = BooleanAlgebra()

        expr = algebra.parse("a&b")
        self.assertEqual(algebra.dnf(expr), expr)
        self.assertEqual(algebra.cnf(expr), expr)

        expr = algebra.parse("a|b")
        self.assertEqual(algebra.dnf(expr), expr)
        self.assertEqual(algebra.cnf(expr), expr)

        expr = algebra.parse("(a&b)|(c&b)")
        result_dnf = algebra.parse("(a&b)|(b&c)")
        result_cnf = algebra.parse("b&(a|c)")
        self.assertEqual(algebra.dnf(expr), result_dnf)
        self.assertEqual(algebra.cnf(expr), result_cnf)

        expr = algebra.parse("(a|b)&(c|b)")
        result_dnf = algebra.parse("b|(a&c)")
        result_cnf = algebra.parse("(a|b)&(b|c)")
        self.assertEqual(algebra.dnf(expr), result_dnf)
        self.assertEqual(algebra.cnf(expr), result_cnf)

        expr = algebra.parse('((s|a)&(s|b)&(s|c)&(s|d)&(e|c|d))|(a&e&d)')
        result = algebra.normalize(expr, expr.AND)
        expected = algebra.parse('(a|s)&(b|e|s)&(c|d|e)&(c|e|s)&(d|s)')
        self.assertEqual(result, expected)

    def test_get_literals_return_all_literals_in_original_order(self):
        alg = BooleanAlgebra()
        exp = alg.parse('a and b or a and c')
        assert [alg.Symbol('a'), alg.Symbol('b'), alg.Symbol('a'), alg.Symbol('c')] == exp.get_literals()

    def test_get_symbols_return_all_symbols_in_original_order(self):
        alg = BooleanAlgebra()
        exp = alg.parse('a and b or True and a and c')
        assert [alg.Symbol('a'), alg.Symbol('b'), alg.Symbol('a'), alg.Symbol('c')] == exp.get_symbols()

    def test_literals_return_set_of_unique_literals(self):
        alg = BooleanAlgebra()
        exp = alg.parse('a and b or a and c')
        assert set([alg.Symbol('a'), alg.Symbol('b'), alg.Symbol('c')]) == exp.literals

    def test_literals_and_negation(self):
        alg = BooleanAlgebra()
        exp = alg.parse('a and not b and not not c')
        assert set([alg.Symbol('a'), alg.parse('not b'), alg.parse('not c')]) == exp.literals

    def test_symbols_and_negation(self):
        alg = BooleanAlgebra()
        exp = alg.parse('a and not b and not not c')
        assert set([alg.Symbol('a'), alg.Symbol('b'), alg.Symbol('c')]) == exp.symbols

    def test_objects_return_set_of_unique_Symbol_objs(self):
        alg = BooleanAlgebra()
        exp = alg.parse('a and b or a and c')
        assert set(['a', 'b', 'c']) == exp.objects


class BooleanBoolTestCase(unittest.TestCase):

    def test_bool(self):
        algebra = BooleanAlgebra()
        a, b, c = algebra.Symbol('a'), algebra.Symbol('b'), algebra.Symbol('c')
        expr = a & b | c
        self.assertRaises(TypeError, bool, expr.subs({a: algebra.TRUE}))
        self.assertRaises(TypeError, bool, expr.subs({b: algebra.TRUE}))
        self.assertRaises(TypeError, bool, expr.subs({c: algebra.TRUE}))
        self.assertRaises(TypeError, bool, expr.subs({a: algebra.TRUE, b: algebra.TRUE}))
        result = expr.subs({c: algebra.TRUE}, simplify=True)
        result = result.simplify()
        self.assertEqual(algebra.TRUE, result)

        result = expr.subs({a: algebra.TRUE, b: algebra.TRUE}, simplify=True)
        result = result.simplify()
        self.assertEqual(algebra.TRUE, result)


class CustomSymbolTestCase(unittest.TestCase):

    def test_custom_symbol(self):
        class CustomSymbol(Symbol):
            def __init__(self, name, value='value'):
                self.var = value
                super(CustomSymbol, self).__init__(name)
        try:
            CustomSymbol('a', value='This is A')
        except TypeError as e:
            self.fail(e)


if __name__ == '__main__':
    unittest.main()
