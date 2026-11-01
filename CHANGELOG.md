# Changelog

🇫🇷 [Version française](CHANGELOG.fr.md)

All notable changes to **Planche-Contact** will be documented in this file.

The project follows the recommendations of **Keep a Changelog** and **Semantic Versioning (SemVer)** as closely as possible.

## [Unreleased]

## [5.2.1] - 2026-11-01

Maintenance release: the program itself does not change.

### Added

- **A Code of Conduct** ([`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md), in English and in
  French), based on the Contributor Covenant 3.0, with the maintainer as the contact for
  reports. The packages ship it: in `/usr/share/doc/planche-contact/` for the `.deb`, in the
  root folder of the Windows packages (installer and portable) and inside the AppImage.

### Changed

- **The build scripts and the packaging files are now in English**, like the documentation:
  `build-deb.sh`, `build-appimage.sh`, `build-windows.ps1` (both the one at the root and the
  one in `windows/`), `debian/postinst` and `debian/control`, as well as the comments of
  `windows/installer.nsi` and `windows/planche-contact.spec`. Their confirmation questions are
  now answered with `y` (`[y/N]`) instead of `o`. The screens of the Windows installer itself
  stay in French, and the comments of the program's source code are unchanged.
- **The license is now declared the same way everywhere**: GPL-3.0-only, as in the `LICENSE`
  file, the README and the program. The AppStream metadata and `debian/copyright` said
  "GPL-3.0-or-later", and the `.deb` package said "GPL-3.0". The packages now declare
  `GPL-3.0-only AND CC-BY-SA-4.0` (the Code of Conduct is distributed under CC BY-SA 4.0), and
  `debian/copyright` describes both.
- The AppStream metadata (`metainfo/planche-contact.metainfo.xml`) is now written in English by
  default, with the French, Spanish and German translations (the Spanish and German wording
  still needs a proofread by a native speaker).
- README: the "Download" section points to this release; the Windows badge no longer says
  "build from source", since the installer is published.

### Fixed

- `build-appimage.sh` could stop without any message on a machine with many system libraries,
  and could, more rarely, leave a library out of the AppImage. Cause: some commands quit at the
  first match of a long `ldconfig` or `ldd` output, and with `pipefail` the resulting SIGPIPE
  made the script stop (or a test fail) at random. These commands now read their whole output.
  The script also reports the line where it stops, and a failed download of `quick-sharun`.

## [5.2.0] - 2026-10-30

### Added

- **File name shown under each photo by default (graphical interface)**, suggested by a user: until now the captions were off unless the "Advanced" section was opened and a field ticked, so the first sheet showed bare thumbnails. The window now starts with the "File name" caption below each photo (`presentation.interface_default_profile()`), still fully adjustable - or switchable off - in the "Advanced" section; "Reset" returns to this new starting point. Since it differs from the default profile, the interface now passes a `--profile` to the CLI from the very first generation. **The command line is unchanged**: without `--profile`, no caption, as before. Locked in by 6 tests (`tests/test_interface_defaults.py`) and checked in a real GTK 4 session.
- **PDF with selectable, copyable text**, suggested by a user (copying a file name out of the PDF): the PDF is assembled from the JPEG sheets, so its text used to be pixels only. `ContactSheetGenerator` now records every text it draws (captions, title, author, page number, footer: `last_text_runs`, with position, size and visible width) and `PDFExporter` lays it back as **invisible text** (render mode 3) over each page image (`portfolio/textlayer.py`, DejaVu Sans subset embedded from the bundled fonts, so accents are right). The page looks exactly as before; a file name can be selected with the mouse, copied and found with the viewer's search. A caption shortened by "…" on the sheet keeps its **full** text for copy-paste, and caption lines dropped for lack of height remain copyable. If the text layer fails or the fonts are missing, the PDF is produced as before, without text (warning in the log). Locked in by 14 tests (`tests/test_pdf_text.py`; the PDF text is read back with `pypdf`, a test-only dependency - those tests are skipped when it is not installed).
- **Choice of the subfolders to process**, suggested by a user: next to "Recursive search", a new "Choose subfolders..." button opens a window listing every folder that contains photos (the main folder first, then the subfolders in alphabetical order, each with its number of photos), all ticked, with "Select all" / "Select none". Only the photos placed directly in a ticked folder are processed (ticking `Paris` does not tick `Paris/Louvre`: each folder is chosen on its own); the sequence numbers, sheets, PDF, HTML gallery, CSV index and preview all follow the selection. The choice is shown as "N of M folder(s)" and is reset when the input folder changes or when the recursive search is unchecked; the output folder of a previous generation is never offered. Command line: `--include-dir DIR` (repeatable; path relative to the input folder, `.` for the input folder itself; implies a recursive scan) and `--include-dirs-file FILE` (UTF-8, one folder per line). Without these options nothing changes. Engine: `Config.include_dirs`, `scanner.list_image_folders()`, `scanner.normalize_include_dir()`; 20 new texts in the 4 languages (the German and Spanish wording still needs a proofread by a native speaker). Locked in by 30 tests (`tests/test_subfolders.py`) and checked in a real GTK 4 session (37 interface checks: dialog, kept selection, real generation, preview). Manuals (×4) updated.
- **AppImage**, requested by a user (see [Anylinux-AppImages](https://github.com/pkgforge-dev/Anylinux-AppImages)): the new `build-appimage.sh` script produces `Planche-Contact-<version>-<arch>.AppImage` and its `.AppImage.sha256`. One file bundles Python 3.12, GTK 4, PyGObject, Pillow, reportlab, rawpy and the C library (assembled by `quick-sharun` from the Anylinux-AppImages project), so it does not depend on the packages of the distribution that runs it. Without argument it starts the graphical interface; `AppImage portfolio ...` gives the command line interface.
  - GTK is forced to its software renderer (Cairo): no OpenGL/Vulkan/Mesa is bundled (43 MB instead of about 92 MB) and the graphics libraries of the host are blocked from loading (otherwise libepoxy picks up the host's `libEGL`, with drivers built for another C library).
  - The script downloads `quick-sharun` and **checks its SHA-256 before running it** (a changed upstream script stops the build rather than running code nobody has read). `--test` runs a real generation (PDF + CSV, with a subfolder) then starts the interface under a virtual display; `--clean` removes the work folder and the generated files. `*.AppImage` and `*.AppImage.sha256` are in `.gitignore` (they are release assets, not source).
  - **Verified**: built and tested on Ubuntu 24.04 (x86_64, GTK 4.14, Python 3.12): command line (PDF with selectable text, CSV, subfolder selection) and the 37 interface checks above, run inside the AppImage's own runtime under a virtual X display (Xvfb), both mounted through FUSE and unpacked (`APPIMAGE_EXTRACT_AND_RUN=1`); the maintainer also ran it (graphical interface and command line) on his own machine. **Not verified**: other distributions (Debian 13 in particular), Wayland, aarch64. The Anylinux-AppImages project recommends building on Arch Linux, which was not done here.
  - Full test suite: 1254 passed (1204 before).

### Changed

- **The documentation is now bilingual.** `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `PROJECT_CONTEXT.md` and `windows/README.md` are now written in English (the default file shown on GitHub), each with a complete French version next to it (`README.fr.md`, `CONTRIBUTING.fr.md`, `CHANGELOG.fr.md`, `PROJECT_CONTEXT.fr.md`, `windows/README.fr.md`), linked to each other at the top of each file. The `CHANGELOG.md` and `PROJECT_CONTEXT.md` that were written in French are now `CHANGELOG.fr.md` and `PROJECT_CONTEXT.fr.md`. No change to the program.

### Fixed

- Packages: the `.deb` package and the Windows installer shipped only the French user manual, so the Help tab opened the French manual whatever the interface language. They now include the four manuals (`docs/planche-contact-manual*.html`: French, English, German, Spanish) as well as the README and the CHANGELOG in both languages (`README.md`/`README.fr.md`, `CHANGELOG.md`/`CHANGELOG.fr.md`; under `/usr/share/doc/planche-contact/` for the `.deb`, next to the executable for Windows).

## [5.1.10] - 2026-10-08

Versions 2.1.0 to 5.1.10 were published without a CHANGELOG section of their own: their changes are
listed together below, as they had been gathered under "Unreleased" until this release. The notes
of each version are on the GitHub Releases page.

### Added

- **"Advanced" section in the graphical interface, for layout, captions and graphic theme** (specification §2/§4, following the `--profile` option already available in the CLI): collapsed by default (`Gtk.Expander`), separate from the existing simple settings (number of photos/format, unchanged). Exposes the layout template (grid/landscape/portrait/large thumbnails/free, with columns/rows for the free template), the orientation, the thumbnail fit mode, the margins/spacings, the position/area/number of lines/font/alignment of the captions and the fields to display (filename, date, camera, lens, focal length, 35 mm equivalent focal length, aperture, speed, ISO, dimensions, GPS position - with a dedicated warning, disabled by default), and the custom colors of the graphic theme (the choice of the theme itself - Light/Dark/Neutral/System - is made in the main window, see "Fixed" below). "Save profile…"/"Load a profile…" buttons (native file chooser) to reuse a set of settings from one session to the next. A profile is passed to the CLI (`--profile`, temporary file) only if it really differs from the default behavior - no change for anyone who never opens this section.
- **Real preview before generation** (specification §3): a "Preview the sheet…" button shows, in a dedicated window, the sheet as it will actually be produced (layout, captions, theme and watermark included), on the first photos of the input folder - with the same number of photos as the real generation would place on it (reduced by the "large thumbnails" template where applicable). The generation is done in a separate CLI subprocess (new internal option `--preview-output`, which produces a single sheet as a PNG and then stops, without ever touching the real output folder or generating a PDF/CSV/HTML gallery) rather than directly in the graphical application: an initial attempt with a direct call, in a background thread of the application, revealed in use a real race between the text rendering of Pillow (title/page number) and Pango (text of the GTK interface itself, whose main loop stays active in the meantime) on the FreeType library shared by the two - which could corrupt the computation of a glyph's size to the point of making the rendering fail. The subprocess, entirely free of any window or GTK loop, eliminates this race structurally.
- **New `--profile file.json` option** (specification §2/§4.4): loads a reusable layout/captions/theme profile (see `portfolio/presentation/profile.py`, `save_profile()`/`load_profile()`) and applies it to the generation (JPEG/PDF sheets and HTML gallery). A missing, unreadable or invalid file silently falls back to the default profile (current behavior unchanged), without ever interrupting the generation. When used together with `--format`/`--num`: these only take precedence over the profile if they are explicitly different from their default value AND the profile has not already customized that same setting (otherwise the profile, being more specific, silently wins - see `Config.__post_init__`). No graphical interface yet to create these profiles (later step): to be written/edited by hand for now.
- **HTML gallery: download of the full-size original** (new option, disabled by default), reported by the user: the viewer's ⇩ button only downloaded the displayed copy, reduced to 2000 px. With the "Full-size originals in the gallery" checkbox (main window, on the HTML gallery line, grayed out if the latter is unchecked) or `--html-originals` on the command line, the photos are attached at full resolution in `gallery/originals/`: JPEG, PNG, TIFF... files are copied **as is** (byte for byte, no recompression, EXIF intact) and **RAW files are converted to full-size JPEG** (see below), then the button downloads them under their name (tooltip "Download the original (full size)"). Without the option, nothing changes: no `originals/` folder, same marking as before. Design points:
  - Unique names in `originals/` (`IMG_1.jpg`, `IMG_1_2.jpg`..., case ignored for Windows/macOS): two photos with the same name in two subfolders (`-r`) never overwrite each other; the download keeps the original name.
  - Encoded URLs (spaces, accents, `#`, parentheses); if copying an original fails (disk full...), the photo stays in the gallery, no truncated file remains and the download falls back to the displayed copy.
  - **No RAW file in the gallery, ever** (requested by the user: a downloaded RAW cannot be opened by an ordinary visitor): a RAW (`.cr2`, `.cr3`, `.nef`, `.dng`, `.arw`) is converted to JPEG at the full sensor resolution, under the same name with a `.jpg` extension (`IMG_1.CR2` → `originals/IMG_1.jpg`, offered for download under that name). Source image: the JPEG preview embedded in the RAW if it covers at least 98% of the sensor resolution (it is the camera's own rendering, and it is almost instantaneous), otherwise full demosaicing (`rawloader.load_full_resolution()`, never a smaller preview passed off as the original); the same decoding serves the displayed copies, so there is a single demosaicing per photo. JPEG quality 95 in 4:4:4, orientation applied to the pixels (and removed from the EXIF), EXIF and color profile of the preview kept when there is one. If the conversion fails (disk full...), the photo stays in the gallery, the download falls back to the displayed copy and the RAW is **never** copied instead; an unreadable RAW (`rawpy` module missing...) is, as before, left out of the gallery. A RAW + JPEG pair with the same name gives `IMG_1.jpg` and `IMG_1_2.jpg`, neither overwrites the other. Verified on real DNG files decoded by LibRaw (command-line generation: 3000 × 2000 px JPEG originals with the right colors, 0 RAW files in the gallery folder; then download of the originals in a real Chromium: file identical to the one in the folder, `.jpg` name, JPEG signature) and locked in by 19 additional test cases (full suite: 1196 instead of 1177), including an end-to-end test on a real 160 × 120 px DNG (`tests/data/mini_raw.dng`, skipped if `rawpy` is missing).
  - The gallery becomes noticeably bigger (checkbox tooltip and manual). **The originals do not carry the watermark**: a warning is written to the log (hence to the interface's log) when a watermark is also requested.
  - Opened over `file://` (double-click), the gallery cannot read the neighboring file through `fetch()` (browser security restriction, already documented): each original is therefore accompanied by a small `.js` sidecar file that still allows the download with a save dialog (see "Fixed" below). Through a web server, the download is direct and these sidecar files are unnecessary.
  - Verified in a real Chromium on 6000×4000 photos (HTTP: downloaded file byte-for-byte identical to the source) and in the real GTK window (the checkbox adds neither width nor height to the form, in French and in German). Locked in by 10 new tests (`tests/test_htmlgallery.py`, `tests/test_portfolio_cli.py`), checked by neutralizing each of the nine changes. Manuals (×4), interface/CLI texts (×4 languages) updated.
- **Contact sheets and PDF: "Developed by Gilles MAGNEVILLE, under the GNU GPL v3 license" notice** below "Sheet generated by Planche-Contact", reported by the user: this second line had only been added to the footer of the HTML gallery, never to the footer of the sheets (the PDF reuses the sheet images and draws no text, so it lacked it too). The footer now has three centered lines (sheet number, credit, developer/license), translated into the 4 languages with the same text as the gallery (`sheet.footer_credit`/`gallery.footer_credit`, parity test); the developer's name is defined only once (`utils.AUTHOR_NAME`, reused by the HTML gallery and the "About" tab).
  - Reserved space below the grid: the positions of the three lines and the reserved height (`FOOTER_*` in `presentation/layout_engine.py`, ~10.7 mm) come from a single source, and the usable area of the grid stops above the footer (`PageLayout.content_bottom_px`, also used for vertical centering). With the default margin (12 mm) and any margin of at least 11 mm, the layout is strictly unchanged (compared with the old version over 1,000 combinations of format, orientation, template, number of photos and margin: 0 differences); below that, the grid is slightly reduced instead of going under the text, as was already the case with a very small margin.
  - The sheet number remains optional; the two notices are always displayed.
  - Verified on real sheets (A4 and A5, light and dark themes, French/German/English/Spanish, 2 mm margin) and on the generated PDF; locked in by 175 new test cases (parameterized ones included: width and centering of the line in each language, secondary color, parity with the gallery, no photo in the footer area for margins from 0 to 20 mm).

### Fixed

- **HTML gallery viewer opened by double-click (`file://`): the download button only opened the image in a new tab, instead of the "Open / Save" dialog**, reported by the user ("which was not the case in the previous version", then "still no dialog box"). Cause: with the previous version of the "originals" option, a RAW was copied as is; since the browser could not display it, `window.open()` made it open its "Open / Save file" dialog - a side effect, never intended, of the file type. Now that RAW files are converted to JPEG (a deliberate change), the browser simply displays the image. In `file://`, the behavior had in fact never been a real download.
  - **Solution adopted (chosen by the user among several): one sidecar file per original.** In `file://`, neither `fetch()`, nor XHR, nor `<canvas>` can read a neighboring image ("opaque" origin, CVE-2019-11730) and Chromium ignores the `download` attribute of a `file://` link; a neighboring `<script src>`, however, loads without restriction. Each original `originals/IMG_1.jpg` is therefore accompanied by `originals/IMG_1.jpg.js`, which contains the file in base64 inside a `pcOriginalLoaded(name, base64)` call (`htmlgallery._write_download_script()`, written in 3 MB blocks so that a large file is never loaded into memory). The button injects this script, rebuilds the original as a `Blob` and downloads it through a `blob:` link with its real name (`downloadOriginalFromScript()`): browsers always honor `download` for a `blob:`, so the browser's save dialog appears, on double-click as before, without a server.
  - HTTP(S) unchanged (`fetch()` → `Blob`, file identical to the original); the `.js` files are useless there and can be deleted before publishing online. Without the "originals" option, no sidecar file. An original whose sidecar file is missing or truncated (script not found, loading error) falls back to the old behavior: download link to the image, opened in a new tab if the browser does not save it (`target="_blank"`: the gallery is never left). A failure to write a sidecar file invalidates neither the original nor the photo.
  - **Cost**: the sidecar file weighs about 133% of the original (base64), i.e. nearly +33% of weight for the gallery with the "originals" option; stated in the manuals (×4).
  - Verified in a real Chromium: `file://` (actual download, correct name, names with accents/`#`, file byte-for-byte identical to the original, 28 MB original in about 1 s), HTTP, and each of the fallbacks; as well as on a gallery generated from real DNG files. **Confirmed by the user in Firefox 140.17.0 ESR (64-bit)**: the save dialog appears on double-click. Not verified by the developers in Firefox (no usable Firefox in the development environment): other versions and browsers remain to be confirmed.
  - Locked in by 8 new tests, one of which replaces the one for the plain download link (full suite: 1204 instead of 1197; content and name of the sidecar file, sidecar of a converted RAW, original larger than 3 MB decoded identically, write failure with no effect on the original, `file://` branch of the viewer and its fallback, no sidecar without the option) and one existing test adapted (`tests/test_portfolio_cli.py`); checked by neutralizing each of the 11 changes.
  - The message displayed in the viewer remains worded exactly in every case ("If nothing was downloaded, the image opened in a new tab..."), translated into the 4 languages; manuals (×4) updated.

- **Latent, not yet reachable from the interface**: the pagination in `portfolio.py` (`main()`) distributed the photos in batches of `config.num_per_sheet` directly, without taking into account the reduction that the "large thumbnails" template ("large_thumbs") may apply to itself (see `presentation.layout_engine.compute_effective_per_page`) to guarantee large thumbnails whatever the requested number. The surplus photos of a page that was too full would have been silently lost (never carried over to an additional page) - fixed by paginating on this EFFECTIVE number rather than on the raw setting. No regression is possible today (the CLI does not yet expose a template/Profile selection - the upcoming `--profile` step), fixed in anticipation and locked in by a new test (`tests/test_portfolio_cli.py`, which does fail without the fix: 1 page generated instead of the 3 expected for 20 photos).
- **Three texts stayed fixed in French whatever the chosen language (`--language`/graphical interface)**, found during a full load test (60 photos, advanced profile with dark theme + captions + watermark, `--language en`): the page number and the "Sheet generated by Planche-Contact" notice drawn directly on each JPEG/PDF sheet (`contactsheet.py`, never connected to `portfolio.i18n`), the header of the CSV index (`csvindex.py`, "Numéro"/"Fichier" hard-coded), and the file-size units displayed in the HTML gallery viewer (`utils.format_file_size()`, always "Ko"/"Mo" with a decimal comma). The four languages now have the corresponding keys (`sheet.*`, `csv.*`, `unit.*`), verified identical in the 4 language files and tested end to end in the 4 languages (sheet, CSV and HTML gallery).
- **Deeper cause of the file-size bug above**: the HTML gallery regenerates the full-size images/thumbnails in separate worker processes (`ProcessPoolExecutor` in `spawn` mode, for the same performance reasons as the generation of the sheets). `spawn` starts an entirely new Python interpreter per worker, which inherits no state from the main process: `set_language()` (called only once at CLI startup) had therefore never taken place in these workers, and every `_()` there silently fell back to English - visible only outside French (the current fallback language of `_()`... but the English of the bug above made it visible). Fixed by explicitly propagating the already-resolved language into the `initializer` of the `ProcessPoolExecutor` (the same mechanism already used to reconfigure logging in these workers), which applies it through `set_language()` before any processing. Point of attention for any future addition of translated text in code run by these workers (`contactsheet.py`/`thumbnail.py` are protected for now: all their translated text runs in the main process).
- **Overlapping, unreadable captions on contact sheets (JPEG/PDF)**, reported by the user. Two distinct defects in the drawing of the captions (`contactsheet.py`/`presentation/layout_engine.py`), both present since the introduction of customizable captions and never covered by the existing tests (which never combined several fields on one line, nor several lines with a large font):
  - **Horizontal overflow** (the most visible case, from the default configuration of a multi-field caption): `_draw_caption()` never limited the width of the drawn text to that of the cell - several fields joined on the same line (e.g. filename + date + camera + ISO) produced text much wider than a thumbnail, which then overflowed massively into the neighboring columns, to the left as well as to the right. Fixed at first by truncation with an ellipsis ("…") as soon as a line exceeds the available width (new function `_fit_text_to_width()`) - this avoided any overlap but in practice cut off the information: replaced by wrapping, see the next entry (truncation only remains as a last safety net).
  - **Vertical overflow** (less visible, requires several lines and/or an enlarged font): the height reserved for the caption followed only `caption_area_mm` (an independent setting, which stayed at its default value of 8 mm if the user increased `lines`/the font size without thinking about it), so that the last lines overflowed into the photo of the next row. `layout_engine._reserve_caption_px()` now reserves the MAXIMUM between `caption_area_mm` and the height actually needed for the configured number of lines/font size - never the first value alone.
  - The constant for the spacing between two caption lines (previously duplicated: `+ 4` hard-coded independently in `contactsheet.py` and implicitly assumed by the layout engine) is now centralized (`presentation.CAPTION_LINE_SPACING_PX`), so that the two can no longer diverge.
  - The PDF (`portfolio.pdf`) directly embeds the same JPEG images as the contact sheets: this fix therefore applies to it too, with no separate change. The HTML gallery was not affected (the text there follows the browser's normal flow, which wraps a caption that is too long rather than letting it overflow).
  - Locked in by 3 new tests (`tests/test_contactsheet.py`, `tests/test_layout_engine.py`), which do fail without the fix.
- **Caption information truncated by "…" below the photos (JPEG/PDF contact sheets)**, reported by the user right after the overlap fix above: the ellipsis truncation it had introduced did remove any overlap, but in practice cut off most multi-field captions (default setting "Text lines" = 1: all the checked fields on ONE single line, much wider than a thumbnail - a large part of the information disappeared). Captions now wrap: `presentation.captions.layout_caption_lines()` fills the lines field by field, wrapping BEFORE the field that would exceed the width of the thumbnail. A field is never cut in two as long as it fits alone on a line; a field too long on its own (e.g. a lens name) wraps at the spaces; the separator never appears at the beginning or end of a line. "Text lines" remains the number of lines over which the fields are first distributed (result strictly identical to before when everything already fits), but the number of lines actually displayed can now be higher.
  - This number of lines depends on the actual text, hence on the width of the thumbnail, itself dependent on the height reserved for the captions: `ContactSheetGenerator._plan_page()` measures the wrapped text and then recomputes the layout until it is stable (`compute_page_layout(..., caption_lines=...)`, capped at 10 lines). The thumbnails shrink just enough to reserve the necessary height - never any overlap. Each sheet thus adjusts the caption height to its own photos (a page where one photo has a very long lens name may have slightly smaller thumbnails than the previous one).
  - The "…" truncation only remains as a last safety net: a single word wider than the cell, or surplus lines beyond the available height (typically a "right" caption on a small thumbnail).
  - Without a caption, no EXIF metadata is read (unchanged, locked in by a test). The PDF reuses the same JPEGs and benefits automatically; the HTML gallery was not affected (the browser handles wrapping itself).
  - Locked in by 12 new tests (`tests/test_captions.py`, `tests/test_layout_engine.py`, `tests/test_contactsheet.py`).
- **Theme choice impossible to find in the main window**, reported by the user: the Light/Dark/Neutral/System menu only existed in the "Advanced settings" section, collapsed by default - for such a common visual setting, it was not discoverable. It is now in the main window ("Theme" list, on the watermark opacity line, with a tooltip describing the four modes); the advanced section only keeps the custom colors ("Theme colors"), which replace those of the chosen theme. This menu is the ONLY widget for the theme mode (no duplicate to keep in sync): it feeds the Profile as before (`_profile_from_widgets()`/`_apply_profile_to_widgets()`), so that saved/loaded profile, preview, "Reset" and the passing to the CLI (`--profile`, only if the profile differs from the default) work without any other change - verified by driving the real interface under GTK4/Xvfb. `gen.theme_*` translation keys added in the 4 languages, `adv.theme_mode*` removed.
  - **"System" mode wrongly described in the manual (4 languages)**: it claimed that the sheets/PDF followed the operating system's preferences. This is wrong: a JPEG/PDF sheet is a still image and `resolve_theme()` is never called with `prefer_dark` - they stay light in this mode; only the HTML gallery follows each visitor's browser. Manuals corrected (the old menu label, "System (HTML gallery only)", already said so) and tooltip added.
  - Tooltip on "Text lines": specifies that the text wraps by itself if it is too wide (see above).
  - New `tests/test_i18n.py` (6 tests): same keys in the 4 languages, every literal translation key used in the code exists, theme menu options translated in each language.
- **Gap between a landscape photo and its caption (JPEG/PDF sheets)**, reported by the user: a thumbnail keeps its proportions (`Image.thumbnail`), so a 4:3 photo only occupies three quarters of its square cell, stuck at the top left, whereas the caption started below the CELL - a gap of a quarter of a thumbnail separated them (and a portrait photo stayed aligned to the left above a centered caption). The photo is now placed against its caption (`contactsheet._thumb_offset()`): aligned at the bottom for "below the photo", at the top for "above", against the caption for "right"; horizontally it follows the text alignment (left/center/right). The gap moves to the side opposite the caption: each photo is grouped with its text and the captions stay aligned from one photo to the next.
  - A small deliberate gap (`presentation.CAPTION_PHOTO_GAP_PX`, ~1.5 mm) is reserved between the photo and its text by the layout engine, IN ADDITION to the text area (which stays exactly the "Caption area (mm)"): it is added to the step between rows/columns, so the thumbnails shrink very slightly when a caption is displayed. Without it, the tops of the letters almost touched the edge of a photo that fills its cell.
  - With no caption actually drawn (position "None", or no field checked), nothing changes: same positions and same sizes as before (locked in by tests).
  - Locked in by 14 new tests (`tests/test_layout_engine.py`, `tests/test_contactsheet.py`); 3 existing tests (caption exactly stuck to the photo) updated to include the gap.
- **"Fill" (thumbnail fit mode) cropped nothing**, noticed while preparing the previous fix: the "Photo fit" setting (Whole / Fill) of the advanced section was indeed saved in the Profile (JSON, preview, saved profiles) and described in the manual, but no rendering code read it - the thumbnails were always "Whole". It is now wired end to end: in "Fill" mode (`fit_mode="cover"`), each photo is center-cropped to a square to fill its whole cell, with no empty margin (JPEG sheets, hence also PDF and preview). A single cropping rule, `thumbnail.fit_thumbnail_image()`, shared by the parallel generation (`spawn` processes, to which the mode is passed explicitly) and the single-image version. The grid geometry does not change (the cells are already square). "Whole" mode (default) strictly unchanged.
  - A photo smaller than its cell is never enlarged, in either mode (`Image.thumbnail` rule, kept): in "Fill", a photo whose short side is smaller than the cell gives a square smaller than the cell, placed like the other thumbnails. No effect for ordinary camera photos, much larger than a cell.
  - RAW: in "Fill", the RAW's embedded preview is only judged large enough if its SHORT side reaches the target (`rawloader._large_enough(..., fill=True)`) - otherwise the crop would give a square that is too small, and the RAW is then fully demosaiced.
  - The HTML gallery is not affected: its CSS grid keeps the natural proportions of the photos (tooltip and manual updated accordingly).

- Locked in by 17 new tests (`tests/test_thumbnail.py`, `tests/test_contactsheet.py`), including a full sheet rendering in "Whole" vs "Fill", with and without a caption; checked by temporarily neutralizing the wiring (they do fail).
- **Title position, author position and sheet numbering: three Profile settings that were read nowhere**, noticed while checking the other Profile fields after "Fill": `title_position`, `author_position` and `page_numbering` were defined, validated and saved in the JSON, but no rendering code read them (the title and author were always centered, the sheet number always displayed). They are now wired end to end and adjustable in the advanced section ("Layout": "Title" and "Author" menus - Left / Centered / Right / Hidden - and "Number the sheets" checkbox).
  - Sheets (hence also PDF and preview): the title then the author stay one BELOW the other, each aligned according to its own position, on the page margins. "Hidden" removes the line and the grid moves up accordingly (the folder name is then no longer displayed in place of a hidden title). A title or author too long for the usable width is first reduced (down to 28 px for the title, 20 px for the author), then truncated with "…" as a last resort - without this guard, a long right-aligned title would have started outside the page. A text that already fits keeps exactly its original size.
  - "Number the sheets" unchecked: only the "Sheet X/Y" label disappears; the credit notice at the bottom of the page is always displayed.
  - HTML gallery: the title and author of the header also follow their position (CSS alignment, or line removed if "Hidden"; the browser tab title is kept). The gallery's image counter and pagination do not change: sheet numbering only concerns the sheets and the PDF.
  - Default settings (title and author centered, numbering checked): sheet rendering pixel-for-pixel identical, HTML markup identical, default profile still not passed to the CLI.
  - Locked in by 22 new tests (`tests/test_contactsheet.py`, `tests/test_htmlgallery.py`); checked by temporarily neutralizing each of the wirings (they do fail).
- **The advanced settings made the main window taller than the screen**, reported by the user: when unfolded, the advanced section took the window from about 1060 px to 1610 px in height and pushed the "Start generation"/"Quit" buttons out of view. It now opens in a **separate modal window**, through an "Advanced settings…" button in the main window, whose height no longer depends on these settings (about 1075 px, including a minimum of 260 px for the generation log).
  - The content of this window scrolls in its own area (scrollbar), whose maximum height follows that of the screen: on a low screen, the bottom bar - status message and "Close" button - always stays visible. Closed with the button, the cross or the Esc key.
  - The settings are kept from one opening to the next (the window is hidden, not destroyed); they apply to the generation and the preview even if the window has never been opened (default profile unchanged).
  - The messages related to this window (preview with no folder chosen, profile saved/loaded) are displayed in its status bar - the main window's log being hidden while it is open - in addition to the log. The preview and the file choosers open on top of it.
  - No setting, default value or output changes; only the place and the opening of these settings change. Verified under real GTK4 (Xvfb) on a large and a small screen (1280×600: scrollbar active, "Close" button visible), including a preview launched from the advanced window.
- **The main window was still too tall for the screen, and its bottom (log, messages) went off it**, reported by the user after the advanced settings were moved (it was still ~1075 px tall):
  - The "Advanced settings…" button is now on the action buttons line, right after "Start generation" (it used to take a line of its own).
  - The generation log now reserves only 120 px at minimum (260 px before). It remains expandable: it takes back the space gained when the window is enlarged. Main window height: ~1075 px → ~890 px on a large screen.
  - On a small screen, the form (title, folders, photo preview, options) scrolls in a scrollbar area, capped at what the screen can hold; the bottom of the tab - action buttons, progress, log - always stays visible and is never pushed off the screen. The scrollbar is shown only if the form actually scrolls; on a large screen, nothing changes (no scrollbar, window sized to its content). Measured under real GTK4: window 659 px tall on a 768 px screen, 517 px on a 600 px screen (against ~1075 px).
  - Advanced settings window, made narrower: ~1260 px → ~990 px wide (settings rows recomposed - columns/rows of the Free template under the template, title/author/numbering on one line - and caption fields on 4 columns instead of 6). Previously, a 1366 px wide screen would have required a horizontal scrollbar for a few pixels. No setting is modified.
  - Manual (×4): the main window paragraph wrongly stated that it "opens maximized by default"; it opens at the size of its content (no maximization in the code). Fixed and completed.
- **The set of photos was not centered on the pages of the contact sheets (hence of the PDF)**, reported by the user. Two cumulative causes:
  - The grid started at the left margin and at the top of the usable area. But the size of the thumbnails is limited by the width OR by the height: the grid is almost always less wide (or less tall) than the available area, and all the empty space stayed on one side only - up to ~6 cm on the right (A4 portrait, 8 photos), ~7 cm below the grid (A4 portrait, 16 photos), even 12 cm on the right in A4 landscape with captions. 209 of the 384 tested format/orientation/template/photos-per-sheet/caption combinations were off-center. The empty space is now split in equal parts: horizontally by the layout engine (`compute_page_layout()`, which also exposes the footprint of the grid, `PageLayout.grid_w`/`grid_h`), vertically between the bottom of the header and the bottom margin (`create_contact_sheet()`, the only one to know the real height of the header). The grid never goes into a margin.
  - Without a caption, each photo was stuck at the TOP LEFT of its square cell: a portrait photo left an empty space on its right, a landscape photo an empty space below it, and the whole looked shifted towards the top and the left even with a centered grid. It is now centered in its cell (with a caption, the placement is unchanged: photo placed against its caption, aligned like the text).
  - The centering is computed on the grid of a FULL page: the last, incomplete page keeps its photos in exactly the same places as the other pages (no jump from one page to the next). Its last incomplete row stays left-aligned, like the previous rows.
  - Measured on 64 sheets actually rendered (A4/Letter, portrait/landscape, grid/large thumbnails, 8 to 30 photos, with and without caption): left/right gap ≤ 1 px, top/bottom gap ≤ 2 px (up to ~2000 px before).
  - The HTML gallery is not affected: its CSS grid is already centered (measured in Chromium at 1000, 1280 and 1920 px wide: identical left/right margins).
  - Locked in by 672 new tests (mostly parameterized) (`tests/test_layout_engine.py`, `tests/test_contactsheet.py`), including full renderings of sheets with landscape, portrait and square photos; checked by neutralizing each of the three changes (they do fail). An existing test, which required the old top-left placement, was updated.
- **The HTML gallery seemed to ignore the theme chosen in the main window**, reported by the user. The requested theme was indeed passed and indeed written into the page (verified: main window → `--profile` → CSS, for the four modes), but a visitor's manual choice - the ◐ button in the footer - was stored in `localStorage` under ONE fixed key, read BEFORE the CSS and taking precedence over it. Now this key is shared by all the galleries opened from the same origin (Chrome shares a single `localStorage` between all local `file://` files): one single click on ◐, in any gallery, then made all the following galleries ignore their theme forever, including those regenerated with another theme. Two defects fixed:
  - The visitor's choice is now stored under a key **specific to each generation** of the gallery (`planche-contact-theme-<12 hexadecimal characters>`, identical on all the pages of the same gallery). It therefore follows the visitor from one page to the next of THEIR gallery, but never survives a regeneration: the old fixed key (possibly already present in a browser) is no longer read at all.
  - The ◐ button only alternated light/dark: from a "Neutral" gallery, two clicks left the page in "Light" with no way to get the requested theme back. A second click now removes the stored choice and hands control back to the theme chosen at generation (Light, Dark, Neutral, or "System" which follows the browser again). Same rendering as before for Light and Dark.
  - Verified in a real Chromium (Playwright) for Light/Dark/Neutral/System (with light and dark OS): old stored choice (historical fixed key or key of another generation) ignored; 1st click → opposite theme, stored after reload and on the next page; 2nd click → requested theme, no stored key anymore. The same scenario fails on 9 points with the old code. Locked in by 7 new test cases in `tests/test_htmlgallery.py` (key specific to the generation, shared by all the pages, same key for reading/writing/removal, return to the requested theme), checked by neutralizing each of the four changes.
  - Manual (×4, §3.3): behavior of the ◐ button and scope of the visitor's choice clarified; mistaken "see §6" reference (which does not describe the button) removed.
- **HTML gallery: "Light" theme requested, dark page displayed, despite the previous fix** (new report: "even after clearing the cache"). The generated CSS is light in this case (no profile passed, verified), but the page did not declare its theme to the browser: a browser with automatic dark mode active (Chrome/Edge "Auto Dark Mode for Web Contents" option, extensions) forcibly darkened it - reproduced in Chromium, background `#121212` instead of `#ffffff`. Clearing the cache changes nothing (it is neither the cache nor `localStorage`).
  - Each page now declares its theme in `<meta name="color-scheme">` and in CSS (`:root`, and each `:root[data-theme=...]` variant of the ◐ button so that the declaration follows the visitor's choice): Light and Neutral → `only light`, Dark → `dark`, System → `light dark`. `only light` is the standard refusal of darkening (`light` alone does NOT prevent it: verified). Deliberate side effect: scrollbar and native fields follow the page's theme.
  - **Known limitation** (verified, cannot be worked around from the page): when the "force dark mode" option is enabled unconditionally with an OS/browser set to a LIGHT preference, Chromium darkens the page anyway. With a dark preference (the most common case), the page stays light. Advice added to the manual (×4, §7).
  - Verified in Chromium (28 combinations: normal browser / automatic dark mode × light / dark OS × Light, Neutral, Dark, System, and "Light" without a profile, with and without a click on ◐): only 4 combinations remain darkened, all those of the limitation above. Locked in by 17 new test cases (`tests/test_htmlgallery.py`: declaration per theme, default "Light" case, declaration following the visitor's choice), checked by neutralizing each of the four changes.
- **HTML gallery: two photos with the same name overwrote each other in the displayed copy, and a `#` in a name cut its address** (found while testing the "originals" option on real photos). The displayed copies were stored under the photo's name alone: with `-r` (several memory cards whose numbering restarts from zero) or a RAW + JPEG pair (`IMG_1.CR2` and `IMG_1.jpg` both give `images/IMG_1.jpg`), the second overwrote the first and the viewer showed the same photo twice; and a `#` (or a `%`) in a name made the viewer request a nonexistent file (404 error, missing image).
  - Each displayed copy now has a **unique** name (`IMG_1.jpg`, `IMG_1_2.jpg`..., case ignored), assigned by the main process as for the originals (`_unique_file_name()`), and its address is **encoded**. The name shown to the user (viewer, information) remains the photo's. Nothing changes for simple names without duplicates.
  - Verified in Chromium on a real gallery with a duplicate name and a name with spaces/accents/`#`/parentheses: the 5 images load, all distinct, no 404 request (before: 4 files for 5 photos, one image in 404). Locked in by 3 new tests (`tests/test_htmlgallery.py`), checked by neutralizing each of the five changes.

### Added

- **Graphic theme and customizable captions, now also in the HTML gallery** (specification §1/§4 - after the JPEG/PDF contact sheets): the four themes (Light/Dark/Neutral/System, custom colors included where applicable) and the per-photo captions configured in the Profile (`portfolio/presentation/`) now also apply to the generated HTML gallery, through the same settings as the sheets - no color or caption rule duplicated between the two. The "System" theme lets the visitor's BROWSER decide (CSS media query `prefers-color-scheme`, which reacts even without regenerating the gallery), and a small discreet selector in the footer additionally lets each visitor switch between light and dark themselves in their own browser, independently of the theme chosen for the gallery - their choice is stored (`localStorage`, specific to their browser) and applied as soon as the page loads, without any flicker. The full-screen viewer (lightbox) deliberately stays dark in all cases, independent of the page theme. With no caption configured, the thumbnail grid keeps HTML markup strictly identical to before (no superfluous EXIF reading). Verified with a real Chromium (Playwright): light/dark/neutral rendering, system media query under light and dark preference, manual toggle and persistence after reload, captions actually displayed and HTML-escaped.
- HTML gallery: clicking a thumbnail now opens a full-screen viewer with previous/next navigation (‹ › arrows or keyboard, closing with Esc or a click outside), instead of opening each image in a new tab.
- Enriched HTML gallery viewer: indicator of the page containing the displayed photo, "go to page" field, filename displayed, download button, information panel (actual original resolution, file size, shooting date), full-screen toggle (keyboard shortcuts `I` and `F` in addition to the buttons).
- HTML gallery viewer: zoom from 50% to 200% in steps of 10% (+/- buttons, click on the percentage to reset, keyboard shortcuts `+`/`-`/`0`), automatically reset on each photo change.
- HTML gallery viewer: next/previous photo navigation with the mouse wheel; zoom with the wheel while holding Ctrl, Alt or Cmd (without triggering the browser's native zoom or scrolling the page in the background).
- **Graphical interface translated into English, German and Spanish** (in addition to French), with a language selector in a Preferences dialog reachable from a new menu (hamburger button in the title bar): System language (default, falling back to English with a warning if the detected language is not available), English, Français, Deutsch, Español. A language change takes effect when the application is restarted.
- **The CLI (`portfolio.py`) and the generated HTML gallery are also translated** into the 4 languages: new `--language` option (resolved before the parser is built, so that `--help` is already displayed in the right language), all progress and help messages translated, and the entire generated HTML gallery (header, navigation, viewer, `<html lang="...">`). The graphical interface automatically passes its active language to the generation subprocess, so that the gallery produced always matches the language displayed on screen.
- **The user manual is translated into the 4 languages** (`docs/planche-contact-manual.{en,de,es}.html`, in addition to the existing French version): the Help tab now opens the version matching the application's active language, falling back to French if the file for that language is missing. The project's internationalization is thus complete — graphical interface, CLI, generated HTML gallery and manual.
- HTML gallery: added a developer/license notice ("Developed by Gilles MAGNEVILLE, under the GNU GPL v3 license", translated into the 4 languages) below "Gallery generated by Planche-Contact" in the footer of each page.
- "View results" now works on results already present in the output folder (sheets, PDF, HTML gallery, CSV index from a previous session), without forcing a new generation to reopen them: verified when the output folder field changes and at startup if a folder was remembered. Generation is of course still always possible if desired.

### Changed

- Windows port status updated: validated on a real machine, no apparent bug, published as an official release (`README.md`, `windows/README.md`, `PROJECT_CONTEXT.md`).
- Language selector moved from the About tab to a new Preferences dialog, reachable through a menu (hamburger button in the title bar): the About tab becomes purely informative again, a setting logically having no place there.

### Fixed

- Recursion under Windows: images already generated during a previous run (`planches/`, `gallery/`) could be detected again as source photos (e.g. 185 images counted for 60 real ones), the exclusion based on a textual comparison of paths (`Path.resolve()` + `relative_to()`) failing when the same physical folder is reached through two textually different paths — typically a mapped network drive vs its UNC path equivalent. The comparison is now based on the real identity of the file (`os.path.samefile()`), bounded to the input folder to avoid a system call per level up to the filesystem root on each photo (noticeable on a network share).
- HTML gallery: watermark sometimes cut off at the bottom of the thumbnails (tile pattern with a fixed font size applied separately on a canvas ~6x smaller than the full-size image, producing a disproportionate pattern depending on the exact height of each photo). The thumbnail is now derived by simply resizing the already-watermarked full-size image, guaranteeing an identical (just reduced) rendering.
- Graphical interface progress bar: it partly depended on a French text line ("Planche X/Y") printed by the CLI, which would have broken it in any other language. Removed before translating the CLI — redundant anyway with the `PROGRESS:X/100` marker (never translated) that immediately follows each generated sheet.
- **Regression**: the "Choose..." buttons (input and output folders) no longer opened the folder chooser, with no visible error message. Cause: `_choose_folder()` used `_` as a throwaway variable (`uri, _, label = line.partition(" ")`, reading the GTK bookmarks) in the same method that also calls `_("...")` to translate the dialog title — Python then treats `_` as local to the whole function, causing an `UnboundLocalError` on every click, silently swallowed by PyGObject. Variable renamed to `_sep`; verified that no other function in the file combines the two uses (systematic AST analysis, not only the one that caused the problem).
- HTML gallery viewer: the previous/next arrows (and the wheel, and the keyboard) looped over the photos of the current page only instead of actually moving to the next/previous photo when it is on another page. Navigation now crosses pages (looping over the whole gallery at both ends), automatically opening the right photo on arriving at the next/previous page, with a warning message (translated into the 4 languages) when this crossing loops over the whole gallery rather than a simple page change.
- Changing language in the About tab without restarting the application did not update the language actually passed to the generation subprocess (`self._language` stayed stuck on the startup language, despite the preference being saved correctly): a generation launched right after a language change started again with the old language. Detected by explicitly testing this scenario.
- HTML gallery viewer: the download button opened the image in the current tab (or a new tab) instead of triggering the browser's save dialog. Fixed by going through a `Blob` (`fetch()` + `URL.createObjectURL()`) rather than the plain HTML `download` attribute, unreliable once served over HTTP(S) depending on the browser — verified with a real Chromium (Playwright), actual download and file of identical size to the original. **Remaining limitation, cannot be worked around**: if the gallery is opened directly over `file://` (double-click on `index.html`), Firefox and Chrome equally block any JavaScript solution (`fetch`, `XMLHttpRequest`, reading a `<canvas>`) to access a neighboring file, since a widely adopted security fix (CVE-2019-11730) — an explanatory message is then displayed, inviting a right click "Save image as" or viewing the gallery through a web server for a one-click download.
- HTML gallery viewer: once the image was zoomed, the top bar (filename, actions) disappeared behind it instead of staying visible in the foreground (`transform: scale()` makes the image a "positioned" element that then takes precedence over the fixed bars according to DOM order); scrolling to move around the enlarged image did not work and affected the page in the background instead (default scroll chaining of a container that has nothing to scroll itself). Fixed by giving an explicit `z-index` to each bar/button of the viewer, by adding `overscroll-behavior: contain`, and by replacing the zoom with real width/height in pixels (`transform` only changes the visual rendering, never the layout size taken into account by scrolling) — all three verified with a real Chromium (Playwright).
- EXIF date sorting (JPEG/PNG photos, non-RAW): `DateTimeOriginal`/`DateTimeDigitized` were in fact never read (these tags live in a separate Exif sub-IFD, inaccessible through a direct `Image.getexif().get()`), so the sorting silently fell back to the file's modification date from the start. Discovered while adding the date display in the new viewer, which made it visible.
- HTML gallery viewer: once zoomed, the image appeared stuck at the top left instead of staying centered, and could not be moved with the mouse or touch to examine its other parts (only the wheel worked, through the container's native scrolling). Cause: the previous approach (see above) switched the centering to top-left as soon as zoom was active to make the overflow reachable by scrolling, at the cost of centering and of any drag-and-drop gesture. Replaced by a different approach: the image always stays centered, and a real drag-and-drop (mouse/touch/stylus via Pointer Events) moves its rendering (`transform: translate()`), bounded so that the image can never be moved completely out of view — the wheel, when zoomed, now moves the image the same way rather than relying on a native scrolling that no longer exists. Verified with a real Chromium (Playwright): centering at 200%, dragging at the exact mouse delta, clamping at the four corners, reset on return to 100% or on photo change.
- Contact sheets: the thumbnails of the last row could slightly overflow the physical bottom of the sheet for certain combinations of number of images per sheet / page format (case discovered: 24 images on A4, where the old computation produced 505 px thumbnails overflowing the bottom of the sheet by about 139 px). Cause: `create_contact_sheet()` only subtracted the spacing between thumbnails (5 mm) from the available width to determine the final size of the thumbnails, never from the height, whereas this same spacing does really add up between the rows in the final placement. Of the 55 combinations covered by the settings offered in the graphical interface (5 page formats × 11 values of "photos per sheet" from 8 to 48 in steps of 4), 27 were affected; once fixed, their thumbnails are about 5 to 15% smaller than before depending on the case, whereas the default setting (A4, 12 photos per sheet) was not concerned and remains unchanged. New non-regression tests (`tests/test_contactsheet.py`) covering all these combinations as well as a real end-to-end generation on the case that revealed the bug.

## [1.5.3] - 2026-08-03

### Added

- Procedure to work around the Windows SmartScreen warning at installation, documented for the end user (`windows/README.md`, `README.md`, user manual).
- Transparent mention of the assistance of Claude.ai (Anthropic) in the design of the software, in `README.md`, the user manual and the application's "About" tab.

## [1.5.1] - 2026-08-03

### Added

- User manual: note on the automatic respect of EXIF orientation, mention that the Help tab opens this manual, CLI example with `--html-per-page`.

### Removed

- Diagnostic traces that had become useless: `[DIAG]` lines in `FolderPreviewController` (`planche-contact-gtk.py`) and the console window of the Windows executable (`console=True` in `windows/planche-contact.spec`, set back to `False`).

## [1.5.0] - 2026-08-02

Consolidates all the changes since 1.2.2-rc.1 (Windows port,
custom folder chooser, unified watermark, RAW, images-per-HTML-page slider,
AppStream metadata, and all the associated fixes).

### Added

- Support for RAW files (`.cr2`, `.cr3`, `.nef`, `.dng`, `.arw`), via `rawpy` — installed and bundled automatically in the `.deb`, with no manual step.
- Custom folder chooser (input/output), replacing the native dialog: shows only folders, a 20-thumbnail preview (2 rows) of the hovered folder, clickable breadcrumb, system bookmarks carried over into the sidebar.
- Input folder preview strip in the main window, paginated in batches of 10, with numbered navigation.
- "View results" button (sheets, PDF, HTML gallery, CSV index) opening each item with the system's default application, with a clear message if no application is available for the file type concerned.
- Watermark opacity slider in the interface (0-100%, default 40%), as well as the `--watermark-opacity` command-line argument.
- Sheet header: name of the source folder displayed by default when none of the Title/Author/Watermark fields is filled in.
- "About" tab: mention of the GNU GPL v3 license, developer's name and link to the GitHub repository.
- Windows 10/11 port (`windows/`): PowerShell build script, PyInstaller `.spec` file, NSIS installer, from the same source code as the Linux version (the `portfolio/` engine is strictly identical; the graphical interface only receives a few targeted additions with no effect under Linux/macOS: a startup block telling GTK4 where to find its bundled libraries, and a fallback to `os.startfile` to open a file with the system's default application).
- Entirely rewritten user documentation (`docs/planche-contact-manual.html`) and dedicated Windows build guide (`windows/README.md`).
- "Images per page" slider for the HTML gallery in the interface (12 to 64 in steps of 4, on the same line as the "Generate HTML Gallery" checkbox), as well as the `--html-per-page` command-line argument.
- AppStream metadata (`metainfo/planche-contact.metainfo.xml`), installed in `/usr/share/metainfo/`: allows App Center (PackageKit + AppStream, since Ubuntu 26.04) to fully recognize the package.

### Changed

- Unified watermark: a single rendering (tile pattern, orientation, opacity) used in a strictly identical way on the sheets, the PDF and the HTML gallery (previously, three different implementations coexisted, with a visibly different rendering depending on the output).
- More discreet default watermark: reduced size (~30%) and reduced opacity (70% → 40%).
- Main window: opens at its natural minimum size rather than an imposed fixed size, while remaining resizable.
- Grouping of fields to reduce the height of the form: Project title and Author name on the same line; Images per sheet, Sheet format, Watermark and Orientation on the same line.
- Project title, Author name, Input folder and Output folder fields: fixed, reasonable width instead of stretching across the whole width of the window.
- Top margin of the contact sheets and PDF reduced, space between the header and the thumbnail grid enlarged.
- Font loading made cross-platform (Linux/Windows/macOS) instead of a hard-coded Linux path.
- Project name made uniform as "Planche-Contact" (instead of "Planche-Contact Linux") in the README and this log, the project no longer being limited to Linux.
- "Contact sheets" button of the "View results" menu: now opens the `planches/` folder (file manager) rather than an individual image — identical behavior whatever the number of sheets generated.

### Fixed

- Output folder not created automatically before generation, causing an error if the folder did not exist yet.
- Permissions of the files bundled in the `.deb` depending on the build machine's `umask`, which could make the application unreadable for a normal user once installed.
- Application icon missing from the `.deb` (the script looked for a file at a nonexistent path); now installed in several sizes (48 to 256 px).
- Project `VERSION` file that could be incremented even if the build failed, putting the displayed version number out of sync with the content actually published.
- Main window enlarged by ~90 px right after being displayed (while the input folder preview loaded), preventing proper vertical centering by the window manager on opening.
- Bundled font not applied on the contact sheets nor the PDF (it only worked for the HTML gallery): the header and footer of the sheets loaded a hard-coded font path instead of going through `utils.get_font()`.
- HTML gallery: EXIF orientation not respected, all photos displayed in landscape at the sensor size whatever their real framing — `ImageOps.exif_transpose()` was no longer called since the switch to single decoding (full-size image + thumbnail).
- `.deb`: the `postinst`/`postrm` scripts were in fact never run by dpkg (they landed as plain inert data files in `/DEBIAN/`, `fpm` not recognizing this folder as a native `dpkg-deb --build` would) — no check of the bundled Python environment had therefore ever taken place at installation.
- `.deb`: bundled venv that could be incomplete (e.g. `reportlab` missing) depending on what was already installed system-wide on the build machine, `pip install` silently skipping the local copy in a `--system-site-packages` venv without `--ignore-installed`.
- Windows: application size not displayed in *Settings > Apps > Installed apps* — `IntFmt $0 "0xX" $0` (NSIS 2.x syntax that does not work in NSIS 3.x) did not convert the computed size to hexadecimal, `EstimatedSize` systematically falling back to 0.

### Performance

- Decoding of thumbnails and sheets significantly sped up: preference given to the JPEG preview already embedded in RAW files rather than a full demosaicing, and accelerated "draft" decoding for JPEG sources.
- HTML gallery: merging of two redundant decoding passes into one (thumbnail derived from the already-decoded image, no more need to decode the source twice), fully parallelized generation.
- Parallel process cap raised (8 → 64), to better exploit machines with many cores.
- Caching of the watermark font loading, previously reloaded from disk on each call.

---

## [1.2.2-rc.1] - 2026-07-23

### First public Release Candidate

#### Features

- Generation of high-quality (300 dpi) photographic contact sheets.
- GTK 4 graphical interface.
- Generation of a PDF document.
- Generation of a responsive HTML gallery.
- Generation of a CSV index.
- Support for JPEG images as well as many RAW formats.

#### Highlights

- Works without a database.
- Direct processing of image folders.
- Simple and fast graphical interface.
- Free software distributed under the GPL-3.0 license.

---

## [1.2.1] - 2026-07-22

- Change to the "About" tab and improvement of `build-deb.sh`.
- Fix of the version number displayed in the `.deb` and in the "About" tab.

## [1.2.0] - 2026-07-22

- Cleanup of the interface fields, fix of the watermark orientation, copyright symbol added to the watermark.

## [1.1.20] - 2026-07-22

- Change of the number of images per sheet, footer notice added on the sheets, fix of the watermark orientation, improvement of the build script.

## [1.1.17] - 2026-07-22

- Gallery cleared before a new generation.

## [1.1.16] - 2026-07-22

- Optimization of gallery generation and navigation.

## [1.1.11] - 2026-07-22

- Clarification in the description.
- Improved progress indicators.

## [1.1.10] - 2026-07-17

- Gallery improvement: watermark, photo format, layout.

## [1.1.8] - 2026-07-16

- Optimization of the gallery watermark.

## [1.1.5] - 2026-07-16

- Gallery fix.

## [1.1.3] - 2026-07-16

- Optimization of gallery creation and new `build-deb.sh` script.

## [1.1.2] - 2026-07-16

- First import of the project in its current form.

## [1.0.1] - 2026-07-15

### Initial public version

- Addition of the GTK4 graphical interface.
- Addition of PDF and HTML export.
- Improved Debian packaging.
