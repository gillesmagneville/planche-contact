import logging
from pathlib import Path

from reportlab.pdfgen import canvas
from PIL import Image as PILImage


class PDFExporter:
    def create_pdf(self, planche_files: list[Path], output_path: Path) -> None:
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
                c.showPage()

            except Exception as e:
                logger.error(f"Erreur lors de l'ajout de {planche.name} au PDF : {e}")

        c.save()
        logger.info(f"PDF créé avec succès : {output_path}")
