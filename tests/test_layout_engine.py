# -*- coding: utf-8 -*-
"""
Tests of the layout engine (portfolio/presentation/layout_engine.py).

The most important part of this file is the non-regression of the "grid"
template: a faithful copy of the CURRENT (fixed - see CHANGELOG.md)
algorithm of ContactSheetGenerator.create_contact_sheet() serves as the
reference, and must produce exactly the same values (thumb_size, cols) as
compute_page_layout() for a default Profile, over the whole range of
existing settings (8 to 48 images/sheet, in steps of 4 - values actually
offered by the graphical interface's slider - and the 5 supported page
formats). If this reference ever diverges from contactsheet.py, both must
be updated together.
"""
import math

import pytest

from portfolio.presentation import (
    Profile, LayoutSettings, CaptionSettings, compute_page_layout, compute_effective_per_page,
)
from portfolio.presentation.layout_engine import (
    PAPER_SIZES_MM, mm_to_px, pt_to_px, canvas_size_px, MIN_THUMB_SIZE_PX,
    LARGE_THUMBS_MAX_COLUMNS_TESTED, LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE,
    CAPTION_LINE_SPACING_PX, CAPTION_PHOTO_GAP_PX, HEADER_RESERVED_PX_GRID,
    FOOTER_PAGE_NUMBER_OFFSET_PX, FOOTER_CREDIT_OFFSET_PX, FOOTER_LICENSE_OFFSET_PX,
    FOOTER_CLEARANCE_PX, FOOTER_RESERVED_PX,
)


def _reference_grid_fit(num_per_sheet: int, page_format: str = "A4") -> tuple[int, int]:
    """Faithful copy, for comparison, of the algorithm currently
    hard-coded in ContactSheetGenerator.create_contact_sheet() - see
    portfolio/contactsheet.py (including its vertical overflow fix, see
    CHANGELOG.md: the spacing between cells is subtracted from the
    available height as well as from the width)."""
    DPI = 300
    width_mm, height_mm = PAPER_SIZES_MM.get(page_format, PAPER_SIZES_MM["A4"])
    canvas_w, canvas_h = int(width_mm * DPI / 25.4), int(height_mm * DPI / 25.4)
    margin = int(12 * 300 / 25.4)
    spacing = int(5 * 300 / 25.4)

    best_cols = 1
    best_thumb_size = 0
    available_w = canvas_w - 2 * margin
    available_h = canvas_h - 2 * margin - 180
    for cols in range(1, min(num_per_sheet + 1, 9)):
        rows = math.ceil(num_per_sheet / cols)
        cell_w = available_w // cols if cols > 1 else available_w
        cell_h = available_h // rows if rows > 1 else available_h
        thumb_size = min(cell_w, cell_h)
        if thumb_size > best_thumb_size:
            best_thumb_size = thumb_size
            best_cols = cols

    thumb_size = max(best_thumb_size, 70)
    cols = best_cols
    rows = math.ceil(num_per_sheet / cols)
    max_thumb_w = (available_w - (cols - 1) * spacing) // cols
    thumb_size = min(thumb_size, max_thumb_w)
    max_thumb_h = (available_h - (rows - 1) * spacing) // rows
    thumb_size = min(thumb_size, max_thumb_h)
    return thumb_size, cols


@pytest.mark.parametrize("per_page", list(range(8, 49, 4)))
@pytest.mark.parametrize("page_format", list(PAPER_SIZES_MM.keys()))
def test_grid_template_matches_current_contactsheet_algorithm(per_page, page_format):
    """Non-regression: a default Profile ("grid" template, no caption) must
    reproduce EXACTLY the thumb_size and cols of the current algorithm, for
    all the settings actually offered by the graphical interface (slider 8 to
    48 in steps of 4) and all the page formats."""
    expected_thumb_size, expected_cols = _reference_grid_fit(per_page, page_format)

    profile = Profile(layout=LayoutSettings(template="grid", per_page=per_page, page_format=page_format))
    page = compute_page_layout(profile, photo_count=per_page)

    assert page.thumb_size == expected_thumb_size
    assert page.cols == expected_cols


def test_grid_cells_count_matches_actual_photo_count_not_per_page():
    """The last page of a series (fewer photos than per_page) must only
    produce cells that are really occupied - the geometry (thumbnail size,
    columns) stays that of per_page, however, so that all the pages of a
    generation have cells of identical size (current behaviour)."""
    profile = Profile(layout=LayoutSettings(template="grid", per_page=12))
    full_page = compute_page_layout(profile, photo_count=12)
    last_page = compute_page_layout(profile, photo_count=5)

    assert len(full_page.cells) == 12
    assert len(last_page.cells) == 5
    assert last_page.thumb_size == full_page.thumb_size
    assert last_page.cols == full_page.cols


def test_cells_do_not_overlap_and_stay_within_canvas():
    """Generic geometric check, independent of contactsheet.py: whatever
    the template, no cell must overflow the canvas horizontally NOR
    vertically, nor overlap another. The vertical overflow is now checked
    for "grid" as for the other templates, since contactsheet.py itself was
    fixed (see CHANGELOG.md) and this module reproduces its fixed
    behaviour."""
    for template in ("grid", "landscape", "portrait", "large_thumbs"):
        profile = Profile(layout=LayoutSettings(template=template, per_page=24, page_format="A4"))
        page = compute_page_layout(profile, photo_count=24)

        assert page.thumb_size >= MIN_THUMB_SIZE_PX
        seen_positions = set()
        for cell in page.cells:
            assert 0 <= cell.photo_x
            assert cell.photo_x + cell.photo_w <= page.canvas_w, template
            assert cell.photo_y + cell.photo_h <= page.canvas_h, template
            assert (cell.row, cell.col) not in seen_positions
            seen_positions.add((cell.row, cell.col))


def test_grid_vertical_overflow_bug_is_fixed():
    """Non-regression of the fix made to contactsheet.py (see
    CHANGELOG.md): the case that revealed the vertical overflow (24 images
    on A4) must no longer overflow the physical bottom of the sheet, for the
    "grid" template as for the others. Before the fix, this same test (then
    named test_grid_known_preexisting_vertical_overflow_bug) checked the
    opposite - see the Git history for the old characterisation of the
    defect."""
    profile = Profile(layout=LayoutSettings(template="grid", per_page=24, page_format="A4"))
    page = compute_page_layout(profile, photo_count=24)
    last_cell = page.cells[-1]
    assert last_cell.photo_y + last_cell.photo_h <= page.canvas_h


def test_caption_position_below_reserves_vertical_space():
    """A "below" caption must reduce thumb_size compared with no caption
    (the reserved space is subtracted from the cell BEFORE computing the
    thumbnail size - see the module docstring), and each cell must have a
    caption area positioned below the photo."""
    no_caption = Profile(layout=LayoutSettings(template="grid", per_page=12, caption_position="none"))
    with_caption = Profile(layout=LayoutSettings(
        template="grid", per_page=12, caption_position="below", caption_area_mm=10,
    ))

    page_no_caption = compute_page_layout(no_caption, photo_count=12)
    page_with_caption = compute_page_layout(with_caption, photo_count=12)

    assert page_with_caption.thumb_size < page_no_caption.thumb_size
    cell = page_with_caption.cells[0]
    assert cell.caption_y == cell.photo_y + cell.photo_h + CAPTION_PHOTO_GAP_PX
    assert cell.caption_h == mm_to_px(10)


def test_caption_position_above_places_caption_before_photo():
    profile = Profile(layout=LayoutSettings(template="grid", per_page=12, caption_position="above", caption_area_mm=8))
    page = compute_page_layout(profile, photo_count=12)
    cell = page.cells[0]
    assert cell.caption_y < cell.photo_y
    assert cell.photo_y == cell.caption_y + cell.caption_h + CAPTION_PHOTO_GAP_PX


def test_caption_position_right_reserves_horizontal_space():
    """A single column ("free" template, columns=1) to guarantee that the
    width is indeed the limiting factor: a "right" caption must then
    strictly reduce thumb_size. With several columns, depending on the page
    format, it is sometimes the height that already limits the thumbnail
    size - subtracting from the width would then change nothing, without
    that being a bug (see the other, more generic test, which only checks
    NON-overflow, never a strict decrease)."""
    no_caption = Profile(layout=LayoutSettings(template="free", per_page=1, columns=1, rows=1, caption_position="none"))
    with_caption = Profile(layout=LayoutSettings(template="free", per_page=1, columns=1, rows=1,
                                                  caption_position="right", caption_area_mm=15))

    page_no_caption = compute_page_layout(no_caption, photo_count=1)
    page_with_caption = compute_page_layout(with_caption, photo_count=1)

    assert page_with_caption.thumb_size < page_no_caption.thumb_size
    cell = page_with_caption.cells[0]
    assert cell.caption_x == cell.photo_x + cell.photo_w + CAPTION_PHOTO_GAP_PX
    assert cell.caption_w == mm_to_px(15)


def test_caption_area_grows_to_fit_configured_lines_and_font_size():
    """Non-regression: with caption_area_mm left at a default/too small
    value, but several caption lines and/or a large font configured, the
    RESERVED height used to stay bounded to caption_area_mm - the last
    lines drawn by contactsheet.py._draw_caption() then overflowed into the
    photo of the next row (reported bug, see CHANGELOG.md). The reserved
    height must now be the larger of the two: never smaller than what
    contactsheet.py will actually draw."""
    profile = Profile(layout=LayoutSettings(
        template="grid", per_page=12, caption_position="below", caption_area_mm=8,
    ), captions=CaptionSettings(fields=["filename"], lines=3, font_size=14))

    page = compute_page_layout(profile, photo_count=12)
    cell = page.cells[0]

    needed_h = 3 * (pt_to_px(14) + CAPTION_LINE_SPACING_PX)
    assert needed_h > mm_to_px(8), "the scenario must exceed caption_area_mm to be meaningful"
    assert cell.caption_h == needed_h

    # And the converse property: when caption_area_mm is already sufficient,
    # it keeps driving the reserved height (current behaviour unchanged for
    # the default configuration - lines=1, font_size=9).
    default_profile = Profile(layout=LayoutSettings(
        template="grid", per_page=12, caption_position="below", caption_area_mm=20,
    ))
    default_page = compute_page_layout(default_profile, photo_count=12)
    assert default_page.cells[0].caption_h == mm_to_px(20)


def test_caption_never_increases_thumb_size():
    """Generic property, weaker but always true: reserving space for a
    caption can never ENLARGE the thumbnail, whatever the configuration."""
    for position in ("below", "above", "right"):
        no_caption = Profile(layout=LayoutSettings(template="grid", per_page=12, caption_position="none"))
        with_caption = Profile(layout=LayoutSettings(template="grid", per_page=12,
                                                       caption_position=position, caption_area_mm=10))
        page_no_caption = compute_page_layout(no_caption, photo_count=12)
        page_with_caption = compute_page_layout(with_caption, photo_count=12)
        assert page_with_caption.thumb_size <= page_no_caption.thumb_size, position


def test_free_template_honors_explicit_columns_and_rows():
    profile = Profile(layout=LayoutSettings(template="free", per_page=20, columns=5, rows=4))
    page = compute_page_layout(profile, photo_count=20)
    assert page.cols == 5
    assert len(page.cells) == 20


def test_free_template_without_any_override_behaves_like_grid():
    """A "free" template with no explicit setting must remain usable (no
    empty page, no exception) - fall back to the same computation as
    "grid"."""
    free_profile = Profile(layout=LayoutSettings(template="free", per_page=12))
    grid_profile = Profile(layout=LayoutSettings(template="grid", per_page=12))

    free_page = compute_page_layout(free_profile, photo_count=12)
    grid_page = compute_page_layout(grid_profile, photo_count=12)

    assert free_page.thumb_size == grid_page.thumb_size
    assert free_page.cols == grid_page.cols


def test_large_thumbs_never_exceeds_its_column_cap():
    """The number of columns never exceeds
    LARGE_THUMBS_MAX_COLUMNS_TESTED, whatever per_page."""
    for per_page in (8, 12, 24, 48):
        profile = Profile(layout=LayoutSettings(template="large_thumbs", per_page=per_page))
        page = compute_page_layout(profile, photo_count=per_page)
        assert page.cols <= LARGE_THUMBS_MAX_COLUMNS_TESTED


def test_large_thumbs_reduces_effective_per_page_above_its_cap():
    """Specification: "for the 'large thumbnails' template, that it itself
    reduce this number to guarantee large thumbnails in all cases."
    compute_effective_per_page() must therefore cap the number of photos
    actually placed per page at LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE as soon
    as per_page exceeds it, and leave per_page unchanged below it."""
    for per_page in (8, 12, 24, 48):
        profile = Profile(layout=LayoutSettings(template="large_thumbs", per_page=per_page))
        expected = min(per_page, LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE)
        assert compute_effective_per_page(profile) == expected

        page = compute_page_layout(profile, photo_count=per_page)
        assert page.effective_per_page == expected
        assert len(page.cells) == expected


def test_large_thumbs_guarantees_same_thumb_size_whatever_per_page_is_configured():
    """THE guarantee sought by the specification: unlike the old design
    (which only bounded the number of columns tested, hence guaranteed
    nothing as soon as per_page forced many rows - see the Git history),
    the thumbnail size of "large_thumbs" now depends ONLY on the page format
    once per_page is beyond LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE: asking for
    12, 24 or 48 photos per sheet then produces exactly the same geometry."""
    pages = []
    for per_page in (LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE, 24, 48):
        profile = Profile(layout=LayoutSettings(template="large_thumbs", per_page=per_page, page_format="A4"))
        pages.append(compute_page_layout(profile, photo_count=per_page))

    reference = pages[0]
    for page in pages[1:]:
        assert page.thumb_size == reference.thumb_size
        assert page.cols == reference.cols
        assert page.rows == reference.rows


def test_large_thumbs_never_overflows_canvas_regardless_of_per_page():
    for per_page in (8, 12, 24, 48):
        profile = Profile(layout=LayoutSettings(template="large_thumbs", per_page=per_page, page_format="A4"))
        page = compute_page_layout(profile, photo_count=per_page)
        for cell in page.cells:
            assert cell.photo_x + cell.photo_w <= page.canvas_w
            assert cell.photo_y + cell.photo_h <= page.canvas_h


def test_large_thumbs_matches_grid_columns_when_per_page_is_already_modest():
    """In the use case actually targeted (few photos per page, under the
    LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE cap), the per-page reduction of
    "large_thumbs" changes nothing (per_page already under the cap): only
    the restriction of the tested columns still distinguishes this template
    from "grid" - with a per_page small enough for both searches to end up
    at the same number of columns, both produce an identical geometry (both
    now apply the same spacing clamping, see CHANGELOG.md)."""
    per_page = min(8, LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE)
    profile_grid = Profile(layout=LayoutSettings(template="grid", per_page=per_page))
    profile_large = Profile(layout=LayoutSettings(template="large_thumbs", per_page=per_page))

    grid_page = compute_page_layout(profile_grid, photo_count=per_page)
    large_page = compute_page_layout(profile_large, photo_count=per_page)

    assert large_page.cols == grid_page.cols
    assert large_page.thumb_size == grid_page.thumb_size
    for cell in large_page.cells:
        assert cell.photo_y + cell.photo_h <= large_page.canvas_h


def test_landscape_orientation_swaps_canvas_dimensions():
    width, height = canvas_size_px("A4", orientation="portrait")
    swapped_width, swapped_height = canvas_size_px("A4", orientation="landscape")
    assert swapped_width == height
    assert swapped_height == width


@pytest.mark.parametrize("photo_count", [0, 1])
def test_edge_case_small_photo_counts_do_not_crash(photo_count):
    profile = Profile(layout=LayoutSettings(template="grid", per_page=12))
    page = compute_page_layout(profile, photo_count=photo_count)
    assert len(page.cells) == photo_count


def test_caption_lines_override_reserves_the_height_of_that_many_lines():
    """`caption_lines` lets contactsheet.py reserve the height of the lines
    REALLY needed once the captions are wrapped (see
    ContactSheetGenerator._plan_page()), which may exceed the
    captions.lines setting: without it, captions taller than expected would
    overflow into the next row."""
    profile = Profile(layout=LayoutSettings(
        template="grid", per_page=12, caption_position="below", caption_area_mm=8,
    ), captions=CaptionSettings(fields=["filename"], lines=1, font_size=9))

    default_page = compute_page_layout(profile, photo_count=12)
    five_lines_page = compute_page_layout(profile, photo_count=12, caption_lines=5)

    line_h = pt_to_px(9) + CAPTION_LINE_SPACING_PX
    assert 5 * line_h > mm_to_px(8), "the scenario must exceed caption_area_mm to be meaningful"
    assert five_lines_page.cells[0].caption_h == 5 * line_h
    assert five_lines_page.cells[0].caption_h > default_page.cells[0].caption_h
    # More room for the text = smaller thumbnails, never the opposite.
    assert five_lines_page.thumb_size < default_page.thumb_size
    # Without an argument: strictly identical to captions.lines (compatibility).
    assert compute_page_layout(profile, photo_count=12, caption_lines=1).cells[0].caption_h == \
        default_page.cells[0].caption_h


def test_caption_lines_override_is_ignored_for_right_captions():
    """For "right", the width is fixed (caption_area_mm) and the height
    already follows that of the thumbnail: the number of lines changes
    nothing in the geometry."""
    profile = Profile(layout=LayoutSettings(
        template="grid", per_page=12, caption_position="right", caption_area_mm=20,
    ), captions=CaptionSettings(fields=["filename"]))

    base = compute_page_layout(profile, photo_count=12)
    more_lines = compute_page_layout(profile, photo_count=12, caption_lines=9)

    assert more_lines.thumb_size == base.thumb_size
    assert more_lines.cells[0].caption_w == base.cells[0].caption_w
    assert more_lines.cells[0].caption_h == base.cells[0].caption_h


def test_photo_caption_gap_is_reserved_on_top_of_the_text_zone():
    """The gap between a photo and its caption (CAPTION_PHOTO_GAP_PX) must
    never be taken FROM the text area set by the user (caption_h stays
    "Caption area (mm)"): it is added to the step between two rows,
    otherwise the last line of a caption could touch the photo of the next
    row."""
    profile = Profile(layout=LayoutSettings(
        template="grid", per_page=12, caption_position="below", caption_area_mm=10,
    ))
    page = compute_page_layout(profile, photo_count=12)
    assert page.rows >= 2
    first, below_first = page.cells[0], page.cells[page.cols]

    assert first.caption_h == mm_to_px(10)
    assert first.caption_y - (first.photo_y + first.photo_h) == CAPTION_PHOTO_GAP_PX
    assert below_first.photo_y - first.photo_y == (
        page.thumb_size + CAPTION_PHOTO_GAP_PX + mm_to_px(10) + page.spacing_px
    )


def test_no_gap_is_reserved_without_a_caption():
    """Without a caption, the geometry stays exactly the original one - no
    phantom gap reserved."""
    page = compute_page_layout(Profile(), photo_count=12)
    first, below_first = page.cells[0], page.cells[page.cols]
    assert below_first.photo_y - first.photo_y == page.thumb_size + page.spacing_px
    assert first.caption_x is None and first.caption_y is None


@pytest.mark.parametrize("position", ["below", "above", "right"])
@pytest.mark.parametrize("per_page", [6, 12, 24])
def test_caption_zone_never_overlaps_another_photo_nor_leaves_the_page(position, per_page):
    profile = Profile(
        layout=LayoutSettings(template="grid", per_page=per_page, caption_position=position, caption_area_mm=10),
        captions=CaptionSettings(fields=["filename"], lines=2),
    )
    page = compute_page_layout(profile, photo_count=per_page)

    for a in page.cells:
        cap_right = a.caption_x + a.caption_w
        cap_bottom = a.caption_y + a.caption_h
        assert cap_right <= page.canvas_w and cap_bottom <= page.canvas_h
        assert a.photo_x + a.photo_w <= page.canvas_w and a.photo_y + a.photo_h <= page.canvas_h
        for b in page.cells:
            if a.index == b.index:
                continue
            overlap_x = a.caption_x < b.photo_x + b.photo_w and b.photo_x < cap_right
            overlap_y = a.caption_y < b.photo_y + b.photo_h and b.photo_y < cap_bottom
            assert not (overlap_x and overlap_y), (position, per_page, a.index, b.index)


# ---------------------------------------------------------------------------
# Horizontal centring of the grid on the page. The thumbnail size is
# limited by the width OR the height: the grid is almost always narrower
# than the usable area, and all the gap used to stay on the right (up to
# ~6 cm).
# ---------------------------------------------------------------------------

def _horizontal_margins(page, caption_position, caption_w_px):
    """Real (left margin, right margin) of the grid, caption areas on the
    right included."""
    reserved_w = (caption_w_px + CAPTION_PHOTO_GAP_PX) if caption_position == "right" else 0
    first = page.cells[0].photo_x
    last_right = page.cells[page.cols - 1].photo_x + page.thumb_size + reserved_w
    return first, page.canvas_w - last_right


@pytest.mark.parametrize("caption_position", ["none", "below", "above", "right"])
@pytest.mark.parametrize("template", ["grid", "landscape", "portrait", "large_thumbs"])
@pytest.mark.parametrize("orientation", ["portrait", "landscape"])
@pytest.mark.parametrize("page_format", ["A5", "A4", "A3", "Letter"])
@pytest.mark.parametrize("per_page", [8, 12, 24, 30, 48])
def test_grid_is_centered_horizontally_between_the_page_margins(
        per_page, page_format, orientation, template, caption_position):
    fields = [] if caption_position == "none" else ["filename", "datetime"]
    profile = Profile(
        layout=LayoutSettings(template=template, per_page=per_page, page_format=page_format,
                              orientation=orientation, caption_position=caption_position),
        captions=CaptionSettings(fields=fields),
    )
    page = compute_page_layout(profile, compute_effective_per_page(profile),
                               caption_lines=2 if fields else None)
    caption_w = page.cells[0].caption_w or 0
    left, right = _horizontal_margins(page, caption_position, caption_w)

    assert left >= page.margin_px, "the grid must never encroach on the left margin"
    assert right >= page.margin_px or page.grid_w > page.canvas_w - 2 * page.margin_px
    assert abs(left - right) <= 1, f"marge gauche {left} px, marge droite {right} px"


def test_known_case_a4_portrait_8_photos_used_to_leave_all_the_empty_space_on_the_right():
    page = compute_page_layout(Profile(layout=LayoutSettings(per_page=8)), 8)
    left, right = _horizontal_margins(page, "none", 0)

    # Before: 141 px on the left (the margin), 846 px on the right.
    assert left == 493 and right == 494


def test_grid_extent_is_exposed_for_vertical_centering():
    page = compute_page_layout(Profile(layout=LayoutSettings(per_page=12)), 12)

    assert page.grid_w == page.cols * page.thumb_size + (page.cols - 1) * page.spacing_px
    assert page.grid_h == page.rows * page.thumb_size + (page.rows - 1) * page.spacing_px


def test_grid_extent_includes_caption_zones():
    profile = Profile(
        layout=LayoutSettings(per_page=12, caption_position="below"),
        captions=CaptionSettings(fields=["filename"]),
    )
    page = compute_page_layout(profile, 12, caption_lines=2)
    row_pitch = page.cells[page.cols].photo_y - page.cells[0].photo_y

    assert page.grid_h == page.rows * (row_pitch - page.spacing_px) + (page.rows - 1) * page.spacing_px


def test_centering_does_not_depend_on_the_number_of_photos_on_the_page():
    """An incomplete page (last page) keeps the same grid, hence the same
    positions for its photos, as the full pages."""
    profile = Profile(layout=LayoutSettings(per_page=12))
    full = compute_page_layout(profile, 12)
    short = compute_page_layout(profile, 5)

    assert (short.grid_w, short.grid_h) == (full.grid_w, full.grid_h)
    assert [(c.photo_x, c.photo_y) for c in short.cells] == [(c.photo_x, c.photo_y) for c in full.cells[:5]]



# ---------------------------------------------------------------------------
# Sheet footer (number, credit, developer/licence): the grid must never
# go down onto it, whatever the chosen margin.
# ---------------------------------------------------------------------------

def test_footer_lines_are_ordered_and_spaced_for_their_font_sizes():
    """Reference values (26 px font for the number, 20 px for the two
    credits): three distinct lines, from top to bottom, without overlap, and
    the last one at a distance from the sheet edge."""
    assert FOOTER_PAGE_NUMBER_OFFSET_PX > FOOTER_CREDIT_OFFSET_PX > FOOTER_LICENSE_OFFSET_PX
    assert FOOTER_PAGE_NUMBER_OFFSET_PX - FOOTER_CREDIT_OFFSET_PX >= 34   # 26 px + line spacing
    assert FOOTER_CREDIT_OFFSET_PX - FOOTER_LICENSE_OFFSET_PX >= 24       # 20 px + line spacing
    assert FOOTER_LICENSE_OFFSET_PX >= 40                                  # text + sheet edge
    assert FOOTER_RESERVED_PX == FOOTER_PAGE_NUMBER_OFFSET_PX + FOOTER_CLEARANCE_PX
    assert FOOTER_CLEARANCE_PX >= 10


@pytest.mark.parametrize("margin_mm", [0, 3, 6, 10])
@pytest.mark.parametrize("page_format", ["A5", "A4", "A3", "Letter"])
@pytest.mark.parametrize("orientation", ["portrait", "landscape"])
@pytest.mark.parametrize("template,per_page", [("grid", 8), ("grid", 24), ("large_thumbs", 12), ("free", 12)])
def test_grid_stops_above_the_footer_when_the_margin_is_smaller_than_the_footer(
        margin_mm, page_format, orientation, template, per_page):
    profile = Profile(layout=LayoutSettings(page_format=page_format, orientation=orientation,
                                            template=template, per_page=per_page, margin_mm=margin_mm))
    page = compute_page_layout(profile, per_page)
    assert page.content_bottom_px == page.canvas_h - FOOTER_RESERVED_PX
    grid_bottom = page.content_top_px + page.grid_h
    assert grid_bottom <= page.content_bottom_px, (
        f"the grid goes down to {grid_bottom} px, the footer starts at {page.content_bottom_px} px"
    )


@pytest.mark.parametrize("margin_mm", [11, 12, 15, 20, 30])
def test_footer_reservation_changes_nothing_when_the_margin_is_large_enough(margin_mm):
    """From ~10.7 mm of margin onwards (the default margin is 12 mm), the
    bottom margin prevails over the footer: usable area, location and size
    of the thumbnails strictly identical to those from before the third
    line was added."""
    profile = Profile(layout=LayoutSettings(margin_mm=margin_mm))
    page = compute_page_layout(profile, 12)
    margin_px = mm_to_px(margin_mm)
    assert page.content_bottom_px == page.canvas_h - margin_px
    # same usable height as before: the whole height minus two margins and the header
    assert page.content_bottom_px - page.content_top_px == page.canvas_h - 2 * margin_px - HEADER_RESERVED_PX_GRID
