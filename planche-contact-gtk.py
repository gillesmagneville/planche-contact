#!/usr/bin/env python3
"""
Planche-Contact GTK - Interface Graphique
"""
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gio

import sys
import subprocess
import threading
import json
import re
import webbrowser
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from portfolio.config import Config


class PlancheContactGTK(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.planchecontact.gtk")
        self.win = None
        self.settings_path = Path.home() / ".config" / "planche-contact" / "settings.json"
        self.last_input_dir = ""
        self.last_output_dir = ""
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
        self.win.set_default_size(1050, 750)
        self.win.set_icon_name("image-x-generic")

        notebook = Gtk.Notebook()
        self.win.set_child(notebook)

        notebook.append_page(self._build_generation_tab(), Gtk.Label(label="Génération"))
        notebook.append_page(self._build_help_tab(), Gtk.Label(label="Aide"))
        notebook.append_page(self._build_about_tab(), Gtk.Label(label="À propos"))

        self.win.present()

    # ====================== ONGLET GÉNÉRATION ======================

    def _build_generation_tab(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(15)
        box.set_margin_start(25)
        box.set_margin_end(25)

        # Titre du projet
        hbox = Gtk.Box(spacing=10)
        hbox.append(Gtk.Label(label="Titre du projet :"))
        self.project_title_entry = Gtk.Entry()
        self.project_title_entry.set_hexpand(True)
        hbox.append(self.project_title_entry)
        box.append(hbox)

        # Nom de l'auteur
        hbox = Gtk.Box(spacing=10)
        hbox.append(Gtk.Label(label="Nom de l'auteur :"))
        self.author_entry = Gtk.Entry()
        self.author_entry.set_hexpand(True)
        hbox.append(self.author_entry)
        box.append(hbox)

        # Dossier d'entrée
        hbox = Gtk.Box(spacing=10)
        hbox.append(Gtk.Label(label="Dossier d'entrée :"))
        self.input_entry = Gtk.Entry()
        if self.last_input_dir:
            self.input_entry.set_text(self.last_input_dir)
        self.input_entry.set_hexpand(True)
        btn = Gtk.Button(label="Choisir...")
        btn.connect("clicked", self._choose_folder, self.input_entry, "input")
        hbox.append(self.input_entry)
        hbox.append(btn)
        box.append(hbox)

        # Dossier de sortie
        hbox = Gtk.Box(spacing=10)
        hbox.append(Gtk.Label(label="Dossier de sortie :"))
        self.output_entry = Gtk.Entry()
        if self.last_output_dir:
            self.output_entry.set_text(self.last_output_dir)
        self.output_entry.set_hexpand(True)
        btn = Gtk.Button(label="Choisir...")
        btn.connect("clicked", self._choose_folder, self.output_entry, "output")
        hbox.append(self.output_entry)
        hbox.append(btn)
        box.append(hbox)

        # Options
        grid = Gtk.Grid(column_spacing=10, row_spacing=6)
        self.recursive_check = Gtk.CheckButton(label="Recherche récursive")
        grid.attach(self.recursive_check, 0, 0, 2, 1)

        grid.attach(Gtk.Label(label="Images par planche :"), 0, 1, 1, 1)
        num_model = Gtk.StringList()
        for n in range(8, 49, 4):
            num_model.append(str(n))
        self.num_combo = Gtk.DropDown(model=num_model)
        self.num_combo.set_selected(1)
        grid.attach(self.num_combo, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="Format de la planche :"), 0, 2, 1, 1)
        format_model = Gtk.StringList()
        for fmt in ["A5", "A4", "A3", "A2", "Letter"]:
            format_model.append(fmt)
        self.format_combo = Gtk.DropDown(model=format_model)
        self.format_combo.set_selected(1)
        grid.attach(self.format_combo, 1, 2, 1, 1)

        # Watermark
        grid.attach(Gtk.Label(label="Filigrane (texte) :"), 0, 3, 1, 1)
        self.watermark_entry = Gtk.Entry()
        grid.attach(self.watermark_entry, 1, 3, 1, 1)

        grid.attach(Gtk.Label(label="Orientation du filigrane :"), 0, 4, 1, 1)
        orient_model = Gtk.StringList()
        for orient in ["Horizontal", "Diagonale horaire", "Diagonale anti-horaire"]:
            orient_model.append(orient)
        self.watermark_orient_combo = Gtk.DropDown(model=orient_model)
        self.watermark_orient_combo.set_selected(0)
        grid.attach(self.watermark_orient_combo, 1, 4, 1, 1)

        self.pdf_check = Gtk.CheckButton(label="Générer PDF")
        self.html_check = Gtk.CheckButton(label="Générer Galerie HTML")
        self.csv_check = Gtk.CheckButton(label="Générer Index CSV")
        self.pdf_check.set_active(True)
        self.html_check.set_active(True)
        self.csv_check.set_active(True)

        grid.attach(self.pdf_check, 0, 5, 2, 1)
        grid.attach(self.html_check, 0, 6, 2, 1)
        grid.attach(self.csv_check, 0, 7, 2, 1)

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
        dialog = Gtk.FileChooserDialog(
            title="Choisir un dossier",
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        dialog.add_buttons("Annuler", Gtk.ResponseType.CANCEL, "Choisir", Gtk.ResponseType.OK)
        dialog.set_transient_for(self.win)

        if folder_type == "input" and self.last_input_dir:
            dialog.set_current_folder(Gio.File.new_for_path(self.last_input_dir))
        elif folder_type == "output" and self.last_output_dir:
            dialog.set_current_folder(Gio.File.new_for_path(self.last_output_dir))

        dialog.connect("response", self._on_folder_response, entry, folder_type)
        dialog.present()

    def _on_folder_response(self, dialog, response, entry, folder_type):
        if response == Gtk.ResponseType.OK:
            path = dialog.get_file().get_path()
            entry.set_text(path)
            if folder_type == "input":
                self.last_input_dir = path
            else:
                self.last_output_dir = path
            self.save_settings()
        dialog.destroy()

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
