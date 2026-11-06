# -*- coding: utf-8 -*-
"""
portfolio/presentation/captions.py - Resolution of the per-photo
customisable captions (specification §1), from the EXIF metadata
extracted by portfolio.utils.get_exif_metadata() and the CaptionSettings
of a Profile.

Strict separation of responsibilities, consistent with the rest of the
package: utils.get_exif_metadata() extracts UNPROCESSED values (numbers,
tuples, datetime) with no textual formatting; this module decides the
"reasonable" default representation of each field (units, rounding,
"{value}" template) and applies any customisation by the user
(CaptionSettings.format_overrides). The output generators
(contactsheet.py/pdfexport.py for PIL rendering, htmlgallery.py for the
HTML, and the future GTK preview) therefore ALL consume the same function
- no caption formatting rule is duplicated between them (specification
§5).

Never raises an exception: a missing metadata item is simply omitted from
the caption (never an empty string displayed, never a generation
interrupted) - specification §1: "never produce an error for photos with
some metadata missing". The GPS filtering (show_gps) is already
guaranteed upstream by CaptionSettings.effective_fields() - this module
merely reuses it, never a second redundant check that could diverge.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

from ..i18n import _
from .profile import Profile


def _format_number(value: float, decimals: int = 1) -> str:
    """Readable number, without unnecessary decimals (e.g. 50.0 -> "50",
    2.8 -> "2.8")."""
    rounded = round(value, decimals)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.{decimals}f}".rstrip("0").rstrip(".")


def _format_shutter_speed(seconds: float) -> str:
    """Usual photographic convention: fraction for fast speeds ("1/250"),
    decimal for long exposures (>= 1 s, e.g. "2.5")."""
    if seconds <= 0:
        return "0"
    if seconds >= 1:
        return _format_number(seconds, 1)
    denominator = round(1 / seconds)
    if denominator <= 0:
        return _format_number(seconds, 3)
    return f"1/{denominator}"


def _format_gps(lat: float, lon: float) -> str:
    lat_ref = "N" if lat >= 0 else "S"
    lon_ref = "E" if lon >= 0 else "W"
    return f"{abs(lat):.4f}°{lat_ref}, {abs(lon):.4f}°{lon_ref}"


def _default_display(field: str, value: Any) -> Optional[str]:
    """Default, "reasonable" representation of a raw metadata value - see
    the module docstring. Returns None if the value is unusable (unexpected
    type for this field), rather than raising an exception or displaying an
    absurd value."""
    try:
        if field == "filename":
            text = str(value)
            return text or None
        if field == "datetime":
            return value.strftime("%Y-%m-%d") if isinstance(value, datetime) else None
        if field in ("camera", "lens"):
            text = str(value).strip()
            return text or None
        if field == "focal_length":
            return f"{_format_number(float(value))} mm"
        if field == "focal_35mm":
            return f"{int(value)} mm ({_('caption.equiv_24x36')})"
        if field == "aperture":
            return f"f/{_format_number(float(value))}"
        if field == "shutter_speed":
            return f"{_format_shutter_speed(float(value))}s"
        if field == "iso":
            return f"ISO {int(value)}"
        if field == "dimensions":
            width, height = value
            return f"{int(width)} × {int(height)}"
        if field == "gps":
            lat, lon = value
            return _format_gps(float(lat), float(lon))
    except (TypeError, ValueError, AttributeError):
        return None
    return None


def _format_field(field: str, metadata: dict, overrides: dict) -> Optional[str]:
    value = metadata.get(field)
    if value is None:
        return None
    display = _default_display(field, value)
    if not display:
        return None
    template = overrides.get(field)
    if template:
        try:
            return template.format(value=display)
        except (KeyError, IndexError, ValueError):
            # Invalid user template (e.g. unescaped brace, reference to a missing
            # name): we fall back to the default display rather than interrupting the
            # whole generation over a typo in a saved profile.
            return display
    return display


def _chunk_evenly(items: list[str], n: int) -> list[list[str]]:
    """Splits `items` into at most `n` consecutive groups as equal as
    possible, in the original order (the first groups receive the extra
    element in case of uneven division). Empty groups (n > len(items)) are
    omitted rather than producing empty caption lines."""
    if n <= 1 or len(items) <= 1:
        return [items] if items else []
    base, extra = divmod(len(items), n)
    chunks = []
    start = 0
    for i in range(n):
        size = base + (1 if i < extra else 0)
        if size == 0:
            continue
        chunks.append(items[start:start + size])
        start += size
    return chunks


def resolve_caption_parts(profile: Profile, metadata: dict) -> list[str]:
    """Formatted texts of the caption fields of ONE photo, in the
    configured order, WITHOUT having yet split them into lines or joined
    them with the separator - only the fields actually present in the
    metadata (empty list otherwise, never an exception). Step shared by
    resolve_caption_lines() (simple split, used by the HTML gallery, whose
    browser handles line wrapping itself) and layout_caption_lines() (split
    taking a pixel width into account, used by the JPEG/PDF rendering)."""
    captions = profile.captions
    fields = captions.effective_fields()
    if not fields or not metadata:
        return []
    return [
        text for text in (
            _format_field(field, metadata, captions.format_overrides)
            for field in fields
        )
        if text
    ]


def resolve_caption_lines(profile: Profile, metadata: dict) -> list[str]:
    """Resolves the caption line(s) of ONE photo, from its metadata (see
    portfolio.utils.get_exif_metadata()) and the Profile's
    CaptionSettings.fields/lines/format_overrides/separator.

    Returns a list of strings (one per really non-empty line) - EMPTY list
    if no field is configured or if no metadata could be extracted for the
    requested fields (e.g. photo without EXIF): in that case, the caller must
    draw nothing, never an empty caption or an exception.

    Does NOT take an available width into account: see
    layout_caption_lines() for a rendering in fixed pixels (JPEG/PDF)."""
    parts = resolve_caption_parts(profile, metadata)
    if not parts:
        return []

    chunks = _chunk_evenly(parts, max(1, profile.captions.lines))
    return [profile.captions.separator.join(chunk) for chunk in chunks]


def _wrap_words(text: str, max_width: int, measure: Callable[[str], int]) -> list[str]:
    """Last resort for a field that ALONE is wider than the area (e.g. a
    very long lens name): greedy line wrapping at spaces. A single word
    wider than `max_width` stays alone on its line, intact - it is then up
    to the caller to bound it at display time (see
    contactsheet._fit_text_to_width()), never this module, which knows
    neither the font nor the rendering."""
    if measure(text) <= max_width:
        return [text]
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = word if not current else f"{current} {word}"
        if not current or measure(candidate) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _wrap_chunk(chunk: list[str], separator: str, max_width: int,
                measure: Callable[[str], int]) -> list[str]:
    """Fills lines from left to right with the fields of `chunk`, wrapping
    BEFORE the field that would exceed `max_width`: a field is therefore
    never split in two as long as it fits alone on a line, and the separator
    never appears at the end or beginning of a line (only BETWEEN two fields
    of the same line)."""
    lines: list[str] = []
    current = ""
    for part in chunk:
        if current:
            candidate = f"{current}{separator}{part}"
            if measure(candidate) <= max_width:
                current = candidate
                continue
            lines.append(current)
        pieces = _wrap_words(part, max_width, measure)
        lines.extend(pieces[:-1])
        current = pieces[-1]
    if current:
        lines.append(current)
    return lines


def layout_caption_lines(profile: Profile, metadata: dict, max_width: int,
                         measure: Callable[[str], int]) -> list[str]:
    """Like resolve_caption_lines(), but for a rendering in fixed pixels:
    no returned line exceeds `max_width` (measured by `measure`, supplied by
    the caller - this module thus stays independent of PIL and of any font),
    as long as each WORD fits alone in that width.

    CaptionSettings.lines is the number of lines over which the fields are
    first split (see resolve_caption_lines()); a line too wide for the area
    then wraps, at field boundaries (see _wrap_chunk()), instead of being
    truncated ("…") or overflowing into the neighbouring cells - fix for a
    reported bug: with several fields ticked and "Text lines" = 1,
    everything fit on a single line, much wider than a thumbnail. The number
    of lines actually needed can therefore exceed CaptionSettings.lines: it
    is up to the caller to reserve the corresponding height in the layout
    (see contactsheet.py, `compute_page_layout(..., caption_lines=...)`).

    `max_width` <= 0 (degenerate area): fall back to
    resolve_caption_lines()."""
    if max_width <= 0:
        return resolve_caption_lines(profile, metadata)

    parts = resolve_caption_parts(profile, metadata)
    if not parts:
        return []

    separator = profile.captions.separator
    lines: list[str] = []
    for chunk in _chunk_evenly(parts, max(1, profile.captions.lines)):
        lines.extend(_wrap_chunk(chunk, separator, max_width, measure))
    return lines
