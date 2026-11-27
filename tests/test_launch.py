# -*- coding: utf-8 -*-
"""
Opening Planche-Contact from a context menu (Nautilus, Windows Explorer) on a
folder or on a selection of photos.

- portfolio.launch: the paths received (command line, --paths-from list file)
  become an input folder, and possibly the exact list of photos to keep;
- Config.only_files / ImageScanner: only those photos are processed;
- command line: --files-from.
"""
import sys
from pathlib import Path

import pytest
from PIL import Image

import portfolio.portfolio as cli_module
from portfolio.config import Config
from portfolio.launch import (
    SELECTION_FILE_PREFIX,
    paths_from_arguments,
    read_paths_file,
    resolve_selection,
)
from portfolio.scanner import ImageScanner


def _photo(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 48), (120, 120, 120)).save(path, quality=80)


@pytest.fixture
def tree(tmp_path):
    """
    photos/
      a.jpg  b.jpg  c.PNG  notes.txt
      Paris/        d.jpg e.jpg
      été 2026/     f.jpg
      vide/         readme.txt
    """
    root = tmp_path / "photos"
    for rel in ("a.jpg", "b.jpg", "c.PNG", "Paris/d.jpg", "Paris/e.jpg", "été 2026/f.jpg"):
        _photo(root / rel)
    (root / "notes.txt").write_text("not a photo")
    (root / "vide").mkdir()
    (root / "vide" / "readme.txt").write_text("not a photo")
    return root


# ====================== resolve_selection ======================


def test_a_single_folder_is_opened_as_the_whole_folder(tree):
    selection = resolve_selection([str(tree / "Paris")])
    assert selection.input_dir == tree / "Paris"
    assert selection.files is None


def test_photos_of_one_folder_make_that_folder_the_input(tree):
    selection = resolve_selection([str(tree / "b.jpg"), str(tree / "a.jpg")])
    assert selection.input_dir == tree
    assert selection.files == ("b.jpg", "a.jpg")
    assert selection.count == 2


def test_photos_of_several_folders_use_their_common_parent(tree):
    selection = resolve_selection([str(tree / "a.jpg"), str(tree / "Paris" / "d.jpg")])
    assert selection.input_dir == tree
    assert selection.files == ("a.jpg", "Paris/d.jpg")


def test_several_folders_give_the_photos_directly_inside_each(tree):
    selection = resolve_selection([str(tree / "Paris"), str(tree / "été 2026")])
    assert selection.input_dir == tree
    assert sorted(selection.files) == ["Paris/d.jpg", "Paris/e.jpg", "été 2026/f.jpg"]


def test_a_folder_mixed_with_photos(tree):
    selection = resolve_selection([str(tree / "Paris"), str(tree / "a.jpg")])
    assert selection.input_dir == tree
    assert sorted(selection.files) == ["Paris/d.jpg", "Paris/e.jpg", "a.jpg"]


def test_duplicates_are_removed(tree):
    selection = resolve_selection([str(tree / "a.jpg"), str(tree / "a.jpg"), str(tree / "b.jpg")])
    assert selection.files == ("a.jpg", "b.jpg")


def test_unsupported_and_missing_paths_are_ignored(tree):
    selection = resolve_selection([
        str(tree / "notes.txt"), str(tree / "absent.jpg"), str(tree / "c.PNG"),
    ])
    assert selection.files == ("c.PNG",)


@pytest.mark.parametrize("which", ["nothing", "only_unsupported", "empty_folders"])
def test_nothing_usable_gives_none(tree, which):
    if which == "nothing":
        paths = []
    elif which == "only_unsupported":
        paths = [str(tree / "notes.txt")]
    else:
        # two folders without any photo directly inside: nothing to process
        (tree / "vide2").mkdir()
        paths = [str(tree / "vide"), str(tree / "vide2")]
    assert resolve_selection(paths) is None


def test_accented_folder_names(tree):
    selection = resolve_selection([str(tree / "été 2026" / "f.jpg")])
    assert selection.input_dir == tree / "été 2026"
    assert selection.files == ("f.jpg",)


# ====================== command line and list file ======================


def test_read_paths_file_handles_bom_crlf_and_blank_lines(tmp_path):
    listing = tmp_path / "list.txt"
    listing.write_bytes("﻿/photos/a.jpg\r\n\r\n/photos/été/b.jpg\r\n".encode("utf-8"))
    assert read_paths_file(listing) == ["/photos/a.jpg", "/photos/été/b.jpg"]
    assert listing.exists(), "a list file written by the user must never be deleted"


def test_read_paths_file_deletes_the_temporary_file_of_a_context_menu(tmp_path):
    listing = tmp_path / f"{SELECTION_FILE_PREFIX}abc123.txt"
    listing.write_text("/photos/a.jpg\n", encoding="utf-8")
    assert read_paths_file(listing) == ["/photos/a.jpg"]
    assert not listing.exists()


def test_read_paths_file_unreadable_gives_an_empty_list(tmp_path):
    assert read_paths_file(tmp_path / "missing.txt") == []


def test_a_name_starting_or_ending_with_a_space_is_kept(tmp_path):
    listing = tmp_path / "list.txt"
    listing.write_text("/photos/ a.jpg\n/photos/b.jpg \n", encoding="utf-8")
    assert read_paths_file(listing) == ["/photos/ a.jpg", "/photos/b.jpg "]


def test_paths_from_arguments_mixes_option_and_direct_paths(tmp_path):
    listing = tmp_path / "list.txt"
    listing.write_text("/x/a.jpg\n/x/b.jpg\n", encoding="utf-8")
    args = ["--paths-from", str(listing), "/x/c.jpg", "--unknown-option", "/x/d.jpg"]
    assert paths_from_arguments(args) == ["/x/a.jpg", "/x/b.jpg", "/x/c.jpg", "/x/d.jpg"]


def test_paths_from_arguments_equals_form_and_double_dash(tmp_path):
    listing = tmp_path / "list.txt"
    listing.write_text("/x/a.jpg\n", encoding="utf-8")
    assert paths_from_arguments([f"--paths-from={listing}", "--", "-odd-name.jpg"]) == [
        "/x/a.jpg", "-odd-name.jpg",
    ]


def test_relative_paths_are_taken_from_the_working_folder_of_the_launcher():
    assert paths_from_arguments(["photos/a.jpg", "/abs/b.jpg"], cwd="/home/me") == [
        "/home/me/photos/a.jpg", "/abs/b.jpg",
    ]


def test_no_arguments_gives_no_paths():
    assert paths_from_arguments([]) == []


# ====================== scanner: Config.only_files ======================


def _scan(root, tmp_path, **kwargs):
    config = Config(input_dir=root, output_dir=tmp_path / "out", sort_by="name", **kwargs)
    return [item["path"].relative_to(root).as_posix() for item in ImageScanner(config).scan()]


def test_without_only_files_everything_is_scanned(tree, tmp_path):
    assert _scan(tree, tmp_path) == ["a.jpg", "b.jpg", "c.PNG"]


def test_only_files_keeps_exactly_those_photos(tree, tmp_path):
    assert sorted(_scan(tree, tmp_path, only_files=("b.jpg", "Paris/e.jpg"))) == ["Paris/e.jpg", "b.jpg"]


def test_only_files_does_not_walk_the_folder_even_when_recursive(tree, tmp_path):
    assert sorted(_scan(tree, tmp_path, only_files=("a.jpg",), recursive=True)) == ["a.jpg"]


def test_only_files_empty_means_no_photo(tree, tmp_path):
    assert _scan(tree, tmp_path, only_files=()) == []


def test_only_files_ignores_missing_unsupported_and_outside_entries(tree, tmp_path):
    outside = tmp_path / "elsewhere.jpg"
    _photo(outside)
    entries = ("a.jpg", "absent.jpg", "notes.txt", "../elsewhere.jpg", str(outside), "a.jpg")
    assert _scan(tree, tmp_path, only_files=entries) == ["a.jpg"]


def test_only_files_accepts_absolute_paths_inside_the_input_folder(tree, tmp_path):
    assert _scan(tree, tmp_path, only_files=(str(tree / "Paris" / "d.jpg"),)) == ["Paris/d.jpg"]


def test_a_selection_resolved_from_paths_scans_to_the_same_photos(tree, tmp_path):
    selection = resolve_selection([str(tree / "Paris"), str(tree / "c.PNG")])
    assert sorted(_scan(selection.input_dir, tmp_path, only_files=selection.files)) == [
        "Paris/d.jpg", "Paris/e.jpg", "c.PNG",
    ]


# ====================== command line: --files-from ======================


def _run_cli(monkeypatch, *extra):
    monkeypatch.setattr(sys, "argv", ["portfolio", *extra])
    cli_module.main()


def test_cli_files_from_processes_only_the_listed_photos(tree, tmp_path, monkeypatch):
    listing = tmp_path / "files.txt"
    listing.write_text("b.jpg\nParis/d.jpg\n", encoding="utf-8")
    out = tmp_path / "out"
    _run_cli(monkeypatch, "-i", str(tree), "-o", str(out), "--files-from", str(listing),
             "--csv", "--sort", "name", "--language", "en")
    rows = (out / "index.csv").read_text(encoding="utf-8-sig")
    assert "b.jpg" in rows and "d.jpg" in rows
    assert "a.jpg" not in rows and "e.jpg" not in rows and "c.PNG" not in rows


def test_cli_files_from_empty_file_means_no_photo(tree, tmp_path, monkeypatch):
    listing = tmp_path / "files.txt"
    listing.write_text("", encoding="utf-8")
    out = tmp_path / "out"
    _run_cli(monkeypatch, "-i", str(tree), "-o", str(out), "--files-from", str(listing),
             "--csv", "--language", "en")
    assert not (out / "planches").exists() or not any((out / "planches").iterdir())


def test_cli_files_from_unreadable_list_exits_with_an_error(tree, tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit) as excinfo:
        _run_cli(monkeypatch, "-i", str(tree), "-o", str(tmp_path / "out"),
                 "--files-from", str(tmp_path / "missing.txt"), "--language", "en")
    assert excinfo.value.code == 2
    assert "missing.txt" in capsys.readouterr().err
