# -*- coding: utf-8 -*-
"""
Tests du mode d'ajustement des vignettes (LayoutSettings.fit_mode) :
"contain" (photo entière, comportement d'origine) et "cover" (photo
recadrée en carré pour remplir toute sa cellule - « Remplir » dans
l'interface). Ce réglage était exposé (Profil JSON, interface, manuel) mais
jamais lu par le rendu : « Remplir » ne recadrait rien.
"""
from pathlib import Path

import pytest
import numpy as np
from PIL import Image

from portfolio.config import Config
from portfolio.rawloader import _large_enough
from portfolio.thumbnail import ThumbnailGenerator, fit_thumbnail_image

RED, GREEN, BLUE = (220, 20, 20), (20, 200, 20), (20, 20, 220)


def _striped_landscape(width=800, height=600, band=60):
    """Bande rouge à gauche, bleue à droite, verte au centre : un recadrage
    CENTRÉ en carré doit couper les deux bandes. Bandes volontairement plus
    étroites que la marge rognée (100 px de chaque côté pour 800x600 -> 400
    carré) : un bord de bande pile sur le bord du recadrage serait mélangé
    au vert par le rééchantillonnage LANCZOS, sans rien dire du recadrage."""
    img = Image.new("RGB", (width, height), GREEN)
    img.paste(Image.new("RGB", (band, height), RED), (0, 0))
    img.paste(Image.new("RGB", (band, height), BLUE), (width - band, 0))
    return img


def _colors(img):
    return {color for _, color in img.getcolors(maxcolors=1_000_000)}


def test_contain_keeps_the_whole_photo_with_its_proportions():
    thumb = fit_thumbnail_image(_striped_landscape(), 400, "contain")
    assert thumb.size == (400, 300)
    assert {RED, BLUE} <= {c for c in _colors(thumb) if c in (RED, BLUE)}, "toute la photo doit rester visible"


def test_cover_crops_the_photo_to_a_centered_square_filling_the_cell():
    # 800x600 -> petit côté ramené à 400 -> 533x400, puis carré central de 400
    # = x de 100 à 700 sur l'original : les bandes 0-60 et 740-800 disparaissent.
    thumb = fit_thumbnail_image(_striped_landscape(), 400, "cover")
    assert thumb.size == (400, 400)
    assert _colors(thumb) == {GREEN}, "le recadrage doit être centré et retirer les bords"


def test_cover_also_crops_portrait_photos_around_their_center():
    portrait = Image.new("RGB", (600, 800), GREEN)
    portrait.paste(Image.new("RGB", (600, 60), RED), (0, 0))
    portrait.paste(Image.new("RGB", (600, 60), BLUE), (0, 740))
    thumb = fit_thumbnail_image(portrait, 400, "cover")
    assert thumb.size == (400, 400)
    assert _colors(thumb) == {GREEN}


@pytest.mark.parametrize("size", [(800, 600), (600, 800), (1001, 667), (4000, 3001), (401, 400), (1000, 1000)])
def test_cover_always_yields_a_full_square_for_large_enough_photos(size):
    """Pas d'arrondi qui laisserait un côté à 399 px (carré incomplet) -
    la vignette remplirait alors presque, mais pas tout à fait, la cellule."""
    thumb = fit_thumbnail_image(Image.new("RGB", size, GREEN), 400, "cover")
    assert thumb.size == (400, 400)


@pytest.mark.parametrize("mode", ["contain", "cover"])
def test_photos_smaller_than_the_cell_are_never_upscaled(mode):
    small = Image.new("RGB", (200, 100), GREEN)
    thumb = fit_thumbnail_image(small, 400, mode)
    assert thumb.size == ((200, 100) if mode == "contain" else (100, 100))


def test_unknown_fit_mode_behaves_like_contain():
    assert fit_thumbnail_image(_striped_landscape(), 400, "n'importe quoi").size == (400, 300)


def _write_photos(tmp_path, n=3, size=(800, 600)):
    paths = []
    for i in range(n):
        p = tmp_path / f"img_{i}.jpg"
        _striped_landscape(*size).save(p, quality=95)
        paths.append(p)
    return paths


def _is_all_green(img, tolerance=40):
    """Tolérance : les photos de ces tests passent par du JPEG (avec pertes)."""
    return bool(np.all(np.abs(np.asarray(img).astype(int) - np.array(GREEN)) < tolerance))


def test_generate_parallel_passes_fit_mode_to_the_worker_processes(tmp_path):
    """Les workers sont des processus `spawn` : le mode doit leur être
    transmis explicitement (ils n'héritent d'aucun état du parent)."""
    gen = ThumbnailGenerator(Config(input_dir=tmp_path, output_dir=tmp_path / "out"))
    paths = _write_photos(tmp_path)

    contain = gen.generate_parallel(paths, 400)
    cover = gen.generate_parallel(paths, 400, fit_mode="cover")

    assert [t.size for t in contain] == [(400, 300)] * 3
    assert [t.size for t in cover] == [(400, 400)] * 3
    assert all(_is_all_green(t) for t in cover), "recadrage centré : plus de bandes rouge/bleue"


def test_create_thumbnail_supports_fit_mode(tmp_path):
    gen = ThumbnailGenerator(Config(input_dir=tmp_path, output_dir=tmp_path / "out"))
    path = _write_photos(tmp_path, 1)[0]
    assert gen.create_thumbnail(path, 400).size == (400, 300)
    assert gen.create_thumbnail(path, 400, fit_mode="cover").size == (400, 400)


def test_raw_embedded_preview_must_be_large_enough_on_its_short_side_to_fill():
    """Un aperçu RAW embarqué 4:3 de 640x424 suffit pour INSCRIRE une photo
    dans 600x600 (grand côté), mais pas pour la RECADRER en 600x600 : son
    petit côté (424) donnerait un carré trop petit - il faut alors
    dématricer le RAW complet."""
    assert _large_enough((640, 424), (600, 600)) is True
    assert _large_enough((640, 424), (600, 600), fill=True) is False
    assert _large_enough((1620, 1080), (600, 600), fill=True) is True
