# -*- coding: utf-8 -*-
"""
Tests de non-régression pour le câblage du thème graphique et des légendes
personnalisables (cahier des charges §1/§4) dans HTMLGalleryGenerator -
même Profil que ContactSheetGenerator (voir tests/test_contactsheet.py),
mais rendu CSS/HTML plutôt que PIL : ces tests vérifient le MARQUAGE
produit (chaînes attendues dans le HTML/CSS généré), la visionneuse
('lightbox') étant volontairement laissée hors de propos (voir
portfolio/presentation/themes.py - elle reste intentionnellement sombre,
indépendante du thème choisi pour la page).

Une vérification visuelle complémentaire (captures d'écran Playwright,
thème clair/sombre/système, bascule manuelle, persistance) a par ailleurs
été effectuée manuellement lors du développement de ce câblage - voir
CHANGELOG.md.
"""
import filecmp
import json
import re
from urllib.parse import quote, unquote

import pytest
from PIL import Image
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
    """Sans légende configurée (Profil par défaut), la grille doit garder
    EXACTEMENT son marquage historique (un <a> par photo, sans wrapper
    supplémentaire) : aucune régression visuelle pour l'utilisateur qui ne
    touche à rien de nouveau."""
    _, images = _make_images(tmp_path, 3)
    html = _generate(tmp_path, images, Profile())

    assert '<div class="gallery-caption">' not in html
    assert '<div class="gallery-item">' not in html
    assert ' <a href="images/img_00.jpg" onclick="return openLightbox(event, 0)">' in html


def test_exif_metadata_is_never_read_when_no_caption_field_is_configured(tmp_path, monkeypatch):
    """Même garde que ContactSheetGenerator (voir test_contactsheet.py) :
    pas de lecture EXIF coûteuse par photo si aucune légende n'est
    demandée."""
    import portfolio.htmlgallery as htmlgallery_module

    def _boom(_path):
        raise AssertionError("get_exif_metadata() ne doit pas être appelé sans légende configurée")

    monkeypatch.setattr(htmlgallery_module, "get_exif_metadata", _boom)

    _, images = _make_images(tmp_path, 3)
    _generate(tmp_path, images, Profile())


def test_captions_are_rendered_when_configured(tmp_path):
    """Légendes EXIF réellement lues sur chaque photo SOURCE (cahier des
    charges §1) et affichées sous chaque vignette de la grille."""
    _, images = _make_images(tmp_path, 2, with_exif=True)
    profile = Profile(captions=CaptionSettings(fields=["filename", "camera", "aperture", "iso"], lines=2))
    html = _generate(tmp_path, images, profile)

    assert '<div class="gallery-item">' in html
    assert '<div class="gallery-caption">img_00.jpg · Canon EOS R5<br>f/2.8 · ISO 400</div>' in html


def test_caption_text_is_html_escaped(tmp_path):
    """Un nom de fichier contenant des caractères spéciaux HTML ne doit
    jamais casser le marquage ni permettre une injection."""
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
    """Le thème "light" (défaut du Profil) doit correspondre exactement à
    la palette partagée (portfolio/presentation/themes.py) - et un mode
    fixe ne doit jamais dépendre des préférences systèmes du visiteur
    (voir vérification visuelle : OS en sombre, page restée claire)."""
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
    """Seul le mode "system" doit laisser le NAVIGATEUR choisir (cahier
    des charges §4) - stratégie documentée dans themes.py : combiner les
    palettes claire et sombre de part et d'autre d'une media query CSS."""
    _, images = _make_images(tmp_path, 2)
    profile = Profile(theme=ThemeSettings(mode="system"))
    html = _generate(tmp_path, images, profile)

    light = get_palette("light")
    dark = get_palette("dark")
    assert f":root {{ --bg: {light.background};" in html, "repli clair tant que la media query ne s'applique pas"
    media_block = html.split("@media (prefers-color-scheme: dark)")[1].split("}")[0]
    assert dark.background in media_block
    assert dark.text in media_block


@pytest.mark.parametrize("mode", ["light", "dark", "neutral", "system"])
def test_theme_toggle_and_all_three_overrides_are_always_present(tmp_path, mode):
    """Le sélecteur de thème discret (cahier des charges §4) doit toujours
    permettre au visiteur de basculer manuellement, quel que soit le mode
    choisi par défaut pour la galerie - vérifié visuellement : bascule au
    clic, persistance après rechargement (localStorage)."""
    _, images = _make_images(tmp_path, 2)
    profile = Profile(theme=ThemeSettings(mode=mode))
    html = _generate(tmp_path, images, profile)

    assert 'class="theme-toggle" onclick="toggleTheme()"' in html
    for palette_mode in ("light", "dark", "neutral"):
        palette = get_palette(palette_mode)
        assert f':root[data-theme="{palette_mode}"] {{ --bg: {palette.background};' in html


def _theme_keys(html):
    """Toutes les clés localStorage de thème citées dans une page, sans
    doublon (la clé fixe historique, sans suffixe, comprise)."""
    return set(re.findall(r"planche-contact-theme[0-9a-f-]*", html))


def test_visitor_theme_choice_is_stored_under_a_per_generation_key(tmp_path):
    """Régression : le choix manuel d'un visiteur (bouton ◐) était mémorisé
    sous UNE clé fixe, partagée par toutes les galeries ouvertes depuis la
    même origine (Chrome partage un seul localStorage entre tous les
    fichiers locaux). Un seul clic suffisait donc à faire ignorer, pour
    toujours, le thème choisi dans la fenêtre principale - y compris pour
    une galerie régénérée avec un autre thème. La clé doit maintenant être
    propre à CHAQUE génération."""
    _, images = _make_images(tmp_path, 2)
    profile = Profile(theme=ThemeSettings(mode="dark"))
    first = _theme_keys(_generate(tmp_path / "a", images, profile))
    second = _theme_keys(_generate(tmp_path / "b", images, profile))

    assert len(first) == 1 and len(second) == 1
    (key_a,), (key_b,) = first, second
    assert re.fullmatch(r"planche-contact-theme-[0-9a-f]{12}", key_a)
    assert key_a != key_b, "deux générations ne doivent jamais partager le choix d'un visiteur"
    assert "planche-contact-theme'" not in _generate(tmp_path / "c", images, profile), (
        "l'ancienne clé fixe ne doit plus jamais être lue"
    )


def test_theme_key_is_shared_by_every_page_of_one_generation(tmp_path):
    """Le choix d'un visiteur doit, lui, suivre d'une page à l'autre de la
    MÊME galerie : toutes ses pages citent la même clé."""
    _, images = _make_images(tmp_path, 5)
    _generate(tmp_path, images, Profile(), html_per_page=2)
    pages = sorted((tmp_path / "out").glob("*.html"))

    assert len(pages) == 3
    keys = [_theme_keys(page.read_text(encoding="utf-8")) for page in pages]
    assert all(len(k) == 1 for k in keys)
    assert keys[0] == keys[1] == keys[2]


@pytest.mark.parametrize("mode", ["light", "dark", "neutral", "system"])
def test_theme_toggle_reads_writes_and_clears_the_same_key(tmp_path, mode):
    """Le script de tête (lecture), le bouton ◐ (écriture) et son retour au
    thème demandé (suppression) doivent tous viser la MÊME clé : sinon un
    choix mémorisé resterait appliqué malgré le second clic."""
    _, images = _make_images(tmp_path, 2)
    html = _generate(tmp_path, images, Profile(theme=ThemeSettings(mode=mode)))

    (key,) = _theme_keys(html)
    assert f"localStorage.getItem('{key}')" in html
    assert f"localStorage.setItem('{key}', next)" in html
    assert f"localStorage.removeItem('{key}')" in html


def test_second_toggle_click_returns_to_the_requested_theme(tmp_path):
    """Régression : le bouton ne faisait qu'alterner clair/sombre. Depuis
    une galerie « Neutre », deux clics laissaient la page en « clair » sans
    aucun moyen de retrouver le thème demandé. Un choix déjà mémorisé doit
    maintenant être RETIRÉ (attribut data-theme supprimé), ce qui rend la
    main au thème choisi à la génération."""
    _, images = _make_images(tmp_path, 2)
    html = _generate(tmp_path, images, Profile(theme=ThemeSettings(mode="neutral")))

    toggle = html.split("function toggleTheme()")[1].split("function openLightbox")[0]
    assert "if (current)" in toggle
    assert "document.documentElement.removeAttribute('data-theme')" in toggle
    # Le retour au thème demandé a lieu AVANT toute écriture d'un nouveau choix.
    assert toggle.index("removeAttribute('data-theme')") < toggle.index("setAttribute('data-theme', next)")


@pytest.mark.parametrize("mode,declared", [
    ("light", "only light"),
    ("neutral", "only light"),
    ("dark", "dark"),
    ("system", "light dark"),
])
def test_page_declares_its_color_scheme_to_the_browser(tmp_path, mode, declared):
    """Régression : « thème clair demandé, page sombre affichée ». Sans
    déclaration `color-scheme`, un navigateur dont le mode sombre
    automatique est actif (Chrome/Edge « Auto Dark Mode for Web Contents »,
    Chrome Android, extensions) noircit de force une galerie claire.
    `only light` est le refus normalisé de ce noircissement (`light` seul
    ne l'empêche pas - vérifié dans Chromium) ; la page doit le déclarer
    à la fois en <meta> (avant tout rendu) et en CSS, pour chaque thème."""
    _, images = _make_images(tmp_path, 2)
    html = _generate(tmp_path, images, Profile(theme=ThemeSettings(mode=mode)))

    assert f'<meta name="color-scheme" content="{declared}">' in html
    baseline = html.split(":root {", 1)[1].split("}", 1)[0]
    assert f"color-scheme: {declared};" in baseline


def test_default_clair_gallery_refuses_forced_darkening(tmp_path):
    """Cas exact signalé : « Clair » choisi dans l'interface (profil par
    défaut, donc AUCUN --profile transmis au CLI)."""
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
    """Quand le visiteur bascule le thème (bouton ◐), la déclaration doit
    suivre : une page passée en sombre ne doit plus se dire « claire
    uniquement » (le navigateur la noircirait une seconde fois), et
    inversement."""
    _, images = _make_images(tmp_path, 2)
    html = _generate(tmp_path, images, Profile(theme=ThemeSettings(mode=mode)))

    block = html.split(f':root[data-theme="{override}"] {{', 1)[1].split("}", 1)[0]
    assert f"color-scheme: {declared};" in block


def test_custom_accent_color_is_applied_to_every_theme_override(tmp_path):
    """Une couleur personnalisée (cahier des charges §4.3) s'applique de
    façon cohérente à TOUTES les variantes claire/sombre/neutre du
    sélecteur, pas seulement au thème par défaut choisi pour la page."""
    _, images = _make_images(tmp_path, 2)
    custom = ThemeCustomColors(accent="#ff00aa")
    profile = Profile(theme=ThemeSettings(mode="light", custom=custom))
    html = _generate(tmp_path, images, profile)

    assert html.count("--accent: #ff00aa;") == 4  # :root + les 3 overrides data-theme


def test_lightbox_styling_is_independent_of_the_page_theme(tmp_path):
    """La visionneuse (lightbox) reste volontairement sombre quel que soit
    le thème choisi pour la page (voir le commentaire de conception dans
    portfolio/presentation/themes.py) - vérifié aussi visuellement."""
    _, images = _make_images(tmp_path, 2)
    profile = Profile(theme=ThemeSettings(mode="dark"))
    html = _generate(tmp_path, images, profile)

    assert "background: rgba(0,0,0,0.92);" in html  # fond du calque .lightbox, jamais var(--bg)


# ---------------------------------------------------------------------------
# Position du titre et de l'auteur (LayoutSettings.title_position/
# author_position) : ces réglages étaient exposés mais jamais lus.
# ---------------------------------------------------------------------------

def test_default_header_markup_is_unchanged(tmp_path):
    """Positions par défaut (centrées) : l'en-tête garde EXACTEMENT son
    balisage historique, sans aucun attribut d'alignement ajouté."""
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
    # L'auteur garde sa propre position (centrée : pas d'attribut).
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
    # Le compteur d'images reste affiché, et le <title> de l'onglet aussi.
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
# Originaux pleine taille joints à la galerie (Config.html_include_originals) :
# le bouton de téléchargement de la visionneuse ne donnait que la copie
# réduite (2000 px) affichée à l'écran.
# ---------------------------------------------------------------------------

def _gallery_meta(html):
    match = re.search(r"const galleryMeta = (\[.*?\]);", html)
    assert match, "galleryMeta introuvable dans la page"
    return json.loads(match.group(1))


def _big_images(tmp_path, specs):
    """specs : liste de (sous-dossier, nom, taille, couleur). Photos plus
    grandes que GALLERY_FULL_MAX_SIZE (2000 px) pour que la copie affichée
    soit forcément réduite."""
    items = []
    for subdir, name, size, color in specs:
        folder = tmp_path / "photos" / subdir if subdir else tmp_path / "photos"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        Image.new("RGB", size, color).save(path, quality=95)
        items.append({"path": path})
    return items


def test_gallery_has_no_originals_by_default(tmp_path):
    """Sans l'option, rien ne change : pas de dossier originals/, pas de
    clé « original » dans les métadonnées - le téléchargement vise la copie
    affichée, comme avant."""
    images = _big_images(tmp_path, [("", "a.jpg", (3000, 2000), (10, 20, 30))])
    html = _generate(tmp_path, images, Profile())

    assert not (tmp_path / "out" / "originals").exists()
    assert all("original" not in entry for entry in _gallery_meta(html))


def test_originals_are_copied_byte_for_byte_at_full_resolution(tmp_path):
    """Régression : « le download ne donne pas l'image originale en pleine
    taille ». Avec l'option, chaque original est copié OCTET POUR OCTET
    (aucune recompression), la copie affichée restant réduite."""
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
        assert filecmp.cmp(item["path"], copy, shallow=False), "l'original doit être identique octet pour octet"
    assert Image.open(out / "originals" / "a.jpg").size == (3000, 2000)
    assert max(Image.open(out / "images" / "a.jpg").size) == 2000, "la copie affichée reste réduite"


def test_originals_with_the_same_name_never_overwrite_each_other(tmp_path):
    """Deux photos de même nom dans deux sous-dossiers (option -r), y
    compris à la casse près (Windows/macOS ne les distinguent pas) :
    perdre un ORIGINAL en silence serait bien plus grave que pour une copie
    réduite."""
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
    # Le téléchargement garde, lui, le nom d'origine de chaque fichier.
    assert [e["originalFilename"] for e in meta] == ["IMG_1.jpg", "IMG_1.jpg", "img_1.JPG"]


def test_original_url_is_percent_encoded(tmp_path):
    """Un nom avec espaces, accents, # ou parenthèses doit rester
    téléchargeable : sans encodage, « # » coupait l'URL (fragment) et le
    navigateur demandait un fichier inexistant."""
    images = _big_images(tmp_path, [("", "Été du 12 #3 (copie).jpg", (2200, 1500), (9, 9, 9))])
    html = _generate(tmp_path, images, Profile(), include_originals=True)

    (entry,) = _gallery_meta(html)
    assert entry["original"] == "originals/" + quote("Été du 12 #3 (copie).jpg")
    assert "#" not in entry["original"] and " " not in entry["original"]
    assert (tmp_path / "out" / unquote(entry["original"])).is_file()


def test_download_button_targets_the_original_when_available(tmp_path):
    """Le script de la visionneuse doit télécharger l'original (et sous son
    nom d'origine) quand la page en connaît un, la copie affichée sinon ; le
    bouton l'annonce par son libellé."""
    images = _big_images(tmp_path, [("", "a.jpg", (2200, 1500), (1, 2, 3))])
    html = _generate(tmp_path, images, Profile(), include_originals=True)

    assert "const url = meta.original || galleryImages[currentIndex];" in html
    assert "const filename = meta.originalFilename || meta.filename;" in html
    assert "dl.href = meta.original || url;" in html
    assert "dl.download = meta.originalFilename || meta.filename;" in html
    assert f"const downloadOriginalLabel = {json.dumps(_('gallery.download_original'), ensure_ascii=False)};" in html
    # Un original (peut-être un RAW) n'est pas ce qu'affiche la visionneuse :
    # le repli « redessiner l'image à l'écran » donnerait la copie réduite.
    assert html.index("if (meta.original)") < html.index("canvas.toBlob")


def test_worker_copies_a_raw_original_untouched(tmp_path, monkeypatch):
    """Un RAW (illisible par un navigateur) est joint tel quel : le visiteur
    télécharge le fichier de la prise de vue, l'image affichée venant de
    l'aperçu décodé. Le worker est appelé directement (dans ce processus)
    pour pouvoir simuler le décodage RAW, rawpy n'étant pas toujours
    installé."""
    from portfolio import htmlgallery

    raw = tmp_path / "photos" / "DSC_0001.NEF"
    raw.parent.mkdir()
    raw.write_bytes(b"NEF-FAKE-" + bytes(range(256)) * 40)
    monkeypatch.setattr(htmlgallery, "load_image", lambda *a, **k: Image.new("RGB", (3000, 2000), (5, 6, 7)))
    images_dir, thumbs_dir, originals_dir = (tmp_path / d for d in ("images", "thumbs", "originals"))
    for d in (images_dir, thumbs_dir, originals_dir):
        d.mkdir()

    ok, meta = htmlgallery._process_full_image_worker((
        str(raw), str(images_dir), str(thumbs_dir), "t.jpg", None, 40, "Horizontal",
        str(originals_dir), "DSC_0001.NEF",
    ))

    assert ok
    assert (originals_dir / "DSC_0001.NEF").read_bytes() == raw.read_bytes()
    assert meta["original"] == "originals/DSC_0001.NEF"
    assert meta["original_filename"] == "DSC_0001.NEF"
    assert meta["filename"] == "DSC_0001.jpg", "la copie affichée d'un RAW reste un JPEG"
    assert (images_dir / "DSC_0001.jpg").is_file()


def test_failed_original_copy_keeps_the_gallery_and_falls_back(tmp_path, monkeypatch):
    """Disque plein ou fichier verrouillé : l'image reste dans la galerie,
    sans fichier tronqué dans originals/, et le téléchargement retombe sur
    la copie affichée (aucune clé « original »)."""
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
    assert list(originals_dir.iterdir()) == [], "aucun fichier tronqué ne doit rester"
    assert (images_dir / "a.jpg").is_file()


def test_worker_without_originals_arguments_still_works(tmp_path):
    """Compatibilité : l'ancien appel à 7 arguments (sans originaux) reste
    valide."""
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
# Copies AFFICHÉES (images/) : noms uniques et URL encodées. Défaut constaté en
# testant les originaux : deux photos de même nom s'écrasaient (la galerie
# montrait deux fois la même photo) et un « # » dans un nom coupait l'URL.
# ---------------------------------------------------------------------------

def _gallery_images(html):
    match = re.search(r"const galleryImages = (\[.*?\]);", html)
    assert match, "galleryImages introuvable dans la page"
    return json.loads(match.group(1))


def _center_color(path):
    img = Image.open(path).convert("RGB")
    return img.getpixel((img.width // 2, img.height // 2))


def test_displayed_copies_of_same_named_photos_never_overwrite_each_other(tmp_path):
    """Deux photos de même nom dans deux sous-dossiers (option -r : plusieurs
    cartes mémoire dont la numérotation repart de zéro), y compris à la
    casse près : chacune doit garder SA copie affichée. Avant le
    correctif, la seconde écrasait la première et la visionneuse montrait
    deux fois la même photo."""
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    images = _big_images(tmp_path, [
        ("carte1", "IMG_1.jpg", (2200, 1500), colors[0]),
        ("carte2", "IMG_1.jpg", (2200, 1500), colors[1]),
        ("carte3", "img_1.JPG", (2200, 1500), colors[2]),
    ])
    html = _generate(tmp_path, images, Profile())
    out = tmp_path / "out"

    urls = _gallery_images(html)
    assert len({u.lower() for u in urls}) == 3, f"copies affichées non uniques : {urls}"
    for url, expected in zip(urls, colors):
        shown = _center_color(out / unquote(url))
        assert all(abs(a - b) <= 12 for a, b in zip(shown, expected)), (
            f"{url} montre {shown} au lieu de la photo d'origine {expected}"
        )
    # Le nom AFFICHÉ à l'utilisateur reste celui de la photo, pas celui du fichier.
    assert [e["filename"] for e in _gallery_meta(html)] == ["IMG_1.jpg", "IMG_1.jpg", "img_1.JPG"]


def test_unique_file_name_handles_raw_jpeg_pairs_and_case():
    """Une paire RAW + JPEG (très courante) donne DEUX copies affichées
    nommées pareil : `display_filename()` remplace l'extension RAW par
    .jpg."""
    from portfolio.htmlgallery import _unique_file_name

    used = set()
    names = [HTMLGalleryGenerator.display_filename(n) for n in ("IMG_1.CR2", "IMG_1.jpg", "IMG_2.NEF")]
    assert names[0] == names[1] == "IMG_1.jpg", "préalable : la paire RAW+JPEG entre bien en collision"
    unique = [_unique_file_name(n, used) for n in names]
    assert unique == ["IMG_1.jpg", "IMG_1_2.jpg", "IMG_2.jpg"]
    assert [_unique_file_name(n, used) for n in ("a.jpg", "a.jpg", "A.JPG")] == ["a.jpg", "a_2.jpg", "A_3.JPG"]


def test_displayed_image_url_is_percent_encoded(tmp_path):
    """Un « # », un « % », des espaces, des accents ou des parenthèses dans
    un nom de photo : la visionneuse et le lien de la vignette doivent
    viser le bon fichier (sans encodage, « # » coupait l'URL et la
    visionneuse demandait un fichier inexistant)."""
    name = "100% réussi #2 (final).jpg"
    images = _big_images(tmp_path, [("", name, (2200, 1500), (30, 60, 90))])
    html = _generate(tmp_path, images, Profile())

    (url,) = _gallery_images(html)
    assert url == "images/" + quote(name)
    assert "#" not in url and " " not in url
    assert (tmp_path / "out" / unquote(url)).is_file()
    assert f'<a href="{url}" onclick="return openLightbox(event, 0)">' in html
