# -*- coding: utf-8 -*-
"""
rawloader.load_full_resolution() : l'image « pleine taille » d'un RAW, à
partir de laquelle la galerie HTML crée le JPEG téléchargeable (option
« originaux pleine taille »). Un faux module `rawpy` est utilisé : le vrai
n'est pas toujours installé, et ce qu'on vérifie ici est le CHOIX entre
l'aperçu JPEG embarqué et le dématriçage complet.
"""
import io
import types

import numpy as np
import pytest
from PIL import Image

from portfolio import rawloader

SENSOR = (6000, 4000)


class _NoThumbnail(Exception):
    pass


def _jpeg_bytes(size):
    buffer = io.BytesIO()
    Image.new("RGB", size, (40, 80, 120)).save(buffer, "JPEG")
    return buffer.getvalue()


def _fake_rawpy(preview_size, calls, sensor=SENSOR):
    """Faux `rawpy` : capteur `sensor`, aperçu JPEG embarqué de taille
    `preview_size` (None : pas d'aperçu). `calls` note ce qui est utilisé."""
    class ThumbFormat:
        JPEG = "jpeg"
        BITMAP = "bitmap"

    class Raw:
        sizes = types.SimpleNamespace(width=sensor[0], height=sensor[1], flip=0)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_thumb(self):
            calls.append("preview")
            if preview_size is None:
                raise _NoThumbnail()
            return types.SimpleNamespace(format=ThumbFormat.JPEG, data=_jpeg_bytes(preview_size))

        def postprocess(self, **kwargs):
            calls.append("demosaic")
            return np.zeros((sensor[1], sensor[0], 3), dtype=np.uint8)

    return types.SimpleNamespace(
        imread=lambda path: Raw(),
        ThumbFormat=ThumbFormat,
        LibRawNoThumbnailError=_NoThumbnail,
        LibRawUnsupportedThumbnailError=_NoThumbnail,
    )


@pytest.fixture
def install_fake_rawpy(monkeypatch):
    def install(preview_size, sensor=SENSOR):
        calls = []
        monkeypatch.setattr(rawloader, "rawpy", _fake_rawpy(preview_size, calls, sensor), raising=False)
        monkeypatch.setattr(rawloader, "RAWPY_AVAILABLE", True)
        return calls
    return install


def test_a_full_size_embedded_preview_is_used_without_demosaicing(install_fake_rawpy, tmp_path):
    """Beaucoup d'appareils enregistrent une image pleine taille dans le
    RAW : c'est le rendu de l'appareil, et l'extraction est quasi instantanée
    (le dématriçage prend de l'ordre d'une seconde par photo)."""
    calls = install_fake_rawpy((6000, 4000))
    img = rawloader.load_full_resolution(tmp_path / "A.CR2")
    assert img.size == (6000, 4000)
    assert "demosaic" not in calls


@pytest.mark.parametrize("preview_size", [(1620, 1080), (5400, 3600), (5700, 3800), None],
                         ids=["petit", "90pc", "95pc", "absent"])
def test_a_smaller_preview_is_never_passed_off_as_the_full_size_photo(install_fake_rawpy, tmp_path, preview_size):
    """Un aperçu nettement plus petit que le capteur - même à 90-95 % de la
    résolution, seuil toléré pour les vignettes - n'est pas la photo
    complète : dématriçage complet, résolution du capteur."""
    calls = install_fake_rawpy(preview_size)
    img = rawloader.load_full_resolution(tmp_path / "A.NEF")
    assert img.size == SENSOR
    assert "demosaic" in calls


def test_a_preview_just_under_the_sensor_size_is_accepted(install_fake_rawpy, tmp_path):
    """Les aperçus pleine taille sont parfois quelques pixels plus petits
    que la matrice brute (bords) : toléré à 98 %."""
    calls = install_fake_rawpy((5900, 3933))
    img = rawloader.load_full_resolution(tmp_path / "A.ARW")
    assert img.size == (5900, 3933) and "demosaic" not in calls


def test_the_embedded_preview_is_ignored_when_the_sensor_size_is_unknown(install_fake_rawpy, tmp_path, monkeypatch):
    calls = install_fake_rawpy((1620, 1080))
    monkeypatch.setattr(rawloader, "get_original_dimensions", lambda path: None)
    img = rawloader.load_full_resolution(tmp_path / "A.DNG")
    assert img.size == SENSOR and calls == ["demosaic"]


def test_without_rawpy_a_raw_raises_instead_of_returning_something_smaller(monkeypatch, tmp_path):
    monkeypatch.setattr(rawloader, "RAWPY_AVAILABLE", False)
    with pytest.raises(RuntimeError):
        rawloader.load_full_resolution(tmp_path / "A.CR3")


def test_a_regular_photo_is_loaded_as_is(tmp_path):
    path = tmp_path / "a.jpg"
    Image.new("RGB", (321, 123), (1, 2, 3)).save(path)
    assert rawloader.load_full_resolution(path).size == (321, 123)


def test_thumbnail_loading_keeps_its_ninety_percent_tolerance(install_fake_rawpy, tmp_path):
    """Non-régression : la tolérance des vignettes (90 %) n'a pas bougé -
    un aperçu à 95 % reste accepté pour elles."""
    calls = install_fake_rawpy((5700, 3800))
    img = rawloader.load_image(tmp_path / "A.CR2", use_embedded_thumb=True, target_size=SENSOR)
    assert img.size == (5700, 3800) and "demosaic" not in calls
