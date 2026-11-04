import logging
from pathlib import Path
from typing import Optional

from reportlab.pdfgen import canvas
from PIL import Image as PILImage
from .i18n import _
from .textlayer import draw_text_layer


class PDFExporter:
    def create_pdf(self, planche_files: list[Path], output_path: Path,
                   text_runs: Optional[dict] = None) -> None:
        """Assembles the sheets into a PDF (one sheet per page).

        `text_runs`: `{sheet path: [TextRun, ...]}` (see textlayer.py,
        ContactSheetGenerator.last_text_runs). When supplied, the text of each
        sheet (title, captions, footer) is laid over the image as INVISIBLE
        text: the page looks identical, but its text can be selected, copied
        and searched. Without it, the PDF contains only the images."""
        if not planche_files:
            logging.warning("Aucune planche à exporter en PDF.")
            return

        logger = logging.getLogger(__name__)

        # We take the dimensions of the first sheet (they should all be identical)
        first_planche = sorted(planche_files)[0]
        with PILImage.open(first_planche) as img:
            img_w, img_h = img.size

        # Symmetric margin around each sheet
        pdf_margin = 12   # ~4.2 mm on each side

        page_w = img_w + (2 * pdf_margin)
        page_h = img_h + (2 * pdf_margin)

        c = canvas.Canvas(str(output_path))
        c.setTitle("Portfolio")

        for planche in sorted(planche_files):
            try:
                c.setPageSize((page_w, page_h))

                # The image is perfectly centred
                c.drawImage(
                    str(planche),
                    pdf_margin,
                    pdf_margin,
                    width=img_w,
                    height=img_h
                )
                runs = (text_runs or {}).get(planche)
                if runs:
                    try:
                        with PILImage.open(planche) as sheet_img:
                            sheet_h = sheet_img.size[1]
                        draw_text_layer(c, runs, sheet_h, pdf_margin)
                    except Exception as e:
                        # The selectable text is a bonus: its failure must
                        # never cost the page.
                        logger.warning(f"Texte sélectionnable ignoré pour {planche.name} : {e}")
                c.showPage()

            except Exception as e:
                logger.error(f"Erreur lors de l'ajout de {planche.name} au PDF : {e}")

        c.save()
        logger.info(_("engine.log_pdf_created", path=output_path))
