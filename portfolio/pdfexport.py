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
        """Assemble les planches en un PDF (une planche par page).

        `text_runs` : `{chemin de planche: [TextRun, ...]}` (voir
        textlayer.py, ContactSheetGenerator.last_text_runs). Quand il est
        fourni, le texte de chaque planche (titre, légendes, pied de page)
        est posé en INVISIBLE par-dessus l'image : la page est visuellement
        identique, mais son texte est sélectionnable, copiable et
        recherchable. Sans lui, le PDF ne contient que les images."""
        if not planche_files:
            logging.warning("Aucune planche à exporter en PDF.")
            return

        logger = logging.getLogger(__name__)

        # On prend les dimensions de la première planche (toutes devraient être identiques)
        first_planche = sorted(planche_files)[0]
        with PILImage.open(first_planche) as img:
            img_w, img_h = img.size

        # Marge symétrique autour de chaque planche
        pdf_margin = 12   # ~4,2 mm de chaque côté

        page_w = img_w + (2 * pdf_margin)
        page_h = img_h + (2 * pdf_margin)

        c = canvas.Canvas(str(output_path))
        c.setTitle("Portfolio")

        for planche in sorted(planche_files):
            try:
                c.setPageSize((page_w, page_h))

                # On centre parfaitement l'image
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
                        # Le texte sélectionnable est un plus : sa
                        # défaillance ne doit jamais coûter la page.
                        logger.warning(f"Texte sélectionnable ignoré pour {planche.name} : {e}")
                c.showPage()

            except Exception as e:
                logger.error(f"Erreur lors de l'ajout de {planche.name} au PDF : {e}")

        c.save()
        logger.info(_("engine.log_pdf_created", path=output_path))
