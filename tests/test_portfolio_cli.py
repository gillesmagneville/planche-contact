# -*- coding: utf-8 -*-
"""
Test de non-régression : la pagination de portfolio.py (main()) doit tenir
compte de la réduction éventuelle du nombre de photos par page appliquée
par le modèle "grandes vignettes" ("large_thumbs" - voir
presentation.layout_engine.compute_effective_per_page()), plutôt que de
continuer à répartir les photos par lots de `config.num_per_sheet`
directement.

Avant ce correctif, `main()` calculait `total_pages` et la taille de
chaque lot à partir de `config.num_per_sheet` (le nombre demandé par
l'utilisateur), sans savoir que ContactSheetGenerator.create_contact_sheet()
ne dessine en réalité jamais plus de
`presentation.compute_effective_per_page(profile)` cellules par page pour
ce modèle (voir contactsheet.py, garde `idx >= effective_per_page`) : les
photos excédentaires d'une page trop chargée étaient donc silencieusement
ignorées, pour toujours (jamais reportées sur une page supplémentaire).

Le CLI n'a pas encore de drapeau `--profile` (étape ultérieure) pour
sélectionner "large_thumbs" lui-même : ce test construit donc le Profil
"à la place" de main(), par substitution de portfolio.portfolio.Config
(équivalent, une fois ce drapeau câblé, à un `--profile` pointant vers un
tel Profil) - mais exerce bien la VRAIE boucle de pagination de main(),
pas une réimplémentation de son calcul.
"""
import sys
from dataclasses import replace

from PIL import Image

import portfolio.portfolio as cli_module
from portfolio.config import Config as RealConfig
from portfolio.presentation import Profile, LayoutSettings, save_profile
from portfolio.presentation.layout_engine import LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE


def _make_photos(img_dir, n):
    img_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        Image.new("RGB", (800, 600), (90, 140, 200)).save(img_dir / f"img_{i:02d}.jpg", quality=90)


def test_large_thumbs_repaginates_instead_of_dropping_excess_photos(tmp_path, monkeypatch):
    photo_count = 20
    img_dir = tmp_path / "photos"
    out_dir = tmp_path / "out"
    _make_photos(img_dir, photo_count)

    # photo_count (20) > LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE (8) : l'ancien
    # calcul (base sur config.num_per_sheet, ici egal a photo_count) aurait
    # produit UNE seule page, qui n'aurait jamais dessine que les 8
    # premieres photos - les 12 autres auraient ete perdues sans message
    # d'erreur.
    assert photo_count > LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE

    def patched_config(*args, **kwargs):
        # Equivalent, une fois un futur drapeau --profile cable, a
        # `--profile large_thumbs.json` : seul le gabarit change, le reste
        # du comportement de Config (dont la synchronisation legacy de
        # Config.__post_init__) reste reel.
        cfg = RealConfig(*args, **kwargs)
        cfg.profile = replace(cfg.profile, layout=replace(cfg.profile.layout, template="large_thumbs"))
        return cfg

    monkeypatch.setattr(cli_module, "Config", patched_config)
    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_dir), "-n", str(photo_count)],
    )

    cli_module.main()

    planches = sorted((out_dir / "planches").glob("planche_*.jpg"))
    expected_pages = -(-photo_count // LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE)  # division entiere arrondie au-dessus
    assert len(planches) == expected_pages, (
        "la pagination doit suivre le nombre EFFECTIF de photos par page "
        "(reduit par le modele 'large_thumbs'), pas config.num_per_sheet "
        "directement - sans quoi des photos seraient perdues sans la "
        "moindre page supplementaire pour les accueillir"
    )


def _capture_config(monkeypatch):
    """Intercepte le VRAI objet Config construit par main() (pour
    l'inspecter ensuite), sans en modifier le comportement."""
    captured = {}

    def wrapper(*args, **kwargs):
        cfg = RealConfig(*args, **kwargs)
        captured["config"] = cfg
        return cfg

    monkeypatch.setattr(cli_module, "Config", wrapper)
    return captured


def test_profile_flag_is_loaded_and_applied(tmp_path, monkeypatch):
    """--profile (cahier des charges §2/§4.4) doit charger le fichier JSON
    et l'appliquer tel quel quand --format/--num restent à leur valeur par
    défaut (aucun conflit à arbitrer)."""
    img_dir = tmp_path / "photos"
    out_dir = tmp_path / "out"
    _make_photos(img_dir, 3)

    profile_path = tmp_path / "mon_profil.json"
    save_profile(Profile(layout=LayoutSettings(template="large_thumbs", per_page=8, page_format="A3")), profile_path)

    captured = _capture_config(monkeypatch)
    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_dir), "--profile", str(profile_path)],
    )
    cli_module.main()

    profile = captured["config"].profile
    assert profile.layout.template == "large_thumbs"
    assert profile.layout.per_page == 8
    assert profile.layout.page_format == "A3"


def test_profile_flag_absent_keeps_default_profile(tmp_path, monkeypatch):
    """Sans --profile, le comportement actuel (profil par défaut) ne doit
    strictement pas changer."""
    img_dir = tmp_path / "photos"
    out_dir = tmp_path / "out"
    _make_photos(img_dir, 3)

    captured = _capture_config(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["portfolio.py", "-i", str(img_dir), "-o", str(out_dir)])
    cli_module.main()

    profile = captured["config"].profile
    assert profile.layout.template == "grid"
    assert profile.layout.per_page == 12
    assert profile.layout.page_format == "A4"


def test_nonexistent_profile_falls_back_silently_to_default(tmp_path, monkeypatch, caplog):
    """Un chemin de profil invalide ne doit jamais interrompre la
    génération (voir presentation.load_profile(), jamais d'exception)."""
    img_dir = tmp_path / "photos"
    out_dir = tmp_path / "out"
    _make_photos(img_dir, 3)

    captured = _capture_config(monkeypatch)
    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_dir), "--profile", str(tmp_path / "absent.json")],
    )
    cli_module.main()  # ne doit lever aucune exception

    assert captured["config"].profile.layout.template == "grid"
    assert (out_dir / "planches" / "planche_001.jpg").exists()


def test_explicit_format_overrides_a_profile_left_at_its_default(tmp_path, monkeypatch):
    """Précédence documentée dans Config.__post_init__ : --format
    l'emporte sur le profil SEULEMENT si celui-ci n'a pas déjà personnalisé
    page_format (ici laissé à "A4", la valeur par défaut)."""
    img_dir = tmp_path / "photos"
    out_dir = tmp_path / "out"
    _make_photos(img_dir, 3)

    profile_path = tmp_path / "profil_format_defaut.json"
    save_profile(Profile(layout=LayoutSettings(template="landscape")), profile_path)  # page_format reste "A4"

    captured = _capture_config(monkeypatch)
    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_dir), "--profile", str(profile_path), "--format", "A3"],
    )
    cli_module.main()

    profile = captured["config"].profile
    assert profile.layout.template == "landscape"  # le reste du profil est conserve
    assert profile.layout.page_format == "A3"  # --format explicite l'emporte


def test_profile_already_customized_format_wins_over_explicit_format_flag(tmp_path, monkeypatch):
    """Précédence inverse, documentée comme limite explicite de
    l'heuristique (Config.__post_init__) : si le profil a DÉJÀ un
    page_format différent de la valeur par défaut, --format est purement
    et simplement ignoré."""
    img_dir = tmp_path / "photos"
    out_dir = tmp_path / "out"
    _make_photos(img_dir, 3)

    profile_path = tmp_path / "profil_format_personnalise.json"
    save_profile(Profile(layout=LayoutSettings(page_format="A2")), profile_path)

    captured = _capture_config(monkeypatch)
    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_dir), "--profile", str(profile_path), "--format", "A3"],
    )
    cli_module.main()

    assert captured["config"].profile.layout.page_format == "A2"
