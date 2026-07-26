from pathlib import Path
import shutil
from concurrent.futures import ProcessPoolExecutor
import logging
import multiprocessing
import os
from PIL import Image, ImageDraw, ImageFont

from .rawloader import load_image, is_raw_file

# Taille max. (plus grand côté) des images "pleine taille" de la galerie
# HTML. Une photo RAW de 45 Mpx pleinement dématricée puis enregistrée telle
# quelle est à la fois très lente à produire et beaucoup plus lourde à
# charger dans un navigateur qu'utile pour une vue agrandie à l'écran :
# 2000px de long côté est largement suffisant pour un affichage plein écran.
GALLERY_FULL_MAX_SIZE = 2000


def _init_worker_logging(log_path):
    """Reconfigure le logging dans les processus enfants (nécessaire avec
    'spawn', qui ne partage pas la configuration du processus parent)."""
    if log_path:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.FileHandler(log_path, encoding="utf-8")],
            force=True,
        )


def _apply_light_watermark_standalone(image, text, opacity):
    """Version autonome (sans self) de HTMLGalleryGenerator._apply_light_watermark,
    pour pouvoir être appelée depuis un processus worker séparé."""
    if not text or image is None:
        return image
    if not text.startswith("©"):
        text = "© " + text
    try:
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        draw = ImageDraw.Draw(image)
        font_size = max(11, min(image.width, image.height) // 22)
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size
            )
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        x = (image.width - text_width) // 2
        y = int(image.height * 0.72)
        alpha = int(255 * (opacity / 100))
        draw.text((x, y), text, font=font, fill=(180, 180, 180, alpha))
        return image.convert('RGB')
    except Exception as e:
        logging.getLogger(__name__).debug(f"Filigrane léger : {e}")
        return image


def _process_full_image_worker(args):
    """Fonction worker (picklable, exécutée dans un processus séparé) qui
    prépare une image "pleine taille" pour la galerie HTML : décodage
    (en préférant l'aperçu embarqué pour les RAW quand il est assez grand,
    voir rawloader.load_image), plafonnement à GALLERY_FULL_MAX_SIZE,
    filigrane éventuel, puis enregistrement en JPEG."""
    image_path, images_dir_str, watermark_text, watermark_opacity = args
    images_dir = Path(images_dir_str)
    path = Path(image_path)
    if not path.exists():
        return

    out_name = HTMLGalleryGenerator.display_filename(path)
    target = (GALLERY_FULL_MAX_SIZE, GALLERY_FULL_MAX_SIZE)
    try:
        img = load_image(path, use_embedded_thumb=True, target_size=target)
        img = img.convert("RGB")
        img.thumbnail(target, Image.Resampling.LANCZOS)
        if watermark_text:
            img = _apply_light_watermark_standalone(img, watermark_text, watermark_opacity)
        img.save(images_dir / out_name, "JPEG", quality=90)
    except Exception as e:
        logging.getLogger(__name__).warning(f"Erreur sur {path.name}: {e}")
        if not is_raw_file(path):
            # Pas de fallback utile pour un RAW (illisible par un navigateur).
            try:
                shutil.copy2(path, images_dir / out_name)
            except Exception:
                pass


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
        if not text or image is None:
            return image

        # Ajout automatique du symbole copyright
        if not text.startswith("©"):
            text = "© " + text

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

    @staticmethod
    def display_filename(image_path) -> str:
        """
        Nom du fichier tel qu'il sera servi dans la galerie. Les fichiers RAW sont
        décodés en JPEG (un navigateur ne peut pas afficher un .cr2/.nef/...), donc
        leur extension est remplacée par .jpg.
        """
        path = Path(image_path)
        if is_raw_file(path):
            return path.stem + ".jpg"
        return path.name

    def create_gallery(self, images, output_dir: Path):
        if output_dir.exists():
            shutil.rmtree(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)
        thumbs_dir = output_dir / "thumbs"
        images_dir = output_dir / "images"
        thumbs_dir.mkdir(exist_ok=True)
        images_dir.mkdir(exist_ok=True)

        display_title = self.project_title or (Path(self.input_dir).name if self.input_dir else "Galerie Photo")
        total_pages = (len(images) + self.images_per_page - 1) // self.images_per_page

        # Des processus séparés plutôt que des threads : le décodage RAW et
        # l'encodage JPEG sont des tâches CPU-intensives, et de vrais
        # processus exploitent mieux plusieurs cœurs qu'un pool de threads
        # (même si les bibliothèques C sous-jacentes libèrent le GIL). Même
        # contexte 'spawn' que pour les vignettes (voir thumbnail.py) : rawpy
        # utilise OpenMP en interne, incompatible avec fork().
        tasks = []
        for item in images:
            image_path = item.get('path') if isinstance(item, dict) else item
            if image_path:
                tasks.append((str(image_path), str(images_dir), self.watermark_text, self.watermark_opacity))

        if tasks:
            max_workers = min(os.cpu_count() or 4, 8)
            ctx = multiprocessing.get_context("spawn")
            log_path = None
            for handler in logging.getLogger().handlers:
                if isinstance(handler, logging.FileHandler):
                    log_path = handler.baseFilename
                    break

            with ProcessPoolExecutor(
                max_workers=max_workers,
                mp_context=ctx,
                initializer=_init_worker_logging,
                initargs=(log_path,),
            ) as executor:
                for _ in executor.map(_process_full_image_worker, tasks):
                    pass

        thumb_size = 400
        thumbnails = self.thumb_gen.generate_parallel(images, thumb_size)

        if self.watermark_text:
            wm_text = self.watermark_text
            if not wm_text.startswith("©"):
                wm_text = "© " + wm_text

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

                    bbox = draw.textbbox((0, 0), wm_text, font=font)
                    text_width = bbox[2] - bbox[0]
                    x = (thumb.width - text_width) // 2
                    y = int(thumb.height * 0.72)

                    alpha = int(255 * (self.watermark_opacity / 100))
                    draw.text((x, y), wm_text, font=font, fill=(180, 180, 180, alpha))
                    thumbnails[i] = thumb.convert('RGB')
                except Exception:
                    pass

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

        nav_html = ""
        if total_pages > 1:
            nav_html = '<div class="nav">'

            if current_page > 1:
                prev = "index.html" if current_page == 2 else f"page_{current_page-1:03d}.html"
                nav_html += f'<a href="{prev}">← Précédent</a>&nbsp;&nbsp;'

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
            filename = self.display_filename(image_path) if image_path else f"image_{idx}.jpg"
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
