# -*- coding: utf-8 -*-
"""
portfolio/presentation/ - Moteur commun de mise en page, légendes et thèmes.

Package introduit pour les évolutions "légendes EXIF personnalisables",
"modèles de mise en page personnalisables", "prévisualisation" et "thèmes
graphiques". Avant ce package, chaque générateur de sortie (contactsheet.py,
htmlgallery.py) réimplémentait sa propre logique de mise en page et ses
propres couleurs en dur - voir PROJECT_CONTEXT.md. Ce package centralise :

- profile.py        : modèle de données (Profil) + (dé)sérialisation JSON
- layout_engine.py  : calcul de géométrie (à venir)
- captions.py       : résolution des légendes EXIF (à venir)
- themes.py         : palettes de couleurs (à venir)

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
)
from .layout_engine import (
    PageLayout,
    CellLayout,
    compute_page_layout,
    compute_effective_per_page,
    canvas_size_px,
    mm_to_px,
)

__all__ = [
    "Profile",
    "LayoutSettings",
    "CaptionSettings",
    "ThemeSettings",
    "ThemeCustomColors",
    "default_profile",
    "load_profile",
    "save_profile",
    "PageLayout",
    "CellLayout",
    "compute_page_layout",
    "compute_effective_per_page",
    "canvas_size_px",
    "mm_to_px",
]
