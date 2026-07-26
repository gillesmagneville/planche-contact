#!/usr/bin/env python3
"""
Planche-Contact GTK - Interface Graphique
"""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gio, Gdk, GdkPixbuf

import sys
import subprocess
import threading
import json
import re
import io
import webbrowser
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from portfolio.config import Config
from portfolio.scanner import ImageScanner
from portfolio.rawloader import load_image

PREVIEW_PAGE_SIZE = 10
PREVIEW_THUMB_SIZE = 90
DIALOG_PREVIEW_PAGE_SIZE = PREVIEW_PAGE_SIZE * 2  # 2 lignes de 10 dans le sélecteur de dossier


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

        self.status_label.set_text("Analyse du dossier...")
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
        GLib.idle_add(self._apply_file_list, token, image_files)

    def _apply_file_list(self, token, image_files):
        if token != self._token:
            return False  # Un scan plus récent a été lancé entre-temps.

        self._files = image_files
        self._page = 0
        self._page_cache = {}

        if not image_files:
            self.status_label.set_text("Aucune photo trouvée dans ce dossier.")
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
        self.status_label.set_text(f"Chargement des photos {start + 1}-{end} sur {total}...")

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
        GLib.idle_add(self._apply_thumbs, token, page_index, thumbs, start, end, total)

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
                f"Photos {start + 1}-{end} sur {total} ({shown} affichée(s), "
                f"certaines illisibles)"
            )
        else:
            self.status_label.set_text(f"Photos {start + 1}-{end} sur {total}")

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
        self._preview_debounce_id = None
        self.load_settings()

    def load_settings(self):
        try:
            if self.settings_path.exists():
                with open(self.settings_path, "r") as f:
                    data = json.load(f)
                    self.last_input_dir = data.get("last_input_dir", "")
                    self.last_output_dir = data.get("last_output_dir", "")
        except Exception:
            pass

    def save_settings(self):
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_input_dir": self.last_input_dir,
            "last_output_dir": self.last_output_dir
        }
        with open(self.settings_path, "w") as f:
            json.dump(data, f, indent=2)

    def do_activate(self):
        self.win = Gtk.ApplicationWindow(application=self)
        self.win.set_title("Planche-Contact")
        # 1050x750 -> +50% en largeur, nettement plus haut (marge pour les
        # informations de progression en bas de fenêtre : la zone de log
        # a maintenant une hauteur minimale garantie de 260px, voir plus bas).
        self.win.set_default_size(1575, 1050)
        self.win.set_icon_name("image-x-generic")

        notebook = Gtk.Notebook()
        self.win.set_child(notebook)

        notebook.append_page(self._build_generation_tab(), Gtk.Label(label="Génération"))
        notebook.append_page(self._build_help_tab(), Gtk.Label(label="Aide"))
        notebook.append_page(self._build_about_tab(), Gtk.Label(label="À propos"))

        self.win.present()
        # Ouverture en plein écran par défaut (la fenêtre reste
        # redimensionnable/restaurable normalement par l'utilisateur).
        # La demande de maximisation est différée d'un cycle de boucle
        # principale : certains gestionnaires de fenêtres l'ignorent si
        # elle arrive avant que la fenêtre soit pleinement réalisée par
        # present().
        GLib.idle_add(self.win.maximize)

        # Le set_text() initial du champ dossier d'entrée a lieu avant la
        # connexion du signal "changed" : on déclenche donc l'aperçu ici
        # explicitement pour un dossier déjà mémorisé au démarrage.
        if self.last_input_dir:
            self.input_preview.refresh(self.last_input_dir)

    # ====================== ONGLET GÉNÉRATION ======================

    def _build_generation_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(15)
        box.set_margin_start(25)
        box.set_margin_end(25)

        # Titre du projet + Nom de l'auteur (même ligne)
        hbox = Gtk.Box(spacing=10)
        hbox.append(Gtk.Label(label="Titre du projet :"))
        self.project_title_entry = Gtk.Entry()
        self.project_title_entry.set_hexpand(False)
        self.project_title_entry.set_halign(Gtk.Align.START)
        self.project_title_entry.set_width_chars(45)
        hbox.append(self.project_title_entry)

        author_label = Gtk.Label(label="Nom de l'auteur :")
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
        hbox.append(Gtk.Label(label="Dossier d'entrée :"))
        self.input_entry = Gtk.Entry()
        if self.last_input_dir:
            self.input_entry.set_text(self.last_input_dir)
        self.input_entry.set_hexpand(False)
        self.input_entry.set_halign(Gtk.Align.START)
        self.input_entry.set_width_chars(68)
        self.input_entry.connect("changed", self._on_input_entry_changed)
        btn = Gtk.Button(label="Choisir...")
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
        preview_scroll.set_child(self.input_preview_flow)
        box.append(preview_scroll)

        preview_nav = Gtk.Box(spacing=6)
        preview_nav.set_halign(Gtk.Align.CENTER)
        preview_nav.set_margin_top(2)
        self.preview_prev_btn = Gtk.Button(label="← Précédent")
        self.preview_prev_btn.set_sensitive(False)
        self.preview_pages_box = Gtk.Box(spacing=4)
        self.preview_next_btn = Gtk.Button(label="Suivant →")
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
        hbox.append(Gtk.Label(label="Dossier de sortie :"))
        self.output_entry = Gtk.Entry()
        if self.last_output_dir:
            self.output_entry.set_text(self.last_output_dir)
        self.output_entry.set_hexpand(False)
        self.output_entry.set_halign(Gtk.Align.START)
        self.output_entry.set_width_chars(68)
        btn = Gtk.Button(label="Choisir...")
        btn.connect("clicked", self._choose_folder, self.output_entry, "output")
        hbox.append(self.output_entry)
        hbox.append(btn)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        hbox.append(spacer)
        box.append(hbox)

        # Options
        grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        self.recursive_check = Gtk.CheckButton(label="Recherche récursive")
        grid.attach(self.recursive_check, 0, 0, 8, 1)

        grid.attach(Gtk.Label(label="Images par planche :"), 0, 1, 1, 1)
        num_model = Gtk.StringList()
        for n in range(8, 49, 4):
            num_model.append(str(n))
        self.num_combo = Gtk.DropDown(model=num_model)
        self.num_combo.set_selected(1)
        grid.attach(self.num_combo, 1, 1, 1, 1)

        format_label = Gtk.Label(label="Format de la planche :")
        format_label.set_margin_start(20)
        grid.attach(format_label, 2, 1, 1, 1)
        format_model = Gtk.StringList()
        for fmt in ["A5", "A4", "A3", "A2", "Letter"]:
            format_model.append(fmt)
        self.format_combo = Gtk.DropDown(model=format_model)
        self.format_combo.set_selected(1)
        grid.attach(self.format_combo, 3, 1, 1, 1)

        # Filigrane : sur la même ligne, pour limiter la hauteur du formulaire
        watermark_label = Gtk.Label(label="Filigrane (texte) :")
        watermark_label.set_margin_start(20)
        grid.attach(watermark_label, 4, 1, 1, 1)
        self.watermark_entry = Gtk.Entry()
        self.watermark_entry.set_hexpand(False)
        self.watermark_entry.set_halign(Gtk.Align.START)
        self.watermark_entry.set_width_chars(18)
        grid.attach(self.watermark_entry, 5, 1, 1, 1)

        orient_label = Gtk.Label(label="Orientation du filigrane :")
        orient_label.set_margin_start(20)
        grid.attach(orient_label, 6, 1, 1, 1)
        orient_model = Gtk.StringList()
        for orient in ["Horizontal", "Diagonale horaire", "Diagonale anti-horaire"]:
            orient_model.append(orient)
        self.watermark_orient_combo = Gtk.DropDown(model=orient_model)
        self.watermark_orient_combo.set_selected(0)
        grid.attach(self.watermark_orient_combo, 7, 1, 1, 1)

        self.pdf_check = Gtk.CheckButton(label="Générer PDF")
        self.html_check = Gtk.CheckButton(label="Générer Galerie HTML")
        self.csv_check = Gtk.CheckButton(label="Générer Index CSV")
        self.pdf_check.set_active(True)
        self.html_check.set_active(True)
        self.csv_check.set_active(True)

        grid.attach(self.pdf_check, 0, 2, 2, 1)
        grid.attach(self.html_check, 0, 3, 2, 1)
        grid.attach(self.csv_check, 0, 4, 2, 1)

        box.append(grid)

        # Boutons
        hbox = Gtk.Box(spacing=10)
        self.run_button = Gtk.Button(label="Lancer la génération")
        self.run_button.add_css_class("suggested-action")
        self.run_button.connect("clicked", self._on_generate)

        reset_btn = Gtk.Button(label="Réinitialiser")
        reset_btn.connect("clicked", self._reset_form)

        quit_btn = Gtk.Button(label="Quitter")
        quit_btn.connect("clicked", lambda b: self.quit())

        left_box = Gtk.Box(spacing=10)
        left_box.append(self.run_button)
        left_box.append(reset_btn)

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
        self.pdf_check.set_active(True)
        self.html_check.set_active(True)
        self.csv_check.set_active(True)
        self.log_buffer.set_text("")
        self.status_label.set_text("")
        self.progress.set_fraction(0.0)

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
            "Choisir un dossier d'entrée" if folder_type == "input"
            else "Choisir un dossier de sortie"
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

        def compare_names(a, b, *args):
            na, nb = a.get_name().lower(), b.get_name().lower()
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

        status_label = Gtk.Label(label="Naviguez pour voir un aperçu des photos.")
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
        prev_btn = Gtk.Button(label="← Précédent")
        prev_btn.set_sensitive(False)
        pages_box = Gtk.Box(spacing=4)
        next_btn = Gtk.Button(label="Suivant →")
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
        cancel_btn = Gtk.Button(label="Annuler")
        select_btn = Gtk.Button(label="Sélectionner ce dossier")
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
        add_sidebar_button("Dossier personnel", home_path, "user-home-symbolic")

        # Réutilise les signets GTK existants de l'utilisateur (partagés
        # avec Nautilus et les autres applis GTK), s'il y en a.
        bookmarks_file = Path.home() / ".config" / "gtk-3.0" / "bookmarks"
        if bookmarks_file.is_file():
            try:
                for line in bookmarks_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    uri, _, label = line.partition(" ")
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

    def _on_generate(self, button):
        input_dir = self.input_entry.get_text().strip()
        if not input_dir:
            self._log("Veuillez sélectionner un dossier d'entrée.")
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
        orientation = self.watermark_orient_combo.get_selected_item().get_string()

        cli_path = str(Path(__file__).parent / "portfolio" / "portfolio.py")

        cmd = [
            sys.executable, cli_path,
            "-i", input_dir,
            "-o", output_dir,
            "-n", str(num_per_sheet),
            "--format", page_format
        ]

        if title:
            cmd.extend(["--title", title])
        if author:
            cmd.extend(["--author", author])
        if watermark:
            cmd.extend(["--watermark", watermark])
            cmd.extend(["--watermark-orientation", orientation])
        if self.recursive_check.get_active():
            cmd.append("-r")
        if self.pdf_check.get_active():
            cmd.append("--pdf")
        if self.html_check.get_active():
            cmd.append("--html")
        if self.csv_check.get_active():
            cmd.append("--csv")

        self._log("Démarrage de la génération...")
        self.run_button.set_sensitive(False)
        self.progress.set_fraction(0.0)
        self.status_label.set_text("Génération en cours...")

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
                    GLib.idle_add(self._log, line)
                    GLib.idle_add(self.status_label.set_text, line)

                    progress_match = re.search(r"PROGRESS:(\d+)/100", line)
                    if progress_match:
                        fraction = int(progress_match.group(1)) / 100.0
                        GLib.idle_add(self.progress.set_fraction, fraction)
                        continue

                    match = re.search(r"Planche (\d+)/(\d+)", line)
                    if match:
                        current = int(match.group(1))
                        total = int(match.group(2))
                        fraction = min(0.70, 0.15 + (current / total) * 0.55)
                        GLib.idle_add(self.progress.set_fraction, fraction)

            process.wait()

            if process.returncode == 0:
                GLib.idle_add(self._log, "✅ Génération terminée avec succès !")
                GLib.idle_add(self.status_label.set_text, "Terminé avec succès")
                GLib.idle_add(self.progress.set_fraction, 1.0)
            else:
                GLib.idle_add(self._log, f"❌ Erreur (code {process.returncode})")
                GLib.idle_add(self.status_label.set_text, "Erreur pendant la génération")
        except Exception as e:
            GLib.idle_add(self._log, f"❌ Erreur : {e}")
            GLib.idle_add(self.status_label.set_text, "Erreur")
        finally:
            GLib.idle_add(self.run_button.set_sensitive, True)

    def _log(self, message):
        self.log_buffer.insert(self.log_buffer.get_end_iter(), message + "\n")
        mark = self.log_buffer.get_insert()
        self.log_view.scroll_mark_onscreen(mark)

    # ====================== AIDE ======================

    def _open_full_manual(self, button):
        manual_path = Path(__file__).parent / "docs" / "planche-contact-manual.html"

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
        title.set_markup("<big><b>Aide - Planche-Contact</b></big>")
        box.append(title)

        info = Gtk.Label()
        info.set_text("Clique sur le bouton ci-dessous pour ouvrir le manuel complet dans ton navigateur.")
        info.set_wrap(True)
        box.append(info)

        button = Gtk.Button(label="Ouvrir le manuel complet dans le navigateur")
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
        desc.set_markup(
            "<span size='small'>Générateur de planches contact photographiques\n"
            "haute qualité (300 dpi)</span>"
        )
        desc.set_justify(Gtk.Justification.CENTER)
        desc.set_margin_top(20)
        box.append(desc)

        # Auteur
        author = Gtk.Label()
        author.set_markup("<span size='small'>Développé par Gilles MAGNEVILLE</span>")
        author.set_margin_top(25)
        box.append(author)

        return box

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
            return f"Version {version}  —  Build du {build_date}"
        else:
            return f"Version {version}"


if __name__ == "__main__":
    app = PlancheContactGTK()
    app.run(sys.argv)
