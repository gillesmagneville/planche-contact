# -*- coding: utf-8 -*-
"""
rawloader.load_full_resolution(): the "full-size" image of a RAW, from
which the HTML gallery creates the downloadable JPEG (the "full-size
originals" option). A fake `rawpy` module is used: the real one is not
always installed, and what is checked here is the CHOICE between the
embedded JPEG preview and full demosaicing.
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
    """Fake `rawpy`: sensor `sensor`, embedded JPEG preview of size
    `preview_size` (None: no preview). `calls` records what is used."""
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
    """Many cameras store a full-size image in the RAW: it is the camera's
    own rendering, and extraction is almost instant (demosaicing takes about
    a second per photo)."""
    calls = install_fake_rawpy((6000, 4000))
    img = rawloader.load_full_resolution(tmp_path / "A.CR2")
    assert img.size == (6000, 4000)
    assert "demosaic" not in calls


@pytest.mark.parametrize("preview_size", [(1620, 1080), (5400, 3600), (5700, 3800), None],
                         ids=["petit", "90pc", "95pc", "absent"])
def test_a_smaller_preview_is_never_passed_off_as_the_full_size_photo(install_fake_rawpy, tmp_path, preview_size):
    """A preview clearly smaller than the sensor - even at 90-95% of the
    resolution, the threshold tolerated for thumbnails - is not the complete
    photo: full demosaicing, sensor resolution."""
    calls = install_fake_rawpy(preview_size)
    img = rawloader.load_full_resolution(tmp_path / "A.NEF")
    assert img.size == SENSOR
    assert "demosaic" in calls


def test_a_preview_just_under_the_sensor_size_is_accepted(install_fake_rawpy, tmp_path):
    """Full-size previews are sometimes a few pixels smaller than the raw
    matrix (edges): tolerated at 98%."""
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
    """Non-regression: the thumbnails' tolerance (90%) has not moved -
    a preview at 95% is still accepted for them."""
    calls = install_fake_rawpy((5700, 3800))
    img = rawloader.load_image(tmp_path / "A.CR2", use_embedded_thumb=True, target_size=SENSOR)
    assert img.size == (5700, 3800) and "demosaic" not in calls
