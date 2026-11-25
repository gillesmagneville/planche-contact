"""
Nautilus extension for Planche-Contact.

Adds an "Open in Planche-Contact" entry to the Nautilus context menu: on a
selection of photos and/or folders, or on the background of a folder. The
extension only collects the selected paths and starts the graphical interface
(planche-contact-gtk), which shows them in its form: the photos are analysed
and the sheets generated in that separate process, so as never to block or
crash Nautilus.

Same mechanism as nautilus-convert-images. Installation: this file must be
located under /usr/share/nautilus-python/extensions/ (and not ~/.local/... nor
/usr/local/..., to stay visible from Nautilus' sandbox). The "python3-nautilus"
package (nautilus-python) provides the host.
"""

import os
import subprocess
import tempfile

import gi

# Deliberately NO gi.require_version("Nautilus", ...): by the time this file
# runs, the host Nautilus process has already loaded the Nautilus typelib
# matching its own version (4.0, 4.1, ...). Pinning a precise version here
# fails depending on the machine: either it does not match the one already
# loaded by Nautilus itself ("already loaded with version X"), or it is
# simply not installed on this system. GObject, on the other hand, has only
# one possible introspection version (2.0): pinning it poses no risk of
# conflict.
gi.require_version("GObject", "2.0")

from gi.repository import GObject, Nautilus  # noqa: E402

GUI_BINARY = "/usr/bin/planche-contact-gtk"

#: Start of the name of the temporary list file. portfolio/launch.py
#: (SELECTION_FILE_PREFIX) deletes any file with this name once it has read it:
#: the two values must stay identical (tests/test_nautilus_extension.py checks
#: it).
SELECTION_FILE_PREFIX = "planche-contact-selection-"

#: Photo formats Planche-Contact processes: the entry is offered only if the
#: selection holds at least one folder or one of these files. A copy of
#: portfolio/scanner.py (ImageScanner.SUPPORTED_EXTENSIONS) - this file is
#: loaded by Nautilus' own Python, which cannot import the application's
#: modules; tests/test_nautilus_extension.py checks that both stay identical.
SUPPORTED_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp",
    ".heic", ".heif", ".cr2", ".cr3", ".nef", ".dng", ".arw",
})

# Texts of the entry, in the four languages of the application. The language
# is chosen like gettext (and like the postinst of the package) does: the
# first non-empty variable among LANGUAGE, LC_ALL, LC_MESSAGES and LANG, which
# may hold several languages separated by ":"; English when none matches.
_TEXTS = {
    "en": (
        "Open in Planche-Contact",
        "Open the selection (folder or photos) in Planche-Contact to make contact sheets",
    ),
    "fr": (
        "Ouvrir dans Planche-Contact",
        "Ouvrir la sélection (dossier ou photos) dans Planche-Contact pour en faire des planches contact",
    ),
    "de": (
        "In Planche-Contact öffnen",
        "Die Auswahl (Ordner oder Fotos) in Planche-Contact öffnen, um Kontaktbögen zu erstellen",
    ),
    "es": (
        "Abrir en Planche-Contact",
        "Abrir la selección (carpeta o fotos) en Planche-Contact para crear hojas de contacto",
    ),
}


def pick_language(environ=None):
    """"fr", "en", "de" or "es" according to the session's language."""
    environ = os.environ if environ is None else environ
    value = ""
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        if environ.get(variable):
            value = environ[variable]
            break
    for entry in value.split(":"):
        if entry in ("C", "POSIX") or entry.startswith(("C.", "POSIX.")):
            break
        code = entry.replace("@", "_").replace(".", "_").split("_")[0].lower()
        if code in _TEXTS:
            return code
    return "en"


def _is_photo_name(name):
    return os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS


def _local_path(file_info):
    """Local path of a Nautilus.FileInfo, or None if it is not a local file
    (e.g. a remote location that is not mounted)."""
    location = file_info.get_location()
    if location is None:
        return None
    return location.get_path()


def relevant_paths(files):
    """Paths, among the selected items, that Planche-Contact can open: the
    local folders and the photos of a supported format."""
    paths = []
    for file_info in files:
        path = _local_path(file_info)
        if not path:
            continue
        if file_info.is_directory() or _is_photo_name(path):
            paths.append(path)
    return paths


def _write_path_list(paths):
    """Writes the paths to a temporary file (one per line, UTF-8) to avoid any
    command-line length limit with a very large selection. The application
    deletes the file once read (see SELECTION_FILE_PREFIX)."""
    fd, name = tempfile.mkstemp(prefix=SELECTION_FILE_PREFIX, suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        for path in paths:
            handle.write(path + "\n")
    return name


def _launch_gui(paths):
    if not paths:
        return
    list_file = _write_path_list(paths)
    try:
        subprocess.Popen(
            [GUI_BINARY, "--paths-from", list_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        # The program could not be started: nobody will read (and delete) the
        # list.
        try:
            os.remove(list_file)
        except OSError:
            pass


class PlancheContactMenuProvider(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        super().__init__()

    def _make_item(self, paths):
        label, tip = _TEXTS[pick_language()]
        item = Nautilus.MenuItem(
            name="PlancheContact::Open",
            label=label,
            tip=tip,
        )
        item.connect("activate", lambda _item: _launch_gui(paths))
        return item

    def get_file_items(self, files):
        # `files`: selection of files and/or folders.
        paths = relevant_paths(files)
        if not paths:
            return []
        return [self._make_item(paths)]

    def get_background_items(self, current_folder):
        # Right click on the background of a folder (nothing selected): opens
        # the current folder.
        path = _local_path(current_folder)
        if not path:
            return []
        return [self._make_item([path])]
