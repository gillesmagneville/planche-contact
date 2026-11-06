# -*- coding: utf-8 -*-
"""
Consistency of the translations (portfolio/locales/{fr,en,de,es}.py): a key
missing from a language does not crash the application (silent fallback of
portfolio.i18n._()), but would display text in the wrong language -
exactly the kind of defect that goes unnoticed as long as each language
is not tested by hand.
"""
import ast
import importlib
import logging
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
    sources = [REPO / "planche-contact-gtk.py", *sorted((REPO / "portfolio").rglob("*.py"))]
    sources = [s for s in sources if "locales" not in s.parts]
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


def test_translations_use_the_same_placeholders_in_every_language():
    """A placeholder missing in one language ({name} forgotten, or misspelt)
    would silently drop the value from the message (see portfolio.i18n._)."""
    placeholder = re.compile(r"\{(\w+)\}")
    reference = _strings("en")
    for lang in LANGS:
        for key, text in _strings(lang).items():
            assert sorted(placeholder.findall(text)) == sorted(placeholder.findall(reference[key])), (lang, key)


def test_no_log_message_for_the_user_bypasses_the_translations():
    """info/warning/error messages of the engine and of the CLI go through
    `_()`: they are read by the user (console, log file, log of the
    graphical interface). Only `debug` messages, meant for the developer,
    may be written directly (in English)."""
    offenders = []
    for source in sorted((REPO / "portfolio").rglob("*.py")):
        if "locales" in source.parts:
            continue
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in ("info", "warning", "error", "critical", "exception"):
                continue
            target = node.func.value
            is_logger = (isinstance(target, ast.Name) and target.id in ("logger", "logging")) or (
                isinstance(target, ast.Attribute) and target.attr == "logger"
            ) or (isinstance(target, ast.Call) and getattr(target.func, "attr", "") == "getLogger")
            if not is_logger or not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Call) and isinstance(first.func, ast.Name) and first.func.id == "_"):
                offenders.append(f"{source.relative_to(REPO)}:{node.lineno}")
    assert not offenders, f"log messages written directly instead of through _(): {offenders}"


@pytest.mark.parametrize("lang, fragment", [
    ("en", "not found"),
    ("fr", "introuvable"),
    ("es", "no encontrado"),
    ("de", "nicht gefunden"),
])
def test_a_missing_profile_is_reported_in_the_active_language(lang, fragment, tmp_path, caplog):
    from portfolio.i18n import set_language
    from portfolio.presentation import load_profile

    set_language(lang)
    with caplog.at_level(logging.WARNING):
        load_profile(tmp_path / "absent.json")
    messages = [r.getMessage() for r in caplog.records]
    assert any(fragment in m for m in messages), messages


@pytest.mark.parametrize("lang, fragment", [
    ("en", "not installed"),
    ("fr", "n'est pas installé"),
    ("es", "no está instalado"),
    ("de", "nicht installiert"),
])
def test_the_missing_rawpy_warning_is_in_the_active_language(lang, fragment, monkeypatch, caplog):
    from portfolio import rawloader
    from portfolio.i18n import set_language

    monkeypatch.setattr(rawloader, "RAWPY_AVAILABLE", False)
    set_language(lang)
    with caplog.at_level(logging.WARNING):
        rawloader.warn_if_rawpy_missing()
    assert any(fragment in r.getMessage() for r in caplog.records)


def test_no_rawpy_warning_when_rawpy_is_available(monkeypatch, caplog):
    from portfolio import rawloader

    monkeypatch.setattr(rawloader, "RAWPY_AVAILABLE", True)
    with caplog.at_level(logging.WARNING):
        rawloader.warn_if_rawpy_missing()
    assert not caplog.records


@pytest.mark.parametrize("lang, fragment", [
    ("en", "No contact sheet"),
    ("fr", "Aucune planche"),
    ("es", "No hay ninguna hoja"),
    ("de", "Keine Kontaktbögen"),
])
def test_the_pdf_export_without_sheets_warns_in_the_active_language(lang, fragment, tmp_path, caplog):
    from portfolio.i18n import set_language
    from portfolio.pdfexport import PDFExporter

    set_language(lang)
    with caplog.at_level(logging.WARNING):
        PDFExporter().create_pdf([], tmp_path / "out.pdf")
    assert any(fragment in r.getMessage() for r in caplog.records)
    assert not (tmp_path / "out.pdf").exists()


def test_the_thumbnail_workers_receive_the_active_language():
    """The workers are `spawn` processes, which start without the language
    of the parent: without this, their messages (a photo whose thumbnail
    fails) would come out in English whatever --language."""
    from portfolio import thumbnail
    from portfolio.i18n import get_language

    thumbnail._init_worker_logging(None, "de")
    assert get_language() == "de"
