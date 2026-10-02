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
