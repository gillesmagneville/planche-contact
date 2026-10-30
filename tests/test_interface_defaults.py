# -*- coding: utf-8 -*-
"""
Réglages par défaut de l'INTERFACE GRAPHIQUE : « Nom du fichier » est
coché (nom du fichier sous chaque photo), alors que la ligne de commande,
sans --profile, ne met toujours aucune légende (default_profile() inchangé,
ce dont dépendent les scripts existants).
"""
from portfolio.config import Config
from portfolio.contactsheet import ContactSheetGenerator
from portfolio.presentation import (
    default_profile, interface_default_profile, load_profile, save_profile,
)
from portfolio.thumbnail import ThumbnailGenerator
from PIL import Image


def test_the_command_line_default_profile_still_has_no_caption():
    profile = default_profile()
    assert profile.captions.fields == []
    assert profile.layout.caption_position == "none"


def test_the_interface_default_shows_the_file_name_below_each_photo():
    profile = interface_default_profile()
    assert profile.captions.fields == ["filename"]
    assert profile.layout.caption_position == "below"


def test_the_interface_default_differs_from_the_command_line_default():
    """C'est cette différence qui fait que l'interface transmet toujours
    son profil au CLI (--profile) : sans elle, la légende par défaut ne
    serait jamais appliquée."""
    assert interface_default_profile() != default_profile()


def test_the_interface_default_keeps_every_other_setting_of_the_default_profile():
    base, gui = default_profile(), interface_default_profile()
    assert gui.theme == base.theme
    assert gui.layout.template == base.layout.template
    assert gui.layout.per_page == base.layout.per_page
    assert gui.layout.page_format == base.layout.page_format
    assert gui.captions.show_gps is False
    assert gui.captions.lines == base.captions.lines


def test_the_interface_default_survives_a_save_and_load(tmp_path):
    path = tmp_path / "profil.json"
    save_profile(interface_default_profile(), path)
    assert load_profile(path) == interface_default_profile()


def test_a_sheet_made_with_the_interface_default_carries_the_file_names(tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    images = []
    for name in ("alpha.jpg", "beta.jpg"):
        Image.new("RGB", (80, 60), (200, 100, 50)).save(photos / name)
        images.append({"path": photos / name, "filename": name})
    config = Config(input_dir=photos, output_dir=tmp_path / "out", profile=interface_default_profile())
    gen = ContactSheetGenerator(config, ThumbnailGenerator(config))
    gen.create_contact_sheet(images, 1, 1)
    texts = [run.text for run in gen.last_text_runs]
    assert "alpha.jpg" in texts and "beta.jpg" in texts
