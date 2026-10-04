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


# ---------------------------------------------------------------------------
# layout_caption_lines() : retour à la ligne dans une largeur en pixels
# (rendu JPEG/PDF) - correctif du bug "informations tronquées par « … »
# sous les photos" (voir CHANGELOG.md).
# ---------------------------------------------------------------------------

from portfolio.presentation import layout_caption_lines  # noqa: E402

_FULL_METADATA = {
    "filename": "photo.jpg",
    "camera": "Canon EOS R5",
    "lens": "RF 24-70mm F2.8 L IS USM",
    "dimensions": (6000, 4000),
}


def _measure(text):
    """Police fictive à chasse fixe : 10 px par caractère - rend les
    largeurs prévisibles sans dépendre d'une vraie police."""
    return len(text) * 10


def test_layout_caption_lines_wraps_at_field_boundaries_instead_of_overflowing():
    """Avec plusieurs champs et lines=1, tout tenait sur UNE ligne bien plus
    large qu'une vignette. Les champs doivent maintenant passer à la ligne
    AVANT de dépasser la largeur, sans jamais couper un champ en deux ni
    laisser le séparateur en début/fin de ligne."""
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
    """Aucune régression pour le cas ordinaire : quand la largeur suffit,
    le résultat est exactement celui de resolve_caption_lines(), y compris
    la répartition explicite sur `lines` lignes."""
    for n_lines in (1, 2, 3):
        profile = Profile(captions=CaptionSettings(
            fields=["filename", "camera", "lens", "dimensions"], lines=n_lines,
        ))
        assert (
            layout_caption_lines(profile, _FULL_METADATA, max_width=100_000, measure=_measure)
            == resolve_caption_lines(profile, _FULL_METADATA)
        ), n_lines


def test_layout_caption_lines_wraps_inside_a_single_field_that_is_too_wide():
    """Un champ À LUI SEUL plus large que la zone (nom d'objectif long)
    passe à la ligne aux espaces, plutôt que d'être tronqué."""
    profile = Profile(captions=CaptionSettings(fields=["lens"], lines=1))

    lines = layout_caption_lines(profile, _FULL_METADATA, max_width=150, measure=_measure)

    assert lines == ["RF 24-70mm F2.8", "L IS USM"]


def test_layout_caption_lines_keeps_a_single_oversized_word_intact():
    """Un mot sans espace plus large que la zone n'est jamais découpé ici
    (ce module ne connaît pas le rendu) : c'est contactsheet._draw_caption()
    qui le borne à l'affichage."""
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
