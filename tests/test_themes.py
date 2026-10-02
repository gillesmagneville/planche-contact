# -*- coding: utf-8 -*-
"""
Tests de portfolio.presentation.themes (cahier des charges §4 : thèmes
Light/Dark/Neutral/System, personnalisation de couleurs).
"""
from portfolio.presentation import (
    ThemeSettings, ThemeCustomColors, Palette, get_palette, resolve_theme,
    apply_custom_colors,
)


def test_light_theme_matches_current_hardcoded_contactsheet_colors():
    """Rétrocompatibilité stricte (cahier des charges §2/§4/§8) : le thème
    "light" (celui du Profil par défaut) doit reproduire EXACTEMENT les
    couleurs actuellement codées en dur dans
    ContactSheetGenerator._draw_header()/_draw_page_number() - fond
    "white", texte "black", texte secondaire "#555555"."""
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
    """Un appelant sans contexte graphique (le CLI, notamment) n'a aucun
    moyen de connaître le thème du système : à défaut d'indication
    explicite, "system" doit se comporter comme "light" - cohérent avec
    la règle de rétrocompatibilité stricte."""
    assert resolve_theme(ThemeSettings(mode="system")) == get_palette("light")


def test_custom_colors_override_individual_fields_only():
    custom = ThemeCustomColors(background="#112233", accent="#ff0000")
    theme = ThemeSettings(mode="light", custom=custom)
    palette = resolve_theme(theme)

    assert palette.background == "#112233"
    assert palette.accent == "#ff0000"
    # Les champs non personnalisés restent ceux de la palette de base.
    assert palette.text == "#000000"
    assert palette.border == "#dddddd"
    # text_secondary n'est jamais personnalisable (pas de champ
    # correspondant dans ThemeCustomColors).
    assert palette.text_secondary == "#555555"


def test_invalid_custom_color_falls_back_to_base_palette_value():
    """Une couleur personnalisée mal formée (ex : un profil édité à la
    main avec une faute de frappe) ne doit jamais produire une couleur
    cassée ni une exception - repli silencieux sur la valeur de base."""
    base = get_palette("dark")
    custom = ThemeCustomColors(background="pas-une-couleur", text="#zzzzzz", accent="#ab")
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
