#!/usr/bin/env python3
"""
portfolio.py - Générateur de planches-contact
(Version avec progression correcte + flush)
"""

import sys
import time
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from portfolio.config import Config
from portfolio.scanner import ImageScanner
from portfolio.thumbnail import ThumbnailGenerator
from portfolio.contactsheet import ContactSheetGenerator
from portfolio.pdfexport import PDFExporter
from portfolio.htmlgallery import HTMLGalleryGenerator
from portfolio.csvindex import CSVIndexGenerator
from portfolio.utils import setup_logging


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Générateur de planches contact photographiques")

    parser.add_argument("-i", "--input", required=True, type=Path, help="Dossier source des images")
    parser.add_argument("-o", "--output", type=Path, help="Dossier de sortie")
    parser.add_argument("-r", "--recursive", action="store_true", help="Recherche récursive")
    parser.add_argument("-n", "--num", type=int, default=12, help="Nombre d'images par planche")
    parser.add_argument("--thumb", type=int, default=600, help="Taille des vignettes")
    parser.add_argument("--format", default="A4", choices=["A5", "A4", "A3", "A2", "Letter"])
    parser.add_argument("--title", default=None, help="Titre du projet")
    parser.add_argument("--author", default=None, help="Nom de l'auteur")
    parser.add_argument("--sort", default="date", choices=["date", "name"])
    parser.add_argument("--pdf", action="store_true", help="Générer un PDF")
    parser.add_argument("--html", action="store_true", help="Générer une galerie HTML")
    parser.add_argument("--csv", action="store_true", help="Générer un index CSV")
    parser.add_argument("--html-per-page", type=int, default=48, help="Images par page HTML")
    parser.add_argument("--watermark", default=None, help="Texte du filigrane")
    parser.add_argument("--watermark-orientation", default="Horizontal",
                        choices=["Horizontal", "Diagonale horaire", "Diagonale anti-horaire"],
                        help="Orientation du filigrane")

    return parser.parse_args()


def main():
    args = parse_args()
    start = time.time()

    output_dir = args.output or (args.input / "Portfolio")

    setup_logging(output_dir / "generation.log")
    logger = logging.getLogger(__name__)

    logger.info(f"Démarrage de la génération pour {args.input}")

    config = Config(
        input_dir=args.input,
        output_dir=output_dir,
        recursive=args.recursive,
        sort_by=args.sort,
        num_per_sheet=args.num,
        thumb_size=args.thumb,
        page_format=args.format,
        title=args.title,
        author=args.author,
        generate_pdf=args.pdf,
        generate_html=args.html,
        generate_csv=args.csv,
        html_images_per_page=args.html_per_page,
        watermark_text=args.watermark,
        watermark_orientation=args.watermark_orientation,
    )

    # Phase 1: Scan
    print("PROGRESS:0/100 Scan des images...", flush=True)
    scanner = ImageScanner(config)
    images = scanner.scan()
    print(f"PROGRESS:10/100 {len(images)} images trouvées.", flush=True)

    if not images:
        logger.warning("Aucune image trouvée.")
        print("PROGRESS:100/100 Terminé (aucune image).", flush=True)
        return

    n = config.num_per_sheet
    total_pages = (len(images) + n - 1) // n

    thumb_gen = ThumbnailGenerator(config)
    cs_gen = ContactSheetGenerator(config, thumb_gen)

    planches_dir = output_dir / "planches"
    planches_dir.mkdir(exist_ok=True)
    planche_files = []

    # Phase 2: Contact sheets
    print("PROGRESS:15/100 Génération des planches contact...", flush=True)
    for page_idx in range(total_pages):
        batch = images[page_idx * n : (page_idx + 1) * n]
        page_num = page_idx + 1

        try:
            sheet = cs_gen.create_contact_sheet(batch, page_num, total_pages)
            if sheet:
                p = planches_dir / f"planche_{page_num:03d}.jpg"
                sheet.save(p, "JPEG", quality=95)
                planche_files.append(p)
                progress = 15 + int(55 * (page_num / total_pages))
                print(f"Planche {page_num}/{total_pages} générée", flush=True)
                print(f"PROGRESS:{progress}/100", flush=True)
        except Exception as e:
            logger.error(f"Erreur planche {page_num}: {e}")

    # On force le flush avant de commencer le PDF
    sys.stdout.flush()

    # Phase 3: PDF
    if config.generate_pdf and planche_files:
        print("PROGRESS:75/100 Génération du PDF...", flush=True)
        PDFExporter().create_pdf(planche_files, output_dir / "portfolio.pdf")
        print("PROGRESS:80/100 PDF terminé.", flush=True)

    # Phase 4: CSV
    if config.generate_csv:
        print("PROGRESS:82/100 Génération de l'index CSV...", flush=True)
        CSVIndexGenerator().create(images, output_dir / "index.csv")
        print("PROGRESS:85/100 CSV terminé.", flush=True)

    # Phase 5: HTML Gallery
    if config.generate_html:
        print("PROGRESS:86/100 Génération de la galerie HTML...", flush=True)
        gdir = output_dir / "gallery"
        HTMLGalleryGenerator(config, thumb_gen).create_gallery(images, gdir)
        print("PROGRESS:98/100 Galerie HTML terminée.", flush=True)

    print("PROGRESS:100/100 Terminé avec succès !", flush=True)
    logger.info(f"Terminé en {time.time() - start:.1f} secondes")


if __name__ == "__main__":
    main()
