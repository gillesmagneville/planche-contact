# Planche-Contact — Project Context

🇫🇷 [Version française](PROJECT_CONTEXT.fr.md)

This document is the complete technical reference for anyone (human or
AI) taking over this project. It covers the whole project: the common engine,
the graphical interface, and the two ports (Linux and Windows).

---

## 1. Purpose of the software

**Planche-Contact** is a lightweight tool that generates high-quality
(300 dpi) photographic contact sheets from a folder of photos, with no
database and no catalog.

From a single source folder, the tool produces, as chosen:
- **contact sheets** (JPEG, one or more pages);
- a **PDF** assembling all the sheets;
- a paginated, standalone **HTML gallery** with clickable thumbnails;
- a **CSV index** listing each photo with its number.

Two ways to use it:
- **GTK4 graphical interface** (`planche-contact-gtk.py`)
- **Command line** (`portfolio/portfolio.py`)

Supported photo formats: JPEG, PNG, TIFF, BMP, WEBP, HEIC/HEIF, and
RAW (CR2, CR3, NEF, DNG, ARW).

Platforms: Linux (Debian/Ubuntu, `.deb` package) and Windows 10/11 (portable
`.zip` or `.exe` installer) — same source code, separate packaging.

---

## 2. Architecture

### 2.1 General principle

The project is structured in **two strictly separated layers**:

1. **The engine (`portfolio/`)**: 100% pure Python, no dependency on the
   graphical interface. Usable on its own as a CLI. This is the layer that is
   *entirely shared* between Linux and Windows, with no adaptation whatsoever.
2. **The graphical interface (`planche-contact-gtk.py`)**: GTK4 (PyGObject),
   a single file. It calls the engine either through a direct import (previews),
   or as a subprocess (generation, so as never to freeze the interface).

Packaging (`.deb` on one side, `.exe`/`.zip` on the other) is the **only**
part really duplicated between the two platforms — and even then, the two
build scripts follow the same logic (version management, interactive
confirmation, `-Major/-Minor/-Patch` options).

### 2.2 The engine (`portfolio/`)

| Module | Role |
|---|---|
| `config.py` | `Config` dataclass: all the parameters of a generation |
| `scanner.py` | Folder scan (recursive or not), sorting by EXIF date or name (delegates to `utils.get_exif_date()`), excludes `planches/` and `gallery/` of the configured output folder to avoid re-scanning its own generated files (comparison by real file identity via `os.path.samefile()`, not by text — see §5); `Config.include_dirs` restricts the scan to the photos placed directly in the listed folders (and forces the recursive walk), `list_image_folders()` gives the list the interface offers ("Choose subfolders...") |
| `rawloader.py` | Unified image/RAW loading: embedded JPEG preview first (fast), full demosaicing (`rawpy`) only if this preview is missing or too small; `get_original_dimensions()`: real original resolution (metadata only, EXIF/RAW orientation applied), used by the HTML gallery viewer; `load_full_resolution()`: image at the FULL resolution of the shot (embedded preview if it covers ≥ 98% of the sensor, otherwise demosaicing), for the "original" JPEG of a RAW in the gallery |
| `thumbnail.py` | Parallel thumbnail generation (`ProcessPoolExecutor`, `spawn` context forced) |
| `contactsheet.py` | Generates the contact sheets (header, thumbnail grid, 3-line footer: page number, credit, developer/license - positions and space reserved below the grid in `layout_engine.FOOTER_*`) |
| `presentation/` | Common layout/captions/theme engine (`profile.py`: `Profile` dataclass + JSON; `layout_engine.py`: geometry of the grid/landscape/portrait/large thumbnails/free templates; `captions.py`: resolution of the EXIF captions, including their wrapping within a width in pixels (`layout_caption_lines()`); `themes.py`: Light/Dark/Neutral/System palettes). **Single source of truth**, used by both `contactsheet.py` (JPEG/PDF sheets) and `htmlgallery.py` (HTML gallery) — never a layout/caption/color rule duplicated between the two. The absence of a Profile (or a partial/invalid Profile) never changes the default behavior nor raises an exception (`default_profile()`); `Config.__post_init__()` backward-compatibly synchronizes the historical "simple" settings (`page_format`/`num_per_sheet`) into the Profile as long as it has not already customized them |
| `pdfexport.py` | Assembles the sheets into a PDF (`reportlab`); top margin reduced independently of the other margins |
| `textlayer.py` | Invisible text layer of the PDF (render mode 3, DejaVu subset embedded from `fonts/`): `ContactSheetGenerator` records every text it draws (`TextRun`, via `_put_text()`), `PDFExporter` replays them over the page image so that file names can be selected and copied. A failure never prevents the PDF from being produced |
| `htmlgallery.py` | Paginated HTML gallery; **a single decoding pass** per photo (the thumbnail is derived from the already-decoded full-size image, not a second decoding); `ImageOps.exif_transpose()` applied systematically to respect orientation (see §5); watermark applied **only once** on the full-size image, the thumbnail being derived by resizing this already-watermarked version (see §5, avoids a disproportionate/truncated pattern); full-screen viewer in vanilla JS built into each generated page (previous/next **crossing pages** with looping over the whole gallery (warning displayed at both ends, see §5), keyboard, mouse wheel, no external dependency) with page indicator, direct jump to a page, filename, download (via blob, see §5 — over `file://`, via a `.js` sidecar file per original) of the displayed copy (2000 px) **or, with the `Config.html_include_originals` option / `--html-originals` / main window checkbox (disabled by default), of the full-size original in `gallery/originals/` (copied as is, except RAW files, converted to JPEG: no RAW in the gallery)** (unique names chosen by the main process, not by the workers; encoded URLs; fallback to the displayed copy if the copy fails; the originals do NOT carry the watermark, hence a CLI warning), information panel (resolution/size/date, computed by the worker at the same time as the image), 50-200% zoom in real width/height, always centered, draggable by drag-and-drop once zoomed (mouse/touch via Pointer Events, bounded so as never to leave the frame completely — see §5, buttons, keyboard, Ctrl/Alt+wheel to zoom and wheel alone to move, never `transform: scale()` for the zoom, reset on each photo change) and full-screen toggle (`Fullscreen API`); footer with developer/license notice; **entirely translated** into the active language at generation time (`<html lang="...">` included), through `i18n.py` |
| `csvindex.py` | Generates the CSV index |
| `utils.py` | `get_font()` (bundled font, cached), `apply_watermark()` (tiled watermark, **single function** used by the sheets, the PDF and the gallery), `get_exif_date()` (shooting date, RAW included — **single function** used by the sorting in `scanner.py` and the viewer information in `htmlgallery.py`), `format_file_size()`, `setup_logging()` |
| `i18n.py` | Internationalization of **the graphical interface, the CLI and the generated HTML gallery** (see §5): `_()`, `set_language()`, `get_language()`, `detect_system_language()`. Python dictionaries (`locales/{fr,en,de,es}.py`), not gettext/.po/.mo — no compilation step nor additional dependency to bundle |
| `portfolio.py` | CLI entry point (`argparse`), orchestrates everything above, prints `PROGRESS:X/100 message` lines on stdout (read by the graphical interface — prefix deliberately never translated, see §5); `--language` resolved *before* the parser is built so that `--help` is already displayed in the right language; `--profile file.json` applies a reusable Profile (`presentation/`); `--preview-output path.png` (internal use by the graphical interface, see §2.3) generates a single sheet as a PNG and stops, without ever touching the real output folder nor generating PDF/CSV/HTML gallery |
| `fonts/` | DejaVu Sans font (regular + bold) bundled with the project — Bitstream Vera license, redistribution allowed |

### 2.3 The graphical interface (`planche-contact-gtk.py`)

A single file, structured around the `PlancheContactGTK(Gtk.Application)` class.

Main components:
- **Generation form**: title/author, input/output folders,
  images per sheet, page format, watermark (text, orientation,
  opacity slider), PDF/HTML/CSV checkboxes, images-per-page slider for the
  HTML gallery (12 to 64 in steps of 4, on the same line as the
  "Generate HTML Gallery" checkbox).
- **Custom folder chooser** (`_choose_folder`): entirely
  built by hand (`Gtk.DirectoryList` + `Gtk.FilterListModel` +
  `Gtk.CustomFilter`), not the native dialog (unreliable depending on the
  system). Sidebar (home folder, GTK bookmarks on Linux,
  list of drives on Windows), clickable breadcrumb, direct path
  entry field (useful for network shares), preview panel
  with pagination.
- **`FolderPreviewController`**: reusable class for the thumbnail
  preview (horizontal strip in the main window, grid in the folder
  chooser), background scan (thread) + notification of the main
  thread via `glib_idle_add()`.
- **Generation**: builds a command and launches it via
  `subprocess.Popen`, reads stdout line by line for the progress bar
  and the log.
- **"View results" menu**: opens each deliverable with the system's
  default application (`Gio.AppInfo` on Linux/macOS,
  `os.startfile()` on Windows), with a clear warning window if
  no application is configured. The contact sheets open the
  `planches/` **folder** (file manager), not an individual file
  — identical behavior whatever the number of sheets
  generated, unlike the old approach (multi-image viewer
  falling back to the first sheet alone).
- **`glib_idle_add()`**: wrapper around `GLib.idle_add()` tolerant of
  two different calling conventions depending on the platform/binding (see
  §6, PyGObject/Windows bug).
- **Language selector**: in a **Preferences** dialog (`_open_preferences()`), reachable via the menu button (hamburger icon,
  `open-menu-symbolic`) of the title bar — **not** in the About
  tab, which deliberately stays purely informative (version, license,
  credits); a setting logically has no place there (maintainer's
  feedback). Options: System language (default,
  falling back to English with a warning if unsupported), English,
  Français, Deutsch, Español. A change only takes effect on
  restart — rebuilding the whole widget tree on the fly would be a much
  heavier undertaking for a preference that is rarely changed (see
  §5, `portfolio/i18n.py`). **Scope**: the CLI (`portfolio.py`, via
  `--language`, passed automatically by the graphical interface when
  launching the generation subprocess) and the generated HTML gallery
  are translated into the same language. The user manual
  (`docs/planche-contact-manual.{en,de,es}.html`) is too —
  the Help tab opens the version matching the active language, falling
  back to French if the file for that language is missing.
- **"Advanced" section** (`_build_advanced_section()`): layout/captions/theme
  (`presentation/`), in a **separate modal window**
  (`_build_advanced_dialog()`, opened by the "Advanced settings…" button
  of the main window; formerly a `Gtk.Expander`, which enlarged the main
  window by ~550 px and made it taller than the screen),
  well apart from the simple settings (number of photos/format, unchanged —
  still the only active settings as long as this window has not been opened).
  The widgets (`self.adv_content`) are built once at startup and
  outlive the window (`set_hide_on_close(True)`: closing it hides it, does not
  destroy it): `_profile_from_widgets()` therefore works even if it has
  never been opened. Content in a `ScrolledWindow` whose maximum height
  is 72% of the screen's (`_advanced_dialog_limits()`) and whose
  natural width (~990 px) fits on a 1366 px screen without a horizontal
  scrollbar - do not put back a 4-column settings row nor a
  `FlowBox` with more than 4 fields per row: the
  bottom bar (status message + "Close") always stays visible. Any
  dialog opened from this window must take `self._dialog_parent()`
  as its parent (the advanced window being modal, a child window of the
  main one would be blocked), and any message to the user goes through
  `_adv_notify()` (log + visible status bar, the main log
  being hidden behind the modal window). Layout template, orientation,
  fit, margins/spacings, columns/rows (free template), caption
  position/area/lines/font/alignment, caption fields (checkbox
  per field, dedicated warning on the GPS field), custom
  theme colors. The theme MODE (Light/Dark/Neutral/System)
  is NOT in this window: it is the `self.theme_mode_dd` menu of the
  main window (everyday setting, see §6), the only widget for the mode —
  `_profile_from_widgets()`/`_apply_profile_to_widgets()` read/write it. `_profile_from_widgets()`/
  `_apply_profile_to_widgets()` do the round trip with a `Profile`;
  passed to the CLI subprocess (`--profile`, temporary JSON file) **
  only if different from the default profile** (`!= default_profile()`),
  so as never to change the behavior of anyone who never opens this
  section. Save/Load profile buttons (`Gtk.FileChooserNative`,
  reference kept in `self._active_file_dialog` as long as the dialog is
  open, to prevent its premature collection by Python).
- **Preview before generation** (`_on_preview_clicked()`): generates the
  sheet as it will actually be produced (same engine, same
  simple/advanced settings) on the first photos of the input folder,
  displayed in a dedicated window. **Always through a separate CLI
  subprocess** (`portfolio.py --preview-output`), never through a direct call
  to `ContactSheetGenerator` in a background thread of this
  application — see §6 for the reason (real, reproducible race
  between Pillow and Pango on FreeType, discovered
  empirically). Temporary PNG file + temporary JSON Profile
  (reuses the same mechanism as `_on_generate`), both deleted
  as soon as the result is read, whether it succeeded or failed.

---

## 3. Directory layout

```
planche-contact/
├── planche-contact-gtk.py          # GTK4 interface (shared Linux/Windows)
├── planche-contact-gtk             # Launch wrapper (Linux)
├── build-deb.sh                    # .deb package build (Linux)
├── build-appimage.sh               # AppImage build (Linux, any distribution; uses quick-sharun from Anylinux-AppImages, SHA-256 checked)
├── build-windows.ps1               # Root relay -> windows/build-windows.ps1
│
├── portfolio/                      # Engine, 100% shared
│   ├── __init__.py
│   ├── config.py
│   ├── scanner.py
│   ├── rawloader.py
│   ├── thumbnail.py
│   ├── contactsheet.py
│   ├── pdfexport.py
│   ├── textlayer.py
│   ├── htmlgallery.py
│   ├── csvindex.py
│   ├── utils.py
│   ├── i18n.py                     # Translation of the graphical interface only
│   ├── locales/                    # fr.py (source), en.py, de.py, es.py
│   ├── portfolio.py
│   └── fonts/
│       ├── DejaVuSans.ttf
│       ├── DejaVuSans-Bold.ttf
│       └── LICENSE.txt
│
├── debian/                         # Linux (.deb) packaging only
│   ├── control, compat, copyright, rules
│   ├── postinst                    # Checks the bundled Python environment at installation
│   └── postrm
│
├── windows/                        # Windows packaging only
│   ├── build-windows.ps1           # Actual build script
│   ├── planche-contact.spec        # PyInstaller config (bundles GTK4 + gi.overrides)
│   ├── installer.nsi               # NSIS script (.exe installer)
│   ├── README.md                   # Prerequisites, troubleshooting, pipeline details
│   └── README.fr.md                # French version of the above
│
├── metainfo/
│   └── planche-contact.metainfo.xml # AppStream metadata (App Center, PackageKit)
│
├── docs/
│   ├── planche-contact-manual.html    # Complete user manual (French, reference)
│   ├── planche-contact-manual.en.html
│   ├── planche-contact-manual.de.html
│   └── planche-contact-manual.es.html
├── screenshots/
│   └── application-icon.png        # Icon source (converted by each build script)
│
├── requirements.txt
├── VERSION                         # Single version number, shared by the two build scripts
├── README.md                       # English (default); French version: README.fr.md
├── README.fr.md
├── CHANGELOG.md                    # English (default); French version: CHANGELOG.fr.md
├── CHANGELOG.fr.md
├── CONTRIBUTING.md                 # English (default); French version: CONTRIBUTING.fr.md
├── CONTRIBUTING.fr.md
├── LICENSE                         # GNU GPL v3
├── CODE_OF_CONDUCT.md              # Contributor Covenant 3.0 (CC BY-SA 4.0); French version: CODE_OF_CONDUCT.fr.md
├── CODE_OF_CONDUCT.fr.md
├── PROJECT_CONTEXT.md              # This file (English)
└── PROJECT_CONTEXT.fr.md           # French version of this file
```

**Note**: `docs/screenshots/` has not existed for a long time (removed from the
repository), it must no longer be mentioned as part of the
directory layout. `portfolio/Utilisation` has been corrected (only `--background`
was actually obsolete among its example arguments; `--thumb` does
exist in the current `portfolio.py`).

---

## 4. Dependencies

### 4.1 Common (engine, `requirements.txt`)

| Package | Version | Role |
|---|---|---|
| Pillow | ≥ 10.0 | Image processing |
| reportlab | ≥ 4.0 | PDF generation |
| rawpy | ≥ 2.24 | RAW decoding (bundles LibRaw). Optional: without it, RAW files are skipped with a warning |
| exifread | ≥ 3.0 | EXIF reading of RAW files (PIL cannot do it) |
| PyGObject (`gi`) | — | GTK4 bindings. Cannot be reliably installed through pip: system package on Linux (`python3-gi`), gvsbuild wheels on Windows |

### 4.2 Linux-specific

- `python3-gi`, `gir1.2-gtk-4.0` (system packages, prerequisites before using the graphical interface from source)
- `fpm` (Ruby gem) to build the `.deb`
- `python3-exifread` (apt) + `rawpy` (pip) installed automatically into the bundled venv by `build-deb.sh`
- `metainfo/planche-contact.metainfo.xml` (AppStream metadata), installed by `build-deb.sh` into `/usr/share/metainfo/` — needed for App Center (PackageKit + AppStream, since Ubuntu 26.04) to fully recognize the package (size, enriched description) instead of limiting itself to the `.desktop` file

### 4.3 Windows-specific

- Python **must match exactly** the version targeted by the
  latest gvsbuild release (currently Python 3.14 — see §6, this
  constraint changes with each new gvsbuild release)
- [gvsbuild](https://github.com/wingtk/gvsbuild): precompiled GTK4 stack
  for Windows (downloaded and installed automatically into `C:\gtk` by
  `build-windows.ps1` if missing)
- PyInstaller (freezes the application into an `.exe`)
- NSIS (generates the `.exe` installer — optional, otherwise only the
  portable `.zip` version is produced)
- winget (used for the automatic installation of NSIS/Python if missing)

---

## 5. Coding conventions

- **Language**: code identifiers (variables, functions, classes) in
  English; code comments in French (the build and packaging scripts —
  `build-deb.sh`, `build-appimage.sh`, `build-windows.ps1`, `debian/postinst` —
  are entirely in English, messages included, and their confirmation questions
  are answered by `y` (`[y/N]`); the comments of `windows/installer.nsi` and
  `windows/planche-contact.spec` are in English too, while the screens of the
  Windows installer itself stay in French); strings visible to the user in the
  interface and messages through `portfolio/locales/` (English, French,
  German, Spanish — `en.py` must stay complete, since English is the
  fallback language). The documentation (`.md` files) is bilingual: the
  English version is the default file (`X.md`) and the French version sits
  next to it (`X.fr.md`), with a link to each other at the top of each file;
  when one is changed, the other must be updated too.
- **Explanatory comments**: systematically used to document
  the *why* of a non-obvious choice (platform-specific
  workaround, binding bug, etc.), not only the *what*.
- **`multiprocessing`**: always with the explicit `spawn` context
  (`multiprocessing.get_context("spawn")`), including on Linux — never
  `fork` (known deadlock between `rawpy`/OpenMP and `fork`).
- **Font loading**: always through `utils.get_font()` (cached,
  bundled font first) — never a hard-coded font path
  elsewhere in the code.
- **EXIF orientation**: always apply `ImageOps.exif_transpose()`
  right after `rawloader.load_image()`, before any later processing
  (resizing, watermark...) — including in the optimized/merged
  decoding paths (see `CHANGELOG.md`, bug fixed on the
  HTML gallery which had lost this call when switching to single
  decoding).
- **Watermark on an image AND its derived thumbnail**: always watermark
  the full-size version first, then derive the thumbnail by
  resizing this already-watermarked version — never apply
  `apply_watermark()` separately on the two sizes. The tile pattern uses
  a fixed font size and spacing in pixels (see `utils.py`),
  designed for large sizes (sheets, PDF, "full-size" images
  of the gallery); applied as is on a much smaller
  canvas (e.g. 400px thumbnail), the pattern becomes disproportionate and may
  end up truncated at the bottom depending on the exact height of the image (see
  `CHANGELOG.md`, bug fixed on the HTML gallery).
- **`pip install` in the bundled venv (Linux, `build-deb.sh`)**:
  always with `--ignore-installed`. The venv is created with
  `--system-site-packages`; without this flag, `pip` silently skips the
  local copy of a package already visible at system level on the build
  machine, producing a venv that works by accident on that
  machine but is really incomplete once the `.deb` is installed
  elsewhere (see `CHANGELOG.md`).
- **Path comparison (folder exclusion)**: always compare
  the real identity of the file via `os.path.samefile()`, never a
  textual comparison (`Path.resolve()` + `relative_to()`/`==`). The same
  physical folder can have several different textual representations
  depending on the path taken — a mapped network drive
  (`Z:\photos`) and its UNC path equivalent
  (`\\server\share\photos`) under Windows are the most
  common example. `Path.resolve()` does not unify them, unlike
  `os.path.samefile()` (see `CHANGELOG.md`, recursion bug under
  Windows). `os.path.samefile()` makes one system call per comparison:
  always bound the climb through the parent folders (`boundary` parameter
  of `_is_within()` in `scanner.py`) rather than climbing up to the
  filesystem root for each file — noticeable on a network
  share.
- **EXIF date (standard formats, non-RAW)**: always go through
  `utils.get_exif_date()`, never through a direct `Image.getexif().get()` for
  `DateTimeOriginal`/`DateTimeDigitized` (tags `0x9003`/`0x9004`). These
  two tags live in a **separate Exif sub-IFD** (pointed to by tag
  `0x8769` of IFD0), never in the main IFD0: `exif.get(0x9003)`
  always returns `None`, you have to go through
  `exif.get_ifd(0x8769).get(0x9003)`. Only `DateTime` (`0x0132`, the file's
  *modification* date, less relevant than a shooting
  date) lives in IFD0 and remains directly accessible. This bug silently
  affected date sorting from the start (fallback to the file's
  modification date) - discovered while adding the date display in the
  HTML gallery viewer, which made it visible
  (see `CHANGELOG.md`).
- **Viewer zoom (HTML gallery): never `transform: scale()`,
  always real width/height in pixels** (`applyZoom()` in
  `htmlgallery.py`). Three pitfalls encountered while discovering this, in
  the order in which they show up:
  1. **`transform` creates a new stacking context.** A transformed element
     (even just `scale()`) is treated as "positioned" for visual
     stacking — it then passes in front of the viewer's `position: fixed`
     bars (auto z-index, decided by DOM order) instead of staying
     below. Confirmed with
     `document.elementFromPoint()` on a real Chromium (Playwright).
     Solution: explicit `z-index` on each bar/button of the
     viewer (10, or 20 for the panels that must go in front of
     even the top bar) rather than counting on DOM order.
  2. **`transform` changes ONLY the visual rendering, never the layout
     size.** An image visually zoomed to 200% via
     `transform: scale(2)` grows neither its `offsetWidth` nor the
     `scrollHeight` of its container: nothing "overflows" in the sense of
     `overflow`, so nothing is actually scrollable even if the screen
     suggests otherwise. Solution: set `width`/`height` to
     computed pixels, never `transform`, so that the overflow is
     real and scrollable.
  3. **`max-width`/`max-height` silently cap any
     width/height set elsewhere**, including in inline JavaScript style
     — the size actually rendered stays bounded to these values
     whatever the requested `width`/`height`. Pitfall
     discovered while fixing point 2: setting `width: 1472px` in JS
     was pointless as long as `max-width: 92vw` (used for the fit
     at 100%) remained active. Solution: explicitly neutralize
     `max-width`/`max-height` (`style.maxWidth = 'none'`) as soon as the zoom
     exceeds 100%, and restore them (`= ''`, to let the CSS
     take over again) on returning to 100%.
- **Moving around the zoomed image (HTML gallery): drag-and-drop via
  `transform: translate()`, never native scrolling of the container**
  (`applyPan()`/`clampPan()` in `htmlgallery.py`). A first version
  relied on `overflow: auto` + a flex centering dynamically switched
  to `flex-start` as soon as the zoom exceeded 100%: this
  left the image stuck at the top left instead of staying centered
  (reported by the maintainer), and in any case allowed no
  touch movement nor mouse drag-and-drop — only the wheel
  worked, relying on the browser's native scrolling.
  Current approach, more robust: `.lightbox` stays `overflow: hidden`
  (never native scrolling, hence no more centering pitfalls nor
  scroll chaining to the background page to handle - both
  problems disappear with their cause), the image stays **always**
  centered by the parent flexbox whatever its size, and
  `panX`/`panY` (two JS variables, applied via `transform:
  translate(panX, panY)` on the image, **without transition** for real-time
  tracking) move its visual rendering independently of its
  layout position. Clamping in `clampPan()`:
  `maxPan = max(0, (imageSize - containerSize) / 2)` in each
  dimension, applied after any zoom change AND after any
  movement, so that it is impossible to move the image
  entirely out of the frame. Triggered by three inputs, all brought together into
  the same `panX`/`panY`/`clampPan()`/`applyPan()`: drag-and-drop
  (Pointer Events - `pointerdown`/`pointermove`/`pointerup`, unifies
  mouse/touch/stylus into a single API, `setPointerCapture` so as not to
  lose the gesture if the cursor leaves the image during
  the drag), and the wheel when already zoomed (see below). Reset to
  zero (`panX = panY = 0`) on each return to 100% zoom and on each
  photo change.
- **Mouse wheel in the viewer**: a single
  `wheel` listener on `.lightbox`, `{ passive: false }` mandatory for
  `preventDefault()` to be honored. Ctrl/Alt/Cmd + wheel = zoom (also prevents
  the page's native zoom from triggering as well); wheel
  alone = previous/next navigation, unless already zoomed beyond
  100% (`currentZoom > 100`), where the wheel directly moves the enlarged
  image (`panX -= deltaX; panY -= deltaY;` then `clampPan()` +
  `applyPan()`, see above) rather than changing photo. Debounce
  (`WHEEL_THROTTLE_MS`) needed on the photo change
  (not on the movement, which must stay smooth): a single gesture on a
  trackpad can emit dozens of `wheel` micro-events, which
  would otherwise scroll through several photos or zoom steps at once.
- **Previous/next navigation crossing pages (HTML gallery
  viewer)**: each generated page being a separate static file
  with its own `galleryImages` array bounded to its photos alone,
  `showDelta()` must detect when the bounds of this array are exceeded
  (`newIndex < 0` or `>= galleryImages.length`) and **navigate to the
  file of the next/previous page** (`window.location.href =
  pageUrl(...)`) rather than looping over the photos of the current page -
  except for a single-page gallery (`totalPages <= 1`), which has
  nowhere to go and keeps a simple local loop (avoids
  reloading the page for nothing). Looping over the **whole**
  gallery at both ends (last photo of the last page →
  first photo of the first page, and vice versa). The
  destination page does not know by itself which photo to open: it arrives
  with `?open=0` (coming from a previous page) or `?open=last` (coming from
  a next one) in the URL, read by a block run at the end of the script
  of the target page, which opens the viewer at the right photo then
  cleans the URL (`history.replaceState`) so that a manual
  refresh does not reopen it unintentionally. A second parameter,
  `&wrap=fwd`/`&wrap=back`, distinguishes a normal crossing (no
  warning) from a loop over the whole gallery (last
  photo → first page or the reverse), to display the right message through
  `showToast()` only in this second case - the target page cannot
  deduce by itself whether its arrival at index 0 or last is a
  loop or a simple coincidence of pagination, the source page has to
  state it explicitly. The background grid (behind the
  viewer) already correctly reflects the target page after this
  change, `window.location.href` being a real full navigation
  — verified empirically (top pagination, thumbnails displayed)
  rather than assumed.
- **Image download in the viewer (HTML gallery)**: the
  button goes through `fetch()` → `Blob` → `URL.createObjectURL()` rather than
  the plain HTML `download` attribute on the direct link, unreliable
  once served over HTTP(S) depending on the browsers. **Fundamental,
  non-circumventable limitation, tested empirically (Playwright/Chromium) with
  `CHANGELOG.md`**: when the gallery is opened directly over `file://`
  (double-click on `index.html`, no web server), `fetch()`,
  `XMLHttpRequest` AND reading a `<canvas>` that loaded the image are
  all three blocked identically by Firefox AND Chrome (each
  `file://` file has an "opaque" origin since the
  **CVE-2019-11730** security fix) - no JavaScript API makes it possible to
  work around that. The code detects `location.protocol === 'file:'` upstream
  and displays an explanatory message (toast button) rather than failing
  silently; do NOT retry `fetch()`/XHR/`<canvas>` for this
  specific case without having rechecked that this browser restriction has
  changed. **Workaround adopted for the originals** ("full-size
  originals" option): each `originals/X.jpg` is doubled by a sidecar
  file `originals/X.jpg.js` (`_write_download_script()`, base64 written
  in 3 MB blocks, call `pcOriginalLoaded(name, base64)`). Over `file://`,
  the button (`downloadOriginalFromScript()`) injects this neighboring
  `<script src>` - neighboring scripts load without restriction, unlike
  `fetch()`/XHR/`<canvas>` - rebuilds a `Blob` and downloads it through a
  `blob:` + `download` link (always honored, browser save dialog,
  real filename). Fallbacks, in order: script missing or
  in error → `<a download target="_blank">` link to the image (never
  `window.open()`: its result depended on the file TYPE - a RAW
  triggered Firefox's "Open/Save" dialog, a JPEG
  was displayed, hence the "regression" reported when RAW files became
  JPEGs); the displayed copy (2000 px, no original) stays on this
  link. Chromium ignores `download` on a `file://` link (verified):
  this link therefore opens in a new tab there. Cost: sidecar files ≈ 133% of
  the original; useless (deletable) over HTTP. Verified in Chromium
  (`file://`, HTTP, fallbacks, 28 MB original); **Firefox: confirmed by
  the user in 140.17.0 ESR (64-bit)** (save dialog
  visible on double-click); no Firefox in the sandbox, hence
  not tested here. Do not "simplify" by removing the sidecar files without having
  rechecked that a browser can read a neighboring file over `file://`.
- **Watermark**: always through `utils.apply_watermark()` — a single
  function, never watermark logic duplicated locally.
- **GTK/Windows compatibility**: systematic defensive pattern for
  platform-sensitive PyGObject calls:
  ```python
  try:
      GLib.idle_add(function, *args)           # expected pythonic form
  except TypeError:
      GLib.idle_add(PRIORITY, function, *args) # fallback to the raw C signature
  ```
- **`VERSION` file**: single source at the root, read and written by the
  two build scripts. Only updated after a **successful** build
  (never on failure, so as not to desynchronize the displayed number from the
  content actually published). **Belongs exclusively to the build
  scripts, never to Claude**: incremented locally by the maintainer on
  each build, independently of the working sessions with Claude - its
  value on GitHub may therefore have moved on since Claude's last `git pull`,
  even several times in a row, with no relation to
  the file Claude is working on. Strict rule: **never
  create, modify, nor deliver a `VERSION` file** from memory or by
  assumption - a `git pull`/`git fetch` right before any delivery is not
  enough on its own if it does not specifically check this file,
  because a change concerning other files could suggest
  that VERSION is up to date when it changed between two pulls.
  If an occasional need requires knowing the current version (e.g. quoting
  it in a discussion), always reread `VERSION` fresh
  from `origin/main` at that precise moment rather than relying on a
  value seen earlier in the conversation - an oversight here would amount to
  making the displayed version number regress.
- **Code delivery**: complete files systematically, never a partial
  diff/patch (working convention established with the maintainer).
- **"View results" working on what already exists**
  (`_check_existing_results()`): no longer conditioned on a
  successful generation in the current session. Triggered on a change of the
  output folder field (typing or chooser, with a 400 ms debounce as
  for the input folder preview) and once at startup if an
  output folder was remembered. Checks the real existence of each
  artifact (non-empty `planches/`, `portfolio.pdf`, `gallery/index.html`,
  `index.csv`) and enables each sub-item independently - **no**
  condition on what was requested in a possible past
  generation (simplified from an earlier version that cross-checked
  file existence AND checkbox ticked this time; existence alone
  now suffices, consistent with the possibility of opening results
  from a previous session without relaunching a generation). `_last_result`
  is therefore no longer reserved for "the last generation of this session":
  it reflects the currently configured output folder, whether or not it
  triggered a generation. **Pitfall encountered while testing**: the
  "folder missing" branch must explicitly disable EACH
  sub-button, not only the main button - otherwise a sub-button
  previously enabled (e.g. PDF found for a folder typed just before)
  stays active after typing a folder with no results at all.
- **Internationalization of the graphical interface** (`portfolio/i18n.py` +
  `portfolio/locales/`): Python dictionaries per language (`fr.py` is the
  source; `en.py`/`de.py`/`es.py` must always have exactly the
  same set of keys — explicitly checked in a test), not gettext/.po/.mo
  — a deliberate choice to avoid a compilation step and an additional
  dependency to bundle in the `.deb`/Windows installer.
  New user-visible string = new key in the 4
  files of `locales/`, never hard-coded text in
  `planche-contact-gtk.py`. A language change only takes effect on
  restart (no on-the-fly rebuilding of the widget tree).
  **Pitfall encountered, to watch out for**: some dropdown menus display
  translated text to the user but must pass a fixed internal (French) value
  to the engine — the case of the watermark orientation,
  compared as hard-coded French in `portfolio/config.py`. Always read the selected
  **index** (`combo.get_selected()`) and make it point
  to a separate list of internal values
  (`self._orient_values[index]`), never the displayed text
  (`get_selected_item().get_string()`) for this kind of field.
  **Second pitfall encountered, more insidious**: `PlancheContactGTK` keeps
  two distinct variables for the language — `self.language_preference`
  (the saved raw choice, may be `"system"`) and `self._language`
  (the result already resolved by `set_language()`, never `"system"` -
  this is the one that goes into `--language` to the CLI subprocess).
  Changing the language in the dropdown without updating
  **both** leaves `self._language` stuck on the startup language:
  a generation launched right after a language change (without
  restarting) would then start again with the old language - detected by
  explicitly testing this precise scenario with Xvfb, not visible when
  rereading the code.
  **Third pitfall encountered, the most serious** (complete regression,
  detected by the maintainer in manual testing, not by Claude): Python
  treats `_` as a **local variable of the whole function** as soon as
  anything is assigned to it anywhere in that function - even
  after the call that uses `_()`. `_choose_folder()` contained
  `uri, _, label = line.partition(" ")` (classic Python convention
  for a throwaway value) in the GTK bookmarks reading code, further
  down in the same method that calls `_("folder_picker.title_input")`
  at the very beginning: this raised `UnboundLocalError` **on every click** on
  "Choose...", simply preventing the dialog from
  opening - PyGObject swallows the exception instead of surfacing a visible
  traceback, giving the impression that "the button does nothing".
  Never use `_` again as a throwaway variable name in a
  file that imports `_` from `i18n.py` - prefer `_sep`, `_unused`, or
  any explicit alternative. A simple static check (looking, through
  AST, for a function that both assigns `_` and calls `_(...)`)
  makes it possible to detect this kind of conflict without having to click on
  each button one by one.
  **Scope**: the CLI (`portfolio.py`), the generated HTML gallery and the
  user manual are also translated into the same language as
  the interface (see §2.2/§2.3). Internationalization is now complete
  across the whole project.

---

## 6. Technical decisions made

Notable decisions, with their rationale (to avoid questioning them
without knowing the reason):

| Decision | Why |
|---|---|
| 100% custom folder chooser, not `Gtk.FileChooserDialog` | The native "folders only" filtering proved unreliable on the users' real systems |
| A single watermark function (`utils.apply_watermark`) | There were originally 3 different versions (sheets, gallery, an unused one), with a real inverted-angle bug between two of them |
| A single decoding pass for the HTML gallery | The thumbnail and the "full-size" image were previously decoded twice separately — significant performance gain |
| RAW preview: embedded thumbnail preferred over full demosaicing | Full demosaicing is slow; the JPEG preview embedded by the camera is enough for thumbnails/previews |
| Font bundled with the project (`portfolio/fonts/`) | Depending on a guessed system path (e.g. `C:/Windows/Fonts/arial.ttf`) could fail silently and fall back to Pillow's tiny font |
| Main window: natural minimum size, no forced size | Explicit request: open as small as possible while remaining resizable |
| Windows port: same source code, no fork | The engine is already 100% portable; duplicating would have doubled the maintenance load for no gain |
| `--run-cli`: the frozen exe relaunches itself in CLI mode | In a frozen executable, `sys.executable` points to the exe itself, not to a generic Python interpreter able to run `portfolio.py` as a separate script |
| `multiprocessing.freeze_support()` called **before** `import gi` | Double effect: (1) prevents the `ProcessPoolExecutor` workers from crashing with "Unknown option --multiprocessing-fork", (2) spares them from needlessly loading the whole GTK4 stack (performance gain on Windows) |
| `gi.overrides` explicitly bundled (`collect_submodules`) in the `.spec` | PyInstaller does not detect these modules automatically (loaded dynamically by PyGObject, never by a visible explicit `import`); without them, several GTK/GLib APIs fall back to their stricter raw C signature |
| `contents_directory='.'` in the PyInstaller `.spec` | PyInstaller 6+ places everything in an `_internal/` subfolder by default; the Windows startup code expects to find the DLLs/typelibs directly next to the executable |
| Repository renamed `planche-contact-linux` → `planche-contact` | The project has no longer been Linux-only since the Windows port |
| `windows/build-windows.ps1` + relay at the root | Symmetry with `build-deb.sh` (launched from the root) without duplicating the build logic itself |
| `fpm` (`build-deb.sh`): maintenance scripts through `--after-install`/`--after-remove`, never a `DEBIAN/` folder in the `-C` sources | Unlike native `dpkg-deb --build`, `fpm` never treats a folder named `DEBIAN/` among its sources specially: such a folder ends up as inert data content (installed as is on the target machine), never recognized as maintenance scripts nor run by dpkg |
| NSIS `IntFmt`: always the printf style (`"0x%X"`), never the mnemonic syntax (`"0xX"`) | `"0xX"` is documented on the NSIS wiki (valid in NSIS 2.x) but no longer converts anything in NSIS 3.x — it returns the literal string unchanged, silently making any `WriteRegDWORD` that depends on it fail (e.g. `EstimatedSize`, fallback to 0) |
| `makensis` + Wine installable via `apt` in Claude's Linux sandbox | Makes it possible to **compile AND run** a real NSIS installer to reproduce/validate a Windows bug without access to a real Windows machine. Requires `nsis` (universe package), and for a 32-bit NSIS installer by default: `dpkg --add-architecture i386` + `wine32:i386` (`wine64` alone is not enough). Registry writes can be checked with `wine reg query`. Does not replace a real user test (visual theme, real UAC, etc.) but makes it possible to confirm/refute a logic fix before handing it over |
| GTK4 + Xvfb installable via `apt` in Claude's Linux sandbox | Makes it possible to **actually run** `planche-contact-gtk.py` (not just check its syntax): `apt-get install gir1.2-gtk-4.0 python3-gi`, then `Xvfb :99 & DISPLAY=:99 python3 script.py`. Drive the app by direct introspection of the widgets (`app.win`, `app.run_button.get_label()`, `dropdown.set_selected(i)`...) via `GLib.timeout_add()` after `app.connect("activate", ...)`, rather than a dedicated UI automation tool. **Xvfb never survives between two separate tool calls** (like test HTTP servers): start Xvfb and launch the Python script in the **same** shell command, never two separate commands (`xvfb-run -a cmd...` handles this automatically, preferable to a manual `Xvfb &`) |
| GTK4 test environment: `python3.12` + `gir1.2-gtk-4.0` specifically, not the sandbox's default `python3` | PyGObject's compiled extension (`_gi.cpython-312-*.so`) only matches Python 3.12 in this environment (the default `python3` is 3.13 → `ImportError` on `gi`); and the `Gtk-4.0` typelib requires the `gir1.2-gtk-4.0` package in addition to `libgtk-4-1` (otherwise `ValueError: Namespace Gtk not available`). Also install the engine's dependencies for this specific interpreter (`python3.12 -m pip install --break-system-packages Pillow reportlab exifread numpy pytest`) |
| Any test script that drives `planche-contact-gtk.py` must itself keep ALL side-effect code (instantiating `Gtk.Application`, creating files...) under `if __name__ == "__main__":` | `ThumbnailGenerator.generate_parallel()` uses `multiprocessing` in `spawn` context, which **re-runs the entire launcher script** in each worker process (under the module name `__mp_main__`, not `__main__` — so a correctly placed `if __name__ == "__main__":` does protect the code it surrounds). A test script whose preparation code (e.g. `app = PlancheContactGTK()`, creating test photos) is outside this guard ends up re-run by each worker, causing hangs/cascading recursion (observed: a test script causing a hang of several minutes, diagnosed as this test harness bug, not a product bug) |
| Sheet preview (graphical interface) generated by a **separate CLI subprocess** (`portfolio.py --preview-output`), never by a direct call to `ContactSheetGenerator` in a background thread of the GTK application | Found empirically (tests under real GTK4, `xvfb-run`): a direct call in a background thread put Pillow's text rendering (title/page number, via FreeType) in a race with Pango (text of the GTK interface itself, whose main loop stays active in the meantime) on the FreeType library **shared by both** in the same process — which could corrupt the computation of a glyph mask's size to the point of raising a `PIL.Image.DecompressionBombError` and making the preview fail. Reproduced several times, with a different mask size each time (the signature of a real race, not a deterministic bug); a warm-up of Pillow rendering at startup, before any GTK activity, was tried and proved **insufficient** (the corruption can occur on any call, not only the first). A separate subprocess, free of any GTK window/loop, eliminates this race structurally rather than trying to make it reliable — **never go back to a direct call in a thread for this need** |
| `pkill -f <pattern>` in a shell command launched by Claude: always wrap the pattern with a character class (`pkill -9 -f "[s]moke_test"` rather than `"smoke_test"`) | `pkill -f` matches against the full command-line text of EVERY process, including that of the shell running the `pkill` command itself: if the searched pattern appears literally in the typed `pkill` command (e.g. `pkill -9 -f smoke_test`), it ends up killing its own parent shell, silently interrupting the rest of the compound command (pitfall encountered and diagnosed in this session). The character class (`[s]moke_test`) breaks this false positive without changing the pattern sought in the REAL target processes |
| Any translated text (`_()`) executed in a `ProcessPoolExecutor(mp_context=spawn)` worker must explicitly receive the active language through the `initializer` (see `htmlgallery._init_worker_logging(log_path, language)`, which calls `set_language(language)`) | `spawn` starts a fresh Python interpreter per worker, which inherits NO state from the parent process (unlike `fork`): `set_language()`, called only once at CLI startup in the main process, never took place in these workers, and `portfolio.i18n._(...)` silently falls back there to its fallback language (English) whatever `--language` is. Bug found concretely during a load test (`utils.format_file_size()`, called from the HTML gallery generation worker, displayed "92.4 KB" in a gallery generated in French). Fixed by propagating the already-resolved language (`get_language()`) in `initargs`, the same mechanism already used to reconfigure logging in these workers. `contactsheet.py`/`thumbnail.py` are today NOT concerned (all their translated text runs in the main process) — but any future translated text added to code run by a `spawn` worker will have to apply the same rule |
| Any text area drawn in fixed pixels (JPEG/PDF sheets, `contactsheet.py`) must be **actively bounded** (wrapped to the width, reserved area enlarged accordingly in height, ellipsis only as a very last resort) to the space reserved for it - never assume that the content "will fit" | Unlike HTML (which naturally wraps text that is too long inside its container), a Pillow canvas never limits by itself the area where `ImageDraw.text()` draws: `_draw_caption()` drew text of any width without ever constraining it to the width of the cell. With several caption fields joined on the same line (default setting `lines=1`, a very common case), the text went well beyond the thumbnail and overflowed into the neighboring columns - reported by the user ("captions overlap and are unreadable"), not detected by the existing tests (which never combined several fields on one line). In the same way, the height reserved for a "below"/"above" caption only followed `layout.caption_area_mm`, independently of `captions.lines`/`captions.font_size`: increasing the latter without manually enlarging `caption_area_mm` made the last lines overflow into the photo of the next row. Fixed by (1) `layout_engine._reserve_caption_px()` which now reserves the MAXIMUM between `caption_area_mm` and the height actually needed for the number of lines/`font_size` - never the configured value alone - and (2) wrapping the captions within the width of a thumbnail (`presentation.captions.layout_caption_lines()`, which receives a `measure(text) -> width` function supplied by `contactsheet.py` to stay independent of PIL). The number of lines actually needed depends on the text, hence on the thumbnail width, hence on the reserved height: `ContactSheetGenerator._plan_page()` iterates (measure -> `compute_page_layout(..., caption_lines=n)` -> measure again) until stable, capped at `MAX_AUTO_CAPTION_LINES`; each sheet therefore adjusts the caption height to its own photos. `_draw_caption()` keeps two safety nets (single word too wide, lines beyond the reserved height -> "…"). A first version of this fix merely truncated with "…": no more overlap, but the user saw the information cut off below the photos - truncation alone is NOT an acceptable fix for text the user explicitly asked to display. Since the PDF directly embeds the same JPEGs as the sheets, it is fixed automatically along with them. Generalizable lesson: any future fixed-size text area in this module must apply the same principle (bound actively, never assume) |
| A setting that the user changes routinely (e.g. the theme MODE) goes in the **main window**, never only in the advanced settings window | Reported by the user ("I can't see a theme choice"): the Light/Dark/Neutral/System menu had been put in the "Advanced settings" expander in the name of the "advanced separate from simple" principle, but a top-level visual setting is not "advanced" in the sense of the specification (which targeted rare/technical settings: margins, columns, caption fields...). Only the custom colors stayed there. One setting = one widget: the main menu feeds the Profile directly, no "advanced" duplicate to keep in sync. Another pitfall noted in passing: the "System" mode can NOT follow the OS theme for a JPEG/PDF sheet (still image, `resolve_theme()` called without `prefer_dark`, hence light) - only the HTML gallery does (CSS media query); the documentation claimed the opposite |
| Never add variable-height content (collapsible section, growing settings grid) to the **main window**: anything bulky and secondary goes in a separate window, with scrolling content capped at the height of the screen | Reported by the user: the advanced section, unfolded in a `Gtk.Expander`, took the main window from about 1060 px to 1610 px in height - more than a screen - and sent the "Start generation"/"Quit" buttons out of view (the window deliberately has no default size, it takes that of its content). Making the WHOLE page scrollable would not have helped either: the action buttons would have stayed below the fold - the Generation tab is therefore split in two, a scrolling form (`self.form_scroll`, capped by `_apply_form_scroll_limits()`) and an always-visible bottom (buttons, status, progress, log). GTK4 pitfall: a classic on-demand scrollbar (`overlay_scrolling` false, `AUTOMATIC` policy) takes width from the content and makes a spurious HORIZONTAL scrollbar appear; the `ALWAYS` vertical policy makes it reserve this width (see `_configure_scroll_area()`, applied only if the content really exceeds the cap). Better to measure the actual window size (`get_height()` under Xvfb) before/after, on a small screen too (1280×600) |
| A thumbnail does NOT fill its square cell: `PageLayout`/`CellLayout` give the cell (`photo_w` x `photo_h` = `thumb_size` x `thumb_size`), but the pasted image keeps its proportions (`Image.thumbnail`, e.g. 4:3) and may be smaller - never assume that the photo touches the edges of its cell | A caption placed below the CELL was therefore separated from a landscape photo by a gap of a quarter of a thumbnail (reported by the user). Fixed at drawing time, not in the layout engine (which does not know the real proportions of the images, only numbers): `contactsheet._thumb_offset()` shifts the thumbnail within its cell (placed against its caption for "below", stuck beneath it for "above", against it for "right"; horizontally according to the text alignment); with NO caption drawn, the photo is centered in its cell (it was stuck at the top left, hence a set of photos that looked shifted - see the line on centering). The deliberate photo/caption gap (`CAPTION_PHOTO_GAP_PX`) is, for its part, reserved by the engine, in addition to the text area - `cell.caption_w`/`caption_h` remain the text area alone, never gap included |
| The photo grid must be **centered** on the page, never stuck to the left/top margin: check the centering on real renderings, over many combinations of settings, by measuring the footprint of the photo pixels (left/right and top/bottom margins), not only the computed coordinates | Reported by the user ("the set of photos is not centered"). Two causes that added up: (1) the thumbnail size is limited by the width OR the height, so the grid almost always leaves an empty space on one side only (209 combinations out of 384 off-center, up to ~12 cm) - the engine now splits the empty space in equal parts (`PageLayout.grid_w`/`grid_h`, horizontal centering in `compute_page_layout()`, vertical in `create_contact_sheet()` which knows the real header height); (2) with no caption, the photo was stuck at the top left of its square cell (`_thumb_offset()` returned `(0, 0)`, presented as "original behavior") - it is centered. The centering is computed on the grid of a FULL page so that the last, incomplete page keeps the same positions. Measurement pitfall: on a single-configuration test (A4 portrait, 12 photos, no caption) the defect was invisible - the grid is already almost centered there |
| Any preference that the HTML gallery stores on the visitor side (`localStorage`) must be **specific to the generation** (suffixed key, see `HTMLGalleryGenerator._theme_storage_key`), never a fixed key; and the toggle button must be able to **return to the requested setting**, not only alternate | Reported by the user ("the HTML gallery does not take the requested theme into account") although the theme was correctly written into the CSS: a click on ◐ stored `light`/`dark` under a single key, read BEFORE the CSS, and shared by all the galleries of the same origin (Chrome: a single `localStorage` for all `file://`) - every following gallery, even one regenerated with another theme, ignored it. And from "Neutral", two clicks no longer made it possible to get "Neutral" back. Diagnostic pitfall: generating then measuring the CSS is not enough, you also have to **measure the rendering in a real browser with a pre-existing `localStorage` state**. Second cause of the same symptom ("Light" requested, dark page): a page that does not declare its theme is darkened by the browser's automatic dark mode → always emit `color-scheme` (`_COLOR_SCHEME` in `htmlgallery.py`; `only light`, not `light` alone); known limitation: an unconditional "force dark mode" with a light preference remains unavoidable |
| Any file written into the gallery under a name derived from the source photo must have a **unique name and an encoded URL** (`quote`) | Two photos with the same name in two subfolders (`-r`) or a RAW + JPEG pair overwrite each other, and a `#` in a name cuts the URL (fragment): found while testing `originals/` with real photos, whereas `images/` already suffered from the same defect. For an ORIGINAL, silently losing a file would be serious, hence `_unique_file_name()` (also applied to the displayed copies in `images/`, where a RAW + JPEG pair `IMG_1.CR2`/`IMG_1.jpg` gives `IMG_1.jpg` twice); the name is assigned in the main process (the `spawn` workers run in parallel and cannot coordinate) |
| No RAW file must ever be written into the HTML gallery folder (`originals/` included): a RAW is converted to JPEG (`rawloader.load_full_resolution()`, quality 95, 4:4:4), never copied, even if the conversion fails | A gallery visitor cannot open a `.CR2`/`.NEF`/`.DNG`; reported by the user after a first version that copied the RAW files "as is" for the originals. An end-to-end test with a real DNG (`tests/data/mini_raw.dng`, 160 x 120, skipped if `rawpy` is missing) checks that no file with a RAW extension remains in the gallery. `spawn` workers cannot be monkeypatched: the tests that simulate RAW decoding replace `htmlgallery.ProcessPoolExecutor` with an in-process executor |
| Never rely on an "Open / Save" dialog produced by the BROWSER (e.g. `window.open()` on a file type it cannot display) for a download: trigger it explicitly, through a `Blob` + `download` link | Reported by the user: the dialog of the download button over `file://` disappeared when RAW files became JPEGs - it had never been provided by the application, only by Firefox facing a RAW it cannot display. Diagnostic pitfall: a feature that "works" thanks to a side effect (here the file type) breaks as soon as the side effect changes. Over `file://`, `fetch()`/XHR/`<canvas>` are blocked and Chromium ignores `download` on a `file://` link; what works (verified in Chromium): a neighboring `<script src>` (`originals/X.jpg.js`, `_write_download_script()`) that delivers the bytes in base64, then `Blob` + `a[download]` on a `blob:`. Firefox cannot be tested in the sandbox: any claim about its behavior must remain marked "unverified" until the user has confirmed it (here: confirmed in Firefox 140 ESR) |
| Any Profile setting exposed to the user must have an **end-to-end rendering** test proving that it changes the output - not only a Profile serialization/round-trip test | `LayoutSettings.fit_mode` ("Fill") was defined, validated, saved in JSON, displayed in the interface and described in the manual, but **never read** by the rendering engine: all the existing tests passed (they only checked the Profile) while the option did nothing. Now wired (`thumbnail.fit_thumbnail_image()`, passed to the `spawn` workers through the task arguments). Useful check to redo before documenting a new field: look for where `.field_name` is read outside `profile.py`. The same defect was then found on `title_position`, `author_position` and `page_numbering`, wired in turn (`ContactSheetGenerator._draw_header()`/`_draw_page_number()`, header of `htmlgallery._generate_page()`). Verification done field by field (search for `.field_name` outside `profile.py`): no Profile field is ignored by the rendering anymore - `show_gps` goes through `CaptionSettings.effective_fields()`, `separator` and `format_overrides` remain adjustable only through the JSON (no control in the interface) |
| Any line added to the footer of the sheets (`ContactSheetGenerator._draw_page_number()`) must take its position from `layout_engine.FOOTER_*_OFFSET_PX`, and `FOOTER_RESERVED_PX` derives from them | The footer is drawn in fixed pixels from the bottom of the sheet, outside the layout engine: without a reservation, a bottom margin smaller than it lets the photos go down under the text. A notice (credit, license) added to only one of the three outputs (sheets, PDF, HTML gallery) creates a gap that the user ends up noticing: "Developed by... GPL v3" only existed in the gallery; the text and the author's name are now common (`sheet.footer_credit`/`gallery.footer_credit`, `utils.AUTHOR_NAME`, parity test). The PDF draws no text: it reuses that of the sheets |

---

## 7. Known bugs / limitations

| Subject | Status |
|---|---|
| GTK4 colors different from the chosen Windows theme | **Inherent limitation**, not a bug: GTK4 uses its own theming system (Adwaita), independent of the OS's native theme. No simple fix is possible without a dedicated theming effort (querying the Windows API/registry and generating GTK CSS dynamically) |
| SmartScreen warning ("Windows protected your PC") at installation | **No code fix possible**: requires a paid code-signing certificate (~€100-500/year) or the natural accumulation of reputation over time. The workaround procedure ("More info" then "Run anyway") is documented for the end user in `windows/README.md`, the user manual and the main `README.md` |
| Windows Python version pinned to that of the latest gvsbuild release | External constraint, not a bug: if gvsbuild publishes a new version targeting another Python version, that new version will have to be installed (the script detects it and offers to install it automatically) |
| Windows build not directly testable by Claude on a real machine | No direct access to a Windows machine — remains true for any future fix. That said, `makensis` + Wine (see §6) make it possible to compile and run a real NSIS installer in the Linux sandbox to reproduce/validate a logic fix before handing it over — several bugs (see history in `CHANGELOG.md`) were thus confirmed then fixed with certainty rather than by deduction. The port has since been **validated on a real Windows machine by the maintainer, with no apparent bug**, and published as an official release |
| Console message "Le module 'rawpy' n'est pas installé..." (`rawloader.py`) always in French, whatever `--language` | Found during the same load test as the three texts fixed above (§6), but deliberately left aside for now: a console warning message (not a file delivered to the end client like the sheets/CSV/gallery), displayed only in the absence of the optional `rawpy` module. Same kind of fix as the other three (connect to `portfolio.i18n`) if handled one day |

---

## 8. Roadmap

- Internationalization (i18n): **done**, across the whole project —
  graphical interface, CLI, generated HTML gallery and user manual
  (English, French, German, Spanish — see §2.2/§2.3/§5).
- Customizable contact sheet templates: **done** — customizable EXIF
  captions, layout templates (grid/landscape/portrait/
  large thumbnails/free) savable as reusable JSON profiles,
  graphic themes (Light/Dark/Neutral/System, custom colors)
  and real preview before generation, all shared by the JPEG/PDF
  sheets and the HTML gallery (see §2.2 `presentation/`, §2.3 advanced
  section of the graphical interface).
- Additional export formats.
- More advanced PDF customization.
- *(Optional, if budget allows)* Code-signing certificate to remove the
  SmartScreen warning under Windows.
- *(Optional, major effort)* Integration of the native Windows
  theme/accent color into the GTK4 rendering.
