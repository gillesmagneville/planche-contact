# -*- coding: utf-8 -*-
"""
Nautilus extension (nautilus-extension/planche_contact_nautilus.py).

It is loaded by Nautilus' own Python, with the Nautilus bindings: here a
stand-in for `gi` is installed so that the file can be imported and driven on
any machine, with or without nautilus-python. What is checked is what the
extension decides itself - which selections get the entry, the list file it
writes, how it starts the application - and that the few values it has to
share with the application (supported formats, name of the temporary list
file) have not drifted apart.
"""
import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

from portfolio.launch import SELECTION_FILE_PREFIX, read_paths_file
from portfolio.scanner import ImageScanner

REPO = Path(__file__).resolve().parent.parent
EXTENSION_PATH = REPO / "nautilus-extension" / "planche_contact_nautilus.py"


class _FakeMenuItem:
    def __init__(self, name, label, tip):
        self.name, self.label, self.tip = name, label, tip
        self.handlers = {}

    def connect(self, signal, callback):
        self.handlers[signal] = callback


@pytest.fixture
def extension(monkeypatch):
    """The extension module, imported against a fake `gi`."""
    gi = types.ModuleType("gi")
    gi.require_version = lambda *args, **kwargs: None
    repository = types.ModuleType("gi.repository")
    repository.GObject = types.SimpleNamespace(GObject=type("GObject", (), {}))
    repository.Nautilus = types.SimpleNamespace(
        MenuProvider=type("MenuProvider", (), {}), MenuItem=_FakeMenuItem
    )
    gi.repository = repository
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)

    spec = importlib.util.spec_from_file_location("planche_contact_nautilus", EXTENSION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeFile:
    def __init__(self, path, directory=False):
        self._path, self._directory = path, directory

    def get_location(self):
        if self._path is None:
            return None
        return types.SimpleNamespace(get_path=lambda: self._path)

    def is_directory(self):
        return self._directory


# ====================== values shared with the application ======================


def test_supported_formats_match_the_scanner(extension):
    assert set(extension.SUPPORTED_EXTENSIONS) == set(ImageScanner.SUPPORTED_EXTENSIONS)


def test_temporary_file_prefix_matches_the_application(extension):
    assert extension.SELECTION_FILE_PREFIX == SELECTION_FILE_PREFIX


# ====================== which selections get the entry ======================


def test_folders_and_photos_are_kept(extension):
    files = [
        _FakeFile("/photos/Paris", directory=True),
        _FakeFile("/photos/a.JPG"),
        _FakeFile("/photos/b.CR3"),
    ]
    assert extension.relevant_paths(files) == ["/photos/Paris", "/photos/a.JPG", "/photos/b.CR3"]


def test_other_files_and_remote_locations_are_left_out(extension):
    files = [_FakeFile("/photos/notes.txt"), _FakeFile("/photos/doc.pdf"), _FakeFile(None)]
    assert extension.relevant_paths(files) == []


def test_no_entry_when_nothing_is_relevant(extension):
    assert extension.PlancheContactMenuProvider().get_file_items([_FakeFile("/x/notes.txt")]) == []


def test_one_entry_for_a_relevant_selection(extension):
    items = extension.PlancheContactMenuProvider().get_file_items(
        [_FakeFile("/x/a.jpg"), _FakeFile("/x/notes.txt")]
    )
    assert len(items) == 1
    assert items[0].name == "PlancheContact::Open"


def test_entry_on_the_background_of_a_folder(extension):
    provider = extension.PlancheContactMenuProvider()
    assert len(provider.get_background_items(_FakeFile("/photos/Paris", directory=True))) == 1
    assert provider.get_background_items(_FakeFile(None)) == []


# ====================== language ======================


@pytest.mark.parametrize("environ, expected", [
    ({"LANG": "fr_FR.UTF-8"}, "fr"),
    ({"LANG": "de_DE.UTF-8"}, "de"),
    ({"LANG": "es_ES.UTF-8"}, "es"),
    ({"LANG": "en_US.UTF-8"}, "en"),
    ({"LANG": "it_IT.UTF-8"}, "en"),
    ({"LANG": "fr_FR.UTF-8", "LANGUAGE": "de:fr"}, "de"),       # LANGUAGE wins, first available
    ({"LANGUAGE": "it:es", "LANG": "fr_FR.UTF-8"}, "es"),       # skips an unavailable language
    ({"LC_ALL": "C", "LANG": "fr_FR.UTF-8"}, "en"),             # "C" stops the search
    ({"LC_ALL": "fr_CA.UTF-8", "LANG": "de_DE.UTF-8"}, "fr"),   # LC_ALL before LANG
    ({"LANG": "fr@euro"}, "fr"),
    ({}, "en"),
])
def test_language_of_the_entry(extension, environ, expected):
    assert extension.pick_language(environ) == expected


def test_every_language_has_a_label_and_a_tip(extension):
    for code in ("en", "fr", "de", "es"):
        label, tip = extension._TEXTS[code]
        assert "Planche-Contact" in label and tip


# ====================== starting the application ======================


def test_the_list_file_is_written_and_the_application_started(extension, monkeypatch, tmp_path):
    monkeypatch.setattr(extension.tempfile, "tempdir", str(tmp_path))
    started = []
    monkeypatch.setattr(extension.subprocess, "Popen", lambda cmd, **kwargs: started.append((cmd, kwargs)))

    paths = ["/photos/été 2026/a.jpg", "/photos/Paris"]
    extension._launch_gui(paths)

    assert len(started) == 1
    command, kwargs = started[0]
    assert command[0] == extension.GUI_BINARY
    assert command[1] == "--paths-from"
    assert kwargs["start_new_session"] is True
    # The application reads the list (and deletes it, being named like that).
    list_file = Path(command[2])
    assert list_file.name.startswith(SELECTION_FILE_PREFIX)
    assert read_paths_file(list_file) == paths
    assert not list_file.exists()


def test_the_list_file_is_removed_if_the_application_cannot_start(extension, monkeypatch, tmp_path):
    monkeypatch.setattr(extension.tempfile, "tempdir", str(tmp_path))

    def failing(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(extension.subprocess, "Popen", failing)
    extension._launch_gui(["/photos/a.jpg"])
    assert list(tmp_path.iterdir()) == []


def test_nothing_is_started_for_an_empty_selection(extension, monkeypatch):
    started = []
    monkeypatch.setattr(extension.subprocess, "Popen", lambda *a, **k: started.append(a))
    extension._launch_gui([])
    assert started == []
    assert os.path.isfile(EXTENSION_PATH)
