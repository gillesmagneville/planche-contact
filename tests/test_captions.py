# -*- coding: utf-8 -*-
"""
Tests of portfolio.presentation.captions.resolve_caption_lines() -
formatting of the per-photo customisable captions (specification §1),
independently of the EXIF extraction itself (see tests/test_utils.py).
The metadata used here are therefore hand-built dictionaries (already in
the format returned by portfolio.utils.get_exif_metadata()), not real
photos - this module only tests the FORMATTING.
"""
from datetime import datetime

from portfolio.presentation import Profile, CaptionSettings, resolve_caption_lines


def test_no_fields_configured_returns_empty_list():
    """Current behaviour (no caption): the default CaptionSettings has an
    empty `fields` - must never display anything nor crash."""
    profile = Profile(captions=CaptionSettings())
    metadata = {"filename": "photo.jpg", "camera": "Canon EOS R5"}
    assert resolve_caption_lines(profile, metadata) == []


def test_empty_metadata_returns_empty_list():
    profile = Profile(captions=CaptionSettings(fields=["filename", "camera"]))
    assert resolve_caption_lines(profile, {}) == []


def test_missing_individual_field_is_silently_omitted():
    """Specification §1: a field with no corresponding metadata (e.g. no
    lens recorded) is omitted, never an error nor visible empty text in the
    caption."""
    profile = Profile(captions=CaptionSettings(fields=["filename", "lens", "camera"]))
    metadata = {"filename": "photo.jpg", "camera": "Canon EOS R5"}  # no "lens"

    lines = resolve_caption_lines(profile, metadata)
    assert lines == ["photo.jpg · Canon EOS R5"]


def test_fields_appear_in_the_order_the_user_chose():
    profile = Profile(captions=CaptionSettings(fields=["camera", "filename"]))
    metadata = {"filename": "photo.jpg", "camera": "Canon EOS R5"}

    lines = resolve_caption_lines(profile, metadata)
    assert lines == ["Canon EOS R5 · photo.jpg"]


def test_custom_separator_is_used():
    profile = Profile(captions=CaptionSettings(fields=["filename", "camera"], separator=" | "))
    metadata = {"filename": "photo.jpg", "camera": "Canon EOS R5"}
    assert resolve_caption_lines(profile, metadata) == ["photo.jpg | Canon EOS R5"]


def test_default_formatting_for_each_field_type():
    """Checks the default "reasonable" template of each field type
    (specification §1), one by one to stay readable on failure."""
    base_metadata = {
        "filename": "IMG_0001.jpg",
        "datetime": datetime(2024, 5, 1, 12, 30, 0),
        "camera": "Canon EOS R5",
        "lens": "RF 24-70mm F2.8",
        "focal_length": 50.0,
        "focal_35mm": 50,
        "aperture": 2.8,
        "shutter_speed": 0.004,  # 1/250s
        "iso": 400,
        "dimensions": (4000, 3000),
        "gps": (48.8566, 2.3522),
    }
    expected = {
        "filename": "IMG_0001.jpg",
        "datetime": "2024-05-01",
        "camera": "Canon EOS R5",
        "lens": "RF 24-70mm F2.8",
        "focal_length": "50 mm",
        "focal_35mm": "50 mm (éq. 24×36)",
        "aperture": "f/2.8",
        "shutter_speed": "1/250s",
        "iso": "ISO 400",
        "dimensions": "4000 × 3000",
        "gps": "48.8566°N, 2.3522°E",
    }
    for field, expected_text in expected.items():
        profile = Profile(captions=CaptionSettings(fields=[field], show_gps=True))
        assert resolve_caption_lines(profile, base_metadata) == [expected_text], field


def test_shutter_speed_long_exposure_uses_decimal_not_fraction():
    profile = Profile(captions=CaptionSettings(fields=["shutter_speed"]))
    metadata = {"shutter_speed": 2.0}
    assert resolve_caption_lines(profile, metadata) == ["2s"]

    metadata_fraction = {"shutter_speed": 1.5}
    assert resolve_caption_lines(profile, metadata_fraction) == ["1.5s"]


def test_gps_hidden_by_default_even_if_listed_in_fields():
    """Privacy guarantee (specification §1): even if "gps" is explicitly in
    `fields`, it does not appear as long as show_gps is not enabled - this
    guarantee comes from CaptionSettings.effective_fields(), which
    resolve_caption_lines() uses rather than `fields` directly."""
    profile = Profile(captions=CaptionSettings(fields=["filename", "gps"], show_gps=False))
    metadata = {"filename": "photo.jpg", "gps": (48.8566, 2.3522)}
    assert resolve_caption_lines(profile, metadata) == ["photo.jpg"]


def test_gps_shown_when_explicitly_enabled():
    profile = Profile(captions=CaptionSettings(fields=["gps"], show_gps=True))
    metadata = {"gps": (48.8566, 2.3522)}
    assert resolve_caption_lines(profile, metadata) == ["48.8566°N, 2.3522°E"]


def test_format_override_wraps_default_display():
    profile = Profile(captions=CaptionSettings(
        fields=["aperture"], format_overrides={"aperture": "Ouverture : {value}"},
    ))
    metadata = {"aperture": 2.8}
    assert resolve_caption_lines(profile, metadata) == ["Ouverture : f/2.8"]


def test_invalid_format_override_falls_back_to_default_display():
    """An invalid user template (unknown substitution key, for example from
    a corrupted or badly hand-edited profile) must never interrupt the
    generation: fall back to the default display."""
    profile = Profile(captions=CaptionSettings(
        fields=["iso"], format_overrides={"iso": "{valeur_invalide}"},
    ))
    metadata = {"iso": 400}
    assert resolve_caption_lines(profile, metadata) == ["ISO 400"]


def test_lines_distributes_fields_evenly_in_order():
    profile = Profile(captions=CaptionSettings(
        fields=["filename", "camera", "aperture", "iso"], lines=2,
    ))
    metadata = {"filename": "p.jpg", "camera": "Canon EOS R5", "aperture": 2.8, "iso": 400}

    lines = resolve_caption_lines(profile, metadata)
    assert lines == ["p.jpg · Canon EOS R5", "f/2.8 · ISO 400"]


def test_lines_greater_than_available_fields_drops_empty_lines():
    """Asking for more lines than there are really displayable fields (e.g.
    3 lines configured but only one field available for this photo) must
    never produce empty lines - just fewer lines than requested."""
    profile = Profile(captions=CaptionSettings(fields=["filename"], lines=3))
    metadata = {"filename": "p.jpg"}
    assert resolve_caption_lines(profile, metadata) == ["p.jpg"]


def test_unknown_or_malformed_field_value_is_omitted_not_raised():
    """A metadata item of the wrong type (e.g. a profile loaded after a
    schema change, or a corrupted value) must never crash the caption - the
    field is simply omitted."""
    profile = Profile(captions=CaptionSettings(fields=["filename", "dimensions", "gps"]))
    metadata = {"filename": "p.jpg", "dimensions": "not a tuple", "gps": (1,)}
    assert resolve_caption_lines(profile, metadata) == ["p.jpg"]


# ---------------------------------------------------------------------------
# layout_caption_lines(): wrapping within a width in pixels
# (JPEG/PDF rendering) - fix for the bug "information truncated by "…"
# under the photos" (see CHANGELOG.md).
# ---------------------------------------------------------------------------

from portfolio.presentation import layout_caption_lines  # noqa: E402

_FULL_METADATA = {
    "filename": "photo.jpg",
    "camera": "Canon EOS R5",
    "lens": "RF 24-70mm F2.8 L IS USM",
    "dimensions": (6000, 4000),
}


def _measure(text):
    """Fixed-width fake font: 10 px per character - makes widths
    predictable without depending on a real font."""
    return len(text) * 10


def test_layout_caption_lines_wraps_at_field_boundaries_instead_of_overflowing():
    """With several fields and lines=1, everything used to fit on ONE line
    much wider than a thumbnail. The fields must now wrap BEFORE exceeding
    the width, without ever splitting a field in two nor leaving the
    separator at the start/end of a line."""
    profile = Profile(captions=CaptionSettings(
        fields=["filename", "camera", "lens", "dimensions"], lines=1,
    ))

    lines = layout_caption_lines(profile, _FULL_METADATA, max_width=300, measure=_measure)

    assert lines == [
        "photo.jpg · Canon EOS R5",
        "RF 24-70mm F2.8 L IS USM",
        "6000 × 4000",
    ]
    assert all(_measure(line) <= 300 for line in lines)


def test_layout_caption_lines_is_identical_to_resolve_caption_lines_when_everything_fits():
    """No regression for the ordinary case: when the width is sufficient,
    the result is exactly that of resolve_caption_lines(), including the
    explicit split over `lines` lines."""
    for n_lines in (1, 2, 3):
        profile = Profile(captions=CaptionSettings(
            fields=["filename", "camera", "lens", "dimensions"], lines=n_lines,
        ))
        assert (
            layout_caption_lines(profile, _FULL_METADATA, max_width=100_000, measure=_measure)
            == resolve_caption_lines(profile, _FULL_METADATA)
        ), n_lines


def test_layout_caption_lines_wraps_inside_a_single_field_that_is_too_wide():
    """A field that ALONE is wider than the area (long lens name) wraps at
    spaces, rather than being truncated."""
    profile = Profile(captions=CaptionSettings(fields=["lens"], lines=1))

    lines = layout_caption_lines(profile, _FULL_METADATA, max_width=150, measure=_measure)

    assert lines == ["RF 24-70mm F2.8", "L IS USM"]


def test_layout_caption_lines_keeps_a_single_oversized_word_intact():
    """A word without spaces wider than the area is never split here (this
    module does not know the rendering): it is contactsheet._draw_caption()
    that bounds it at display time."""
    profile = Profile(captions=CaptionSettings(fields=["filename", "camera"], lines=1))
    metadata = {"filename": "a_very_long_filename_without_any_space.jpg", "camera": "Canon"}

    lines = layout_caption_lines(profile, metadata, max_width=100, measure=_measure)

    assert lines == ["a_very_long_filename_without_any_space.jpg", "Canon"]


def test_layout_caption_lines_returns_empty_list_without_fields_or_metadata():
    assert layout_caption_lines(Profile(captions=CaptionSettings()), _FULL_METADATA, 300, _measure) == []
    profile = Profile(captions=CaptionSettings(fields=["filename"]))
    assert layout_caption_lines(profile, {}, 300, _measure) == []


def test_layout_caption_lines_degenerate_width_falls_back_to_plain_lines():
    profile = Profile(captions=CaptionSettings(fields=["filename", "camera"], lines=1))
    assert (
        layout_caption_lines(profile, _FULL_METADATA, max_width=0, measure=_measure)
        == resolve_caption_lines(profile, _FULL_METADATA)
    )
