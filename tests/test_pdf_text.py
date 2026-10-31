# -*- coding: utf-8 -*-
"""
PDF à texte sélectionnable.

Le PDF est assemblé à partir des planches JPEG : sans précaution, son texte
(nom des fichiers sous les photos, titre, pied de page) n'est que des pixels,
impossible à copier. ContactSheetGenerator note désormais chaque texte qu'il
dessine (`last_text_runs`) et PDFExporter le repose en INVISIBLE par-dessus
l'image (portfolio/textlayer.py) : l'aspect de la page ne change pas, mais le
nom d'un fichier peut être sélectionné, copié, recherché.

La lecture du PDF produit passe par `pypdf` (test ignoré s'il n'est pas
installé : c'est une dépendance de test, pas de l'application).
"""
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import portfolio.portfolio as cli_module
from portfolio.config import Config
from portfolio.contactsheet import ContactSheetGenerator
from portfolio.pdfexport import PDFExporter
from portfolio.presentation import (
    Profile, LayoutSettings, CaptionSettings, resolve_theme, save_profile,
)
from portfolio.textlayer import TextRun, draw_text_layer
from portfolio.thumbnail import ThumbnailGenerator


def _images(folder: Path, names):
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name in names:
        p = folder / name
        Image.new("RGB", (640, 480), (90, 140, 200)).save(p, quality=90)
        out.append({"path": p, "filename": p.name})
    return out


def _profile(**caption_kwargs):
    return Profile(
        layout=LayoutSettings(per_page=6, caption_position="below"),
        captions=CaptionSettings(fields=["filename"], **caption_kwargs),
    )


def _generator(tmp_path, profile, **config_kwargs):
    config = Config(input_dir=tmp_path, output_dir=tmp_path / "out", num_per_sheet=6,
                    profile=profile, **config_kwargs)
    return ContactSheetGenerator(config, ThumbnailGenerator(config))


def _pdf_text(path: Path) -> str:
    pypdf = pytest.importorskip("pypdf")
    return "\n".join(page.extract_text() for page in pypdf.PdfReader(str(path)).pages)


# ---------------------------------------------------------------------------
# Enregistrement des textes par ContactSheetGenerator
# ---------------------------------------------------------------------------

def test_sheet_records_every_caption_title_and_footer_text(tmp_path):
    images = _images(tmp_path / "photos", ["été_01.jpg", "b.jpg", "c.jpg"])
    gen = _generator(tmp_path, _profile(), title="Voyage", author="Gilles")
    sheet = gen.create_contact_sheet(images, 1, 3)

    texts = [run.text for run in gen.last_text_runs]
    assert "Voyage" in texts and "Gilles" in texts
    for name in ("été_01.jpg", "b.jpg", "c.jpg"):
        assert name in texts
    assert any("1/3" in t for t in texts), "le numéro de planche fait partie du pied de page"

    # Reading order : en-tête, puis légendes, puis pied de page.
    assert texts.index("Voyage") < texts.index("été_01.jpg") < texts.index(
        next(t for t in texts if "1/3" in t))

    width, height = sheet.size
    for run in gen.last_text_runs:
        assert 0 <= run.x < width and 0 < run.baseline < height
        assert run.size > 0 and run.width > 0


def test_recorded_baseline_matches_the_ink_actually_drawn(tmp_path):
    """La ligne de base notée doit tomber au bas des lettres sans jambage :
    c'est ce qui aligne le texte invisible sur le texte visible dans le PDF."""
    import numpy as np

    images = _images(tmp_path / "photos", ["EEEE.jpg"])
    gen = _generator(tmp_path, _profile())
    sheet = gen.create_contact_sheet(images, 1, 1)
    run = next(r for r in gen.last_text_runs if r.text == "EEEE.jpg")

    gray = np.array(sheet.convert("L")).astype(int)
    x0, x1 = int(run.x), int(run.x + run.width)
    band = gray[int(run.baseline) - int(run.size * 1.5): int(run.baseline) + int(run.size), x0:x1]
    ink_rows = np.where((band < 128).any(axis=1))[0]
    assert ink_rows.size
    # Dernière ligne d'encre des « EEEE » = ligne de base (à un pixel près) ;
    # le « j » de « .jpg » descend plus bas, d'où la restriction aux 4 « E ».
    e_width = max(1, int(run.width * 0.45))
    e_rows = np.where((band[:, :e_width] < 128).any(axis=1))[0]
    bottom = int(run.baseline) - int(run.size * 1.5) + e_rows.max()
    assert abs(bottom - run.baseline) <= 2


def test_text_runs_are_reset_at_each_sheet(tmp_path):
    images = _images(tmp_path / "photos", ["a.jpg", "b.jpg"])
    gen = _generator(tmp_path, _profile())
    gen.create_contact_sheet(images, 1, 2)
    first = [r.text for r in gen.last_text_runs]
    gen.create_contact_sheet(images[:1], 2, 2)
    second = [r.text for r in gen.last_text_runs]
    assert "b.jpg" in first and "b.jpg" not in second
    assert any("2/2" in t for t in second)


def test_no_caption_means_no_caption_text_but_the_rest_is_still_selectable(tmp_path):
    images = _images(tmp_path / "photos", ["a.jpg"])
    gen = _generator(tmp_path, Profile(layout=LayoutSettings(per_page=6)), title="Titre")
    gen.create_contact_sheet(images, 1, 1)
    texts = [r.text for r in gen.last_text_runs]
    assert "a.jpg" not in texts
    assert "Titre" in texts


def test_a_truncated_caption_keeps_its_full_text_for_copy_paste(tmp_path):
    """Un nom de fichier trop long pour la vignette est tronqué par « … » à
    l'écran, mais c'est le nom COMPLET qu'on doit pouvoir copier du PDF."""
    long_name = "IMG_" + "x" * 80 + ".jpg"
    profile = _profile()
    gen = _generator(tmp_path, profile)
    canvas = Image.new("RGB", (800, 200), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    gen._draw_caption(draw, [long_name], 10, 20, 150, 60, profile.captions,
                      resolve_theme(profile.theme))
    assert len(gen.last_text_runs) == 1
    run = gen.last_text_runs[0]
    assert run.text == long_name
    assert run.width <= 150 + 1, "la largeur retenue est celle du texte VISIBLE"


def test_caption_lines_cut_for_lack_of_height_are_still_copyable(tmp_path):
    profile = _profile()
    gen = _generator(tmp_path, profile)
    canvas = Image.new("RGB", (800, 600), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    from portfolio.presentation import pt_to_px, CAPTION_LINE_SPACING_PX
    line_height = max(6, pt_to_px(profile.captions.font_size)) + CAPTION_LINE_SPACING_PX
    gen._draw_caption(draw, [f"ligne{i}" for i in range(5)], 10, 20, 700, 2 * line_height,
                      profile.captions, resolve_theme(profile.theme))
    assert len(gen.last_text_runs) == 2
    assert gen.last_text_runs[0].text == "ligne0"
    assert gen.last_text_runs[1].text == "ligne1 ligne2 ligne3 ligne4"


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _make_pdf(tmp_path, names, *, with_text=True, title="Mon voyage"):
    images = _images(tmp_path / "photos", names)
    gen = _generator(tmp_path, _profile(), title=title)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    sheet = gen.create_contact_sheet(images, 1, 1)
    sheet_path = out / "planche_001.jpg"
    sheet.save(sheet_path, "JPEG", quality=90)
    pdf_path = out / "portfolio.pdf"
    runs = {sheet_path: list(gen.last_text_runs)} if with_text else None
    PDFExporter().create_pdf([sheet_path], pdf_path, text_runs=runs)
    return pdf_path


def test_pdf_text_contains_the_file_names_title_and_footer(tmp_path):
    pdf = _make_pdf(tmp_path, ["été_01.jpg", "IMG_0002.jpg", "c.jpg"])
    text = _pdf_text(pdf)
    for expected in ("été_01.jpg", "IMG_0002.jpg", "c.jpg", "Mon voyage"):
        assert expected in text


def test_pdf_text_layer_is_invisible_and_does_not_change_the_page_geometry(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    with_text = pypdf.PdfReader(str(_make_pdf(tmp_path / "a", ["x.jpg", "y.jpg"])))
    without = pypdf.PdfReader(str(_make_pdf(tmp_path / "b", ["x.jpg", "y.jpg"], with_text=False)))

    assert with_text.pages[0].mediabox == without.pages[0].mediabox
    assert len(with_text.pages) == len(without.pages) == 1

    content = with_text.pages[0].get_contents().get_data()
    assert b"3 Tr" in content, "mode de rendu 3 = texte invisible"
    assert b"3 Tr" not in without.pages[0].get_contents().get_data()
    # L'image de la planche est toujours là, une seule fois.
    assert len(list(with_text.pages[0].images)) == 1


def test_pdf_without_text_runs_is_still_produced_as_before(tmp_path):
    pdf = _make_pdf(tmp_path, ["a.jpg"], with_text=False)
    assert pdf.stat().st_size > 0
    assert _pdf_text(pdf).strip() == ""


def test_pdf_is_still_produced_when_the_text_layer_fails(tmp_path, monkeypatch):
    import portfolio.pdfexport as pdfexport

    def boom(*args, **kwargs):
        raise RuntimeError("couche de texte en panne")

    monkeypatch.setattr(pdfexport, "draw_text_layer", boom)
    pdf = _make_pdf(tmp_path, ["a.jpg"])
    assert pdf.exists() and pdf.stat().st_size > 0


def test_missing_fonts_mean_no_text_layer_but_a_valid_pdf(tmp_path, monkeypatch):
    import portfolio.textlayer as textlayer

    monkeypatch.setattr(textlayer, "_register_fonts", lambda: None)
    pdf = _make_pdf(tmp_path, ["a.jpg"])
    assert pdf.exists() and _pdf_text(pdf).strip() == ""


def test_draw_text_layer_ignores_empty_input(tmp_path):
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(tmp_path / "x.pdf"))
    assert draw_text_layer(c, [], 100) == 0
    assert draw_text_layer(c, [TextRun("", 0, 0, 10, 10)], 100) == 0
    assert draw_text_layer(c, [TextRun("a", 0, 0, 0, 10)], 100) == 0


def test_copied_text_spans_the_visible_width_even_when_longer_than_what_is_shown(tmp_path):
    """Texte complet mais largeur de l'affichage : le texte invisible couvre
    la zone visible (sélection à la souris au bon endroit)."""
    pytest.importorskip("pypdf")
    from reportlab.pdfgen import canvas

    long_name = "IMG_" + "y" * 60 + ".jpg"
    c = canvas.Canvas(str(tmp_path / "t.pdf"), pagesize=(400, 100))
    assert draw_text_layer(c, [TextRun(long_name, 10, 50, 12, 100)], 100) == 1
    c.showPage()
    c.save()
    assert long_name in _pdf_text(tmp_path / "t.pdf")


# ---------------------------------------------------------------------------
# Bout en bout, par la ligne de commande
# ---------------------------------------------------------------------------

def test_cli_pdf_is_selectable_with_captions_from_a_profile(tmp_path, monkeypatch):
    photos = tmp_path / "photos"
    _images(photos, ["alpha.jpg", "été.jpg"])
    out = tmp_path / "out"
    profile_path = tmp_path / "profil.json"
    save_profile(_profile(), profile_path)
    monkeypatch.setattr(sys, "argv", [
        "portfolio.py", "-i", str(photos), "-o", str(out), "--pdf",
        "--title", "Sortie", "--profile", str(profile_path),
    ])
    cli_module.main()

    text = _pdf_text(out / "portfolio.pdf")
    assert "alpha.jpg" in text and "été.jpg" in text and "Sortie" in text
