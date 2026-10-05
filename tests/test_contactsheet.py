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
from pathlib import Path

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


def test_fit_text_to_width_truncates_with_ellipsis_when_too_wide():
    """Filet de sécurité (signalé par l'utilisateur : "les légendes se
    chevauchent et sont illisibles") : une ligne dont le texte rendu dépasse
    la largeur disponible doit être tronquée avec une ellipsis ("…"),
    jamais dessinée telle quelle - sans quoi elle déborde dans la cellule
    voisine. Depuis le retour à la ligne des légendes
    (presentation.captions.layout_caption_lines()), ce filet ne s'applique
    plus qu'à un MOT isolé plus large que la cellule, jamais à une légende
    ordinaire de plusieurs champs (voir les tests suivants)."""
    from PIL import ImageDraw
    from portfolio.contactsheet import _fit_text_to_width
    from portfolio.utils import get_font

    img = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(img)
    font = get_font(30)
    long_text = "img_00.jpg · Canon EOS R5 · RF 24-70mm F2.8 L IS USM · 6000 × 4000"

    fitted = _fit_text_to_width(draw, long_text, font, max_width=300)
    bbox = draw.textbbox((0, 0), fitted, font=font)
    assert bbox[2] - bbox[0] <= 300
    assert fitted != long_text
    assert fitted.endswith("…")

    # Un texte qui tient déjà dans max_width n'est jamais modifié.
    short_text = "img_00.jpg"
    assert _fit_text_to_width(draw, short_text, font, max_width=300) == short_text


def test_long_caption_with_several_fields_does_not_bleed_into_the_next_column(tmp_path, monkeypatch):
    """RÉGRESSION rapportée par l'utilisateur : avec plusieurs champs de
    légende sélectionnés et le réglage par défaut (lines=1), les champs
    sont joints sur une seule ligne (voir
    presentation.captions.resolve_caption_lines()) qui pouvait être bien
    plus large qu'une vignette, débordant alors massivement dans la
    colonne voisine ("les légendes se chevauchent et sont illisibles").

    La zone de légende réelle sur l'image rendue est décalée verticalement
    (`y_shift`, voir create_contact_sheet()) par rapport aux coordonnées
    brutes de compute_page_layout() - ce test repère donc le bandeau
    réel par la même technique que
    test_caption_reserved_area_never_overlaps_the_next_photo ci-dessus
    (détection des segments de vignette par couleur), plutôt que de
    recalculer ce décalage à la main."""
    photo_color = (10, 200, 10)
    images = _make_images(tmp_path, 6, color=photo_color)

    def fake_metadata(path):
        return {
            "filename": Path(path).name,
            "camera": "Canon EOS R5",
            "lens": "RF 24-70mm F2.8 L IS USM",
            "dimensions": (6000, 4000),
        }

    monkeypatch.setattr("portfolio.contactsheet.get_exif_metadata", fake_metadata)

    profile = Profile(
        layout=LayoutSettings(template="grid", per_page=6, caption_position="below", caption_area_mm=10),
        captions=CaptionSettings(fields=["filename", "camera", "lens", "dimensions"], lines=1, font_size=9),
    )
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=6, page_format="A4", profile=profile)
    cs_gen = ContactSheetGenerator(config, ThumbnailGenerator(config))
    sheet = cs_gen.create_contact_sheet(images, 1, 1)

    page = compute_page_layout(config.profile, photo_count=6)
    assert page.cols >= 2 and page.rows >= 2, "ce test suppose au moins 2 colonnes et 2 lignes"
    cell0, cell1 = page.cells[0], page.cells[1]
    x_center = cell0.photo_x + cell0.photo_w // 2

    arr = np.array(sheet)
    column = arr[:, x_center, :].astype(int)
    is_photo = np.all(np.abs(column - np.array(photo_color)) < 12, axis=1)

    segments, in_segment, start = [], False, 0
    for y, flag in enumerate(is_photo):
        if flag and not in_segment:
            start, in_segment = y, True
        elif not flag and in_segment:
            segments.append((start, y - 1))
            in_segment = False
    if in_segment:
        segments.append((start, len(is_photo) - 1))

    assert len(segments) >= 2, "au moins deux segments de vignette attendus sur cette colonne"
    caption_band_top, caption_band_bottom = segments[0][1] + 1, segments[1][0]

    band = arr[caption_band_top:caption_band_bottom, :, :].astype(int)
    is_text = np.any(band < 128, axis=2)  # pixel sombre (texte) sur fond blanc par défaut

    # La gouttière entre les deux colonnes (cell1 a sa PROPRE légende, donc
    # on ne peut pas vérifier au-delà de cell1.photo_x - ce serait alors sa
    # légende à elle, pas un débordement de cell0) : aucun pixel de texte
    # ne doit y apparaître. Avant le correctif, le texte de cell0 non
    # tronqué traversait largement cette gouttière (et bien au-delà).
    gutter = is_text[:, cell0.photo_x + cell0.photo_w:cell1.photo_x]
    assert not gutter.any(), (
        "la légende déborde dans la gouttière vers la colonne suivante - "
        "texte non tronqué à la largeur de la cellule"
    )
    # Et la légende doit bien avoir produit du texte visible DANS sa
    # propre cellule (preuve que le test exerce réellement le dessin,
    # pas un cas où rien n'aurait été dessiné du tout).
    assert is_text[:, cell0.photo_x:cell0.photo_x + cell0.photo_w].any()


def _fake_rich_metadata(path):
    return {
        "filename": Path(path).name,
        "camera": "Canon EOS R5",
        "lens": "RF 24-70mm F2.8 L IS USM",
        "focal_length": 50.0,
        "aperture": 2.8,
        "shutter_speed": 1 / 250,
        "iso": 400,
        "dimensions": (6000, 4000),
    }


def _caption_generator(tmp_path, monkeypatch, n_photos=6, color=(90, 140, 200), **caption_kwargs):
    monkeypatch.setattr("portfolio.contactsheet.get_exif_metadata", _fake_rich_metadata)
    images = _make_images(tmp_path, n_photos, color=color)
    profile = Profile(
        layout=LayoutSettings(template="grid", per_page=n_photos, caption_position="below", caption_area_mm=8),
        captions=CaptionSettings(
            fields=["filename", "camera", "lens", "focal_length", "aperture", "shutter_speed", "iso", "dimensions"],
            lines=1, font_size=9, **caption_kwargs,
        ),
    )
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=n_photos,
                    page_format="A4", profile=profile)
    return images, config, ContactSheetGenerator(config, ThumbnailGenerator(config))


def test_plan_page_wraps_captions_so_that_no_information_is_truncated(tmp_path, monkeypatch):
    """RÉGRESSION rapportée par l'utilisateur : "les informations sont
    tronquées sous les photos (elles se terminent par « ... »)". Avec
    plusieurs champs et lines=1, la légende tenait sur une seule ligne,
    tronquée par une ellipsis pour ne pas déborder. Elle doit maintenant
    passer à la ligne : TOUS les champs visibles, aucune ligne plus large
    que la vignette, et une hauteur réservée suffisante pour toutes les
    lignes (sinon la dernière déborderait dans la rangée suivante)."""
    from PIL import ImageDraw
    from portfolio.presentation import pt_to_px, CAPTION_LINE_SPACING_PX
    from portfolio.utils import get_font

    images, config, cs_gen = _caption_generator(tmp_path, monkeypatch)

    page, texts = cs_gen._plan_page(images)

    assert set(texts) == set(range(6))
    font_px = max(6, pt_to_px(9))
    font = get_font(font_px)
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for idx, lines in texts.items():
        assert len(lines) > 1, "la légende doit passer à la ligne, pas rester sur une seule ligne"
        assert not any("…" in line for line in lines), "aucune information ne doit être tronquée"
        joined = " ".join(lines)
        for expected in (f"img_{idx:02d}", "Canon EOS R5", "RF 24-70mm F2.8 L IS USM", "f/2.8", "ISO 400", "6000 × 4000"):
            assert expected in joined, (idx, expected)
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            assert bbox[2] - bbox[0] <= page.thumb_size, (idx, line)

    needed_h = max(len(lines) for lines in texts.values()) * (font_px + CAPTION_LINE_SPACING_PX)
    assert page.cells[0].caption_h >= needed_h


def test_wrapped_captions_leave_no_text_in_the_gutter_between_columns(tmp_path, monkeypatch):
    """Rendu réel de bout en bout (create_contact_sheet) avec légendes
    passées à la ligne : aucun pixel de texte dans la gouttière entre deux
    colonnes, et du texte bien présent sous chaque vignette de la première
    rangée - sur toute la hauteur de la zone réservée, pas seulement la
    première ligne."""
    photo_color = (10, 200, 10)
    images, config, cs_gen = _caption_generator(tmp_path, monkeypatch, color=photo_color)

    sheet = cs_gen.create_contact_sheet(images, 1, 1)
    page, texts = cs_gen._plan_page(images)
    assert page.cols >= 2 and page.rows >= 2

    cell0, cell1 = page.cells[0], page.cells[1]
    arr = np.array(sheet).astype(int)
    column = arr[:, cell0.photo_x + cell0.photo_w // 2, :]
    is_photo = np.all(np.abs(column - np.array(photo_color)) < 12, axis=1)
    segments, in_segment, start = [], False, 0
    for y, flag in enumerate(is_photo):
        if flag and not in_segment:
            start, in_segment = y, True
        elif not flag and in_segment:
            segments.append((start, y - 1))
            in_segment = False
    assert len(segments) >= 2
    band = arr[segments[0][1] + 1:segments[1][0], :, :]
    is_text = np.any(band < 128, axis=2)

    assert not is_text[:, cell0.photo_x + cell0.photo_w:cell1.photo_x].any()
    # Le texte occupe plusieurs lignes : l'étendue verticale des pixels
    # sombres sous la première vignette prouve que TOUTES les lignes sont
    # bien dessinées (et donc visibles), pas seulement la première.
    from portfolio.presentation import pt_to_px, CAPTION_LINE_SPACING_PX
    line_height = max(6, pt_to_px(9)) + CAPTION_LINE_SPACING_PX
    n_lines = len(texts[0])
    assert n_lines >= 3
    own_cell = is_text[:, cell0.photo_x:cell0.photo_x + cell0.photo_w]
    text_rows = np.where(own_cell.any(axis=1))[0]
    assert text_rows.size > 0
    assert text_rows.max() - text_rows.min() >= (n_lines - 1) * line_height


def test_plan_page_does_not_read_exif_without_a_caption(tmp_path, monkeypatch):
    """Aucun coût par défaut : sans légende positionnée sous/sur/à côté de
    la photo (comportement par défaut), la planification ne doit lire AUCUNE
    métadonnée EXIF (un ou plusieurs accès fichier par photo)."""
    def boom(path):
        raise AssertionError("get_exif_metadata ne doit pas être appelée sans légende")

    monkeypatch.setattr("portfolio.contactsheet.get_exif_metadata", boom)
    images = _make_images(tmp_path, 4)

    for profile in (
        Profile(),  # défaut : ni position ni champs
        Profile(captions=CaptionSettings(fields=["filename"])),  # champs mais position "none"
        Profile(layout=LayoutSettings(caption_position="below")),  # position mais aucun champ
    ):
        config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=4, profile=profile)
        cs_gen = ContactSheetGenerator(config, ThumbnailGenerator(config))
        page, texts = cs_gen._plan_page(images)
        assert texts == {}
        assert len(page.cells) == 4


def test_draw_caption_never_draws_more_lines_than_the_reserved_height(tmp_path):
    """Filet de sécurité de _draw_caption() : plus de lignes que la hauteur
    réservée n'en contient (légende "à droite" sur une petite vignette, ou
    plafond MAX_AUTO_CAPTION_LINES atteint) -> les lignes en trop sont
    supprimées, jamais dessinées dans l'espace de la photo suivante."""
    from PIL import ImageDraw
    from portfolio.presentation import pt_to_px, CAPTION_LINE_SPACING_PX, resolve_theme

    profile = Profile(captions=CaptionSettings(fields=["filename"], font_size=9))
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", profile=profile)
    cs_gen = ContactSheetGenerator(config, ThumbnailGenerator(config))

    canvas = Image.new("RGB", (800, 600), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    line_height = max(6, pt_to_px(9)) + CAPTION_LINE_SPACING_PX
    y0 = 20
    cs_gen._draw_caption(
        draw, [f"ligne {i}" for i in range(6)], 10, y0, 700, 2 * line_height,
        profile.captions, resolve_theme(profile.theme),
    )

    arr = np.array(canvas).astype(int)
    dark_rows = np.where(np.any(arr < 128, axis=(1, 2)))[0]
    assert dark_rows.size > 0, "le texte doit bien être dessiné"
    # Tolérance de quelques pixels pour le jambage (descendante) de la
    # dernière ligne autorisée, mais certainement pas 4 lignes de plus.
    assert dark_rows.max() < y0 + 2 * line_height + 8


# ---------------------------------------------------------------------------
# Photo collée à sa légende (au lieu de rester en haut à gauche de la cellule
# carrée, avec un vide sous les photos en paysage).
# ---------------------------------------------------------------------------

def test_thumb_offset_sits_the_photo_against_its_caption():
    from portfolio.contactsheet import _thumb_offset

    landscape, portrait = (400, 300), (300, 400)  # dans une cellule 400 x 400
    # "below" : photo posée sur sa légende (alignée en bas), centrée par défaut
    assert _thumb_offset("below", "center", landscape, 400) == (0, 100)
    assert _thumb_offset("below", "center", portrait, 400) == (50, 0)
    # horizontalement, la photo suit l'alignement du texte
    assert _thumb_offset("below", "left", portrait, 400) == (0, 0)
    assert _thumb_offset("below", "right", portrait, 400) == (100, 0)
    # "above" : photo collée sous sa légende (alignée en haut)
    assert _thumb_offset("above", "center", landscape, 400) == (0, 0)
    # "right" : photo collée contre sa légende (alignée à droite)
    assert _thumb_offset("right", "center", portrait, 400) == (100, 0)
    assert _thumb_offset("right", "center", landscape, 400) == (0, 0)
    # sans légende : photo CENTRÉE dans sa cellule, dans les deux sens (elle
    # était auparavant collée en haut à gauche, d'où un ensemble de photos
    # décalé vers le haut et la gauche de la page)
    assert _thumb_offset("none", "center", landscape, 400) == (0, 50)
    assert _thumb_offset("none", "center", portrait, 400) == (50, 0)
    assert _thumb_offset("none", "left", portrait, 400) == (50, 0)  # sans légende, l'alignement du texte n'a pas de sens
    assert _thumb_offset("none", "center", (400, 400), 400) == (0, 0)
    assert _thumb_offset("none", "center", (500, 500), 400) == (0, 0)
    # jamais de décalage négatif si la vignette dépasse la cellule
    assert _thumb_offset("below", "center", (500, 500), 400) == (0, 0)


def _photo_segments(column, photo_color):
    is_photo = np.all(np.abs(column - np.array(photo_color)) < 12, axis=1)
    segments, in_segment, start = [], False, 0
    for y, flag in enumerate(is_photo):
        if flag and not in_segment:
            start, in_segment = y, True
        elif not flag and in_segment:
            segments.append((start, y - 1))
            in_segment = False
    if in_segment:
        segments.append((start, len(is_photo) - 1))
    return segments


def test_landscape_photo_has_its_caption_right_under_it(tmp_path, monkeypatch):
    """Demande de l'utilisateur : « resserrer l'espace » entre une photo en
    paysage et sa légende. La vignette 4:3 n'occupait que 3/4 de sa cellule
    carrée, collée en haut, et la légende démarrait sous la CELLULE : un
    vide d'un quart de vignette les séparait. Désormais la photo est posée
    sur sa légende : seul l'écart voulu (CAPTION_PHOTO_GAP_PX) subsiste."""
    from portfolio.presentation import pt_to_px, CAPTION_PHOTO_GAP_PX

    photo_color = (10, 200, 10)
    images, config, cs_gen = _caption_generator(tmp_path, monkeypatch, color=photo_color)
    sheet = cs_gen.create_contact_sheet(images, 1, 1)
    page, _ = cs_gen._plan_page(images)
    cell0 = page.cells[0]

    arr = np.array(sheet).astype(int)
    segments = _photo_segments(arr[:, cell0.photo_x + cell0.photo_w // 2, :], photo_color)
    assert len(segments) >= 2
    photo_bottom, next_photo_top = segments[0][1], segments[1][0]

    band = arr[photo_bottom + 1:next_photo_top, cell0.photo_x:cell0.photo_x + cell0.photo_w, :]
    text_rows = np.where(np.any(band < 128, axis=(1, 2)))[0]
    assert text_rows.size > 0
    gap_to_text = int(text_rows.min())  # lignes vides entre le bas de la photo et le 1er pixel de texte

    font_px = max(6, pt_to_px(9))
    assert CAPTION_PHOTO_GAP_PX <= gap_to_text < CAPTION_PHOTO_GAP_PX + font_px, (
        f"écart photo/légende de {gap_to_text}px : attendu l'écart voulu "
        f"({CAPTION_PHOTO_GAP_PX}px) plus l'approche de la lettre, pas le vide d'une cellule carrée"
    )


def test_portrait_photo_is_centered_above_its_centered_caption(tmp_path, monkeypatch):
    """Une photo en portrait (plus étroite que sa cellule carrée) était
    collée à GAUCHE de la cellule alors que sa légende était centrée : elle
    suit désormais l'alignement de la légende."""
    photo_color = (10, 200, 10)
    monkeypatch.setattr("portfolio.contactsheet.get_exif_metadata", _fake_rich_metadata)
    images = _make_images(tmp_path, 6, color=photo_color, size=(600, 800))
    profile = Profile(
        layout=LayoutSettings(template="grid", per_page=6, caption_position="below", caption_area_mm=8),
        captions=CaptionSettings(fields=["filename"], lines=1, font_size=9, alignment="center"),
    )
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=6,
                    page_format="A4", profile=profile)
    cs_gen = ContactSheetGenerator(config, ThumbnailGenerator(config))
    sheet = cs_gen.create_contact_sheet(images, 1, 1)
    page, _ = cs_gen._plan_page(images)
    cell0 = page.cells[0]

    arr = np.array(sheet).astype(int)
    center_x = cell0.photo_x + cell0.photo_w // 2
    segments = _photo_segments(arr[:, center_x, :], photo_color)
    assert segments, "la colonne centrale de la cellule doit traverser la photo"
    row = arr[(segments[0][0] + segments[0][1]) // 2, :, :]
    cols = np.where(np.all(np.abs(row - np.array(photo_color)) < 12, axis=1))[0]
    cols = cols[(cols >= cell0.photo_x) & (cols < cell0.photo_x + cell0.photo_w)]

    left_margin = int(cols.min() - cell0.photo_x)
    right_margin = int(cell0.photo_x + cell0.photo_w - 1 - cols.max())
    assert left_margin > 0, "une photo en portrait doit être plus étroite que sa cellule"
    assert abs(left_margin - right_margin) <= 1, (left_margin, right_margin)


# ---------------------------------------------------------------------------
# Mode d'ajustement "Remplir" (fit_mode="cover") : la photo est recadrée en
# carré pour remplir toute sa cellule. Ce réglage était exposé mais jamais
# lu par le rendu.
# ---------------------------------------------------------------------------

def _render_with_fit_mode(tmp_path, fit_mode, photo_color, **layout_kwargs):
    # 2000 x 1500 (paysage 4:3), plus grand que la cellule : une vignette
    # n'est jamais AGRANDIE (ni en "contain" ni en "cover"), donc des photos
    # plus petites que la cellule ne la rempliraient pas, par construction.
    images = _make_images(tmp_path, 6, color=photo_color, size=(2000, 1500))
    profile = Profile(layout=LayoutSettings(template="grid", per_page=6, fit_mode=fit_mode, **layout_kwargs))
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=6,
                    page_format="A4", profile=profile)
    cs_gen = ContactSheetGenerator(config, ThumbnailGenerator(config))
    page, _ = cs_gen._plan_page(images)
    return np.array(cs_gen.create_contact_sheet(images, 1, 1)).astype(int), page


def _photo_extent(arr, page, photo_color):
    """(hauteur, largeur) en pixels de la photo de la 1re cellule, mesurées
    sur une ligne et une colonne qui la traversent en son centre."""
    cell = page.cells[0]
    x_center = cell.photo_x + cell.photo_w // 2
    segments = _photo_segments(arr[:, x_center, :], photo_color)
    top, bottom = segments[0]
    row = arr[(top + bottom) // 2, :, :]
    cols = np.where(np.all(np.abs(row - np.array(photo_color)) < 12, axis=1))[0]
    cols = cols[(cols >= cell.photo_x) & (cols < cell.photo_x + cell.photo_w)]
    return bottom - top + 1, int(cols.max() - cols.min() + 1)


def test_cover_fit_mode_fills_the_whole_square_cell_while_contain_keeps_the_proportions(tmp_path):
    photo_color = (10, 200, 10)
    contain_sheet, page = _render_with_fit_mode(tmp_path, "contain", photo_color)
    cover_sheet, cover_page = _render_with_fit_mode(tmp_path, "cover", photo_color)

    # Le mode d'ajustement ne change PAS la géométrie de la grille.
    assert cover_page.thumb_size == page.thumb_size

    contain_h, contain_w = _photo_extent(contain_sheet, page, photo_color)
    cover_h, cover_w = _photo_extent(cover_sheet, cover_page, photo_color)

    # "contain" : photo 4:3 entière, donc plus large que haute.
    assert abs(contain_w - page.thumb_size) <= 1
    assert abs(contain_h - round(page.thumb_size * 0.75)) <= 2
    # "cover" : toute la cellule carrée est remplie.
    assert abs(cover_w - page.thumb_size) <= 1
    assert abs(cover_h - page.thumb_size) <= 1


def test_cover_fit_mode_leaves_no_gap_between_photo_and_caption_beyond_the_wanted_one(tmp_path, monkeypatch):
    """Avec une légende, une photo recadrée remplit sa cellule : seul
    l'écart voulu (CAPTION_PHOTO_GAP_PX) la sépare de son texte."""
    from portfolio.presentation import pt_to_px, CAPTION_PHOTO_GAP_PX

    photo_color = (10, 200, 10)
    monkeypatch.setattr("portfolio.contactsheet.get_exif_metadata", _fake_rich_metadata)
    images = _make_images(tmp_path, 6, color=photo_color, size=(2000, 1500))
    profile = Profile(
        layout=LayoutSettings(template="grid", per_page=6, fit_mode="cover", caption_position="below", caption_area_mm=8),
        captions=CaptionSettings(fields=["filename"], lines=1, font_size=9),
    )
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=6,
                    page_format="A4", profile=profile)
    cs_gen = ContactSheetGenerator(config, ThumbnailGenerator(config))
    arr = np.array(cs_gen.create_contact_sheet(images, 1, 1)).astype(int)
    page, _ = cs_gen._plan_page(images)
    cell0 = page.cells[0]

    segments = _photo_segments(arr[:, cell0.photo_x + cell0.photo_w // 2, :], photo_color)
    assert abs((segments[0][1] - segments[0][0] + 1) - page.thumb_size) <= 1

    band = arr[segments[0][1] + 1:segments[1][0], cell0.photo_x:cell0.photo_x + cell0.photo_w, :]
    text_rows = np.where(np.any(band < 128, axis=(1, 2)))[0]
    assert text_rows.size > 0
    font_px = max(6, pt_to_px(9))
    assert CAPTION_PHOTO_GAP_PX <= int(text_rows.min()) < CAPTION_PHOTO_GAP_PX + font_px


# ---------------------------------------------------------------------------
# Position du titre / de l'auteur et numérotation des planches
# (LayoutSettings.title_position, author_position, page_numbering) : ces
# trois réglages étaient exposés par l'interface et le profil JSON, mais
# jamais lus par le rendu.
# ---------------------------------------------------------------------------

from types import SimpleNamespace

from PIL import ImageDraw

_HEADER_PALETTE = SimpleNamespace(text=(0, 0, 0), text_secondary=(0, 0, 0))


def _header_generator(tmp_path, *, title=None, author=None, watermark=None, **layout_kwargs):
    profile = Profile(layout=LayoutSettings(**layout_kwargs))
    config = Config(input_dir=tmp_path / "Mon dossier", output_dir=tmp_path / "out", num_per_sheet=6,
                    title=title, author=author, watermark_text=watermark, profile=profile)
    return ContactSheetGenerator(config, ThumbnailGenerator(config))


def _draw_header_only(gen, canvas_w=2480, canvas_h=800, margin=142):
    """Dessine UNIQUEMENT l'en-tête sur un canevas blanc, renvoie
    (tableau des niveaux de gris, ordonnée du bas de l'en-tête)."""
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    bottom = gen._draw_header(ImageDraw.Draw(canvas), canvas_w, margin, _HEADER_PALETTE)
    return np.array(canvas.convert("L")).astype(int), bottom


def _ink_columns(gray, y0=0, y1=None):
    """(première, dernière) colonne contenant de l'encre entre y0 et y1,
    ou None si la zone est vide."""
    cols = np.where((gray[y0:y1, :] < 128).any(axis=0))[0]
    return (int(cols.min()), int(cols.max())) if len(cols) else None


GLYPH_BEARING_TOLERANCE_PX = 14


@pytest.mark.parametrize("which", ["title", "author"])
def test_header_text_is_aligned_on_the_page_margins(tmp_path, which):
    margin, canvas_w = 142, 2480
    kwargs = {"title": "Voyage", "author": None} if which == "title" else {"title": None, "author": "Jeanne"}
    for position in ("top_left", "top_center", "top_right"):
        gen = _header_generator(tmp_path, **kwargs, **{f"{which}_position": position})
        gray, _ = _draw_header_only(gen, canvas_w=canvas_w, margin=margin)
        left, right = _ink_columns(gray)
        if position == "top_left":
            assert abs(left - margin) <= GLYPH_BEARING_TOLERANCE_PX
        elif position == "top_right":
            assert abs(right - (canvas_w - margin)) <= GLYPH_BEARING_TOLERANCE_PX
        else:
            assert abs(left - (canvas_w - 1 - right)) <= GLYPH_BEARING_TOLERANCE_PX


def test_default_header_is_strictly_the_historical_centered_rendering(tmp_path):
    """Positions par défaut (centrées) : mêmes pixels qu'avec une position
    "top_center" explicite, et titre/auteur toujours centrés l'un sous
    l'autre, bas d'en-tête inchangé (170 px)."""
    default_gen = _header_generator(tmp_path, title="Voyage", author="Jeanne")
    explicit_gen = _header_generator(tmp_path, title="Voyage", author="Jeanne",
                                     title_position="top_center", author_position="top_center")
    default_gray, default_bottom = _draw_header_only(default_gen)
    explicit_gray, explicit_bottom = _draw_header_only(explicit_gen)

    assert default_bottom == explicit_bottom == 170
    assert np.array_equal(default_gray, explicit_gray)


def test_header_bottom_keeps_its_historical_values(tmp_path):
    assert _draw_header_only(_header_generator(tmp_path, title="Voyage"))[1] == 128
    assert _draw_header_only(_header_generator(tmp_path, author="Jeanne"))[1] == 112
    assert _draw_header_only(_header_generator(tmp_path, title="Voyage", author="Jeanne"))[1] == 170
    # Rien à écrire (filigrane seul) : l'en-tête ne réserve que sa marge haute.
    assert _draw_header_only(_header_generator(tmp_path, watermark="© moi"))[1] == 70


def test_title_and_author_can_sit_on_opposite_sides_while_stacked(tmp_path):
    margin, canvas_w = 142, 2480
    gen = _header_generator(tmp_path, title="Voyage", author="Jeanne",
                            title_position="top_left", author_position="top_right")
    gray, bottom = _draw_header_only(gen, canvas_w=canvas_w, margin=margin)

    assert bottom == 170
    half = canvas_w // 2
    left_ink = _ink_columns(gray[:, :half])
    right_ink = _ink_columns(gray[:, half:])
    assert abs(left_ink[0] - margin) <= GLYPH_BEARING_TOLERANCE_PX
    assert abs((half + right_ink[1]) - (canvas_w - margin)) <= GLYPH_BEARING_TOLERANCE_PX
    # Le titre (à gauche) est au-dessus de l'auteur (à droite) : ils ne
    # partagent pas les mêmes lignes de pixels, hors débord de jambage.
    title_rows = np.where((gray[:, :half] < 128).any(axis=1))[0]
    author_rows = np.where((gray[:, half:] < 128).any(axis=1))[0]
    assert title_rows.min() < author_rows.min()


def test_hidden_title_and_author_draw_nothing_and_reserve_no_height(tmp_path):
    gen = _header_generator(tmp_path, title="Voyage", author="Jeanne",
                            title_position="none", author_position="none")
    gray, bottom = _draw_header_only(gen)

    assert _ink_columns(gray) is None
    assert bottom == 70


def test_hiding_only_the_title_moves_the_author_up_to_the_title_slot(tmp_path):
    gen = _header_generator(tmp_path, title="Voyage", author="Jeanne", title_position="none")
    gray, bottom = _draw_header_only(gen)

    assert _ink_columns(gray) is not None
    assert bottom == 112


def test_folder_name_fallback_title_is_never_shown_once_the_title_is_hidden(tmp_path):
    shown = _header_generator(tmp_path)
    hidden = _header_generator(tmp_path, title_position="none")

    assert _ink_columns(_draw_header_only(shown)[0]) is not None
    gray, bottom = _draw_header_only(hidden)
    assert _ink_columns(gray) is None
    assert bottom == 70


@pytest.mark.parametrize("position", ["top_left", "top_center", "top_right"])
def test_a_very_long_title_always_stays_inside_the_page_margins(tmp_path, position):
    margin, canvas_w = 142, 2480
    long_title = "Un titre extraordinairement long pour une seule ligne de planche contact " * 3
    gen = _header_generator(tmp_path, title=long_title, author=long_title, title_position=position,
                            author_position=position)
    gray, _ = _draw_header_only(gen, canvas_w=canvas_w, margin=margin)
    left, right = _ink_columns(gray)

    assert left >= margin - GLYPH_BEARING_TOLERANCE_PX
    assert right <= canvas_w - margin + GLYPH_BEARING_TOLERANCE_PX


def test_a_short_title_keeps_its_historical_font_size(tmp_path):
    """Le garde-fou « tenir dans la page » ne doit pas rétrécir un titre
    qui tient déjà : même encombrement qu'avec la police 54 px d'origine."""
    from portfolio.utils import get_font

    gen = _header_generator(tmp_path, title="Voyage")
    gray, _ = _draw_header_only(gen)
    left, right = _ink_columns(gray)

    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    bbox = probe.textbbox((0, 0), "Voyage", font=get_font(54, bold=True))
    assert abs((right - left) - (bbox[2] - bbox[0])) <= GLYPH_BEARING_TOLERANCE_PX


# Pied de page : trois lignes centrées, de haut en bas - numéro de planche
# (optionnel), « Planche générée par Planche-Contact », puis « Développé par
# Gilles MAGNEVILLE, sous licence GNU GPL v3 ». Bandes en pixels depuis le
# BAS de la planche (valeurs écrites en dur, pas relues dans layout_engine :
# un décalage involontaire des constantes doit faire échouer ces tests).
FOOTER_NUMBER_BAND = (120, 80)
FOOTER_CREDIT_BAND = (80, 52)
FOOTER_LICENSE_BAND = (52, 20)
#: Écart admis entre la largeur d'encre mesurée et celle du texte (police
#: 20 px : crénage/anti-crénelage, pas davantage).
FOOTER_TEXT_TOLERANCE_PX = 4


def _band(gray, band):
    top, bottom = band
    return gray[gray.shape[0] - top:gray.shape[0] - bottom, :]


def _footer_gray(gen, page_numbering_arg, canvas_w=2480, canvas_h=3508):
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    gen._draw_page_number(ImageDraw.Draw(canvas), canvas_w, canvas_h, 2, 5, _HEADER_PALETTE,
                          show_page_number=page_numbering_arg)
    return np.array(canvas.convert("L")).astype(int)


def _footer_ink_lines(gray):
    """(numéro, crédit, licence) : True si la bande contient de l'encre."""
    return tuple(bool((_band(gray, b) < 128).any())
                 for b in (FOOTER_NUMBER_BAND, FOOTER_CREDIT_BAND, FOOTER_LICENSE_BAND))


def _footer_ink(gen, page_numbering_arg):
    return _footer_ink_lines(_footer_gray(gen, page_numbering_arg))


def test_page_number_is_drawn_by_default_with_the_credit_lines(tmp_path):
    gen = _header_generator(tmp_path)
    assert _footer_ink(gen, True) == (True, True, True)


def test_page_number_can_be_hidden_while_the_credit_lines_stay(tmp_path):
    gen = _header_generator(tmp_path)
    assert _footer_ink(gen, False) == (False, True, True)


def test_page_numbering_setting_reaches_the_rendered_sheet(tmp_path):
    images = _make_images(tmp_path, 6)

    def render(page_numbering):
        profile = Profile(layout=LayoutSettings(per_page=6, page_numbering=page_numbering))
        config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=6, profile=profile)
        gen = ContactSheetGenerator(config, ThumbnailGenerator(config))
        sheet = gen.create_contact_sheet(images, 1, 3)
        return _footer_ink_lines(np.array(sheet.convert("L")).astype(int))

    assert render(True) == (True, True, True)
    assert render(False) == (False, True, True)


@pytest.fixture
def restore_language():
    from portfolio.i18n import get_language, set_language
    previous = get_language()
    yield set_language
    set_language(previous)


@pytest.mark.parametrize("lang", ["fr", "en", "de", "es"])
def test_license_line_is_centered_and_as_wide_as_its_text(tmp_path, restore_language, lang):
    """La mention développeur/licence est dessinée entière (largeur = celle
    du texte traduit mesuré à la police 20 px, aucune troncature) et
    centrée sur la page, dans chaque langue."""
    from portfolio.i18n import _
    from portfolio.utils import AUTHOR_NAME, get_font

    restore_language(lang)
    text = _("sheet.footer_credit", name=AUTHOR_NAME)
    assert AUTHOR_NAME in text and "GPL v3" in text

    canvas_w = 2480
    gray = _footer_gray(_header_generator(tmp_path), True, canvas_w=canvas_w)
    left, right = _ink_columns(_band(gray, FOOTER_LICENSE_BAND))

    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    bbox = probe.textbbox((0, 0), text, font=get_font(20))
    assert abs((right - left + 1) - (bbox[2] - bbox[0])) <= FOOTER_TEXT_TOLERANCE_PX
    assert abs(left - (canvas_w - 1 - right)) <= FOOTER_TEXT_TOLERANCE_PX


def test_license_line_sits_below_the_credit_line_without_touching_it(tmp_path):
    gray = _footer_gray(_header_generator(tmp_path), True)
    rows = np.where((gray < 128).any(axis=1))[0]
    h = gray.shape[0]
    # trois groupes de lignes de pixels séparés par du blanc : numéro, crédit, licence
    groups = np.split(rows, np.where(np.diff(rows) > 1)[0] + 1)
    assert len(groups) == 3, f"{len(groups)} lignes de texte au lieu de 3"
    # l'ordre est numéro, crédit, licence, de haut en bas, et la dernière
    # ligne reste à distance du bord physique de la planche (~2 mm)
    assert groups[0][-1] < groups[1][0] and groups[1][-1] < groups[2][0]
    assert h - 1 - groups[2][-1] >= 20


def test_license_line_uses_the_secondary_text_color(tmp_path):
    palette = SimpleNamespace(text=(0, 0, 0), text_secondary=(120, 120, 120))
    gen = _header_generator(tmp_path)
    canvas = Image.new("RGB", (2480, 3508), "white")
    gen._draw_page_number(ImageDraw.Draw(canvas), 2480, 3508, 1, 1, palette, show_page_number=True)
    gray = np.array(canvas.convert("L")).astype(int)
    assert _band(gray, FOOTER_NUMBER_BAND).min() == 0
    assert _band(gray, FOOTER_CREDIT_BAND).min() == 120
    assert _band(gray, FOOTER_LICENSE_BAND).min() == 120


@pytest.mark.parametrize("lang", ["fr", "en", "de", "es"])
def test_sheet_and_gallery_use_the_same_license_wording(restore_language, lang):
    """Les planches/PDF et le pied de la galerie HTML affichent la même
    mention, dans chaque langue : un seul texte à tenir à jour."""
    from portfolio.i18n import _
    from portfolio.utils import AUTHOR_NAME

    restore_language(lang)
    assert _("sheet.footer_credit", name=AUTHOR_NAME) == _("gallery.footer_credit", name=AUTHOR_NAME)


def test_the_rendered_sheet_carries_the_license_line_and_the_pdf_inherits_it(tmp_path):
    """Bout en bout : la planche JPEG réellement générée porte les deux
    mentions ; le PDF est construit à partir de ces planches (il ne dessine
    aucun texte lui-même) et les reprend donc à l'identique."""
    images = _make_images(tmp_path, 6)
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=6,
                    profile=Profile(layout=LayoutSettings(per_page=6)))
    sheet = ContactSheetGenerator(config, ThumbnailGenerator(config)).create_contact_sheet(images, 1, 1)
    gray = np.array(sheet.convert("L")).astype(int)
    assert _footer_ink_lines(gray) == (True, True, True)


def test_header_position_setting_reaches_the_rendered_sheet(tmp_path):
    images = _make_images(tmp_path, 6)

    def header_extent(position):
        profile = Profile(layout=LayoutSettings(per_page=6, title_position=position))
        config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=6,
                        title="Voyage", profile=profile)
        gen = ContactSheetGenerator(config, ThumbnailGenerator(config))
        gray = np.array(gen.create_contact_sheet(images, 1, 1).convert("L")).astype(int)
        return _ink_columns(gray, 70, 120), gray.shape[1]

    (left, _), width = header_extent("top_left")
    (_, right), _ = header_extent("top_right")
    assert left < width // 4
    assert right > 3 * width // 4
    assert header_extent("none")[0] is None


# ---------------------------------------------------------------------------
# Centrage de l'ensemble des photos sur la page. Deux causes d'un ensemble
# décalé vers le haut et la gauche : (1) la grille démarrait à la marge
# gauche/en haut de la zone utile, tout le vide restant à droite/en bas ;
# (2) sans légende, chaque photo était collée en haut à gauche de sa
# cellule carrée.
# ---------------------------------------------------------------------------

def _render_ink(tmp_path, photo_size, *, template="grid", per_page=8, page_format="A4",
                orientation="portrait", n_photos=None, color=(10, 200, 10), title="Voyage",
                margin_mm=None):
    """Planche rendue ; renvoie (tableau RGB, PageLayout, bas de l'en-tête)."""
    images = _make_images(tmp_path, n_photos or per_page, color=color, size=photo_size)
    extra = {} if margin_mm is None else {"margin_mm": margin_mm}
    profile = Profile(layout=LayoutSettings(template=template, per_page=per_page,
                                            page_format=page_format, orientation=orientation,
                                            **extra))
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=per_page,
                    page_format=page_format, title=title, profile=profile)
    gen = ContactSheetGenerator(config, ThumbnailGenerator(config))
    page, _ = gen._plan_page(images)
    return np.array(gen.create_contact_sheet(images, 1, 1)).astype(int), page


def _ink_bbox(arr, color=(10, 200, 10)):
    """(gauche, droite, haut, bas) des marges entre les pixels de photo et
    le bord de la page."""
    mask = np.all(np.abs(arr - np.array(color)) < 40, axis=2)
    ys, xs = np.where(mask)
    return (int(xs.min()), int(arr.shape[1] - 1 - xs.max()),
            int(ys.min()), int(arr.shape[0] - 1 - ys.max()))


CENTERING_CONFIGS = [
    # (format, orientation, modèle, photos par page) : la plupart laissaient
    # un grand vide d'un seul côté (jusqu'à ~6 cm à droite).
    ("A4", "portrait", "grid", 8),
    ("A4", "portrait", "grid", 24),
    ("A4", "landscape", "grid", 12),
    ("A4", "landscape", "grid", 48),
    ("Letter", "portrait", "large_thumbs", 12),
]


@pytest.mark.parametrize("photo_size", [(2000, 1500), (1500, 2000), (1700, 1700)],
                         ids=["paysage", "portrait", "carre"])
@pytest.mark.parametrize("page_format,orientation,template,per_page", CENTERING_CONFIGS)
def test_the_whole_set_of_photos_is_centered_horizontally_on_the_page(
        tmp_path, page_format, orientation, template, per_page, photo_size):
    arr, _ = _render_ink(tmp_path, photo_size, template=template, per_page=per_page,
                         page_format=page_format, orientation=orientation)
    left, right, _, _ = _ink_bbox(arr)
    assert abs(left - right) <= 3, f"marge gauche {left} px, marge droite {right} px"


@pytest.mark.parametrize("photo_size", [(2000, 1500), (1500, 2000)], ids=["paysage", "portrait"])
@pytest.mark.parametrize("page_format,orientation,template,per_page", CENTERING_CONFIGS)
def test_the_whole_set_of_photos_is_centered_vertically_below_the_header(
        tmp_path, page_format, orientation, template, per_page, photo_size):
    """Entre le bas de l'en-tête (titre, ici 128 px) + la marge et la marge
    basse de la page, le vide est réparti à parts égales au-dessus et
    au-dessous de l'ensemble des photos."""
    arr, page = _render_ink(tmp_path, photo_size, template=template, per_page=per_page,
                            page_format=page_format, orientation=orientation)
    _, _, top, bottom = _ink_bbox(arr)
    free_top = 128 + page.margin_px
    free_bottom = page.margin_px
    above, below = top - free_top, bottom - free_bottom
    assert above >= 0 and below >= 0, f"photos hors de la zone libre : {above} / {below}"
    assert abs(above - below) <= 3, f"vide au-dessus {above} px, au-dessous {below} px"


@pytest.mark.parametrize("margin_mm", [0, 3, 6, 10, 12, 20])
@pytest.mark.parametrize("page_format,orientation,template,per_page", CENTERING_CONFIGS)
def test_the_footer_lines_never_overlap_the_photos_whatever_the_margin(
        tmp_path, page_format, orientation, template, per_page, margin_mm):
    """Le pied de page compte désormais trois lignes : avec une marge
    basse plus petite que lui, les dernières photos descendaient jusque
    sous le texte. La grille s'arrête maintenant au-dessus du pied de
    page, quelle que soit la marge choisie."""
    arr, _ = _render_ink(tmp_path, (1500, 2000), template=template, per_page=per_page,
                         page_format=page_format, orientation=orientation, margin_mm=margin_mm)
    _, _, _, bottom_gap = _ink_bbox(arr)
    assert bottom_gap >= FOOTER_NUMBER_BAND[0], (
        f"les photos descendent à {bottom_gap} px du bas de la page, "
        f"le pied de page commence à {FOOTER_NUMBER_BAND[0]} px"
    )
    footer_zone = arr[arr.shape[0] - FOOTER_NUMBER_BAND[0]:, :, :]
    assert not np.all(np.abs(footer_zone - np.array((10, 200, 10))) < 40, axis=2).any()


def test_a_portrait_photo_is_centered_in_its_cell_not_stuck_to_its_left_edge(tmp_path):
    """Cause (2) : sans légende, une photo portrait (plus étroite que sa
    cellule carrée) restait collée à gauche de la cellule."""
    arr, page = _render_ink(tmp_path, (1500, 2000), per_page=8)
    cell = page.cells[0]
    mask = np.all(np.abs(arr - np.array((10, 200, 10))) < 40, axis=2)
    ys, xs = np.where(mask[:, cell.photo_x:cell.photo_x + cell.photo_w])
    row = mask[int(ys.min()) + 5, :]
    cols = np.where(row[cell.photo_x:cell.photo_x + cell.photo_w])[0]
    left_gap = int(cols.min())
    right_gap = cell.photo_w - 1 - int(cols.max())
    assert left_gap > 20, "le test n'a pas de sens : la photo remplit sa cellule"
    assert abs(left_gap - right_gap) <= 2, f"vide à gauche {left_gap} px, à droite {right_gap} px"


def test_photos_keep_exactly_the_same_place_on_an_incomplete_last_page(tmp_path):
    """Le centrage se calcule sur la grille d'une page PLEINE : la dernière
    page, incomplète, garde ses photos exactement aux mêmes endroits que les
    autres (aucun saut d'une page à l'autre)."""
    full_arr, full_page = _render_ink(tmp_path, (2000, 1500), per_page=12, n_photos=12)
    short_arr, short_page = _render_ink(tmp_path, (2000, 1500), per_page=12, n_photos=5)

    assert (short_page.grid_w, short_page.grid_h) == (full_page.grid_w, full_page.grid_h)
    for short_cell, full_cell in zip(short_page.cells, full_page.cells):
        assert (short_cell.photo_x, short_cell.photo_y) == (full_cell.photo_x, full_cell.photo_y)
    # même premier pixel de photo, en x comme en y
    mask_full = np.all(np.abs(full_arr - np.array((10, 200, 10))) < 40, axis=2)
    mask_short = np.all(np.abs(short_arr - np.array((10, 200, 10))) < 40, axis=2)
    fy, fx = np.where(mask_full); sy, sx = np.where(mask_short)
    assert (int(fx.min()), int(fy.min())) == (int(sx.min()), int(sy.min()))


def test_captioned_sheet_is_centered_horizontally_too(tmp_path, monkeypatch):
    """Avec légende sous les photos (cellule = photo + zone de texte), la
    grille reste centrée sur la page."""
    monkeypatch.setattr("portfolio.contactsheet.get_exif_metadata", _fake_rich_metadata)
    images = _make_images(tmp_path, 12, color=(10, 200, 10), size=(2000, 1500))
    profile = Profile(
        layout=LayoutSettings(template="grid", per_page=12, caption_position="below", caption_area_mm=8),
        captions=CaptionSettings(fields=["filename", "camera"], lines=2, alignment="center"),
    )
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=12, profile=profile)
    gen = ContactSheetGenerator(config, ThumbnailGenerator(config))
    arr = np.array(gen.create_contact_sheet(images, 1, 1)).astype(int)
    left, right, _, _ = _ink_bbox(arr)
    assert abs(left - right) <= 3, f"marge gauche {left} px, marge droite {right} px"

