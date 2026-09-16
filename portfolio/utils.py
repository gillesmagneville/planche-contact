import functools
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

from .rawloader import is_raw_file

try:
    import exifread
    EXIFREAD_AVAILABLE = True
except ImportError:
    EXIFREAD_AVAILABLE = False


def setup_logging(log_path: Path) -> None:
    """Configure le logging (fichier + console)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


# Police embarquée avec le projet (portfolio/fonts/, licence Bitstream Vera
# - voir portfolio/fonts/LICENSE.txt), utilisée en priorité : garantit un
# rendu strictement identique sur toutes les plateformes, plutôt que de
# dépendre d'une police système trouvée à un chemin devinable (ex:
# C:/Windows/Fonts/arial.ttf), qui peut échouer silencieusement selon la
# machine et faire retomber sur la police minuscule intégrée à Pillow.
_BUNDLED_FONTS_DIR = Path(__file__).parent / "fonts"


@functools.lru_cache(maxsize=32)
def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Charge une police TrueType de manière cross-platform.
    Retourne la police par défaut si aucune police système n'est trouvée.
    Mise en cache : évite de relire/reparser le fichier de police à chaque
    appel (des centaines de fois sur une galerie de centaines de photos
    avec filigrane).
    """
    suffix = "-Bold" if bold else ""
    candidates = [
        _BUNDLED_FONTS_DIR / f"DejaVuSans{suffix}.ttf",
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{suffix}.ttf",
        f"C:/Windows/Fonts/arial{'bd' if bold else ''}.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def apply_watermark(
    image: Image.Image,
    text: str,
    opacity: int = 70,
    orientation: str = "Horizontal"
) -> Image.Image:
    """
    Filigrane en mosaïque répétée, utilisé de façon identique par les
    planches contact (et donc le PDF, qui réutilise ces mêmes images) et la
    galerie HTML - une seule implémentation, pour garantir un rendu
    strictement identique partout.

    `opacity` est un pourcentage (0-100), converti ici en canal alpha
    (0-255).
    """
    if not text:
        return image

    # Ajout automatique du symbole copyright (comportement des deux
    # implémentations d'origine, conservé ici).
    if not text.startswith("©"):
        text = "© " + text

    try:
        img = image.convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        font = get_font(14, bold=True)

        alpha = max(0, min(255, int(255 * (opacity / 100))))
        text_color = (255, 255, 255, alpha)

        # Gestion de l'orientation. PIL fait pivoter dans le sens
        # anti-horaire pour un angle positif : "horaire" correspond donc à
        # un angle négatif, et inversement.
        if orientation == "Diagonale horaire":
            angle = -32
        elif orientation == "Diagonale anti-horaire":
            angle = 32
        else:
            angle = 0

        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Espacement (identique aux planches)
        x_spacing = text_width + 220
        y_spacing = text_height + 160

        for y in range(-text_height, img.height + text_height, y_spacing):
            for x in range(-text_width, img.width + text_width, x_spacing):
                offset_x = (y // y_spacing) * 50 if angle != 0 else 0
                draw.text((x + offset_x, y), text, font=font, fill=text_color)

        # Rotation si besoin
        if angle != 0:
            overlay = overlay.rotate(angle, resample=Image.BICUBIC, expand=False, center=(img.width / 2, img.height / 2))

        return Image.alpha_composite(img, overlay).convert("RGB")

    except Exception as e:
        logging.getLogger(__name__).warning(f"Filigrane impossible : {e}")
        return image


def get_exif_date(path: Path) -> Optional[datetime]:
    """Extrait la date EXIF la plus pertinente (prise de vue), RAW compris.
    Centralisé ici : utilisé à la fois pour le tri des photos
    (scanner.py) et pour les informations affichées dans la visionneuse
    de la galerie HTML (htmlgallery.py)."""
    path = Path(path)
    if is_raw_file(path):
        if not EXIFREAD_AVAILABLE:
            return None
        try:
            with open(path, "rb") as f:
                tags = exifread.process_file(f, details=False, stop_tag="EXIF DateTimeOriginal")
            for key in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"):
                date_str = tags.get(key)
                if date_str:
                    try:
                        return datetime.strptime(str(date_str), "%Y:%m:%d %H:%M:%S")
                    except ValueError:
                        continue
        except Exception:
            pass
        return None

    try:
        with Image.open(path) as img:
            exif = img.getexif()
            # DateTimeOriginal (0x9003) et DateTimeDigitized (0x9004) vivent
            # dans le sous-IFD Exif, jamais dans l'IFD0 principal : exif.get()
            # direct ne les trouve pas, il faut passer par get_ifd(). Seul
            # DateTime (0x0132, date de MODIFICATION du fichier, moins
            # pertinente qu'une date de prise de vue) vit dans l'IFD0.
            exif_ifd = exif.get_ifd(0x8769)  # ExifTags.IFD.Exif
            for tag in (0x9003, 0x9004):
                date_str = exif_ifd.get(tag)
                if date_str:
                    try:
                        return datetime.strptime(str(date_str), "%Y:%m:%d %H:%M:%S")
                    except ValueError:
                        continue
            date_str = exif.get(0x0132)
            if date_str:
                try:
                    return datetime.strptime(str(date_str), "%Y:%m:%d %H:%M:%S")
                except ValueError:
                    pass
    except Exception:
        pass
    return None


def format_file_size(num_bytes: int) -> str:
    """Taille de fichier lisible (ex: "4,2 Mo"), utilisée pour les
    informations affichées dans la visionneuse de la galerie HTML."""
    size = float(num_bytes)
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024 or unit == "Go":
            if unit == "o":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}".replace(".", ",")
        size /= 1024
    return f"{size:.1f} Go".replace(".", ",")
