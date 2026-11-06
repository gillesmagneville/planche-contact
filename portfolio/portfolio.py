#!/usr/bin/env python3
"""
portfolio.py - Contact sheet generator
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
from portfolio.rawloader import warn_if_rawpy_missing
from portfolio.presentation import compute_effective_per_page, load_profile


def _pre_resolve_language():
    """Determines the language to use for --help and the CLI messages,
    before even the normal argument parsing: argparse builds the help text
    of each add_argument() immediately at parser declaration, hence before
    the value of args.language is known - so we have to look at sys.argv
    ourselves beforehand, for this one need.
    """
    for i, arg in enumerate(sys.argv):
        if arg == "--language" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith("--language="):
            return arg.split("=", 1)[1]
    return "system"


def parse_args():
    import argparse

    # Resolved BEFORE building the parser: the help text of each
    # add_argument() below calls _() assuming the language is already
    # active (see _pre_resolve_language() above).
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
    parser.add_argument("--html-originals", action="store_true", help=_("cli.help_html_originals"))
    parser.add_argument("--watermark", default=None, help=_("cli.help_watermark"))
    # Choices left in French: internal value compared as a hard-coded literal
    # by portfolio/config.py (see PROJECT_CONTEXT.md §5) - only the displayed
    # help text is translated, never the values themselves.
    parser.add_argument("--watermark-orientation", default="Horizontal",
                        choices=["Horizontal", "Diagonale horaire", "Diagonale anti-horaire"],
                        help=_("cli.help_watermark_orientation"))
    parser.add_argument("--watermark-opacity", type=int, default=40,
                        help=_("cli.help_watermark_opacity"))
    # Already resolved above (see _pre_resolve_language): merely
    # declared here so that argparse recognises the option (useful in
    # particular when the graphical interface launches this script as a
    # subprocess with its own language already active - see
    # planche-contact-gtk.py, _on_generate) and shows it in --help.
    parser.add_argument("--language", default="system", choices=AVAILABLE_LANGUAGES,
                        help=_("cli.help_language"))
    # Customisable layout/captions/theme (specification §2/§4.4): a
    # reusable JSON profile, saved via presentation.save_profile()
    # (graphical interface, a later step) or written/edited by hand. See
    # the note on precedence with --format/--num below
    # (Config.__post_init__).
    parser.add_argument("--profile", type=Path, default=None, help=_("cli.help_profile"))
    # Choice of the subfolders to process (the list of folders that contain
    # photos is offered by the graphical interface, see
    # scanner.list_image_folders()). Implies a recursive search.
    parser.add_argument("--include-dir", action="append", default=None, metavar="DIR",
                        help=_("cli.help_include_dir"))
    parser.add_argument("--include-dirs-file", type=Path, default=None, metavar="FILE",
                        help=_("cli.help_include_dirs_file"))

    # Preview mode (specification §3), reserved for internal use by the
    # graphical interface (planche-contact-gtk.py, _on_preview_clicked):
    # generates a SINGLE sheet (the first page, with the number of photos
    # actually shown on it - see compute_effective_per_page) in this CLI
    # subprocess entirely separate from the GTK application, then writes the
    # result as a PNG at the given path and stops - without ever touching
    # the real output folder or generating any PDF/CSV/HTML gallery. See
    # _generate_preview_sheet() below for the reason for this subprocess
    # isolation.
    parser.add_argument("--preview-output", type=Path, default=None, help=_("cli.help_preview_output"))

    return parser.parse_args()


def _include_dirs_from_args(args):
    """Subfolders requested by --include-dir (repeatable) and/or
    --include-dirs-file (one folder per line, UTF-8; the graphical interface
    uses it to avoid exceeding the maximum command-line length with many
    folders), or None if neither option is given (all photos). An empty
    file = no folder selected, hence no photos."""
    if not args.include_dir and args.include_dirs_file is None:
        return None
    dirs = list(args.include_dir or [])
    if args.include_dirs_file is not None:
        try:
            text = Path(args.include_dirs_file).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            print(_("cli.error_include_dirs_file", path=args.include_dirs_file, error=exc),
                  file=sys.stderr)
            sys.exit(2)
        dirs.extend(line for line in text.splitlines() if line.strip())
    return tuple(dirs)


def _generate_preview_sheet(args, profile_kwargs):
    """Generates a single sheet for the preview (--preview-output)
    and nothing else - see the argument's comment above.

    Deliberately a separate code path, independent of the rest of
    main(): never creates the real output folder, configures no logging
    in it, cleans/overwrites nothing from a previous generation, and
    produces no PDF, CSV or HTML gallery - only the PNG image of the
    requested sheet.

    Isolation in a subprocess (rather than a simple direct call from the
    graphical interface, in a background thread of the GTK application):
    empirical finding (tests under real GTK4) that Pillow text rendering
    (sheet title/page number - see
    ContactSheetGenerator._draw_header()/_draw_page_number()) run
    concurrently with Pango - which also relies on FreeType, to display the
    widgets of the main GTK loop that stays active - can corrupt FreeType's
    internal initialisation and produce a glyph mask of aberrant size, to
    the point of making the rendering fail
    (PIL.Image.DecompressionBombError). A separate subprocess, without any
    window or GTK loop, structurally eliminates this concurrency rather than
    trying to make it reliable."""
    config = Config(
        input_dir=args.input,
        # Never created nor written: this mode only generates a standalone PNG,
        # at the --preview-output path supplied by the caller.
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

    # Once the language is set (parse_args): see rawloader.warn_if_rawpy_missing.
    warn_if_rawpy_missing()

    # Config arguments that do not come from the "simple" options:
    # the profile (--profile) and the selected subfolders (--include-dir...).
    profile_kwargs = {}
    if args.profile is not None:
        profile_kwargs["profile"] = load_profile(args.profile)
    include_dirs = _include_dirs_from_args(args)
    if include_dirs is not None:
        profile_kwargs["include_dirs"] = include_dirs

    if args.preview_output is not None:
        # Preview mode: see _generate_preview_sheet() - an entirely separate
        # code path from the rest of this function, which returns before any
        # creation/modification of the real output folder.
        _generate_preview_sheet(args, profile_kwargs)
        return

    output_dir = args.output or (args.input / "Portfolio")
    output_dir.mkdir(parents=True, exist_ok=True)

    setup_logging(output_dir / "generation.log")
    logger = logging.getLogger(__name__)

    logger.info(_("cli.log_starting", input=args.input))

    # Optional JSON profile (specification §2/§4.4, --profile): a
    # missing/unreadable/invalid file silently falls back to the default
    # profile (see presentation.load_profile(), never an exception) - no
    # "profile=" argument is then passed to Config below, to let its own
    # default value (default_profile()) apply normally. When a profile IS
    # supplied, Config.__post_init__() itself arbitrates the precedence with
    # --format/--num when both are given at once (see its docstring for the
    # current limit of this heuristic): --format/--num prevail only if they
    # were explicitly changed from their default value AND the profile has
    # not already customised that same setting. (profile_kwargs is computed
    # above, even before the branch to preview mode.)
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
        html_include_originals=args.html_originals,
        watermark_text=args.watermark,
        watermark_orientation=args.watermark_orientation,
        watermark_opacity=args.watermark_opacity,
        **profile_kwargs,
    )

    # The originals attached to the gallery are copied as-is: they
    # therefore carry no watermark, which would lose its meaning if the
    # user did not know it. The warning is written to the log AND to the
    # console (hence to the graphical interface's log).
    if config.generate_html and config.html_include_originals and config.watermark_text:
        logger.warning(_("cli.warn_originals_watermark"))

    # Phase 1: Scan
    print(f"PROGRESS:0/100 {_('cli.progress_scanning')}", flush=True)
    scanner = ImageScanner(config)
    images = scanner.scan()
    print(f"PROGRESS:10/100 {_('cli.progress_found', count=len(images))}", flush=True)

    if not images:
        logger.warning(_("cli.log_no_images"))
        print(f"PROGRESS:100/100 {_('cli.progress_done_empty')}", flush=True)
        return

    # The "large thumbnails" template ("large_thumbs") can itself reduce
    # the number of photos fitting on ONE page, to guarantee large
    # thumbnails whatever the number requested (see
    # presentation.layout_engine.compute_effective_per_page) - the other
    # templates return `config.num_per_sheet` unchanged. Paginating on this
    # EFFECTIVE value (rather than on `config.num_per_sheet` directly)
    # guarantees that the excess photos of an overcrowded "large_thumbs"
    # page end up on an additional page rather than being silently ignored
    # (ContactSheetGenerator never draws more cells than this same value
    # anyway - see contactsheet.py).
    n = compute_effective_per_page(config.profile)
    total_pages = (len(images) + n - 1) // n

    thumb_gen = ThumbnailGenerator(config)
    cs_gen = ContactSheetGenerator(config, thumb_gen)

    # === Cleanup before generation ===
    planches_dir = output_dir / "planches"
    if planches_dir.exists():
        shutil.rmtree(planches_dir)
    planches_dir.mkdir(exist_ok=True)

    pdf_path = output_dir / "portfolio.pdf"
    if pdf_path.exists():
        pdf_path.unlink()

    planche_files = []
    # Texts drawn on each sheet, for the PDF's selectable text.
    text_runs = {}

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
                text_runs[p] = list(cs_gen.last_text_runs)
                progress = 15 + int(55 * (page_num / total_pages))
                # "PROGRESS:X/100" is the only marker read by the graphical
                # interface (see planche-contact-gtk.py, _run_cli):
                # deliberately never translated, so that it stays valid in
                # all languages without depending on human-readable text.
                print(_("cli.sheet_generated", page=page_num, total=total_pages), flush=True)
                print(f"PROGRESS:{progress}/100", flush=True)
        except Exception as e:
            logger.error(_("cli.log_error_sheet", page=page_num, error=e))

    sys.stdout.flush()

    # Phase 3: PDF
    if config.generate_pdf and planche_files:
        print(f"PROGRESS:75/100 {_('cli.progress_pdf')}", flush=True)
        PDFExporter().create_pdf(planche_files, output_dir / "portfolio.pdf", text_runs=text_runs)
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
    # See the equivalent comment in planche-contact-gtk.py: needed so that
    # multiprocessing.ProcessPoolExecutor works correctly in a frozen
    # context (PyInstaller). No effect when run from source.
    import multiprocessing
    multiprocessing.freeze_support()
    main()
