import functools
import logging
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


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
