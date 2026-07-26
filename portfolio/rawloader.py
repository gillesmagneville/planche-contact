"""
rawloader.py - Chargement unifié des images, RAW comprises.

Pillow seul ne sait pas décoder les fichiers RAW (.cr2, .cr3, .nef, .dng, .arw...).
Ce module fournit un point d'entrée unique (`load_image`) utilisé partout dans
l'application (vignettes, planches contact, galerie HTML) pour charger un fichier
image, qu'il s'agisse d'un format standard (JPEG, PNG, TIFF...) ou d'un format RAW.

Stratégie pour les RAW :
1. On tente d'extraire la miniature/aperçu JPEG embarqué dans le fichier RAW
   (quasi instantané, suffisant pour vignettes et planches contact).
2. Si aucun aperçu n'est disponible, ou qu'il est trop petit pour l'usage
   demandé (voir `target_size`), on effectue un dématriçage complet via
   LibRaw (nettement plus lent : de l'ordre de la seconde par photo, contre
   quelques dizaines de millisecondes pour l'aperçu embarqué).

Le paramètre `target_size` (optionnel) sert deux buts liés à la performance :
- Pour un JPEG standard, il active le décodage "draft" de Pillow, qui
  s'appuie sur la mise à l'échelle native d'un JPEG (facteurs 1/2, 1/4, 1/8)
  pour décoder directement une image plus petite, sans jamais décoder la
  pleine résolution puis la redimensionner. Gain typique : plusieurs fois
  plus rapide sur de grandes photos JPEG.
- Pour un RAW, il détermine si l'aperçu embarqué (rapide) est assez grand
  pour l'usage demandé ; sinon, on bascule sur le dématriçage complet.
"""

import io
import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".dng", ".arw"}

try:
    import rawpy
    RAWPY_AVAILABLE = True
except ImportError:
    RAWPY_AVAILABLE = False
    logger.warning(
        "Le module 'rawpy' n'est pas installé : les fichiers RAW "
        "(.cr2, .cr3, .nef, .dng, .arw) ne pourront pas être traités."
    )


def is_raw_file(path: Path) -> bool:
    return Path(path).suffix.lower() in RAW_EXTENSIONS


def _large_enough(img_size, target_size, tolerance=0.9):
    """Vrai si img_size couvre au moins ~tolerance fois le plus grand côté
    demandé. Une petite marge est tolérée : un aperçu embarqué très
    légèrement plus petit que la cible reste largement préférable, en
    vitesse, à un dématriçage complet pour une différence imperceptible."""
    return max(img_size) >= max(target_size) * tolerance


def _load_raw(path: Path, use_embedded_thumb: bool = True, target_size=None) -> Image.Image:
    """Charge un fichier RAW et retourne une image PIL en mode RGB."""
    if not RAWPY_AVAILABLE:
        raise RuntimeError(
            f"Impossible de lire '{path.name}' : le module 'rawpy' n'est pas installé. "
            f"Installez-le avec : pip install rawpy"
        )

    with rawpy.imread(str(path)) as raw:
        if use_embedded_thumb:
            try:
                thumb = raw.extract_thumb()
                img = None
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    img = Image.open(io.BytesIO(thumb.data))
                    if target_size is not None:
                        try:
                            img.draft("RGB", target_size)
                        except Exception:
                            pass
                    img.load()
                    img = img.convert("RGB")
                elif thumb.format == rawpy.ThumbFormat.BITMAP:
                    img = Image.fromarray(thumb.data).convert("RGB")

                if img is not None:
                    if target_size is None or _large_enough(img.size, target_size):
                        return img
                    # Aperçu trop petit pour l'usage demandé : on continue
                    # plus bas vers un dématriçage complet.
            except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
                pass
            except Exception as e:
                logger.debug(f"Aperçu embarqué inutilisable pour {path.name} : {e}")

        # Pas d'aperçu exploitable (ou trop petit) : dématriçage complet.
        rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False, output_bps=8)
        return Image.fromarray(rgb)


def load_image(path: Path, use_embedded_thumb: bool = True, target_size=None) -> Image.Image:
    """
    Point d'entrée unique pour charger n'importe quelle image (RAW ou standard).
    Retourne toujours une image PIL en mode RGB. Lève une exception en cas d'échec
    (à charge de l'appelant de logger/ignorer).

    target_size : tuple (largeur_max, hauteur_max) optionnel indiquant la
    taille finale approximative souhaitée. Fournir cette information quand
    elle est connue accélère significativement le décodage (voir docstring
    du module) ; elle n'a aucun effet sur le résultat final si l'appelant
    redimensionne de toute façon ensuite (thumbnail(), etc.) - c'est une
    pure optimisation de vitesse.
    """
    path = Path(path)
    if is_raw_file(path):
        return _load_raw(path, use_embedded_thumb=use_embedded_thumb, target_size=target_size)

    with Image.open(path) as img:
        if target_size is not None:
            try:
                img.draft("RGB", target_size)
            except Exception:
                pass
        img.load()
        return img
