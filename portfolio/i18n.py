# -*- coding: utf-8 -*-
"""Internationalisation de l'interface (planche-contact-gtk.py).

Volontairement un simple dictionnaire Python par langue (portfolio/locales/)
plutôt que gettext/.po/.mo : pas d'étape de compilation, pas de dépendance
supplémentaire à empaqueter dans le .deb ou l'installeur Windows - un choix
cohérent avec le reste du projet (voir PROJECT_CONTEXT.md, §5).

Ce module ne traduit QUE l'interface graphique (planche-contact-gtk.py) et
la fenêtre de dialogue qu'elle affiche. Le CLI (portfolio/portfolio.py), la
galerie HTML générée et le manuel restent en français pour l'instant (voir
CHANGELOG.md - portée volontairement limitée dans un premier temps).
"""
import locale
import logging

from .locales import en, fr, de, es

logger = logging.getLogger(__name__)

# Ordre d'affichage dans le sélecteur de langue de l'onglet "À propos".
AVAILABLE_LANGUAGES = ["system", "en", "fr", "de", "es"]

# "en" DOIT rester complet (mêmes clés que fr.py) : c'est la langue de
# repli utilisée quand la langue système détectée n'a pas de traduction.
_ALL_STRINGS = {
    "en": en.STRINGS,
    "fr": fr.STRINGS,
    "de": de.STRINGS,
    "es": es.STRINGS,
}

_FALLBACK_LANGUAGE = "en"
_current_language = _FALLBACK_LANGUAGE


def detect_system_language():
    """Renvoie le code de langue à deux lettres détecté depuis les
    paramètres système (ex: "fr", "de", "ja"...), ou None si la détection
    échoue complètement."""
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
    """Détermine la langue à réellement utiliser à partir de la préférence
    enregistrée ("system", "en", "fr", "de" ou "es").

    Renvoie un tuple (langue_active, code_detecte_non_supporte) :
    - Si `preference` est une langue supportée explicite (pas "system"),
      elle est utilisée directement ; second élément toujours None.
    - Si `preference` vaut "system" et que la langue détectée est
      supportée, elle est utilisée ; second élément None.
    - Si `preference` vaut "system" mais que la langue détectée n'est PAS
      supportée (ou n'a pas pu être détectée), on retombe sur l'anglais ;
      le second élément contient alors le code détecté (ou "?" si la
      détection a complètement échoué), à charge de l'appelant d'afficher
      un avertissement (voir lang.fallback_warning_* dans les fichiers de
      langue) - l'utilisateur doit savoir que ce n'est pas sa langue.
    """
    if preference != "system":
        if preference in _ALL_STRINGS:
            return preference, None
        # Préférence enregistrée invalide (fichier de config corrompu/
        # ancienne version) : comportement identique à "system".
        preference = "system"

    detected = detect_system_language()
    if detected in _ALL_STRINGS:
        return detected, None

    return _FALLBACK_LANGUAGE, (detected or "?")


def set_language(preference):
    """Active la langue à utiliser par _() pour le reste du processus.
    Renvoie le même tuple que resolve_language(), pour que l'appelant
    (l'application GTK) sache s'il doit afficher l'avertissement de repli."""
    global _current_language
    language, unsupported_detected = resolve_language(preference)
    _current_language = language
    return language, unsupported_detected


def get_language():
    """Langue actuellement active (jamais "system" - toujours déjà
    résolue par set_language() vers un code concret)."""
    return _current_language


def _(key, **kwargs):
    """Traduit `key` dans la langue actuellement active. Repli sur
    l'anglais si la clé manque dans cette langue (fichier de traduction
    incomplet), puis sur la clé elle-même en tout dernier recours (pour ne
    jamais faire planter l'interface sur une traduction manquante - un
    texte de repli moche reste préférable à un crash)."""
    strings = _ALL_STRINGS.get(_current_language, _ALL_STRINGS[_FALLBACK_LANGUAGE])
    text = strings.get(key)
    if text is None:
        text = _ALL_STRINGS[_FALLBACK_LANGUAGE].get(key, key)
        logger.debug(f"Clé de traduction manquante en '{_current_language}' : {key}")
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
