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


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Charge une police TrueType de manière cross-platform.
    Retourne la police par défaut si aucune police système n'est trouvée.
    """
    candidates = [
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
        f"C:/Windows/Fonts/arial{'bd' if bold else ''}.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
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
    Filigrane identique à celui utilisé dans les planches contact.
    Respecte l'opacité et l'orientation demandées.
    """
    if not text:
        return image

    try:
        img = image.convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        font = get_font(20, bold=True)

        text_color = (255, 255, 255, opacity)

        # Gestion de l'orientation
        if orientation == "Diagonale horaire":
            angle = 32
        elif orientation == "Diagonale anti-horaire":
            angle = -32
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
        print(f"[utils.apply_watermark] Erreur : {e}")
        return image
