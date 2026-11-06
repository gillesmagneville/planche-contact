# -*- coding: utf-8 -*-
"""Internationalisation of the interface (planche-contact-gtk.py).

Deliberately a simple Python dictionary per language (portfolio/locales/)
rather than gettext/.po/.mo: no compilation step, no extra dependency to
package in the .deb or the Windows installer - a choice consistent with
the rest of the project (see PROJECT_CONTEXT.md, §5).

These dictionaries serve the graphical interface (planche-contact-gtk.py)
and its dialogs, the messages of the CLI (portfolio/portfolio.py) and of the
engine (the log), the text drawn on the sheets and the generated HTML
gallery. The manual is one file per language (docs/). Only the messages
meant for the developer (logger.debug) stay in English, untranslated.
"""
import locale
import logging

from .locales import en, fr, de, es

logger = logging.getLogger(__name__)

# Display order in the language selector of the "About" tab.
AVAILABLE_LANGUAGES = ["system", "en", "fr", "de", "es"]

# "en" MUST remain complete (same keys as fr.py): it is the fallback
# language used when the detected system language has no translation.
_ALL_STRINGS = {
    "en": en.STRINGS,
    "fr": fr.STRINGS,
    "de": de.STRINGS,
    "es": es.STRINGS,
}

_FALLBACK_LANGUAGE = "en"
_current_language = _FALLBACK_LANGUAGE


def detect_system_language():
    """Returns the two-letter language code detected from the system
    settings (e.g. "fr", "de", "ja"...), or None if detection fails
    completely."""
    try:
        system_locale, _encoding = locale.getlocale()
    except Exception:
        system_locale = None

    if not system_locale or system_locale in ("C", "POSIX"):
        try:
            system_locale = locale.getdefaultlocale()[0]
        except Exception:
            system_locale = None

    if not system_locale:
        return None

    # "fr_FR", "fr_FR.UTF-8", "de-DE" -> "fr", "de"
    return system_locale.replace("-", "_").split("_")[0].lower()


def resolve_language(preference):
    """Determines the language to actually use from the saved preference
    ("system", "en", "fr", "de" or "es").

    Returns a tuple (active_language, unsupported_detected_code):
    - If `preference` is an explicit supported language (not "system"), it
      is used directly; second element always None.
    - If `preference` is "system" and the detected language is supported,
      it is used; second element None.
    - If `preference` is "system" but the detected language is NOT supported
      (or could not be detected), we fall back to English; the second
      element then holds the detected code (or "?" if detection failed
      completely), and it is up to the caller to display a warning (see
      lang.fallback_warning_* in the language files) - the user must know
      that this is not their language.
    """
    if preference != "system":
        if preference in _ALL_STRINGS:
            return preference, None
        # Saved preference invalid (corrupted config file/older
        # version): same behaviour as "system".
        preference = "system"

    detected = detect_system_language()
    if detected in _ALL_STRINGS:
        return detected, None

    return _FALLBACK_LANGUAGE, (detected or "?")


def set_language(preference):
    """Activates the language to be used by _() for the rest of the process.
    Returns the same tuple as resolve_language(), so that the caller
    (the GTK application) knows whether it must display the fallback warning."""
    global _current_language
    language, unsupported_detected = resolve_language(preference)
    _current_language = language
    return language, unsupported_detected


def get_language():
    """Currently active language (never "system" - always already
    resolved by set_language() to a concrete code)."""
    return _current_language


def _(key, **kwargs):
    """Translates `key` into the currently active language. Falls back to
    English if the key is missing in that language (incomplete translation
    file), then to the key itself as a last resort (so the interface never
    crashes on a missing translation - an ugly fallback text is preferable
    to a crash)."""
    strings = _ALL_STRINGS.get(_current_language, _ALL_STRINGS[_FALLBACK_LANGUAGE])
    text = strings.get(key)
    if text is None:
        text = _ALL_STRINGS[_FALLBACK_LANGUAGE].get(key, key)
        logger.debug(f"Missing translation key in '{_current_language}': {key}")
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
