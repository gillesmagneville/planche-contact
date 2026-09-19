from pathlib import Path
import json
import shutil
from concurrent.futures import ProcessPoolExecutor
import logging
import multiprocessing
import os
from PIL import Image, ImageOps

from .rawloader import load_image, is_raw_file, get_original_dimensions
from .utils import apply_watermark, get_exif_date, format_file_size
from .i18n import _, get_language

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
    principal. Calcule également les métadonnées affichées dans la
    visionneuse (résolution réelle d'origine, taille du fichier, date de
    prise de vue) pendant que le fichier est déjà ouvert, plutôt qu'une
    passe séparée qui relirait chaque photo une seconde fois."""
    (image_path, images_dir_str, thumbs_dir_str, thumb_filename,
     watermark_text, watermark_opacity, watermark_orientation) = args
    images_dir = Path(images_dir_str)
    thumbs_dir = Path(thumbs_dir_str)
    path = Path(image_path)
    if not path.exists():
        return (False, None)

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

        dimensions = get_original_dimensions(path)
        exif_date = get_exif_date(path)
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = None

        metadata = {
            "filename": out_name,
            "width": dimensions[0] if dimensions else None,
            "height": dimensions[1] if dimensions else None,
            "size": format_file_size(size_bytes) if size_bytes is not None else None,
            "date": exif_date.strftime("%d/%m/%Y %H:%M") if exif_date else None,
        }
        return (True, metadata)
    except Exception as e:
        logging.getLogger(__name__).warning(f"Erreur sur {path.name}: {e}")
        if not is_raw_file(path):
            # Pas de fallback utile pour un RAW (illisible par un navigateur).
            try:
                shutil.copy2(path, images_dir / out_name)
            except Exception:
                pass
        return (False, None)


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

        results = [(False, None)] * len(images)
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

        page_ok = [ok for ok, _ in results]
        page_meta_all = [meta for _, meta in results]

        for page_num in range(1, total_pages + 1):
            start = (page_num - 1) * self.images_per_page
            page_images = images[start : start + self.images_per_page]
            page_results = page_ok[start : start + self.images_per_page]
            page_meta = page_meta_all[start : start + self.images_per_page]

            html_path = output_dir / ("index.html" if page_num == 1 else f"page_{page_num:03d}.html")

            self._generate_page(
                page_images=page_images,
                page_results=page_results,
                page_meta=page_meta,
                html_path=html_path,
                display_title=display_title,
                current_page=page_num,
                total_pages=total_pages,
                total_images=len(images),
                thumbs_dir=thumbs_dir
            )

        print(_("gallery.created_log", pages=total_pages, dir=output_dir))

    def _generate_page(self, page_images, page_results, page_meta, html_path, display_title,
                       current_page, total_pages, total_images, thumbs_dir):
        thumbs_dir.mkdir(exist_ok=True)

        header_html = f"<h1>{display_title}</h1>"
        if self.author:
            header_html += f"<p>{_('gallery.by_author', author=self.author)}</p>"
        header_html += f"<p>{_('gallery.header_count', count=total_images, current=current_page, total=total_pages)}</p>"

        nav_html = ""
        if total_pages > 1:
            nav_html = '<div class="nav">'

            if current_page > 1:
                prev = "index.html" if current_page == 2 else f"page_{current_page-1:03d}.html"
                nav_html += f'<a href="{prev}">{_("gallery.nav_prev")}</a>&nbsp;&nbsp;'

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
                nav_html += f'&nbsp;&nbsp;<a href="{nextp}">{_("gallery.nav_next")}</a>'

            nav_html += '</div>'

        html = f"""<!DOCTYPE html>
<html lang="{get_language()}">
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
            /* L'image reste TOUJOURS centrée, même zoomée au-delà de
               l'écran (voir plus bas) : le débordement est simplement
               rogné ici, jamais défilé nativement - le déplacement dans
               l'image zoomée se fait par glisser-déposer (transform:
               translate() piloté en JS), pas par défilement du navigateur.
               Un centrage flex classique + overflow: auto ne révèle pas la
               partie qui dépasse en haut/à gauche au défilement ; cette
               approche par transform contourne le problème à la racine. */
            overflow: hidden;
        }}
        .lightbox.open {{ display: flex; }}
        .lightbox img {{
            max-width: 92vw;
            max-height: 92vh;
            border-radius: 4px;
            box-shadow: 0 4px 24px rgba(0,0,0,0.5);
            transition: width 0.15s ease-out, height 0.15s ease-out;
            /* Pas de transition sur transform : le glisser-déposer doit
               suivre la souris/le doigt en temps réel, sans latence. */
            /* z-index explicite : sans lui, une fois zoomée (largeur/hauteur
               agrandies), l'image passait devant la barre du haut et les
               flèches précédent/suivant malgré leur position: fixed - un
               élément "positionné" via z-index auto se classe par ordre du
               DOM, pas par sa taille. */
            position: relative;
            z-index: 1;
            touch-action: none;
        }}
        .lightbox img.zoomed {{ cursor: grab; }}
        .lightbox img.zoomed.dragging {{ cursor: grabbing; }}
        .lightbox-prev, .lightbox-next {{
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
            z-index: 10;
        }}
        .lightbox-prev:hover, .lightbox-next:hover {{
            background: rgba(255,255,255,0.28);
        }}
        .lightbox-prev {{ left: 16px; top: 50%; transform: translateY(-50%); }}
        .lightbox-next {{ right: 16px; top: 50%; transform: translateY(-50%); }}

        .lightbox-topbar {{
            position: fixed;
            z-index: 10;
            top: 0; left: 0; right: 0;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            padding: 10px 16px;
            background: rgba(0,0,0,0.55);
            color: white;
            box-sizing: border-box;
            font-size: 0.95em;
        }}
        .lightbox-filename {{
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            opacity: 0.9;
        }}
        .lightbox-page-indicator {{
            opacity: 0.75;
            white-space: nowrap;
            margin-left: auto;
            margin-right: 12px;
        }}
        .lightbox-actions {{ display: flex; gap: 6px; flex-shrink: 0; }}
        .lightbox-btn {{
            background: rgba(255,255,255,0.12);
            color: white;
            border: none;
            cursor: pointer;
            font-size: 1.2em;
            line-height: 1;
            padding: 6px 12px;
            border-radius: 6px;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
        }}
        .lightbox-btn:hover {{ background: rgba(255,255,255,0.28); }}
        .lightbox-zoom-level {{
            min-width: 3.4em;
            justify-content: center;
            font-size: 0.85em;
            cursor: pointer;
        }}

        .lightbox-bottombar {{
            position: fixed;
            z-index: 10;
            bottom: 0; left: 0; right: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 24px;
            padding: 10px 16px;
            background: rgba(0,0,0,0.55);
            color: rgba(255,255,255,0.9);
            box-sizing: border-box;
            font-size: 0.9em;
        }}
        .lightbox-goto {{ display: flex; align-items: center; gap: 6px; }}
        .lightbox-goto input {{
            width: 4.5em;
            padding: 3px 6px;
            border-radius: 4px;
            border: none;
        }}
        .lightbox-goto button {{
            background: rgba(255,255,255,0.15);
            color: white;
            border: none;
            border-radius: 4px;
            padding: 4px 10px;
            cursor: pointer;
        }}
        .lightbox-goto button:hover {{ background: rgba(255,255,255,0.3); }}
        .lightbox-counter {{ white-space: nowrap; }}

        .lightbox-info {{
            display: none;
            position: fixed;
            z-index: 20;
            top: 56px;
            right: 16px;
            background: rgba(20,20,20,0.92);
            color: rgba(255,255,255,0.92);
            padding: 14px 18px;
            border-radius: 8px;
            font-size: 0.9em;
            max-width: 320px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.4);
        }}
        .lightbox-info.open {{ display: block; }}
        .lightbox-info p {{ margin: 4px 0; }}

        .lightbox-toast {{
            position: fixed;
            z-index: 20;
            bottom: 56px;
            left: 50%;
            transform: translateX(-50%) translateY(10px);
            max-width: 90vw;
            width: max-content;
            background: rgba(20,20,20,0.95);
            color: rgba(255,255,255,0.95);
            padding: 10px 18px;
            border-radius: 8px;
            font-size: 0.88em;
            text-align: center;
            box-shadow: 0 4px 16px rgba(0,0,0,0.4);
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.2s, transform 0.2s;
        }}
        .lightbox-toast.show {{
            opacity: 1;
            visibility: visible;
            transform: translateX(-50%) translateY(0);
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
        gallery_meta = []
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
            meta = page_meta[idx] or {}
            width, height = meta.get("width"), meta.get("height")
            gallery_meta.append({
                "filename": meta.get("filename") or filename,
                "resolution": f"{width} × {height} px" if width and height else _("gallery.unknown"),
                "size": meta.get("size") or _("gallery.unknown"),
                "date": meta.get("date") or _("gallery.unknown"),
            })
            html += f''' <a href="images/{filename}" onclick="return openLightbox(event, {position})">
        <img src="thumbs/{thumb_filename}" alt="">
    </a>\n'''

        goto_page_html = ""
        if total_pages > 1:
            goto_page_html = (
                '<div class="lightbox-goto">'
                f'<label for="goto-page-input">{_("gallery.goto_page_label")}</label>'
                f'<input type="number" id="goto-page-input" min="1" max="{total_pages}" placeholder="1-{total_pages}">'
                f'<button onclick="goToPage()">{_("gallery.goto_page_ok")}</button>'
                '</div>'
            )

        # Pré-échappé pour JS (json.dumps échappe correctement guillemets/
        # apostrophes quelle que soit la langue, plus sûr qu'un échappement
        # manuel - les traductions contiennent chacune leur propre
        # ponctuation).
        download_toast_js = json.dumps(_("gallery.download_toast"), ensure_ascii=False)
        wrap_forward_js = json.dumps(_("gallery.wrap_forward"), ensure_ascii=False)
        wrap_backward_js = json.dumps(_("gallery.wrap_backward"), ensure_ascii=False)

        html += f"""
</div>
{nav_html}
<div class="footer">
    <p>{_('gallery.footer')}</p>
    <p>{_('gallery.footer_credit', name='Gilles MAGNEVILLE')}</p>
</div>

<div id="lightbox" class="lightbox" onclick="if (event.target === this) closeLightbox()">
    <div class="lightbox-topbar">
        <span id="lightbox-filename" class="lightbox-filename"></span>
        <span class="lightbox-page-indicator">{_('gallery.lightbox_page', current=current_page, total=total_pages)}</span>
        <div class="lightbox-actions">
            <button class="lightbox-btn" onclick="zoomOut()" aria-label="{_('gallery.zoom_out')}" title="{_('gallery.zoom_out_title')}">&minus;</button>
            <button class="lightbox-btn lightbox-zoom-level" id="lightbox-zoom-level" onclick="zoomReset()" aria-label="{_('gallery.zoom_reset_label')}" title="{_('gallery.zoom_reset_title')}">100 %</button>
            <button class="lightbox-btn" onclick="zoomIn()" aria-label="{_('gallery.zoom_in')}" title="{_('gallery.zoom_in_title')}">&plus;</button>
            <button class="lightbox-btn" onclick="toggleInfo()" aria-label="{_('gallery.info')}" title="{_('gallery.info')}">&#9432;</button>
            <a id="lightbox-download" class="lightbox-btn" href="#" onclick="downloadCurrentImage(); return false;" aria-label="{_('gallery.download')}" title="{_('gallery.download')}">&#8681;</a>
            <button class="lightbox-btn" onclick="toggleFullscreen()" aria-label="{_('gallery.fullscreen')}" title="{_('gallery.fullscreen')}">&#10530;</button>
            <button class="lightbox-btn" onclick="closeLightbox()" aria-label="{_('gallery.close')}" title="{_('gallery.close')}">&times;</button>
        </div>
    </div>

    <button class="lightbox-prev" onclick="showDelta(-1)" aria-label="{_('gallery.prev')}">&#8249;</button>
    <img id="lightbox-img" src="" alt="">
    <button class="lightbox-next" onclick="showDelta(1)" aria-label="{_('gallery.next')}">&#8250;</button>

    <div id="lightbox-info" class="lightbox-info">
        <p><strong>{_('gallery.info_filename')}</strong> <span id="info-filename"></span></p>
        <p><strong>{_('gallery.info_resolution')}</strong> <span id="info-resolution"></span></p>
        <p><strong>{_('gallery.info_size')}</strong> <span id="info-size"></span></p>
        <p><strong>{_('gallery.info_date')}</strong> <span id="info-date"></span></p>
    </div>

    <div id="lightbox-toast" class="lightbox-toast"></div>

    <div class="lightbox-bottombar">
        <div class="lightbox-counter" id="lightbox-counter"></div>
        {goto_page_html}
    </div>
</div>

<script>
    const galleryImages = {json.dumps(full_image_urls, ensure_ascii=False)};
    const galleryMeta = {json.dumps(gallery_meta, ensure_ascii=False)};
    const totalPages = {total_pages};
    const currentPage = {current_page};
    let currentIndex = -1;
    let currentZoom = 100;
    let baseWidth = 0, baseHeight = 0;
    let panX = 0, panY = 0;
    let isDragging = false;
    let dragStartX = 0, dragStartY = 0, panStartX = 0, panStartY = 0;
    const ZOOM_MIN = 50, ZOOM_MAX = 200, ZOOM_STEP = 10;
    let lastWheelAction = 0;
    const WHEEL_THROTTLE_MS = 150;

    function pageUrl(n) {{
        return n === 1 ? 'index.html' : 'page_' + String(n).padStart(3, '0') + '.html';
    }}

    function openLightbox(event, index) {{
        event.preventDefault();
        currentIndex = index;
        updateLightbox();
        document.getElementById('lightbox').classList.add('open');
        return false;
    }}

    function closeLightbox() {{
        document.getElementById('lightbox').classList.remove('open');
        document.getElementById('lightbox-info').classList.remove('open');
    }}

    function showDelta(delta) {{
        if (galleryImages.length === 0) return;
        const newIndex = currentIndex + delta;

        // Au-delà des bornes de la page en cours : passe réellement à la
        // page suivante/précédente (avec bouclage sur l'ensemble de la
        // galerie aux deux extrémités) plutôt que de boucler sur les
        // photos de cette seule page. Une galerie d'une seule page n'a
        // nulle part où aller : elle garde l'ancien comportement (simple
        // bouclage local, sans recharger la page pour rien).
        if (totalPages > 1 && (newIndex < 0 || newIndex >= galleryImages.length)) {{
            if (newIndex < 0) {{
                const wrapping = currentPage === 1;
                const targetPage = wrapping ? totalPages : currentPage - 1;
                window.location.href = pageUrl(targetPage) + '?open=last' + (wrapping ? '&wrap=back' : '');
            }} else {{
                const wrapping = currentPage === totalPages;
                const targetPage = wrapping ? 1 : currentPage + 1;
                window.location.href = pageUrl(targetPage) + '?open=0' + (wrapping ? '&wrap=fwd' : '');
            }}
            return;
        }}

        currentIndex = (newIndex + galleryImages.length) % galleryImages.length;
        updateLightbox();
    }}

    function triggerBlobDownload(blob, filename) {{
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
    }}

    function showToast(message) {{
        const toast = document.getElementById('lightbox-toast');
        toast.textContent = message;
        toast.classList.add('show');
        clearTimeout(toast._hideTimer);
        toast._hideTimer = setTimeout(() => toast.classList.remove('show'), 6000);
    }}

    function downloadCurrentImage() {{
        const url = galleryImages[currentIndex];
        const filename = galleryMeta[currentIndex].filename;

        // Depuis un correctif de sécurité largement adopté (CVE-2019-11730),
        // Firefox et Chrome traitent une page ouverte en file:// (double-clic
        // direct sur index.html, sans serveur web) comme ayant une origine
        // "opaque" : fetch(), XMLHttpRequest ET la lecture d'un <canvas>
        // ayant chargé l'image sont bloqués de façon identique dans les deux
        // navigateurs pour accéder à un fichier voisin - aucune de ces trois
        // voies ne permet de contourner ça en JavaScript. On le détecte donc
        // en amont plutôt que d'échouer silencieusement après coup.
        if (window.location.protocol === 'file:') {{
            window.open(url, '_blank');
            showToast({download_toast_js});
            return;
        }}

        // L'attribut HTML "download" natif est également peu fiable une
        // fois servi via HTTP(S) selon les navigateurs (priorité donnée à
        // l'en-tête Content-Disposition, etc.) : on convertit donc en blob
        // avant de déclencher le téléchargement, ce qui contourne cette
        // variabilité (voir CHANGELOG.md).
        fetch(url)
            .then(response => {{
                if (!response.ok) throw new Error('fetch a echoue');
                return response.blob();
            }})
            .then(blob => triggerBlobDownload(blob, filename))
            .catch(() => {{
                // Repli improbable si fetch() échoue malgré tout en HTTP(S) :
                // l'image est déjà chargée à l'écran (<img>), on la redessine
                // sur un canevas caché pour en extraire un blob, sans
                // nouvelle requête réseau.
                try {{
                    const img = document.getElementById('lightbox-img');
                    const canvas = document.createElement('canvas');
                    canvas.width = img.naturalWidth;
                    canvas.height = img.naturalHeight;
                    canvas.getContext('2d').drawImage(img, 0, 0);
                    canvas.toBlob(blob => {{
                        if (blob) triggerBlobDownload(blob, filename);
                        else window.open(url, '_blank');
                    }}, 'image/jpeg', 0.92);
                }} catch (e) {{
                    // Dernier repli : au moins ouvrir l'image.
                    window.open(url, '_blank');
                }}
            }});
    }}

    function updateLightbox() {{
        const url = galleryImages[currentIndex];
        const meta = galleryMeta[currentIndex];

        currentZoom = 100;
        baseWidth = 0;
        baseHeight = 0;

        const img = document.getElementById('lightbox-img');
        img.style.width = '';
        img.style.height = '';
        img.src = url;

        document.getElementById('lightbox-filename').textContent = meta.filename;
        document.getElementById('lightbox-counter').textContent =
            (currentIndex + 1) + ' / ' + galleryImages.length;

        const dl = document.getElementById('lightbox-download');
        dl.href = url;
        dl.download = meta.filename;

        document.getElementById('info-filename').textContent = meta.filename;
        document.getElementById('info-resolution').textContent = meta.resolution;
        document.getElementById('info-size').textContent = meta.size;
        document.getElementById('info-date').textContent = meta.date;

        document.getElementById('lightbox-zoom-level').textContent = '100 %';
        document.getElementById('lightbox').classList.remove('zoomed');
    }}

    // Mesure la taille "ajustée à l'écran" (100 %) une fois l'image
    // effectivement chargée, pour zoomer en dimensions réelles
    // (largeur/hauteur) plutôt qu'un simple transform: scale() -
    // nécessaire pour que le débordement au-delà de 100 % soit réellement
    // défilable : transform ne change que le rendu visuel, jamais la
    // taille de mise en page prise en compte par overflow (voir
    // CHANGELOG.md).
    document.getElementById('lightbox-img').addEventListener('load', function() {{
        this.style.width = '';
        this.style.height = '';
        baseWidth = this.clientWidth;
        baseHeight = this.clientHeight;
        applyZoom();
    }});

    function applyZoom() {{
        const img = document.getElementById('lightbox-img');
        if (currentZoom === 100 || !baseWidth) {{
            img.style.width = '';
            img.style.height = '';
            img.style.maxWidth = '';
            img.style.maxHeight = '';
            panX = 0;
            panY = 0;
        }} else {{
            // max-width/max-height (CSS, pour l'ajustement à 100%) plafonnent
            // sinon silencieusement la taille réellement rendue, quelle que
            // soit la largeur/hauteur fixée ci-dessous - rien ne dépasserait
            // alors vraiment, et il n'y aurait rien à déplacer.
            img.style.maxWidth = 'none';
            img.style.maxHeight = 'none';
            img.style.width = Math.round(baseWidth * currentZoom / 100) + 'px';
            img.style.height = Math.round(baseHeight * currentZoom / 100) + 'px';
            clampPan();
        }}
        applyPan();
        img.classList.toggle('zoomed', currentZoom > 100);
    }}

    // Borne le déplacement pour que l'image zoomée ne puisse jamais sortir
    // complètement de la fenêtre (dans chaque dimension où elle dépasse
    // effectivement le cadre - sinon, aucun déplacement autorisé sur cette
    // dimension, l'image y tenant déjà entièrement).
    function clampPan() {{
        const img = document.getElementById('lightbox-img');
        const lightbox = document.getElementById('lightbox');
        const maxPanX = Math.max(0, (img.offsetWidth - lightbox.clientWidth) / 2);
        const maxPanY = Math.max(0, (img.offsetHeight - lightbox.clientHeight) / 2);
        panX = Math.max(-maxPanX, Math.min(maxPanX, panX));
        panY = Math.max(-maxPanY, Math.min(maxPanY, panY));
    }}

    function applyPan() {{
        const img = document.getElementById('lightbox-img');
        img.style.transform = (panX !== 0 || panY !== 0) ? `translate(${{panX}}px, ${{panY}}px)` : '';
    }}

    function setZoom(value) {{
        currentZoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, value));
        applyZoom();
        document.getElementById('lightbox-zoom-level').textContent = currentZoom + ' %';
    }}

    function zoomIn() {{ setZoom(currentZoom + ZOOM_STEP); }}
    function zoomOut() {{ setZoom(currentZoom - ZOOM_STEP); }}
    function zoomReset() {{ setZoom(100); }}

    // Glisser-déposer pour déplacer l'image zoomée (souris, tactile et
    // stylet unifiés via les Pointer Events). N'agit que si zoomée
    // au-delà de 100% - sinon l'image tient déjà entièrement, rien à
    // déplacer.
    (function() {{
        const img = document.getElementById('lightbox-img');

        img.addEventListener('pointerdown', function(e) {{
            if (currentZoom <= 100) return;
            isDragging = true;
            dragStartX = e.clientX;
            dragStartY = e.clientY;
            panStartX = panX;
            panStartY = panY;
            img.setPointerCapture(e.pointerId);
            img.classList.add('dragging');
            e.preventDefault();
        }});

        img.addEventListener('pointermove', function(e) {{
            if (!isDragging) return;
            panX = panStartX + (e.clientX - dragStartX);
            panY = panStartY + (e.clientY - dragStartY);
            clampPan();
            applyPan();
        }});

        function stopDragging() {{
            isDragging = false;
            img.classList.remove('dragging');
        }}
        img.addEventListener('pointerup', stopDragging);
        img.addEventListener('pointercancel', stopDragging);
    }})();

    function toggleInfo() {{
        document.getElementById('lightbox-info').classList.toggle('open');
    }}

    function toggleFullscreen() {{
        if (!document.fullscreenElement) {{
            document.documentElement.requestFullscreen().catch(() => {{}});
        }} else {{
            document.exitFullscreen();
        }}
    }}

    function goToPage() {{
        const input = document.getElementById('goto-page-input');
        let n = parseInt(input.value, 10);
        if (isNaN(n)) return;
        n = Math.max(1, Math.min(totalPages, n));
        window.location.href = pageUrl(n);
    }}

    document.addEventListener('keydown', function(e) {{
        if (!document.getElementById('lightbox').classList.contains('open')) return;
        if (document.activeElement && document.activeElement.id === 'goto-page-input') {{
            if (e.key === 'Enter') goToPage();
            return;
        }}
        if (e.key === 'Escape') closeLightbox();
        else if (e.key === 'ArrowLeft') showDelta(-1);
        else if (e.key === 'ArrowRight') showDelta(1);
        else if (e.key === 'i' || e.key === 'I') toggleInfo();
        else if (e.key === 'f' || e.key === 'F') toggleFullscreen();
        else if (e.key === '+' || e.key === '=') zoomIn();
        else if (e.key === '-' || e.key === '_') zoomOut();
        else if (e.key === '0') zoomReset();
    }});

    // Molette de la souris, uniquement au-dessus de la visionneuse (jamais
    // sur la page/le navigateur en arrière-plan, grâce à preventDefault) :
    // - Ctrl/Alt/Cmd + molette : zoome, comme le geste natif du navigateur
    //   mais limité à la seule photo affichée (empêche aussi le zoom natif
    //   de la page de se déclencher en plus).
    // - Molette seule : passe à la photo suivante/précédente - sauf si
    //   déjà zoomée au-delà de 100 %, où la molette déplace directement
    //   l'image agrandie (panX/panY, voir applyPan) plutôt que de changer
    //   de photo.
    document.getElementById('lightbox').addEventListener('wheel', function(e) {{
        const now = Date.now();
        if (e.ctrlKey || e.metaKey || e.altKey) {{
            e.preventDefault();
            if (now - lastWheelAction < WHEEL_THROTTLE_MS) return;
            lastWheelAction = now;
            if (e.deltaY < 0) zoomIn(); else zoomOut();
            return;
        }}
        if (currentZoom > 100) {{
            e.preventDefault();
            panX -= e.deltaX;
            panY -= e.deltaY;
            clampPan();
            applyPan();
            return;
        }}
        e.preventDefault();
        if (now - lastWheelAction < WHEEL_THROTTLE_MS) return;
        lastWheelAction = now;
        if (e.deltaY > 0) showDelta(1); else showDelta(-1);
    }}, {{ passive: false }});

    // Arrivée en provenance de la page précédente/suivante (voir
    // showDelta ci-dessus) : rouvre directement la visionneuse à la
    // bonne photo plutôt que sur la grille, pour un enchaînement fluide
    // entre deux pages. Nettoie l'URL ensuite pour qu'un rafraîchissement
    // manuel n'ouvre pas la visionneuse de façon inattendue.
    (function() {{
        const params = new URLSearchParams(window.location.search);
        if (!params.has('open')) return;
        const raw = params.get('open');
        const index = raw === 'last' ? galleryImages.length - 1 : parseInt(raw, 10);
        if (!isNaN(index) && index >= 0 && index < galleryImages.length) {{
            openLightbox({{ preventDefault() {{}} }}, index);
            // Bouclage sur l'ensemble de la galerie (dernière photo ->
            // première page, ou l'inverse) : prévenir l'utilisateur, sans
            // quoi le changement de page pourrait sembler inattendu.
            const wrap = params.get('wrap');
            if (wrap === 'fwd') showToast({wrap_forward_js});
            else if (wrap === 'back') showToast({wrap_backward_js});
        }}
        history.replaceState(null, '', window.location.pathname);
    }})();
</script>
</body>
</html>"""
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
