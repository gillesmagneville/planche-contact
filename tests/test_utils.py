# -*- coding: utf-8 -*-
"""
Tests of portfolio.utils.get_exif_metadata() - extraction of the EXIF
metadata used by the per-photo customisable captions (specification §1,
see also tests/test_captions.py for their formatting).

The test images are real JPEGs produced by Pillow, with real EXIF
metadata written via PIL.Image.Exif (IFD0 + Exif/GPS sub-IFD) - not
mocks - to verify a genuine EXIF write/read round trip, consistent with
the project's culture of empirical verification.

The RAW path (exifread) is only verified here for its RESILIENCE
(missing/corrupted file must never raise an exception): building a real
RAW file (.cr2/.nef/.dng...) with controlled EXIF tags would go far
beyond the scope of this test module; the exact mapping of the exifread
tags (EXIF FocalLength, GPS GPSLatitude...) nevertheless follows exactly
the same logic as the Pillow path below, already verified.
"""
from datetime import datetime

import pytest
from PIL import Image
from PIL.ExifTags import IFD

from portfolio.utils import get_exif_metadata


def _make_jpeg_with_exif(path, *, make=None, model=None, lens=None,
                          focal_length=None, focal_35mm=None, aperture=None,
                          shutter_speed=None, iso=None, date_original=None,
                          gps=None, size=(800, 600)):
    """Creates a test JPEG with the supplied EXIF tags - see the module
    docstring for the rationale of this approach (real files, no mocks)."""
    img = Image.new("RGB", size, (120, 80, 200))
    exif = Image.Exif()

    if make is not None:
        exif[0x010F] = make
    if model is not None:
        exif[0x0110] = model

    exif_ifd = exif.get_ifd(IFD.Exif)
    if lens is not None:
        exif_ifd[0xA434] = lens
    if focal_length is not None:
        exif_ifd[0x920A] = focal_length
    if focal_35mm is not None:
        exif_ifd[0xA405] = focal_35mm
    if aperture is not None:
        exif_ifd[0x829D] = aperture
    if shutter_speed is not None:
        exif_ifd[0x829A] = shutter_speed
    if iso is not None:
        exif_ifd[0x8827] = iso
    if date_original is not None:
        exif_ifd[0x9003] = date_original

    if gps is not None:
        lat, lon = gps
        gps_ifd = exif.get_ifd(IFD.GPSInfo)
        gps_ifd[1] = "N" if lat >= 0 else "S"
        gps_ifd[2] = _decimal_to_dms(abs(lat))
        gps_ifd[3] = "E" if lon >= 0 else "W"
        gps_ifd[4] = _decimal_to_dms(abs(lon))

    img.save(path, format="JPEG", exif=exif.tobytes())


def _decimal_to_dms(value):
    degrees = int(value)
    minutes_float = (value - degrees) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    return (float(degrees), float(minutes), float(seconds))


def test_filename_always_present(tmp_path):
    """filename is set even for an image with no EXIF at all - never a
    missing key, unlike the other fields."""
    path = tmp_path / "sans_exif.jpg"
    Image.new("RGB", (100, 100)).save(path, format="JPEG")

    metadata = get_exif_metadata(path)
    assert metadata["filename"] == "sans_exif.jpg"


def test_missing_metadata_fields_are_none_not_raised(tmp_path):
    """Specification §1: never an error for absent EXIF fields - they are
    simply None, the others remain usable."""
    path = tmp_path / "partiel.jpg"
    _make_jpeg_with_exif(path, make="Fujifilm", model="X-T5")

    metadata = get_exif_metadata(path)
    assert metadata["camera"] == "Fujifilm X-T5"
    assert metadata.get("lens") is None
    assert metadata.get("aperture") is None
    assert metadata.get("gps") is None
    # The dimensions, for their part, are always available (read via
    # rawloader, independently of the EXIF).
    assert metadata["dimensions"] == (800, 600)


def test_camera_combines_make_and_model_without_duplication():
    """A model that already repeats the make (Nikon convention: Make =
    "NIKON CORPORATION", Model = "NIKON D850") must not produce a
    doubled string."""
    from portfolio.utils import _combine_camera

    assert _combine_camera("Canon", "Canon EOS R5") == "Canon EOS R5"
    assert _combine_camera("NIKON CORPORATION", "NIKON D850") == "NIKON D850"
    assert _combine_camera("Sony", "ILCE-7RM4") == "Sony ILCE-7RM4"
    assert _combine_camera("Canon", None) == "Canon"
    assert _combine_camera(None, "ILCE-7RM4") == "ILCE-7RM4"
    assert _combine_camera(None, None) is None


def test_full_metadata_round_trip(tmp_path):
    """Checks a complete EXIF write -> read round trip for each supported
    field, including focal length, aperture, shutter speed, ISO, 35mm
    equivalent focal length and shooting date."""
    path = tmp_path / "complete.jpg"
    _make_jpeg_with_exif(
        path,
        make="Canon", model="Canon EOS R5", lens="RF 24-70mm F2.8",
        focal_length=50.0, focal_35mm=50, aperture=2.8, shutter_speed=0.004,
        iso=400, date_original="2024:05:01 12:00:00",
    )

    metadata = get_exif_metadata(path)
    assert metadata["camera"] == "Canon EOS R5"
    assert metadata["lens"] == "RF 24-70mm F2.8"
    assert metadata["focal_length"] == pytest.approx(50.0)
    assert metadata["focal_35mm"] == 50
    assert metadata["aperture"] == pytest.approx(2.8)
    assert metadata["shutter_speed"] == pytest.approx(0.004)
    assert metadata["iso"] == 400
    assert metadata["datetime"] == datetime(2024, 5, 1, 12, 0, 0)
    assert metadata["dimensions"] == (800, 600)


def test_gps_round_trip_and_hemisphere_signs(tmp_path):
    """GPS coordinates must come back as SIGNED decimal degrees
    (positive = North/East), whatever the hemisphere - verified in all
    four cases (N/E, N/W, S/E, S/W)."""
    cases = [
        ((48.8566, 2.3522), (48.8566, 2.3522)),     # Paris: N, E
        ((48.8566, -122.3522), (48.8566, -122.3522)),  # N, W
        ((-33.8688, 151.2093), (-33.8688, 151.2093)),  # S, E
        ((-33.8688, -70.6693), (-33.8688, -70.6693)),  # S, W
    ]
    for i, (gps_in, expected) in enumerate(cases):
        path = tmp_path / f"gps_{i}.jpg"
        _make_jpeg_with_exif(path, gps=gps_in)
        metadata = get_exif_metadata(path)
        lat, lon = metadata["gps"]
        assert lat == pytest.approx(expected[0], abs=1e-3)
        assert lon == pytest.approx(expected[1], abs=1e-3)


def test_nonexistent_file_never_raises(tmp_path):
    """A file that no longer exists (deleted between the scan and the
    generation, for example) must never crash the extraction - it should
    only produce empty metadata beyond the file name."""
    path = tmp_path / "introuvable.jpg"
    metadata = get_exif_metadata(path)
    assert metadata["filename"] == "introuvable.jpg"
    assert metadata.get("dimensions") is None


def test_corrupted_file_never_raises(tmp_path):
    """A file with an image extension but corrupted content must never
    raise an exception."""
    path = tmp_path / "corrompu.jpg"
    path.write_bytes(b"this is not a valid JPEG")
    metadata = get_exif_metadata(path)
    assert metadata["filename"] == "corrompu.jpg"
    assert metadata.get("camera") is None


def test_raw_extension_never_raises_even_without_valid_raw_content(tmp_path):
    """Resilience of the RAW path (exifread): a file with a RAW extension
    but invalid content (not a real RAW sensor file) must never raise an
    exception - see the module docstring for the real scope of this
    test."""
    path = tmp_path / "fake.nef"
    path.write_bytes(b"not a real RAW file")
    metadata = get_exif_metadata(path)
    assert metadata["filename"] == "fake.nef"
    assert metadata.get("camera") is None
    assert metadata.get("dimensions") is None
