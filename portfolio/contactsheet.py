from PIL import Image, ImageDraw, ImageFont, ImageOps
import math
from pathlib import Path

from .utils import apply_watermark


class ContactSheetGenerator:
    def __init__(self, config, thumbnail_generator):
        self.config = config
        self.thumb_gen = thumbnail_generator
        self.page_format = getattr(config, 'page_format', 'A4')
        self.project_title = getattr(config, 'title', None)
        self.author = getattr(config, 'author', None)
        self.input_dir = getattr(config, 'input_dir', None)
        self.num_per_sheet = getattr(config, 'num_per_sheet', 12)

    def _get_canvas_size(self):
        PAPER_SIZES_MM = {
            "A5": (148, 210), "A4": (210, 297), "A3": (297, 420),
            "A2": (420, 594), "Letter": (216, 279),
        }
        DPI = 300
        width_mm, height_mm = PAPER_SIZES_MM.get(self.page_format, PAPER_SIZES_MM["A4"])
        return int(width_mm * DPI / 25.4), int(height_mm * DPI / 25.4)

    def create_contact_sheet(self, images, page_num, total_pages):
        if not images:
            return None

        canvas_w, canvas_h = self._get_canvas_size()
        margin = int(12 * 300 / 25.4)
        spacing = int(5 * 300 / 25.4)
        n = len(images)

        best_cols = 1
        best_thumb_size = 0

        for cols in range(1, min(self.num_per_sheet + 1, 9)):
            rows = math.ceil(self.num_per_sheet / cols)
            available_w = canvas_w - 2 * margin
            available_h = canvas_h - 2 * margin - 180

            cell_w = available_w // cols if cols > 1 else available_w
            cell_h = available_h // rows if rows > 1 else available_h
            thumb_size = min(cell_w, cell_h)

            if thumb_size > best_thumb_size:
                best_thumb_size = thumb_size
                best_cols = cols

        thumb_size = max(best_thumb_size, 70)
        cols = best_cols

        max_thumb_w = (available_w - (cols - 1) * spacing) // cols
        thumb_size = min(thumb_size, max_thumb_w)

        thumbnails = self.thumb_gen.generate_parallel(images, thumb_size)

        sheet = Image.new("RGB", (canvas_w, canvas_h), "white")
        draw = ImageDraw.Draw(sheet)

        header_bottom_y = self._draw_header(draw, canvas_w)
        # Espace entre le bas de l'en-tête et la grille de vignettes : plus
        # généreux que la version précédente, aligné sur la même valeur que
        # les marges latérales/basse pour une composition équilibrée.
        content_gap = margin
        y_start = header_bottom_y + content_gap

        for idx, thumb in enumerate(thumbnails):
            if thumb is None:
                continue

            if self.config.watermark_text:
                thumb = apply_watermark(
                    thumb,
                    self.config.watermark_text,
                    getattr(self.config, 'watermark_opacity', 40),
                    getattr(self.config, 'watermark_orientation', 'Horizontal')
                )

            row = idx // cols
            col = idx % cols
            x = margin + col * (thumb_size + spacing)
            y = y_start + row * (thumb_size + spacing)
            sheet.paste(thumb, (x, y))

        self._draw_page_number(draw, canvas_w, canvas_h, page_num, total_pages)
        return sheet

    def _draw_header(self, draw, canvas_w):
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 54)
            font_author = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        except:
            font_title = font_author = ImageFont.load_default()

        # Marge haute réduite avant l'en-tête (6 mm, contre ~9,5 mm
        # auparavant) : le titre démarre nettement plus près du haut de la
        # planche/page.
        y = int(6 * 300 / 25.4)

        # Si aucun champ (titre, auteur, filigrane) n'a été renseigné, la
        # planche serait totalement anonyme : on affiche alors par défaut
        # le nom du dossier source (sans son chemin complet) en guise de
        # titre.
        watermark_text = getattr(self.config, 'watermark_text', None)
        display_title = self.project_title
        if not display_title and not self.author and not watermark_text and self.input_dir:
            display_title = Path(self.input_dir).name

        if display_title:
            bbox = draw.textbbox((0, 0), display_title, font=font_title)
            text_w = bbox[2] - bbox[0]
            draw.text(((canvas_w - text_w) / 2, y), display_title, fill="black", font=font_title)
            y += 58

        if self.author:
            bbox = draw.textbbox((0, 0), self.author, font=font_author)
            text_w = bbox[2] - bbox[0]
            draw.text(((canvas_w - text_w) / 2, y), self.author, fill="black", font=font_author)
            y += 42

        return y

    def _draw_page_number(self, draw, canvas_w, canvas_h, page_num, total_pages):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        except:
            font = font_small = ImageFont.load_default()

        page_text = f"Planche {page_num}/{total_pages}"
        bbox = draw.textbbox((0, 0), page_text, font=font)
        page_w = bbox[2] - bbox[0]
        draw.text(((canvas_w - page_w) / 2, canvas_h - 90), page_text, fill="black", font=font)

        credit = "Planche générée par Planche-Contact"
        bbox = draw.textbbox((0, 0), credit, font=font_small)
        credit_w = bbox[2] - bbox[0]
        draw.text(((canvas_w - credit_w) / 2, canvas_h - 50), credit, fill="#555555", font=font_small)
