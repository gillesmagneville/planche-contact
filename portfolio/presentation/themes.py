# -*- coding: utf-8 -*-
"""
portfolio/presentation/themes.py - Palettes de couleurs pour les planches
contact/PDF, les portfolios et la galerie HTML (cahier des charges §4).

Comme layout_engine.py (géométrie) et captions.py (légendes), ce module
est INDÉPENDANT de tout moteur de rendu : il ne connaît ni PIL ni le HTML,
seulement des couleurs (chaînes hexadécimales "#rrggbb") - charge à
chaque générateur de sortie (contactsheet.py/pdfexport.py via PIL,
htmlgallery.py via CSS, la future prévisualisation GTK) de les appliquer
dans son propre format. Un seul jeu de palettes, jamais une redéfinition
divergente par renderer (cahier des charges §5).

Le thème "light" reproduit EXACTEMENT les couleurs actuellement codées en
dur dans ContactSheetGenerator (fond "white", texte "black", texte
secondaire "#555555" - voir _draw_header()/_draw_page_number()) : c'est
le thème par défaut (ThemeSettings.mode == "light"), pour que l'absence de
personnalisation de thème ne change rien au rendu actuel une fois ce
module câblé (étape ultérieure séparée - rien n'est encore branché dans
contactsheet.py/htmlgallery.py à ce stade, comme pour le reste de ce
package).

Le mode "system" (cahier des charges : "avec prise en charge de
prefers-color-scheme pour le HTML") n'est pas une palette en soi, mais une
STRATÉGIE de résolution : une planche JPEG/PDF est une image statique qui
ne peut pas réagir après coup au thème du système, donc resolve_theme()
exige un choix explicite (`prefer_dark`) fourni par l'appelant (l'interface
graphique peut interroger le thème GTK courant ; le CLI, sans contexte
graphique, passe la valeur par défaut `False`, donc "light" - cohérent
avec la règle de rétrocompatibilité). La galerie HTML, elle, n'a pas besoin
de choisir à la génération : son étape d'intégration (ultérieure) peut
récupérer les DEUX palettes via get_palette("light") et get_palette("dark")
et les placer de part et d'autre d'une media query CSS
`prefers-color-scheme`, pour un choix fait par le NAVIGATEUR du visiteur,
en toute cohérence avec les couleurs qu'utilisent déjà les planches/PDF.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .profile import ThemeSettings, ThemeCustomColors

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


@dataclass(frozen=True)
class Palette:
    """Un jeu de couleurs résolu, prêt à l'emploi par un renderer. Les
    valeurs sont toujours des chaînes hexadécimales valides ("#rrggbb" ou
    "#rgb") - jamais None, jamais un nom de couleur CSS/PIL ambigu entre
    bibliothèques."""
    background: str
    text: str
    text_secondary: str
    accent: str
    border: str


#: Palettes prédéfinies (cahier des charges §4.1). "light" doit rester
#: identique aux couleurs actuellement codées en dur dans contactsheet.py
#: - voir le docstring du module. "dark" et "neutral" sont de nouvelles
#: palettes, choisies pour rester lisibles (contraste suffisant
#: texte/fond) sans prétendre à une charte graphique figée - librement
#: ajustables par l'utilisateur via ThemeCustomColors.
THEME_PALETTES: dict[str, Palette] = {
    "light": Palette(
        background="#ffffff", text="#000000", text_secondary="#555555",
        accent="#0066cc", border="#dddddd",
    ),
    "dark": Palette(
        background="#1b1b1b", text="#f2f2f2", text_secondary="#a0a0a0",
        accent="#4da3ff", border="#3a3a3a",
    ),
    "neutral": Palette(
        background="#f0efe9", text="#2b2a28", text_secondary="#6e6a63",
        accent="#8a7968", border="#dcd8d0",
    ),
}

#: Palette de repli pour un mode inconnu (profil corrompu ou d'une
#: version future du projet introduisant un mode non reconnu ici) -
#: jamais une exception, toujours un rendu exploitable.
_FALLBACK_MODE = "light"


def get_palette(mode: str) -> Palette:
    """Palette prédéfinie pour un mode LITTÉRAL ("light"/"dark"/"neutral"
    uniquement - jamais "system", qui n'est pas une palette mais une
    stratégie de résolution, voir resolve_theme()). Un mode inconnu
    retombe silencieusement sur "light"."""
    return THEME_PALETTES.get(mode, THEME_PALETTES[_FALLBACK_MODE])


def _valid_hex(value: Optional[str]) -> Optional[str]:
    """Valide qu'une couleur personnalisée est un hexadécimal CSS
    bien formé - une vérification plus stricte que celle, purement
    syntaxique (juste "commence par #"), déjà faite par
    ThemeCustomColors.from_dict() lors du chargement JSON (qui ne
    connaît, lui, rien à la validité réelle d'une couleur). Une valeur
    invalide est ignorée (repli sur la couleur de la palette de base),
    jamais une exception ni une couleur cassée transmise à PIL ou au
    HTML."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate if _HEX_COLOR_RE.fullmatch(candidate) else None


def apply_custom_colors(base: Palette, custom: ThemeCustomColors) -> Palette:
    """Applique les couleurs personnalisées (cahier des charges §4.3,
    toutes optionnelles) par-dessus une palette de base, champ par champ -
    une couleur absente ou invalide laisse la couleur de la palette de
    base inchangée pour CE champ précis. `text_secondary` n'est pas
    personnalisable (ThemeCustomColors n'expose pas ce champ - réglage
    volontairement plus simple, cohérent avec son schéma JSON actuel)."""
    return Palette(
        background=_valid_hex(custom.background) or base.background,
        text=_valid_hex(custom.text) or base.text,
        text_secondary=base.text_secondary,
        accent=_valid_hex(custom.accent) or base.accent,
        border=_valid_hex(custom.border) or base.border,
    )


def resolve_theme(theme: ThemeSettings, *, prefer_dark: bool = False) -> Palette:
    """Résout un ThemeSettings complet (mode prédéfini + personnalisation
    éventuelle) en UNE palette concrète, prête à appliquer par un
    renderer produisant une sortie statique (planche JPEG, PDF, future
    prévisualisation GTK à un instant donné).

    `prefer_dark` ne sert qu'à résoudre le mode "system" (voir le
    docstring du module) : à défaut d'un contexte graphique capable de le
    déterminer, l'appelant doit passer explicitement sa meilleure
    estimation - la valeur par défaut `False` (donc "light") préserve le
    rendu actuel pour tout appelant qui ne se soucie pas du thème système
    (CLI notamment), cohérent avec la règle de rétrocompatibilité stricte
    du Profil.

    Ne lève jamais d'exception : un mode inconnu ou des couleurs
    personnalisées invalides retombent sur des valeurs par défaut
    exploitables."""
    mode = theme.mode
    if mode == "system":
        mode = "dark" if prefer_dark else "light"
    base = get_palette(mode)
    return apply_custom_colors(base, theme.custom)
