# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pex.translator import ChainedTranslator, Translator, TranslatorBase

try:
  import mock
except ImportError:
  from unittest import mock


def test_info_is_passed_to_chained_translators():
  translator = mock.MagicMock(spec=TranslatorBase)

  t = ChainedTranslator(translator)
  t.translate("fake_package", "fake_into")

  translator.translate.assert_called_with("fake_package", into="fake_into")


def test_chained_translator_short_circuit_translate():
  initial_empty_translator = mock.MagicMock(spec=TranslatorBase)
  initial_empty_translator.translate.return_value = None
  translator_with_value = mock.MagicMock(spec=TranslatorBase)
  translator_with_value.translate.return_value = "fake_success"
  translator_after_value = mock.MagicMock(spec=TranslatorBase)

  t = ChainedTranslator(initial_empty_translator, translator_with_value, translator_after_value)
  result = t.translate("fake_package", "fake_into")

  assert result == "fake_success"
  assert initial_empty_translator.translate.called
  assert translator_with_value.translate.called
  assert not translator_after_value.translate.called


def test_chained_translator_repr():
  assert str(Translator.default()) == (
      'ChainedTranslator(WheelTranslator, EggTranslator, SourceTranslator)')
