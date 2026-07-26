from PIL import Image, ImageDraw, ImageFont, ImageOps
import math
from pathlib import Path


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

        header_height = self._draw_header(draw, canvas_w, margin)
        y_start = margin + header_height + 42

        for idx, thumb in enumerate(thumbnails):
            if thumb is None:
                continue

            if self.config.watermark_text:
                thumb = self._apply_watermark(
                    thumb,
                    self.config.watermark_text,
                    getattr(self.config, 'watermark_opacity', 70),
                    getattr(self.config, 'watermark_orientation', 'Horizontal')
                )

            row = idx // cols
            col = idx % cols
            x = margin + col * (thumb_size + spacing)
            y = y_start + row * (thumb_size + spacing)
            sheet.paste(thumb, (x, y))

        self._draw_page_number(draw, canvas_w, canvas_h, page_num, total_pages)
        return sheet

    def _draw_header(self, draw, canvas_w, margin):
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 54)
            font_author = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        except:
            font_title = font_author = ImageFont.load_default()

        y = margin - 30

        if self.project_title:
            bbox = draw.textbbox((0, 0), self.project_title, font=font_title)
            text_w = bbox[2] - bbox[0]
            draw.text(((canvas_w - text_w) / 2, y), self.project_title, fill="black", font=font_title)
            y += 58

        if self.author:
            bbox = draw.textbbox((0, 0), self.author, font=font_author)
            text_w = bbox[2] - bbox[0]
            draw.text(((canvas_w - text_w) / 2, y), self.author, fill="black", font=font_author)
            y += 42

        return y - margin

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

    def _apply_watermark(self, image, text, opacity=70, orientation="Horizontal"):
        if not text:
            return image

        # Ajout automatique du symbole copyright
        if not text.startswith("©"):
            text = "© " + text

        img = image.convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
        except:
            font = ImageFont.load_default()

        text_color = (255, 255, 255, opacity)

        if orientation == "Diagonale horaire":
            angle = -32
        elif orientation == "Diagonale anti-horaire":
            angle = 32
        else:
            angle = 0

        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        x_spacing = text_width + 220
        y_spacing = text_height + 160

        for y in range(-text_height, img.height + text_height, y_spacing):
            for x in range(-text_width, img.width + text_width, x_spacing):
                offset_x = (y // y_spacing) * 50 if angle != 0 else 0
                draw.text((x + offset_x, y), text, font=font, fill=text_color)

        if angle != 0:
            overlay = overlay.rotate(angle, resample=Image.BICUBIC, expand=False, center=(img.width/2, img.height/2))

        return Image.alpha_composite(img, overlay).convert("RGB")
