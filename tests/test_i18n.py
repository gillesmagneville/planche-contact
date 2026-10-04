# -*- coding: utf-8 -*-
"""
Cohérence des traductions (portfolio/locales/{fr,en,de,es}.py) : une clé
absente d'une langue ne plante pas l'application (repli silencieux de
portfolio.i18n._()), mais afficherait un texte dans la mauvaise langue -
exactement le genre de défaut qui passe inaperçu tant qu'on ne teste pas
chaque langue à la main.
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
            f"{lang} : clés manquantes {sorted(reference - keys)}, "
            f"en trop {sorted(keys - reference)}"
        )


def test_every_literal_translation_key_used_in_the_code_exists():
    """Toute clé écrite en littéral dans un appel `_("...")` (interface
    graphique et moteur) doit exister. Les clés construites dynamiquement
    (f-strings) ne sont pas vues ici : voir les tests dédiés ci-dessous."""
    pattern = re.compile(r'\b_\(\s*"([a-z][a-z0-9_]*\.[A-Za-z0-9_.]+)"')
    sources = [REPO / "planche-contact-gtk.py", *sorted((REPO / "portfolio").glob("*.py"))]
    reference = set(_strings("fr"))
    missing = {}
    for source in sources:
        for key in pattern.findall(source.read_text(encoding="utf-8")):
            if key not in reference:
                missing.setdefault(key, []).append(source.name)
    assert not missing, f"clés de traduction utilisées mais jamais définies : {missing}"


@pytest.mark.parametrize("lang", LANGS)
def test_theme_menu_of_the_main_window_is_translated(lang):
    """Le menu « Thème » de la fenêtre principale construit ses options par
    f-string (`gen.theme_mode.{mode}`) : une option oubliée dans une langue
    ne serait détectée par aucun test statique."""
    strings = _strings(lang)
    for mode in THEME_MODES:
        assert strings.get(f"gen.theme_mode.{mode}"), (lang, mode)
    assert strings.get("gen.theme_label")
    assert strings.get("gen.theme_tooltip")
