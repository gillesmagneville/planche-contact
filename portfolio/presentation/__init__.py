# -*- coding: utf-8 -*-
"""
portfolio/presentation/ - Common engine for layout, captions and themes.

Package introduced for the "customisable EXIF captions", "customisable
layout templates", "preview" and "graphic themes" enhancements. Before
this package, each output generator (contactsheet.py, htmlgallery.py)
reimplemented its own layout logic and its own hard-coded colours - see
PROJECT_CONTEXT.md. This package centralises:

- profile.py        : data model (Profile) + JSON (de)serialisation
- layout_engine.py  : geometry computation
- captions.py       : resolution of EXIF captions (formatting - see
                      portfolio.utils.get_exif_metadata() for extraction)
- themes.py         : colour palettes

General rule, valid for the whole package: the ABSENCE of a profile, or
a partial/invalid profile, must never change the application's current
behaviour nor raise an exception - see profile.default_profile().
"""

from .profile import (
    Profile,
    LayoutSettings,
    CaptionSettings,
    ThemeSettings,
    ThemeCustomColors,
    default_profile,
    interface_default_profile,
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
    "interface_default_profile",
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
