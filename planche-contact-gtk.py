#!/usr/bin/env python3
"""
Planche-Contact GTK - Interface Graphique
"""
import sys
import os
from pathlib import Path

# --- Interception des processus de travail multiprocessing (AVANT tout
# import GTK) -----------------------------------------------------------
# Dans un exécutable gelé (PyInstaller), chaque worker de ProcessPoolExecutor
# (utilisé pour les planches contact et la galerie HTML, jusqu'à 64 workers
# en parallèle) relance ce même exécutable. Sans cette interception TRÈS TÔT
# - avant même `import gi` -, chaque worker chargerait inutilement toute la
# pile GTK4 (DLL, typelibs...) avant d'atteindre multiprocessing.freeze_
# support() plus bas, alors qu'un worker ne fait que du traitement d'image
# et n'a jamais besoin de GTK. Un gaspillage de temps non négligeable,
# multiplié par le nombre de workers. Sans effet en exécution depuis les
# sources (Linux/macOS, non gelé) : freeze_support() n'y fait rien de toute
# façon dans ce cas normal (pas un worker), et l'exécution continue
# normalement plus bas.
if getattr(sys, "frozen", False):
    import multiprocessing
    multiprocessing.freeze_support()
    # Si l'exécution arrive jusqu'ici, ce n'est pas un worker multiprocessing
    # (sinon freeze_support() aurait déjà appelé sys.exit() ci-dessus) : on
    # continue normalement vers le chargement de l'application GTK.

# --- Bootstrap Windows (paquet gelé PyInstaller) ---------------------------
# Quand l'application tourne comme exécutable Windows gelé par PyInstaller
# (voir windows/planche-contact.spec), GTK4 et ses typelibs sont embarqués à
# côté de l'exécutable plutôt qu'installés dans le système : il faut donc
# indiquer explicitement à PyGObject où les trouver, avant le tout premier
# `import gi`. Sans effet sur Linux/macOS, ni en exécution depuis les
# sources (getattr(sys, "frozen", False) n'est vrai que dans un exécutable
# gelé par PyInstaller).
if sys.platform == "win32" and getattr(sys, "frozen", False):
    _app_dir = Path(sys.executable).parent
    _typelib_dir = _app_dir / "gi_typelibs"
    if _typelib_dir.is_dir():
        os.environ["GI_TYPELIB_PATH"] = str(_typelib_dir)
    # Les DLL de GTK4 (bin/ de gvsbuild) sont embarquées à la racine du
    # paquet, à côté de l'exécutable : on l'ajoute explicitement au chemin
    # de recherche des DLL (nécessaire depuis Python 3.8 sous Windows,
    # modifier PATH seul ne suffit plus).
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(_app_dir))
        except OSError:
            pass

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gio, Gdk, GdkPixbuf

import subprocess
import threading
import json
import re
import io
import webbrowser
import tempfile
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from portfolio.config import Config
from portfolio.scanner import ImageScanner
from portfolio.rawloader import load_image
from portfolio.i18n import _, set_language, get_language, AVAILABLE_LANGUAGES, detect_system_language
from portfolio.presentation import (
    Profile, LayoutSettings, CaptionSettings, ThemeSettings, ThemeCustomColors,
    CAPTION_FIELDS, LAYOUT_TEMPLATES, FIT_MODES, ORIENTATIONS, CAPTION_POSITIONS,
    CAPTION_ALIGNMENTS, THEME_MODES, HEADER_POSITIONS, default_profile, load_profile,
    save_profile, compute_effective_per_page,
)


def glib_idle_add(function, *args):
    """Enveloppe autour de GLib.idle_add(), tolérante à deux conventions
    d'appel possibles selon la version/le binding de PyGObject :
    - GLib.idle_add(function, *args)               (forme pythonique
      habituelle, fournie par le module de surcharge Python de GLib)
    - GLib.idle_add(priorite, function, *args)      (signature brute de la
      fonction C sous-jacente, utilisée si ce module de surcharge n'est
      pas chargé - observé sur un exécutable gelé par PyInstaller avec la
      pile GTK4 gvsbuild sous Windows : "TypeError: Must be number, not
      method").
    Cette fonction essaie d'abord la forme pythonique ; en cas d'échec
    précisément pour cette raison, elle retente avec la priorité en tête.
    Aucun effet sur Linux/macOS, où la forme pythonique fonctionne toujours
    du premier coup."""
    try:
        return GLib.idle_add(function, *args)
    except TypeError:
        return GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, function, *args)


PREVIEW_PAGE_SIZE = 10
PREVIEW_THUMB_SIZE = 90
DIALOG_PREVIEW_PAGE_SIZE = PREVIEW_PAGE_SIZE * 2  # 2 lignes de 10 dans le sélecteur de dossier

#: Couleur personnalisée attendue au format "#rrggbb" (cahier des charges
#: §4.3) - voir PlancheContactGTK._hex_or_none().
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _pagination_sequence(current, total, window=2):
    """Retourne une séquence comme [1, '…', 3, 4, 5, 6, 7, '…', 19] pour
    current=5, total=19, window=2 (current et total sont 1-indexés)."""
    if total <= 0:
        return []
    pages = {1, total}
    for p in range(current - window, current + window + 1):
        if 1 <= p <= total:
            pages.add(p)
    sequence = []
    prev = None
    for p in sorted(pages):
        if prev is not None and p - prev > 1:
            sequence.append("…")
        sequence.append(p)
        prev = p
    return sequence


class FolderPreviewController:
    """Scanne un dossier et affiche les vignettes des photos qu'il contient,
    par pages de PREVIEW_PAGE_SIZE, dans un jeu de widgets GTK donné.

    Réutilisé à la fois par la bande d'aperçu de la fenêtre principale et
    par le sélecteur de dossier personnalisé (celui-ci en a besoin car la
    boîte de dialogue native de GTK4 ne permet plus d'y intégrer de widget
    de prévisualisation - voir _choose_folder)."""

    def __init__(self, status_label, flow_box, prev_btn, next_btn, pages_box, page_size=PREVIEW_PAGE_SIZE):
        self.status_label = status_label
        self.flow_box = flow_box
        self.prev_btn = prev_btn
        self.next_btn = next_btn
        self.pages_box = pages_box
        self.page_size = page_size

        self._token = 0
        self._files = []
        self._page = 0
        self._page_cache = {}

        self.prev_btn.connect("clicked", lambda b: self.go_prev())
        self.next_btn.connect("clicked", lambda b: self.go_next())

    def refresh(self, folder_path):
        self._token += 1
        token = self._token

        self._files = []
        self._page = 0
        self._page_cache = {}
        self._clear_flow()
        self._update_nav()

        if not folder_path or not Path(folder_path).is_dir():
            self.status_label.set_text("")
            return

        self.status_label.set_text(_("preview.analyzing"))
        threading.Thread(
            target=self._scan_files,
            args=(folder_path, token),
            daemon=True
        ).start()

    def _clear_flow(self):
        child = self.flow_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.flow_box.remove(child)
            child = next_child

    def _scan_files(self, folder_path, token):
        """Exécuté en arrière-plan : liste uniquement les fichiers (rapide,
        pas de décodage d'image ici) pour connaître le nombre total de
        photos et permettre la pagination."""
        try:
            folder = Path(folder_path)
            image_files = sorted(
                p for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() in ImageScanner.SUPPORTED_EXTENSIONS
            )
        except Exception:
            image_files = []
        glib_idle_add(self._apply_file_list, token, image_files)

    def _apply_file_list(self, token, image_files):
        if token != self._token:
            return False  # Un scan plus récent a été lancé entre-temps.

        self._files = image_files
        self._page = 0
        self._page_cache = {}

        if not image_files:
            self.status_label.set_text(_("preview.no_photos"))
            self._clear_flow()
            self._update_nav()
            return False

        self._load_page(0)
        return False

    def _total_pages(self):
        if not self._files:
            return 0
        return (len(self._files) - 1) // self.page_size + 1

    def _update_nav(self):
        total_pages = self._total_pages()

        child = self.pages_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.pages_box.remove(child)
            child = next_child

        if total_pages <= 1:
            self.prev_btn.set_sensitive(False)
            self.next_btn.set_sensitive(False)
            return

        current_1indexed = self._page + 1
        for item in _pagination_sequence(current_1indexed, total_pages):
            if item == "…":
                lbl = Gtk.Label(label="…")
                lbl.add_css_class("dim-label")
                lbl.set_margin_start(4)
                lbl.set_margin_end(4)
                self.pages_box.append(lbl)
            else:
                btn = Gtk.Button(label=str(item))
                btn.set_size_request(36, -1)
                if item == current_1indexed:
                    btn.set_sensitive(False)
                    btn.add_css_class("suggested-action")
                else:
                    btn.connect("clicked", lambda b, p=item: self._load_page(p - 1))
                self.pages_box.append(btn)

        self.prev_btn.set_sensitive(self._page > 0)
        self.next_btn.set_sensitive(self._page < total_pages - 1)

    def go_prev(self):
        if self._page > 0:
            self._load_page(self._page - 1)

    def go_next(self):
        if self._page < self._total_pages() - 1:
            self._load_page(self._page + 1)

    def _load_page(self, page_index):
        self._page = page_index
        token = self._token
        total = len(self._files)
        start = page_index * self.page_size
        end = min(start + self.page_size, total)

        self._update_nav()

        # Page déjà générée précédemment (navigation arrière notamment) :
        # on l'affiche immédiatement, sans repasser par un thread.
        if page_index in self._page_cache:
            self._display(self._page_cache[page_index], start, end, total)
            return

        self._clear_flow()
        self.status_label.set_text(_("preview.loading", start=start + 1, end=end, total=total))

        files_slice = self._files[start:end]
        threading.Thread(
            target=self._generate_thumbs,
            args=(files_slice, token, page_index, start, end, total),
            daemon=True
        ).start()

    def _generate_thumbs(self, files_slice, token, page_index, start, end, total):
        """Exécuté en arrière-plan : ne touche à aucun widget GTK ici."""
        thumbs = []
        for path in files_slice:
            try:
                img = load_image(path, use_embedded_thumb=True)
                img = img.convert("RGB")
                img.thumbnail((PREVIEW_THUMB_SIZE, PREVIEW_THUMB_SIZE))
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                thumbs.append(buf.getvalue())
            except Exception:
                continue
        glib_idle_add(self._apply_thumbs, token, page_index, thumbs, start, end, total)

    def _apply_thumbs(self, token, page_index, thumb_bytes_list, start, end, total):
        if token != self._token:
            return False  # Le dossier a changé entre-temps.
        if page_index != self._page:
            return False  # L'utilisateur a déjà changé de page entre-temps.

        self._page_cache[page_index] = thumb_bytes_list
        self._display(thumb_bytes_list, start, end, total)
        return False

    def _display(self, thumb_bytes_list, start, end, total):
        self._clear_flow()

        shown = len(thumb_bytes_list)
        if shown < (end - start):
            self.status_label.set_text(
                _("preview.showing_partial", start=start + 1, end=end, total=total, shown=shown)
            )
        else:
            self.status_label.set_text(_("preview.showing", start=start + 1, end=end, total=total))

        for data in thumb_bytes_list:
            try:
                stream = Gio.MemoryInputStream.new_from_data(data, None)
                pixbuf = GdkPixbuf.Pixbuf.new_from_stream(stream, None)
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                picture = Gtk.Picture.new_for_paintable(texture)
                picture.set_size_request(PREVIEW_THUMB_SIZE, PREVIEW_THUMB_SIZE)
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                self.flow_box.append(picture)
            except Exception:
                continue


class PlancheContactGTK(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.planchecontact.gtk")
        self.win = None
        self.settings_path = Path.home() / ".config" / "planche-contact" / "settings.json"
        self.last_input_dir = ""
        self.last_output_dir = ""
        self.language_preference = "system"
        self._preview_debounce_id = None
        self._output_debounce_id = None
        self._last_result = None
        self._pending_result = None
        # Référence conservée tant qu'une boîte de dialogue Gtk.FileChooserNative
        # (enregistrer/charger un profil) est ouverte, pour éviter qu'elle soit
        # collectée par Python avant que l'utilisateur n'y réponde.
        self._active_file_dialog = None
        self.load_settings()
        # Résolu AVANT toute construction d'interface : tous les widgets
        # créés dans do_activate() appellent _() en supposant la langue
        # déjà active. self._language_fallback_detected reste None sauf si
        # la langue système demandée n'a aucune traduction disponible -
        # dans ce cas, un avertissement est affiché une fois la fenêtre
        # affichée (voir do_activate).
        self._language, self._language_fallback_detected = set_language(self.language_preference)

    def load_settings(self):
        try:
            if self.settings_path.exists():
                with open(self.settings_path, "r") as f:
                    data = json.load(f)
                    self.last_input_dir = data.get("last_input_dir", "")
                    self.last_output_dir = data.get("last_output_dir", "")
                    self.language_preference = data.get("language", "system")
        except Exception:
            pass

    def save_settings(self):
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_input_dir": self.last_input_dir,
            "last_output_dir": self.last_output_dir,
            "language": self.language_preference
        }
        with open(self.settings_path, "w") as f:
            json.dump(data, f, indent=2)

    def do_activate(self):
        self.win = Gtk.ApplicationWindow(application=self)
        self.win.set_title("Planche-Contact")
        # Pas de set_default_size() : la fenêtre s'ouvre à la taille la plus
        # réduite possible (celle nécessaire pour afficher son contenu sans
        # rien couper), déterminée automatiquement par GTK à partir des
        # tailles minimales des widgets. Elle reste normalement
        # redimensionnable (agrandissable) par l'utilisateur ensuite.
        self.win.set_icon_name("image-x-generic")

        # Barre de titre avec un menu (bouton hamburger) donnant accès aux
        # Préférences - volontairement PAS dans l'onglet À propos, qui
        # reste purement informatif (version, licence, crédits) : un
        # réglage comme la langue n'a logiquement rien à y faire.
        headerbar = Gtk.HeaderBar()
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")

        menu_popover = Gtk.Popover()
        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        menu_box.set_margin_top(6)
        menu_box.set_margin_bottom(6)
        menu_box.set_margin_start(6)
        menu_box.set_margin_end(6)

        prefs_item = Gtk.Button(label=_("prefs.title"))
        prefs_item.add_css_class("flat")
        child = prefs_item.get_child()
        if child is not None:
            child.set_xalign(0)

        def on_prefs_clicked(b):
            menu_popover.popdown()
            self._open_preferences()

        prefs_item.connect("clicked", on_prefs_clicked)
        menu_box.append(prefs_item)
        menu_popover.set_child(menu_box)
        menu_button.set_popover(menu_popover)
        headerbar.pack_end(menu_button)
        self.win.set_titlebar(headerbar)

        notebook = Gtk.Notebook()
        self.win.set_child(notebook)

        notebook.append_page(self._build_generation_tab(), Gtk.Label(label=_("tab.generation")))
        notebook.append_page(self._build_help_tab(), Gtk.Label(label=_("tab.help")))
        notebook.append_page(self._build_about_tab(), Gtk.Label(label=_("tab.about")))

        self.win.present()

        # Le set_text() initial du champ dossier d'entrée a lieu avant la
        # connexion du signal "changed" : on déclenche donc l'aperçu ici
        # explicitement pour un dossier déjà mémorisé au démarrage.
        if self.last_input_dir:
            self.input_preview.refresh(self.last_input_dir)

        # Même chose pour le dossier de sortie : si des résultats existent
        # déjà (générés lors d'une session précédente), "Afficher les
        # résultats" doit être opérant sans attendre une nouvelle génération.
        if self.last_output_dir:
            self._check_existing_results(self.last_output_dir)

        # Langue système sélectionnée mais sans traduction disponible :
        # affiché une seule fois au démarrage, après la fenêtre principale
        # pour ne pas retarder son affichage.
        if self._language_fallback_detected is not None:
            dialog = Gtk.AlertDialog()
            dialog.set_modal(True)
            dialog.set_message(_("lang.fallback_warning_title"))
            dialog.set_detail(_("lang.fallback_warning_detail", detected=self._language_fallback_detected))
            dialog.set_buttons(["OK"])
            dialog.show(self.win)

    def _open_preferences(self):
        dialog = Gtk.Window(transient_for=self.win, modal=True)
        dialog.set_title(_("prefs.title"))
        dialog.set_default_size(360, -1)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)
        dialog.set_child(box)

        lang_box = Gtk.Box(spacing=10)
        lang_box.append(Gtk.Label(label=_("about.language_label")))
        lang_model = Gtk.StringList()
        for code in AVAILABLE_LANGUAGES:
            lang_model.append(_(f"lang.{code}"))
        self.language_combo = Gtk.DropDown(model=lang_model)
        self.language_combo.set_selected(AVAILABLE_LANGUAGES.index(self.language_preference))
        self.language_combo.set_hexpand(True)
        lang_box.append(self.language_combo)
        box.append(lang_box)

        self.language_restart_label = Gtk.Label(label=_("about.language_restart_notice"))
        self.language_restart_label.add_css_class("dim-label")
        self.language_restart_label.set_wrap(True)
        self.language_restart_label.set_xalign(0)
        self.language_restart_label.set_visible(False)
        box.append(self.language_restart_label)

        self.language_combo.connect("notify::selected", self._on_language_changed)

        dialog.present()

    # ====================== ONGLET GÉNÉRATION ======================

    def _build_generation_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(15)
        box.set_margin_start(25)
        box.set_margin_end(25)

        # Titre du projet + Nom de l'auteur (même ligne)
        hbox = Gtk.Box(spacing=10)
        hbox.append(Gtk.Label(label=_("gen.project_title")))
        self.project_title_entry = Gtk.Entry()
        self.project_title_entry.set_hexpand(False)
        self.project_title_entry.set_halign(Gtk.Align.START)
        self.project_title_entry.set_width_chars(45)
        hbox.append(self.project_title_entry)

        author_label = Gtk.Label(label=_("gen.author"))
        author_label.set_margin_start(15)
        hbox.append(author_label)
        self.author_entry = Gtk.Entry()
        self.author_entry.set_hexpand(False)
        self.author_entry.set_halign(Gtk.Align.START)
        self.author_entry.set_width_chars(36)
        hbox.append(self.author_entry)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        hbox.append(spacer)
        box.append(hbox)

        # Dossier d'entrée
        hbox = Gtk.Box(spacing=10)
        hbox.append(Gtk.Label(label=_("gen.input_dir")))
        self.input_entry = Gtk.Entry()
        if self.last_input_dir:
            self.input_entry.set_text(self.last_input_dir)
        self.input_entry.set_hexpand(False)
        self.input_entry.set_halign(Gtk.Align.START)
        self.input_entry.set_width_chars(68)
        self.input_entry.connect("changed", self._on_input_entry_changed)
        btn = Gtk.Button(label=_("gen.choose"))
        btn.connect("clicked", self._choose_folder, self.input_entry, "input")
        hbox.append(self.input_entry)
        hbox.append(btn)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        hbox.append(spacer)
        box.append(hbox)

        # Aperçu des photos du dossier d'entrée (le sélecteur système ne
        # propose pas de vignettes pour un choix de dossier : on affiche
        # donc ici un aperçu généré par l'application elle-même, paginé
        # pour rester fluide même sur un dossier contenant des centaines
        # de photos).
        self.input_preview_status = Gtk.Label(label="")
        self.input_preview_status.set_xalign(0)
        self.input_preview_status.add_css_class("dim-label")
        box.append(self.input_preview_status)

        self.input_preview_flow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.input_preview_flow.set_margin_top(2)
        preview_scroll = Gtk.ScrolledWindow()
        preview_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        preview_scroll.set_min_content_height(PREVIEW_THUMB_SIZE + 10)
        preview_scroll.set_max_content_height(PREVIEW_THUMB_SIZE + 10)
        # set_size_request en complément : min/max_content_height ne semblent
        # pas s'appliquer tant que le contenu (les vignettes) n'a pas encore
        # été chargé (la zone reste alors quasi invisible, ~2px), ce qui fait
        # grandir la fenêtre après coup une fois l'aperçu chargé - et
        # perturbe le centrage vertical fait par le gestionnaire de
        # fenêtres à l'ouverture. set_size_request agit dès le premier
        # affichage, sans attendre le contenu.
        preview_scroll.set_size_request(-1, PREVIEW_THUMB_SIZE + 10)
        preview_scroll.set_child(self.input_preview_flow)
        box.append(preview_scroll)

        preview_nav = Gtk.Box(spacing=6)
        preview_nav.set_halign(Gtk.Align.CENTER)
        preview_nav.set_margin_top(2)
        self.preview_prev_btn = Gtk.Button(label=_("preview.prev"))
        self.preview_prev_btn.set_sensitive(False)
        self.preview_pages_box = Gtk.Box(spacing=4)
        # Hauteur réservée dès le départ (avant même qu'un dossier ne soit
        # scanné) : sans ça, cette zone est vide au premier affichage puis
        # se remplit de boutons de pagination une fois le scan terminé, ce
        # qui agrandit la fenêtre après coup - et perturbe le centrage
        # vertical fait par le gestionnaire de fenêtres à l'ouverture.
        self.preview_pages_box.set_size_request(-1, 34)
        self.preview_next_btn = Gtk.Button(label=_("preview.next"))
        self.preview_next_btn.set_sensitive(False)
        preview_nav.append(self.preview_prev_btn)
        preview_nav.append(self.preview_pages_box)
        preview_nav.append(self.preview_next_btn)
        box.append(preview_nav)

        self.input_preview = FolderPreviewController(
            self.input_preview_status, self.input_preview_flow,
            self.preview_prev_btn, self.preview_next_btn, self.preview_pages_box
        )

        # Dossier de sortie
        hbox = Gtk.Box(spacing=10)
        hbox.append(Gtk.Label(label=_("gen.output_dir")))
        self.output_entry = Gtk.Entry()
        if self.last_output_dir:
            self.output_entry.set_text(self.last_output_dir)
        self.output_entry.set_hexpand(False)
        self.output_entry.set_halign(Gtk.Align.START)
        self.output_entry.set_width_chars(68)
        self.output_entry.connect("changed", self._on_output_entry_changed)
        btn = Gtk.Button(label=_("gen.choose"))
        btn.connect("clicked", self._choose_folder, self.output_entry, "output")
        hbox.append(self.output_entry)
        hbox.append(btn)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        hbox.append(spacer)
        box.append(hbox)

        # Options
        grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        self.recursive_check = Gtk.CheckButton(label=_("gen.recursive"))
        grid.attach(self.recursive_check, 0, 0, 8, 1)

        grid.attach(Gtk.Label(label=_("gen.images_per_sheet")), 0, 1, 1, 1)
        num_model = Gtk.StringList()
        for n in range(8, 49, 4):
            num_model.append(str(n))
        self.num_combo = Gtk.DropDown(model=num_model)
        self.num_combo.set_selected(1)
        grid.attach(self.num_combo, 1, 1, 1, 1)

        format_label = Gtk.Label(label=_("gen.sheet_format"))
        format_label.set_margin_start(20)
        grid.attach(format_label, 2, 1, 1, 1)
        format_model = Gtk.StringList()
        for fmt in ["A5", "A4", "A3", "A2", "Letter"]:
            format_model.append(fmt)
        self.format_combo = Gtk.DropDown(model=format_model)
        self.format_combo.set_selected(1)
        grid.attach(self.format_combo, 3, 1, 1, 1)

        # Filigrane : sur la même ligne, pour limiter la hauteur du formulaire
        watermark_label = Gtk.Label(label=_("gen.watermark_text"))
        watermark_label.set_margin_start(20)
        grid.attach(watermark_label, 4, 1, 1, 1)
        self.watermark_entry = Gtk.Entry()
        self.watermark_entry.set_hexpand(False)
        self.watermark_entry.set_halign(Gtk.Align.START)
        self.watermark_entry.set_width_chars(18)
        grid.attach(self.watermark_entry, 5, 1, 1, 1)

        orient_label = Gtk.Label(label=_("gen.watermark_orientation"))
        orient_label.set_margin_start(20)
        grid.attach(orient_label, 6, 1, 1, 1)
        # Les valeurs de ce menu sont transmises telles quelles au CLI
        # (portfolio.py --watermark-orientation), qui les compare en
        # français (voir portfolio/config.py) : on affiche la traduction
        # mais on garde la valeur française en interne pour ne rien casser
        # côté moteur.
        self._orient_values = ["Horizontal", "Diagonale horaire", "Diagonale anti-horaire"]
        orient_model = Gtk.StringList()
        for key in ["watermark.horizontal", "watermark.diagonal_cw", "watermark.diagonal_ccw"]:
            orient_model.append(_(key))
        self.watermark_orient_combo = Gtk.DropDown(model=orient_model)
        self.watermark_orient_combo.set_selected(0)
        grid.attach(self.watermark_orient_combo, 7, 1, 1, 1)

        # Opacité du filigrane (0-100%), valeur par défaut alignée sur celle
        # utilisée par le générateur (voir portfolio/config.py).
        opacity_label = Gtk.Label(label=_("gen.watermark_opacity"))
        grid.attach(opacity_label, 0, 2, 1, 1)
        self.watermark_opacity_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.watermark_opacity_scale.set_value(40)
        self.watermark_opacity_scale.set_draw_value(True)
        self.watermark_opacity_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.watermark_opacity_scale.set_hexpand(False)
        self.watermark_opacity_scale.set_size_request(220, -1)
        grid.attach(self.watermark_opacity_scale, 1, 2, 3, 1)

        # Thème graphique (Clair/Sombre/Neutre/Système) : un réglage COURANT,
        # donc visible dans la fenêtre principale plutôt que caché dans la
        # section avancée repliée (signalé par un utilisateur : "je ne vois
        # pas de choix de thème"). Seules les couleurs PERSONNALISÉES
        # restent dans la section avancée. Ce menu est l'unique widget du
        # mode de thème : _profile_from_widgets()/_apply_profile_to_widgets()
        # le lisent/l'écrivent comme les autres réglages du Profil.
        theme_label = Gtk.Label(label=_("gen.theme_label"))
        theme_label.set_margin_start(20)
        grid.attach(theme_label, 4, 2, 1, 1)
        self.theme_mode_dd = self._make_choice_dropdown(
            THEME_MODES, [f"gen.theme_mode.{m}" for m in THEME_MODES]
        )
        self.theme_mode_dd.set_tooltip_text(_("gen.theme_tooltip"))
        theme_label.set_tooltip_text(_("gen.theme_tooltip"))
        grid.attach(self.theme_mode_dd, 5, 2, 1, 1)

        self.pdf_check = Gtk.CheckButton(label=_("gen.generate_pdf"))
        self.html_check = Gtk.CheckButton(label=_("gen.generate_html"))
        self.csv_check = Gtk.CheckButton(label=_("gen.generate_csv"))
        self.pdf_check.set_active(True)
        self.html_check.set_active(True)
        self.csv_check.set_active(True)

        grid.attach(self.pdf_check, 0, 3, 2, 1)
        grid.attach(self.html_check, 0, 4, 2, 1)
        grid.attach(self.csv_check, 0, 5, 2, 1)

        # Nombre d'images par page de la galerie HTML : sur la même ligne
        # que la case à cocher correspondante (voir portfolio/htmlgallery.py,
        # HTMLGalleryGenerator.images_per_page, défaut 48).
        html_per_page_label = Gtk.Label(label=_("gen.images_per_page"))
        html_per_page_label.set_margin_start(20)
        grid.attach(html_per_page_label, 2, 4, 1, 1)
        self.html_per_page_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 12, 64, 4)
        self.html_per_page_scale.set_value(48)
        self.html_per_page_scale.set_digits(0)
        self.html_per_page_scale.set_draw_value(True)
        self.html_per_page_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self.html_per_page_scale.set_hexpand(False)
        self.html_per_page_scale.set_size_request(220, -1)
        # GtkScale ne cale pas nativement le glissé à la souris sur le pas
        # fourni à new_with_range (celui-ci ne régit que le clavier/molette) :
        # on arrondit donc manuellement au multiple de 4 le plus proche.
        self.html_per_page_scale.connect("value-changed", self._snap_html_per_page)
        grid.attach(self.html_per_page_scale, 3, 4, 3, 1)

        box.append(grid)

        # Mise en page/légendes/thème personnalisables (cahier des charges
        # §1/§2/§4) : dans une fenêtre modale à part, clairement à l'écart
        # des réglages simples/courants ci-dessus - voir
        # _build_advanced_section() et _open_advanced_dialog().
        #
        # Auparavant un Gtk.Expander dans cette fenêtre : une fois déplié,
        # il l'agrandissait d'environ 550 px (jusqu'à ~1600 px de haut), bien
        # au-delà de la hauteur d'un écran, et repoussait les boutons
        # « Lancer »/« Quitter » hors de vue. Les widgets sont toujours
        # construits ICI, une seule fois, et vivent aussi longtemps que
        # l'application : _profile_from_widgets() lit donc leur état même si
        # la fenêtre n'a jamais été ouverte (profil par défaut). La fenêtre,
        # elle, n'est créée qu'à la première ouverture, puis seulement
        # masquée à sa fermeture (les réglages sont conservés).
        self.adv_content = self._build_advanced_section()
        self._adv_dialog = None
        self.adv_open_btn = Gtk.Button(label=_("adv.open_button"))
        self.adv_open_btn.set_halign(Gtk.Align.START)
        self.adv_open_btn.set_margin_top(4)
        self.adv_open_btn.set_tooltip_text(_("adv.open_button_tooltip"))
        self.adv_open_btn.connect("clicked", self._open_advanced_dialog)
        box.append(self.adv_open_btn)
        self._apply_profile_to_widgets(default_profile())

        # Boutons
        hbox = Gtk.Box(spacing=10)
        self.run_button = Gtk.Button(label=_("gen.run"))
        self.run_button.add_css_class("suggested-action")
        self.run_button.connect("clicked", self._on_generate)

        reset_btn = Gtk.Button(label=_("gen.reset"))
        reset_btn.connect("clicked", self._reset_form)

        # Bouton à liste déroulante pour ouvrir les résultats (planches,
        # PDF, galerie) dans les applications par défaut du système - pas
        # d'aperçu intégré, donc la fenêtre principale ne grandit pas.
        # Désactivé tant qu'aucune génération n'a réussi ; chaque option
        # individuelle n'est activée que si l'élément correspondant a
        # effectivement été produit lors de la dernière génération.
        self.view_results_btn = Gtk.MenuButton(label=_("gen.view_results"))
        self.view_results_btn.set_sensitive(False)

        view_popover = Gtk.Popover()
        view_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        view_box.set_margin_top(6)
        view_box.set_margin_bottom(6)
        view_box.set_margin_start(6)
        view_box.set_margin_end(6)

        def make_view_item(label_text, handler):
            btn = Gtk.Button(label=label_text)
            btn.add_css_class("flat")
            child = btn.get_child()
            if child is not None:
                child.set_xalign(0)

            def on_clicked(b):
                view_popover.popdown()
                handler()

            btn.connect("clicked", on_clicked)
            view_box.append(btn)
            return btn

        self.view_planches_btn = make_view_item(_("gen.view_planches"), self._open_planches)
        self.view_pdf_btn = make_view_item(_("gen.view_pdf"), self._open_pdf)
        self.view_gallery_btn = make_view_item(_("gen.view_gallery"), self._open_gallery)
        self.view_csv_btn = make_view_item(_("gen.view_csv"), self._open_csv)

        view_popover.set_child(view_box)
        self.view_results_btn.set_popover(view_popover)

        quit_btn = Gtk.Button(label=_("gen.quit"))
        quit_btn.connect("clicked", lambda b: self.quit())

        left_box = Gtk.Box(spacing=10)
        left_box.append(self.run_button)
        left_box.append(reset_btn)
        left_box.append(self.view_results_btn)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)

        hbox.append(left_box)
        hbox.append(spacer)
        hbox.append(quit_btn)
        box.append(hbox)

        self.status_label = Gtk.Label(label="")
        box.append(self.status_label)

        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        box.append(self.progress)

        self.log_buffer = Gtk.TextBuffer()
        self.log_view = Gtk.TextView(buffer=self.log_buffer)
        self.log_view.set_editable(False)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(self.log_view)
        scrolled.set_vexpand(True)
        scrolled.set_min_content_height(260)
        box.append(scrolled)

        return box

    # ====================== FENÊTRE DES RÉGLAGES AVANCÉS ======================

    def _build_advanced_dialog(self):
        """Fenêtre modale contenant self.adv_content (construit une fois pour
        toutes par _build_advanced_section()). Le contenu défile dans sa
        propre zone, dont la hauteur maximale suit celle de l'écran
        (_advanced_dialog_limits()) : la barre du bas - message d'état et
        bouton « Fermer » - reste toujours visible, même sur un petit écran."""
        dialog = Gtk.Window(transient_for=self.win, modal=True)
        dialog.set_title(_("adv.dialog_title"))
        # Fermer la fenêtre (croix, Échap, bouton) la MASQUE seulement : les
        # widgets qu'elle contient doivent survivre, ils portent les réglages.
        dialog.set_hide_on_close(True)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        dialog.set_child(root)

        self.adv_scroll = Gtk.ScrolledWindow()
        self.adv_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        # Sans cette propagation, la zone défilante s'ouvrirait à sa taille
        # minimale (quasi nulle) au lieu de celle du contenu.
        self.adv_scroll.set_propagate_natural_width(True)
        self.adv_scroll.set_propagate_natural_height(True)
        self.adv_scroll.set_vexpand(True)
        self.adv_scroll.set_child(self.adv_content)
        root.append(self.adv_scroll)

        root.append(Gtk.Separator())
        bar = Gtk.Box(spacing=10)
        bar.set_margin_top(8)
        bar.set_margin_bottom(8)
        bar.set_margin_start(14)
        bar.set_margin_end(14)

        # Retour d'information VISIBLE ici : la fenêtre principale (et son
        # journal) est masquée derrière cette fenêtre modale tant qu'elle
        # est ouverte (voir _adv_notify()).
        self.adv_status_label = Gtk.Label(label="")
        self.adv_status_label.set_xalign(0)
        self.adv_status_label.set_hexpand(True)
        self.adv_status_label.set_wrap(True)
        self.adv_status_label.add_css_class("dim-label")
        bar.append(self.adv_status_label)

        close_btn = Gtk.Button(label=_("adv.dialog_close"))
        close_btn.add_css_class("suggested-action")
        close_btn.connect("clicked", lambda b: dialog.close())
        bar.append(close_btn)
        root.append(bar)

        key_controller = Gtk.EventControllerKey()

        def on_key_pressed(controller, keyval, keycode, state):
            if keyval == Gdk.KEY_Escape:
                dialog.close()
                return True
            return False

        key_controller.connect("key-pressed", on_key_pressed)
        dialog.add_controller(key_controller)
        return dialog

    def _advanced_dialog_limits(self):
        """(largeur, hauteur) maximales de la zone défilante, déduites de
        l'écran où se trouve la fenêtre principale : la fenêtre des réglages
        avancés, barre de titre et barre du bas comprises, doit tenir dans
        l'écran - jamais plus haute que lui (le défaut corrigé ici). Repli
        sur des valeurs prudentes si la taille de l'écran est introuvable."""
        width, height = 1400, 800
        try:
            surface = self.win.get_surface()
            monitor = Gdk.Display.get_default().get_monitor_at_surface(surface)
            if monitor is not None:
                geometry = monitor.get_geometry()
                if geometry.width > 0 and geometry.height > 0:
                    width, height = geometry.width, geometry.height
        except Exception:
            pass
        return int(width * 0.92), int(height * 0.72)

    def _open_advanced_dialog(self, button=None):
        if self._adv_dialog is None:
            self._adv_dialog = self._build_advanced_dialog()
        max_width, max_height = self._advanced_dialog_limits()
        self.adv_scroll.set_max_content_width(max_width)
        self.adv_scroll.set_max_content_height(max_height)
        self.adv_status_label.set_text("")
        self._adv_dialog.present()

    def _dialog_parent(self):
        """Fenêtre parente à donner à toute fenêtre/boîte de dialogue ouverte
        depuis l'interface : celle des réglages avancés tant qu'elle est
        affichée (étant modale, elle bloque la fenêtre principale - une
        fenêtre fille de CELLE-CI n'aurait aucun effet), la fenêtre
        principale sinon."""
        dialog = getattr(self, "_adv_dialog", None)
        if dialog is not None and dialog.get_visible():
            return dialog
        return self.win

    def _adv_notify(self, message):
        """Message issu d'une action de la fenêtre des réglages avancés
        (aperçu, enregistrer/charger un profil) : consigné dans le journal
        de la fenêtre principale ET affiché dans la barre d'état de la
        fenêtre avancée, seule visible pendant qu'elle est ouverte."""
        self._log(message)
        label = getattr(self, "adv_status_label", None)
        if label is not None:
            label.set_text(message)

    # ====================== MISE EN PAGE/LÉGENDES/THÈME AVANCÉS ======================
    # Cahier des charges §1/§2/§4 : ces réglages alimentent un Profil
    # (portfolio/presentation/profile.py), la même source unique de vérité
    # que les planches JPEG/PDF (contactsheet.py) et la galerie HTML
    # (htmlgallery.py) - jamais de règle de mise en page/légende/thème
    # dupliquée ici. Le nombre de photos par planche et le format de page
    # restent pilotés par les réglages simples existants (num_combo/
    # format_combo) : Config.__post_init__() les synchronise déjà
    # automatiquement dans le Profil, exactement comme pour le CLI sans
    # --profile (voir tests/test_portfolio_cli.py) - ils ne sont donc PAS
    # dupliqués ici pour éviter toute ambiguïté entre deux réglages du
    # même nombre.

    @staticmethod
    def _make_choice_dropdown(values, label_keys, selected_index=0):
        """Un Gtk.DropDown dont chaque option affiche une traduction
        (label_keys) tout en gardant la valeur INTERNE (values, ex :
        LAYOUT_TEMPLATES) récupérable via _dropdown_value() - même principe
        que self._orient_values pour le filigrane, généralisé."""
        model = Gtk.StringList()
        for key in label_keys:
            model.append(_(key))
        dropdown = Gtk.DropDown(model=model)
        dropdown.set_selected(selected_index)
        dropdown._pc_values = tuple(values)
        return dropdown

    @staticmethod
    def _dropdown_value(dropdown):
        return dropdown._pc_values[dropdown.get_selected()]

    @staticmethod
    def _set_dropdown_value(dropdown, value):
        try:
            index = dropdown._pc_values.index(value)
        except ValueError:
            index = 0
        dropdown.set_selected(index)

    @staticmethod
    def _spin_or_none(spin_button):
        """0 = automatique (None) - utilisé pour les colonnes/lignes du
        modèle "Libre" (LayoutSettings.columns/rows)."""
        value = int(spin_button.get_value())
        return value if value > 0 else None

    @staticmethod
    def _hex_or_none(entry):
        """Couleur personnalisée valide ("#rrggbb") ou None (champ vide ou
        invalide) - jamais d'exception, la couleur par défaut du thème
        s'applique alors simplement (voir ThemeCustomColors). Un contenu
        non vide mais invalide est signalé visuellement (bordure rouge),
        sans bloquer la génération pour autant."""
        text = entry.get_text().strip()
        if not text:
            entry.remove_css_class("error")
            return None
        if _HEX_COLOR_RE.match(text):
            entry.remove_css_class("error")
            return text
        entry.add_css_class("error")
        return None

    def _build_advanced_section(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)

        def subtitle(key):
            lbl = Gtk.Label()
            lbl.set_markup(f"<b>{_(key)}</b>")
            lbl.set_xalign(0)
            lbl.set_margin_top(6)
            return lbl

        # --- Mise en page (cahier des charges §2) --------------------------
        box.append(subtitle("adv.layout_subtitle"))
        grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        box.append(grid)

        grid.attach(Gtk.Label(label=_("adv.template_label"), xalign=0), 0, 0, 1, 1)
        self.adv_template_dd = self._make_choice_dropdown(
            LAYOUT_TEMPLATES, [f"adv.template.{t}" for t in LAYOUT_TEMPLATES]
        )
        self.adv_template_dd.connect("notify::selected", self._update_advanced_sensitivity)
        grid.attach(self.adv_template_dd, 1, 0, 1, 1)

        orient_label = Gtk.Label(label=_("adv.orientation_label"), xalign=0)
        orient_label.set_margin_start(20)
        grid.attach(orient_label, 2, 0, 1, 1)
        self.adv_orientation_dd = self._make_choice_dropdown(
            ORIENTATIONS, [f"adv.orientation.{o}" for o in ORIENTATIONS]
        )
        grid.attach(self.adv_orientation_dd, 3, 0, 1, 1)

        fit_label = Gtk.Label(label=_("adv.fit_mode_label"), xalign=0)
        fit_label.set_margin_start(20)
        grid.attach(fit_label, 4, 0, 1, 1)
        self.adv_fit_mode_dd = self._make_choice_dropdown(
            FIT_MODES, [f"adv.fit_mode.{m}" for m in FIT_MODES]
        )
        fit_label.set_tooltip_text(_("adv.fit_mode_tooltip"))
        self.adv_fit_mode_dd.set_tooltip_text(_("adv.fit_mode_tooltip"))
        grid.attach(self.adv_fit_mode_dd, 5, 0, 1, 1)

        grid.attach(Gtk.Label(label=_("adv.margin_label"), xalign=0), 0, 1, 1, 1)
        self.adv_margin_spin = Gtk.SpinButton.new_with_range(0, 60, 1)
        grid.attach(self.adv_margin_spin, 1, 1, 1, 1)

        spacing_label = Gtk.Label(label=_("adv.spacing_label"), xalign=0)
        spacing_label.set_margin_start(20)
        grid.attach(spacing_label, 2, 1, 1, 1)
        self.adv_spacing_spin = Gtk.SpinButton.new_with_range(0, 40, 1)
        grid.attach(self.adv_spacing_spin, 3, 1, 1, 1)

        cols_label = Gtk.Label(label=_("adv.free_columns_label"), xalign=0)
        cols_label.set_margin_start(20)
        grid.attach(cols_label, 4, 1, 1, 1)
        self.adv_free_cols_spin = Gtk.SpinButton.new_with_range(0, 12, 1)
        grid.attach(self.adv_free_cols_spin, 5, 1, 1, 1)

        rows_label = Gtk.Label(label=_("adv.free_rows_label"), xalign=0)
        rows_label.set_margin_start(20)
        grid.attach(rows_label, 6, 1, 1, 1)
        self.adv_free_rows_spin = Gtk.SpinButton.new_with_range(0, 12, 1)
        grid.attach(self.adv_free_rows_spin, 7, 1, 1, 1)

        grid.attach(Gtk.Label(label=_("adv.title_position_label"), xalign=0), 0, 2, 1, 1)
        self.adv_title_position_dd = self._make_choice_dropdown(
            HEADER_POSITIONS, [f"adv.header_position.{p}" for p in HEADER_POSITIONS]
        )
        grid.attach(self.adv_title_position_dd, 1, 2, 1, 1)

        author_pos_label = Gtk.Label(label=_("adv.author_position_label"), xalign=0)
        author_pos_label.set_margin_start(20)
        grid.attach(author_pos_label, 2, 2, 1, 1)
        self.adv_author_position_dd = self._make_choice_dropdown(
            HEADER_POSITIONS, [f"adv.header_position.{p}" for p in HEADER_POSITIONS]
        )
        grid.attach(self.adv_author_position_dd, 3, 2, 1, 1)

        self.adv_page_numbering_check = Gtk.CheckButton(label=_("adv.page_numbering_label"))
        self.adv_page_numbering_check.set_margin_start(20)
        self.adv_page_numbering_check.set_tooltip_text(_("adv.page_numbering_tooltip"))
        grid.attach(self.adv_page_numbering_check, 4, 2, 2, 1)

        # --- Légendes par photo (cahier des charges §1) ---------------------
        box.append(subtitle("adv.captions_subtitle"))
        grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        box.append(grid)

        grid.attach(Gtk.Label(label=_("adv.caption_position_label"), xalign=0), 0, 0, 1, 1)
        self.adv_caption_position_dd = self._make_choice_dropdown(
            CAPTION_POSITIONS, [f"adv.caption_position.{p}" for p in CAPTION_POSITIONS]
        )
        self.adv_caption_position_dd.connect("notify::selected", self._update_advanced_sensitivity)
        grid.attach(self.adv_caption_position_dd, 1, 0, 1, 1)

        area_label = Gtk.Label(label=_("adv.caption_area_label"), xalign=0)
        area_label.set_margin_start(20)
        grid.attach(area_label, 2, 0, 1, 1)
        self.adv_caption_area_spin = Gtk.SpinButton.new_with_range(4, 40, 1)
        grid.attach(self.adv_caption_area_spin, 3, 0, 1, 1)

        lines_label = Gtk.Label(label=_("adv.caption_lines_label"), xalign=0)
        lines_label.set_margin_start(20)
        grid.attach(lines_label, 4, 0, 1, 1)
        self.adv_caption_lines_spin = Gtk.SpinButton.new_with_range(1, 4, 1)
        # Le texte passe de toute façon à la ligne s'il est trop large pour
        # la vignette (voir presentation.captions.layout_caption_lines()) :
        # ce réglage n'est donc qu'un point de départ, pas une limite.
        lines_label.set_tooltip_text(_("adv.caption_lines_tooltip"))
        self.adv_caption_lines_spin.set_tooltip_text(_("adv.caption_lines_tooltip"))
        grid.attach(self.adv_caption_lines_spin, 5, 0, 1, 1)

        grid.attach(Gtk.Label(label=_("adv.caption_font_size_label"), xalign=0), 0, 1, 1, 1)
        self.adv_caption_font_spin = Gtk.SpinButton.new_with_range(6, 24, 1)
        grid.attach(self.adv_caption_font_spin, 1, 1, 1, 1)

        align_label = Gtk.Label(label=_("adv.caption_alignment_label"), xalign=0)
        align_label.set_margin_start(20)
        grid.attach(align_label, 2, 1, 1, 1)
        self.adv_caption_alignment_dd = self._make_choice_dropdown(
            CAPTION_ALIGNMENTS, [f"adv.caption_alignment.{a}" for a in CAPTION_ALIGNMENTS]
        )
        grid.attach(self.adv_caption_alignment_dd, 3, 1, 1, 1)

        fields_label = Gtk.Label(label=_("adv.caption_fields_label"), xalign=0)
        fields_label.set_margin_top(4)
        box.append(fields_label)

        fields_flow = Gtk.FlowBox()
        fields_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        fields_flow.set_min_children_per_line(3)
        fields_flow.set_max_children_per_line(6)
        fields_flow.set_row_spacing(2)
        fields_flow.set_column_spacing(14)
        box.append(fields_flow)

        self.adv_caption_field_checks = {}
        for field_name in CAPTION_FIELDS:
            label = _(f"adv.field.{field_name}")
            check = Gtk.CheckButton(label=label)
            if field_name == "gps":
                check.set_tooltip_text(_("adv.field_gps_warning"))
            self.adv_caption_field_checks[field_name] = check
            fields_flow.append(check)

        # --- Couleurs personnalisées du thème (cahier des charges §4) -------
        # Le MODE de thème (Clair/Sombre/Neutre/Système) se choisit dans la
        # fenêtre principale (self.theme_mode_dd, voir
        # _build_generation_tab()) : seules les couleurs qui le surchargent
        # restent ici, section avancée.
        box.append(subtitle("adv.theme_subtitle"))

        colors_label = Gtk.Label(label=_("adv.custom_colors_label"), xalign=0)
        colors_label.set_margin_top(4)
        box.append(colors_label)

        colors_box = Gtk.Box(spacing=10)
        box.append(colors_box)

        def make_color_entry(label_key):
            colors_box.append(Gtk.Label(label=_(label_key)))
            entry = Gtk.Entry()
            entry.set_width_chars(9)
            entry.set_placeholder_text(_("adv.custom_color_placeholder"))
            colors_box.append(entry)
            return entry

        self.adv_color_bg_entry = make_color_entry("adv.custom_background_label")
        self.adv_color_text_entry = make_color_entry("adv.custom_text_label")
        self.adv_color_accent_entry = make_color_entry("adv.custom_accent_label")
        self.adv_color_border_entry = make_color_entry("adv.custom_border_label")

        # --- Profils réutilisables (cahier des charges §2/§4.4) + aperçu ----
        actions_box = Gtk.Box(spacing=10)
        actions_box.set_margin_top(10)
        self.adv_preview_btn = Gtk.Button(label=_("adv.preview_button"))
        self.adv_preview_btn.connect("clicked", self._on_preview_clicked)
        actions_box.append(self.adv_preview_btn)

        self.adv_save_profile_btn = Gtk.Button(label=_("adv.save_profile_button"))
        self.adv_save_profile_btn.connect("clicked", self._on_save_profile_clicked)
        actions_box.append(self.adv_save_profile_btn)

        self.adv_load_profile_btn = Gtk.Button(label=_("adv.load_profile_button"))
        self.adv_load_profile_btn.connect("clicked", self._on_load_profile_clicked)
        actions_box.append(self.adv_load_profile_btn)

        box.append(actions_box)

        return box

    def _update_advanced_sensitivity(self, *args):
        is_free = self._dropdown_value(self.adv_template_dd) == "free"
        self.adv_free_cols_spin.set_sensitive(is_free)
        self.adv_free_rows_spin.set_sensitive(is_free)

        has_caption = self._dropdown_value(self.adv_caption_position_dd) != "none"
        self.adv_caption_area_spin.set_sensitive(has_caption)
        self.adv_caption_lines_spin.set_sensitive(has_caption)
        self.adv_caption_font_spin.set_sensitive(has_caption)
        self.adv_caption_alignment_dd.set_sensitive(has_caption)
        for check in self.adv_caption_field_checks.values():
            check.set_sensitive(has_caption)

    def _profile_from_widgets(self) -> Profile:
        """Construit le Profil correspondant à l'état courant des widgets
        avancés ET du menu de thème de la fenêtre principale
        (self.theme_mode_dd) - layout.per_page/page_format restent
        volontairement à leur valeur par défaut (voir l'en-tête de cette
        section) :
        Config.__post_init__() les aligne sur num_combo/format_combo."""
        layout = LayoutSettings(
            template=self._dropdown_value(self.adv_template_dd),
            columns=self._spin_or_none(self.adv_free_cols_spin),
            rows=self._spin_or_none(self.adv_free_rows_spin),
            margin_mm=self.adv_margin_spin.get_value(),
            spacing_mm=self.adv_spacing_spin.get_value(),
            orientation=self._dropdown_value(self.adv_orientation_dd),
            fit_mode=self._dropdown_value(self.adv_fit_mode_dd),
            caption_position=self._dropdown_value(self.adv_caption_position_dd),
            caption_area_mm=self.adv_caption_area_spin.get_value(),
            title_position=self._dropdown_value(self.adv_title_position_dd),
            author_position=self._dropdown_value(self.adv_author_position_dd),
            page_numbering=self.adv_page_numbering_check.get_active(),
        )

        show_gps = self.adv_caption_field_checks["gps"].get_active()
        fields = [
            field_name for field_name in CAPTION_FIELDS
            if field_name != "gps" and self.adv_caption_field_checks[field_name].get_active()
        ]
        if show_gps:
            fields.append("gps")

        captions = CaptionSettings(
            fields=fields,
            lines=int(self.adv_caption_lines_spin.get_value()),
            font_size=int(self.adv_caption_font_spin.get_value()),
            alignment=self._dropdown_value(self.adv_caption_alignment_dd),
            show_gps=show_gps,
        )

        custom = ThemeCustomColors(
            background=self._hex_or_none(self.adv_color_bg_entry),
            text=self._hex_or_none(self.adv_color_text_entry),
            accent=self._hex_or_none(self.adv_color_accent_entry),
            border=self._hex_or_none(self.adv_color_border_entry),
        )
        theme = ThemeSettings(mode=self._dropdown_value(self.theme_mode_dd), custom=custom)

        return Profile(layout=layout, captions=captions, theme=theme)

    def _apply_profile_to_widgets(self, profile: Profile):
        """Réciproque de _profile_from_widgets() : reflète un Profil
        (chargé depuis un fichier, ou default_profile() pour réinitialiser)
        dans l'état des widgets avancés."""
        self._set_dropdown_value(self.adv_template_dd, profile.layout.template)
        self._set_dropdown_value(self.adv_orientation_dd, profile.layout.orientation)
        self._set_dropdown_value(self.adv_fit_mode_dd, profile.layout.fit_mode)
        self.adv_margin_spin.set_value(profile.layout.margin_mm)
        self.adv_spacing_spin.set_value(profile.layout.spacing_mm)
        self.adv_free_cols_spin.set_value(profile.layout.columns or 0)
        self.adv_free_rows_spin.set_value(profile.layout.rows or 0)
        self._set_dropdown_value(self.adv_title_position_dd, profile.layout.title_position)
        self._set_dropdown_value(self.adv_author_position_dd, profile.layout.author_position)
        self.adv_page_numbering_check.set_active(profile.layout.page_numbering)

        self._set_dropdown_value(self.adv_caption_position_dd, profile.layout.caption_position)
        self.adv_caption_area_spin.set_value(profile.layout.caption_area_mm)
        self.adv_caption_lines_spin.set_value(profile.captions.lines)
        self.adv_caption_font_spin.set_value(profile.captions.font_size)
        self._set_dropdown_value(self.adv_caption_alignment_dd, profile.captions.alignment)
        for field_name, check in self.adv_caption_field_checks.items():
            is_active = field_name in profile.captions.fields or (
                field_name == "gps" and profile.captions.show_gps
            )
            check.set_active(is_active)

        self._set_dropdown_value(self.theme_mode_dd, profile.theme.mode)
        self.adv_color_bg_entry.set_text(profile.theme.custom.background or "")
        self.adv_color_text_entry.set_text(profile.theme.custom.text or "")
        self.adv_color_accent_entry.set_text(profile.theme.custom.accent or "")
        self.adv_color_border_entry.set_text(profile.theme.custom.border or "")

        self._update_advanced_sensitivity()

    def _on_save_profile_clicked(self, button):
        dialog = Gtk.FileChooserNative.new(
            _("adv.save_profile_dialog_title"), self._dialog_parent(),
            Gtk.FileChooserAction.SAVE, _("folder_picker.select"), _("folder_picker.cancel"),
        )
        dialog.set_current_name("profil.json")
        json_filter = Gtk.FileFilter()
        json_filter.set_name("JSON")
        json_filter.add_pattern("*.json")
        dialog.add_filter(json_filter)

        def on_response(dlg, response):
            if response == Gtk.ResponseType.ACCEPT:
                gfile = dlg.get_file()
                path = gfile.get_path() if gfile else None
                if path:
                    if not path.lower().endswith(".json"):
                        path += ".json"
                    try:
                        save_profile(self._profile_from_widgets(), path)
                        self._adv_notify(_("adv.profile_saved", path=path))
                    except OSError as e:
                        self._adv_notify(_("adv.profile_save_error", error=e))
            dlg.destroy()
            self._active_file_dialog = None

        self._active_file_dialog = dialog
        dialog.connect("response", on_response)
        dialog.show()

    def _on_load_profile_clicked(self, button):
        dialog = Gtk.FileChooserNative.new(
            _("adv.load_profile_dialog_title"), self._dialog_parent(),
            Gtk.FileChooserAction.OPEN, _("folder_picker.select"), _("folder_picker.cancel"),
        )
        json_filter = Gtk.FileFilter()
        json_filter.set_name("JSON")
        json_filter.add_pattern("*.json")
        dialog.add_filter(json_filter)

        def on_response(dlg, response):
            if response == Gtk.ResponseType.ACCEPT:
                gfile = dlg.get_file()
                path = gfile.get_path() if gfile else None
                if path:
                    # load_profile() ne lève jamais d'exception (voir
                    # presentation/profile.py) : un fichier invalide
                    # retombe silencieusement sur les valeurs par défaut.
                    profile = load_profile(path)
                    self._apply_profile_to_widgets(profile)
                    self._adv_notify(_("adv.profile_loaded", path=path))
            dlg.destroy()
            self._active_file_dialog = None

        self._active_file_dialog = dialog
        dialog.connect("response", on_response)
        dialog.show()

    # ====================== APERÇU DE LA PLANCHE (CAHIER DES CHARGES §3) ======================
    # Un VRAI aperçu : réutilise le même moteur (ContactSheetGenerator,
    # portfolio/presentation/) que la génération finale - mais dans un
    # SOUS-PROCESSUS CLI séparé (portfolio.py --preview-output), exactement
    # comme la génération réelle (_on_generate ci-dessous), plutôt que dans
    # un thread d'arrière-plan interne à cette application GTK.
    #
    # Ce n'est pas qu'une question de cohérence architecturale : un premier
    # essai avec ContactSheetGenerator appelé directement depuis un thread
    # de cette appli a révélé, à l'usage (tests sous GTK4 réel), un bug de
    # concurrence réel et reproductible. Le rendu du titre/numéro de page
    # (texte dessiné par Pillow - voir
    # ContactSheetGenerator._draw_header()/_draw_page_number()) utilise
    # FreeType, tout comme Pango pour l'affichage des widgets de la boucle
    # GTK principale restée active pendant ce temps : les deux sollicitant
    # FreeType en concurrence (threads différents, même processus), son
    # initialisation interne peut être corrompue et produire un masque de
    # glyphe de taille aberrante - jusqu'à faire échouer le rendu avec une
    # PIL.Image.DecompressionBombError (reproduit à plusieurs reprises,
    # avec des tailles de masque différentes à chaque fois - signature
    # typique d'une véritable concurrence, pas d'un problème déterministe).
    # Un sous-processus séparé, sans fenêtre ni boucle GTK, élimine cette
    # concurrence structurellement plutôt que de tenter de la fiabiliser
    # (verrou, pré-chauffage de FreeType - essayé, insuffisant : la
    # corruption peut survenir sur n'importe quel appel, pas seulement le
    # premier).
    #
    # Le sous-processus refait son propre scan du dossier d'entrée (comme
    # _on_generate le fait déjà pour la génération réelle) plutôt que de
    # réutiliser la liste déjà affichée par l'aperçu du dossier
    # (self.input_preview) : cohérent avec le reste de l'application, et
    # sans conséquence pratique (même dossier, quelques instants plus
    # tard). self.input_preview._files sert uniquement ici à un
    # retour immédiat si le dossier ne contient visiblement aucune photo,
    # avant même de lancer un sous-processus pour rien.

    def _on_preview_clicked(self, button):
        input_dir = self.input_entry.get_text().strip()
        if not input_dir or not Path(input_dir).is_dir():
            self._adv_notify(_("gen.select_input_first"))
            return

        if not self.input_preview._files:
            self._show_no_viewer_dialog(_("adv.preview_title"), _("adv.preview_no_photos"))
            return

        num_per_sheet = int(self.num_combo.get_selected_item().get_string())
        page_format = self.format_combo.get_selected_item().get_string()
        title = self.project_title_entry.get_text().strip() or None
        author = self.author_entry.get_text().strip() or None
        watermark = self.watermark_entry.get_text().strip() or None
        orientation = self._orient_values[self.watermark_orient_combo.get_selected()]
        opacity = int(self.watermark_opacity_scale.get_value())
        advanced_profile = self._profile_from_widgets()

        # Nombre de photos effectivement affichées sur cette planche
        # (le modèle "large_thumbs" peut le réduire - voir
        # compute_effective_per_page) : uniquement pour le message affiché
        # sous l'aperçu, le sous-processus refait ce même calcul de son
        # côté pour la planche elle-même.
        config_for_count = Config(
            input_dir=Path(input_dir), output_dir=Path(input_dir),
            num_per_sheet=num_per_sheet, page_format=page_format,
            profile=advanced_profile,
        )
        shown_count = min(
            len(self.input_preview._files),
            compute_effective_per_page(config_for_count.profile),
        )

        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--run-cli"]
        else:
            cli_path = str(Path(__file__).parent / "portfolio" / "portfolio.py")
            cmd = [sys.executable, cli_path]

        fd, preview_png_path = tempfile.mkstemp(suffix=".png", prefix="planche-contact-preview-")
        os.close(fd)

        cmd += [
            "-i", input_dir,
            "-n", str(num_per_sheet),
            "--format", page_format,
            "--language", self._language,
            "--preview-output", preview_png_path,
        ]
        if title:
            cmd.extend(["--title", title])
        if author:
            cmd.extend(["--author", author])
        if watermark:
            cmd.extend(["--watermark", watermark])
            cmd.extend(["--watermark-orientation", orientation])
            cmd.extend(["--watermark-opacity", str(opacity)])
        if self.recursive_check.get_active():
            cmd.append("-r")

        profile_path = None
        if advanced_profile != default_profile():
            fd, profile_path = tempfile.mkstemp(suffix=".json", prefix="planche-contact-profile-")
            os.close(fd)
            save_profile(advanced_profile, profile_path)
            cmd.extend(["--profile", profile_path])

        dialog, picture, status_label = self._build_preview_dialog()
        dialog.present()
        status_label.set_text(_("adv.preview_generating"))

        threading.Thread(
            target=self._generate_preview,
            args=(cmd, preview_png_path, profile_path, picture, status_label, shown_count),
            daemon=True,
        ).start()

    def _build_preview_dialog(self):
        dialog = Gtk.Window(transient_for=self._dialog_parent(), modal=True)
        dialog.set_title(_("adv.preview_title"))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(14)
        box.set_margin_bottom(14)
        box.set_margin_start(14)
        box.set_margin_end(14)
        dialog.set_child(box)

        status_label = Gtk.Label(label="")
        status_label.set_xalign(0)
        status_label.add_css_class("dim-label")
        status_label.set_wrap(True)
        box.append(status_label)

        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_width(500)
        scroll.set_min_content_height(500)
        scroll.set_max_content_width(900)
        scroll.set_max_content_height(760)
        picture = Gtk.Picture()
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        scroll.set_child(picture)
        box.append(scroll)

        btn_box = Gtk.Box(spacing=10)
        btn_box.set_halign(Gtk.Align.END)
        btn_box.set_margin_top(4)
        close_btn = Gtk.Button(label=_("adv.preview_close"))
        close_btn.add_css_class("suggested-action")
        close_btn.connect("clicked", lambda b: dialog.destroy())
        btn_box.append(close_btn)
        box.append(btn_box)

        return dialog, picture, status_label

    def _generate_preview(self, cmd, preview_png_path, profile_path, picture, status_label, shown_count):
        """Exécuté en arrière-plan : lance et attend le sous-processus CLI
        (potentiellement coûteux - décodage/filigrane/dessin réels, voir
        ContactSheetGenerator) - voir le commentaire au-dessus de
        _on_preview_clicked pour la raison de cet isolement en
        sous-processus plutôt qu'un appel direct ici. Ne touche à aucun
        widget GTK directement, uniquement via glib_idle_add."""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0 or not Path(preview_png_path).is_file():
                raise RuntimeError(result.stderr.strip() or _("adv.preview_empty_result"))
            with open(preview_png_path, "rb") as f:
                data = f.read()
        except Exception as e:
            glib_idle_add(status_label.set_text, _("adv.preview_error", error=e))
            return
        finally:
            for path in (preview_png_path, profile_path):
                if path:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        glib_idle_add(self._apply_preview_image, data, picture, status_label, shown_count)

    def _apply_preview_image(self, data, picture, status_label, shown_count):
        try:
            stream = Gio.MemoryInputStream.new_from_data(data, None)
            pixbuf = GdkPixbuf.Pixbuf.new_from_stream(stream, None)
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            picture.set_paintable(texture)
        except Exception as e:
            status_label.set_text(_("adv.preview_error", error=e))
            return False
        status_label.set_text(_("adv.preview_note", count=shown_count))
        return False

    def _snap_html_per_page(self, scale):
        value = scale.get_value()
        snapped = round((value - 12) / 4) * 4 + 12
        snapped = max(12, min(64, snapped))
        if snapped != value:
            scale.set_value(snapped)

    def _reset_form(self, button):
        self.input_entry.set_text("")
        self.output_entry.set_text("")
        self.project_title_entry.set_text("")
        self.author_entry.set_text("")
        self.watermark_entry.set_text("")
        self.recursive_check.set_active(False)
        self.num_combo.set_selected(1)
        self.format_combo.set_selected(1)
        self.watermark_orient_combo.set_selected(0)
        self.watermark_opacity_scale.set_value(40)
        self.html_per_page_scale.set_value(48)
        self.pdf_check.set_active(True)
        self.html_check.set_active(True)
        self.csv_check.set_active(True)
        self._apply_profile_to_widgets(default_profile())
        self.log_buffer.set_text("")
        self.status_label.set_text("")
        self.progress.set_fraction(0.0)
        self._last_result = None
        self.view_results_btn.set_sensitive(False)

    def _choose_folder(self, button, entry, folder_type):
        """Sélecteur de dossier personnalisé, avec aperçu des vignettes.

        Entièrement construit "maison" : une première version s'appuyait
        sur Gtk.FileChooserWidget avec un filtre pour masquer les fichiers,
        mais ce filtre s'est avéré peu fiable selon les systèmes (fichiers
        toujours visibles chez certains utilisateurs malgré le filtre). On
        liste donc nous-mêmes le contenu des dossiers via Gio
        (Gtk.DirectoryList + Gtk.FilterListModel + Gtk.CustomFilter), ce qui
        garantit un résultat fiable et identique sur toute machine : le
        filtrage "dossiers uniquement" est fait par notre propre code
        Python, pas par un mécanisme interne de GTK qu'on ne contrôle pas.
        """
        dialog = Gtk.Window(transient_for=self.win, modal=True)
        dialog.set_title(
            _("folder_picker.title_input") if folder_type == "input"
            else _("folder_picker.title_output")
        )
        dialog.set_default_size(1150, 750)

        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        dialog.set_child(root_box)

        # --- Fil d'Ariane (chemin courant, cliquable par segment) ----------
        breadcrumb_box = Gtk.Box(spacing=2)
        breadcrumb_scroll = Gtk.ScrolledWindow()
        breadcrumb_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        breadcrumb_scroll.set_child(breadcrumb_box)
        breadcrumb_scroll.set_margin_top(8)
        breadcrumb_scroll.set_margin_start(10)
        breadcrumb_scroll.set_margin_end(10)
        breadcrumb_scroll.set_margin_bottom(4)
        root_box.append(breadcrumb_scroll)

        # --- Saisie directe d'un chemin --------------------------------------
        # Utile en particulier pour les partages réseau (ex: \\serveur\partage)
        # qui n'apparaissent pas forcément dans la barre latérale ou dont la
        # lettre de lecteur n'est pas mappée en permanence.
        path_entry_box = Gtk.Box(spacing=6)
        path_entry_box.set_margin_start(10)
        path_entry_box.set_margin_end(10)
        path_entry_box.set_margin_bottom(6)
        path_entry = Gtk.Entry()
        path_entry.set_hexpand(True)
        path_entry.set_placeholder_text(_("folder_picker.path_placeholder"))
        path_go_btn = Gtk.Button(label=_("folder_picker.go"))
        path_entry_box.append(path_entry)
        path_entry_box.append(path_go_btn)
        root_box.append(path_entry_box)

        # --- Corps principal : barre latérale + liste de dossiers ----------
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        body.set_vexpand(True)
        root_box.append(body)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        sidebar.set_margin_top(6)
        sidebar.set_margin_start(6)
        sidebar.set_margin_end(6)
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_child(sidebar)
        sidebar_scroll.set_size_request(190, -1)
        body.append(sidebar_scroll)

        # Liste des dossiers du répertoire courant : Gtk.DirectoryList liste
        # tout le contenu (fichiers compris), Gtk.FilterListModel + notre
        # propre fonction de filtre ne garde que les sous-dossiers visibles.
        dir_list = Gtk.DirectoryList()
        dir_list.set_attributes("standard::name,standard::type,standard::is-hidden")

        def only_visible_folders(file_info):
            try:
                return (file_info.get_file_type() == Gio.FileType.DIRECTORY
                        and not file_info.get_is_hidden())
            except Exception:
                return False

        dir_filter = Gtk.CustomFilter.new(only_visible_folders)
        filtered_model = Gtk.FilterListModel(model=dir_list, filter=dir_filter)

        def compare_names(*args):
            # Sur certaines plateformes/liaisons, le comparateur peut être
            # invoqué avec des arguments supplémentaires (observé sous
            # Windows : un argument numérique en plus des deux éléments à
            # comparer) - on ne garde donc que les arguments qui
            # ressemblent réellement à des Gio.FileInfo (qui exposent
            # get_name()), plutôt que de supposer un ordre positionnel fixe.
            items = [x for x in args if hasattr(x, "get_name")]
            if len(items) < 2:
                return 0
            na, nb = items[0].get_name().lower(), items[1].get_name().lower()
            if na < nb:
                return -1
            if na > nb:
                return 1
            return 0

        sorter = Gtk.CustomSorter.new(compare_names)
        sorted_model = Gtk.SortListModel(model=filtered_model, sorter=sorter)
        selection_model = Gtk.SingleSelection(model=sorted_model)
        selection_model.set_autoselect(False)

        factory = Gtk.SignalListItemFactory()

        def on_factory_setup(factory, list_item):
            row = Gtk.Box(spacing=8)
            row.set_margin_top(4)
            row.set_margin_bottom(4)
            row.set_margin_start(6)
            row.append(Gtk.Image.new_from_icon_name("folder-symbolic"))
            row.append(Gtk.Label(xalign=0))
            list_item.set_child(row)

        def on_factory_bind(factory, list_item):
            row = list_item.get_child()
            label = row.get_last_child()
            label.set_text(list_item.get_item().get_name())

        factory.connect("setup", on_factory_setup)
        factory.connect("bind", on_factory_bind)

        list_view = Gtk.ListView(model=selection_model, factory=factory)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_child(list_view)
        list_scroll.set_hexpand(True)
        list_scroll.set_vexpand(True)
        body.append(list_scroll)

        # --- Panneau d'aperçu (identique à celui de la fenêtre principale,
        # mais 2 lignes de 10 vignettes au lieu d'une) ----------------------
        preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        preview_box.set_margin_top(8)
        preview_box.set_margin_start(12)
        preview_box.set_margin_end(12)
        preview_box.set_margin_bottom(4)

        status_label = Gtk.Label(label=_("preview.hint"))
        status_label.set_xalign(0)
        status_label.add_css_class("dim-label")
        preview_box.append(status_label)

        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_min_children_per_line(10)
        flow.set_max_children_per_line(10)
        flow.set_row_spacing(8)
        flow.set_column_spacing(8)
        flow_scroll = Gtk.ScrolledWindow()
        flow_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        flow_scroll.set_min_content_height(2 * PREVIEW_THUMB_SIZE + 24)
        flow_scroll.set_max_content_height(2 * PREVIEW_THUMB_SIZE + 24)
        flow_scroll.set_child(flow)
        preview_box.append(flow_scroll)

        nav_box = Gtk.Box(spacing=6)
        nav_box.set_halign(Gtk.Align.CENTER)
        prev_btn = Gtk.Button(label=_("preview.prev"))
        prev_btn.set_sensitive(False)
        pages_box = Gtk.Box(spacing=4)
        next_btn = Gtk.Button(label=_("preview.next"))
        next_btn.set_sensitive(False)
        nav_box.append(prev_btn)
        nav_box.append(pages_box)
        nav_box.append(next_btn)
        preview_box.append(nav_box)

        root_box.append(preview_box)

        preview = FolderPreviewController(
            status_label, flow, prev_btn, next_btn, pages_box,
            page_size=DIALOG_PREVIEW_PAGE_SIZE
        )

        # --- Boutons d'action ------------------------------------------------
        btn_box = Gtk.Box(spacing=10)
        btn_box.set_halign(Gtk.Align.END)
        btn_box.set_margin_top(8)
        btn_box.set_margin_bottom(10)
        btn_box.set_margin_end(12)
        cancel_btn = Gtk.Button(label=_("folder_picker.cancel"))
        select_btn = Gtk.Button(label=_("folder_picker.select"))
        select_btn.add_css_class("suggested-action")
        btn_box.append(cancel_btn)
        btn_box.append(select_btn)
        root_box.append(btn_box)

        # --- Navigation --------------------------------------------------------
        state = {"current": None}

        def build_breadcrumb(path):
            child = breadcrumb_box.get_first_child()
            while child is not None:
                next_child = child.get_next_sibling()
                breadcrumb_box.remove(child)
                child = next_child

            parts = Path(path).parts
            accum = ""
            for i, part in enumerate(parts):
                accum = part if i == 0 else str(Path(accum) / part)
                label_text = part if part != "/" else "/"
                seg_btn = Gtk.Button(label=label_text)
                seg_btn.add_css_class("flat")
                seg_btn.connect("clicked", lambda b, p=accum: navigate_to(p))
                breadcrumb_box.append(seg_btn)
                if i < len(parts) - 1:
                    sep = Gtk.Label(label="›")
                    sep.add_css_class("dim-label")
                    breadcrumb_box.append(sep)

        def navigate_to(path):
            if not path or not Path(path).is_dir():
                return
            state["current"] = path
            dir_list.set_file(Gio.File.new_for_path(path))
            build_breadcrumb(path)
            preview.refresh(path)

        def on_path_entry_activate(entry_widget):
            typed = entry_widget.get_text().strip()
            if typed and Path(typed).is_dir():
                navigate_to(typed)
            else:
                # Chemin invalide/inaccessible : retour visuel temporaire.
                entry_widget.add_css_class("error")
                GLib.timeout_add(
                    1500,
                    lambda: (entry_widget.remove_css_class("error"), False)[1]
                )

        path_entry.connect("activate", on_path_entry_activate)
        path_go_btn.connect("clicked", lambda b: on_path_entry_activate(path_entry))

        def on_row_activated(list_view, position):
            file_info = selection_model.get_item(position)
            if file_info is None:
                return
            navigate_to(str(Path(state["current"]) / file_info.get_name()))

        list_view.connect("activate", on_row_activated)

        # --- Barre latérale : dossier personnel + signets GTK existants ----
        def add_sidebar_button(label_text, path, icon_name="folder-symbolic"):
            btn = Gtk.Button()
            btn.add_css_class("flat")
            content = Gtk.Box(spacing=8)
            content.append(Gtk.Image.new_from_icon_name(icon_name))
            content.append(Gtk.Label(label=label_text, xalign=0))
            btn.set_child(content)
            btn.connect("clicked", lambda b, p=path: navigate_to(p))
            sidebar.append(btn)

        home_path = str(Path.home())
        add_sidebar_button(_("folder_picker.home"), home_path, "user-home-symbolic")

        # "Ce PC" : lettres de lecteur disponibles sous Windows (disques
        # locaux ET lecteurs réseau mappés - os.listdrives() ne fait pas la
        # différence, il liste tout ce qui a une lettre assignée). Sans
        # effet sur Linux/macOS, où cette fonction n'existe pas.
        if hasattr(os, "listdrives"):
            try:
                drives = os.listdrives()
            except OSError:
                drives = []
            if drives:
                sep_label = Gtk.Label(label=_("folder_picker.this_pc"))
                sep_label.add_css_class("dim-label")
                sep_label.set_xalign(0)
                sep_label.set_margin_top(10)
                sidebar.append(sep_label)
                for drive in drives:
                    if Path(drive).is_dir():
                        add_sidebar_button(drive, drive, "drive-harddisk-symbolic")

        # Réutilise les signets GTK existants de l'utilisateur (partagés
        # avec Nautilus et les autres applis GTK), s'il y en a.
        bookmarks_file = Path.home() / ".config" / "gtk-3.0" / "bookmarks"
        if bookmarks_file.is_file():
            try:
                for line in bookmarks_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    uri, _sep, label = line.partition(" ")
                    bpath = Gio.File.new_for_uri(uri).get_path()
                    if bpath and Path(bpath).is_dir():
                        add_sidebar_button(label or Path(bpath).name, bpath)
            except Exception:
                pass  # Signets illisibles : pas bloquant, on continue sans.

        # --- Dossier de départ -------------------------------------------------
        start_path = entry.get_text().strip()
        if not (start_path and Path(start_path).is_dir()):
            start_path = home_path
        navigate_to(start_path)

        def on_cancel(b):
            dialog.destroy()

        def on_select(b):
            if state["current"]:
                entry.set_text(state["current"])
                if folder_type == "input":
                    self.last_input_dir = state["current"]
                else:
                    self.last_output_dir = state["current"]
                self.save_settings()
            dialog.destroy()

        cancel_btn.connect("clicked", on_cancel)
        select_btn.connect("clicked", on_select)

        dialog.present()

    # ====================== APERÇU DU DOSSIER D'ENTRÉE ======================

    def _on_input_entry_changed(self, entry):
        # Anti-rebond : on évite de relancer un scan à chaque frappe.
        if self._preview_debounce_id is not None:
            GLib.source_remove(self._preview_debounce_id)
        self._preview_debounce_id = GLib.timeout_add(
            400, self._debounced_preview_refresh, entry.get_text().strip()
        )

    def _debounced_preview_refresh(self, path):
        self._preview_debounce_id = None
        self.input_preview.refresh(path)
        return False

    def _on_output_entry_changed(self, entry):
        # Anti-rebond, même logique que pour le dossier d'entrée : évite de
        # scanner le disque à chaque frappe.
        if self._output_debounce_id is not None:
            GLib.source_remove(self._output_debounce_id)
        self._output_debounce_id = GLib.timeout_add(
            400, self._debounced_output_check, entry.get_text().strip()
        )

    def _debounced_output_check(self, path):
        self._output_debounce_id = None
        self._check_existing_results(path)
        return False

    def _check_existing_results(self, output_dir_str):
        """Active "Afficher les résultats" pour ce qui existe déjà dans le
        dossier de sortie choisi (planches, PDF, galerie HTML, CSV d'une
        génération précédente), sans obliger à relancer une génération
        juste pour rouvrir des résultats déjà là. Appelé au changement du
        champ dossier de sortie (saisie ou sélecteur), au démarrage si un
        dossier était mémorisé, et après une génération réussie."""
        output_dir = Path(output_dir_str) if output_dir_str else None
        if not output_dir or not output_dir.is_dir():
            self._last_result = None
            self.view_planches_btn.set_sensitive(False)
            self.view_pdf_btn.set_sensitive(False)
            self.view_gallery_btn.set_sensitive(False)
            self.view_csv_btn.set_sensitive(False)
            self.view_results_btn.set_sensitive(False)
            return

        planches_dir = output_dir / "planches"
        has_planches = planches_dir.is_dir() and any(planches_dir.iterdir())

        pdf_path = output_dir / "portfolio.pdf"
        has_pdf = pdf_path.is_file()

        gallery_index = output_dir / "gallery" / "index.html"
        has_gallery = gallery_index.is_file()

        csv_path = output_dir / "index.csv"
        has_csv = csv_path.is_file()

        self._last_result = {"output_dir": output_dir}
        self.view_planches_btn.set_sensitive(has_planches)
        self.view_pdf_btn.set_sensitive(has_pdf)
        self.view_gallery_btn.set_sensitive(has_gallery)
        self.view_csv_btn.set_sensitive(has_csv)
        self.view_results_btn.set_sensitive(has_planches or has_pdf or has_gallery or has_csv)

    def _on_generate(self, button):
        input_dir = self.input_entry.get_text().strip()
        if not input_dir:
            self._log(_("gen.select_input_first"))
            return

        output_dir = self.output_entry.get_text().strip() or str(Path(input_dir) / "Portfolio")
        self.last_input_dir = input_dir
        self.last_output_dir = output_dir
        self.save_settings()

        num_per_sheet = int(self.num_combo.get_selected_item().get_string())
        page_format = self.format_combo.get_selected_item().get_string()
        title = self.project_title_entry.get_text().strip() or None
        author = self.author_entry.get_text().strip() or None
        watermark = self.watermark_entry.get_text().strip() or None
        # Valeur française interne (voir portfolio/config.py), pas le texte
        # traduit affiché dans le menu déroulant - self._orient_values est
        # rempli dans le même ordre que les options du menu.
        orientation = self._orient_values[self.watermark_orient_combo.get_selected()]
        opacity = int(self.watermark_opacity_scale.get_value())
        html_per_page = int(self.html_per_page_scale.get_value())

        if getattr(sys, "frozen", False):
            # Exécutable gelé (PyInstaller, build Windows) : sys.executable
            # pointe vers l'application elle-même (planche-contact-gtk.exe),
            # pas vers un interpréteur Python générique capable d'exécuter
            # un script portfolio.py séparé. On relance donc ce même exe
            # avec un indicateur spécial (--run-cli), intercepté tout en
            # bas de ce fichier pour déléguer directement à la logique CLI
            # de portfolio.py, sans jamais instancier l'application GTK.
            cmd = [sys.executable, "--run-cli"]
        else:
            # Exécution depuis les sources : sys.executable est un vrai
            # interpréteur Python, auquel on passe le script CLI à exécuter.
            cli_path = str(Path(__file__).parent / "portfolio" / "portfolio.py")
            cmd = [sys.executable, cli_path]

        cmd += [
            "-i", input_dir,
            "-o", output_dir,
            "-n", str(num_per_sheet),
            "--format", page_format,
            "--html-per-page", str(html_per_page),
            # Langue déjà résolue (voir __init__ : plus jamais "system" à ce
            # stade) - garantit que la galerie HTML générée correspond
            # toujours à la langue affichée dans l'interface, plutôt que de
            # laisser le CLI redétecter indépendamment la langue système.
            "--language", self._language
        ]

        if title:
            cmd.extend(["--title", title])
        if author:
            cmd.extend(["--author", author])
        if watermark:
            cmd.extend(["--watermark", watermark])
            cmd.extend(["--watermark-orientation", orientation])
            cmd.extend(["--watermark-opacity", str(opacity)])
        if self.recursive_check.get_active():
            cmd.append("-r")
        if self.pdf_check.get_active():
            cmd.append("--pdf")
        if self.html_check.get_active():
            cmd.append("--html")
        if self.csv_check.get_active():
            cmd.append("--csv")

        # Mise en page/légendes/thème avancés (cahier des charges §2/§4.4) :
        # --profile n'est transmis que si l'utilisateur a réellement
        # personnalisé quelque chose, pour ne jamais changer le
        # comportement par défaut (voir Config.__post_init__, déjà
        # strictement rétrocompatible sans profil explicite).
        advanced_profile = self._profile_from_widgets()
        if advanced_profile != default_profile():
            fd, profile_path = tempfile.mkstemp(suffix=".json", prefix="planche-contact-profile-")
            os.close(fd)
            save_profile(advanced_profile, profile_path)
            cmd.extend(["--profile", profile_path])

        self._log(_("gen.starting"))
        self.run_button.set_sensitive(False)
        self.view_results_btn.set_sensitive(False)
        self.progress.set_fraction(0.0)
        self.status_label.set_text(_("gen.running"))

        # Mémorise le dossier de sortie de CETTE génération (indépendamment
        # du champ, qui pourrait être modifié par l'utilisateur avant la
        # fin du traitement) : sert à vérifier ce qui existe réellement une
        # fois terminé (voir _on_generation_success/_check_existing_results).
        self._pending_result = {
            "output_dir": Path(output_dir),
        }

        threading.Thread(target=self._run_cli, args=(cmd,), daemon=True).start()

    def _run_cli(self, cmd):
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            for line in process.stdout:
                line = line.strip()
                if line:
                    glib_idle_add(self._log, line)
                    glib_idle_add(self.status_label.set_text, line)

                    # Le calcul de progression repose uniquement sur le
                    # marqueur "PROGRESS:X/100", volontairement jamais
                    # traduit (voir portfolio/portfolio.py) : ne dépend
                    # d'aucun texte humain, donc valable dans toutes les
                    # langues de l'interface.
                    progress_match = re.search(r"PROGRESS:(\d+)/100", line)
                    if progress_match:
                        fraction = int(progress_match.group(1)) / 100.0
                        glib_idle_add(self.progress.set_fraction, fraction)
                        continue

            process.wait()

            if process.returncode == 0:
                glib_idle_add(self._log, _("gen.success_log"))
                glib_idle_add(self.status_label.set_text, _("gen.success_status"))
                glib_idle_add(self.progress.set_fraction, 1.0)
                glib_idle_add(self._on_generation_success)
            else:
                glib_idle_add(self._log, _("gen.error_log_code", code=process.returncode))
                glib_idle_add(self.status_label.set_text, _("gen.error_status"))
        except Exception as e:
            glib_idle_add(self._log, _("gen.error_log_exception", error=e))
            glib_idle_add(self.status_label.set_text, _("gen.error_status_generic"))
        finally:
            glib_idle_add(self.run_button.set_sensitive, True)

    def _log(self, message):
        text = message + "\n"
        end_iter = self.log_buffer.get_end_iter()
        try:
            self.log_buffer.insert(end_iter, text)
        except TypeError:
            # Repli sur la signature C brute (buffer, iter, texte, longueur)
            # si le module de surcharge Python de Gtk n'est pas charge -
            # voir le commentaire dans windows/planche-contact.spec.
            self.log_buffer.insert(end_iter, text, -1)
        mark = self.log_buffer.get_insert()
        self.log_view.scroll_mark_onscreen(mark)

    # ====================== AFFICHAGE DES RÉSULTATS ======================
    # Ouvre les résultats (planches, PDF, galerie) avec les applications par
    # défaut du système (visionneuse d'images/gestionnaire de fichiers,
    # lecteur PDF, navigateur web) plutôt que dans un aperçu intégré : la
    # fenêtre principale ne s'agrandit donc jamais pour ça.

    def _on_generation_success(self):
        output_dir = self._pending_result["output_dir"]
        self._pending_result = None
        self._check_existing_results(str(output_dir))
        return False

    def _show_no_viewer_dialog(self, message, detail):
        dialog = Gtk.AlertDialog()
        dialog.set_modal(True)
        dialog.set_message(message)
        dialog.set_detail(detail)
        dialog.set_buttons(["OK"])
        dialog.show(self._dialog_parent())

    def _open_path_with_default_app(self, path: Path) -> bool:
        """Ouvre un fichier avec l'application par défaut du système
        d'exploitation. Sous Windows, os.startfile() est l'API native pour
        ça (aucune dépendance supplémentaire) ; sous Linux/macOS, on utilise
        Gio.AppInfo. Retourne True en cas de succès, False sinon (à charge
        de l'appelant d'afficher un message adapté)."""
        if sys.platform == "win32":
            try:
                os.startfile(str(path))  # nosec - ouverture normale de fichier
                return True
            except OSError:
                return False
        else:
            try:
                uri = Gio.File.new_for_path(str(path)).get_uri()
                Gio.AppInfo.launch_default_for_uri(uri, None)
                return True
            except Exception:
                return False

    def _open_planches(self):
        if not self._last_result:
            return
        planches_dir = self._last_result["output_dir"] / "planches"
        if not planches_dir.is_dir():
            return

        # Ouvre le DOSSIER des planches (gestionnaire de fichiers), pas une
        # planche individuelle : contrairement à une visionneuse d'images
        # unique, ça fonctionne de façon identique quel que soit le nombre
        # de planches, et laisse l'utilisateur choisir laquelle regarder -
        # même mécanisme que pour le PDF/la galerie/le CSV, appliqué ici à
        # un dossier plutôt qu'à un fichier.
        if not self._open_path_with_default_app(planches_dir):
            self._show_no_viewer_dialog(
                _("dialog.no_file_manager_title"),
                _("dialog.no_file_manager_detail")
            )

    def _open_pdf(self):
        if not self._last_result:
            return
        pdf_path = self._last_result["output_dir"] / "portfolio.pdf"
        if not pdf_path.is_file():
            return
        if not self._open_path_with_default_app(pdf_path):
            self._show_no_viewer_dialog(
                _("dialog.no_pdf_viewer_title"),
                _("dialog.no_pdf_viewer_detail")
            )

    def _open_gallery(self):
        if not self._last_result:
            return
        gallery_index = self._last_result["output_dir"] / "gallery" / "index.html"
        if not gallery_index.is_file():
            return
        # Gio.AppInfo / os.startfile (comme pour le PDF/CSV) plutôt que le
        # module webbrowser de Python : ce dernier ne remonte pas fidèlement
        # un échec (il lance xdg-open en arrière-plan et considère souvent
        # l'opération réussie même si aucun navigateur n'a en réalité pu
        # être trouvé).
        if not self._open_path_with_default_app(gallery_index):
            self._show_no_viewer_dialog(
                _("dialog.no_browser_title"),
                _("dialog.no_browser_detail")
            )

    def _open_csv(self):
        if not self._last_result:
            return
        csv_path = self._last_result["output_dir"] / "index.csv"
        if not csv_path.is_file():
            return
        if not self._open_path_with_default_app(csv_path):
            self._show_no_viewer_dialog(
                _("dialog.no_csv_app_title"),
                _("dialog.no_csv_app_detail")
            )

    # ====================== AIDE ======================

    def _open_full_manual(self, button):
        docs_dir = Path(__file__).parent / "docs"
        # Une version distincte par langue (pas de bascule JS interne au
        # fichier, comme pour la galerie HTML générée) : plus simple à
        # maintenir pour un document de référence statique. Repli sur le
        # français si le fichier de la langue active n'existe pas (ne
        # devrait arriver que pour "system" avec une langue non couverte,
        # déjà gérée par ailleurs - voir portfolio/i18n.py).
        lang = get_language()
        candidate = docs_dir / f"planche-contact-manual.{lang}.html" if lang != "fr" else docs_dir / "planche-contact-manual.html"
        manual_path = candidate if candidate.exists() else docs_dir / "planche-contact-manual.html"

        if manual_path.exists():
            webbrowser.open(f'file://{manual_path.resolve()}')
        else:
            html_content = self._get_full_manual_html()
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
                f.write(html_content)
                webbrowser.open(f'file://{f.name}')

    def _get_full_manual_html(self):
        return """<!DOCTYPE html>
<html><body><h1>Planche-Contact</h1>
<p>Le manuel détaillé se trouve dans <code>docs/planche-contact-manual.html</code>.</p>
</body></html>"""

    def _build_help_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        box.set_margin_top(20)
        box.set_margin_start(30)
        box.set_margin_end(30)

        title = Gtk.Label()
        title.set_markup(f"<big><b>{_('help.title')}</b></big>")
        box.append(title)

        info = Gtk.Label()
        info.set_text(_("help.description"))
        info.set_wrap(True)
        box.append(info)

        button = Gtk.Button(label=_("help.open_manual"))
        button.connect("clicked", self._open_full_manual)
        box.append(button)

        return box

    # ====================== À PROPOS ======================

    def _build_about_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(40)
        box.set_margin_start(30)
        box.set_margin_end(30)

        # Titre
        title = Gtk.Label()
        title.set_markup("<span size='large'><b>Planche-Contact</b></span>")
        box.append(title)

        # Version + date de build
        version_text = self._get_version_info()
        version_label = Gtk.Label()
        version_label.set_markup(f"<span size='medium'>{version_text}</span>")
        version_label.set_margin_top(10)
        box.append(version_label)

        # Description
        desc = Gtk.Label()
        desc.set_markup(f"<span size='small'>{_('about.tagline')}</span>")
        desc.set_justify(Gtk.Justification.CENTER)
        desc.set_margin_top(20)
        box.append(desc)

        # Auteur
        author = Gtk.Label()
        author.set_markup(f"<span size='small'>{_('about.developed_by', name='Gilles MAGNEVILLE')}</span>")
        author.set_margin_top(25)
        box.append(author)

        # Mention transparente de l'assistance IA à la conception
        ai_credit = Gtk.Label()
        ai_credit.set_markup(
            f"<span size='small'>{_('about.ai_credit', link='<a href=\"https://claude.ai\">Claude.ai</a>')}</span>"
        )
        ai_credit.set_margin_top(4)
        box.append(ai_credit)

        # Licence
        license_label = Gtk.Label()
        license_label.set_markup(f"<span size='small'>{_('about.license')}</span>")
        license_label.set_margin_top(10)
        box.append(license_label)

        # Dépôt GitHub (lien cliquable, ouvre le navigateur par défaut)
        github_label = Gtk.Label()
        github_label.set_markup(
            '<span size="small">'
            '<a href="https://github.com/gillesmagneville/planche-contact">'
            'github.com/gillesmagneville/planche-contact</a>'
            '</span>'
        )
        github_label.set_margin_top(4)
        box.append(github_label)

        return box

    def _on_language_changed(self, dropdown, _param):
        new_preference = AVAILABLE_LANGUAGES[dropdown.get_selected()]
        if new_preference == self.language_preference:
            return
        self.language_preference = new_preference
        self.save_settings()
        self.language_restart_label.set_visible(True)
        # Les widgets déjà construits ne changent pas de texte sans
        # redémarrer (voir le message ci-dessus), mais self._language doit
        # être mis à jour immédiatement : c'est elle qui est transmise au
        # CLI via --language dans _on_generate(), et une génération lancée
        # avant un redémarrage doit refléter le choix qui vient d'être
        # fait, pas la langue active au démarrage de l'application.
        self._language, _unsupported = set_language(new_preference)

    def _get_version_info(self):
        """Récupère le numéro de version et la date de build"""
        version = "inconnue"
        build_date = ""

        possible_paths = [
            Path(__file__).parent / "VERSION",
            Path(__file__).parent.parent / "VERSION",
            Path("/usr/share/planche-contact/VERSION"),
        ]

        version_file = None
        for p in possible_paths:
            if p.exists():
                version_file = p
                break

        if version_file:
            try:
                version = version_file.read_text().strip()
                mtime = version_file.stat().st_mtime
                build_date = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y")
            except Exception:
                pass

        if build_date:
            return _("about.version_build", version=version, date=build_date)
        else:
            return _("about.version_only", version=version)


if __name__ == "__main__":
    # multiprocessing.freeze_support() est désormais appelé bien plus tôt,
    # tout en haut du fichier (avant même `import gi`) - voir le
    # commentaire à cet endroit. Rien à refaire ici.

    if len(sys.argv) > 1 and sys.argv[1] == "--run-cli":
        # Relance de l'exécutable gelé lui-même en mode CLI (voir
        # _on_generate ci-dessus, nécessaire car sys.executable pointe vers
        # cette même application dans un exécutable gelé PyInstaller, pas
        # vers un interpréteur Python générique). On délègue directement au
        # point d'entrée CLI de portfolio.py, sans jamais instancier
        # l'application GTK.
        from portfolio.portfolio import main as portfolio_cli_main
        sys.argv = [sys.argv[0]] + sys.argv[2:]  # retire "--run-cli" avant argparse
        portfolio_cli_main()
    else:
        app = PlancheContactGTK()
        app.run(sys.argv)
