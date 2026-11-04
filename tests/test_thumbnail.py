# -*- coding: utf-8 -*-
"""
Tests of the thumbnail fit mode (LayoutSettings.fit_mode):
"contain" (whole photo, original behaviour) and "cover" (photo
cropped to a square to fill its whole cell - "Fill" in the
interface). This setting was exposed (JSON Profile, interface, manual) but
never read by the renderer: "Fill" cropped nothing.
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
    """Red band on the left, blue on the right, green in the centre: a
    CENTRED square crop must cut off both bands. Bands deliberately narrower
    than the trimmed margin (100 px on each side for 800x600 -> 400 square):
    a band edge exactly on the crop edge would be blended with the green by
    LANCZOS resampling, which would say nothing about the cropping."""
    img = Image.new("RGB", (width, height), GREEN)
    img.paste(Image.new("RGB", (band, height), RED), (0, 0))
    img.paste(Image.new("RGB", (band, height), BLUE), (width - band, 0))
    return img


def _colors(img):
    return {color for _, color in img.getcolors(maxcolors=1_000_000)}


def test_contain_keeps_the_whole_photo_with_its_proportions():
    thumb = fit_thumbnail_image(_striped_landscape(), 400, "contain")
    assert thumb.size == (400, 300)
    assert {RED, BLUE} <= {c for c in _colors(thumb) if c in (RED, BLUE)}, "the whole photo must remain visible"


def test_cover_crops_the_photo_to_a_centered_square_filling_the_cell():
    # 800x600 -> short side brought down to 400 -> 533x400, then central square of 400
    # = x from 100 to 700 on the original: the 0-60 and 740-800 bands disappear.
    thumb = fit_thumbnail_image(_striped_landscape(), 400, "cover")
    assert thumb.size == (400, 400)
    assert _colors(thumb) == {GREEN}, "the crop must be centred and remove the edges"


def test_cover_also_crops_portrait_photos_around_their_center():
    portrait = Image.new("RGB", (600, 800), GREEN)
    portrait.paste(Image.new("RGB", (600, 60), RED), (0, 0))
    portrait.paste(Image.new("RGB", (600, 60), BLUE), (0, 740))
    thumb = fit_thumbnail_image(portrait, 400, "cover")
    assert thumb.size == (400, 400)
    assert _colors(thumb) == {GREEN}


@pytest.mark.parametrize("size", [(800, 600), (600, 800), (1001, 667), (4000, 3001), (401, 400), (1000, 1000)])
def test_cover_always_yields_a_full_square_for_large_enough_photos(size):
    """No rounding that would leave a side at 399 px (incomplete square) -
    the thumbnail would then almost, but not quite, fill the cell."""
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
    """Tolerance: the photos in these tests go through (lossy) JPEG."""
    return bool(np.all(np.abs(np.asarray(img).astype(int) - np.array(GREEN)) < tolerance))


def test_generate_parallel_passes_fit_mode_to_the_worker_processes(tmp_path):
    """The workers are `spawn` processes: the mode must be passed to them
    explicitly (they inherit no state from the parent)."""
    gen = ThumbnailGenerator(Config(input_dir=tmp_path, output_dir=tmp_path / "out"))
    paths = _write_photos(tmp_path)

    contain = gen.generate_parallel(paths, 400)
    cover = gen.generate_parallel(paths, 400, fit_mode="cover")

    assert [t.size for t in contain] == [(400, 300)] * 3
    assert [t.size for t in cover] == [(400, 400)] * 3
    assert all(_is_all_green(t) for t in cover), "centred crop: no more red/blue bands"


def test_create_thumbnail_supports_fit_mode(tmp_path):
    gen = ThumbnailGenerator(Config(input_dir=tmp_path, output_dir=tmp_path / "out"))
    path = _write_photos(tmp_path, 1)[0]
    assert gen.create_thumbnail(path, 400).size == (400, 300)
    assert gen.create_thumbnail(path, 400, fit_mode="cover").size == (400, 400)


def test_raw_embedded_preview_must_be_large_enough_on_its_short_side_to_fill():
    """A 640x424 embedded 4:3 RAW preview is enough to FIT a photo inside
    600x600 (long side), but not to CROP it to 600x600: its short side (424)
    would give a square that is too small - the full RAW must then be
    demosaiced."""
    assert _large_enough((640, 424), (600, 600)) is True
    assert _large_enough((640, 424), (600, 600), fill=True) is False
    assert _large_enough((1620, 1080), (600, 600), fill=True) is True
