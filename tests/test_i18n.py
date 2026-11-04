# -*- coding: utf-8 -*-
"""
Consistency of the translations (portfolio/locales/{fr,en,de,es}.py): a key
missing from a language does not crash the application (silent fallback of
portfolio.i18n._()), but would display text in the wrong language -
exactly the kind of defect that goes unnoticed as long as each language
is not tested by hand.
"""
import importlib
import re
from pathlib import Path

import pytest

from portfolio.presentation import THEME_MODES

LANGS = ("fr", "en", "de", "es")
REPO = Path(__file__).resolve().parent.parent


def _strings(lang):
    return importlib.import_module(f"portfolio.locales.{lang}").STRINGS


def test_all_locales_define_exactly_the_same_keys():
    reference = set(_strings("fr"))
    for lang in LANGS:
        keys = set(_strings(lang))
        assert keys == reference, (
            f"{lang}: missing keys {sorted(reference - keys)}, "
            f"extra {sorted(keys - reference)}"
        )


def test_every_literal_translation_key_used_in_the_code_exists():
    """Every key written as a literal in a `_("...")` call (graphical
    interface and engine) must exist. Dynamically built keys (f-strings)
    are not seen here: see the dedicated tests below."""
    pattern = re.compile(r'\b_\(\s*"([a-z][a-z0-9_]*\.[A-Za-z0-9_.]+)"')
    sources = [REPO / "planche-contact-gtk.py", *sorted((REPO / "portfolio").glob("*.py"))]
    reference = set(_strings("fr"))
    missing = {}
    for source in sources:
        for key in pattern.findall(source.read_text(encoding="utf-8")):
            if key not in reference:
                missing.setdefault(key, []).append(source.name)
    assert not missing, f"translation keys used but never defined: {missing}"


@pytest.mark.parametrize("lang", LANGS)
def test_theme_menu_of_the_main_window_is_translated(lang):
    """The main window's "Theme" menu builds its options with an f-string
    (`gen.theme_mode.{mode}`): an option forgotten in one language would be
    caught by no static test."""
    strings = _strings(lang)
    for mode in THEME_MODES:
        assert strings.get(f"gen.theme_mode.{mode}"), (lang, mode)
    assert strings.get("gen.theme_label")
    assert strings.get("gen.theme_tooltip")
