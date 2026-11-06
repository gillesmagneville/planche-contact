# -*- coding: utf-8 -*-
"""
Non-regression tests for the wiring of the graphical theme and of the
customisable captions (specification §1/§4) in HTMLGalleryGenerator -
same Profile as ContactSheetGenerator (see tests/test_contactsheet.py),
but CSS/HTML rendering rather than PIL: these tests check the MARKUP
produced (expected strings in the generated HTML/CSS), the viewer
('lightbox') being deliberately left out of scope (see
portfolio/presentation/themes.py - it intentionally stays dark,
independent of the theme chosen for the page).

A complementary visual check (Playwright screenshots, light/dark/system
theme, manual toggle, persistence) was also carried out manually while
developing this wiring - see CHANGELOG.md.
"""
import base64
import filecmp
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote, unquote

import pytest
from PIL import Image, JpegImagePlugin
from PIL.ExifTags import IFD

from portfolio.config import Config
from portfolio.thumbnail import ThumbnailGenerator
from portfolio.htmlgallery import HTMLGalleryGenerator
from portfolio.i18n import _
from portfolio.presentation import (
    Profile, LayoutSettings, CaptionSettings, ThemeSettings, ThemeCustomColors, get_palette,
)


def _make_images(tmp_path, n, *, with_exif=False, color=(90, 140, 200), size=(800, 600)):
    img_dir = tmp_path / "photos"
    img_dir.mkdir(exist_ok=True)
    paths = []
    for i in range(n):
        p = img_dir / f"img_{i:02d}.jpg"
        if with_exif:
            img = Image.new("RGB", size, color)
            exif = Image.Exif()
            exif[0x010F] = "Canon"
            exif[0x0110] = "EOS R5"
            exif_ifd = exif.get_ifd(IFD.Exif)
            exif_ifd[0x829D] = 2.8
            exif_ifd[0x8827] = 400
            img.save(p, format="JPEG", quality=95, exif=exif.tobytes())
        else:
            Image.new("RGB", size, color).save(p, quality=95)
        paths.append(p)
    return img_dir, [{"path": p} for p in paths]


def _generate(tmp_path, images, profile, *, per_page=12, title=None, author=None,
              html_per_page=48, include_originals=False, watermark=None):
    img_dir = images[0]["path"].parent
    out_dir = tmp_path / "out"
    config = Config(
        input_dir=img_dir, output_dir=out_dir, num_per_sheet=per_page,
        page_format="A4", profile=profile, title=title, author=author,
        html_images_per_page=html_per_page, html_include_originals=include_originals,
        watermark_text=watermark,
    )
    gallery_gen = HTMLGalleryGenerator(config, ThumbnailGenerator(config))
    gallery_gen.create_gallery(images, out_dir)
    return (out_dir / "index.html").read_text(encoding="utf-8")


def test_default_profile_grid_markup_is_unchanged(tmp_path):
    """Without any caption configured (default Profile), the grid must keep
    EXACTLY its historical markup (one <a> per photo, no extra wrapper):
    no visual regression for the user who changes nothing."""
    _, images = _make_images(tmp_path, 3)
    html = _generate(tmp_path, images, Profile())

    assert '<div class="gallery-caption">' not in html
    assert '<div class="gallery-item">' not in html
    assert ' <a href="images/img_00.jpg" onclick="return openLightbox(event, 0)">' in html


def test_exif_metadata_is_never_read_when_no_caption_field_is_configured(tmp_path, monkeypatch):
    """Same guard as ContactSheetGenerator (see test_contactsheet.py): no
    costly EXIF read per photo if no caption is requested."""
    import portfolio.htmlgallery as htmlgallery_module

    def _boom(_path):
        raise AssertionError("get_exif_metadata() must not be called without a configured caption")

    monkeypatch.setattr(htmlgallery_module, "get_exif_metadata", _boom)

    _, images = _make_images(tmp_path, 3)
    _generate(tmp_path, images, Profile())


def test_captions_are_rendered_when_configured(tmp_path):
    """EXIF captions actually read from each SOURCE photo (specification
    §1) and displayed under each thumbnail of the grid."""
    _, images = _make_images(tmp_path, 2, with_exif=True)
    profile = Profile(captions=CaptionSettings(fields=["filename", "camera", "aperture", "iso"], lines=2))
    html = _generate(tmp_path, images, profile)

    assert '<div class="gallery-item">' in html
    assert '<div class="gallery-caption">img_00.jpg · Canon EOS R5<br>f/2.8 · ISO 400</div>' in html


def test_caption_text_is_html_escaped(tmp_path):
    """A file name containing special HTML characters must never break the
    markup nor allow an injection."""
    img_dir = tmp_path / "photos"
    img_dir.mkdir()
    tricky_name = "a_<b>_&_amp.jpg"
    p = img_dir / tricky_name
    Image.new("RGB", (800, 600), (90, 140, 200)).save(p, quality=95)
    images = [{"path": p}]

    profile = Profile(captions=CaptionSettings(fields=["filename"]))
    html = _generate(tmp_path, images, profile, per_page=1)

    after = html.split('<div class="gallery-caption">')[1]
    caption_content = after.split('</div>')[0]
    assert caption_content == "a_&lt;b&gt;_&amp;_amp.jpg"


def test_light_theme_is_the_default_and_never_emits_a_media_query(tmp_path):
    """The "light" theme (Profile default) must match the shared palette
    exactly (portfolio/presentation/themes.py) - and a fixed mode must never
    depend on the visitor's system preferences (see visual check: OS in
    dark mode, page stayed light)."""
    _, images = _make_images(tmp_path, 2)
    html = _generate(tmp_path, images, Profile())

    light = get_palette("light")
    assert f":root {{ --bg: {light.background}; --text: {light.text}; " in html
    assert "@media (prefers-color-scheme: dark)" not in html


def test_dark_theme_fixed_mode_never_emits_a_media_query(tmp_path):
    _, images = _make_images(tmp_path, 2)
    profile = Profile(theme=ThemeSettings(mode="dark"))
    html = _generate(tmp_path, images, profile)

    dark = get_palette("dark")
    assert f":root {{ --bg: {dark.background}; --text: {dark.text}; " in html
    assert "@media (prefers-color-scheme: dark)" not in html


def test_system_mode_emits_prefers_color_scheme_media_query_with_dark_palette(tmp_path):
    """Only the "system" mode must let the BROWSER choose (specification
    §4) - strategy documented in themes.py: combine the light and dark
    palettes on either side of a CSS media query."""
    _, images = _make_images(tmp_path, 2)
    profile = Profile(theme=ThemeSettings(mode="system"))
    html = _generate(tmp_path, images, profile)

    light = get_palette("light")
    dark = get_palette("dark")
    assert f":root {{ --bg: {light.background};" in html, "light fallback while the media query does not apply"
    media_block = html.split("@media (prefers-color-scheme: dark)")[1].split("}")[0]
    assert dark.background in media_block
    assert dark.text in media_block


@pytest.mark.parametrize("mode", ["light", "dark", "neutral", "system"])
def test_theme_toggle_and_all_three_overrides_are_always_present(tmp_path, mode):
    """The discreet theme selector (specification §4) must always let the
    visitor switch manually, whatever the default mode chosen for the
    gallery - checked visually: switch on click, persistence after reload
    (localStorage)."""
    _, images = _make_images(tmp_path, 2)
    profile = Profile(theme=ThemeSettings(mode=mode))
    html = _generate(tmp_path, images, profile)

    assert 'class="theme-toggle" onclick="toggleTheme()"' in html
    for palette_mode in ("light", "dark", "neutral"):
        palette = get_palette(palette_mode)
        assert f':root[data-theme="{palette_mode}"] {{ --bg: {palette.background};' in html


def _theme_keys(html):
    """All the theme localStorage keys cited in a page, without duplicates
    (the historical fixed key, without suffix, included)."""
    return set(re.findall(r"planche-contact-theme[0-9a-f-]*", html))


def test_visitor_theme_choice_is_stored_under_a_per_generation_key(tmp_path):
    """Regression: a visitor's manual choice (◐ button) was stored under ONE
    fixed key, shared by all the galleries opened from the same origin
    (Chrome shares a single localStorage between all local files). A single
    click was therefore enough to make the theme chosen in the main window
    be ignored for good - including for a gallery regenerated with another
    theme. The key must now be specific to EACH generation."""
    _, images = _make_images(tmp_path, 2)
    profile = Profile(theme=ThemeSettings(mode="dark"))
    first = _theme_keys(_generate(tmp_path / "a", images, profile))
    second = _theme_keys(_generate(tmp_path / "b", images, profile))

    assert len(first) == 1 and len(second) == 1
    (key_a,), (key_b,) = first, second
    assert re.fullmatch(r"planche-contact-theme-[0-9a-f]{12}", key_a)
    assert key_a != key_b, "two generations must never share a visitor's choice"
    assert "planche-contact-theme'" not in _generate(tmp_path / "c", images, profile), (
        "the old fixed key must never be read again"
    )


def test_theme_key_is_shared_by_every_page_of_one_generation(tmp_path):
    """A visitor's choice must, on the other hand, carry over from one page
    to the next of the SAME gallery: all its pages cite the same key."""
    _, images = _make_images(tmp_path, 5)
    _generate(tmp_path, images, Profile(), html_per_page=2)
    pages = sorted((tmp_path / "out").glob("*.html"))

    assert len(pages) == 3
    keys = [_theme_keys(page.read_text(encoding="utf-8")) for page in pages]
    assert all(len(k) == 1 for k in keys)
    assert keys[0] == keys[1] == keys[2]


@pytest.mark.parametrize("mode", ["light", "dark", "neutral", "system"])
def test_theme_toggle_reads_writes_and_clears_the_same_key(tmp_path, mode):
    """The head script (read), the ◐ button (write) and its return to the
    requested theme (removal) must all target the SAME key: otherwise a
    stored choice would stay applied despite the second click."""
    _, images = _make_images(tmp_path, 2)
    html = _generate(tmp_path, images, Profile(theme=ThemeSettings(mode=mode)))

    (key,) = _theme_keys(html)
    assert f"localStorage.getItem('{key}')" in html
    assert f"localStorage.setItem('{key}', next)" in html
    assert f"localStorage.removeItem('{key}')" in html


def test_second_toggle_click_returns_to_the_requested_theme(tmp_path):
    """Regression: the button merely alternated light/dark. From a "Neutral"
    gallery, two clicks left the page "light" with no way of getting back
    the requested theme. An already stored choice must now be REMOVED
    (data-theme attribute deleted), which hands control back to the theme
    chosen at generation."""
    _, images = _make_images(tmp_path, 2)
    html = _generate(tmp_path, images, Profile(theme=ThemeSettings(mode="neutral")))

    toggle = html.split("function toggleTheme()")[1].split("function openLightbox")[0]
    assert "if (current)" in toggle
    assert "document.documentElement.removeAttribute('data-theme')" in toggle
    # The return to the requested theme happens BEFORE any write of a new choice.
    assert toggle.index("removeAttribute('data-theme')") < toggle.index("setAttribute('data-theme', next)")


@pytest.mark.parametrize("mode,declared", [
    ("light", "only light"),
    ("neutral", "only light"),
    ("dark", "dark"),
    ("system", "light dark"),
])
def test_page_declares_its_color_scheme_to_the_browser(tmp_path, mode, declared):
    """Regression: "light theme requested, dark page displayed". Without a
    `color-scheme` declaration, a browser whose automatic dark mode is
    active (Chrome/Edge "Auto Dark Mode for Web Contents", Chrome Android,
    extensions) forcibly darkens a light gallery. `only light` is the
    standardised refusal of this darkening (`light` alone does not prevent
    it - verified in Chromium); the page must declare it both in <meta>
    (before any rendering) and in CSS, for each theme."""
    _, images = _make_images(tmp_path, 2)
    html = _generate(tmp_path, images, Profile(theme=ThemeSettings(mode=mode)))

    assert f'<meta name="color-scheme" content="{declared}">' in html
    baseline = html.split(":root {", 1)[1].split("}", 1)[0]
    assert f"color-scheme: {declared};" in baseline


def test_default_clair_gallery_refuses_forced_darkening(tmp_path):
    """Exact reported case: "Light" chosen in the interface (default
    profile, hence NO --profile passed to the CLI)."""
    _, images = _make_images(tmp_path, 2)
    html = _generate(tmp_path, images, Profile())

    assert '<meta name="color-scheme" content="only light">' in html
    assert ":root { --bg: #ffffff; --text: #000000;" in html
    assert "color-scheme: only light;" in html.split(":root {", 1)[1].split("}", 1)[0]


@pytest.mark.parametrize("override,declared", [
    ("light", "only light"),
    ("dark", "dark"),
    ("neutral", "only light"),
])
@pytest.mark.parametrize("mode", ["light", "dark", "neutral", "system"])
def test_visitor_override_updates_the_declared_color_scheme(tmp_path, mode, override, declared):
    """When the visitor toggles the theme (◐ button), the declaration must
    follow: a page switched to dark must no longer claim to be "light
    only" (the browser would darken it a second time), and vice versa."""
    _, images = _make_images(tmp_path, 2)
    html = _generate(tmp_path, images, Profile(theme=ThemeSettings(mode=mode)))

    block = html.split(f':root[data-theme="{override}"] {{', 1)[1].split("}", 1)[0]
    assert f"color-scheme: {declared};" in block


def test_custom_accent_color_is_applied_to_every_theme_override(tmp_path):
    """A custom colour (specification §4.3) applies consistently to ALL the
    light/dark/neutral variants of the selector, not only to the default
    theme chosen for the page."""
    _, images = _make_images(tmp_path, 2)
    custom = ThemeCustomColors(accent="#ff00aa")
    profile = Profile(theme=ThemeSettings(mode="light", custom=custom))
    html = _generate(tmp_path, images, profile)

    assert html.count("--accent: #ff00aa;") == 4  # :root + the 3 data-theme overrides


def test_lightbox_styling_is_independent_of_the_page_theme(tmp_path):
    """The viewer (lightbox) deliberately stays dark whatever the theme
    chosen for the page (see the design comment in
    portfolio/presentation/themes.py) - also checked visually."""
    _, images = _make_images(tmp_path, 2)
    profile = Profile(theme=ThemeSettings(mode="dark"))
    html = _generate(tmp_path, images, profile)

    assert "background: rgba(0,0,0,0.92);" in html  # background of the .lightbox layer, never var(--bg)


# ---------------------------------------------------------------------------
# Position of the title and of the author (LayoutSettings.title_position/
# author_position): these settings were exposed but never read.
# ---------------------------------------------------------------------------

def test_default_header_markup_is_unchanged(tmp_path):
    """Default (centred) positions: the header keeps EXACTLY its historical
    markup, with no alignment attribute added."""
    _, images = _make_images(tmp_path, 3)
    html = _generate(tmp_path, images, Profile(), title="Mon Titre", author="Jeanne")

    assert "<h1>Mon Titre</h1>" in html
    assert "<p>" in html and "Jeanne" in html
    assert 'style="text-align' not in html.split("</div>", 1)[0].split('<div class="header">')[-1]


@pytest.mark.parametrize("position,css", [("top_left", "left"), ("top_right", "right")])
def test_title_and_author_follow_their_own_position(tmp_path, position, css):
    _, images = _make_images(tmp_path, 3)
    profile = Profile(layout=LayoutSettings(title_position=position, author_position="top_center"))
    html = _generate(tmp_path, images, profile, title="Mon Titre", author="Jeanne")

    assert f'<h1 style="text-align: {css}">Mon Titre</h1>' in html
    # The author keeps their own position (centred: no attribute).
    assert '<p style=' not in html
    assert "Jeanne" in html


def test_author_position_is_independent_from_the_title_position(tmp_path):
    _, images = _make_images(tmp_path, 3)
    profile = Profile(layout=LayoutSettings(title_position="top_center", author_position="top_right"))
    html = _generate(tmp_path, images, profile, title="Mon Titre", author="Jeanne")

    assert "<h1>Mon Titre</h1>" in html
    assert '<p style="text-align: right">' in html


def test_hidden_title_and_author_are_removed_from_the_header(tmp_path):
    _, images = _make_images(tmp_path, 3)
    profile = Profile(layout=LayoutSettings(title_position="none", author_position="none"))
    html = _generate(tmp_path, images, profile, title="Mon Titre", author="Jeanne")

    body = html.split("<body", 1)[1]
    assert "<h1" not in body
    assert "Jeanne" not in body
    # The image counter stays displayed, and so does the tab's <title>.
    assert "<title>Mon Titre</title>" in html
    assert 'class="header"' in body


def test_header_positions_apply_to_every_page(tmp_path):
    _, images = _make_images(tmp_path, 5)
    profile = Profile(layout=LayoutSettings(title_position="top_left"))
    _generate(tmp_path, images, profile, html_per_page=2, title="Mon Titre")

    pages = sorted((tmp_path / "out").glob("*.html"))
    assert len(pages) >= 3
    for page in pages:
        assert '<h1 style="text-align: left">Mon Titre</h1>' in page.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Full-size originals attached to the gallery (Config.html_include_originals):
# the viewer's download button only gave the reduced copy (2000 px)
# displayed on screen.
# ---------------------------------------------------------------------------

def _gallery_meta(html):
    match = re.search(r"const galleryMeta = (\[.*?\]);", html)
    assert match, "galleryMeta not found in the page"
    return json.loads(match.group(1))


def _big_images(tmp_path, specs):
    """specs: list of (subfolder, name, size, colour). Photos larger than
    GALLERY_FULL_MAX_SIZE (2000 px) so that the displayed copy is
    necessarily reduced."""
    items = []
    for subdir, name, size, color in specs:
        folder = tmp_path / "photos" / subdir if subdir else tmp_path / "photos"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        Image.new("RGB", size, color).save(path, quality=95)
        items.append({"path": path})
    return items


def test_gallery_has_no_originals_by_default(tmp_path):
    """Without the option, nothing changes: no originals/ folder, no
    "original" key in the metadata - the download targets the displayed
    copy, as before."""
    images = _big_images(tmp_path, [("", "a.jpg", (3000, 2000), (10, 20, 30))])
    html = _generate(tmp_path, images, Profile())

    assert not (tmp_path / "out" / "originals").exists()
    assert all("original" not in entry for entry in _gallery_meta(html))


def test_originals_are_copied_byte_for_byte_at_full_resolution(tmp_path):
    """Regression: "the download does not give the original full-size
    image". With the option, each original is copied BYTE FOR BYTE (no
    recompression), the displayed copy staying reduced."""
    images = _big_images(tmp_path, [
        ("", "a.jpg", (3000, 2000), (10, 20, 30)),
        ("", "b.jpg", (2400, 3600), (200, 100, 50)),
    ])
    html = _generate(tmp_path, images, Profile(), include_originals=True)
    out = tmp_path / "out"

    meta = _gallery_meta(html)
    assert [e["original"] for e in meta] == ["originals/a.jpg", "originals/b.jpg"]
    assert [e["originalFilename"] for e in meta] == ["a.jpg", "b.jpg"]
    for item in images:
        copy = out / "originals" / item["path"].name
        assert filecmp.cmp(item["path"], copy, shallow=False), "the original must be byte-for-byte identical"
    assert Image.open(out / "originals" / "a.jpg").size == (3000, 2000)
    assert max(Image.open(out / "images" / "a.jpg").size) == 2000, "the displayed copy stays reduced"


def test_originals_with_the_same_name_never_overwrite_each_other(tmp_path):
    """Two photos with the same name in two subfolders (option -r), even
    differing only by case (Windows/macOS do not distinguish them): silently
    losing an ORIGINAL would be far worse than for a reduced copy."""
    images = _big_images(tmp_path, [
        ("un", "IMG_1.jpg", (2200, 1500), (255, 0, 0)),
        ("deux", "IMG_1.jpg", (2200, 1500), (0, 255, 0)),
        ("trois", "img_1.JPG", (2200, 1500), (0, 0, 255)),
    ])
    html = _generate(tmp_path, images, Profile(), include_originals=True)
    out = tmp_path / "out" / "originals"

    meta = _gallery_meta(html)
    names = [unquote(e["original"]).split("/", 1)[1] for e in meta]
    assert len({n.lower() for n in names}) == 3, f"noms d'originaux non uniques : {names}"
    for item, name in zip(images, names):
        assert filecmp.cmp(item["path"], out / name, shallow=False)
    # The download, for its part, keeps each file's original name.
    assert [e["originalFilename"] for e in meta] == ["IMG_1.jpg", "IMG_1.jpg", "img_1.JPG"]


def test_original_url_is_percent_encoded(tmp_path):
    """A name with spaces, accents, # or parentheses must remain
    downloadable: without encoding, "#" cut the URL (fragment) and the
    browser asked for a non-existent file."""
    images = _big_images(tmp_path, [("", "Été du 12 #3 (copie).jpg", (2200, 1500), (9, 9, 9))])
    html = _generate(tmp_path, images, Profile(), include_originals=True)

    (entry,) = _gallery_meta(html)
    assert entry["original"] == "originals/" + quote("Été du 12 #3 (copie).jpg")
    assert "#" not in entry["original"] and " " not in entry["original"]
    assert (tmp_path / "out" / unquote(entry["original"])).is_file()


def test_download_button_targets_the_original_when_available(tmp_path):
    """The viewer script must download the original (under its original
    name) when the page knows one, the displayed copy otherwise; the button
    announces it through its label."""
    images = _big_images(tmp_path, [("", "a.jpg", (2200, 1500), (1, 2, 3))])
    html = _generate(tmp_path, images, Profile(), include_originals=True)

    assert "const url = meta.original || galleryImages[currentIndex];" in html
    assert "const filename = meta.originalFilename || meta.filename;" in html
    assert "dl.href = meta.original || url;" in html
    assert "dl.download = meta.originalFilename || meta.filename;" in html
    assert f"const downloadOriginalLabel = {json.dumps(_('gallery.download_original'), ensure_ascii=False)};" in html
    # An original (possibly a RAW) is not what the viewer displays:
    # the "redraw the on-screen image" fallback would give the reduced copy.
    assert html.index("if (meta.original)") < html.index("canvas.toBlob")


RAW_EXTENSIONS = (".cr2", ".cr3", ".nef", ".dng", ".arw")


def _raw_worker_dirs(tmp_path):
    images_dir, thumbs_dir, originals_dir = (tmp_path / d for d in ("images", "thumbs", "originals"))
    for d in (images_dir, thumbs_dir, originals_dir):
        d.mkdir()
    return images_dir, thumbs_dir, originals_dir


def _fake_raw(tmp_path, name="DSC_0001.NEF"):
    raw = tmp_path / "photos" / name
    raw.parent.mkdir(exist_ok=True)
    raw.write_bytes(b"NEF-FAKE-" + bytes(range(256)) * 40)
    return raw


def _raw_files_under(folder):
    return sorted(p.name for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in RAW_EXTENSIONS)


def test_worker_converts_a_raw_original_to_a_full_size_jpeg(tmp_path, monkeypatch):
    """A RAW is NEVER copied into the gallery: the downloadable original is
    a JPEG at full resolution (here 3000 x 2000, hence larger than the
    displayed copy capped at 2000 px), under the photo's name in `.jpg`.
    The worker is called directly (in this process) so that the RAW
    decoding can be simulated, rawpy not always being installed."""
    from portfolio import htmlgallery

    raw = _fake_raw(tmp_path)
    monkeypatch.setattr(htmlgallery, "load_full_resolution",
                        lambda path: Image.new("RGB", (3000, 2000), (5, 60, 200)))
    monkeypatch.setattr(htmlgallery.shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("a RAW must never be copied as is")))
    images_dir, thumbs_dir, originals_dir = _raw_worker_dirs(tmp_path)

    ok, meta = htmlgallery._process_full_image_worker((
        str(raw), str(images_dir), str(thumbs_dir), "t.jpg", None, 40, "Horizontal",
        str(originals_dir), "DSC_0001.jpg",
    ))

    assert ok
    original = originals_dir / "DSC_0001.jpg"
    with Image.open(original) as img:
        assert img.format == "JPEG"
        assert img.size == (3000, 2000), "the original keeps the full resolution"
        assert all(abs(a - b) <= 6 for a, b in zip(img.getpixel((1500, 1000)), (5, 60, 200)))
        # Downloadable version of the shot, not a display copy:
        # quality 95 (fine quantisation table) and 4:4:4 colours.
        assert img.quantization[0][0] <= 3
        assert JpegImagePlugin.get_sampling(img) == 0
    assert original.read_bytes()[:9] != raw.read_bytes()[:9]
    assert meta["original"] == "originals/DSC_0001.jpg"
    assert meta["original_filename"] == "DSC_0001.jpg", "the download offers a .jpg, never the RAW extension"
    assert meta["filename"] == "DSC_0001.jpg"
    assert max(Image.open(images_dir / "DSC_0001.jpg").size) == 2000, "the displayed copy stays reduced"
    for folder in (images_dir, thumbs_dir, originals_dir):
        assert _raw_files_under(folder) == []


def test_worker_never_writes_a_raw_extension_even_when_given_a_raw_name(tmp_path, monkeypatch):
    """Safeguard: whatever original name is received, a RAW is written as
    `.jpg`."""
    from portfolio import htmlgallery

    raw = _fake_raw(tmp_path)
    monkeypatch.setattr(htmlgallery, "load_full_resolution",
                        lambda path: Image.new("RGB", (2400, 1600), (90, 90, 90)))
    images_dir, thumbs_dir, originals_dir = _raw_worker_dirs(tmp_path)

    ok, meta = htmlgallery._process_full_image_worker((
        str(raw), str(images_dir), str(thumbs_dir), "t.jpg", None, 40, "Horizontal",
        str(originals_dir), "DSC_0001.NEF",
    ))

    assert ok
    assert sorted(p.name for p in originals_dir.iterdir()) == ["DSC_0001.jpg", "DSC_0001.jpg.js"]
    assert meta["original"] == "originals/DSC_0001.jpg"


def test_raw_original_has_no_watermark_while_the_displayed_copy_has_one(tmp_path, monkeypatch):
    """As for the other originals: the watermark is applied only to the
    displayed copies (warning already provided on the interface/CLI side)."""
    from portfolio import htmlgallery

    raw = _fake_raw(tmp_path)
    monkeypatch.setattr(htmlgallery, "load_full_resolution",
                        lambda path: Image.new("RGB", (2400, 1600), (120, 120, 120)))
    images_dir, thumbs_dir, originals_dir = _raw_worker_dirs(tmp_path)

    ok, _meta = htmlgallery._process_full_image_worker((
        str(raw), str(images_dir), str(thumbs_dir), "t.jpg", "COPYRIGHT", 80, "Horizontal",
        str(originals_dir), "DSC_0001.jpg",
    ))

    assert ok
    low, high = Image.open(originals_dir / "DSC_0001.jpg").convert("L").getextrema()
    assert high - low <= 6, "a RAW's original must carry no watermark"
    low, high = Image.open(images_dir / "DSC_0001.jpg").convert("L").getextrema()
    assert high - low > 20, "the displayed copy, on the other hand, must carry the watermark"


def test_raw_original_keeps_exif_and_color_profile_and_is_not_rotated_twice(tmp_path, monkeypatch):
    """A RAW's embedded preview carries the EXIF (camera...) and sometimes a
    colour profile: kept in the downloadable JPEG. The orientation is
    applied to the pixels (as for the displayed copy) AND removed from the
    EXIF, otherwise a viewer would flip the image a second time."""
    from PIL import ImageCms
    from portfolio import htmlgallery

    raw = _fake_raw(tmp_path)
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    preview = Image.new("RGB", (3000, 2000), (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "TestCamera"        # Make
    exif[0x0112] = 6                   # Orientation: 90° - to be applied
    preview_path = tmp_path / "preview.jpg"
    preview.save(preview_path, exif=exif, icc_profile=icc)
    monkeypatch.setattr(htmlgallery, "load_full_resolution", lambda path: Image.open(preview_path))
    images_dir, thumbs_dir, originals_dir = _raw_worker_dirs(tmp_path)

    ok, _meta = htmlgallery._process_full_image_worker((
        str(raw), str(images_dir), str(thumbs_dir), "t.jpg", None, 40, "Horizontal",
        str(originals_dir), "DSC_0001.jpg",
    ))

    assert ok
    with Image.open(originals_dir / "DSC_0001.jpg") as img:
        assert img.size == (2000, 3000), "pixels rotated according to the EXIF orientation"
        saved = img.getexif()
        assert saved.get(0x010F) == "TestCamera"
        assert saved.get(0x0112) in (None, 1), "the orientation must no longer appear in the EXIF"
        assert img.info.get("icc_profile") == icc


def test_failed_raw_conversion_never_falls_back_to_copying_the_raw(tmp_path, monkeypatch):
    """If the JPEG original cannot be written (disk full...), the photo
    stays in the gallery (download of the displayed copy): the RAW is never
    copied in its place."""
    from portfolio import htmlgallery

    raw = _fake_raw(tmp_path)
    monkeypatch.setattr(htmlgallery, "load_full_resolution",
                        lambda path: Image.new("RGB", (2400, 1600), (9, 9, 9)))
    monkeypatch.setattr(htmlgallery.shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("a RAW must never be copied as is")))
    images_dir, thumbs_dir, originals_dir = _raw_worker_dirs(tmp_path)
    originals_dir.rmdir()  # destination missing: writing the original fails

    ok, meta = htmlgallery._process_full_image_worker((
        str(raw), str(images_dir), str(thumbs_dir), "t.jpg", None, 40, "Horizontal",
        str(originals_dir), "DSC_0001.jpg",
    ))

    assert ok and "original" not in meta
    assert (images_dir / "DSC_0001.jpg").is_file()
    assert _raw_files_under(tmp_path / "images") == []


def test_unreadable_raw_leaves_nothing_in_the_gallery(tmp_path, monkeypatch):
    """Unreadable RAW (rawpy missing, corrupted file): the photo is dropped
    from the gallery, with no RAW copied anywhere."""
    from portfolio import htmlgallery

    raw = _fake_raw(tmp_path)

    def broken(path):
        raise RuntimeError("rawpy absent")

    monkeypatch.setattr(htmlgallery, "load_full_resolution", broken)
    images_dir, thumbs_dir, originals_dir = _raw_worker_dirs(tmp_path)

    ok, meta = htmlgallery._process_full_image_worker((
        str(raw), str(images_dir), str(thumbs_dir), "t.jpg", None, 40, "Horizontal",
        str(originals_dir), "DSC_0001.jpg",
    ))

    assert (ok, meta) == (False, None)
    for folder in (images_dir, thumbs_dir, originals_dir):
        assert list(folder.iterdir()) == []


def test_raw_without_originals_option_still_uses_the_fast_decoding_path(tmp_path, monkeypatch):
    """Without the option, nothing changes for a RAW: "large enough for
    display" decoding (embedded preview), no full demosaicing for nothing."""
    from portfolio import htmlgallery

    raw = _fake_raw(tmp_path)
    calls = []
    monkeypatch.setattr(htmlgallery, "load_full_resolution",
                        lambda path: calls.append("full") or Image.new("RGB", (3000, 2000)))
    monkeypatch.setattr(htmlgallery, "load_image",
                        lambda *a, **k: calls.append("fast") or Image.new("RGB", (3000, 2000)))
    images_dir, thumbs_dir, _originals_dir = _raw_worker_dirs(tmp_path)

    ok, meta = htmlgallery._process_full_image_worker((
        str(raw), str(images_dir), str(thumbs_dir), "t.jpg", None, 40, "Horizontal",
    ))

    assert ok and "original" not in meta
    assert calls == ["fast"]


def test_raw_original_names_are_jpg_and_stay_unique_next_to_a_jpeg_of_the_same_name(tmp_path):
    """RAW + JPEG with the same name (common pair): two distinct `.jpg`
    originals, none overwritten; the RAW's original is indeed a JPEG."""
    from portfolio.htmlgallery import _unique_file_name

    used = set()
    names = [HTMLGalleryGenerator.display_filename(n) for n in ("IMG_1.CR2", "IMG_1.jpg", "IMG_2.NEF")]
    unique = [_unique_file_name(n, used) for n in names]
    assert unique == ["IMG_1.jpg", "IMG_1_2.jpg", "IMG_2.jpg"]
    assert not any(n.lower().endswith(RAW_EXTENSIONS) for n in unique)


def _file_branch(html):
    """Body of the `file:` branch of downloadCurrentImage()."""
    start = html.index("if (window.location.protocol === 'file:')")
    return html[start:html.index("// The native HTML \"download\" attribute", start)]


def test_local_file_page_downloads_an_original_through_its_companion_script(tmp_path):
    """Gallery opened by double-click (file://): fetch() is blocked and the
    `download` attribute is not honoured everywhere, but a neighbouring
    <script src> tag always loads. For an original, the button therefore
    inserts `originals/<name>.js`, which delivers the file in base64: it is
    then downloaded under its real name. Without a usable companion file
    (script missing or truncated), it falls back to the download link."""
    images = _big_images(tmp_path, [("", "a.jpg", (2200, 1500), (1, 2, 3))])
    html = _generate(tmp_path, images, Profile(), include_originals=True)

    branch = _file_branch(html)
    assert "downloadOriginalFromScript(meta, filename, () => openDownloadLink(url, filename));" in branch
    assert branch.index("if (meta.original)") < branch.index("openDownloadLink(url, filename);\n            return;")
    assert "script.src = meta.original + '.js';" in html
    assert "script.onerror = failed;" in html and "script.onload = failed;" in html
    assert "triggerBlobDownload(new Blob([bytes], { type: 'image/jpeg' }), pending.filename);" in html
    # The name expected by the companion script is that of the file (decoded from the URL).
    assert "decodeURIComponent(meta.original.split('/').pop())" in html


def test_download_link_fallback_never_leaves_the_gallery(tmp_path):
    """Fallback (displayed copy without the "originals" option, or original
    without a companion file): <a download> link, honoured or not depending
    on the browser; target=_blank so as never to replace the gallery page,
    and an explanatory message in all cases."""
    images = _big_images(tmp_path, [("", "a.jpg", (2200, 1500), (1, 2, 3))])
    html = _generate(tmp_path, images, Profile(), include_originals=False)

    start = html.index("function openDownloadLink(url, filename)")
    body = html[start:html.index("// Downloads in progress", start)]
    for expected in ("link.href = url;", "link.download = filename;", "link.target = '_blank';", "link.click();"):
        assert expected in body, expected
    assert "window.open" not in body
    assert "showToast(" in body
    assert json.dumps(_("gallery.download_toast"), ensure_ascii=False) in html
    # without "originals", only the link is used (the companion script does not exist)
    assert _file_branch(html).rstrip().endswith("}")
    assert "openDownloadLink(url, filename);\n            return;" in _file_branch(html)


def _script_payload(script_path):
    """(name, bytes) decoded from a companion file `pcOriginalLoaded("name","base64");`."""
    text = script_path.read_text(encoding="ascii")
    match = re.fullmatch(r'window\.pcOriginalLoaded\((".*?"),"([A-Za-z0-9+/=]*)"\);', text, re.S)
    assert match, f"format inattendu : {text[:80]}"
    return json.loads(match.group(1)), base64.b64decode(match.group(2))


def test_every_original_comes_with_a_companion_script_that_carries_its_exact_bytes(tmp_path):
    """Companion file of each original, next to it: the decoded base64 is
    byte-for-byte identical to the original, and the name it announces is
    that of the file (including accents, spaces and # - escaped in ASCII)."""
    images = _big_images(tmp_path, [
        ("", "Été du 12 #3 (copie).jpg", (2200, 1500), (9, 9, 9)),
        ("un", "IMG_1.jpg", (2200, 1500), (255, 0, 0)),
        ("deux", "IMG_1.jpg", (2200, 1500), (0, 255, 0)),
    ])
    html = _generate(tmp_path, images, Profile(), include_originals=True)
    out = tmp_path / "out" / "originals"

    for entry in _gallery_meta(html):
        original = out / unquote(entry["original"]).split("/", 1)[1]
        name, payload = _script_payload(original.with_name(original.name + ".js"))
        assert name == original.name
        assert payload == original.read_bytes()
    assert sorted(p.name for p in out.glob("*.js")) == [
        "IMG_1.jpg.js", "IMG_1_2.jpg.js", "Été du 12 #3 (copie).jpg.js",
    ]


def test_there_is_no_companion_script_without_the_originals_option(tmp_path):
    images = _big_images(tmp_path, [("", "a.jpg", (2200, 1500), (1, 2, 3))])
    _generate(tmp_path, images, Profile())
    assert list((tmp_path / "out").rglob("*.js")) == []


def test_companion_script_of_a_converted_raw_carries_the_jpeg_not_the_raw(tmp_path, monkeypatch):
    from portfolio import htmlgallery

    raw = _fake_raw(tmp_path)
    monkeypatch.setattr(htmlgallery, "load_full_resolution",
                        lambda path: Image.new("RGB", (3000, 2000), (5, 60, 200)))
    images_dir, thumbs_dir, originals_dir = _raw_worker_dirs(tmp_path)

    ok, _meta = htmlgallery._process_full_image_worker((
        str(raw), str(images_dir), str(thumbs_dir), "t.jpg", None, 40, "Horizontal",
        str(originals_dir), "DSC_0001.jpg",
    ))

    assert ok
    name, payload = _script_payload(originals_dir / "DSC_0001.jpg.js")
    assert name == "DSC_0001.jpg"
    assert payload == (originals_dir / "DSC_0001.jpg").read_bytes()
    assert payload[:3] == b"\xff\xd8\xff", "the companion file delivers the JPEG, never the RAW"
    assert raw.read_bytes()[:9] not in payload[:64]


def test_a_failed_companion_script_leaves_no_truncated_file_and_keeps_the_original(tmp_path, monkeypatch):
    """Disk full while writing the companion file: a truncated script would
    run badly and the click would have no effect - it is therefore deleted
    (the viewer falls back to the link); the original itself stays valid."""
    from portfolio import htmlgallery

    src = _big_images(tmp_path, [("", "a.jpg", (2200, 1500), (1, 1, 1))])[0]["path"]
    images_dir, thumbs_dir, originals_dir = _raw_worker_dirs(tmp_path)
    real_b64 = htmlgallery.base64.b64encode
    calls = []

    def failing_b64(block):
        calls.append(1)
        raise OSError("disque plein")

    monkeypatch.setattr(htmlgallery.base64, "b64encode", failing_b64)
    ok, meta = htmlgallery._process_full_image_worker((
        str(src), str(images_dir), str(thumbs_dir), "t.jpg", None, 40, "Horizontal",
        str(originals_dir), "a.jpg",
    ))
    monkeypatch.setattr(htmlgallery.base64, "b64encode", real_b64)

    assert calls, "the test did not exercise the writing of the companion file"
    assert ok and meta["original"] == "originals/a.jpg"
    assert [p.name for p in originals_dir.iterdir()] == ["a.jpg"]
    assert (originals_dir / "a.jpg").read_bytes() == src.read_bytes()


def test_companion_script_of_an_original_larger_than_one_block_decodes_exactly(tmp_path):
    """With the real block size: an original slightly larger than one block
    (two blocks, the second partial) must stay a continuous base64 - a
    block that is not a multiple of 3 bytes would insert a `=` in the middle
    and corrupt the downloaded file."""
    from portfolio import htmlgallery

    assert htmlgallery._DOWNLOAD_SCRIPT_CHUNK_BYTES % 3 == 0
    original = tmp_path / "grand.jpg"
    data = bytes((i * 7919) % 251 for i in range(htmlgallery._DOWNLOAD_SCRIPT_CHUNK_BYTES + 1000))
    original.write_bytes(data)
    assert htmlgallery._write_download_script(original, "grand.jpg") is True
    assert _script_payload(tmp_path / "grand.jpg.js") == ("grand.jpg", data)


def test_companion_script_is_written_in_blocks_and_stays_one_valid_string(tmp_path, monkeypatch):
    """An original read in several blocks (here of 3 bytes, a multiple of 3
    so that the base64 stays continuous from one block to the next) gives a
    single JS literal, with no line break, which decodes to the exact
    original."""
    from portfolio import htmlgallery

    monkeypatch.setattr(htmlgallery, "_DOWNLOAD_SCRIPT_CHUNK_BYTES", 3)
    original = tmp_path / "o.jpg"
    data = bytes(range(256)) * 3 + b"xy"
    original.write_bytes(data)
    assert htmlgallery._write_download_script(original, "o.jpg") is True
    text = (tmp_path / "o.jpg.js").read_text(encoding="ascii")
    assert "\n" not in text
    assert _script_payload(tmp_path / "o.jpg.js") == ("o.jpg", data)


class _InProcessExecutor:
    """Replaces ProcessPoolExecutor so that the workers run in THIS process
    (hence monkeypatchable: a `spawn` worker re-imports the module and
    ignores any patch)."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, function, tasks):
        return [function(task) for task in tasks]


def test_gallery_with_raw_files_contains_no_raw_and_keeps_raw_jpeg_pairs_apart(tmp_path, monkeypatch):
    """Complete gallery (naming, metadata, HTML page) with simulated RAWs:
    no RAW file anywhere in the gallery folder; a RAW + JPEG pair with the
    same name gives two distinct `.jpg` originals (neither overwrites the
    other); the download never offers a RAW extension."""
    from portfolio import htmlgallery

    photos = tmp_path / "photos"
    photos.mkdir()
    for name in ("IMG_1.CR2", "IMG_2.nef"):
        (photos / name).write_bytes(b"RAW-FAKE-" + name.encode() + bytes(200))
    Image.new("RGB", (2600, 1700), (10, 200, 10)).save(photos / "IMG_1.jpg", quality=95)
    monkeypatch.setattr(htmlgallery, "ProcessPoolExecutor", _InProcessExecutor)
    monkeypatch.setattr(htmlgallery, "load_full_resolution",
                        lambda path: Image.new("RGB", (3200, 2100), (200, 10, 10)))
    images = [{"path": photos / n} for n in ("IMG_1.CR2", "IMG_1.jpg", "IMG_2.nef")]

    html = _generate(tmp_path, images, Profile(), include_originals=True)
    out = tmp_path / "out"

    assert _raw_files_under(out) == []
    meta = _gallery_meta(html)
    assert [e["originalFilename"] for e in meta] == ["IMG_1.jpg", "IMG_1.jpg", "IMG_2.jpg"]
    files = [unquote(e["original"]).split("/", 1)[1] for e in meta]
    assert files == ["IMG_1.jpg", "IMG_1_2.jpg", "IMG_2.jpg"]
    sizes = [Image.open(out / "originals" / f).size for f in files]
    assert sizes == [(3200, 2100), (2600, 1700), (3200, 2100)], "the converted RAW does not overwrite the real JPEG"
    assert Image.open(out / "originals" / "IMG_1_2.jpg").getpixel((1300, 850))[1] > 150


REAL_DNG = Path(__file__).parent / "data" / "mini_raw.dng"


def test_gallery_with_real_raw_files_contains_no_raw_at_all(tmp_path):
    """End to end with a real RAW file (160 x 120 px DNG, red on the left /
    blue on the right) decoded by LibRaw, in real worker processes, paired
    with a JPEG of the same name: no RAW file anywhere in the gallery
    folder, and the originals are real JPEGs at the RAW's resolution, with
    the right colours. Skipped if rawpy is not installed (it is nevertheless
    listed in requirements.txt)."""
    pytest.importorskip("rawpy")
    photos = tmp_path / "photos"
    photos.mkdir()
    for name in ("MINI.dng", "Autre.DNG"):
        shutil.copy2(REAL_DNG, photos / name)
    Image.new("RGB", (160, 120), (10, 200, 10)).save(photos / "MINI.jpg", quality=95)
    images = [{"path": photos / n} for n in ("MINI.dng", "MINI.jpg", "Autre.DNG")]

    html = _generate(tmp_path, images, Profile(), include_originals=True)
    out = tmp_path / "out"

    assert _raw_files_under(out) == [], "no RAW must remain in the gallery"
    meta = _gallery_meta(html)
    assert len(meta) == 3
    originals = [out / unquote(e["original"]) for e in meta]
    assert len({o.name.lower() for o in originals}) == 3
    for original in originals:
        with Image.open(original) as img:
            assert img.format == "JPEG" and img.size == (160, 120)
    red_blue = [Image.open(o).convert("RGB") for o in (originals[0], originals[2])]
    for img in red_blue:
        left, right = img.getpixel((10, 60)), img.getpixel((150, 60))
        assert left[0] > 200 and left[2] < 150, f"gauche attendu rouge : {left}"
        assert right[2] > 200 and right[0] < 120, f"droite attendu bleu : {right}"
    assert Image.open(originals[1]).convert("RGB").getpixel((80, 60))[1] > 150, "the real JPEG is still copied"
    assert [e["originalFilename"] for e in meta] == ["MINI.jpg", "MINI.jpg", "Autre.jpg"]


def test_failed_original_copy_keeps_the_gallery_and_falls_back(tmp_path, monkeypatch):
    """Disk full or locked file: the image stays in the gallery, with no
    truncated file in originals/, and the download falls back to the
    displayed copy (no "original" key)."""
    from portfolio import htmlgallery

    src = _big_images(tmp_path, [("", "a.jpg", (2200, 1500), (1, 1, 1))])[0]["path"]
    images_dir, thumbs_dir, originals_dir = (tmp_path / d for d in ("images", "thumbs", "originals"))
    for d in (images_dir, thumbs_dir, originals_dir):
        d.mkdir()

    def broken_copy(source, destination, *a, **k):
        destination = htmlgallery.Path(destination)
        destination.write_bytes(b"tronque")
        raise OSError("disque plein")

    monkeypatch.setattr(htmlgallery.shutil, "copy2", broken_copy)
    ok, meta = htmlgallery._process_full_image_worker((
        str(src), str(images_dir), str(thumbs_dir), "t.jpg", None, 40, "Horizontal",
        str(originals_dir), "a.jpg",
    ))

    assert ok and "original" not in meta
    assert list(originals_dir.iterdir()) == [], "no truncated file must remain"
    assert (images_dir / "a.jpg").is_file()


def test_worker_without_originals_arguments_still_works(tmp_path):
    """Compatibility: the old 7-argument call (without originals) remains
    valid."""
    from portfolio import htmlgallery

    src = _big_images(tmp_path, [("", "a.jpg", (2200, 1500), (1, 1, 1))])[0]["path"]
    images_dir, thumbs_dir = tmp_path / "images", tmp_path / "thumbs"
    images_dir.mkdir()
    thumbs_dir.mkdir()

    ok, meta = htmlgallery._process_full_image_worker((
        str(src), str(images_dir), str(thumbs_dir), "t.jpg", None, 40, "Horizontal",
    ))

    assert ok and "original" not in meta


# ---------------------------------------------------------------------------
# DISPLAYED copies (images/): unique names and encoded URLs. Defect found
# while testing the originals: two photos with the same name overwrote each
# other (the gallery showed the same photo twice) and a "#" in a name cut the URL.
# ---------------------------------------------------------------------------

def _gallery_images(html):
    match = re.search(r"const galleryImages = (\[.*?\]);", html)
    assert match, "galleryImages not found in the page"
    return json.loads(match.group(1))


def _center_color(path):
    img = Image.open(path).convert("RGB")
    return img.getpixel((img.width // 2, img.height // 2))


def test_displayed_copies_of_same_named_photos_never_overwrite_each_other(tmp_path):
    """Two photos with the same name in two subfolders (option -r: several
    memory cards whose numbering restarts from zero), even differing only
    by case: each must keep ITS displayed copy. Before the fix, the second
    overwrote the first and the viewer showed the same photo twice."""
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    images = _big_images(tmp_path, [
        ("carte1", "IMG_1.jpg", (2200, 1500), colors[0]),
        ("carte2", "IMG_1.jpg", (2200, 1500), colors[1]),
        ("carte3", "img_1.JPG", (2200, 1500), colors[2]),
    ])
    html = _generate(tmp_path, images, Profile())
    out = tmp_path / "out"

    urls = _gallery_images(html)
    assert len({u.lower() for u in urls}) == 3, f"displayed copies not unique: {urls}"
    for url, expected in zip(urls, colors):
        shown = _center_color(out / unquote(url))
        assert all(abs(a - b) <= 12 for a, b in zip(shown, expected)), (
            f"{url} shows {shown} instead of the original photo {expected}"
        )
    # The name DISPLAYED to the user stays that of the photo, not that of the file.
    assert [e["filename"] for e in _gallery_meta(html)] == ["IMG_1.jpg", "IMG_1.jpg", "img_1.JPG"]


def test_unique_file_name_handles_raw_jpeg_pairs_and_case():
    """A RAW + JPEG pair (very common) gives TWO displayed copies named
    identically: `display_filename()` replaces the RAW extension with
    .jpg."""
    from portfolio.htmlgallery import _unique_file_name

    used = set()
    names = [HTMLGalleryGenerator.display_filename(n) for n in ("IMG_1.CR2", "IMG_1.jpg", "IMG_2.NEF")]
    assert names[0] == names[1] == "IMG_1.jpg", "precondition: the RAW+JPEG pair does collide"
    unique = [_unique_file_name(n, used) for n in names]
    assert unique == ["IMG_1.jpg", "IMG_1_2.jpg", "IMG_2.jpg"]
    assert [_unique_file_name(n, used) for n in ("a.jpg", "a.jpg", "A.JPG")] == ["a.jpg", "a_2.jpg", "A_3.JPG"]


def test_displayed_image_url_is_percent_encoded(tmp_path):
    """A "#", a "%", spaces, accents or parentheses in a photo name: the
    viewer and the thumbnail's link must target the right file (without
    encoding, "#" cut the URL and the viewer asked for a non-existent
    file)."""
    name = "100% réussi #2 (final).jpg"
    images = _big_images(tmp_path, [("", name, (2200, 1500), (30, 60, 90))])
    html = _generate(tmp_path, images, Profile())

    (url,) = _gallery_images(html)
    assert url == "images/" + quote(name)
    assert "#" not in url and " " not in url
    assert (tmp_path / "out" / unquote(url)).is_file()
    assert f'<a href="{url}" onclick="return openLightbox(event, 0)">' in html
