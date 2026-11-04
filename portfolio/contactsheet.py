from PIL import Image, ImageDraw, ImageOps
from pathlib import Path

from .utils import apply_watermark, get_font, get_exif_metadata, AUTHOR_NAME
from .presentation import (
    compute_page_layout, compute_effective_per_page, resolve_theme, layout_caption_lines,
    canvas_size_px, pt_to_px, CAPTION_LINE_SPACING_PX,
    FOOTER_PAGE_NUMBER_OFFSET_PX, FOOTER_CREDIT_OFFSET_PX, FOOTER_LICENSE_OFFSET_PX,
)
from .i18n import _
from .textlayer import TextRun

#: Maximum number of caption lines that the layout adds by itself when
#: the text, once wrapped to the width of a thumbnail, exceeds
#: captions.lines (see ContactSheetGenerator._plan_page()). A safety
#: bound against an endless readjustment loop on extremely narrow
#: thumbnails: beyond it, _draw_caption() clamps the text to the reserved
#: height anyway, so it never overflows into the next photo.
MAX_AUTO_CAPTION_LINES = 10


def _fit_text_to_width(draw, text, font, max_width):
    """Truncates `text` with an ellipsis ("…") if its rendered width exceeds
    `max_width`, otherwise returns it unchanged. Last safety net of
    ContactSheetGenerator._draw_caption(): captions are normally already
    wrapped to the available width
    (presentation.captions.layout_caption_lines()), so that this truncation
    now only applies to a single WORD wider than the cell (e.g. an endless
    file name on a tiny thumbnail) - never to an ordinary caption made of
    several fields. See CHANGELOG.md.

    Linear search (removes one character at a time): sufficient here, since
    a caption never exceeds a few dozen characters and this function is only
    called once per line/per photo."""
    if max_width <= 0:
        return ""
    bbox = draw.textbbox((0, 0), text, font=font)
    if bbox[2] - bbox[0] <= max_width:
        return text

    ellipsis = "…"
    bbox = draw.textbbox((0, 0), ellipsis, font=font)
    if bbox[2] - bbox[0] > max_width:
        # Even the ellipsis alone does not fit (extremely narrow cell):
        # nothing displayable fits, better to draw nothing than a misleading
        # fragment.
        return ""

    truncated = text
    while truncated:
        truncated = truncated[:-1]
        candidate = truncated.rstrip() + ellipsis
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return candidate
    return ellipsis


def _thumb_offset(caption_position, alignment, thumb_wh, cell_size):
    """Offset (dx, dy), in pixels, of the thumbnail INSIDE its square cell
    `cell_size x cell_size`, so that the photo is stuck to its caption
    instead of staying at the top left of the cell.

    A thumbnail keeps its proportions (`Image.thumbnail`): a 4:3 landscape
    photo only occupies three quarters of the cell's height, and the caption,
    placed below the cell (see layout_engine.compute_page_layout()), was
    therefore separated from its photo by a gap - all the more visible when
    the caption runs to several lines. The gap now ends up on the side
    opposite the caption, which visually groups each photo with its caption
    AND keeps the captions aligned from one photo to the next (the caption
    area itself has not moved):

    - "below": photo resting on its caption (bottom-aligned);
    - "above": photo stuck under its caption (top-aligned);
    - "right": photo stuck against its caption (right-aligned);
    - horizontally, for "below"/"above", the photo follows the text
      alignment (left/centre/right) - previously always left, whereas the
      caption was centred under the cell.

    Without a caption (`caption_position` other than these three values,
    including "none" - the value to pass when no field is configured): photo
    CENTRED in its cell, in both directions. It used to be stuck at the top
    left of the cell (offset (0, 0)), which left a gap to the right of a
    portrait photo and below a landscape photo: all the photos looked shifted
    towards the top and left of the page, even once the grid itself was
    centred (see layout_engine.compute_page_layout() and
    create_contact_sheet())."""
    width, height = thumb_wh
    free_w = max(0, cell_size - width)
    free_h = max(0, cell_size - height)

    if caption_position == "right":
        return free_w, 0
    if caption_position not in ("below", "above"):
        return free_w // 2, free_h // 2

    dy = free_h if caption_position == "below" else 0
    if alignment == "left":
        dx = 0
    elif alignment == "right":
        dx = free_w
    else:
        dx = free_w // 2
    return dx, dy


def _fit_header_text(draw, text, size, bold, max_width, min_size):
    """Font and text of the header (title/author) fitting within `max_width`:
    the largest size <= `size` (in steps of 2 px, never below `min_size`)
    for which `text` fits; if even `min_size` is not enough, the text is
    truncated with "…" (_fit_text_to_width) as a last resort. A text that
    already fits keeps exactly its original font.

    Without this guard, a long title overflowed the page - with no visible
    consequence as long as it was centred (clipped symmetrically), but a
    right-aligned title would have started OUTSIDE the page."""
    font = get_font(size, bold=bold)
    for candidate in range(size, min_size - 1, -2):
        font = get_font(candidate, bold=bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font, text
    return font, _fit_text_to_width(draw, text, font, max_width)


def _text_run(draw, xy, text, font, bold=False, copy_text=None):
    """`TextRun` describing a text that `draw.text(xy, text, font=font)` has
    just drawn (default PIL anchor: left edge, top of the line), for the
    PDF's invisible text layer (see textlayer.py). Returns None if the font
    does not allow measuring the text: the sheet is then drawn normally,
    simply without selectable text for that line."""
    if not text:
        return None
    try:
        ascent = font.getmetrics()[0]
        width = float(draw.textlength(text, font=font))
        size = float(font.size)
    except Exception:
        return None
    return TextRun(
        text=copy_text or text, x=float(xy[0]), baseline=float(xy[1]) + ascent,
        size=size, width=width, bold=bold,
    )


def _header_x(position, canvas_w, margin_px, text_w):
    """X coordinate of the header text according to HEADER_POSITIONS:
    aligned on the page margin on the left/right, centred otherwise
    (original formula, unchanged: centring never took the margins into
    account)."""
    if position == "top_left":
        return margin_px
    if position == "top_right":
        return canvas_w - margin_px - text_w
    return (canvas_w - text_w) / 2


class ContactSheetGenerator:
    def __init__(self, config, thumbnail_generator):
        self.config = config
        self.thumb_gen = thumbnail_generator
        # The Profile (portfolio/presentation/profile.py) is now the single
        # source of truth for layout, captions and theme - see
        # Config.__post_init__() for the backward-compatible synchronisation
        # with page_format/num_per_sheet when no explicit Profile was supplied.
        self.profile = config.profile
        self.page_format = self.profile.layout.page_format
        self.project_title = getattr(config, 'title', None)
        self.author = getattr(config, 'author', None)
        self.input_dir = getattr(config, 'input_dir', None)
        self.num_per_sheet = self.profile.layout.per_page
        #: Texts drawn on the LAST sheet created (list of TextRun, in reading
        #: order: header, captions, footer): the PDF uses them to lay selectable
        #: text over the image.
        self.last_text_runs = []

    def _put_text(self, draw, xy, text, fill, font, bold=False, copy_text=None):
        """`draw.text()` + recording of the text in `last_text_runs`.
        `copy_text`: text to copy from the PDF when it differs from the one
        displayed (line truncated with "…": the PDF keeps the full version)."""
        draw.text(xy, text, fill=fill, font=font)
        run = _text_run(draw, xy, text, font, bold=bold, copy_text=copy_text)
        if run is not None:
            self.last_text_runs.append(run)

    def _get_canvas_size(self):
        return canvas_size_px(self.profile.layout.page_format, self.profile.layout.orientation)

    def create_contact_sheet(self, images, page_num, total_pages):
        self.last_text_runs = []
        if not images:
            return None

        profile = self.profile
        palette = resolve_theme(profile.theme)
        # The geometry depends on the TEXT of the captions (their number of
        # lines once wrapped to the width of a thumbnail determines the height
        # to reserve, hence the size of the thumbnails): see _plan_page().
        page, caption_lines_by_idx = self._plan_page(images)

        canvas_w, canvas_h = page.canvas_w, page.canvas_h
        margin = page.margin_px
        thumb_size = page.thumb_size
        # "large_thumbs" may itself have reduced the number of photos fitting
        # on ONE page (see layout_engine.compute_effective_per_page): the
        # actual distribution of the EXCESS photos over additional pages
        # remains to be wired upstream, in portfolio.py's pagination loop
        # (which still ignores this reduction and keeps distributing in batches
        # of config.num_per_sheet) - a separate later step. Meanwhile, we never
        # draw here more cells than what the computed geometry actually
        # provides (page.cells contains at most as many), so as never to
        # overflow the grid.
        effective_per_page = page.effective_per_page

        # Fit mode (Profile, "Fill" in the interface): "cover" crops each photo
        # to a square to fill its whole cell.
        thumbnails = self.thumb_gen.generate_parallel(
            images, thumb_size, fit_mode=profile.layout.fit_mode,
        )

        sheet = Image.new("RGB", (canvas_w, canvas_h), palette.background)
        draw = ImageDraw.Draw(sheet)

        header_bottom_y = self._draw_header(draw, canvas_w, margin, palette)
        # Space between the bottom of the header and the thumbnail grid: more
        # generous than the previous version, aligned on the same value as the
        # side/bottom margins for a balanced composition.
        content_gap = margin
        y_start = header_bottom_y + content_gap

        # RIGID vertical offset applied to ALL the cells computed by the
        # layout engine (photos AND captions): the engine assumes a grid start
        # at a FIXED header height (page.content_top_px), whereas contactsheet.py
        # computes its own dynamically according to the text actually displayed
        # (title/author) - see _draw_header() above - for a rendering of the
        # "grid" template strictly identical to before this engine was
        # introduced (specification: no regression of existing behaviour). A
        # CONSTANT offset exactly preserves the RELATIVE spacing computed by the
        # engine between all the cells of a same page (including the space
        # reserved for captions, which is added to the height of each row - see
        # compute_page_layout()): rebuilding this computation by hand here would
        # duplicate a rule that is already centralised, with the real risk of
        # redoing it INCORRECTLY (a first attempt at this fix did so, in fact:
        # captions encroached on the next row of thumbnails, for want of
        # subtracting the caption space from the gap between rows).
        y_shift = y_start - page.content_top_px

        # VERTICAL centring of the grid in the space actually free under the
        # header (down to the bottom margin): the thumbnail size is limited by
        # the width OR by the height, so the grid almost always leaves a gap on
        # one side only - at the bottom of the page, up to several centimetres.
        # The remaining gap is split equally above and below. Computed on the
        # grid of a FULL page (page.grid_h): all the pages of a generation -
        # incomplete last page included - keep their photos at exactly the same
        # places. Never a negative offset (the grid does not move up under the
        # header); horizontal centring is done by the engine
        # (layout_engine.compute_page_layout()).
        free_h = page.content_bottom_px - y_start
        y_shift += max(0, free_h - page.grid_h) // 2

        # Caption position actually DRAWN: with no field configured, the area is
        # reserved but stays empty - the thumbnails are then kept exactly where
        # they were (see _thumb_offset()).
        drawn_caption_position = (
            profile.layout.caption_position if profile.captions.effective_fields() else "none"
        )

        for idx, thumb in enumerate(thumbnails):
            if idx >= effective_per_page or idx >= len(page.cells):
                break
            if thumb is None:
                continue

            if self.config.watermark_text:
                thumb = apply_watermark(
                    thumb,
                    self.config.watermark_text,
                    getattr(self.config, 'watermark_opacity', 40),
                    getattr(self.config, 'watermark_orientation', 'Horizontal')
                )

            cell = page.cells[idx]
            x, y = cell.photo_x, cell.photo_y + y_shift
            dx, dy = _thumb_offset(
                drawn_caption_position, profile.captions.alignment, thumb.size, thumb_size,
            )
            sheet.paste(thumb, (x + dx, y + dy))

            lines = caption_lines_by_idx.get(idx)
            if lines and cell.caption_x is not None:
                self._draw_caption(
                    draw, lines, cell.caption_x, cell.caption_y + y_shift,
                    cell.caption_w, cell.caption_h, profile.captions, palette,
                )

        self._draw_page_number(
            draw, canvas_w, canvas_h, page_num, total_pages, palette,
            show_page_number=profile.layout.page_numbering,
        )
        return sheet

    def _plan_page(self, images):
        """Computes the page geometry AND the text (already wrapped) of each
        photo's captions - returns `(PageLayout, {photo_index: [lines]})`.

        Without a caption below/above the photo (default case), strictly
        equivalent to a plain `compute_page_layout()`: no EXIF metadata is read
        (costly, one or more file accesses per photo - see
        utils.get_exif_metadata()), no extra cost.

        With a caption, the lines to reserve depend on the actual text, itself
        depending on the thumbnail width, which in turn depends on the reserved
        height (more lines -> smaller thumbnails -> narrower captions ->
        sometimes even more lines): we start from captions.lines, measure the
        actual text wrapped to the width of a thumbnail
        (presentation.captions.layout_caption_lines()), and if a photo needs
        more lines than those reserved, we recompute the geometry with that
        number until stable - at most MAX_AUTO_CAPTION_LINES lines, the number
        of lines only ever growing from one iteration to the next. "Right"
        captions do not need this loop: their width is fixed (caption_area_mm)
        and their height already follows that of the thumbnail.

        Accepted consequence: each PAGE adjusts the caption height to ITS own
        photos (a page where one photo has a very long lens name may have
        slightly smaller thumbnails than the previous one)."""
        profile = self.profile
        caption_fields = profile.captions.effective_fields()
        position = profile.layout.caption_position
        if not caption_fields or position not in ("below", "above", "right"):
            return compute_page_layout(profile, photo_count=len(images)), {}

        per_page = compute_effective_per_page(profile)
        metadata = [get_exif_metadata(img["path"]) for img in images[:per_page]]

        font = get_font(max(6, pt_to_px(profile.captions.font_size)))
        scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

        def measure(text):
            bbox = scratch.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]

        n_lines = max(1, profile.captions.lines)
        max_lines = max(n_lines, MAX_AUTO_CAPTION_LINES)
        while True:
            page = compute_page_layout(profile, photo_count=len(images), caption_lines=n_lines)
            texts = {}
            needed = 1
            for idx, cell in enumerate(page.cells):
                if idx >= len(metadata) or cell.caption_w is None:
                    continue
                lines = layout_caption_lines(profile, metadata[idx], cell.caption_w, measure)
                if lines:
                    texts[idx] = lines
                    needed = max(needed, len(lines))
            if position == "right" or needed <= n_lines or n_lines >= max_lines:
                return page, texts
            n_lines = min(needed, max_lines)

    def _draw_header(self, draw, canvas_w, margin_px, palette):
        """Title then author, one UNDER the other, each aligned according to
        LayoutSettings.title_position/author_position (left/centre/right on the
        page margins, or "none" to hide it). Returns the y coordinate of the
        bottom of the header (the thumbnail grid starts below it). Default
        positions (centred): rendering strictly identical to before these
        settings were introduced."""
        layout = self.profile.layout
        max_width = canvas_w - 2 * margin_px

        # Reduced top margin before the header (6 mm, against ~9.5 mm
        # previously): the title starts noticeably closer to the top of the
        # sheet/page.
        y = int(6 * 300 / 25.4)

        # If no field (title, author, watermark) has been filled in, the sheet
        # would be completely anonymous: the name of the source folder (without
        # its full path) is then displayed by default as the title. Never when
        # the user has explicitly hidden the title (title_position == "none").
        watermark_text = getattr(self.config, 'watermark_text', None)
        display_title = self.project_title
        if not display_title and not self.author and not watermark_text and self.input_dir:
            display_title = Path(self.input_dir).name

        if display_title and layout.title_position != "none":
            font_title, text = _fit_header_text(draw, display_title, 54, True, max_width, 28)
            bbox = draw.textbbox((0, 0), text, font=font_title)
            text_w = bbox[2] - bbox[0]
            x = _header_x(layout.title_position, canvas_w, margin_px, text_w)
            self._put_text(draw, (x, y), text, palette.text, font_title, bold=True,
                           copy_text=display_title if text != display_title else None)
            y += 58

        if self.author and layout.author_position != "none":
            font_author, text = _fit_header_text(draw, self.author, 36, True, max_width, 20)
            bbox = draw.textbbox((0, 0), text, font=font_author)
            text_w = bbox[2] - bbox[0]
            x = _header_x(layout.author_position, canvas_w, margin_px, text_w)
            self._put_text(draw, (x, y), text, palette.text, font_author, bold=True,
                           copy_text=self.author if text != self.author else None)
            y += 42

        return y

    def _draw_caption(self, draw, lines, x, y, width, height, caption_settings, palette):
        """Draws the caption lines of ONE photo (specification §1), already
        resolved AND wrapped by _plan_page()
        (presentation.captions.layout_caption_lines()) - this method ONLY
        positions/draws them, no formatting or wrapping rule is duplicated
        here. `x`/`y`: top-left corner of the caption area reserved for this
        photo; `width`/`height`: usable dimensions of this area, for the
        horizontal centring/alignment and to bound the number of lines drawn.

        Two safety nets, never an overflow into the neighbouring cells (reported
        bug: captions overlapping, unreadable):
        - a line wider than `width` (a single WORD that is too long) is
          truncated with "…";
        - if there are more lines than `height` can hold ("right" caption on a
          small thumbnail, or MAX_AUTO_CAPTION_LINES ceiling reached), the
          excess lines are removed and the last one ends with "…".
        In the ordinary case (several fields on a normal-sized thumbnail),
        neither applies: all the text is visible.
        See CHANGELOG.md."""
        font_px = max(6, pt_to_px(caption_settings.font_size))
        font = get_font(font_px)
        # CAPTION_LINE_SPACING_PX: same constant as
        # layout_engine._reserve_caption_px(), which computes the height to
        # reserve from this formula - never a hard-coded duplicated value here,
        # so that a drawn line can never again become taller than the space
        # actually reserved.
        line_height = font_px + CAPTION_LINE_SPACING_PX

        max_lines = max(1, height // line_height)
        # Full text of each line for the PDF (invisible text layer, see
        # textlayer.py): the lines removed for lack of room are appended
        # after the last visible line.
        full_lines = list(lines)
        if len(lines) > max_lines:
            full_lines = list(lines[:max_lines - 1]) + [" ".join(lines[max_lines - 1:])]
            lines = list(lines[:max_lines])
            lines[-1] = lines[-1] + "…"

        for i, line in enumerate(lines):
            line = _fit_text_to_width(draw, line, font, width)
            bbox = draw.textbbox((0, 0), line, font=font)
            text_w = bbox[2] - bbox[0]
            if caption_settings.alignment == "left":
                text_x = x
            elif caption_settings.alignment == "right":
                text_x = x + width - text_w
            else:
                text_x = x + (width - text_w) / 2
            if line:
                self._put_text(
                    draw, (text_x, y + i * line_height), line, palette.text, font,
                    copy_text=full_lines[i] if full_lines[i] != line else None,
                )

    def _draw_page_number(self, draw, canvas_w, canvas_h, page_num, total_pages, palette,
                          show_page_number=True):
        """Footer, three centred lines: sheet number ("Planche 1/3"),
        "Planche générée par Planche-Contact" (generated-by notice), then the
        developer and licence credit (the same as the HTML gallery's footer).
        The number alone is optional (LayoutSettings.page_numbering); the two
        credits are always displayed. The positions come from
        layout_engine.FOOTER_*_OFFSET_PX, which also reserves the corresponding
        space below the grid."""
        font = get_font(26)
        font_small = get_font(20)

        lines = []
        if show_page_number:
            lines.append((
                _("sheet.page_label", page=page_num, total=total_pages),
                FOOTER_PAGE_NUMBER_OFFSET_PX, font, palette.text,
            ))
        lines.append((_("sheet.footer"), FOOTER_CREDIT_OFFSET_PX, font_small, palette.text_secondary))
        lines.append((
            _("sheet.footer_credit", name=AUTHOR_NAME),
            FOOTER_LICENSE_OFFSET_PX, font_small, palette.text_secondary,
        ))

        for text, offset_px, line_font, color in lines:
            bbox = draw.textbbox((0, 0), text, font=line_font)
            text_w = bbox[2] - bbox[0]
            self._put_text(draw, ((canvas_w - text_w) / 2, canvas_h - offset_px), text, color, line_font)
