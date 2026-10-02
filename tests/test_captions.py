# -*- coding: utf-8 -*-
"""
Tests de portfolio.presentation.captions.resolve_caption_lines() - mise en
forme des légendes personnalisables par photo (cahier des charges §1),
indépendamment de l'extraction EXIF elle-même (voir tests/test_utils.py).
Les métadonnées utilisées ici sont donc des dictionnaires construits à la
main (déjà au format renvoyé par portfolio.utils.get_exif_metadata()),
pas de vraies photos - ce module ne teste que le FORMATAGE.
"""
from datetime import datetime

from portfolio.presentation import Profile, CaptionSettings, resolve_caption_lines


def test_no_fields_configured_returns_empty_list():
    """Comportement actuel (aucune légende) : CaptionSettings par défaut
    a `fields` vide - ne doit jamais rien afficher ni planter."""
    profile = Profile(captions=CaptionSettings())
    metadata = {"filename": "photo.jpg", "camera": "Canon EOS R5"}
    assert resolve_caption_lines(profile, metadata) == []


def test_empty_metadata_returns_empty_list():
    profile = Profile(captions=CaptionSettings(fields=["filename", "camera"]))
    assert resolve_caption_lines(profile, {}) == []


def test_missing_individual_field_is_silently_omitted():
    """Cahier des charges §1 : un champ sans métadonnée correspondante
    (ex : pas d'objectif renseigné) est omis, jamais une erreur ni un
    texte vide visible dans la légende."""
    profile = Profile(captions=CaptionSettings(fields=["filename", "lens", "camera"]))
    metadata = {"filename": "photo.jpg", "camera": "Canon EOS R5"}  # pas de "lens"

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
    """Vérifie le gabarit par défaut "raisonnable" de chaque type de champ
    (cahier des charges §1), un par un pour rester lisible en cas
    d'échec."""
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
    """Garantie de confidentialité (cahier des charges §1) : même si "gps"
    figure explicitement dans `fields`, il n'apparaît pas tant que
    show_gps n'est pas activé - cette garantie vient de
    CaptionSettings.effective_fields(), que resolve_caption_lines()
    utilise plutôt que `fields` directement."""
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
    """Un gabarit utilisateur invalide (clé de substitution inconnue, par
    exemple issu d'un profil corrompu ou mal édité à la main) ne doit
    jamais interrompre la génération : repli sur l'affichage par défaut."""
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
    """Demander plus de lignes que de champs réellement affichables (ex :
    3 lignes configurées mais un seul champ disponible pour cette photo)
    ne doit jamais produire de lignes vides - juste moins de lignes que
    demandé."""
    profile = Profile(captions=CaptionSettings(fields=["filename"], lines=3))
    metadata = {"filename": "p.jpg"}
    assert resolve_caption_lines(profile, metadata) == ["p.jpg"]


def test_unknown_or_malformed_field_value_is_omitted_not_raised():
    """Une métadonnée du mauvais type (ex : profil chargé après un
    changement de schéma, ou valeur corrompue) ne doit jamais faire
    planter la légende - le champ est simplement omis."""
    profile = Profile(captions=CaptionSettings(fields=["filename", "dimensions", "gps"]))
    metadata = {"filename": "p.jpg", "dimensions": "pas un tuple", "gps": (1,)}
    assert resolve_caption_lines(profile, metadata) == ["p.jpg"]
