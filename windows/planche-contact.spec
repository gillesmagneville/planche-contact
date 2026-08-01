# -*- mode: python ; coding: utf-8 -*-
"""
Fichier .spec PyInstaller pour Planche-Contact (Windows).

Ce fichier est lu par build-windows.ps1 (via `pyinstaller planche-contact.spec`),
qui positionne au préalable trois variables d'environnement :
  - PLANCHE_WORK_DIR : dossier contenant planche-contact-gtk.py, portfolio/,
    VERSION, docs/, LICENSE (copie de travail préparée par le script PowerShell)
  - PLANCHE_GTK_DIR  : dossier de la pile GTK4 gvsbuild (C:\\gtk par défaut),
    dont on embarque bin/, lib/girepository-1.0/ et share/
  - PLANCHE_ICON     : chemin vers l'icône .ico de l'application

Approche volontairement simple pour ce premier portage : on embarque
l'intégralité de bin/, lib/girepository-1.0/ et share/ de la pile gvsbuild,
plutôt que de trier finement quels fichiers sont strictement nécessaires.
Le paquet obtenu est donc plus volumineux que le strict minimum, mais
beaucoup plus robuste - éviter les "il manque une DLL" est bien plus
important qu'économiser quelques dizaines de Mo.
"""

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

work_dir = Path(os.environ.get("PLANCHE_WORK_DIR", "."))
gtk_dir = Path(os.environ.get("PLANCHE_GTK_DIR", r"C:\gtk"))
icon_file = os.environ.get("PLANCHE_ICON", None)


def collect_tree(src_dir: Path, dest_prefix: str):
    """Parcourt src_dir et retourne une liste de tuples (source, dest) au
    format attendu par Analysis(binaries=..., datas=...) : un couple par
    fichier, dest étant le sous-dossier (relatif à la racine du paquet
    gelé) dans lequel ce fichier doit atterrir."""
    items = []
    if not src_dir.is_dir():
        print(f"[planche-contact.spec] ATTENTION : dossier absent, ignoré : {src_dir}")
        return items
    for root, _dirs, files in os.walk(src_dir):
        for filename in files:
            full_path = Path(root) / filename
            rel_dir = full_path.parent.relative_to(src_dir)
            dest = str(Path(dest_prefix) / rel_dir) if str(rel_dir) != "." else dest_prefix
            items.append((str(full_path), dest))
    return items


# --- Binaires GTK4 (DLL) : à la racine du paquet, pour que le chargeur de
# DLL de Windows les trouve à côté de l'exécutable. ------------------------
gtk_binaries = collect_tree(gtk_dir / "bin", ".")

# --- Typelibs GObject-Introspection : nécessaires à `from gi.repository
# import Gtk` etc. au runtime. Placés dans un sous-dossier dédié, dont le
# chemin est indiqué à PyGObject via la variable GI_TYPELIB_PATH (voir le
# bloc de démarrage ajouté dans planche-contact-gtk.py). --------------------
gtk_typelibs = collect_tree(gtk_dir / "lib" / "girepository-1.0", "gi_typelibs")

# --- Données partagées GTK (icônes Adwaita/hicolor, schémas GSettings
# compilés, thèmes...) -------------------------------------------------------
gtk_share = collect_tree(gtk_dir / "share", "share")

datas = [
    (str(work_dir / "portfolio"), "portfolio"),
    (str(work_dir / "VERSION"), "."),
]
if (work_dir / "docs").is_dir():
    datas.append((str(work_dir / "docs"), "docs"))
if (work_dir / "LICENSE").is_file():
    datas.append((str(work_dir / "LICENSE"), "."))

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
    # Les modules "gi.overrides.*" (GLib.py, Gtk.py, Gdk.py...) fournissent
    # les signatures pythoniques habituelles (arguments par defaut,
    # simplification des callbacks...) par-dessus les liaisons brutes issues
    # de l'introspection GObject. PyGObject les charge dynamiquement au
    # runtime (jamais via un "import" explicite visible dans le code), donc
    # l'analyse statique de PyInstaller ne peut pas les detecter toute
    # seule : sans cette ligne, ils sont absents du paquet gele, et le code
    # retombe alors sur les signatures C brutes, plus strictes (observe :
    # GLib.idle_add exigeant une priorite numerique en premier argument,
    # Gtk.TextBuffer.insert() exigeant une longueur explicite...).
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
    console=True,  # DIAGNOSTIC TEMPORAIRE : remettre a False une fois le probleme resolu
    icon=icon_file if icon_file and os.path.isfile(icon_file) else None,
    # Désactive le sous-dossier "_internal" (comportement par défaut de
    # PyInstaller 6+) : les DLL/typelibs GTK4 se retrouvent directement à
    # côté de l'exécutable, là où le bloc de démarrage Windows de
    # planche-contact-gtk.py va les chercher.
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
