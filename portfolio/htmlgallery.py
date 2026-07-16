from pathlib import Path
import shutil
from PIL import Image

from portfolio.utils import apply_watermark


class HTMLGalleryGenerator:
    def __init__(self, config, thumbnail_generator):
        self.config = config
        self.thumb_gen = thumbnail_generator
        self.project_title = getattr(config, 'title', None)
        self.author = getattr(config, 'author', None)
        self.input_dir = getattr(config, 'input_dir', None)
        self.images_per_page = getattr(config, 'html_images_per_page', 48)

        self.watermark_text = getattr(config, 'watermark_text', None)
        self.watermark_opacity = getattr(config, 'watermark_opacity', 45)
        self.watermark_orientation = getattr(config, 'watermark_orientation', 'Horizontal')

    def create_gallery(self, images, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        thumbs_dir = output_dir / "thumbs"
        images_dir = output_dir / "images"
        thumbs_dir.mkdir(exist_ok=True)
        images_dir.mkdir(exist_ok=True)

        display_title = self.project_title or (Path(self.input_dir).name if self.input_dir else "Galerie Photo")
        folder_name = Path(self.input_dir).name if self.input_dir else ""
        total_pages = (len(images) + self.images_per_page - 1) // self.images_per_page

        # Images originales + filigrane
        for item in images:
            image_path = item.get('path') if isinstance(item, dict) else item
            if image_path and Path(image_path).exists():
                try:
                    img = Image.open(image_path)
                    if self.watermark_text:
                        img = apply_watermark(
                            img,
                            self.watermark_text,
                            self.watermark_opacity,
                            self.watermark_orientation
                        )
                    img.save(images_dir / Path(image_path).name, quality=90)
                except Exception as e:
                    print(f"Erreur sur {image_path}: {e}")
                    shutil.copy2(image_path, images_dir / Path(image_path).name)

        # Miniatures + filigrane
        thumb_size = 400
        thumbnails = self.thumb_gen.generate_parallel(images, thumb_size)

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
                folder_name=folder_name,
                current_page=page_num,
                total_pages=total_pages,
                total_images=len(images),
                thumbs_dir=thumbs_dir
            )

        print(f"Galerie HTML créée : {total_pages} page(s) dans {output_dir}")

    def _generate_page(self, page_images, page_thumbs, html_path, display_title, folder_name,
                       current_page, total_pages, total_images, thumbs_dir):
        thumbs_dir.mkdir(exist_ok=True)

        # En-tête avec titre + auteur
        header_html = f"<h1>{display_title}</h1>"
        if folder_name:
            header_html += f"<p>{folder_name}</p>"
        if self.author:
            header_html += f"<p>Par {self.author}</p>"
        header_html += f"<p>{total_images} images • Page {current_page} / {total_pages}</p>"

        nav_html = ""
        if total_pages > 1:
            nav_html = '<div class="nav">'
            if current_page > 1:
                prev = "index.html" if current_page == 2 else f"page_{current_page-1:03d}.html"
                nav_html += f'<a href="{prev}">← Précédent</a> '
            nav_html += f'Page {current_page} / {total_pages} '
            if current_page < total_pages:
                nextp = f"page_{current_page+1:03d}.html"
                nav_html += f'<a href="{nextp}">Suivant →</a>'
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
        .nav {{ text-align: center; margin: 15px 0; }}
        .nav a {{ margin: 0 12px; text-decoration: none; color: #0066cc; font-size: 1.1em; }}
        .gallery {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; max-width: 1400px; margin: 0 auto; }}
        .gallery img {{ width: 100%; height: 200px; object-fit: cover; border-radius: 6px; box-shadow: 0 2px 6px rgba(0,0,0,0.15); transition: transform 0.2s; }}
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

            # Application du filigrane centré sur la miniature
            if self.watermark_text and thumb:
                thumb = apply_watermark(
                    thumb,
                    self.watermark_text,
                    self.watermark_opacity,
                    self.watermark_orientation
                )

            thumb.save(thumb_path, "JPEG", quality=85)

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
