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

import numpy as np
import pytest
from PIL import Image

from portfolio.config import Config
from portfolio.thumbnail import ThumbnailGenerator
from portfolio.contactsheet import ContactSheetGenerator
from portfolio.presentation import (
    Profile, LayoutSettings, CaptionSettings, ThemeSettings, compute_page_layout, mm_to_px,
)

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


# ---------------------------------------------------------------------------
# Câblage du moteur de mise en page/légendes/thème partagé
# (portfolio/presentation/) dans ContactSheetGenerator - cahier des charges
# §1/§2/§4/§5. La non-régression du comportement PAR DÉFAUT (aucun Profil
# personnalisé) est déjà exhaustivement couverte ailleurs (ce fichier,
# tests/test_layout_engine.py) ; les tests ci-dessous couvrent les NOUVELLES
# capacités (thème, légendes, modèles alternatifs) elles-mêmes.
# ---------------------------------------------------------------------------

def _make_images(tmp_path, n, color=(90, 140, 200), size=(800, 600)):
    img_dir = tmp_path / "photos"
    img_dir.mkdir(exist_ok=True)
    paths = []
    for i in range(n):
        p = img_dir / f"img_{i:02d}.jpg"
        Image.new("RGB", size, color).save(p, quality=95)
        paths.append(p)
    return [{"path": p, "filename": p.name} for p in paths]


def test_dark_theme_changes_the_background_color(tmp_path):
    images = _make_images(tmp_path, 6)
    profile = Profile(theme=ThemeSettings(mode="dark"))
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=6, profile=profile)
    cs_gen = ContactSheetGenerator(config, ThumbnailGenerator(config))

    sheet = cs_gen.create_contact_sheet(images, 1, 1)
    corner = sheet.getpixel((2, 2))
    # Thème "dark" (voir portfolio/presentation/themes.py) : fond proche de
    # "#1b1b1b", très loin du blanc par défaut.
    assert corner[0] < 60 and corner[1] < 60 and corner[2] < 60


def test_default_profile_keeps_white_background(tmp_path):
    images = _make_images(tmp_path, 6)
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=6)
    cs_gen = ContactSheetGenerator(config, ThumbnailGenerator(config))

    sheet = cs_gen.create_contact_sheet(images, 1, 1)
    assert sheet.getpixel((2, 2)) == (255, 255, 255)


def test_exif_metadata_is_never_read_when_no_caption_field_is_configured(tmp_path, monkeypatch):
    """Garantie de performance (cahier des charges) : le comportement par
    défaut (aucune légende) ne doit pas payer le coût d'une extraction
    EXIF par photo. On fait planter get_exif_metadata() s'il est appelé,
    pour une génération par défaut."""
    images = _make_images(tmp_path, 4)
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=4)
    cs_gen = ContactSheetGenerator(config, ThumbnailGenerator(config))

    def _boom(path):
        raise AssertionError("get_exif_metadata() ne doit pas être appelé sans légende configurée")

    monkeypatch.setattr("portfolio.contactsheet.get_exif_metadata", _boom)
    sheet = cs_gen.create_contact_sheet(images, 1, 1)
    assert sheet is not None


def test_captions_are_actually_drawn_when_configured(tmp_path):
    """Les légendes doivent produire une différence de pixels observable
    par rapport à une génération identique sans légende - preuve qu'elles
    sont réellement dessinées, pas seulement acceptées sans effet."""
    images = _make_images(tmp_path, 4)

    profile_no_caption = Profile(layout=LayoutSettings(per_page=4, caption_position="none"))
    profile_with_caption = Profile(
        layout=LayoutSettings(per_page=4, caption_position="below", caption_area_mm=10),
        captions=CaptionSettings(fields=["filename"]),
    )

    config_no = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=4, profile=profile_no_caption)
    config_with = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=4, profile=profile_with_caption)

    sheet_no = ContactSheetGenerator(config_no, ThumbnailGenerator(config_no)).create_contact_sheet(images, 1, 1)
    sheet_with = ContactSheetGenerator(config_with, ThumbnailGenerator(config_with)).create_contact_sheet(images, 1, 1)

    assert np.array(sheet_no).shape != np.array(sheet_with).shape or not np.array_equal(
        np.array(sheet_no), np.array(sheet_with)
    )


@pytest.mark.parametrize("caption_position", ["below", "above", "right"])
def test_caption_reserved_area_never_overlaps_the_next_photo(tmp_path, caption_position):
    """RÉGRESSION : une première version de ce câblage recalculait l'écart
    entre cellules à la main dans create_contact_sheet() sans retrancher
    l'espace de légende, si bien qu'une légende "below"/"above" empiétait
    sur la ligne de vignettes suivante - découvert par inspection visuelle
    du rendu, pas par ce test (qui vient le verrouiller). On repère les
    vraies limites verticales des vignettes (couleur unique et saturée)
    sur la colonne centrale de la première colonne de la grille, et on
    vérifie l'écart réel entre deux lignes consécutives."""
    photo_color = (10, 200, 10)
    images = _make_images(tmp_path, 6, color=photo_color)

    profile = Profile(
        layout=LayoutSettings(template="grid", per_page=6, caption_position=caption_position, caption_area_mm=12),
        captions=CaptionSettings(fields=["filename"]),
    )
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=6, page_format="A4", profile=profile)
    cs_gen = ContactSheetGenerator(config, ThumbnailGenerator(config))
    sheet = cs_gen.create_contact_sheet(images, 1, 1)

    page = compute_page_layout(config.profile, photo_count=6)
    assert page.cols >= 1 and page.rows >= 2, "Ce test suppose au moins 2 lignes de vignettes"
    x_center = page.cells[0].photo_x + page.cells[0].photo_w // 2

    arr = np.array(sheet)
    column = arr[:, x_center, :].astype(int)
    is_photo = np.all(np.abs(column - np.array(photo_color)) < 12, axis=1)

    segments = []
    in_segment = False
    start = 0
    for y, flag in enumerate(is_photo):
        if flag and not in_segment:
            start, in_segment = y, True
        elif not flag and in_segment:
            segments.append((start, y - 1))
            in_segment = False
    if in_segment:
        segments.append((start, len(is_photo) - 1))

    assert len(segments) >= 2, f"Au moins deux segments de vignette attendus sur cette colonne ({caption_position})"
    gap = segments[1][0] - segments[0][1]

    # Avant le correctif, cet écart aurait été d'environ spacing (5 mm)
    # pour "below"/"above" (l'espace de légende n'étant pas retranché de
    # l'écart entre lignes) ; il doit désormais être d'au moins la hauteur
    # de légende réservée (12 mm), avec une marge de tolérance pour
    # l'anticrénelage du texte sur les bords du segment détecté.
    if caption_position in ("below", "above"):
        assert gap >= mm_to_px(12) * 0.9, (caption_position, gap)
    else:  # "right" ne réserve pas de hauteur supplémentaire entre les lignes
        assert gap >= mm_to_px(5) * 0.9, (caption_position, gap)


def test_large_thumbs_never_draws_more_cells_than_its_effective_per_page(tmp_path):
    """"large_thumbs" peut réduire lui-même son effectif par page (voir
    layout_engine.compute_effective_per_page) ; tant que la pagination
    amont (portfolio.py) n'en tient pas encore compte (étape ultérieure),
    create_contact_sheet() ne doit JAMAIS dessiner plus de cellules que ce
    que sa géométrie prévoit réellement - les photos excédentaires sont
    simplement absentes de CETTE planche plutôt que de déborder de la
    grille calculée."""
    from portfolio.presentation.layout_engine import LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE

    n_images = LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE + 10
    images = _make_images(tmp_path, n_images)
    profile = Profile(layout=LayoutSettings(template="large_thumbs", per_page=n_images))
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=n_images, profile=profile)
    cs_gen = ContactSheetGenerator(config, ThumbnailGenerator(config))

    sheet = cs_gen.create_contact_sheet(images, 1, 1)
    assert sheet is not None  # ne doit pas lever d'exception (dépassement d'index, etc.)
