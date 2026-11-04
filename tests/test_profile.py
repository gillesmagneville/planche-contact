# -*- coding: utf-8 -*-
"""
Tests of the Profile data model (portfolio/presentation/profile.py).

In particular covers the backward-compatibility requirement of the
specification: the absence of a profile, a partial profile or an invalid
profile must always fall back to a behaviour identical to the current
one, without ever raising an exception.
"""
import json

import pytest

from portfolio.presentation import (
    Profile,
    LayoutSettings,
    CaptionSettings,
    ThemeSettings,
    default_profile,
    load_profile,
    save_profile,
)


# ---------------------------------------------------------------------------
# Default values = current behaviour
# ---------------------------------------------------------------------------

def test_default_profile_matches_current_behavior():
    """The default values must match exactly what is hard-coded today in
    contactsheet.py/htmlgallery.py: light theme, no caption, "grid"
    template, 12 mm margin / 5 mm spacing (see
    ContactSheetGenerator.create_contact_sheet)."""
    p = default_profile()
    assert p.theme.mode == "light"
    assert p.captions.fields == []
    assert p.captions.effective_fields() == []
    assert p.layout.template == "grid"
    assert p.layout.margin_mm == 12.0
    assert p.layout.spacing_mm == 5.0
    assert p.layout.per_page == 12
    assert p.layout.page_format == "A4"
    assert p.layout.caption_position == "none"


def test_default_profile_is_independent_instance():
    """Two calls return independent objects (not a mutable singleton
    shared by accident between two successive generations)."""
    a = default_profile()
    b = default_profile()
    a.layout.per_page = 99
    assert b.layout.per_page == 12


# ---------------------------------------------------------------------------
# JSON round trip
# ---------------------------------------------------------------------------

def test_save_then_load_roundtrip(tmp_path):
    profile = Profile(
        name="Mon profil",
        layout=LayoutSettings(template="large_thumbs", per_page=8, page_format="A3"),
        captions=CaptionSettings(fields=["filename", "camera", "aperture"], show_gps=False),
        theme=ThemeSettings(mode="dark"),
    )
    path = tmp_path / "profil.json"
    save_profile(profile, path)

    loaded = load_profile(path)
    assert loaded.name == "Mon profil"
    assert loaded.layout.template == "large_thumbs"
    assert loaded.layout.per_page == 8
    assert loaded.layout.page_format == "A3"
    assert loaded.captions.fields == ["filename", "camera", "aperture"]
    assert loaded.theme.mode == "dark"


def test_save_produces_readable_json(tmp_path):
    """The produced file must be standard JSON, readable/editable by hand
    (specification §2: profiles "preferably in JSON format")."""
    path = tmp_path / "profil.json"
    save_profile(default_profile(), path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["layout"]["template"] == "grid"
    assert data["theme"]["mode"] == "light"


# ---------------------------------------------------------------------------
# Resilience: never an exception, always a usable profile
# ---------------------------------------------------------------------------

def test_load_missing_file_returns_default(tmp_path):
    loaded = load_profile(tmp_path / "n_existe_pas.json")
    assert loaded == default_profile()


def test_load_malformed_json_returns_default(tmp_path):
    path = tmp_path / "corrompu.json"
    path.write_text("{this is not valid JSON", encoding="utf-8")
    loaded = load_profile(path)
    assert loaded == default_profile()


def test_load_json_array_instead_of_object_returns_default(tmp_path):
    """A profile "from an older/newer version of the project" that is not
    even structurally an object must not crash the generation."""
    path = tmp_path / "tableau.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    loaded = load_profile(path)
    assert loaded == default_profile()


def test_partial_profile_merges_with_defaults(tmp_path):
    """A profile that only sets a subset of the fields (e.g. produced by an
    earlier version of the application, before a new field was added) must
    silently be completed with the default values, never raise an exception
    nor ignore the whole profile."""
    path = tmp_path / "partiel.json"
    path.write_text(json.dumps({"layout": {"per_page": 20}}), encoding="utf-8")
    loaded = load_profile(path)
    assert loaded.layout.per_page == 20
    assert loaded.layout.template == "grid"  # default value, not set
    assert loaded.theme.mode == "light"      # missing group -> default values


def test_unknown_top_level_and_nested_keys_are_ignored(tmp_path):
    """Forward compatibility: a profile produced by a FUTURE version of the
    project (fields still unknown here) must be accepted without error, the
    unknown fields simply being ignored."""
    path = tmp_path / "futur.json"
    path.write_text(json.dumps({
        "layout": {"per_page": 10, "champ_du_futur": 42},
        "un_groupe_qui_n_existe_pas_encore": {"x": 1},
    }), encoding="utf-8")
    loaded = load_profile(path)
    assert loaded.layout.per_page == 10


@pytest.mark.parametrize("bad_template", ["", "n_importe_quoi", 42, None])
def test_invalid_layout_template_falls_back_to_default(bad_template):
    settings = LayoutSettings.from_dict({"template": bad_template})
    assert settings.template == "grid"


def test_invalid_page_format_falls_back_to_default():
    settings = LayoutSettings.from_dict({"page_format": "A0"})  # not supported
    assert settings.page_format == "A4"


def test_negative_or_wrong_type_numeric_values_fall_back():
    settings = LayoutSettings.from_dict({"margin_mm": "beaucoup", "per_page": -5})
    assert settings.margin_mm == 12.0
    # per_page: a negative integer is not rejected by the generic coercer
    # (only the type is checked here, the business bound is up to the
    # future layout_engine.py), but a string or a None must indeed fall
    # back to the default:
    settings2 = LayoutSettings.from_dict({"per_page": "douze"})
    assert settings2.per_page == 12


def test_profile_from_dict_with_non_dict_input_returns_default():
    assert Profile.from_dict(None) == Profile()
    assert Profile.from_dict("texte") == Profile()
    assert Profile.from_dict([1, 2]) == Profile()


# ---------------------------------------------------------------------------
# Captions: GPS privacy
# ---------------------------------------------------------------------------

def test_gps_is_excluded_unless_explicitly_enabled():
    """Specification §1: GPS coordinates must be explicitly hideable - by
    default (show_gps=False), even if "gps" appears in the list of fields,
    it must never be displayed."""
    settings = CaptionSettings(fields=["filename", "gps", "camera"], show_gps=False)
    assert "gps" not in settings.effective_fields()
    assert settings.effective_fields() == ["filename", "camera"]


def test_gps_is_included_when_explicitly_enabled():
    settings = CaptionSettings(fields=["filename", "gps"], show_gps=True)
    assert settings.effective_fields() == ["filename", "gps"]


def test_unknown_caption_field_is_ignored(tmp_path):
    settings = CaptionSettings.from_dict({"fields": ["filename", "champ_inconnu", "camera"]})
    assert settings.fields == ["filename", "camera"]


def test_duplicate_caption_fields_are_deduplicated():
    settings = CaptionSettings.from_dict({"fields": ["filename", "filename", "camera"]})
    assert settings.fields == ["filename", "camera"]


# ---------------------------------------------------------------------------
# Theme: custom colours
# ---------------------------------------------------------------------------

def test_invalid_custom_color_is_ignored():
    theme = ThemeSettings.from_dict({"mode": "dark", "custom": {"background": "not-a-colour"}})
    assert theme.mode == "dark"
    assert theme.custom.background is None


def test_valid_custom_colors_are_kept():
    theme = ThemeSettings.from_dict({
        "mode": "neutral",
        "custom": {"background": "#112233", "accent": "#ff8800"},
    })
    assert theme.custom.background == "#112233"
    assert theme.custom.accent == "#ff8800"
    assert theme.custom.text is None
