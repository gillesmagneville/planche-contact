from pathlib import Path
import base64
import json
import shutil
from concurrent.futures import ProcessPoolExecutor
from html import escape as html_escape
from urllib.parse import quote
import logging
import multiprocessing
import os
import uuid
from PIL import Image, ImageOps

from .rawloader import load_image, load_full_resolution, is_raw_file, get_original_dimensions
from .utils import apply_watermark, get_exif_date, format_file_size, get_exif_metadata, AUTHOR_NAME
from .i18n import _, get_language, set_language
from .presentation import get_palette, apply_custom_colors, resolve_caption_lines

# Max. size (longest side) of the "full-size" images of the HTML
# gallery. A 45 Mpx RAW photo fully demosaiced and then saved as is is
# both very slow to produce and much heavier to load in a browser than
# useful for an enlarged on-screen view: 2000 px on the long side is
# amply sufficient for a full-screen display.
GALLERY_FULL_MAX_SIZE = 2000


def _css_vars(palette) -> str:
    """Serialises a Palette (portfolio/presentation/themes.py) into a list
    of CSS custom-property declarations, to be injected as is inside a
    `{ ... }` block (see HTMLGalleryGenerator._build_theme_style_block())."""
    return (
        f"--bg: {palette.background}; "
        f"--text: {palette.text}; "
        f"--text-secondary: {palette.text_secondary}; "
        f"--accent: {palette.accent}; "
        f"--border: {palette.border};"
    )


#: `color-scheme` value (CSS property AND <meta> tag) announced to the
#: browser for each theme. Without this declaration, a browser whose
#: "automatic dark mode" is active (Chrome/Edge's "Auto Dark Mode for
#: Web Contents" option, Chrome's dark mode on Android, or some
#: extensions) forcibly darkens a gallery that was nevertheless requested
#: light: light theme chosen in the interface, dark page displayed.
#: `only light` is the explicit, standardised refusal of this darkening
#: (`light` alone does NOT prevent it - verified in Chromium); `dark` and
#: `light dark` declare that the page handles the dark theme itself, so
#: nothing is inverted a second time, and native elements (scrollbar,
#: fields) follow the page's theme.
_COLOR_SCHEME = {
    "light": "only light",
    "neutral": "only light",
    "dark": "dark",
    "system": "light dark",
}


def _init_worker_logging(log_path, language=None):
    """Reconfigures logging in child processes (required with 'spawn',
    which does not share the parent process's configuration).

    Also re-propagates the active language (`portfolio.i18n`): 'spawn'
    starts a brand-new Python interpreter per worker (no state of the parent
    process is inherited, unlike 'fork'), so `set_language()` - called once
    at CLI startup - never took place in this worker. Without this explicit
    re-arming, any call to `_()` INSIDE a worker (e.g. `format_file_size()`
    below, for the viewer's metadata) silently fell back to English
    (`portfolio.i18n`'s fallback language), whatever language was requested
    via --language - bug observed concretely: gallery generated in French,
    but file sizes displayed as "92.4 KB" (English) instead of "92,4 Ko"."""
    if log_path:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.FileHandler(log_path, encoding="utf-8")],
            force=True,
        )
    if language:
        set_language(language)


#: Size (in bytes, a multiple of 3 so that the base64 stays continuous
#: from one block to the next) of the blocks read by
#: _write_download_script().
_DOWNLOAD_SCRIPT_CHUNK_BYTES = 3 * 1024 * 1024


def _write_download_script(original_path: Path, original_name: str) -> bool:
    """Writes `originals/<name>.js`, the companion file of an original: the
    file's content in base64 inside a `pcOriginalLoaded(name, base64)` call.

    Why: when opened by double-click (`file://`), a page can neither read a
    neighbouring file (fetch/XHR/canvas blocked by all browsers) nor get a
    link to download rather than display a JPEG. On the other hand, a
    neighbouring `<script src>` tag is loaded normally (never blocked in
    `file://`): the viewer inserts it on demand, rebuilds the file from the
    base64 and downloads it under its real name, with the browser's usual
    dialog box (see downloadCurrentImage()). Served over HTTP, the gallery
    does not need it (the file is fetched directly): these files can be
    deleted before publishing online without breaking anything.

    Written in blocks (never the whole original in memory twice). Never
    raises an exception: on failure (disk full...), the partial companion
    file is deleted - a truncated script would not run and the click would
    have no effect - and the viewer falls back to its usual behaviour.
    Returns True if the companion file is complete."""
    script_path = original_path.with_name(original_name + ".js")
    try:
        with open(original_path, "rb") as source, open(script_path, "w", encoding="ascii") as out:
            # json.dumps escapes every non-ASCII character: the name stays exact
            # in a strictly ASCII file, whatever encoding is served.
            out.write("window.pcOriginalLoaded(" + json.dumps(original_name) + ',"')
            while True:
                block = source.read(_DOWNLOAD_SCRIPT_CHUNK_BYTES)
                if not block:
                    break
                out.write(base64.b64encode(block).decode("ascii"))
            out.write('");')
        return True
    except Exception as e:
        logging.getLogger(__name__).warning(_("engine.warn_html_download_file", name=original_name, error=e))
        try:
            script_path.unlink()
        except OSError:
            pass
        return False


#: Quality (and 4:4:4 subsampling, with no loss of colour detail) of the
#: JPEG created from a RAW for `originals/`: it is the downloadable
#: version of the shot, not a display copy (quality 90, 2000 px).
GALLERY_ORIGINAL_JPEG_QUALITY = 95


def _unique_file_name(name: str, used: set) -> str:
    """Unique file name across the whole gallery (`images/` and
    `originals/`): two photos with the same name must never overwrite each
    other. Common cases: the same number in two subfolders (option -r,
    several memory cards) and above all a RAW + JPEG pair (`IMG_1.CR2` and
    `IMG_1.jpg`, whose displayed copies are both called `IMG_1.jpg`). Losing
    an ORIGINAL silently would be far worse still than for a reduced copy.
    The comparison ignores case (Windows and macOS do not distinguish
    `IMG_1.JPG` from `img_1.jpg`). `used` is updated."""
    candidate = name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 2
    while candidate.lower() in used:
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    used.add(candidate.lower())
    return candidate


def _process_full_image_worker(args):
    """Worker function (picklable, run in a separate process) that prepares
    both the "full-size" image AND the thumbnail of the HTML gallery from a
    single decode (instead of two separate decodes as before): decoding
    (preferring the embedded preview for RAWs when it is large enough, see
    rawloader.load_image), capping to GALLERY_FULL_MAX_SIZE, optional
    watermark (tiled, identical to the contact sheets / the PDF, see
    utils.apply_watermark) applied ONCE on the full-size image, then
    derivation of the 400px thumbnail by simply resizing this
    already-watermarked version (not a new decode, nor a new watermark at a
    different scale - avoids a disproportionate/truncated pattern on a
    much smaller canvas), then saving of both JPEGs - all within the worker
    process, without going back through the main process. Also computes the
    metadata displayed in the viewer (real original resolution, file size,
    shooting date) while the file is already open, rather than a separate
    pass that would re-read each photo a second time."""
    (image_path, images_dir_str, thumbs_dir_str, thumb_filename,
     watermark_text, watermark_opacity, watermark_orientation) = args[:7]
    # Optional arguments, all chosen by the main process (the workers run in
    # parallel and cannot coordinate to guarantee name uniqueness): folder
    # and unique name of the full-size original (see
    # Config.html_include_originals), then unique name of the displayed copy
    # in `images/`. Absent (historical call with 7 arguments): no original,
    # copy name = display name.
    originals_dir_str, original_name, image_file_name = (tuple(args[7:10]) + (None, None, None))[:3]
    images_dir = Path(images_dir_str)
    thumbs_dir = Path(thumbs_dir_str)
    path = Path(image_path)
    if not path.exists():
        return (False, None)

    visible_name = HTMLGalleryGenerator.display_filename(path)
    out_name = image_file_name or visible_name
    target = (GALLERY_FULL_MAX_SIZE, GALLERY_FULL_MAX_SIZE)
    # A RAW must NEVER end up in the gallery (originals/ included): with the
    # "originals" option, it is converted to JPEG at its full resolution (see
    # below). The same decode then serves the original AND the displayed
    # copies (a single demosaicing, not two).
    convert_raw_original = bool(originals_dir_str and original_name and is_raw_file(path))
    try:
        if convert_raw_original:
            img = load_full_resolution(path)
        else:
            img = load_image(path, use_embedded_thumb=True, target_size=target)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        # Full-resolution image, neither reduced nor watermarked, intended for
        # the original: the displayed copies are made on a COPY (thumbnail() and
        # the watermark would modify it).
        full_resolution = img if convert_raw_original else None
        if full_resolution is not None:
            img = img.copy()
        img.thumbnail(target, Image.Resampling.LANCZOS)

        if watermark_text:
            img = apply_watermark(img, watermark_text, watermark_opacity, watermark_orientation)

        # Thumbnail derived from the full-size image ABOVE, already watermarked:
        # a simple resize, guaranteeing a visually identical watermark (just
        # reduced). Applying the tiled pattern separately on a canvas ~6x smaller
        # (with the same fixed font size and spacing in pixels) produced a
        # disproportionate rendering, sometimes truncated at the bottom of the
        # thumbnail depending on the exact height of each photo (see
        # CHANGELOG.md).
        thumb = img.copy()
        thumb.thumbnail((400, 400), Image.Resampling.LANCZOS)

        img.save(images_dir / out_name, "JPEG", quality=90)
        thumb.save(thumbs_dir / thumb_filename, "JPEG", quality=85)

        dimensions = get_original_dimensions(path)
        exif_date = get_exif_date(path)
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = None

        metadata = {
            # Name DISPLAYED to the user (viewer, information): that of the photo,
            # never the unique file name of the copy.
            "filename": visible_name,
            "image_file": out_name,
            "width": dimensions[0] if dimensions else None,
            "height": dimensions[1] if dimensions else None,
            "size": format_file_size(size_bytes) if size_bytes is not None else None,
            "date": exif_date.strftime("%d/%m/%Y %H:%M") if exif_date else None,
        }

        # Full-size original (option Config.html_include_originals).
        # - JPEG, PNG, TIFF... file: copied BYTE FOR BYTE (no re-decoding or
        #   recompression: original resolution, EXIF and quality intact).
        # - RAW: never copied as is (a visitor cannot open it, and no RAW must
        #   remain in the gallery) but converted to JPEG at the full resolution
        #   (see rawloader.load_full_resolution()), under the same name in
        #   `.jpg`. The metadata of the embedded preview (EXIF, colour profile)
        #   is kept when there is any.
        # In both cases, on failure (disk full, conversion impossible...) the
        # gallery stays complete: the download simply falls back to the reduced
        # copy - without ever copying the RAW instead.
        if originals_dir_str and original_name:
            if is_raw_file(Path(original_name)):
                # Safeguard: whatever name is received, a RAW is never written under a
                # RAW extension.
                original_name = Path(original_name).stem + ".jpg"
            target_original = Path(originals_dir_str) / original_name
            try:
                if full_resolution is not None:
                    save_options = {
                        "quality": GALLERY_ORIGINAL_JPEG_QUALITY,
                        "subsampling": 0,
                        "optimize": True,
                    }
                    exif = full_resolution.getexif()
                    if exif:
                        save_options["exif"] = exif
                    if full_resolution.info.get("icc_profile"):
                        save_options["icc_profile"] = full_resolution.info["icc_profile"]
                    full_resolution.save(target_original, "JPEG", **save_options)
                else:
                    shutil.copy2(path, target_original)
                metadata["original"] = "originals/" + quote(original_name)
                # Name offered for download: that of the photo (for a RAW, its name in
                # `.jpg`, never the original RAW extension).
                metadata["original_filename"] = visible_name
                # Companion file for double-click download (see
                # _write_download_script): its failure does not invalidate the original.
                _write_download_script(target_original, original_name)
            except Exception as e:
                logging.getLogger(__name__).warning(_("engine.warn_html_original", name=path.name, error=e))
                try:
                    target_original.unlink()  # no truncated file
                except OSError:
                    pass
        return (True, metadata)
    except Exception as e:
        logging.getLogger(__name__).warning(_("engine.warn_html_image", name=path.name, error=e))
        if not is_raw_file(path):
            # No useful fallback for a RAW (unreadable by a browser).
            try:
                shutil.copy2(path, images_dir / out_name)
            except Exception:
                pass
        return (False, None)


_HEADER_TEXT_ALIGN = {"top_left": "left", "top_right": "right"}


def _header_align_attr(position):
    """HTML alignment attribute of a line of the gallery header (title,
    author) according to Profile.layout.title_position / author_position.
    EMPTY string for centring (default value, already provided by the CSS
    class .header): the markup of a gallery generated without customisation
    therefore stays strictly identical to that of before."""
    align = _HEADER_TEXT_ALIGN.get(position)
    return f' style="text-align: {align}"' if align else ""


class HTMLGalleryGenerator:
    def __init__(self, config, thumbnail_generator):
        self.config = config
        self.thumb_gen = thumbnail_generator
        self.project_title = getattr(config, 'title', None)
        self.author = getattr(config, 'author', None)
        self.input_dir = getattr(config, 'input_dir', None)
        self.images_per_page = getattr(config, 'html_images_per_page', 48)
        self.include_originals = bool(getattr(config, 'html_include_originals', False))

        self.watermark_text = getattr(config, 'watermark_text', None)
        self.watermark_opacity = getattr(config, 'watermark_opacity', 40)
        self.watermark_orientation = getattr(config, 'watermark_orientation', 'Horizontal')

        # Graphic theme and customisable captions (specification §1/§4): same
        # Profile (portfolio/presentation/profile.py) as ContactSheetGenerator -
        # see Config.__post_init__() for the backward-compatible synchronisation
        # when no explicit Profile was supplied.
        self.profile = config.profile
        self.theme = self.profile.theme
        # The three fixed palettes are all pre-computed (possible custom colours
        # already applied - see presentation.themes.apply_custom_colors): the
        # HTML gallery needs ALL THREE at once, whatever the chosen mode, to
        # build both the page's default theme AND the discreet selector that
        # lets the visitor switch between light/dark themselves in their browser
        # (see _build_theme_style_block()) - unlike the JPEG/PDF sheets
        # (contactsheet.py), which resolve only ONE static palette at rendering
        # time.
        self._palettes = {
            mode: apply_custom_colors(get_palette(mode), self.theme.custom)
            for mode in ("light", "dark", "neutral")
        }
        # localStorage key of a visitor's manual choice (◐ button), SPECIFIC TO
        # THIS GENERATION of the gallery (random suffix, identical on all its
        # pages). A single fixed key for all galleries meant that one click on ◐
        # - in any gallery opened from the same origin (Chrome shares a single
        # localStorage between all local file:// files, a web server between all
        # its sites on the same host) - then overrode for good the theme chosen
        # in the main window, including for a gallery regenerated with another
        # theme: the gallery "ignored" the requested theme. With a key per
        # generation, a visitor's choice survives from one page to the next of
        # THEIR gallery, but never a regeneration.
        self._theme_storage_key = f"planche-contact-theme-{uuid.uuid4().hex[:12]}"
        # Customisable captions (specification §1): as for
        # ContactSheetGenerator, the EXIF metadata of each photo is re-read
        # (costly, one more file access per photo) ONLY if at least one caption
        # field is actually configured - default behaviour (no caption) with no
        # extra cost nor visual change to the existing grid.
        self.caption_fields = self.profile.captions.effective_fields()

    @staticmethod
    def display_filename(image_path) -> str:
        """
        File name as it will be served in the gallery. RAW files are
        decoded to JPEG (a browser cannot display a .cr2/.nef/...), so
        their extension is replaced by .jpg.
        """
        path = Path(image_path)
        if is_raw_file(path):
            return path.stem + ".jpg"
        return path.name

    def _color_scheme(self) -> str:
        """`color-scheme` value of the theme chosen for the gallery (see
        _COLOR_SCHEME). A manual choice by the visitor (◐ button) replaces it
        via the `:root[data-theme=...]` blocks of _build_theme_style_block()."""
        return _COLOR_SCHEME.get(self.theme.mode, _COLOR_SCHEME["light"])

    def _build_theme_style_block(self) -> str:
        """Builds the theme CSS declarations (specification §4): a default set
        of `:root` variables (the theme chosen in the Profile), plus - only in
        "system" mode - a `prefers-color-scheme: dark` media query letting the
        BROWSER decide (see presentation/themes.py, which explicitly documents
        this approach, specific to HTML rendering). The three
        `:root[data-theme="..."]` blocks are ALWAYS emitted, whatever the chosen
        mode: they feed the discreet selector below (_theme_toggle_html), which
        lets the visitor switch the theme themselves in their own browser,
        independently of the default theme chosen for the gallery.

        The `:root[data-theme="..."]` selectors have a strictly higher CSS
        specificity than the plain `:root` used by the media query below (two
        selectors against one): they therefore win automatically as soon as a
        data-theme attribute is set on <html>, without having to duplicate a
        `:not()` rule."""
        light_vars = _css_vars(self._palettes["light"])
        dark_vars = _css_vars(self._palettes["dark"])
        neutral_vars = _css_vars(self._palettes["neutral"])
        baseline_vars = self._palettes.get(self.theme.mode)
        # "system" mode (no static palette of its own): "light" serves as the
        # fallback value as long as neither the media query below nor the manual
        # selector has taken over yet (browsers without prefers-color-scheme
        # support, for example).
        baseline_vars = _css_vars(baseline_vars) if baseline_vars is not None else light_vars

        media_block = ""
        if self.theme.mode == "system":
            media_block = f"""
        @media (prefers-color-scheme: dark) {{
            :root {{ {dark_vars} }}
        }}"""

        return f"""
        :root {{ {baseline_vars} color-scheme: {self._color_scheme()}; }}{media_block}
        :root[data-theme="light"] {{ {light_vars} color-scheme: {_COLOR_SCHEME["light"]}; }}
        :root[data-theme="dark"] {{ {dark_vars} color-scheme: {_COLOR_SCHEME["dark"]}; }}
        :root[data-theme="neutral"] {{ {neutral_vars} color-scheme: {_COLOR_SCHEME["neutral"]}; }}"""

    def _effective_dark_js_expr(self) -> str:
        """JS expression (boolean) giving the initial direction of the
        light/dark toggle button (_theme_toggle_html) when the visitor has never
        used it themselves (no stored data-theme): "is the currently displayed
        theme dark?", so that the first click switches in the opposite direction
        rather than risking "going back" to the theme already displayed."""
        if self.theme.mode == "dark":
            return "true"
        if self.theme.mode == "system":
            return "prefersDark"
        return "false"  # "light" and "neutral" are both light/medium themes

    def _theme_toggle_html(self) -> str:
        """Discreet light/dark toggle button (specification §4: "discreet theme
        selector"), available whatever the theme chosen for the gallery - see
        _build_theme_style_block()."""
        label = html_escape(_("gallery.theme_toggle"))
        return (
            f'<button type="button" class="theme-toggle" onclick="toggleTheme()" '
            f'aria-label="{label}" title="{label}">&#9680;</button>'
        )

    def create_gallery(self, images, output_dir: Path):
        if output_dir.exists():
            shutil.rmtree(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)
        thumbs_dir = output_dir / "thumbs"
        images_dir = output_dir / "images"
        thumbs_dir.mkdir(exist_ok=True)
        images_dir.mkdir(exist_ok=True)
        originals_dir = output_dir / "originals"
        if self.include_originals:
            originals_dir.mkdir(exist_ok=True)

        display_title = self.project_title or (Path(self.input_dir).name if self.input_dir else "Galerie Photo")
        total_pages = (len(images) + self.images_per_page - 1) // self.images_per_page

        # Separate processes rather than threads: RAW decoding and JPEG
        # encoding are CPU-intensive tasks, and real processes make better use
        # of several cores than a thread pool (even if the underlying C
        # libraries release the GIL). Same 'spawn' context as for the thumbnails
        # (see thumbnail.py): rawpy uses OpenMP internally, incompatible with
        # fork().
        # A single parallel pass per image: each worker produces both the
        # "full-size" image AND the gallery thumbnail (see
        # _process_full_image_worker). The thumbnail name is precomputed here to
        # stay consistent with the page number used further below by
        # _generate_page.
        tasks = []
        used_original_names = set()
        used_image_names = set()
        for i, item in enumerate(images):
            image_path = item.get('path') if isinstance(item, dict) else item
            if image_path:
                page_num = i // self.images_per_page + 1
                idx_in_page = i % self.images_per_page
                thumb_filename = f"thumb_p{page_num}_{idx_in_page:04d}.jpg"
                # Unique names decided HERE, in the main process.
                original_task = (None, None)
                if self.include_originals:
                    original_task = (
                        str(originals_dir),
                        # DISPLAY name: a RAW becomes `.jpg` (see
                        # _process_full_image_worker), never a RAW name.
                        _unique_file_name(self.display_filename(image_path), used_original_names),
                    )
                tasks.append((
                    str(image_path), str(images_dir), str(thumbs_dir), thumb_filename,
                    self.watermark_text, self.watermark_opacity, self.watermark_orientation,
                    *original_task,
                    _unique_file_name(self.display_filename(image_path), used_image_names),
                ))

        results = [(False, None)] * len(images)
        if tasks:
            max_workers = min(os.cpu_count() or 4, 64)
            ctx = multiprocessing.get_context("spawn")
            log_path = None
            for handler in logging.getLogger().handlers:
                if isinstance(handler, logging.FileHandler):
                    log_path = handler.baseFilename
                    break

            with ProcessPoolExecutor(
                max_workers=max_workers,
                mp_context=ctx,
                initializer=_init_worker_logging,
                initargs=(log_path, get_language()),
            ) as executor:
                results = list(executor.map(_process_full_image_worker, tasks))

        page_ok = [ok for ok, _ in results]
        page_meta_all = [meta for _, meta in results]

        for page_num in range(1, total_pages + 1):
            start = (page_num - 1) * self.images_per_page
            page_images = images[start : start + self.images_per_page]
            page_results = page_ok[start : start + self.images_per_page]
            page_meta = page_meta_all[start : start + self.images_per_page]

            html_path = output_dir / ("index.html" if page_num == 1 else f"page_{page_num:03d}.html")

            self._generate_page(
                page_images=page_images,
                page_results=page_results,
                page_meta=page_meta,
                html_path=html_path,
                display_title=display_title,
                current_page=page_num,
                total_pages=total_pages,
                total_images=len(images),
                thumbs_dir=thumbs_dir
            )

        print(_("gallery.created_log", pages=total_pages, dir=output_dir))

    def _generate_page(self, page_images, page_results, page_meta, html_path, display_title,
                       current_page, total_pages, total_images, thumbs_dir):
        thumbs_dir.mkdir(exist_ok=True)

        layout = self.profile.layout
        header_html = ""
        if layout.title_position != "none":
            header_html += f"<h1{_header_align_attr(layout.title_position)}>{display_title}</h1>"
        if self.author and layout.author_position != "none":
            header_html += (
                f"<p{_header_align_attr(layout.author_position)}>"
                f"{_('gallery.by_author', author=self.author)}</p>"
            )
        header_html += f"<p>{_('gallery.header_count', count=total_images, current=current_page, total=total_pages)}</p>"

        nav_html = ""
        if total_pages > 1:
            nav_html = '<div class="nav">'

            if current_page > 1:
                prev = "index.html" if current_page == 2 else f"page_{current_page-1:03d}.html"
                nav_html += f'<a href="{prev}">{_("gallery.nav_prev")}</a>&nbsp;&nbsp;'

            if total_pages <= 15:
                pages = list(range(1, total_pages + 1))
            else:
                pages = [1]
                start = max(2, current_page - 2)
                end = min(total_pages - 1, current_page + 2)
                if start > 2:
                    pages.append("…")
                pages.extend(range(start, end + 1))
                if end < total_pages - 1:
                    pages.append("…")
                pages.append(total_pages)

            for p in pages:
                if p == "…":
                    nav_html += ' <span class="ellipsis">…</span> '
                else:
                    href = "index.html" if p == 1 else f"page_{p:03d}.html"
                    if p == current_page:
                        nav_html += f' <span class="current">{p}</span> '
                    else:
                        nav_html += f' <a href="{href}">{p}</a> '

            if current_page < total_pages:
                nextp = f"page_{current_page+1:03d}.html"
                nav_html += f'&nbsp;&nbsp;<a href="{nextp}">{_("gallery.nav_next")}</a>'

            nav_html += '</div>'

        html = f"""<!DOCTYPE html>
<html lang="{get_language()}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="color-scheme" content="{self._color_scheme()}">
    <title>{display_title}</title>
    <script>
        // Applied before the first render (document head, before the colour
        // CSS), to avoid any visible "flash" from one theme to the other for a
        // visitor who has already chosen theirs (see toggleTheme(), further down
        // the page) - it alone reads/writes this localStorage key, specific to
        // this visitor/this browser AND to this generation of the gallery (see
        // HTMLGalleryGenerator.__init__): a choice stored for an old gallery
        // never masks the theme requested for this one.
        (function() {{
            try {{
                var t = localStorage.getItem('{self._theme_storage_key}');
                if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
            }} catch (e) {{}}
        }})();
    </script>
    <style>{self._build_theme_style_block()}
        body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: var(--bg); color: var(--text); }}
        .header {{ text-align: center; margin-bottom: 20px; padding: 15px; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .header h1 {{ margin: 0; color: var(--text); }}
        .nav {{ text-align: center; margin: 15px 0; font-size: 1.05em; }}
        .nav a {{ margin: 0 6px; text-decoration: none; color: var(--accent); }}
        .nav a:hover {{ text-decoration: underline; }}
        .nav .current {{
            margin: 0 6px;
            font-weight: bold;
            color: var(--text);
            background: var(--border);
            padding: 2px 8px;
            border-radius: 4px;
        }}
        .nav .ellipsis {{
            margin: 0 4px;
            color: var(--text-secondary);
        }}
        .gallery {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; max-width: 1400px; margin: 0 auto; }}
        .gallery-item {{ display: flex; flex-direction: column; }}
        .gallery img {{
            width: 100%;
            height: auto;
            border-radius: 6px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.15);
            transition: transform 0.2s;
        }}
        .gallery img:hover {{ transform: scale(1.03); }}
        .gallery-caption {{
            margin-top: 4px;
            font-size: 0.8em;
            line-height: 1.3;
            text-align: center;
            color: var(--text-secondary);
        }}
        .footer {{ text-align: center; margin-top: 30px; color: var(--text-secondary); }}
        .theme-toggle {{
            margin-top: 10px;
            background: none;
            border: 1px solid var(--border);
            color: var(--text-secondary);
            border-radius: 6px;
            padding: 3px 10px;
            font-size: 0.95em;
            cursor: pointer;
            opacity: 0.6;
            transition: opacity 0.2s;
        }}
        .theme-toggle:hover {{ opacity: 1; }}

        .lightbox {{
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.92);
            z-index: 1000;
            align-items: center;
            justify-content: center;
            /* The image ALWAYS stays centred, even zoomed beyond the screen
               (see below): the overflow is simply clipped here, never natively
               scrolled - moving within the zoomed image is done by drag-and-drop
               (transform: translate() driven in JS), not by browser scrolling. A
               classic flex centring + overflow: auto does not reveal the part that
               overflows at the top/left when scrolling; this transform-based
               approach solves the problem at its root. */
            overflow: hidden;
        }}
        .lightbox.open {{ display: flex; }}
        .lightbox img {{
            max-width: 92vw;
            max-height: 92vh;
            border-radius: 4px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.5);
            transition: width 0.15s ease-out, height 0.15s ease-out;
            /* No transition on transform: the drag-and-drop must follow the
               mouse/finger in real time, with no latency. */
            /* explicit z-index: without it, once zoomed (enlarged width/height),
               the image went in front of the top bar and the previous/next arrows
               despite their position: fixed - a "positioned" element with z-index
               auto is stacked in DOM order, not by its size. */
            position: relative;
            z-index: 1;
            touch-action: none;
        }}
        .lightbox img.zoomed {{ cursor: grab; }}
        .lightbox img.zoomed.dragging {{ cursor: grabbing; }}
        .lightbox-prev, .lightbox-next {{
            position: fixed;
            background: rgba(255,255,255,0.12);
            color: white;
            border: none;
            cursor: pointer;
            font-size: 1.8em;
            line-height: 1;
            padding: 10px 16px;
            border-radius: 6px;
            user-select: none;
            z-index: 10;
        }}
        .lightbox-prev:hover, .lightbox-next:hover {{
            background: rgba(255,255,255,0.28);
        }}
        .lightbox-prev {{ left: 16px; top: 50%; transform: translateY(-50%); }}
        .lightbox-next {{ right: 16px; top: 50%; transform: translateY(-50%); }}

        .lightbox-topbar {{
            position: fixed;
            z-index: 10;
            top: 0; left: 0; right: 0;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            padding: 10px 16px;
            background: rgba(0,0,0,0.55);
            color: white;
            box-sizing: border-box;
            font-size: 0.95em;
        }}
        .lightbox-filename {{
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            opacity: 0.9;
        }}
        .lightbox-page-indicator {{
            opacity: 0.75;
            white-space: nowrap;
            margin-left: auto;
            margin-right: 12px;
        }}
        .lightbox-actions {{ display: flex; gap: 6px; flex-shrink: 0; }}
        .lightbox-btn {{
            background: rgba(255,255,255,0.12);
            color: white;
            border: none;
            cursor: pointer;
            font-size: 1.2em;
            line-height: 1;
            padding: 6px 12px;
            border-radius: 6px;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
        }}
        .lightbox-btn:hover {{ background: rgba(255,255,255,0.28); }}
        .lightbox-zoom-level {{
            min-width: 3.4em;
            justify-content: center;
            font-size: 0.85em;
            cursor: pointer;
        }}

        .lightbox-bottombar {{
            position: fixed;
            z-index: 10;
            bottom: 0; left: 0; right: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 24px;
            padding: 10px 16px;
            background: rgba(0,0,0,0.55);
            color: rgba(255,255,255,0.9);
            box-sizing: border-box;
            font-size: 0.9em;
        }}
        .lightbox-goto {{ display: flex; align-items: center; gap: 6px; }}
        .lightbox-goto input {{
            width: 4.5em;
            padding: 3px 6px;
            border-radius: 4px;
            border: none;
        }}
        .lightbox-goto button {{
            background: rgba(255,255,255,0.15);
            color: white;
            border: none;
            border-radius: 4px;
            padding: 4px 10px;
            cursor: pointer;
        }}
        .lightbox-goto button:hover {{ background: rgba(255,255,255,0.3); }}
        .lightbox-counter {{ white-space: nowrap; }}

        .lightbox-info {{
            display: none;
            position: fixed;
            z-index: 20;
            top: 56px;
            right: 16px;
            background: rgba(20,20,20,0.92);
            color: rgba(255,255,255,0.92);
            padding: 14px 18px;
            border-radius: 8px;
            font-size: 0.9em;
            max-width: 320px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.4);
        }}
        .lightbox-info.open {{ display: block; }}
        .lightbox-info p {{ margin: 4px 0; }}

        .lightbox-toast {{
            position: fixed;
            z-index: 20;
            bottom: 56px;
            left: 50%;
            transform: translateX(-50%) translateY(10px);
            max-width: 90vw;
            width: max-content;
            background: rgba(20,20,20,0.95);
            color: rgba(255,255,255,0.95);
            padding: 10px 18px;
            border-radius: 8px;
            font-size: 0.88em;
            text-align: center;
            box-shadow: 0 4px 16px rgba(0,0,0,0.4);
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.2s, transform 0.2s;
        }}
        .lightbox-toast.show {{
            opacity: 1;
            visibility: visible;
            transform: translateX(-50%) translateY(0);
        }}
    </style>
</head>
<body>
<div class="header">
    {header_html}
</div>
{nav_html}
<div class="gallery">
"""
        full_image_urls = []
        gallery_meta = []
        for idx, (item, ok) in enumerate(zip(page_images, page_results)):
            if not ok:
                continue

            image_path = item.get('path') if isinstance(item, dict) else item
            filename = self.display_filename(image_path) if image_path else f"image_{idx}.jpg"
            thumb_filename = f"thumb_p{current_page}_{idx:04d}.jpg"
            # The thumbnail file has already been written by the parallel worker
            # (see _process_full_image_worker): we merely reference its name here,
            # with no new write nor new decode.

            position = len(full_image_urls)
            meta = page_meta[idx] or {}
            # File actually written by the worker (unique name, see
            # _unique_file_name), encoded for the URL: a "#" or a "?" in a photo
            # name would otherwise cut the address (fragment/query).
            image_url = "images/" + quote(meta.get("image_file") or filename)
            full_image_urls.append(image_url)
            width, height = meta.get("width"), meta.get("height")
            entry = {
                "filename": meta.get("filename") or filename,
                "resolution": f"{width} × {height} px" if width and height else _("gallery.unknown"),
                "size": meta.get("size") or _("gallery.unknown"),
                "date": meta.get("date") or _("gallery.unknown"),
            }
            if meta.get("original"):
                # Absent by default (historical markup unchanged): the download then
                # targets the original instead of the reduced copy displayed in the
                # viewer.
                entry["original"] = meta["original"]
                entry["originalFilename"] = meta.get("original_filename") or entry["filename"]
            gallery_meta.append(entry)

            thumb_link = f''' <a href="{image_url}" onclick="return openLightbox(event, {position})">
        <img src="thumbs/{thumb_filename}" alt="">
    </a>\n'''

            # Customisable captions (specification §1), read directly from the
            # SOURCE photo (see utils.get_exif_metadata) - distinct from the light
            # metadata above (already computed by the parallel worker for the
            # viewer). No extra read if no field is configured (self.caption_fields
            # empty by default): grid strictly identical to before.
            if self.caption_fields and image_path:
                exif_metadata = get_exif_metadata(image_path)
                caption_lines = resolve_caption_lines(self.profile, exif_metadata)
                if caption_lines:
                    caption_html = "<br>".join(html_escape(line) for line in caption_lines)
                    html += (
                        ' <div class="gallery-item">\n'
                        f'{thumb_link}'
                        f'    <div class="gallery-caption">{caption_html}</div>\n'
                        ' </div>\n'
                    )
                    continue

            html += thumb_link

        goto_page_html = ""
        if total_pages > 1:
            goto_page_html = (
                '<div class="lightbox-goto">'
                f'<label for="goto-page-input">{_("gallery.goto_page_label")}</label>'
                f'<input type="number" id="goto-page-input" min="1" max="{total_pages}" placeholder="1-{total_pages}">'
                f'<button onclick="goToPage()">{_("gallery.goto_page_ok")}</button>'
                '</div>'
            )

        # Pre-escaped for JS (json.dumps correctly escapes quotes/apostrophes
        # whatever the language, safer than manual escaping - the translations
        # each contain their own punctuation).
        download_toast_js = json.dumps(_("gallery.download_toast"), ensure_ascii=False)
        download_label_js = json.dumps(_("gallery.download"), ensure_ascii=False)
        download_original_label_js = json.dumps(_("gallery.download_original"), ensure_ascii=False)
        wrap_forward_js = json.dumps(_("gallery.wrap_forward"), ensure_ascii=False)
        wrap_backward_js = json.dumps(_("gallery.wrap_backward"), ensure_ascii=False)

        html += f"""
</div>
{nav_html}
<div class="footer">
    <p>{_('gallery.footer')}</p>
    <p>{_('gallery.footer_credit', name=AUTHOR_NAME)}</p>
    {self._theme_toggle_html()}
</div>

<div id="lightbox" class="lightbox" onclick="if (event.target === this) closeLightbox()">
    <div class="lightbox-topbar">
        <span id="lightbox-filename" class="lightbox-filename"></span>
        <span class="lightbox-page-indicator">{_('gallery.lightbox_page', current=current_page, total=total_pages)}</span>
        <div class="lightbox-actions">
            <button class="lightbox-btn" onclick="zoomOut()" aria-label="{_('gallery.zoom_out')}" title="{_('gallery.zoom_out_title')}">&minus;</button>
            <button class="lightbox-btn lightbox-zoom-level" id="lightbox-zoom-level" onclick="zoomReset()" aria-label="{_('gallery.zoom_reset_label')}" title="{_('gallery.zoom_reset_title')}">100 %</button>
            <button class="lightbox-btn" onclick="zoomIn()" aria-label="{_('gallery.zoom_in')}" title="{_('gallery.zoom_in_title')}">&plus;</button>
            <button class="lightbox-btn" onclick="toggleInfo()" aria-label="{_('gallery.info')}" title="{_('gallery.info')}">&#9432;</button>
            <a id="lightbox-download" class="lightbox-btn" href="#" onclick="downloadCurrentImage(); return false;" aria-label="{_('gallery.download')}" title="{_('gallery.download')}">&#8681;</a>
            <button class="lightbox-btn" onclick="toggleFullscreen()" aria-label="{_('gallery.fullscreen')}" title="{_('gallery.fullscreen')}">&#10530;</button>
            <button class="lightbox-btn" onclick="closeLightbox()" aria-label="{_('gallery.close')}" title="{_('gallery.close')}">&times;</button>
        </div>
    </div>

    <button class="lightbox-prev" onclick="showDelta(-1)" aria-label="{_('gallery.prev')}">&#8249;</button>
    <img id="lightbox-img" src="" alt="">
    <button class="lightbox-next" onclick="showDelta(1)" aria-label="{_('gallery.next')}">&#8250;</button>

    <div id="lightbox-info" class="lightbox-info">
        <p><strong>{_('gallery.info_filename')}</strong> <span id="info-filename"></span></p>
        <p><strong>{_('gallery.info_resolution')}</strong> <span id="info-resolution"></span></p>
        <p><strong>{_('gallery.info_size')}</strong> <span id="info-size"></span></p>
        <p><strong>{_('gallery.info_date')}</strong> <span id="info-date"></span></p>
    </div>

    <div id="lightbox-toast" class="lightbox-toast"></div>

    <div class="lightbox-bottombar">
        <div class="lightbox-counter" id="lightbox-counter"></div>
        {goto_page_html}
    </div>
</div>

<script>
    const galleryImages = {json.dumps(full_image_urls, ensure_ascii=False)};
    const galleryMeta = {json.dumps(gallery_meta, ensure_ascii=False)};
    const downloadLabel = {download_label_js};
    const downloadOriginalLabel = {download_original_label_js};
    const totalPages = {total_pages};
    const currentPage = {current_page};
    let currentIndex = -1;
    let currentZoom = 100;
    let baseWidth = 0, baseHeight = 0;
    let panX = 0, panY = 0;
    let isDragging = false;
    let dragStartX = 0, dragStartY = 0, panStartX = 0, panStartY = 0;
    const ZOOM_MIN = 50, ZOOM_MAX = 200, ZOOM_STEP = 10;
    let lastWheelAction = 0;
    const WHEEL_THROTTLE_MS = 150;

    function pageUrl(n) {{
        return n === 1 ? 'index.html' : 'page_' + String(n).padStart(3, '0') + '.html';
    }}

    // Discreet theme selector (specification §4): toggles between the
    // gallery's theme and its light/dark opposite, and stores the visitor's
    // choice (specific to their browser and to this generation of the
    // gallery - see the script at the top of the page, which applies this
    // choice before the first render to avoid any flash). A second click
    // REMOVES this choice: the page then goes back to exactly the theme
    // requested at generation (including "neutral", which a simple
    // light/dark back-and-forth could never get back).
    function toggleTheme() {{
        const current = document.documentElement.getAttribute('data-theme');
        if (current) {{
            document.documentElement.removeAttribute('data-theme');
            try {{ localStorage.removeItem('{self._theme_storage_key}'); }} catch (e) {{}}
            return;
        }}
        const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        const next = ({self._effective_dark_js_expr()}) ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        try {{ localStorage.setItem('{self._theme_storage_key}', next); }} catch (e) {{}}
    }}

    function openLightbox(event, index) {{
        event.preventDefault();
        currentIndex = index;
        updateLightbox();
        document.getElementById('lightbox').classList.add('open');
        return false;
    }}

    function closeLightbox() {{
        document.getElementById('lightbox').classList.remove('open');
        document.getElementById('lightbox-info').classList.remove('open');
    }}

    function showDelta(delta) {{
        if (galleryImages.length === 0) return;
        const newIndex = currentIndex + delta;

        // Beyond the bounds of the current page: really moves to the
        // next/previous page (wrapping around the whole gallery at both ends)
        // rather than looping over the photos of this one page alone. A
        // single-page gallery has nowhere to go: it keeps the old behaviour
        // (simple local wrap-around, without reloading the page for nothing).
        if (totalPages > 1 && (newIndex < 0 || newIndex >= galleryImages.length)) {{
            if (newIndex < 0) {{
                const wrapping = currentPage === 1;
                const targetPage = wrapping ? totalPages : currentPage - 1;
                window.location.href = pageUrl(targetPage) + '?open=last' + (wrapping ? '&wrap=back' : '');
            }} else {{
                const wrapping = currentPage === totalPages;
                const targetPage = wrapping ? 1 : currentPage + 1;
                window.location.href = pageUrl(targetPage) + '?open=0' + (wrapping ? '&wrap=fwd' : '');
            }}
            return;
        }}

        currentIndex = (newIndex + galleryImages.length) % galleryImages.length;
        updateLightbox();
    }}

    function triggerBlobDownload(blob, filename) {{
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
    }}

    function showToast(message) {{
        const toast = document.getElementById('lightbox-toast');
        toast.textContent = message;
        toast.classList.add('show');
        clearTimeout(toast._hideTimer);
        toast._hideTimer = setTimeout(() => toast.classList.remove('show'), 6000);
    }}

    // Ordinary download link (`download` attribute): honoured by some
    // browsers for a neighbouring file in file://, ignored by others
    // (Chrome/Chromium then open the link in a NEW tab thanks to
    // target=_blank: the gallery is never left). In all cases, the message
    // explains what to do if nothing was downloaded.
    function openDownloadLink(url, filename) {{
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        link.target = '_blank';
        link.rel = 'noopener';
        document.body.appendChild(link);
        link.click();
        link.remove();
        showToast({download_toast_js});
    }}

    // Downloads in progress from a companion file, by file name:
    // the companion script calls pcOriginalLoaded(name, base64) when it runs.
    const pendingLocalDownloads = {{}};

    function pcOriginalLoaded(name, base64) {{
        const pending = pendingLocalDownloads[name];
        if (!pending) return;
        delete pendingLocalDownloads[name];
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
        triggerBlobDownload(new Blob([bytes], {{ type: 'image/jpeg' }}), pending.filename);
    }}

    function downloadOriginalFromScript(meta, filename, fallback) {{
        const name = decodeURIComponent(meta.original.split('/').pop());
        pendingLocalDownloads[name] = {{ filename: filename }};
        const script = document.createElement('script');
        // The script runs BEFORE its load event: if the entry still exists
        // then, it was missing, truncated or did not work.
        const failed = () => {{
            script.remove();
            if (pendingLocalDownloads[name]) {{
                delete pendingLocalDownloads[name];
                fallback();
            }}
        }};
        script.onload = failed;
        script.onerror = failed;
        script.src = meta.original + '.js';
        document.head.appendChild(script);
    }}

    function downloadCurrentImage() {{
        // Full-size original when the gallery embeds it ("originals" option),
        // otherwise the copy displayed in the viewer.
        const meta = galleryMeta[currentIndex];
        const url = meta.original || galleryImages[currentIndex];
        const filename = meta.originalFilename || meta.filename;

        // Since a widely adopted security fix (CVE-2019-11730), Firefox and
        // Chrome treat a page opened via file:// (double-click directly on
        // index.html, without a web server) as having an "opaque" origin:
        // fetch(), XMLHttpRequest AND reading a <canvas> that loaded the image
        // are blocked identically in both browsers to access a neighbouring
        // file - none of these three routes allows getting around that in
        // JavaScript. We therefore detect it upfront rather than failing
        // silently afterwards.
        // Two routes remain possible without reading the file: a neighbouring
        // <script src> tag (never blocked in file://, see below), and an
        // <a download> link, which browsers honour or not for a neighbouring
        // file (Chromium ignores it in file://; reported with no effect by a
        // Firefox user) - hence the companion file.
        if (window.location.protocol === 'file:') {{
            // Full-size original: its .js companion file (see
            // htmlgallery._write_download_script) allows a real download - exact
            // name, browser dialog box - even without a web server, and whatever
            // the browser.
            if (meta.original) {{
                downloadOriginalFromScript(meta, filename, () => openDownloadLink(url, filename));
                return;
            }}
            openDownloadLink(url, filename);
            return;
        }}

        // The native HTML "download" attribute is also unreliable once served
        // over HTTP(S) depending on the browsers (priority given to the
        // Content-Disposition header, etc.): we therefore convert to a blob
        // before triggering the download, which gets around this variability
        // (see CHANGELOG.md).
        fetch(url)
            .then(response => {{
                if (!response.ok) throw new Error('fetch a echoue');
                return response.blob();
            }})
            .then(blob => triggerBlobDownload(blob, filename))
            .catch(() => {{
                // An original (possibly a RAW) is not what is displayed in the
                // viewer: redrawing it on a canvas would give the reduced copy under
                // the original's name.
                if (meta.original) {{
                    window.open(url, '_blank');
                    return;
                }}
                // Unlikely fallback if fetch() fails nonetheless over HTTP(S): the
                // image is already loaded on screen (<img>), so we redraw it on a
                // hidden canvas to extract a blob, without a new network request.
                try {{
                    const img = document.getElementById('lightbox-img');
                    const canvas = document.createElement('canvas');
                    canvas.width = img.naturalWidth;
                    canvas.height = img.naturalHeight;
                    canvas.getContext('2d').drawImage(img, 0, 0);
                    canvas.toBlob(blob => {{
                        if (blob) triggerBlobDownload(blob, filename);
                        else window.open(url, '_blank');
                    }}, 'image/jpeg', 0.92);
                }} catch (e) {{
                    // Last fallback: at least open the image.
                    window.open(url, '_blank');
                }}
            }});
    }}

    function updateLightbox() {{
        const url = galleryImages[currentIndex];
        const meta = galleryMeta[currentIndex];

        currentZoom = 100;
        baseWidth = 0;
        baseHeight = 0;

        const img = document.getElementById('lightbox-img');
        img.style.width = '';
        img.style.height = '';
        img.src = url;

        document.getElementById('lightbox-filename').textContent = meta.filename;
        document.getElementById('lightbox-counter').textContent =
            (currentIndex + 1) + ' / ' + galleryImages.length;

        const dl = document.getElementById('lightbox-download');
        dl.href = meta.original || url;
        dl.download = meta.originalFilename || meta.filename;
        const dlLabel = meta.original ? downloadOriginalLabel : downloadLabel;
        dl.title = dlLabel;
        dl.setAttribute('aria-label', dlLabel);

        document.getElementById('info-filename').textContent = meta.filename;
        document.getElementById('info-resolution').textContent = meta.resolution;
        document.getElementById('info-size').textContent = meta.size;
        document.getElementById('info-date').textContent = meta.date;

        document.getElementById('lightbox-zoom-level').textContent = '100 %';
        document.getElementById('lightbox').classList.remove('zoomed');
    }}

    // Measures the "fit to screen" size (100%) once the image has actually
    // loaded, to zoom in real dimensions (width/height) rather than a
    // simple transform: scale() - needed so that the overflow beyond 100%
    // is really scrollable: transform only changes the visual rendering,
    // never the layout size taken into account by overflow (see
    // CHANGELOG.md).
    document.getElementById('lightbox-img').addEventListener('load', function() {{
        this.style.width = '';
        this.style.height = '';
        baseWidth = this.clientWidth;
        baseHeight = this.clientHeight;
        applyZoom();
    }});

    function applyZoom() {{
        const img = document.getElementById('lightbox-img');
        if (currentZoom === 100 || !baseWidth) {{
            img.style.width = '';
            img.style.height = '';
            img.style.maxWidth = '';
            img.style.maxHeight = '';
            panX = 0;
            panY = 0;
        }} else {{
            // max-width/max-height (CSS, for the 100% fit) otherwise silently cap
            // the size actually rendered, whatever the width/height set below -
            // nothing would then really overflow, and there would be nothing to
            // move.
            img.style.maxWidth = 'none';
            img.style.maxHeight = 'none';
            img.style.width = Math.round(baseWidth * currentZoom / 100) + 'px';
            img.style.height = Math.round(baseHeight * currentZoom / 100) + 'px';
            clampPan();
        }}
        applyPan();
        img.classList.toggle('zoomed', currentZoom > 100);
    }}

    // Bounds the movement so that the zoomed image can never leave the
    // window completely (in each dimension where it actually exceeds the
    // frame - otherwise, no movement allowed in that dimension, the image
    // already fitting entirely).
    function clampPan() {{
        const img = document.getElementById('lightbox-img');
        const lightbox = document.getElementById('lightbox');
        const maxPanX = Math.max(0, (img.offsetWidth - lightbox.clientWidth) / 2);
        const maxPanY = Math.max(0, (img.offsetHeight - lightbox.clientHeight) / 2);
        panX = Math.max(-maxPanX, Math.min(maxPanX, panX));
        panY = Math.max(-maxPanY, Math.min(maxPanY, panY));
    }}

    function applyPan() {{
        const img = document.getElementById('lightbox-img');
        img.style.transform = (panX !== 0 || panY !== 0) ? `translate(${{panX}}px, ${{panY}}px)` : '';
    }}

    function setZoom(value) {{
        currentZoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, value));
        applyZoom();
        document.getElementById('lightbox-zoom-level').textContent = currentZoom + ' %';
    }}

    function zoomIn() {{ setZoom(currentZoom + ZOOM_STEP); }}
    function zoomOut() {{ setZoom(currentZoom - ZOOM_STEP); }}
    function zoomReset() {{ setZoom(100); }}

    // Drag-and-drop to move the zoomed image (mouse, touch and stylus
    // unified via Pointer Events). Only acts if zoomed beyond 100% -
    // otherwise the image already fits entirely, nothing to move.
    (function() {{
        const img = document.getElementById('lightbox-img');

        img.addEventListener('pointerdown', function(e) {{
            if (currentZoom <= 100) return;
            isDragging = true;
            dragStartX = e.clientX;
            dragStartY = e.clientY;
            panStartX = panX;
            panStartY = panY;
            img.setPointerCapture(e.pointerId);
            img.classList.add('dragging');
            e.preventDefault();
        }});

        img.addEventListener('pointermove', function(e) {{
            if (!isDragging) return;
            panX = panStartX + (e.clientX - dragStartX);
            panY = panStartY + (e.clientY - dragStartY);
            clampPan();
            applyPan();
        }});

        function stopDragging() {{
            isDragging = false;
            img.classList.remove('dragging');
        }}
        img.addEventListener('pointerup', stopDragging);
        img.addEventListener('pointercancel', stopDragging);
    }})();

    function toggleInfo() {{
        document.getElementById('lightbox-info').classList.toggle('open');
    }}

    function toggleFullscreen() {{
        if (!document.fullscreenElement) {{
            document.documentElement.requestFullscreen().catch(() => {{}});
        }} else {{
            document.exitFullscreen();
        }}
    }}

    function goToPage() {{
        const input = document.getElementById('goto-page-input');
        let n = parseInt(input.value, 10);
        if (isNaN(n)) return;
        n = Math.max(1, Math.min(totalPages, n));
        window.location.href = pageUrl(n);
    }}

    document.addEventListener('keydown', function(e) {{
        if (!document.getElementById('lightbox').classList.contains('open')) return;
        if (document.activeElement && document.activeElement.id === 'goto-page-input') {{
            if (e.key === 'Enter') goToPage();
            return;
        }}
        if (e.key === 'Escape') closeLightbox();
        else if (e.key === 'ArrowLeft') showDelta(-1);
        else if (e.key === 'ArrowRight') showDelta(1);
        else if (e.key === 'i' || e.key === 'I') toggleInfo();
        else if (e.key === 'f' || e.key === 'F') toggleFullscreen();
        else if (e.key === '+' || e.key === '=') zoomIn();
        else if (e.key === '-' || e.key === '_') zoomOut();
        else if (e.key === '0') zoomReset();
    }});

    // Mouse wheel, only over the viewer (never over the page/browser in
    // the background, thanks to preventDefault):
    // - Ctrl/Alt/Cmd + wheel: zooms, like the browser's native gesture
    //   but limited to the displayed photo alone (also prevents the page's
    //   native zoom from triggering in addition).
    // - Wheel alone: goes to the next/previous photo - except when already
    //   zoomed beyond 100%, where the wheel directly moves the enlarged
    //   image (panX/panY, see applyPan) rather than changing photo.
    document.getElementById('lightbox').addEventListener('wheel', function(e) {{
        const now = Date.now();
        if (e.ctrlKey || e.metaKey || e.altKey) {{
            e.preventDefault();
            if (now - lastWheelAction < WHEEL_THROTTLE_MS) return;
            lastWheelAction = now;
            if (e.deltaY < 0) zoomIn(); else zoomOut();
            return;
        }}
        if (currentZoom > 100) {{
            e.preventDefault();
            panX -= e.deltaX;
            panY -= e.deltaY;
            clampPan();
            applyPan();
            return;
        }}
        e.preventDefault();
        if (now - lastWheelAction < WHEEL_THROTTLE_MS) return;
        lastWheelAction = now;
        if (e.deltaY > 0) showDelta(1); else showDelta(-1);
    }}, {{ passive: false }});

    // Arrival from the previous/next page (see showDelta above): reopens
    // the viewer directly at the right photo rather than on the grid, for a
    // smooth sequence between two pages. Cleans the URL afterwards so that a
    // manual refresh does not open the viewer unexpectedly.
    (function() {{
        const params = new URLSearchParams(window.location.search);
        if (!params.has('open')) return;
        const raw = params.get('open');
        const index = raw === 'last' ? galleryImages.length - 1 : parseInt(raw, 10);
        if (!isNaN(index) && index >= 0 && index < galleryImages.length) {{
            openLightbox({{ preventDefault() {{}} }}, index);
            // Wrap-around over the whole gallery (last photo -> first page, or the
            // reverse): warn the user, otherwise the page change might seem
            // unexpected.
            const wrap = params.get('wrap');
            if (wrap === 'fwd') showToast({wrap_forward_js});
            else if (wrap === 'back') showToast({wrap_backward_js});
        }}
        history.replaceState(null, '', window.location.pathname);
    }})();
</script>
</body>
</html>"""
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
