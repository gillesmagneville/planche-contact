# -*- coding: utf-8 -*-
"""
Non-regression test: the pagination of portfolio.py (main()) must take
into account the possible reduction of the number of photos per page
applied by the "large thumbnails" template ("large_thumbs" - see
presentation.layout_engine.compute_effective_per_page()), rather than
continuing to distribute the photos in batches of `config.num_per_sheet`
directly.

Before this fix, `main()` computed `total_pages` and the size of each
batch from `config.num_per_sheet` (the number requested by the user),
without knowing that ContactSheetGenerator.create_contact_sheet() in
reality never draws more than
`presentation.compute_effective_per_page(profile)` cells per page for
this template (see contactsheet.py, `idx >= effective_per_page` guard):
the excess photos of an overcrowded page were therefore silently ignored,
for good (never carried over to an additional page).

The CLI does not yet have a `--profile` flag (a later step) to select
"large_thumbs" itself: this test therefore builds the Profile "in place
of" main(), by substituting portfolio.portfolio.Config (equivalent, once
that flag is wired, to a `--profile` pointing to such a Profile) - but
does exercise main()'s REAL pagination loop, not a reimplementation of
its computation.
"""
import json
import re
import sys
from dataclasses import replace

from PIL import Image

import portfolio.portfolio as cli_module
from portfolio.config import Config as RealConfig
from portfolio.presentation import Profile, LayoutSettings, ThemeSettings, save_profile
from portfolio.presentation.layout_engine import LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE


def _make_photos(img_dir, n):
    img_dir.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        Image.new("RGB", (800, 600), (90, 140, 200)).save(img_dir / f"img_{i:02d}.jpg", quality=90)


def test_large_thumbs_repaginates_instead_of_dropping_excess_photos(tmp_path, monkeypatch):
    photo_count = 20
    img_dir = tmp_path / "photos"
    out_dir = tmp_path / "out"
    _make_photos(img_dir, photo_count)

    # photo_count (20) > LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE (8): the old
    # computation (based on config.num_per_sheet, here equal to photo_count)
    # would have produced a SINGLE page, which would only ever have drawn the
    # first 8 photos - the other 12 would have been lost without an error
    # message.
    assert photo_count > LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE

    def patched_config(*args, **kwargs):
        # Equivalent, once a future --profile flag is wired, to
        # `--profile large_thumbs.json`: only the template changes, the rest
        # of Config's behaviour (including the legacy synchronisation of
        # Config.__post_init__) remains real.
        cfg = RealConfig(*args, **kwargs)
        cfg.profile = replace(cfg.profile, layout=replace(cfg.profile.layout, template="large_thumbs"))
        return cfg

    monkeypatch.setattr(cli_module, "Config", patched_config)
    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_dir), "-n", str(photo_count)],
    )

    cli_module.main()

    planches = sorted((out_dir / "planches").glob("planche_*.jpg"))
    expected_pages = -(-photo_count // LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE)  # integer division rounded up
    assert len(planches) == expected_pages, (
        "pagination must follow the EFFECTIVE number of photos per page "
        "(reduced by the 'large_thumbs' template), not config.num_per_sheet "
        "directly - otherwise photos would be lost without the slightest "
        "additional page to hold them"
    )


def _capture_config(monkeypatch):
    """Intercepts the REAL Config object built by main() (to inspect it
    afterwards), without changing its behaviour."""
    captured = {}

    def wrapper(*args, **kwargs):
        cfg = RealConfig(*args, **kwargs)
        captured["config"] = cfg
        return cfg

    monkeypatch.setattr(cli_module, "Config", wrapper)
    return captured


def test_profile_flag_is_loaded_and_applied(tmp_path, monkeypatch):
    """--profile (specification §2/§4.4) must load the JSON file and apply
    it as is when --format/--num stay at their default value (no conflict
    to arbitrate)."""
    img_dir = tmp_path / "photos"
    out_dir = tmp_path / "out"
    _make_photos(img_dir, 3)

    profile_path = tmp_path / "mon_profil.json"
    save_profile(Profile(layout=LayoutSettings(template="large_thumbs", per_page=8, page_format="A3")), profile_path)

    captured = _capture_config(monkeypatch)
    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_dir), "--profile", str(profile_path)],
    )
    cli_module.main()

    profile = captured["config"].profile
    assert profile.layout.template == "large_thumbs"
    assert profile.layout.per_page == 8
    assert profile.layout.page_format == "A3"


def test_profile_flag_absent_keeps_default_profile(tmp_path, monkeypatch):
    """Without --profile, the current behaviour (default profile) must not
    change at all."""
    img_dir = tmp_path / "photos"
    out_dir = tmp_path / "out"
    _make_photos(img_dir, 3)

    captured = _capture_config(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["portfolio.py", "-i", str(img_dir), "-o", str(out_dir)])
    cli_module.main()

    profile = captured["config"].profile
    assert profile.layout.template == "grid"
    assert profile.layout.per_page == 12
    assert profile.layout.page_format == "A4"


def test_nonexistent_profile_falls_back_silently_to_default(tmp_path, monkeypatch, caplog):
    """An invalid profile path must never interrupt the generation (see
    presentation.load_profile(), never an exception)."""
    img_dir = tmp_path / "photos"
    out_dir = tmp_path / "out"
    _make_photos(img_dir, 3)

    captured = _capture_config(monkeypatch)
    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_dir), "--profile", str(tmp_path / "absent.json")],
    )
    cli_module.main()  # must not raise any exception

    assert captured["config"].profile.layout.template == "grid"
    assert (out_dir / "planches" / "planche_001.jpg").exists()


def test_explicit_format_overrides_a_profile_left_at_its_default(tmp_path, monkeypatch):
    """Precedence documented in Config.__post_init__: --format prevails
    over the profile ONLY if the latter has not already customised
    page_format (here left at "A4", the default value)."""
    img_dir = tmp_path / "photos"
    out_dir = tmp_path / "out"
    _make_photos(img_dir, 3)

    profile_path = tmp_path / "profil_format_defaut.json"
    save_profile(Profile(layout=LayoutSettings(template="landscape")), profile_path)  # page_format stays "A4"

    captured = _capture_config(monkeypatch)
    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_dir), "--profile", str(profile_path), "--format", "A3"],
    )
    cli_module.main()

    profile = captured["config"].profile
    assert profile.layout.template == "landscape"  # the rest of the profile is preserved
    assert profile.layout.page_format == "A3"  # explicit --format prevails


def test_profile_already_customized_format_wins_over_explicit_format_flag(tmp_path, monkeypatch):
    """Reverse precedence, documented as an explicit limit of the
    heuristic (Config.__post_init__): if the profile ALREADY has a
    page_format different from the default value, --format is simply
    ignored."""
    img_dir = tmp_path / "photos"
    out_dir = tmp_path / "out"
    _make_photos(img_dir, 3)

    profile_path = tmp_path / "profil_format_personnalise.json"
    save_profile(Profile(layout=LayoutSettings(page_format="A2")), profile_path)

    captured = _capture_config(monkeypatch)
    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_dir), "--profile", str(profile_path), "--format", "A3"],
    )
    cli_module.main()

    assert captured["config"].profile.layout.page_format == "A2"


# ====================== PREVIEW MODE (--preview-output) ======================
# Internal use by the graphical interface (planche-contact-gtk.py,
# _on_preview_clicked) - see the comment of the --preview-output argument
# and the docstring of portfolio.portfolio._generate_preview_sheet() for
# the why (subprocess isolation, to avoid a Pillow/Pango concurrency on
# FreeType observed empirically when the preview generation took place
# directly in a thread of the GTK application).

def test_preview_output_generates_single_png_without_touching_real_output(tmp_path, monkeypatch):
    img_dir = tmp_path / "photos"
    out_dir = tmp_path / "out"
    preview_png = tmp_path / "preview.png"
    _make_photos(img_dir, 20)

    monkeypatch.setattr(
        sys, "argv",
        [
            "portfolio.py", "-i", str(img_dir), "-o", str(out_dir),
            "--preview-output", str(preview_png), "-n", "12", "--format", "A4",
        ],
    )
    cli_module.main()

    assert preview_png.is_file(), "the preview PNG must be created at the requested path"
    with Image.open(preview_png) as img:
        # A4 at 300 DPI (see presentation.layout_engine.canvas_size_px):
        # exactly the same geometry as a real sheet in the same format.
        assert img.size == (2480, 3507)

    # Preview mode must never create/touch the REAL output folder
    # (neither planches/, nor portfolio.pdf, nor anything else): only the
    # requested standalone PNG must exist.
    assert not out_dir.exists(), (
        "a preview must never create the real output folder "
        "(otherwise it would behave like a partial generation)"
    )


def test_preview_output_never_overwrites_an_existing_generation(tmp_path, monkeypatch):
    """Non-regression safeguard: if --output points (as is normally the
    case from the graphical interface) to a folder that already contains a
    previous generation, the preview must neither clean it nor overwrite a
    single file of it."""
    img_dir = tmp_path / "photos"
    out_dir = tmp_path / "out"
    preview_png = tmp_path / "preview.png"
    _make_photos(img_dir, 5)

    planches_dir = out_dir / "planches"
    planches_dir.mkdir(parents=True)
    sentinel_planche = planches_dir / "planche_001.jpg"
    sentinel_planche.write_bytes(b"old sheet, must not move")
    sentinel_pdf = out_dir / "portfolio.pdf"
    sentinel_pdf.write_bytes(b"old pdf, must not move")

    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_dir), "--preview-output", str(preview_png)],
    )
    cli_module.main()

    assert preview_png.is_file()
    assert sentinel_planche.read_bytes() == b"old sheet, must not move"
    assert sentinel_pdf.read_bytes() == b"old pdf, must not move"


def test_preview_output_with_no_photos_creates_no_file(tmp_path, monkeypatch, caplog):
    img_dir = tmp_path / "photos"
    img_dir.mkdir()
    preview_png = tmp_path / "preview.png"

    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "--preview-output", str(preview_png)],
    )
    cli_module.main()

    assert not preview_png.exists()


def test_preview_output_respects_profile_flag(tmp_path, monkeypatch):
    """The preview must use exactly the same Profile (layout/captions/
    theme) as a real generation with the same --profile - checked here
    through a dark theme, whose background colour is easy to tell apart from
    the default white on the produced PNG."""
    img_dir = tmp_path / "photos"
    preview_png = tmp_path / "preview.png"
    _make_photos(img_dir, 3)

    profile_path = tmp_path / "profil_sombre.json"
    save_profile(Profile(theme=ThemeSettings(mode="dark")), profile_path)

    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "--preview-output", str(preview_png), "--profile", str(profile_path)],
    )
    cli_module.main()

    with Image.open(preview_png) as img:
        corner_pixel = img.convert("RGB").getpixel((5, 5))
    # Dark theme: the sheet's corner (outside any thumbnail) must be dark,
    # never white/light (default behaviour).
    assert sum(corner_pixel) < 200, (
        f"the --profile (dark theme) was not applied to the preview: "
        f"corner colour {corner_pixel}"
    )


def test_csv_index_header_follows_language_flag(tmp_path, monkeypatch):
    """Non-regression: the header of the CSV index (portfolio/csvindex.py)
    was hard-coded in French ("Numéro"/"Fichier"), whatever --language was -
    found during a full load test with --language en. It must now follow
    the requested language, like the rest of the generated outputs
    (CHANGELOG.md, §6 PROJECT_CONTEXT.md)."""
    img_dir = tmp_path / "photos"
    _make_photos(img_dir, 2)

    out_fr = tmp_path / "out_fr"
    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_fr), "--csv", "--language", "fr"],
    )
    cli_module.main()
    assert (out_fr / "index.csv").read_text(encoding="utf-8").splitlines()[0] == "Numéro,Fichier"

    out_en = tmp_path / "out_en"
    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_en), "--csv", "--language", "en"],
    )
    cli_module.main()
    assert (out_en / "index.csv").read_text(encoding="utf-8").splitlines()[0] == "Number,Filename"


def test_html_gallery_file_size_follows_language_in_worker_process(tmp_path, monkeypatch):
    """Non-regression (a subtler bug than the previous one): the HTML
    gallery regenerates the images/thumbnails in separate worker processes
    (ProcessPoolExecutor, mp_context="spawn" - see htmlgallery.py), which
    inherit NO state from the main process, including the active language
    (portfolio.i18n). The file size displayed in the viewer
    (utils.format_file_size(), called INSIDE the worker) therefore silently
    fell back to English even with --language fr - found during the same
    load test as the test above. Locked down here by directly inspecting
    galleryMeta in the generated HTML, for both languages."""
    img_dir = tmp_path / "photos"
    _make_photos(img_dir, 2)

    def _first_size(out_dir):
        html = (out_dir / "gallery" / "index.html").read_text(encoding="utf-8")
        match = re.search(r"const galleryMeta = (\[.*?\]);", html)
        assert match, "galleryMeta not found in the generated gallery"
        meta = json.loads(match.group(1))
        return meta[0]["size"]

    out_fr = tmp_path / "out_fr"
    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_fr), "--html", "--language", "fr"],
    )
    cli_module.main()
    size_fr = _first_size(out_fr)
    assert "Ko" in size_fr and "," in size_fr, (
        f"file size not translated into French (worker language not propagated): {size_fr!r}"
    )

    out_en = tmp_path / "out_en"
    monkeypatch.setattr(
        sys, "argv",
        ["portfolio.py", "-i", str(img_dir), "-o", str(out_en), "--html", "--language", "en"],
    )
    cli_module.main()
    size_en = _first_size(out_en)
    assert "KB" in size_en and "." in size_en, f"taille de fichier non traduite en anglais : {size_en!r}"


def test_html_originals_flag_adds_full_size_originals_to_the_gallery(tmp_path, monkeypatch):
    """--html-originals attaches the originals to the gallery; without it,
    no originals/ folder is created (historical behaviour)."""
    img_dir = tmp_path / "photos"
    _make_photos(img_dir, 2)

    out_plain = tmp_path / "plain"
    monkeypatch.setattr(sys, "argv", ["portfolio.py", "-i", str(img_dir), "-o", str(out_plain), "--html"])
    cli_module.main()
    assert not (out_plain / "gallery" / "originals").exists()

    out_orig = tmp_path / "orig"
    monkeypatch.setattr(
        sys, "argv", ["portfolio.py", "-i", str(img_dir), "-o", str(out_orig), "--html", "--html-originals"]
    )
    cli_module.main()
    originals_dir = out_orig / "gallery" / "originals"
    # Each original is accompanied by its companion file (double-click
    # download, see htmlgallery._write_download_script).
    assert sorted(p.name for p in originals_dir.iterdir()) == [
        "img_00.jpg", "img_00.jpg.js", "img_01.jpg", "img_01.jpg.js",
    ]
    for name in ("img_00.jpg", "img_01.jpg"):
        assert (originals_dir / name).read_bytes() == (img_dir / name).read_bytes()
        assert (originals_dir / (name + ".js")).read_text(encoding="ascii").startswith(
            'window.pcOriginalLoaded("%s","' % name
        )


def test_html_originals_with_watermark_warns_that_originals_are_not_watermarked(tmp_path, monkeypatch, caplog):
    """A watermark loses its meaning if the originals attached to the
    gallery do not carry it and the user does not know it: explicit warning
    (log + console, hence the interface's log), but only when both options
    are active."""
    img_dir = tmp_path / "photos"
    _make_photos(img_dir, 1)

    def run(name, *extra):
        out = tmp_path / name
        monkeypatch.setattr(sys, "argv", ["portfolio.py", "-i", str(img_dir), "-o", str(out), "--language", "fr", *extra])
        caplog.clear()
        with caplog.at_level("WARNING"):
            cli_module.main()
        return any("ne portent PAS le filigrane" in r.getMessage() for r in caplog.records)

    assert run("a", "--html", "--html-originals", "--watermark", "(c) Moi") is True
    assert run("b", "--html", "--html-originals") is False, "no watermark: nothing to report"
    assert run("c", "--html", "--watermark", "(c) Moi") is False, "no originals: nothing to report"
    assert run("d", "--html-originals", "--watermark", "(c) Moi") is False, "no HTML gallery: nothing to report"
