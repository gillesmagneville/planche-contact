# -*- coding: utf-8 -*-
"""
portfolio/presentation/profile.py - "Profile" data model (layout +
captions + theme) and its JSON (de)serialisation.

A Profile groups all the settings of the captions/layout templates/themes
enhancements (specification §2, §4.4):

- LayoutSettings  : layout template, grid, margins, page format...
- CaptionSettings : displayed caption fields, order, format, font...
- ThemeSettings   : preset theme + colour customisation.

A Profile can be saved by the user as a reusable JSON file and reloaded
later (graphical interface), or pointed to directly on the command line
(--profile file.json).

STRICT backward-compatibility rule (specification §2, §4.4, §8): the
total absence of a profile must produce a rendering strictly identical to
the application's current behaviour (before these features). Each
default value below has therefore been chosen to match EXACTLY what is
hard-coded today in contactsheet.py (white background, black text, no
per-photo caption, grid by searching for the best number of columns,
12 mm margin, 5 mm spacing) and htmlgallery.py (no per-photo caption,
current light palette). A missing or invalid field in a loaded JSON
silently falls back to that same default value - never an exception,
never a generation interrupted for a profile file that is corrupted or
produced by an earlier version of the project that does not yet know
this or that field.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------

#: Layout templates (specification §2). "grid" corresponds to the only
#: algorithm existing today in contactsheet.py (search for the number of
#: columns maximising the thumbnail size); the other four are new
#: strategies of the future layout_engine.py.
LAYOUT_TEMPLATES = ("grid", "landscape", "portrait", "large_thumbs", "free")

#: How a photo fits its cell (specification §2).
FIT_MODES = ("contain", "cover")

#: Supported page formats - must stay in sync with
#: ContactSheetGenerator._get_canvas_size() (contactsheet.py).
PAGE_FORMATS = ("A5", "A4", "A3", "A2", "Letter")

ORIENTATIONS = ("portrait", "landscape")

#: Possible positions for the title/author in the sheet header.
HEADER_POSITIONS = ("top_left", "top_center", "top_right", "none")

#: Possible positions for a photo's caption relative to the photo.
CAPTION_POSITIONS = ("below", "above", "right", "none")

#: Alignment of the caption text.
CAPTION_ALIGNMENTS = ("left", "center", "right")

#: Available caption fields (specification §1). The actual display
#: order chosen by the user lives in CaptionSettings.fields, not here -
#: this tuple only serves to validate that a key is recognised.
#: "gps" is deliberately a field like any other here: it is
#: CaptionSettings.show_gps that acts as the explicit privacy switch,
#: see below.
CAPTION_FIELDS = (
    "filename", "datetime", "camera", "lens", "focal_length", "focal_35mm",
    "aperture", "shutter_speed", "iso", "dimensions", "gps",
)

#: Preset themes (specification §4.1). "light" corresponds to the
#: currently hard-coded colours (white background, black text, grey
#: #555555 for secondary text) - it is the default theme, so as to change
#: nothing visually as long as no theme is explicitly chosen.
THEME_MODES = ("light", "dark", "neutral", "system")


def _coerce(value: Any, expected_type: type, default: Any, field_name: str) -> Any:
    """Returns `value` if its type matches `expected_type`, otherwise
    `default` (with a log message) - never an exception. `bool` is excluded
    from Python's implicit int/float coercion (a bool is also an int) to
    prevent a value such as `true` from being accepted where a number is
    expected, or vice versa."""
    if expected_type is float and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, expected_type) and not (expected_type in (int, float) and isinstance(value, bool)):
        return value
    if value is not None:
        logger.debug(f"Profil : valeur invalide pour '{field_name}' ({value!r}), valeur par défaut utilisée.")
    return default


def _coerce_choice(value: Any, choices: tuple, default: str, field_name: str) -> str:
    if isinstance(value, str) and value in choices:
        return value
    if value is not None:
        logger.debug(
            f"Profil : valeur '{value!r}' non reconnue pour '{field_name}' "
            f"(attendu parmi {choices}), valeur par défaut '{default}' utilisée."
        )
    return default


def _coerce_optional_int(value: Any, default: Optional[int], field_name: str) -> Optional[int]:
    if value is None:
        return default
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    logger.debug(f"Profil : entier positif attendu pour '{field_name}' ({value!r}), ignoré.")
    return default


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

@dataclass
class LayoutSettings:
    #: Layout template - see LAYOUT_TEMPLATES.
    template: str = "grid"
    #: Number of columns/rows imposed by the user ("free" template
    #: notably) - None lets the layout engine determine them
    #: automatically, as today.
    columns: Optional[int] = None
    rows: Optional[int] = None
    #: Number of photos per page - takes over the historical internal name
    #: "num_per_sheet" of Config, but now lives here.
    per_page: int = 12
    margin_mm: float = 12.0
    spacing_mm: float = 5.0
    page_format: str = "A4"
    orientation: str = "portrait"
    fit_mode: str = "contain"
    title_position: str = "top_center"
    author_position: str = "top_center"
    page_numbering: bool = True
    #: "none" = no caption under the photos - current behaviour.
    caption_position: str = "none"
    caption_area_mm: float = 8.0

    @classmethod
    def from_dict(cls, data: dict) -> "LayoutSettings":
        d = cls()
        if not isinstance(data, dict):
            return d
        return cls(
            template=_coerce_choice(data.get("template"), LAYOUT_TEMPLATES, d.template, "layout.template"),
            columns=_coerce_optional_int(data.get("columns"), d.columns, "layout.columns"),
            rows=_coerce_optional_int(data.get("rows"), d.rows, "layout.rows"),
            per_page=_coerce_optional_int(data.get("per_page"), d.per_page, "layout.per_page") or d.per_page,
            margin_mm=_coerce(data.get("margin_mm"), float, d.margin_mm, "layout.margin_mm"),
            spacing_mm=_coerce(data.get("spacing_mm"), float, d.spacing_mm, "layout.spacing_mm"),
            page_format=_coerce_choice(data.get("page_format"), PAGE_FORMATS, d.page_format, "layout.page_format"),
            orientation=_coerce_choice(data.get("orientation"), ORIENTATIONS, d.orientation, "layout.orientation"),
            fit_mode=_coerce_choice(data.get("fit_mode"), FIT_MODES, d.fit_mode, "layout.fit_mode"),
            title_position=_coerce_choice(data.get("title_position"), HEADER_POSITIONS, d.title_position, "layout.title_position"),
            author_position=_coerce_choice(data.get("author_position"), HEADER_POSITIONS, d.author_position, "layout.author_position"),
            page_numbering=_coerce(data.get("page_numbering"), bool, d.page_numbering, "layout.page_numbering"),
            caption_position=_coerce_choice(data.get("caption_position"), CAPTION_POSITIONS, d.caption_position, "layout.caption_position"),
            caption_area_mm=_coerce(data.get("caption_area_mm"), float, d.caption_area_mm, "layout.caption_area_mm"),
        )


# ---------------------------------------------------------------------------
# Captions
# ---------------------------------------------------------------------------

@dataclass
class CaptionSettings:
    #: Displayed fields, IN THE ORDER chosen by the user. Empty list by
    #: default = no caption, current behaviour.
    fields: list[str] = field(default_factory=list)
    #: Display format per field (e.g. {"aperture": "f/{value}"}) - fields
    #: not present here use a reasonable default format (see captions.py,
    #: to come).
    format_overrides: dict[str, str] = field(default_factory=dict)
    #: Distribution over several lines (specification §1).
    lines: int = 1
    font_size: int = 9
    alignment: str = "center"
    separator: str = " · "
    #: EXPLICIT privacy switch for the GPS coordinates (specification §1:
    #: "option explicitly allowing them to be hidden"). Even if "gps" appears
    #: in `fields`, the field is actually displayed ONLY if show_gps is True
    #: - defaults to False so as never to expose a location by accident.
    show_gps: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "CaptionSettings":
        d = cls()
        if not isinstance(data, dict):
            return d

        fields_in = data.get("fields")
        fields_out: list[str] = []
        if isinstance(fields_in, list):
            for f in fields_in:
                if isinstance(f, str) and f in CAPTION_FIELDS and f not in fields_out:
                    fields_out.append(f)
                else:
                    logger.debug(f"Profil : champ de légende ignoré (inconnu ou dupliqué) : {f!r}")
        elif fields_in is not None:
            logger.debug("Profil : 'captions.fields' doit être une liste, ignoré.")

        overrides_in = data.get("format_overrides")
        overrides_out: dict[str, str] = {}
        if isinstance(overrides_in, dict):
            for key, value in overrides_in.items():
                if key in CAPTION_FIELDS and isinstance(value, str):
                    overrides_out[key] = value

        return cls(
            fields=fields_out,
            format_overrides=overrides_out,
            lines=_coerce_optional_int(data.get("lines"), d.lines, "captions.lines") or d.lines,
            font_size=_coerce_optional_int(data.get("font_size"), d.font_size, "captions.font_size") or d.font_size,
            alignment=_coerce_choice(data.get("alignment"), CAPTION_ALIGNMENTS, d.alignment, "captions.alignment"),
            separator=data.get("separator") if isinstance(data.get("separator"), str) else d.separator,
            show_gps=_coerce(data.get("show_gps"), bool, d.show_gps, "captions.show_gps"),
        )

    def effective_fields(self) -> list[str]:
        """Fields actually to display, GPS filtered out as long as `show_gps`
        is not explicitly enabled - to be used by captions.py rather than
        `fields` directly, so that it is structurally impossible to display a
        GPS location "by mistake"."""
        if self.show_gps:
            return list(self.fields)
        return [f for f in self.fields if f != "gps"]


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------

@dataclass
class ThemeCustomColors:
    """Custom colours (specification §4.3), all optional: a colour set to
    None leaves the chosen preset theme unchanged for that particular
    colour. Expected values in hexadecimal ("#rrggbb"), validated by
    themes.py (to come) rather than here."""
    background: Optional[str] = None
    text: Optional[str] = None
    accent: Optional[str] = None
    border: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "ThemeCustomColors":
        if not isinstance(data, dict):
            return cls()

        def _hex_or_none(value: Any) -> Optional[str]:
            if isinstance(value, str) and value.startswith("#"):
                return value
            if value is not None:
                logger.debug(f"Profil : couleur personnalisée invalide ignorée : {value!r}")
            return None

        return cls(
            background=_hex_or_none(data.get("background")),
            text=_hex_or_none(data.get("text")),
            accent=_hex_or_none(data.get("accent")),
            border=_hex_or_none(data.get("border")),
        )


@dataclass
class ThemeSettings:
    #: Preset theme - see THEME_MODES. "light" = the currently hard-coded
    #: colours, hence no visual change as long as no theme is explicitly
    #: chosen.
    mode: str = "light"
    custom: ThemeCustomColors = field(default_factory=ThemeCustomColors)

    @classmethod
    def from_dict(cls, data: dict) -> "ThemeSettings":
        d = cls()
        if not isinstance(data, dict):
            return d
        return cls(
            mode=_coerce_choice(data.get("mode"), THEME_MODES, d.mode, "theme.mode"),
            custom=ThemeCustomColors.from_dict(data.get("custom")),
        )


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@dataclass
class Profile:
    """A complete profile: name (for display in the graphical interface) +
    the three groups of settings. `default_profile()` is the "empty" profile
    whose rendering must be strictly identical to the application's
    current behaviour."""
    name: Optional[str] = None
    layout: LayoutSettings = field(default_factory=LayoutSettings)
    captions: CaptionSettings = field(default_factory=CaptionSettings)
    theme: ThemeSettings = field(default_factory=ThemeSettings)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        if not isinstance(data, dict):
            logger.warning("Profil : contenu JSON invalide (objet attendu), valeurs par défaut utilisées.")
            return cls()
        name = data.get("name")
        return cls(
            name=name if isinstance(name, str) else None,
            layout=LayoutSettings.from_dict(data.get("layout")),
            captions=CaptionSettings.from_dict(data.get("captions")),
            theme=ThemeSettings.from_dict(data.get("theme")),
        )


def default_profile() -> Profile:
    """The "empty" profile whose rendering is strictly identical to the
    application's current behaviour, before captions/layout templates/themes
    - used when no profile is supplied (neither --profile on the CLI, nor a
    profile loaded in the graphical interface)."""
    return Profile()


def interface_default_profile() -> Profile:
    """Profile that the GRAPHICAL INTERFACE presents at startup and on
    "Reset": that of default_profile() with, in addition, the file name under
    each photo (the "File name" caption ticked).

    Deliberately distinct from default_profile(), which remains what the
    command line applies without --profile (no caption: rendering strictly
    identical to that of before the captions, which existing scripts depend
    on) - the interface, for its part, always passes its profile to the CLI
    as soon as it differs from default_profile() (see planche-contact-gtk.py)."""
    return Profile(
        layout=LayoutSettings(caption_position="below"),
        captions=CaptionSettings(fields=["filename"]),
    )


def load_profile(path: "str | Path") -> Profile:
    """Loads a profile from a JSON file. Never an exception: a missing,
    unreadable, malformed or partially recognised file (missing fields or
    from a newer/older version of the project) falls back to the default
    values for the fields concerned, with a log message - never a generation
    interrupted because of a profile."""
    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.warning(f"Profil introuvable : {path} - valeurs par défaut utilisées.")
        return default_profile()
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Profil illisible ({path}) : {e} - valeurs par défaut utilisées.")
        return default_profile()

    try:
        return Profile.from_dict(data)
    except Exception as e:
        # Final safety net: even an unexpected error in from_dict() must
        # never interrupt a generation over a mere profile problem.
        logger.warning(f"Profil invalide ({path}) : {e} - valeurs par défaut utilisées.")
        return default_profile()


def save_profile(profile: Profile, path: "str | Path") -> None:
    """Saves a profile as JSON, readable/editable by hand and reloadable
    by load_profile() or usable via --profile."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile.to_dict(), f, indent=2, ensure_ascii=False)
        f.write("\n")
