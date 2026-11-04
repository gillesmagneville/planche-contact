# -*- coding: utf-8 -*-
"""
portfolio/presentation/layout_engine.py - Geometry computation of the
contact sheets, INDEPENDENT of the final rendering (no dependency on
PIL/Pillow nor on HTML: numbers only). Used by contactsheet.py for the
JPEG/PDF rendering, and by the future GTK preview - both thus ALWAYS get
the same geometry, by construction (specification §5: "The layout engine
must be designed [...] as a common component [...] so that a same layout
rule is not implemented differently in several parts of the program").

The "grid" template reproduces the algorithm of
ContactSheetGenerator.create_contact_sheet() (search for the number of
columns maximising the thumbnail size, fixed 180 px reservation for the
header), INCLUDING its vertical overflow fix (see CHANGELOG.md "Contact
sheets: the thumbnails of the last row could slightly overflow..."): the
spacing between cells is now subtracted from the available height as well
as from the width, for ALL templates without exception - there is no
longer a "bug-faithful" template since contactsheet.py itself was fixed.

The HTML gallery (htmlgallery.py) does NOT directly use the pixel
coordinates of this module (a responsive CSS grid makes no sense in
fixed pixels): it consumes the same Profile, via themes.py/captions.py,
so that the SETTINGS remain a single source of truth, even if the final
translation into CSS is specific to HTML (see PROJECT_CONTEXT.md once
this module is integrated).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .profile import Profile

#: Reference resolution for all contact sheets/PDF - taken over as is
#: from contactsheet.py.
DPI = 300

#: Page sizes in millimetres (width, height), portrait orientation -
#: taken over as is from contactsheet.py._get_canvas_size().
PAPER_SIZES_MM = {
    "A5": (148, 210),
    "A4": (210, 297),
    "A3": (297, 420),
    "A2": (420, 594),
    "Letter": (216, 279),
}

#: Fixed vertical reservation for the header (title/author) in the grid
#: search of the "grid" template, in pixels at 300 ppi - historical value
#: of contactsheet.py (~15.2 mm), independent of the actual content of the
#: header (which may be shorter, e.g. no author). Kept here for
#: pixel-exact fidelity to the current behaviour; see the module
#: docstring.
HEADER_RESERVED_PX_GRID = 180

#: Sheet footer: three lines, from top to bottom - sheet number
#: (optional), "Planche générée par Planche-Contact", then the
#: developer/licence credit. Each value is the distance, in pixels at
#: 300 ppi, between the BOTTOM of the sheet and the origin (top) of the
#: line's text; contactsheet.py._draw_page_number() uses them as they
#: are, and FOOTER_RESERVED_PX is derived from them - a single source of
#: truth, so that a line added or moved here can never encroach on the
#: thumbnail grid without the reservation following.
FOOTER_PAGE_NUMBER_OFFSET_PX = 114
FOOTER_CREDIT_OFFSET_PX = 76
FOOTER_LICENSE_OFFSET_PX = 50

#: Minimum free space between the grid and the first line of the footer
#: (~1 mm).
FOOTER_CLEARANCE_PX = 12

#: Height reserved at the bottom of the page for the footer, sheet edge
#: included (~10.7 mm). The usable area of the grid stops at
#: `canvas_h - max(margin, FOOTER_RESERVED_PX)`: with the default margin
#: (12 mm = 141 px) the margin prevails and the geometry is strictly
#: unchanged; with a smaller margin, the grid no longer goes down under
#: the footer (the text lines used to cover the last photos).
FOOTER_RESERVED_PX = FOOTER_PAGE_NUMBER_OFFSET_PX + FOOTER_CLEARANCE_PX

#: Maximum number of columns tested by the "grid" search - historical
#: value of contactsheet.py (range(1, min(num_per_sheet + 1, 9))).
GRID_MAX_COLUMNS_TESTED = 8

#: Maximum number of columns tested by the "large thumbnails" template:
#: deliberately low, to favour large thumbnails rather than fitting as
#: many as possible on a page.
LARGE_THUMBS_MAX_COLUMNS_TESTED = 4

#: Maximum number of rows allowed by the "large thumbnails" template, for
#: the same reason as LARGE_THUMBS_MAX_COLUMNS_TESTED above: limiting
#: ONLY the number of columns tested is not enough to guarantee large
#: thumbnails, since nothing then prevents a high number of ROWS as soon
#: as `per_page` is large (e.g. 48 photos on 4 columns would require 12
#: rows, giving tiny thumbnails - the opposite of the intended goal). See
#: LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE and compute_effective_per_page().
LARGE_THUMBS_MAX_ROWS_TESTED = 2

#: Number of photos that the "large thumbnails" template allows itself to
#: place at most on ONE page, INDEPENDENTLY of the number of photos per
#: sheet actually configured by the user (layout.per_page): specification
#: - "that it itself reduce this number to guarantee large thumbnails in
#: all cases". With this bounded number of cells (and thus a bounded
#: number of rows/columns via the _grid_search search), the resulting
#: thumbnail size depends ONLY on the page format - never on the
#: requested number of photos per sheet. The excess photos (beyond this
#: limit) move on to the following pages - that is the role of
#: compute_effective_per_page(), whose value must be used by the caller
#: for the actual pagination (distribution of the photos into pages),
#: not layout.per_page, when this template is selected.
LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE = LARGE_THUMBS_MAX_COLUMNS_TESTED * LARGE_THUMBS_MAX_ROWS_TESTED

#: Absolute minimum thumbnail size (px), whatever the template - taken
#: over from contactsheet.py (max(best_thumb_size, 70)).
MIN_THUMB_SIZE_PX = 70


def mm_to_px(mm: float, dpi: int = DPI) -> int:
    return int(mm * dpi / 25.4)


def pt_to_px(pt: float, dpi: int = DPI) -> int:
    """Converts a size in typographic points (1 pt = 1/72 inch - the unit of
    CaptionSettings.font_size, chosen to have an identical meaning on the
    PIL side (here) AND on the CSS side of the HTML gallery, which will use
    it directly in "pt" without conversion) to pixels at the given
    resolution. Deliberately distinct from the header/footer font sizes
    (54/36/26/20), which are values in pixels already chosen empirically,
    with no defined equivalent in points."""
    return int(pt * dpi / 72)


def canvas_size_px(page_format: str, orientation: str = "portrait", dpi: int = DPI) -> tuple[int, int]:
    """Page size in pixels. Takes over exactly
    contactsheet.py._get_canvas_size() when orientation="portrait" (its only
    current use case); "landscape" swaps width/height - a new case,
    introduced with the layout profile."""
    width_mm, height_mm = PAPER_SIZES_MM.get(page_format, PAPER_SIZES_MM["A4"])
    if orientation == "landscape":
        width_mm, height_mm = height_mm, width_mm
    return mm_to_px(width_mm, dpi), mm_to_px(height_mm, dpi)


def compute_effective_per_page(profile: Profile) -> int:
    """Number of photos ACTUALLY placed on a page for this Profile's layout
    template. Equal to profile.layout.per_page for all templates (current
    behaviour unchanged), EXCEPT "large_thumbs" which reduces itself (see
    LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE) to guarantee large thumbnails
    whatever the configured per_page.

    The caller responsible for pagination (distribution of the photos of a
    generation over several pages) must rely on THIS value, and not directly
    on profile.layout.per_page, to get the real number of photos per page
    once this module is integrated into contactsheet.py."""
    layout = profile.layout
    if layout.template == "large_thumbs":
        return min(layout.per_page, LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE)
    return layout.per_page


@dataclass
class CellLayout:
    """Location of ONE photo (+ its possible caption) on the page, in
    pixels. The (x, y) coordinates are the top-left corner of each area,
    consistent with PIL.Image.paste()/ImageDraw."""
    index: int
    row: int
    col: int
    photo_x: int
    photo_y: int
    photo_w: int
    photo_h: int
    caption_x: Optional[int] = None
    caption_y: Optional[int] = None
    caption_w: Optional[int] = None
    caption_h: Optional[int] = None


@dataclass
class PageLayout:
    """Complete geometry of a page. `cells` only contains the locations
    actually occupied by a photo (up to min(photo_count,
    effective_per_page)), never empty cells - consistent with the current
    loop of create_contact_sheet().

    `effective_per_page` is the number of photos for which this geometry was
    computed - identical to profile.layout.per_page for all templates,
    except "large_thumbs" (see compute_effective_per_page()). It is this
    value, not profile.layout.per_page, that must drive the pagination once
    this module is integrated into contactsheet.py."""
    canvas_w: int
    canvas_h: int
    margin_px: int
    spacing_px: int
    content_top_px: int
    cols: int
    rows: int
    thumb_size: int
    effective_per_page: int = 0
    cells: list[CellLayout] = field(default_factory=list)
    #: Width and height of the COMPLETE grid of a full page, caption areas
    #: included (columns x rows computed for `effective_per_page` photos,
    #: independently of the number of photos actually present on THIS page:
    #: all the pages of a same generation thus have the same footprint, at
    #: the same place). Used to centre the grid on the page: horizontally
    #: here (compute_page_layout()), vertically in contactsheet.py, the only
    #: one to know the real height of the header.
    grid_w: int = 0
    grid_h: int = 0
    #: Y coordinate (top edge = 0) below which the grid must not go down:
    #: bottom of the usable area, reserved footer included (see
    #: FOOTER_RESERVED_PX). Used to centre the grid vertically in
    #: contactsheet.py.
    content_bottom_px: int = 0


#: Vertical spacing between two caption lines, in addition to the font
#: height itself. SINGLE source of this value (re-exported by
#: presentation/__init__.py and imported as is by
#: contactsheet.py._draw_caption(), `line_height = font_px +
#: CAPTION_LINE_SPACING_PX`): the height reserved here must always match
#: EXACTLY what that method actually draws (see _reserve_caption_px()
#: below) - never two duplicated constants that could diverge.
CAPTION_LINE_SPACING_PX = 4

#: Vertical space ("below"/"above" caption) or horizontal space
#: ("right" caption) between a photo and ITS caption, in pixels at 300 ppi
#: (~1.5 mm). Reserved IN ADDITION to the text area (see
#: compute_page_layout()), never taken from it: `cell.caption_w`/
#: `cell.caption_h` remain the size of the text area alone (that of
#: "Caption area (mm)"). Without this space, a photo filling its cell
#: (portrait, or square) had its caption stuck to its edge, the tops of
#: the letters almost touching the image.
CAPTION_PHOTO_GAP_PX = 18


def _reserve_caption_px(profile: Profile, caption_lines: Optional[int] = None) -> tuple[int, int]:
    """Space (width, height) in pixels to reserve per cell for the caption,
    according to layout.caption_position. Only one of the two values is
    non-zero at a time (a caption is either below/above the photo, or beside
    it - never both).

    For "below"/"above": the reserved height is the MAXIMUM between
    layout.caption_area_mm (value chosen by the user) and the height really
    needed to draw `caption_lines` lines at captions.font_size - never the
    first alone. Without this floor, a user increasing the number of lines or
    the font size without thinking of manually enlarging the caption area
    (caption_area_mm stays at its default value of 8 mm) got last caption
    lines overflowing into the photo of the next row - reported bug
    (CHANGELOG.md). "right" does not need this floor: its height always
    follows thumb_size (see compute_page_layout(), cell.caption_h =
    thumb_size), never caption_area_mm.

    `caption_lines`: number of lines to provide for. By default
    captions.lines (the user's setting); a caller that knows the actual text
    and its width (contactsheet.py) passes the number of lines REALLY needed
    once the captions are wrapped to fit the width of a thumbnail - which may
    exceed captions.lines (see presentation.captions.layout_caption_lines())."""
    layout = profile.layout
    if layout.caption_position in ("below", "above"):
        configured_h = mm_to_px(layout.caption_area_mm)
        font_px = max(6, pt_to_px(profile.captions.font_size))
        lines = profile.captions.lines if caption_lines is None else caption_lines
        needed_h = max(1, lines) * (font_px + CAPTION_LINE_SPACING_PX)
        return 0, max(configured_h, needed_h)
    if layout.caption_position == "right":
        return mm_to_px(layout.caption_area_mm), 0
    return 0, 0


def _apply_spacing_clamp(thumb_size: int, available_w: int, available_h: int,
                          cols: int, rows: int, spacing_px: int,
                          caption_w_px: int, caption_h_px: int) -> int:
    """A posteriori clamping to account for the spacing BETWEEN cells,
    absent from the initial computation of cell_w/cell_h (which merely
    divides the available space by the number of columns/rows, without
    subtracting the spacing between them) - both horizontally (between
    columns) and vertically (between rows), for all templates without
    exception: see the module docstring and CHANGELOG.md for the
    corresponding fix made to contactsheet.py."""
    max_thumb_w = (available_w - (cols - 1) * spacing_px) // cols - caption_w_px
    thumb_size = min(thumb_size, max(1, max_thumb_w))
    max_thumb_h = (available_h - (rows - 1) * spacing_px) // rows - caption_h_px
    thumb_size = min(thumb_size, max(1, max_thumb_h))
    return thumb_size


def _grid_search(available_w: int, available_h: int, per_page: int,
                  spacing_px: int, max_columns_tested: int,
                  caption_w_px: int, caption_h_px: int) -> tuple[int, int]:
    """Core of the "grid" algorithm (and of "large_thumbs"/"landscape"/
    "portrait", which only differ by `per_page`/`max_columns_tested` and/or
    a post-processing): searches, among the tested numbers of columns, for
    the one maximising the resulting thumbnail size. Extended to reserve the
    caption space per cell (zero when there is no caption, hence strictly
    equivalent to the original algorithm in that case). Returns
    (thumb_size, cols)."""
    best_cols = 1
    best_thumb_size = 0

    for cols in range(1, min(per_page + 1, max_columns_tested + 1)):
        rows = math.ceil(per_page / cols)

        cell_w = available_w // cols if cols > 1 else available_w
        cell_h = available_h // rows if rows > 1 else available_h

        # Caption space subtracted from the cell BEFORE computing the
        # thumbnail size: the caption must be known before the thumbnails
        # themselves are generated (see the module docstring and
        # PROJECT_CONTEXT.md, limitation no. 4 of the analysis).
        photo_cell_w = max(1, cell_w - caption_w_px)
        photo_cell_h = max(1, cell_h - caption_h_px)
        thumb_size = min(photo_cell_w, photo_cell_h)

        if thumb_size > best_thumb_size:
            best_thumb_size = thumb_size
            best_cols = cols

    thumb_size = max(best_thumb_size, MIN_THUMB_SIZE_PX)
    cols = best_cols
    rows = math.ceil(per_page / cols)

    thumb_size = _apply_spacing_clamp(
        thumb_size, available_w, available_h, cols, rows, spacing_px,
        caption_w_px, caption_h_px,
    )

    return thumb_size, cols


def _free_layout(profile: Profile, available_w: int, available_h: int,
                  spacing_px: int, caption_w_px: int, caption_h_px: int) -> tuple[int, int]:
    """The "free" template: columns/rows explicitly supplied by the user.
    If one of the two (or both) is not set, behaves like "grid" for the
    missing dimension - a "free" template with no setting at all must remain
    usable, not produce an empty page or an exception."""
    layout = profile.layout
    cols = layout.columns or None
    rows = layout.rows

    if cols is None and rows is None:
        return _grid_search(available_w, available_h, layout.per_page, spacing_px,
                             GRID_MAX_COLUMNS_TESTED, caption_w_px, caption_h_px)

    if cols is None:
        cols = max(1, math.ceil(layout.per_page / rows))
    if rows is None:
        rows = max(1, math.ceil(layout.per_page / cols))

    cell_w = available_w // cols if cols > 1 else available_w
    cell_h = available_h // rows if rows > 1 else available_h
    photo_cell_w = max(1, cell_w - caption_w_px)
    photo_cell_h = max(1, cell_h - caption_h_px)
    thumb_size = max(MIN_THUMB_SIZE_PX, min(photo_cell_w, photo_cell_h))

    thumb_size = _apply_spacing_clamp(
        thumb_size, available_w, available_h, cols, rows, spacing_px,
        caption_w_px, caption_h_px,
    )

    return thumb_size, cols


def compute_page_layout(profile: Profile, photo_count: int,
                        caption_lines: Optional[int] = None) -> PageLayout:
    """Computes the geometry of a page for the given Profile.

    `caption_lines` (optional): number of caption lines to provide for
    below/above each photo - see _reserve_caption_px(). No effect when no
    caption is positioned below/above the photo.

    `photo_count` is the number of photos ACTUALLY present on this page (may
    be lower than the per-page count for the last page of a series) - the
    grid geometry itself is always based on the template's per-page count
    (compute_effective_per_page(), identical to profile.layout.per_page
    except for "large_thumbs"), so that all the pages of a same generation
    have cells of identical size; only the number of cells actually filled
    varies.

    Never raises an exception: a default Profile produces exactly the
    current (corrected) geometry of contactsheet.py.
    """
    layout = profile.layout
    canvas_w, canvas_h = canvas_size_px(layout.page_format, layout.orientation)
    margin_px = mm_to_px(layout.margin_mm)
    spacing_px = mm_to_px(layout.spacing_mm)

    # Bottom margin: the Profile's, but never below the footer
    # (FOOTER_RESERVED_PX) - no effect from ~10.7 mm of margin onwards.
    bottom_px = max(margin_px, FOOTER_RESERVED_PX)
    available_w = canvas_w - 2 * margin_px
    available_h = canvas_h - margin_px - bottom_px - HEADER_RESERVED_PX_GRID

    caption_w_px, caption_h_px = _reserve_caption_px(profile, caption_lines)
    # Photo/caption gap: reserved in addition to the text area, in the
    # direction in which the caption is attached to the photo (width for
    # "right", height for "below"/"above"). It is these TOTALS (area + gap)
    # that enter into the computation of the thumbnail size and of the step
    # between cells; the cells, for their part, expose the text area alone.
    gap_px = CAPTION_PHOTO_GAP_PX if layout.caption_position in ("below", "above", "right") else 0
    reserved_w_px = caption_w_px + (gap_px if layout.caption_position == "right" else 0)
    reserved_h_px = caption_h_px + (gap_px if layout.caption_position in ("below", "above") else 0)

    effective_per_page = compute_effective_per_page(profile)

    if layout.template == "free":
        thumb_size, cols = _free_layout(profile, available_w, available_h, spacing_px,
                                         reserved_w_px, reserved_h_px)
        # "free" is not affected by the reduction of the per-page count of
        # "large_thumbs" (compute_effective_per_page() returns layout.per_page
        # as is for this template); kept here so that the computation of
        # rows/cells below stays based on one and the same variable for all
        # templates.
        effective_per_page = layout.per_page
    elif layout.template == "large_thumbs":
        thumb_size, cols = _grid_search(available_w, available_h, effective_per_page, spacing_px,
                                         LARGE_THUMBS_MAX_COLUMNS_TESTED, reserved_w_px, reserved_h_px)
    elif layout.template in ("landscape", "portrait"):
        # Search identical to "grid", but the preference between two numbers of
        # columns giving a nearly identical thumbnail size (within 5%) goes to
        # more columns ("landscape" - cells wider than tall, fewer rows) or
        # fewer columns ("portrait" - cells taller than wide, more rows).
        # Deliberately simple heuristic at this stage; to be refined after a
        # first real visual preview, the request not specifying an exact rule
        # beyond the names of the templates.
        thumb_size, cols = _grid_search(available_w, available_h, effective_per_page, spacing_px,
                                         GRID_MAX_COLUMNS_TESTED, reserved_w_px, reserved_h_px)
        rows_at_cols = math.ceil(effective_per_page / cols)
        prefer_more_cols = layout.template == "landscape"
        candidates = range(1, min(effective_per_page + 1, GRID_MAX_COLUMNS_TESTED + 1))
        for alt_cols in candidates:
            if (alt_cols > cols) != prefer_more_cols:
                continue
            alt_rows = math.ceil(effective_per_page / alt_cols)
            cell_w = available_w // alt_cols if alt_cols > 1 else available_w
            cell_h = available_h // alt_rows if alt_rows > 1 else available_h
            alt_thumb = min(max(1, cell_w - reserved_w_px), max(1, cell_h - reserved_h_px))
            if alt_thumb >= thumb_size * 0.95 and (
                (prefer_more_cols and alt_cols > cols) or (not prefer_more_cols and alt_cols < cols)
            ):
                cols, thumb_size, rows_at_cols = alt_cols, alt_thumb, alt_rows
        thumb_size = max(MIN_THUMB_SIZE_PX, _apply_spacing_clamp(
            thumb_size, available_w, available_h, cols, rows_at_cols, spacing_px,
            reserved_w_px, reserved_h_px,
        ))
    else:  # "grid", and safety net for an unknown value
        thumb_size, cols = _grid_search(available_w, available_h, effective_per_page, spacing_px,
                                         GRID_MAX_COLUMNS_TESTED, reserved_w_px, reserved_h_px)

    rows = math.ceil(effective_per_page / cols)
    content_top_px = margin_px + HEADER_RESERVED_PX_GRID

    # Footprint of a full page's grid, and HORIZONTAL centring: the
    # thumbnail size is limited by the width OR by the height (the more
    # constraining of the two), so the grid is almost always narrower than
    # the usable area - all the gap used to stay on the RIGHT of the page
    # (up to several centimetres), with the grid stuck to the left margin.
    # The remaining space is now split equally on each side. Never below the
    # margin, even if the grid overflows.
    grid_w = cols * (thumb_size + reserved_w_px) + (cols - 1) * spacing_px
    grid_h = rows * (thumb_size + reserved_h_px) + (rows - 1) * spacing_px
    grid_left_px = margin_px + max(0, available_w - grid_w) // 2

    cells: list[CellLayout] = []
    n_cells = min(photo_count, effective_per_page)
    for idx in range(n_cells):
        row = idx // cols
        col = idx % cols
        cell_x = grid_left_px + col * (thumb_size + reserved_w_px + spacing_px)
        cell_y = content_top_px + row * (thumb_size + reserved_h_px + spacing_px)

        if layout.caption_position == "above":
            # caption, then gap, then photo
            caption_y, photo_y = cell_y, cell_y + caption_h_px + gap_px
        else:
            # photo, then gap, then caption
            photo_y, caption_y = cell_y, cell_y + thumb_size + gap_px

        cell = CellLayout(
            index=idx, row=row, col=col,
            photo_x=cell_x, photo_y=photo_y, photo_w=thumb_size, photo_h=thumb_size,
        )
        if layout.caption_position == "right":
            cell.caption_x = cell_x + thumb_size + gap_px
            cell.caption_y = cell_y
            cell.caption_w = caption_w_px
            cell.caption_h = thumb_size
        elif layout.caption_position in ("below", "above"):
            cell.caption_x = cell_x
            cell.caption_y = caption_y
            cell.caption_w = thumb_size
            cell.caption_h = caption_h_px
        cells.append(cell)

    return PageLayout(
        canvas_w=canvas_w, canvas_h=canvas_h,
        margin_px=margin_px, spacing_px=spacing_px,
        content_top_px=content_top_px,
        cols=cols, rows=rows, thumb_size=thumb_size,
        effective_per_page=effective_per_page,
        cells=cells,
        grid_w=grid_w, grid_h=grid_h,
        content_bottom_px=canvas_h - bottom_px,
    )
