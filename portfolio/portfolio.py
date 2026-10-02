#!/usr/bin/env python3
"""
portfolio.py - Générateur de planches-contact
"""

import sys
import time
import logging
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from portfolio.config import Config
from portfolio.scanner import ImageScanner
from portfolio.thumbnail import ThumbnailGenerator
from portfolio.contactsheet import ContactSheetGenerator
from portfolio.pdfexport import PDFExporter
from portfolio.htmlgallery import HTMLGalleryGenerator
from portfolio.csvindex import CSVIndexGenerator
from portfolio.utils import setup_logging
from portfolio.i18n import _, set_language, AVAILABLE_LANGUAGES
from portfolio.presentation import compute_effective_per_page, load_profile


def _pre_resolve_language():
    """Détermine la langue à utiliser pour --help et les messages du CLI,
    avant même le parsing normal des arguments : argparse construit le
    texte d'aide de chaque add_argument() immédiatement à la déclaration
    du parser, donc avant qu'on connaisse la valeur de args.language - il
    faut donc regarder sys.argv nous-mêmes en amont, pour ce seul besoin.
    """
    for i, arg in enumerate(sys.argv):
        if arg == "--language" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith("--language="):
            return arg.split("=", 1)[1]
    return "system"


def parse_args():
    import argparse

    # Résolu AVANT de construire le parser : le texte d'aide de chaque
    # add_argument() ci-dessous appelle _() en supposant la langue déjà
    # active (voir _pre_resolve_language() ci-dessus).
    language, unsupported_detected = set_language(_pre_resolve_language())
    if unsupported_detected is not None:
        print(_("lang.fallback_warning_detail", detected=unsupported_detected), file=sys.stderr)

    parser = argparse.ArgumentParser(description=_("cli.description"))

    parser.add_argument("-i", "--input", required=True, type=Path, help=_("cli.help_input"))
    parser.add_argument("-o", "--output", type=Path, help=_("cli.help_output"))
    parser.add_argument("-r", "--recursive", action="store_true", help=_("cli.help_recursive"))
    parser.add_argument("-n", "--num", type=int, default=12, help=_("cli.help_num"))
    parser.add_argument("--thumb", type=int, default=600, help=_("cli.help_thumb"))
    parser.add_argument("--format", default="A4", choices=["A5", "A4", "A3", "A2", "Letter"],
                        help=_("cli.help_format"))
    parser.add_argument("--title", default=None, help=_("cli.help_title"))
    parser.add_argument("--author", default=None, help=_("cli.help_author"))
    parser.add_argument("--sort", default="date", choices=["date", "name"], help=_("cli.help_sort"))
    parser.add_argument("--pdf", action="store_true", help=_("cli.help_pdf"))
    parser.add_argument("--html", action="store_true", help=_("cli.help_html"))
    parser.add_argument("--csv", action="store_true", help=_("cli.help_csv"))
    parser.add_argument("--html-per-page", type=int, default=48, help=_("cli.help_html_per_page"))
    parser.add_argument("--watermark", default=None, help=_("cli.help_watermark"))
    # Choix laissés en français : valeur interne comparée en dur par
    # portfolio/config.py (voir PROJECT_CONTEXT.md §5) - seul le texte
    # d'aide affiché est traduit, jamais les valeurs elles-mêmes.
    parser.add_argument("--watermark-orientation", default="Horizontal",
                        choices=["Horizontal", "Diagonale horaire", "Diagonale anti-horaire"],
                        help=_("cli.help_watermark_orientation"))
    parser.add_argument("--watermark-opacity", type=int, default=40,
                        help=_("cli.help_watermark_opacity"))
    # Déjà résolu ci-dessus (voir _pre_resolve_language) : simplement
    # déclaré ici pour qu'argparse reconnaisse l'option (utile en
    # particulier quand l'interface graphique lance ce script en
    # sous-processus avec sa propre langue déjà active - voir
    # planche-contact-gtk.py, _on_generate) et l'affiche dans --help.
    parser.add_argument("--language", default="system", choices=AVAILABLE_LANGUAGES,
                        help=_("cli.help_language"))
    # Mise en page/légendes/thème personnalisables (cahier des charges
    # §2/§4.4) : un profil JSON réutilisable, enregistré via
    # presentation.save_profile() (interface graphique, étape ultérieure)
    # ou écrit/modifié à la main. Voir la note de précédence avec
    # --format/--num ci-dessous (Config.__post_init__).
    parser.add_argument("--profile", type=Path, default=None, help=_("cli.help_profile"))

    # Mode prévisualisation (cahier des charges §3), réservé à un usage
    # interne par l'interface graphique (planche-contact-gtk.py,
    # _on_preview_clicked) : génère UNE SEULE planche (la première page,
    # avec le nombre de photos réellement affichées dessus - voir
    # compute_effective_per_page) dans ce sous-processus CLI totalement
    # séparé de l'application GTK, puis écrit le résultat en PNG au chemin
    # donné et s'arrête - sans jamais toucher au dossier de sortie réel ni
    # générer de PDF/CSV/galerie HTML. Voir _generate_preview_sheet()
    # ci-dessous pour la raison de cet isolement en sous-processus.
    parser.add_argument("--preview-output", type=Path, default=None, help=_("cli.help_preview_output"))

    return parser.parse_args()


def _generate_preview_sheet(args, profile_kwargs):
    """Génère une planche unique pour la prévisualisation (--preview-output)
    et rien d'autre - voir le commentaire de l'argument ci-dessus.

    Volontairement un chemin de code à part, indépendant du reste de
    main() : ne crée jamais le dossier de sortie réel, ne configure pas de
    logging dedans, ne nettoie/écrase rien d'une génération précédente, et
    ne produit ni PDF, ni CSV, ni galerie HTML - seulement l'image PNG de
    la planche demandée.

    Isolement en sous-processus (plutôt qu'un simple appel direct depuis
    l'interface graphique, dans un fil d'arrière-plan de l'application
    GTK) : constat empirique (tests sous GTK4 réel) qu'un rendu de texte
    Pillow (titre/numéro de page de la planche - voir
    ContactSheetGenerator._draw_header()/_draw_page_number()) exécuté en
    concurrence avec Pango - qui s'appuie, lui aussi, sur FreeType, pour
    l'affichage des widgets de la boucle GTK principale restée active -
    peut corrompre l'initialisation interne de FreeType et produire un
    masque de glyphe de taille aberrante, jusqu'à faire échouer le rendu
    (PIL.Image.DecompressionBombError). Un sous-processus séparé, sans la
    moindre fenêtre ni boucle GTK, élimine structurellement cette
    concurrence plutôt que de tenter de la fiabiliser."""
    config = Config(
        input_dir=args.input,
        # Jamais créé ni écrit : ce mode ne génère qu'un PNG autonome, au
        # chemin --preview-output fourni par l'appelant.
        output_dir=args.input,
        recursive=args.recursive,
        sort_by=args.sort,
        num_per_sheet=args.num,
        thumb_size=args.thumb,
        page_format=args.format,
        title=args.title,
        author=args.author,
        watermark_text=args.watermark,
        watermark_orientation=args.watermark_orientation,
        watermark_opacity=args.watermark_opacity,
        **profile_kwargs,
    )

    scanner = ImageScanner(config)
    images = scanner.scan()
    if not images:
        return

    n = compute_effective_per_page(config.profile)
    total_pages = (len(images) + n - 1) // n
    batch = images[:n]

    thumb_gen = ThumbnailGenerator(config)
    cs_gen = ContactSheetGenerator(config, thumb_gen)
    sheet = cs_gen.create_contact_sheet(batch, 1, total_pages)
    if sheet is not None:
        args.preview_output.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(args.preview_output, "PNG")


def main():
    args = parse_args()
    start = time.time()

    profile_kwargs = {}
    if args.profile is not None:
        profile_kwargs["profile"] = load_profile(args.profile)

    if args.preview_output is not None:
        # Mode prévisualisation : voir _generate_preview_sheet() - un
        # chemin de code totalement séparé du reste de cette fonction, qui
        # retourne avant la moindre création/modification du dossier de
        # sortie réel.
        _generate_preview_sheet(args, profile_kwargs)
        return

    output_dir = args.output or (args.input / "Portfolio")
    output_dir.mkdir(parents=True, exist_ok=True)

    setup_logging(output_dir / "generation.log")
    logger = logging.getLogger(__name__)

    logger.info(_("cli.log_starting", input=args.input))

    # Profil JSON optionnel (cahier des charges §2/§4.4, --profile) : un
    # fichier absent/illisible/invalide retombe silencieusement sur le
    # profil par défaut (voir presentation.load_profile(), jamais
    # d'exception) - aucun argument "profile=" n'est alors passé à Config
    # ci-dessous, pour laisser sa propre valeur par défaut
    # (default_profile()) s'appliquer normalement. Quand un profil EST
    # fourni, Config.__post_init__() arbitre lui-même la précédence avec
    # --format/--num quand les deux sont donnés à la fois (voir son
    # docstring pour la limite actuelle de cette heuristique) : --format/
    # --num ne l'emportent que s'ils ont été explicitement changés par
    # rapport à leur valeur par défaut ET que le profil n'a, lui, pas déjà
    # personnalisé ce même réglage. (profile_kwargs est calculé plus haut,
    # avant même l'embranchement vers le mode prévisualisation.)
    config = Config(
        input_dir=args.input,
        output_dir=output_dir,
        recursive=args.recursive,
        sort_by=args.sort,
        num_per_sheet=args.num,
        thumb_size=args.thumb,
        page_format=args.format,
        title=args.title,
        author=args.author,
        generate_pdf=args.pdf,
        generate_html=args.html,
        generate_csv=args.csv,
        html_images_per_page=args.html_per_page,
        watermark_text=args.watermark,
        watermark_orientation=args.watermark_orientation,
        watermark_opacity=args.watermark_opacity,
        **profile_kwargs,
    )

    # Phase 1: Scan
    print(f"PROGRESS:0/100 {_('cli.progress_scanning')}", flush=True)
    scanner = ImageScanner(config)
    images = scanner.scan()
    print(f"PROGRESS:10/100 {_('cli.progress_found', count=len(images))}", flush=True)

    if not images:
        logger.warning(_("cli.log_no_images"))
        print(f"PROGRESS:100/100 {_('cli.progress_done_empty')}", flush=True)
        return

    # Le modèle "grandes vignettes" ("large_thumbs") peut réduire lui-même
    # le nombre de photos tenant sur UNE page, pour garantir de grandes
    # vignettes quel que soit le nombre demandé (voir
    # presentation.layout_engine.compute_effective_per_page) - les autres
    # modèles renvoient `config.num_per_sheet` inchangé. Paginer sur cette
    # valeur EFFECTIVE (plutôt que sur `config.num_per_sheet` directement)
    # garantit que les photos excédentaires d'une page "large_thumbs"
    # trop chargée se retrouvent sur une page supplémentaire plutôt que
    # d'être silencieusement ignorées (ContactSheetGenerator ne dessine de
    # toute façon jamais plus de cellules que cette même valeur - voir
    # contactsheet.py).
    n = compute_effective_per_page(config.profile)
    total_pages = (len(images) + n - 1) // n

    thumb_gen = ThumbnailGenerator(config)
    cs_gen = ContactSheetGenerator(config, thumb_gen)

    # === Nettoyage avant génération ===
    planches_dir = output_dir / "planches"
    if planches_dir.exists():
        shutil.rmtree(planches_dir)
    planches_dir.mkdir(exist_ok=True)

    pdf_path = output_dir / "portfolio.pdf"
    if pdf_path.exists():
        pdf_path.unlink()

    planche_files = []

    # Phase 2: Contact sheets
    print(f"PROGRESS:15/100 {_('cli.progress_sheets')}", flush=True)
    for page_idx in range(total_pages):
        batch = images[page_idx * n : (page_idx + 1) * n]
        page_num = page_idx + 1

        try:
            sheet = cs_gen.create_contact_sheet(batch, page_num, total_pages)
            if sheet:
                p = planches_dir / f"planche_{page_num:03d}.jpg"
                sheet.save(p, "JPEG", quality=95)
                planche_files.append(p)
                progress = 15 + int(55 * (page_num / total_pages))
                # "PROGRESS:X/100" est le seul marqueur lu par l'interface
                # graphique (voir planche-contact-gtk.py, _run_cli) :
                # volontairement jamais traduit, pour rester valable dans
                # toutes les langues sans dépendre d'un texte humain.
                print(_("cli.sheet_generated", page=page_num, total=total_pages), flush=True)
                print(f"PROGRESS:{progress}/100", flush=True)
        except Exception as e:
            logger.error(_("cli.log_error_sheet", page=page_num, error=e))

    sys.stdout.flush()

    # Phase 3: PDF
    if config.generate_pdf and planche_files:
        print(f"PROGRESS:75/100 {_('cli.progress_pdf')}", flush=True)
        PDFExporter().create_pdf(planche_files, output_dir / "portfolio.pdf")
        print(f"PROGRESS:80/100 {_('cli.progress_pdf_done')}", flush=True)

    # Phase 4: CSV
    if config.generate_csv:
        print(f"PROGRESS:82/100 {_('cli.progress_csv')}", flush=True)
        CSVIndexGenerator().create(images, output_dir / "index.csv")
        print(f"PROGRESS:85/100 {_('cli.progress_csv_done')}", flush=True)

    # Phase 5: HTML Gallery
    if config.generate_html:
        print(f"PROGRESS:86/100 {_('cli.progress_html')}", flush=True)
        gdir = output_dir / "gallery"
        HTMLGalleryGenerator(config, thumb_gen).create_gallery(images, gdir)
        print(f"PROGRESS:98/100 {_('cli.progress_html_done')}", flush=True)

    print(f"PROGRESS:100/100 {_('cli.progress_success')}", flush=True)
    logger.info(_("cli.log_finished", elapsed=f"{time.time() - start:.1f}"))


if __name__ == "__main__":
    # Voir le commentaire équivalent dans planche-contact-gtk.py : nécessaire
    # pour que multiprocessing.ProcessPoolExecutor fonctionne correctement
    # dans un contexte gelé (PyInstaller). Sans effet depuis les sources.
    import multiprocessing
    multiprocessing.freeze_support()
    main()
