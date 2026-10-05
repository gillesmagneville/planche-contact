# -*- coding: utf-8 -*-
"""
portfolio/presentation/ - Moteur commun de mise en page, légendes et thèmes.

Package introduit pour les évolutions "légendes EXIF personnalisables",
"modèles de mise en page personnalisables", "prévisualisation" et "thèmes
graphiques". Avant ce package, chaque générateur de sortie (contactsheet.py,
htmlgallery.py) réimplémentait sa propre logique de mise en page et ses
propres couleurs en dur - voir PROJECT_CONTEXT.md. Ce package centralise :

- profile.py        : modèle de données (Profil) + (dé)sérialisation JSON
- layout_engine.py  : calcul de géométrie
- captions.py       : résolution des légendes EXIF (formatage - voir
                      portfolio.utils.get_exif_metadata() pour l'extraction)
- themes.py         : palettes de couleurs

Règle générale, valable pour tout le package : l'ABSENCE de profil, ou un
profil partiel/invalide, ne doit jamais changer le comportement actuel de
l'application ni lever d'exception - voir profile.default_profile().
"""

from .profile import (
    Profile,
    LayoutSettings,
    CaptionSettings,
    ThemeSettings,
    ThemeCustomColors,
    default_profile,
    load_profile,
    save_profile,
    LAYOUT_TEMPLATES,
    FIT_MODES,
    PAGE_FORMATS,
    ORIENTATIONS,
    HEADER_POSITIONS,
    CAPTION_POSITIONS,
    CAPTION_ALIGNMENTS,
    CAPTION_FIELDS,
    THEME_MODES,
)
from .layout_engine import (
    PageLayout,
    CellLayout,
    compute_page_layout,
    compute_effective_per_page,
    canvas_size_px,
    mm_to_px,
    pt_to_px,
    CAPTION_LINE_SPACING_PX,
    CAPTION_PHOTO_GAP_PX,
    FOOTER_PAGE_NUMBER_OFFSET_PX,
    FOOTER_CREDIT_OFFSET_PX,
    FOOTER_LICENSE_OFFSET_PX,
    FOOTER_RESERVED_PX,
)
from .captions import resolve_caption_lines, resolve_caption_parts, layout_caption_lines
from .themes import Palette, THEME_PALETTES, get_palette, resolve_theme, apply_custom_colors

__all__ = [
    "Profile",
    "LayoutSettings",
    "CaptionSettings",
    "ThemeSettings",
    "ThemeCustomColors",
    "default_profile",
    "load_profile",
    "save_profile",
    "LAYOUT_TEMPLATES",
    "FIT_MODES",
    "PAGE_FORMATS",
    "ORIENTATIONS",
    "HEADER_POSITIONS",
    "CAPTION_POSITIONS",
    "CAPTION_ALIGNMENTS",
    "CAPTION_FIELDS",
    "THEME_MODES",
    "PageLayout",
    "CellLayout",
    "compute_page_layout",
    "compute_effective_per_page",
    "canvas_size_px",
    "mm_to_px",
    "pt_to_px",
    "CAPTION_LINE_SPACING_PX",
    "CAPTION_PHOTO_GAP_PX",
    "FOOTER_PAGE_NUMBER_OFFSET_PX",
    "FOOTER_CREDIT_OFFSET_PX",
    "FOOTER_LICENSE_OFFSET_PX",
    "FOOTER_RESERVED_PX",
    "resolve_caption_lines",
    "resolve_caption_parts",
    "layout_caption_lines",
    "Palette",
    "THEME_PALETTES",
    "get_palette",
    "resolve_theme",
    "apply_custom_colors",
]
