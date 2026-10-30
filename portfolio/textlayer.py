# -*- coding: utf-8 -*-
"""
Couche de texte INVISIBLE superposée aux planches dans le PDF.

Le PDF est construit à partir des planches JPEG (une image par page) : le
texte qu'elles portent - titre, légendes par photo (nom de fichier, date,
réglages...), pied de page - n'y est donc que des pixels, qu'on ne peut ni
sélectionner ni copier. Pour pouvoir, par exemple, copier le nom d'un
fichier depuis le PDF, ContactSheetGenerator note chaque texte qu'il dessine
(`TextRun`) et PDFExporter le repose ici par-dessus l'image, en mode de rendu
« invisible » (le procédé des PDF issus d'une reconnaissance de caractères) :
l'aspect de la page ne change pas d'un pixel, mais le texte est sélectionnable,
copiable et trouvable par la recherche du lecteur PDF.

Les coordonnées sont celles de la planche, en pixels, origine en HAUT à
gauche ; la conversion vers le repère du PDF (points, origine en BAS à
gauche) est faite ici. Une planche étant posée dans le PDF à l'échelle 1 pixel
= 1 point (voir PDFExporter), le texte s'aligne exactement sur celui de
l'image.
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .utils import _BUNDLED_FONTS_DIR

logger = logging.getLogger(__name__)

#: Mode de rendu PDF « texte invisible » (ni tracé ni rempli).
_INVISIBLE = 3

_FONT_NAMES = {False: "PlancheContact-DejaVuSans", True: "PlancheContact-DejaVuSans-Bold"}
_FONT_FILES = {False: "DejaVuSans.ttf", True: "DejaVuSans-Bold.ttf"}


@dataclass(frozen=True)
class TextRun:
    """Un texte dessiné sur une planche, tel que le PDF doit le reproduire.

    - `text` : ce qui sera copié depuis le PDF. Peut être PLUS LONG que ce
      qui est visible : une ligne tronquée par « … » faute de place sur la
      planche garde ici son texte complet (un nom de fichier copié depuis le
      PDF n'est ainsi jamais coupé) ;
    - `x`, `baseline` : origine du texte sur la planche, en pixels (abscisse
      du bord gauche, ordonnée de la LIGNE DE BASE), origine en haut à gauche ;
    - `size` : corps de la police, en pixels ;
    - `width` : largeur occupée à l'écran, en pixels (sert à caler la largeur
      du texte invisible sur celle du texte visible) ;
    - `bold` : police grasse ou non."""
    text: str
    x: float
    baseline: float
    size: float
    width: float
    bold: bool = False


def _font_path(bold: bool) -> Path:
    return Path(_BUNDLED_FONTS_DIR) / _FONT_FILES[bold]


def _register_fonts() -> Optional[dict]:
    """Enregistre (une seule fois) les polices DejaVu fournies avec
    l'application, les mêmes que celles qui dessinent les planches, et
    renvoie `{gras: nom}` - ou None si elles sont introuvables ou
    inutilisables (le PDF est alors produit sans couche de texte plutôt que
    de ne pas être produit)."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    names = {}
    for bold in (False, True):
        name = _FONT_NAMES[bold]
        try:
            pdfmetrics.getFont(name)
        except KeyError:
            path = _font_path(bold)
            if not path.is_file():
                logger.warning("Police %s introuvable : PDF sans texte sélectionnable.", path)
                return None
            try:
                pdfmetrics.registerFont(TTFont(name, str(path)))
            except Exception as exc:  # police illisible : on renonce à la couche de texte
                logger.warning("Police %s inutilisable (%s) : PDF sans texte sélectionnable.", path, exc)
                return None
        names[bold] = name
    return names


def draw_text_layer(pdf_canvas, runs: Iterable[TextRun], sheet_height_px: float,
                    margin_pt: float = 0.0) -> int:
    """Pose `runs` en texte invisible sur la page courante de `pdf_canvas`
    (reportlab). La planche occupe le rectangle dont le coin bas-gauche est
    à (margin_pt, margin_pt) et la hauteur `sheet_height_px`, à l'échelle 1
    pixel = 1 point. Renvoie le nombre de textes posés (0 si rien à poser
    ou si les polices manquent)."""
    runs = [run for run in runs if run.text and run.size > 0]
    if not runs:
        return 0
    fonts = _register_fonts()
    if fonts is None:
        return 0

    from reportlab.pdfbase.pdfmetrics import stringWidth

    placed = 0
    text = pdf_canvas.beginText()
    text.setTextRenderMode(_INVISIBLE)
    for run in runs:
        font_name = fonts[bool(run.bold)]
        try:
            natural = stringWidth(run.text, font_name, run.size)
        except Exception:
            continue
        # Étirement horizontal pour que le texte invisible couvre
        # exactement la largeur du texte visible (même police : ~100 %, mais
        # un texte tronqué à l'écran garde son texte complet ici).
        scale = 100.0 * run.width / natural if natural > 0 and run.width > 0 else 100.0
        text.setFont(font_name, run.size)
        text.setHorizScale(scale)
        text.setTextOrigin(margin_pt + run.x, margin_pt + sheet_height_px - run.baseline)
        text.textOut(run.text)
        placed += 1
    pdf_canvas.drawText(text)
    return placed
