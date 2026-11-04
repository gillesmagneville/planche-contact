# -*- coding: utf-8 -*-
"""
portfolio/presentation/themes.py - Colour palettes for the contact
sheets/PDF, the portfolios and the HTML gallery (specification §4).

Like layout_engine.py (geometry) and captions.py (captions), this module
is INDEPENDENT of any rendering engine: it knows neither PIL nor HTML,
only colours (hexadecimal "#rrggbb" strings) - it is up to each output
generator (contactsheet.py/pdfexport.py via PIL, htmlgallery.py via CSS,
the future GTK preview) to apply them in its own format. A single set of
palettes, never a divergent redefinition per renderer (specification §5).

The "light" theme reproduces EXACTLY the colours currently hard-coded in
ContactSheetGenerator ("white" background, "black" text, "#555555"
secondary text - see _draw_header()/_draw_page_number()): it is the
default theme (ThemeSettings.mode == "light"), so that the absence of
theme customisation changes nothing in the current rendering once this
module is wired in (a separate later step - nothing is hooked up yet in
contactsheet.py/htmlgallery.py at this stage, as for the rest of this
package).

The "system" mode (specification: "with support for prefers-color-scheme
for the HTML") is not a palette in itself, but a resolution STRATEGY: a
JPEG/PDF sheet is a static image that cannot react afterwards to the
system theme, so resolve_theme() requires an explicit choice
(`prefer_dark`) supplied by the caller (the graphical interface can query
the current GTK theme; the CLI, with no graphical context, passes the
default value `False`, hence "light" - consistent with the backward
compatibility rule). The HTML gallery, for its part, does not need to
choose at generation time: its integration step (later) can fetch BOTH
palettes via get_palette("light") and get_palette("dark") and place them
on either side of a `prefers-color-scheme` CSS media query, for a choice
made by the visitor's BROWSER, in full consistency with the colours the
sheets/PDF already use.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .profile import ThemeSettings, ThemeCustomColors

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


@dataclass(frozen=True)
class Palette:
    """A resolved set of colours, ready for use by a renderer. The values
    are always valid hexadecimal strings ("#rrggbb" or "#rgb") - never None,
    never a CSS/PIL colour name that is ambiguous between libraries."""
    background: str
    text: str
    text_secondary: str
    accent: str
    border: str


#: Preset palettes (specification §4.1). "light" must stay identical to
#: the colours currently hard-coded in contactsheet.py - see the module
#: docstring. "dark" and "neutral" are new palettes, chosen to stay
#: readable (sufficient text/background contrast) without claiming to be
#: a fixed visual identity - freely adjustable by the user via
#: ThemeCustomColors.
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

#: Fallback palette for an unknown mode (corrupted profile or one from a
#: future version of the project introducing a mode not recognised here)
#: - never an exception, always a usable rendering.
_FALLBACK_MODE = "light"


def get_palette(mode: str) -> Palette:
    """Preset palette for a LITERAL mode ("light"/"dark"/"neutral" only -
    never "system", which is not a palette but a resolution strategy, see
    resolve_theme()). An unknown mode silently falls back to "light"."""
    return THEME_PALETTES.get(mode, THEME_PALETTES[_FALLBACK_MODE])


def _valid_hex(value: Optional[str]) -> Optional[str]:
    """Validates that a custom colour is a well-formed CSS hexadecimal - a
    stricter check than the purely syntactic one (just "starts with #")
    already done by ThemeCustomColors.from_dict() when loading the JSON
    (which knows nothing about the actual validity of a colour). An invalid
    value is ignored (fallback to the base palette's colour), never an
    exception nor a broken colour passed on to PIL or the HTML."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate if _HEX_COLOR_RE.fullmatch(candidate) else None


def apply_custom_colors(base: Palette, custom: ThemeCustomColors) -> Palette:
    """Applies the custom colours (specification §4.3, all optional) on top
    of a base palette, field by field - a missing or invalid colour leaves
    the base palette's colour unchanged for THAT particular field.
    `text_secondary` is not customisable (ThemeCustomColors does not expose
    this field - a deliberately simpler setting, consistent with its current
    JSON schema)."""
    return Palette(
        background=_valid_hex(custom.background) or base.background,
        text=_valid_hex(custom.text) or base.text,
        text_secondary=base.text_secondary,
        accent=_valid_hex(custom.accent) or base.accent,
        border=_valid_hex(custom.border) or base.border,
    )


def resolve_theme(theme: ThemeSettings, *, prefer_dark: bool = False) -> Palette:
    """Resolves a complete ThemeSettings (preset mode + possible
    customisation) into ONE concrete palette, ready to be applied by a
    renderer producing a static output (JPEG sheet, PDF, future GTK preview
    at a given instant).

    `prefer_dark` only serves to resolve the "system" mode (see the module
    docstring): lacking a graphical context able to determine it, the caller
    must explicitly pass its best estimate - the default value `False`
    (hence "light") preserves the current rendering for any caller that does
    not care about the system theme (the CLI notably), consistent with the
    Profile's strict backward-compatibility rule.

    Never raises an exception: an unknown mode or invalid custom colours
    fall back to usable default values."""
    mode = theme.mode
    if mode == "system":
        mode = "dark" if prefer_dark else "light"
    base = get_palette(mode)
    return apply_custom_colors(base, theme.custom)
