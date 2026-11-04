# -*- coding: utf-8 -*-
"""
Tests of portfolio.presentation.themes (specification §4: Light/Dark/
Neutral/System themes, colour customisation).
"""
from portfolio.presentation import (
    ThemeSettings, ThemeCustomColors, Palette, get_palette, resolve_theme,
    apply_custom_colors,
)


def test_light_theme_matches_current_hardcoded_contactsheet_colors():
    """Strict backward compatibility (specification §2/§4/§8): the "light"
    theme (that of the default Profile) must reproduce EXACTLY the colours
    currently hard-coded in
    ContactSheetGenerator._draw_header()/_draw_page_number() - "white"
    background, "black" text, "#555555" secondary text."""
    palette = resolve_theme(ThemeSettings())
    assert palette.background == "#ffffff"
    assert palette.text == "#000000"
    assert palette.text_secondary == "#555555"


def test_get_palette_returns_three_distinct_predefined_modes():
    light = get_palette("light")
    dark = get_palette("dark")
    neutral = get_palette("neutral")

    for palette in (light, dark, neutral):
        assert isinstance(palette, Palette)

    assert light != dark
    assert light != neutral
    assert dark != neutral


def test_get_palette_unknown_mode_falls_back_to_light():
    assert get_palette("solarized-ultra") == get_palette("light")


def test_resolve_theme_system_mode_uses_prefer_dark_flag():
    system_theme = ThemeSettings(mode="system")

    assert resolve_theme(system_theme, prefer_dark=False) == get_palette("light")
    assert resolve_theme(system_theme, prefer_dark=True) == get_palette("dark")


def test_resolve_theme_system_defaults_to_light_without_a_graphical_context():
    """A caller without a graphical context (the CLI, notably) has no way
    of knowing the system theme: lacking an explicit indication, "system"
    must behave like "light" - consistent with the strict backward
    compatibility rule."""
    assert resolve_theme(ThemeSettings(mode="system")) == get_palette("light")


def test_custom_colors_override_individual_fields_only():
    custom = ThemeCustomColors(background="#112233", accent="#ff0000")
    theme = ThemeSettings(mode="light", custom=custom)
    palette = resolve_theme(theme)

    assert palette.background == "#112233"
    assert palette.accent == "#ff0000"
    # The non-customised fields stay those of the base palette.
    assert palette.text == "#000000"
    assert palette.border == "#dddddd"
    # text_secondary is never customisable (no corresponding field in
    # ThemeCustomColors).
    assert palette.text_secondary == "#555555"


def test_invalid_custom_color_falls_back_to_base_palette_value():
    """A malformed custom colour (e.g. a hand-edited profile with a typo)
    must never produce a broken colour nor an exception - silent fallback
    to the base value."""
    base = get_palette("dark")
    custom = ThemeCustomColors(background="not-a-colour", text="#zzzzzz", accent="#ab")
    resolved = apply_custom_colors(base, custom)
    assert resolved.background == base.background
    assert resolved.text == base.text
    assert resolved.accent == base.accent


def test_custom_colors_accept_three_and_six_digit_hex():
    custom = ThemeCustomColors(background="#fff", text="#000000")
    resolved = apply_custom_colors(get_palette("light"), custom)
    assert resolved.background == "#fff"
    assert resolved.text == "#000000"


def test_apply_custom_colors_with_no_overrides_returns_base_values():
    base = get_palette("neutral")
    resolved = apply_custom_colors(base, ThemeCustomColors())
    assert resolved == base
