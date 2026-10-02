# -*- coding: utf-8 -*-
"""
Tests de Config.__post_init__() - synchronisation rétrocompatible entre les
réglages "simples" historiques (page_format, num_per_sheet) et le nouveau
Profil (profile.layout.page_format/per_page), cahier des charges §2/§8.
"""
from pathlib import Path

from portfolio.config import Config
from portfolio.presentation import Profile, LayoutSettings


def test_default_profile_matches_default_legacy_fields():
    """Sans aucun réglage explicite, le Profil par défaut doit déjà
    correspondre aux valeurs par défaut historiques de Config (A4/12)."""
    config = Config(input_dir=Path("in"), output_dir=Path("out"))
    assert config.profile.layout.page_format == "A4"
    assert config.profile.layout.per_page == 12


def test_explicit_legacy_fields_sync_into_the_default_profile():
    """Cas réel actuel (CLI/interface graphique, pas de Profil fourni) :
    page_format/num_per_sheet explicites doivent se refléter dans le
    Profil interne, sans quoi le moteur de mise en page calculerait une
    géométrie incohérente avec ce que l'utilisateur a demandé."""
    config = Config(
        input_dir=Path("in"), output_dir=Path("out"),
        page_format="A3", num_per_sheet=24,
    )
    assert config.profile.layout.page_format == "A3"
    assert config.profile.layout.per_page == 24


def test_explicit_custom_profile_is_not_clobbered_by_default_legacy_fields():
    """Un Profil explicite (ex: --profile, étape ultérieure) dont le
    format/nombre par planche diffère DÉJÀ des valeurs par défaut de
    LayoutSettings ne doit pas être écrasé par les valeurs par défaut de
    Config (page_format="A4", num_per_sheet=12) quand elles n'ont, elles,
    pas été explicitement changées par l'appelant."""
    custom_profile = Profile(layout=LayoutSettings(page_format="A2", per_page=48))
    config = Config(input_dir=Path("in"), output_dir=Path("out"), profile=custom_profile)

    assert config.profile.layout.page_format == "A2"
    assert config.profile.layout.per_page == 48


def test_explicit_legacy_fields_do_not_override_an_already_customized_profile():
    """Précision du même comportement : si le Profil fourni a DÉJÀ un
    format différent des valeurs par défaut de LayoutSettings, un
    page_format legacy resté à sa valeur par défaut ("A4") ne doit pas
    l'emporter sur le Profil, plus spécifique (voir Config.__post_init__
    pour la limite explicitement documentée de cette heuristique)."""
    custom_profile = Profile(layout=LayoutSettings(page_format="A2"))
    config = Config(
        input_dir=Path("in"), output_dir=Path("out"),
        page_format="A4",  # valeur par défaut de Config, donc non "explicite" au sens de cette heuristique
        profile=custom_profile,
    )
    assert config.profile.layout.page_format == "A2"
