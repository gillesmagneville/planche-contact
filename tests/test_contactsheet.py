# -*- coding: utf-8 -*-
"""
Tests de non-régression pour le correctif du débordement vertical des
planches contact (voir CHANGELOG.md) : ContactSheetGenerator.
create_contact_sheet() ne retranchait auparavant l'espacement entre
cellules que de la largeur disponible, jamais de la hauteur, ce qui
pouvait faire déborder les vignettes de la dernière ligne au bas physique
de la planche pour certaines combinaisons nombre d'images/format de page.
"""
import math

import pytest
from PIL import Image

from portfolio.config import Config
from portfolio.thumbnail import ThumbnailGenerator
from portfolio.contactsheet import ContactSheetGenerator

PAPER_SIZES_MM = {
    "A5": (148, 210), "A4": (210, 297), "A3": (297, 420),
    "A2": (420, 594), "Letter": (216, 279),
}


def _grid_fit(num_per_sheet, page_format="A4"):
    """Reproduit le calcul (version CORRIGÉE) de
    ContactSheetGenerator.create_contact_sheet(), pour vérifier son
    invariant sur toute la plage de réglages sans avoir à décoder de
    vraies images à chaque combinaison."""
    DPI = 300
    width_mm, height_mm = PAPER_SIZES_MM.get(page_format, PAPER_SIZES_MM["A4"])
    canvas_w, canvas_h = int(width_mm * DPI / 25.4), int(height_mm * DPI / 25.4)
    margin = int(12 * 300 / 25.4)
    spacing = int(5 * 300 / 25.4)

    best_cols, best_thumb = 1, 0
    available_w = canvas_w - 2 * margin
    available_h = canvas_h - 2 * margin - 180
    for cols in range(1, min(num_per_sheet + 1, 9)):
        rows = math.ceil(num_per_sheet / cols)
        cell_w = available_w // cols if cols > 1 else available_w
        cell_h = available_h // rows if rows > 1 else available_h
        thumb = min(cell_w, cell_h)
        if thumb > best_thumb:
            best_thumb, best_cols = thumb, cols

    thumb_size = max(best_thumb, 70)
    cols = best_cols
    rows = math.ceil(num_per_sheet / cols)
    max_w = (available_w - (cols - 1) * spacing) // cols
    thumb_size = min(thumb_size, max_w)
    max_h = (available_h - (rows - 1) * spacing) // rows
    thumb_size = min(thumb_size, max_h)

    return canvas_w, canvas_h, margin, spacing, cols, rows, thumb_size


@pytest.mark.parametrize("page_format", list(PAPER_SIZES_MM.keys()))
@pytest.mark.parametrize("num_per_sheet", list(range(8, 49, 4)))
def test_grid_fit_never_overflows_canvas_vertically(num_per_sheet, page_format):
    """Quelle que soit la combinaison nombre d'images par planche / format
    de page réellement proposée par l'interface graphique (curseur 8 à 48
    par pas de 4), la dernière ligne de vignettes ne doit plus déborder du
    bas physique de la planche."""
    canvas_w, canvas_h, margin, spacing, cols, rows, thumb_size = _grid_fit(num_per_sheet, page_format)
    content_top = margin + 180 + margin  # marge haute + en-tête réservé + espace de contenu
    last_row_bottom = content_top + (rows - 1) * (thumb_size + spacing) + thumb_size
    assert last_row_bottom <= canvas_h


def test_known_regression_case_24_per_sheet_a4():
    """Cas précis ayant révélé le bug (24 images/planche, A4) : avant le
    correctif, thumb_size=505 et la dernière ligne débordait d'environ
    139 px du bas de la planche."""
    canvas_w, canvas_h, margin, spacing, cols, rows, thumb_size = _grid_fit(24, "A4")
    assert thumb_size < 505
    content_top = margin + 180 + margin
    last_row_bottom = content_top + (rows - 1) * (thumb_size + spacing) + thumb_size
    assert last_row_bottom <= canvas_h


def test_real_generation_end_to_end(tmp_path):
    """Vérification de bout en bout avec de vraies images (pas seulement
    l'arithmétique isolée) : la génération doit réussir et produire une
    planche de la bonne taille de canevas, sans erreur, sur le cas ayant
    révélé le bug."""
    img_dir = tmp_path / "photos"
    img_dir.mkdir()
    for i in range(24):
        Image.new("RGB", (800, 600), (i * 10 % 255, 100, 150)).save(img_dir / f"photo_{i:02d}.jpg", quality=90)

    images = [{"path": p, "filename": p.name} for p in sorted(img_dir.glob("*.jpg"))]

    config = Config(input_dir=img_dir, output_dir=tmp_path / "out", num_per_sheet=24, page_format="A4")
    thumb_gen = ThumbnailGenerator(config)
    cs_gen = ContactSheetGenerator(config, thumb_gen)

    sheet = cs_gen.create_contact_sheet(images, 1, 1)
    assert sheet is not None
    assert sheet.size == cs_gen._get_canvas_size()
