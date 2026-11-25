# -*- coding: utf-8 -*-
"""
Opening Planche-Contact from a context menu (right click in Nautilus or in
the Windows Explorer) on a folder or on a selection of photos.

The menu entry only passes the selected paths to the graphical interface,
either on the command line or - to stay clear of the maximum command-line
length (about 32,000 characters on Windows) when many photos are selected -
in a UTF-8 text file, one path per line, given with ``--paths-from FILE``.
This module turns those paths into what the rest of the program understands:

- ONE folder alone      -> that folder is the input folder, all its photos
                           are processed (the "recursive search" option stays
                           the user's choice);
- photos, or several    -> the common parent folder is the input folder and
  folders, or a mix        ``Config.only_files`` lists exactly the photos to
                           keep (the photos located DIRECTLY in each selected
                           folder, plus the selected photos).

Pure Python, no GTK: it is tested without a graphical session
(tests/test_launch.py).
"""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .scanner import ImageScanner

#: Start of the name of the temporary files written by the context menus
#: (``planche-contact-selection-XXXX.txt``). The application deletes such a
#: file once it has read it: nobody else would, and it would pile up in the
#: temporary folder. A list file with any other name (written by the user) is
#: never deleted.
SELECTION_FILE_PREFIX = "planche-contact-selection-"


@dataclass(frozen=True)
class LaunchSelection:
    """What a context menu asks to open.

    `input_dir`: the input folder (absolute path).
    `files`: None = the whole folder; otherwise the photos to keep, as POSIX
    paths relative to `input_dir` (the form expected by
    ``Config.only_files``)."""

    input_dir: Path
    files: Optional[tuple] = None

    @property
    def count(self) -> int:
        return len(self.files) if self.files is not None else 0


def _is_selection_temp_file(path: Path) -> bool:
    return path.name.startswith(SELECTION_FILE_PREFIX) and path.suffix.lower() == ".txt"


def read_paths_file(path) -> list:
    """Paths listed in `path` (UTF-8, with or without a byte order mark, one
    per line, blank lines ignored). An unreadable file gives an empty list.

    A file written by a context menu (see SELECTION_FILE_PREFIX) is deleted
    once read."""
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []
    finally:
        if _is_selection_temp_file(file_path):
            try:
                file_path.unlink()
            except OSError:
                pass
    # splitlines() removes the line ends ("\n" on Linux, "\r\n" on Windows)
    # but leaves any other character alone: a file name may legitimately
    # start or end with a space.
    return [line for line in text.splitlines() if line.strip()]


def paths_from_arguments(args: Iterable[str], cwd: Optional[str] = None) -> list:
    """Paths designated by the command line of the graphical interface
    (without the program name): ``--paths-from FILE`` (or
    ``--paths-from=FILE``) and/or paths given directly. ``--`` ends the
    options. Any other option is ignored. A relative path is taken from `cwd`
    - the working folder of the process that was launched, which differs from
    ours when a second launch is forwarded to an already running instance."""
    collected = []
    pending_file_option = False
    options_ended = False
    for arg in args:
        if pending_file_option:
            collected.extend(read_paths_file(arg))
            pending_file_option = False
        elif options_ended or not arg.startswith("-"):
            collected.append(arg)
        elif arg == "--":
            options_ended = True
        elif arg == "--paths-from":
            pending_file_option = True
        elif arg.startswith("--paths-from="):
            collected.extend(read_paths_file(arg.split("=", 1)[1]))
        # any other option: ignored

    if cwd:
        collected = [p if os.path.isabs(p) else os.path.join(cwd, p) for p in collected]
    return collected


def _is_photo(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in ImageScanner.SUPPORTED_EXTENSIONS


def _photos_directly_in(folder: Path) -> list:
    try:
        return sorted(
            (child for child in folder.iterdir() if _is_photo(child)),
            key=lambda p: p.name.lower(),
        )
    except OSError:
        return []


def resolve_selection(paths: Iterable[str]) -> Optional[LaunchSelection]:
    """The selection to open for these paths, or None when none of them is
    a folder or a supported photo (a missing path, a PDF... are ignored)."""
    folders = []
    photos = []
    for raw in paths:
        path = Path(os.path.abspath(raw))
        if path.is_dir():
            folders.append(path)
        elif _is_photo(path):
            photos.append(path)

    if not folders and not photos:
        return None

    # One folder alone: the folder itself is opened, as if it had been chosen
    # with the "Choose..." button.
    if len(folders) == 1 and not photos:
        return LaunchSelection(input_dir=folders[0], files=None)

    # Otherwise: an explicit list of photos. The photos of a selected folder
    # are those located directly in it (like the default behaviour of a
    # folder opened alone, without the recursive search).
    for folder in folders:
        photos.extend(_photos_directly_in(folder))
    photos = list(dict.fromkeys(photos))  # no duplicates, order kept
    if not photos:
        return None

    # A selection normally lies on a single drive (Explorer cannot select
    # across drives, nor can Nautilus across mount points): if it ever did,
    # only the drive of the first photo is kept, as os.path.commonpath()
    # cannot compare paths of different drives.
    drive = os.path.splitdrive(str(photos[0]))[0].lower()
    photos = [p for p in photos if os.path.splitdrive(str(p))[0].lower() == drive]

    common = Path(os.path.commonpath([str(p.parent) for p in photos]))
    relative = tuple(p.relative_to(common).as_posix() for p in photos)
    return LaunchSelection(input_dir=common, files=relative)
