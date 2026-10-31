# -*- coding: utf-8 -*-
"""
Choix des sous-dossiers d'un dossier principal.

`Config.include_dirs` restreint le scan aux photos situées DIRECTEMENT dans
les dossiers listés (chemins relatifs POSIX, "." = le dossier d'entrée) ;
`scanner.list_image_folders()` fournit la liste des dossiers possibles (celle
que l'interface graphique propose) ; la ligne de commande expose le tout par
--include-dir (répétable) et --include-dirs-file (un dossier par ligne).
Sans ces options, rien ne change : toutes les photos sont traitées.
"""
import sys
from pathlib import Path

import pytest
from PIL import Image

import portfolio.portfolio as cli_module
from portfolio.config import Config
from portfolio.scanner import ImageScanner, list_image_folders, normalize_include_dir


def _photo(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), (120, 120, 120)).save(path, quality=80)


@pytest.fixture
def tree(tmp_path):
    """
    photos/
      racine1.jpg racine2.jpg
      Paris/          a.jpg b.jpg c.jpg
      Paris/Louvre/   d.jpg
      été 2026/       e.jpg
      vide/           notes.txt
    """
    root = tmp_path / "photos"
    for rel in ("racine1.jpg", "racine2.jpg", "Paris/a.jpg", "Paris/b.jpg", "Paris/c.jpg",
                "Paris/Louvre/d.jpg", "été 2026/e.jpg"):
        _photo(root / rel)
    (root / "vide").mkdir()
    (root / "vide" / "notes.txt").write_text("pas une photo")
    return root


def _scan(root, tmp_path, **kwargs):
    config = Config(input_dir=root, output_dir=tmp_path / "out", sort_by="name", **kwargs)
    return [item["path"].relative_to(root).as_posix() for item in ImageScanner(config).scan()]


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def test_without_include_dirs_the_scan_is_unchanged(tree, tmp_path):
    assert _scan(tree, tmp_path) == ["racine1.jpg", "racine2.jpg"]
    assert len(_scan(tree, tmp_path, recursive=True)) == 7


def test_only_the_selected_folders_are_scanned_even_without_the_recursive_option(tree, tmp_path):
    assert _scan(tree, tmp_path, include_dirs=("Paris",)) == [
        "Paris/a.jpg", "Paris/b.jpg", "Paris/c.jpg"]


def test_only_photos_directly_inside_a_selected_folder_are_kept(tree, tmp_path):
    """Cocher « Paris » ne coche pas « Paris/Louvre » : chaque dossier se choisit à part."""
    found = _scan(tree, tmp_path, include_dirs=("Paris",))
    assert "Paris/Louvre/d.jpg" not in found
    found = _scan(tree, tmp_path, include_dirs=("Paris", "Paris/Louvre"))
    assert "Paris/Louvre/d.jpg" in found


def test_the_main_folder_itself_is_selected_with_a_dot(tree, tmp_path):
    assert _scan(tree, tmp_path, include_dirs=(".",)) == ["racine1.jpg", "racine2.jpg"]
    # Tri par NOM DE FICHIER (sort_by="name"), tous dossiers confondus.
    assert _scan(tree, tmp_path, include_dirs=(".", "été 2026")) == [
        "été 2026/e.jpg", "racine1.jpg", "racine2.jpg"]


def test_an_empty_selection_means_no_photo_at_all(tree, tmp_path):
    assert _scan(tree, tmp_path, include_dirs=()) == []
    assert _scan(tree, tmp_path, recursive=True, include_dirs=()) == []


def test_unknown_folders_match_nothing(tree, tmp_path):
    assert _scan(tree, tmp_path, include_dirs=("n-existe-pas",)) == []


def test_sequence_numbers_follow_the_selection_only(tree, tmp_path):
    config = Config(input_dir=tree, output_dir=tmp_path / "out", sort_by="name",
                    include_dirs=("Paris", "été 2026"))
    nums = [item["num"] for item in ImageScanner(config).scan()]
    assert nums == ["001", "002", "003", "004"]


@pytest.mark.parametrize("entry", ["Paris", "./Paris", "Paris/", "Paris//", "Paris/Louvre/.."])
def test_equivalent_spellings_of_a_folder_are_accepted(tree, tmp_path, entry):
    assert _scan(tree, tmp_path, include_dirs=(entry,)) == [
        "Paris/a.jpg", "Paris/b.jpg", "Paris/c.jpg"]


def test_an_absolute_path_inside_the_input_folder_is_accepted(tree, tmp_path):
    assert _scan(tree, tmp_path, include_dirs=(str(tree / "Paris"),)) == [
        "Paris/a.jpg", "Paris/b.jpg", "Paris/c.jpg"]


def test_a_folder_outside_the_input_folder_is_ignored_with_a_warning(tree, tmp_path, caplog):
    with caplog.at_level("WARNING"):
        found = _scan(tree, tmp_path, include_dirs=("../ailleurs", str(tmp_path), "Paris"))
    assert found == ["Paris/a.jpg", "Paris/b.jpg", "Paris/c.jpg"]
    assert sum("ignor" in r.message.lower() for r in caplog.records) == 2


def test_normalize_include_dir():
    root = Path("/photos")
    assert normalize_include_dir(root, ".") == "."
    assert normalize_include_dir(root, "") == "."
    assert normalize_include_dir(root, "a/b") == "a/b"
    assert normalize_include_dir(root, "/photos/a/b") == "a/b"
    assert normalize_include_dir(root, "/photos") == "."
    assert normalize_include_dir(root, "..") is None
    assert normalize_include_dir(root, "../x") is None
    assert normalize_include_dir(root, "/ailleurs") is None


# ---------------------------------------------------------------------------
# Liste des dossiers proposés
# ---------------------------------------------------------------------------

def test_list_image_folders_gives_every_folder_with_photos_and_their_count(tree):
    assert list_image_folders(tree) == [
        (".", 2), ("Paris", 3), ("Paris/Louvre", 1), ("été 2026", 1),
    ]


def test_list_image_folders_is_sorted_with_the_main_folder_first(tree):
    names = [name for name, _count in list_image_folders(tree)]
    assert names[0] == "."
    assert names[1:] == sorted(names[1:], key=str.lower)


def test_list_image_folders_skips_folders_without_photos(tree):
    assert "vide" not in [name for name, _count in list_image_folders(tree)]


def test_list_image_folders_when_only_subfolders_have_photos(tmp_path):
    root = tmp_path / "p"
    _photo(root / "x" / "1.jpg")
    assert list_image_folders(root) == [("x", 1)]


def test_list_image_folders_of_an_empty_or_missing_folder(tmp_path):
    (tmp_path / "vide").mkdir()
    assert list_image_folders(tmp_path / "vide") == []
    assert list_image_folders(tmp_path / "absent") == []


def test_list_image_folders_hides_the_output_of_a_previous_generation(tree):
    out = tree / "Portfolio"
    _photo(out / "planches" / "planche_001.jpg")
    _photo(out / "gallery" / "thumbs" / "x.jpg")
    names = [name for name, _count in list_image_folders(tree, output_dir=out)]
    assert not any(name.startswith("Portfolio") for name in names)
    # Sans cette précision le dossier de sortie serait, lui, proposé.
    assert any(name.startswith("Portfolio") for name, _count in list_image_folders(tree))


def test_every_listed_folder_selects_exactly_its_own_photos(tree, tmp_path):
    total = 0
    for name, count in list_image_folders(tree):
        found = _scan(tree, tmp_path, include_dirs=(name,))
        assert len(found) == count, name
        total += count
    assert total == len(_scan(tree, tmp_path, recursive=True))


# ---------------------------------------------------------------------------
# Ligne de commande
# ---------------------------------------------------------------------------

def _run_cli(monkeypatch, tree, out, *extra):
    monkeypatch.setattr(sys, "argv", [
        "portfolio.py", "-i", str(tree), "-o", str(out), "--csv", "--sort", "name", *map(str, extra),
    ])
    cli_module.main()
    csv_path = out / "index.csv"
    if not csv_path.exists():
        return []
    rows = csv_path.read_text(encoding="utf-8").splitlines()[1:]
    return [row.split(",", 1)[1] for row in rows]


def test_cli_include_dir_option_is_repeatable(tree, tmp_path, monkeypatch):
    names = _run_cli(monkeypatch, tree, tmp_path / "out",
                     "--include-dir", "Paris", "--include-dir", "été 2026")
    assert names == ["a.jpg", "b.jpg", "c.jpg", "e.jpg"]


def test_cli_include_dirs_file_lists_one_folder_per_line(tree, tmp_path, monkeypatch):
    listing = tmp_path / "dossiers.txt"
    listing.write_text("été 2026\n\nParis/Louvre\r\n.\n", encoding="utf-8")
    names = _run_cli(monkeypatch, tree, tmp_path / "out", "--include-dirs-file", listing)
    assert names == ["d.jpg", "e.jpg", "racine1.jpg", "racine2.jpg"]


def test_cli_include_dir_and_file_are_combined(tree, tmp_path, monkeypatch):
    listing = tmp_path / "dossiers.txt"
    listing.write_text("été 2026\n", encoding="utf-8")
    names = _run_cli(monkeypatch, tree, tmp_path / "out",
                     "--include-dir", "Paris/Louvre", "--include-dirs-file", listing)
    assert names == ["d.jpg", "e.jpg"]


def test_cli_empty_include_dirs_file_selects_nothing(tree, tmp_path, monkeypatch):
    listing = tmp_path / "vide.txt"
    listing.write_text("", encoding="utf-8")
    assert _run_cli(monkeypatch, tree, tmp_path / "out", "--include-dirs-file", listing) == []


def test_cli_without_the_options_still_processes_everything_requested(tree, tmp_path, monkeypatch):
    assert _run_cli(monkeypatch, tree, tmp_path / "a") == ["racine1.jpg", "racine2.jpg"]
    assert len(_run_cli(monkeypatch, tree, tmp_path / "b", "-r")) == 7


def test_cli_unreadable_include_dirs_file_stops_with_a_clear_error(tree, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "portfolio.py", "-i", str(tree), "-o", str(tmp_path / "out"),
        "--include-dirs-file", str(tmp_path / "absent.txt"),
    ])
    with pytest.raises(SystemExit) as exc:
        cli_module.main()
    assert exc.value.code == 2
    assert "absent.txt" in capsys.readouterr().err


def test_cli_utf8_bom_in_the_include_dirs_file_is_tolerated(tree, tmp_path, monkeypatch):
    listing = tmp_path / "bom.txt"
    listing.write_bytes("﻿Paris\n".encode("utf-8"))
    names = _run_cli(monkeypatch, tree, tmp_path / "out", "--include-dirs-file", listing)
    assert names == ["a.jpg", "b.jpg", "c.jpg"]


def test_cli_preview_honours_the_selection(tree, tmp_path, monkeypatch):
    png = tmp_path / "apercu.png"
    monkeypatch.setattr(sys, "argv", [
        "portfolio.py", "-i", str(tree), "--preview-output", str(png), "--include-dir", "Paris",
    ])
    cli_module.main()
    assert png.exists()

    nothing = tmp_path / "rien.png"
    monkeypatch.setattr(sys, "argv", [
        "portfolio.py", "-i", str(tree), "--preview-output", str(nothing),
        "--include-dir", "n-existe-pas",
    ])
    cli_module.main()
    assert not nothing.exists(), "aucune photo retenue : aucune planche d'aperçu"
