# -*- coding: utf-8 -*-
"""
INVISIBLE text layer laid over the sheets in the PDF.

The PDF is built from the JPEG sheets (one image per page): the text
they carry - title, per-photo captions (file name, date, settings...),
footer - is therefore only pixels, which cannot be selected or copied.
So that one can, for example, copy a file name out of the PDF,
ContactSheetGenerator records every text it draws (`TextRun`) and
PDFExporter places it again here on top of the image, in the
"invisible" rendering mode (the technique used by PDFs produced by
character recognition): the page does not change by a single pixel, but
the text can be selected, copied and found by the PDF reader's search.

The coordinates are those of the sheet, in pixels, origin at the TOP
left; the conversion to the PDF's coordinate system (points, origin at
the BOTTOM left) is done here. Since a sheet is placed in the PDF at a
scale of 1 pixel = 1 point (see PDFExporter), the text lines up exactly
with that of the image.
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .utils import _BUNDLED_FONTS_DIR

logger = logging.getLogger(__name__)

#: PDF rendering mode "invisible text" (neither stroked nor filled).
_INVISIBLE = 3

_FONT_NAMES = {False: "PlancheContact-DejaVuSans", True: "PlancheContact-DejaVuSans-Bold"}
_FONT_FILES = {False: "DejaVuSans.ttf", True: "DejaVuSans-Bold.ttf"}


@dataclass(frozen=True)
class TextRun:
    """A text drawn on a sheet, as the PDF must reproduce it.

    - `text`: what will be copied from the PDF. May be LONGER than what is
      visible: a line truncated with "…" for lack of room on the sheet keeps
      its full text here (a file name copied from the PDF is thus never
      cut off);
    - `x`, `baseline`: origin of the text on the sheet, in pixels (abscissa
      of the left edge, ordinate of the BASELINE), origin at the top left;
    - `size`: font size, in pixels;
    - `width`: width occupied on screen, in pixels (used to match the width
      of the invisible text to that of the visible text);
    - `bold`: bold font or not."""
    text: str
    x: float
    baseline: float
    size: float
    width: float
    bold: bool = False


def _font_path(bold: bool) -> Path:
    return Path(_BUNDLED_FONTS_DIR) / _FONT_FILES[bold]


def _register_fonts() -> Optional[dict]:
    """Registers (once) the DejaVu fonts shipped with the application, the
    same ones that draw the sheets, and returns `{bold: name}` - or None if
    they cannot be found or used (the PDF is then produced without a text
    layer rather than not being produced at all)."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    names = {}
    for bold in (False, True):
        name = _FONT_NAMES[bold]
        try:
            pdfmetrics.getFont(name)
        except KeyError:
            path = _font_path(bold)
            if not path.is_file():
                logger.warning("Police %s introuvable : PDF sans texte sélectionnable.", path)
                return None
            try:
                pdfmetrics.registerFont(TTFont(name, str(path)))
            except Exception as exc:  # unreadable font: give up the text layer
                logger.warning("Police %s inutilisable (%s) : PDF sans texte sélectionnable.", path, exc)
                return None
        names[bold] = name
    return names


def draw_text_layer(pdf_canvas, runs: Iterable[TextRun], sheet_height_px: float,
                    margin_pt: float = 0.0) -> int:
    """Places `runs` as invisible text on the current page of `pdf_canvas`
    (reportlab). The sheet occupies the rectangle whose bottom-left corner
    is at (margin_pt, margin_pt) and whose height is `sheet_height_px`, at a
    scale of 1 pixel = 1 point. Returns the number of texts placed (0 if
    there is nothing to place or if the fonts are missing)."""
    runs = [run for run in runs if run.text and run.size > 0]
    if not runs:
        return 0
    fonts = _register_fonts()
    if fonts is None:
        return 0

    from reportlab.pdfbase.pdfmetrics import stringWidth

    placed = 0
    text = pdf_canvas.beginText()
    text.setTextRenderMode(_INVISIBLE)
    for run in runs:
        font_name = fonts[bool(run.bold)]
        try:
            natural = stringWidth(run.text, font_name, run.size)
        except Exception:
            continue
        # Horizontal stretch so that the invisible text covers exactly the
        # width of the visible text (same font: ~100%, but a text truncated
        # on screen keeps its full text here).
        scale = 100.0 * run.width / natural if natural > 0 and run.width > 0 else 100.0
        text.setFont(font_name, run.size)
        text.setHorizScale(scale)
        text.setTextOrigin(margin_pt + run.x, margin_pt + sheet_height_px - run.baseline)
        text.textOut(run.text)
        placed += 1
    pdf_canvas.drawText(text)
    return placed
