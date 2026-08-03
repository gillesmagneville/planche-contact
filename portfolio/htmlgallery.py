from pathlib import Path
import json
import shutil
from concurrent.futures import ProcessPoolExecutor
import logging
import multiprocessing
import os
from PIL import Image, ImageOps

from .rawloader import load_image, is_raw_file
from .utils import apply_watermark

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


def _process_full_image_worker(args):
    """Fonction worker (picklable, exécutée dans un processus séparé) qui
    prépare à la fois l'image "pleine taille" ET la vignette de la galerie
    HTML à partir d'un seul et même décodage (au lieu de deux décodages
    séparés comme auparavant) : décodage (en préférant l'aperçu embarqué
    pour les RAW quand il est assez grand, voir rawloader.load_image),
    plafonnement à GALLERY_FULL_MAX_SIZE, filigrane éventuel (mosaïque
    identique aux planches contact / au PDF, voir utils.apply_watermark)
    appliqué UNE SEULE FOIS sur l'image pleine taille, puis dérivation de
    la vignette 400px par simple redimensionnement de cette version déjà
    filigranée (pas un nouveau décodage, ni un nouveau filigrane à une
    échelle différente - évite un motif disproportionné/tronqué sur un
    canevas nettement plus petit), puis enregistrement des deux JPEG - le
    tout dans le processus worker, sans repasser par le processus
    principal."""
    (image_path, images_dir_str, thumbs_dir_str, thumb_filename,
     watermark_text, watermark_opacity, watermark_orientation) = args
    images_dir = Path(images_dir_str)
    thumbs_dir = Path(thumbs_dir_str)
    path = Path(image_path)
    if not path.exists():
        return False

    out_name = HTMLGalleryGenerator.display_filename(path)
    target = (GALLERY_FULL_MAX_SIZE, GALLERY_FULL_MAX_SIZE)
    try:
        img = load_image(path, use_embedded_thumb=True, target_size=target)
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail(target, Image.Resampling.LANCZOS)

        if watermark_text:
            img = apply_watermark(img, watermark_text, watermark_opacity, watermark_orientation)

        # Vignette dérivée de l'image pleine taille CI-DESSUS, déjà
        # filigranée : simple redimensionnement, garantissant un filigrane
        # visuellement identique (juste réduit). Appliquer le motif en
        # mosaïque séparément sur un canevas ~6x plus petit (avec la même
        # taille de police et le même espacement fixes en pixels) produisait
        # un rendu disproportionné, parfois tronqué en bas de la vignette
        # selon la hauteur exacte de chaque photo (voir CHANGELOG.md).
        thumb = img.copy()
        thumb.thumbnail((400, 400), Image.Resampling.LANCZOS)

        img.save(images_dir / out_name, "JPEG", quality=90)
        thumb.save(thumbs_dir / thumb_filename, "JPEG", quality=85)
        return True
    except Exception as e:
        logging.getLogger(__name__).warning(f"Erreur sur {path.name}: {e}")
        if not is_raw_file(path):
            # Pas de fallback utile pour un RAW (illisible par un navigateur).
            try:
                shutil.copy2(path, images_dir / out_name)
            except Exception:
                pass
        return False


class HTMLGalleryGenerator:
    def __init__(self, config, thumbnail_generator):
        self.config = config
        self.thumb_gen = thumbnail_generator
        self.project_title = getattr(config, 'title', None)
        self.author = getattr(config, 'author', None)
        self.input_dir = getattr(config, 'input_dir', None)
        self.images_per_page = getattr(config, 'html_images_per_page', 48)

        self.watermark_text = getattr(config, 'watermark_text', None)
        self.watermark_opacity = getattr(config, 'watermark_opacity', 40)
        self.watermark_orientation = getattr(config, 'watermark_orientation', 'Horizontal')

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
        # Une seule passe parallèle par image : chaque worker produit à la
        # fois l'image "pleine taille" ET la vignette de la galerie (voir
        # _process_full_image_worker). Le nom de vignette est précalculé
        # ici pour rester cohérent avec le numéro de page utilisé plus bas
        # par _generate_page.
        tasks = []
        for i, item in enumerate(images):
            image_path = item.get('path') if isinstance(item, dict) else item
            if image_path:
                page_num = i // self.images_per_page + 1
                idx_in_page = i % self.images_per_page
                thumb_filename = f"thumb_p{page_num}_{idx_in_page:04d}.jpg"
                tasks.append((
                    str(image_path), str(images_dir), str(thumbs_dir), thumb_filename,
                    self.watermark_text, self.watermark_opacity, self.watermark_orientation
                ))

        results = [False] * len(images)
        if tasks:
            max_workers = min(os.cpu_count() or 4, 64)
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
                results = list(executor.map(_process_full_image_worker, tasks))

        for page_num in range(1, total_pages + 1):
            start = (page_num - 1) * self.images_per_page
            page_images = images[start : start + self.images_per_page]
            page_results = results[start : start + self.images_per_page]

            html_path = output_dir / ("index.html" if page_num == 1 else f"page_{page_num:03d}.html")

            self._generate_page(
                page_images=page_images,
                page_results=page_results,
                html_path=html_path,
                display_title=display_title,
                current_page=page_num,
                total_pages=total_pages,
                total_images=len(images),
                thumbs_dir=thumbs_dir
            )

        print(f"Galerie HTML créée : {total_pages} page(s) dans {output_dir}")

    def _generate_page(self, page_images, page_results, html_path, display_title,
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

        .lightbox {{
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.92);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }}
        .lightbox.open {{ display: flex; }}
        .lightbox img {{
            max-width: 92vw;
            max-height: 92vh;
            border-radius: 4px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.5);
        }}
        .lightbox-close, .lightbox-prev, .lightbox-next {{
            position: fixed;
            background: rgba(255,255,255,0.12);
            color: white;
            border: none;
            cursor: pointer;
            font-size: 1.8em;
            line-height: 1;
            padding: 10px 16px;
            border-radius: 6px;
            user-select: none;
        }}
        .lightbox-close:hover, .lightbox-prev:hover, .lightbox-next:hover {{
            background: rgba(255,255,255,0.28);
        }}
        .lightbox-close {{ top: 16px; right: 16px; }}
        .lightbox-prev {{ left: 16px; top: 50%; transform: translateY(-50%); }}
        .lightbox-next {{ right: 16px; top: 50%; transform: translateY(-50%); }}
        .lightbox-counter {{
            position: fixed;
            bottom: 16px;
            left: 50%;
            transform: translateX(-50%);
            color: rgba(255,255,255,0.85);
            font-size: 0.95em;
        }}
    </style>
</head>
<body>
<div class="header">
    {header_html}
</div>
{nav_html}
<div class="gallery">
"""
        full_image_urls = []
        for idx, (item, ok) in enumerate(zip(page_images, page_results)):
            if not ok:
                continue

            image_path = item.get('path') if isinstance(item, dict) else item
            filename = self.display_filename(image_path) if image_path else f"image_{idx}.jpg"
            thumb_filename = f"thumb_p{current_page}_{idx:04d}.jpg"
            # Le fichier de vignette a déjà été écrit par le worker parallèle
            # (voir _process_full_image_worker) : on référence juste son nom
            # ici, sans nouvelle écriture ni nouveau décodage.

            position = len(full_image_urls)
            full_image_urls.append(f"images/{filename}")
            html += f''' <a href="images/{filename}" onclick="return openLightbox(event, {position})">
        <img src="thumbs/{thumb_filename}" alt="">
    </a>\n'''

        html += f"""
</div>
{nav_html}
<div class="footer">
    <p>Galerie générée par Planche-Contact</p>
</div>

<div id="lightbox" class="lightbox" onclick="if (event.target === this) closeLightbox()">
    <button class="lightbox-close" onclick="closeLightbox()" aria-label="Fermer">&times;</button>
    <button class="lightbox-prev" onclick="showDelta(-1)" aria-label="Précédent">&#8249;</button>
    <img id="lightbox-img" src="" alt="">
    <button class="lightbox-next" onclick="showDelta(1)" aria-label="Suivant">&#8250;</button>
    <div class="lightbox-counter" id="lightbox-counter"></div>
</div>

<script>
    const galleryImages = {json.dumps(full_image_urls, ensure_ascii=False)};
    let currentIndex = -1;

    function openLightbox(event, index) {{
        event.preventDefault();
        currentIndex = index;
        updateLightbox();
        document.getElementById('lightbox').classList.add('open');
        return false;
    }}

    function closeLightbox() {{
        document.getElementById('lightbox').classList.remove('open');
    }}

    function showDelta(delta) {{
        if (galleryImages.length === 0) return;
        currentIndex = (currentIndex + delta + galleryImages.length) % galleryImages.length;
        updateLightbox();
    }}

    function updateLightbox() {{
        document.getElementById('lightbox-img').src = galleryImages[currentIndex];
        document.getElementById('lightbox-counter').textContent =
            (currentIndex + 1) + ' / ' + galleryImages.length;
    }}

    document.addEventListener('keydown', function(e) {{
        if (!document.getElementById('lightbox').classList.contains('open')) return;
        if (e.key === 'Escape') closeLightbox();
        else if (e.key === 'ArrowLeft') showDelta(-1);
        else if (e.key === 'ArrowRight') showDelta(1);
    }});
</script>
</body>
</html>"""
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
