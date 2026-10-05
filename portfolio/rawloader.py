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

from .i18n import _

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


def get_original_dimensions(path: Path):
    """Résolution réelle du fichier source (largeur, hauteur), orientation
    EXIF/RAW appliquée pour refléter ce que l'utilisateur voit réellement -
    utilisé pour l'affichage d'informations dans la visionneuse de la
    galerie HTML (voir htmlgallery.py). Toujours une lecture de métadonnées
    seules (en-tête JPEG/TIFF, ou `rawpy.sizes` pour un RAW) : jamais un
    décodage complet, donc rapide même sur plusieurs centaines de photos.

    Retourne None si la lecture échoue (fichier corrompu, format non
    supporté...) - à charge de l'appelant de gérer l'absence de résultat.
    """
    path = Path(path)
    try:
        if is_raw_file(path):
            if not RAWPY_AVAILABLE:
                return None
            with rawpy.imread(str(path)) as raw:
                width, height = raw.sizes.width, raw.sizes.height
                # raw.sizes.flip est le code de rotation LibRaw (0 = aucune,
                # 3 = 180°, 5/6 = 90° dans un sens ou l'autre) : width/height
                # restent dans l'orientation NATIVE du capteur, à échanger
                # pour les rotations à 90°.
                if raw.sizes.flip in (5, 6):
                    width, height = height, width
                return (width, height)

        with Image.open(path) as img:
            width, height = img.size
            exif = img.getexif()
            orientation = exif.get(0x0112)  # tag EXIF Orientation
            if orientation in (5, 6, 7, 8):
                width, height = height, width
            return (width, height)
    except Exception as e:
        logger.debug(f"Dimensions d'origine illisibles pour {path.name} : {e}")
        return None


def _large_enough(img_size, target_size, tolerance=0.9, fill=False):
    """Vrai si img_size couvre au moins ~tolerance fois le plus grand côté
    demandé. Une petite marge est tolérée : un aperçu embarqué très
    légèrement plus petit que la cible reste largement préférable, en
    vitesse, à un dématriçage complet pour une différence imperceptible.

    `fill` : la vignette sera RECADRÉE pour remplir toute sa cellule (mode
    d'ajustement "cover", voir thumbnail.fit_thumbnail_image()) - c'est
    alors le PETIT côté de l'aperçu qui doit atteindre la cible, pas le
    grand : un aperçu 4:3 dont seul le grand côté suffirait laisserait un
    carré recadré plus petit que sa cellule."""
    side = min(img_size) if fill else max(img_size)
    return side >= max(target_size) * tolerance


def _load_raw(path: Path, use_embedded_thumb: bool = True, target_size=None, fill: bool = False,
              min_ratio: float = 0.9) -> Image.Image:
    """Charge un fichier RAW et retourne une image PIL en mode RGB.
    `min_ratio` : part de `target_size` que l'aperçu embarqué doit couvrir
    pour être accepté (voir _large_enough())."""
    if not RAWPY_AVAILABLE:
        raise RuntimeError(_("engine.raw_module_missing", name=path.name))

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
                    if target_size is None or _large_enough(img.size, target_size, tolerance=min_ratio, fill=fill):
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


def load_image(path: Path, use_embedded_thumb: bool = True, target_size=None, fill: bool = False) -> Image.Image:
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

    fill : mettre à True quand l'appelant va RECADRER l'image pour remplir
    une zone `target_size` (vignette en mode "cover") plutôt que l'y
    inscrire : un aperçu RAW embarqué n'est alors jugé assez grand que si
    son petit côté atteint la cible (voir _large_enough()). Sans effet
    pour les images non RAW.
    """
    path = Path(path)
    if is_raw_file(path):
        return _load_raw(path, use_embedded_thumb=use_embedded_thumb, target_size=target_size, fill=fill)

    with Image.open(path) as img:
        if target_size is not None:
            try:
                img.draft("RGB", target_size)
            except Exception:
                pass
        img.load()
        return img


#: Part de la résolution du capteur qu'un aperçu JPEG embarqué doit couvrir
#: pour servir d'image « pleine taille » (voir load_full_resolution()) :
#: quasi exact, contrairement à la tolérance de 90 % des vignettes - un
#: aperçu sensiblement plus petit que la prise de vue n'est pas la photo
#: complète.
FULL_RESOLUTION_PREVIEW_MIN_RATIO = 0.98


def load_full_resolution(path: Path) -> Image.Image:
    """Image à la résolution COMPLÈTE de la prise de vue, en RGB - pour
    produire un fichier JPEG téléchargeable à partir d'un RAW (galerie HTML,
    option « originaux pleine taille »), à la différence de load_image() qui
    se contente d'une image « assez grande pour l'usage demandé ».

    Fichier non RAW : identique à load_image(). RAW : l'aperçu JPEG embarqué
    s'il couvre au moins FULL_RESOLUTION_PREVIEW_MIN_RATIO de la résolution
    du capteur (c'est le rendu de l'appareil lui-même, et l'extraction est
    quasi instantanée - beaucoup d'appareils y enregistrent une image pleine
    taille) ; sinon, dématriçage complet. Lève une exception en cas d'échec
    (rawpy absent, fichier illisible...) : jamais de repli sur un aperçu plus
    petit, qui serait présenté comme l'original."""
    path = Path(path)
    if not is_raw_file(path):
        return load_image(path)
    dimensions = get_original_dimensions(path)
    return _load_raw(
        path,
        # Résolution du capteur inconnue : impossible d'apprécier l'aperçu,
        # dématriçage complet.
        use_embedded_thumb=dimensions is not None,
        target_size=dimensions,
        min_ratio=FULL_RESOLUTION_PREVIEW_MIN_RATIO,
    )
