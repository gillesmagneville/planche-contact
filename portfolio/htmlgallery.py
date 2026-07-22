from pathlib import Path
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from PIL import Image, ImageDraw, ImageFont


class HTMLGalleryGenerator:
    def __init__(self, config, thumbnail_generator):
        self.config = config
        self.thumb_gen = thumbnail_generator
        self.project_title = getattr(config, 'title', None)
        self.author = getattr(config, 'author', None)
        self.input_dir = getattr(config, 'input_dir', None)
        self.images_per_page = getattr(config, 'html_images_per_page', 48)

        self.watermark_text = getattr(config, 'watermark_text', None)
        self.watermark_opacity = getattr(config, 'watermark_opacity', 50)
        self.watermark_orientation = getattr(config, 'watermark_orientation', 'Horizontal')

    def _apply_light_watermark(self, image: Image.Image, text: str):
        """Filigrane léger, gris neutre, positionné au tiers inférieur"""
        if not text or image is None:
            return image

        try:
            if image.mode != 'RGBA':
                image = image.convert('RGBA')

            draw = ImageDraw.Draw(image)
            font_size = max(11, min(image.width, image.height) // 22)

            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size
                )
            except:
                font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            x = (image.width - text_width) // 2
            y = int(image.height * 0.72)

            alpha = int(255 * (self.watermark_opacity / 100))
            draw.text((x, y), text, font=font, fill=(180, 180, 180, alpha))

            return image.convert('RGB')
        except Exception as e:
            print(f"[Filigrane léger] Erreur : {e}")
            return image

    def _process_full_image(self, item, images_dir: Path):
        """Worker pour le traitement parallèle des images plein format"""
        image_path = item.get('path') if isinstance(item, dict) else item
        if not image_path or not Path(image_path).exists():
            return

        try:
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                if self.watermark_text:
                    img = self._apply_light_watermark(img, self.watermark_text)
                img.save(images_dir / Path(image_path).name, quality=90, optimize=True)
        except Exception as e:
            print(f"Erreur sur {image_path}: {e}")
            try:
                shutil.copy2(image_path, images_dir / Path(image_path).name)
            except Exception:
                pass

    def create_gallery(self, images, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        thumbs_dir = output_dir / "thumbs"
        images_dir = output_dir / "images"
        thumbs_dir.mkdir(exist_ok=True)
        images_dir.mkdir(exist_ok=True)

        display_title = self.project_title or (Path(self.input_dir).name if self.input_dir else "Galerie Photo")
        total_pages = (len(images) + self.images_per_page - 1) // self.images_per_page

        # === 1. Images plein format en parallèle ===
        max_workers = min(os.cpu_count() or 4, 8)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self._process_full_image, item, images_dir)
                for item in images
            ]
            for future in as_completed(futures):
                future.result()

        # === 2. Vignettes en parallèle ===
        thumb_size = 400
        thumbnails = self.thumb_gen.generate_parallel(images, thumb_size)

        # === 3. Application unique du filigrane sur les vignettes ===
        if self.watermark_text:
            for i, thumb in enumerate(thumbnails):
                if thumb is None:
                    continue
                try:
                    if thumb.mode != 'RGBA':
                        thumb = thumb.convert('RGBA')
                    draw = ImageDraw.Draw(thumb)

                    font_size = max(10, thumb.width // 16)
                    try:
                        font = ImageFont.truetype(
                            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size
                        )
                    except:
                        font = ImageFont.load_default()

                    bbox = draw.textbbox((0, 0), self.watermark_text, font=font)
                    text_width = bbox[2] - bbox[0]
                    x = (thumb.width - text_width) // 2
                    y = int(thumb.height * 0.72)

                    alpha = int(255 * (self.watermark_opacity / 100))
                    draw.text((x, y), self.watermark_text, font=font, fill=(180, 180, 180, alpha))
                    thumbnails[i] = thumb.convert('RGB')
                except Exception:
                    pass

        # === 4. Génération des pages HTML ===
        for page_num in range(1, total_pages + 1):
            start = (page_num - 1) * self.images_per_page
            page_images = images[start : start + self.images_per_page]
            page_thumbs = thumbnails[start : start + self.images_per_page]

            html_path = output_dir / ("index.html" if page_num == 1 else f"page_{page_num:03d}.html")

            self._generate_page(
                page_images=page_images,
                page_thumbs=page_thumbs,
                html_path=html_path,
                display_title=display_title,
                current_page=page_num,
                total_pages=total_pages,
                total_images=len(images),
                thumbs_dir=thumbs_dir
            )

        print(f"Galerie HTML créée : {total_pages} page(s) dans {output_dir}")

    def _generate_page(self, page_images, page_thumbs, html_path, display_title,
                       current_page, total_pages, total_images, thumbs_dir):
        thumbs_dir.mkdir(exist_ok=True)

        header_html = f"<h1>{display_title}</h1>"
        if self.author:
            header_html += f"<p>Par {self.author}</p>"
        header_html += f"<p>{total_images} images • Page {current_page} / {total_pages}</p>"

        # === Navigation améliorée ===
        nav_html = ""
        if total_pages > 1:
            nav_html = '<div class="nav">'

            # Bouton Précédent
            if current_page > 1:
                prev = "index.html" if current_page == 2 else f"page_{current_page-1:03d}.html"
                nav_html += f'<a href="{prev}">← Précédent</a>&nbsp;&nbsp;'

            # Numéros de pages
            if total_pages <= 15:
                pages = list(range(1, total_pages + 1))
            else:
                pages = [1]
                start = max(2, current_page - 2)
                end = min(total_pages - 1, current_page + 2)
                if start > 2:
                    pages.append("…")
                pages.extend(range(start, end + 1))
                if end < total_pages - 1:
                    pages.append("…")
                pages.append(total_pages)

            for p in pages:
                if p == "…":
                    nav_html += ' <span class="ellipsis">…</span> '
                else:
                    href = "index.html" if p == 1 else f"page_{p:03d}.html"
                    if p == current_page:
                        nav_html += f' <span class="current">{p}</span> '
                    else:
                        nav_html += f' <a href="{href}">{p}</a> '

            # Bouton Suivant
            if current_page < total_pages:
                nextp = f"page_{current_page+1:03d}.html"
                nav_html += f'&nbsp;&nbsp;<a href="{nextp}">Suivant →</a>'

            nav_html += '</div>'

        html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{display_title}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .header {{ text-align: center; margin-bottom: 20px; padding: 15px; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .header h1 {{ margin: 0; color: #222; }}
        .nav {{ text-align: center; margin: 15px 0; font-size: 1.05em; }}
        .nav a {{ margin: 0 6px; text-decoration: none; color: #0066cc; }}
        .nav a:hover {{ text-decoration: underline; }}
        .nav .current {{
            margin: 0 6px;
            font-weight: bold;
            color: #222;
            background: #e0e0e0;
            padding: 2px 8px;
            border-radius: 4px;
        }}
        .nav .ellipsis {{
            margin: 0 4px;
            color: #888;
        }}
        .gallery {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; max-width: 1400px; margin: 0 auto; }}
        .gallery img {{
            width: 100%;
            height: auto;
            border-radius: 6px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.15);
            transition: transform 0.2s;
        }}
        .gallery img:hover {{ transform: scale(1.03); }}
        .footer {{ text-align: center; margin-top: 30px; color: #666; }}
    </style>
</head>
<body>
<div class="header">
    {header_html}
</div>
{nav_html}
<div class="gallery">
"""
        for idx, (item, thumb) in enumerate(zip(page_images, page_thumbs)):
            if thumb is None:
                continue

            image_path = item.get('path') if isinstance(item, dict) else item
            filename = Path(image_path).name if image_path else f"image_{idx}"
            thumb_filename = f"thumb_p{current_page}_{idx:04d}.jpg"
            thumb_path = thumbs_dir / thumb_filename

            try:
                thumb.save(thumb_path, "JPEG", quality=85, optimize=True)
            except Exception:
                continue

            html += f''' <a href="images/{filename}" target="_blank">
        <img src="thumbs/{thumb_filename}" alt="">
    </a>\n'''

        html += f"""
</div>
{nav_html}
<div class="footer">
    <p>Galerie générée par Planche-Contact</p>
</div>
</body>
</html>"""
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
