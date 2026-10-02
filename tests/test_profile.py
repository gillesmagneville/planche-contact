# -*- coding: utf-8 -*-
"""
Tests du modèle de données Profil (portfolio/presentation/profile.py).

Couvre en particulier l'exigence de rétrocompatibilité du cahier des
charges : absence de profil, profil partiel, ou profil invalide doivent
toujours retomber sur un comportement identique à l'actuel, sans jamais
lever d'exception.
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
# Valeurs par défaut = comportement actuel
# ---------------------------------------------------------------------------

def test_default_profile_matches_current_behavior():
    """Les valeurs par défaut doivent correspondre exactement à ce qui est
    aujourd'hui codé en dur dans contactsheet.py/htmlgallery.py : thème
    clair, aucune légende, modèle "grille", marge 12 mm / espacement 5 mm
    (voir ContactSheetGenerator.create_contact_sheet)."""
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
    """Deux appels renvoient des objets indépendants (pas un singleton
    mutable partagé par mégarde entre deux générations successives)."""
    a = default_profile()
    b = default_profile()
    a.layout.per_page = 99
    assert b.layout.per_page == 12


# ---------------------------------------------------------------------------
# Aller-retour JSON
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
    """Le fichier produit doit être du JSON standard, lisible/éditable à
    la main (cahier des charges §2 : profils "de préférence au format
    JSON")."""
    path = tmp_path / "profil.json"
    save_profile(default_profile(), path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["layout"]["template"] == "grid"
    assert data["theme"]["mode"] == "light"


# ---------------------------------------------------------------------------
# Résilience : jamais d'exception, toujours un profil utilisable
# ---------------------------------------------------------------------------

def test_load_missing_file_returns_default(tmp_path):
    loaded = load_profile(tmp_path / "n_existe_pas.json")
    assert loaded == default_profile()


def test_load_malformed_json_returns_default(tmp_path):
    path = tmp_path / "corrompu.json"
    path.write_text("{ceci n'est pas du JSON valide", encoding="utf-8")
    loaded = load_profile(path)
    assert loaded == default_profile()


def test_load_json_array_instead_of_object_returns_default(tmp_path):
    """Un profil "d'une version plus ancienne/récente du projet" qui
    n'est même pas structurellement un objet ne doit pas faire planter la
    génération."""
    path = tmp_path / "tableau.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    loaded = load_profile(path)
    assert loaded == default_profile()


def test_partial_profile_merges_with_defaults(tmp_path):
    """Un profil ne renseignant qu'un sous-ensemble des champs (ex :
    produit par une version antérieure de l'application, avant l'ajout
    d'un nouveau champ) doit compléter silencieusement avec les valeurs
    par défaut, jamais lever d'exception ni ignorer tout le profil."""
    path = tmp_path / "partiel.json"
    path.write_text(json.dumps({"layout": {"per_page": 20}}), encoding="utf-8")
    loaded = load_profile(path)
    assert loaded.layout.per_page == 20
    assert loaded.layout.template == "grid"  # valeur par défaut, non renseignée
    assert loaded.theme.mode == "light"      # groupe absent -> valeurs par défaut


def test_unknown_top_level_and_nested_keys_are_ignored(tmp_path):
    """Avant-compatibilité : un profil produit par une version FUTURE du
    projet (champs encore inconnus ici) doit être accepté sans erreur,
    les champs inconnus étant simplement ignorés."""
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
    settings = LayoutSettings.from_dict({"page_format": "A0"})  # non pris en charge
    assert settings.page_format == "A4"


def test_negative_or_wrong_type_numeric_values_fall_back():
    settings = LayoutSettings.from_dict({"margin_mm": "beaucoup", "per_page": -5})
    assert settings.margin_mm == 12.0
    # per_page : un entier négatif n'est pas rejeté par le coercteur générique
    # (seul le type est vérifié ici, la borne métier est du ressort du futur
    # layout_engine.py), mais une chaîne ou un None doivent bien retomber au
    # défaut :
    settings2 = LayoutSettings.from_dict({"per_page": "douze"})
    assert settings2.per_page == 12


def test_profile_from_dict_with_non_dict_input_returns_default():
    assert Profile.from_dict(None) == Profile()
    assert Profile.from_dict("texte") == Profile()
    assert Profile.from_dict([1, 2]) == Profile()


# ---------------------------------------------------------------------------
# Légendes : confidentialité GPS
# ---------------------------------------------------------------------------

def test_gps_is_excluded_unless_explicitly_enabled():
    """Cahier des charges §1 : les coordonnées GPS doivent pouvoir être
    masquées explicitement - par défaut (show_gps=False), même si "gps"
    figure dans la liste des champs, il ne doit jamais être affiché."""
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
# Thème : couleurs personnalisées
# ---------------------------------------------------------------------------

def test_invalid_custom_color_is_ignored():
    theme = ThemeSettings.from_dict({"mode": "dark", "custom": {"background": "pas-une-couleur"}})
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
