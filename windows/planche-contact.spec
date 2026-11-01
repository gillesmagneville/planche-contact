# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller .spec file for Planche-Contact (Windows).

This file is read by build-windows.ps1 (through `pyinstaller planche-contact.spec`),
which first sets three environment variables:
  - PLANCHE_WORK_DIR: folder containing planche-contact-gtk.py, portfolio/,
    VERSION, docs/, LICENSE, and the README, CHANGELOG and CODE_OF_CONDUCT in two
    languages (working copy prepared by the PowerShell script)
  - PLANCHE_GTK_DIR: folder of the gvsbuild GTK4 stack (C:\\gtk by default),
    of which bin/, lib/girepository-1.0/ and share/ are bundled
  - PLANCHE_ICON: path to the application's .ico icon

Deliberately simple approach for this first port: the whole of bin/,
lib/girepository-1.0/ and share/ of the gvsbuild stack is bundled, rather
than finely sorting which files are strictly necessary. The resulting
package is therefore bigger than the strict minimum, but much more robust
- avoiding "a DLL is missing" matters far more than saving a few tens of
MB.
"""

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

work_dir = Path(os.environ.get("PLANCHE_WORK_DIR", "."))
gtk_dir = Path(os.environ.get("PLANCHE_GTK_DIR", r"C:\gtk"))
icon_file = os.environ.get("PLANCHE_ICON", None)


def collect_tree(src_dir: Path, dest_prefix: str):
    """Walks src_dir and returns a list of (source, dest) tuples in the
    format expected by Analysis(binaries=..., datas=...): one pair per
    file, dest being the subfolder (relative to the root of the frozen
    package) in which that file must end up."""
    items = []
    if not src_dir.is_dir():
        print(f"[planche-contact.spec] WARNING: folder missing, ignored: {src_dir}")
        return items
    for root, _dirs, files in os.walk(src_dir):
        for filename in files:
            full_path = Path(root) / filename
            rel_dir = full_path.parent.relative_to(src_dir)
            dest = str(Path(dest_prefix) / rel_dir) if str(rel_dir) != "." else dest_prefix
            items.append((str(full_path), dest))
    return items


# --- GTK4 binaries (DLLs): at the root of the package, so that the Windows
# DLL loader finds them next to the executable. ----------------------------
gtk_binaries = collect_tree(gtk_dir / "bin", ".")

# --- GObject-Introspection typelibs: needed by `from gi.repository
# import Gtk` etc. at runtime. Placed in a dedicated subfolder, whose
# path is given to PyGObject through the GI_TYPELIB_PATH variable (see the
# startup block added in planche-contact-gtk.py). --------------------------
gtk_typelibs = collect_tree(gtk_dir / "lib" / "girepository-1.0", "gi_typelibs")

# --- GTK shared data (Adwaita/hicolor icons, compiled GSettings schemas,
# themes...) -------------------------------------------------------------
gtk_share = collect_tree(gtk_dir / "share", "share")

datas = [
    (str(work_dir / "portfolio"), "portfolio"),
    (str(work_dir / "VERSION"), "."),
]
if (work_dir / "docs").is_dir():
    datas.append((str(work_dir / "docs"), "docs"))
if (work_dir / "LICENSE").is_file():
    datas.append((str(work_dir / "LICENSE"), "."))
# The project documentation, in both languages (English by default, French
# in .fr.md), next to the executable. The code of conduct is under CC-BY-SA-4.0.
for doc_name in ("README.md", "README.fr.md", "CHANGELOG.md", "CHANGELOG.fr.md", "CODE_OF_CONDUCT.md", "CODE_OF_CONDUCT.fr.md"):
    if (work_dir / doc_name).is_file():
        datas.append((str(work_dir / doc_name), "."))

datas += gtk_share
datas += gtk_typelibs

binaries = gtk_binaries

a = Analysis(
    [str(work_dir / "planche-contact-gtk.py")],
    pathex=[str(work_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "gi",
        "gi.repository.Gtk",
        "gi.repository.Gdk",
        "gi.repository.GdkPixbuf",
        "gi.repository.Gio",
        "gi.repository.GLib",
        "gi.repository.GObject",
        "gi.repository.Pango",
        "gi.repository.cairo",
        "rawpy",
        "exifread",
        "reportlab",
    ] + collect_submodules("gi.overrides"),
    # The "gi.overrides.*" modules (GLib.py, Gtk.py, Gdk.py...) provide
    # the usual Pythonic signatures (default arguments,
    # callback simplification...) on top of the raw bindings coming from
    # GObject introspection. PyGObject loads them dynamically at
    # runtime (never through an explicit "import" visible in the code), so
    # PyInstaller's static analysis cannot detect them on its own:
    # without this line, they are missing from the frozen package, and the code
    # then falls back on the stricter raw C signatures (observed:
    # GLib.idle_add demanding a numeric priority as first argument,
    # Gtk.TextBuffer.insert() demanding an explicit length...).
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="planche-contact-gtk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon_file if icon_file and os.path.isfile(icon_file) else None,
    # Disables the "_internal" subfolder (PyInstaller 6+ default behavior):
    # the GTK4 DLLs/typelibs end up directly next to the executable, where
    # the Windows startup block of planche-contact-gtk.py looks for them.
    # (See also the `datas` list above.)
    contents_directory=".",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="planche-contact",
)
