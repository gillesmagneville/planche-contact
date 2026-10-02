from PIL import Image, ImageDraw, ImageOps
from pathlib import Path

from .utils import apply_watermark, get_font, get_exif_metadata
from .presentation import (
    compute_page_layout, resolve_theme, resolve_caption_lines, canvas_size_px, pt_to_px,
)


class ContactSheetGenerator:
    def __init__(self, config, thumbnail_generator):
        self.config = config
        self.thumb_gen = thumbnail_generator
        # Le Profil (portfolio/presentation/profile.py) est désormais la
        # source unique de vérité pour la mise en page, les légendes et le
        # thème - voir Config.__post_init__() pour la synchronisation
        # rétrocompatible avec page_format/num_per_sheet quand aucun
        # Profil explicite n'a été fourni.
        self.profile = config.profile
        self.page_format = self.profile.layout.page_format
        self.project_title = getattr(config, 'title', None)
        self.author = getattr(config, 'author', None)
        self.input_dir = getattr(config, 'input_dir', None)
        self.num_per_sheet = self.profile.layout.per_page

    def _get_canvas_size(self):
        return canvas_size_px(self.profile.layout.page_format, self.profile.layout.orientation)

    def create_contact_sheet(self, images, page_num, total_pages):
        if not images:
            return None

        profile = self.profile
        page = compute_page_layout(profile, photo_count=len(images))
        palette = resolve_theme(profile.theme)

        canvas_w, canvas_h = page.canvas_w, page.canvas_h
        margin = page.margin_px
        thumb_size = page.thumb_size
        # "large_thumbs" peut avoir réduit lui-même le nombre de photos
        # tenant sur UNE page (voir layout_engine.compute_effective_per_page) :
        # la répartition réelle des photos EXCÉDENTAIRES sur des pages
        # supplémentaires reste à câbler en amont, dans la boucle de
        # pagination de portfolio.py (qui ignore encore cette réduction et
        # continue de répartir par lots de config.num_per_sheet) - une
        # étape ultérieure séparée. En attendant, on ne dessine ici jamais
        # plus de cellules que ce que la géométrie calculée prévoit
        # réellement (page.cells en contient au plus autant), pour ne
        # jamais déborder de la grille.
        effective_per_page = page.effective_per_page

        thumbnails = self.thumb_gen.generate_parallel(images, thumb_size)

        sheet = Image.new("RGB", (canvas_w, canvas_h), palette.background)
        draw = ImageDraw.Draw(sheet)

        header_bottom_y = self._draw_header(draw, canvas_w, palette)
        # Espace entre le bas de l'en-tête et la grille de vignettes : plus
        # généreux que la version précédente, aligné sur la même valeur que
        # les marges latérales/basse pour une composition équilibrée.
        content_gap = margin
        y_start = header_bottom_y + content_gap

        # Décalage vertical RIGIDE appliqué à TOUTES les cellules calculées
        # par le moteur de mise en page (photos ET légendes) : le moteur
        # suppose un début de grille à une hauteur d'en-tête FIXE
        # (page.content_top_px), alors que contactsheet.py calcule la
        # sienne dynamiquement selon le texte réellement affiché (titre/
        # auteur) - voir _draw_header() ci-dessus - pour un rendu du
        # modèle "grid" strictement identique à avant l'introduction de ce
        # moteur (cahier des charges : aucune régression du comportement
        # existant). Un décalage CONSTANT préserve exactement l'espacement
        # RELATIF calculé par le moteur entre toutes les cellules d'une
        # même page (y compris l'espace réservé aux légendes, qui s'ajoute
        # à la hauteur de chaque ligne - voir compute_page_layout()) :
        # reconstruire ce calcul à la main ici dupliquerait une règle déjà
        # centralisée, avec le risque réel de la refaire INCORRECTEMENT
        # (un premier essai de ce correctif l'a d'ailleurs fait : les
        # légendes empiétaient sur la ligne de vignettes suivante, faute
        # de retrancher l'espace de légende de l'écart entre lignes).
        y_shift = y_start - page.content_top_px

        # Légendes personnalisables (cahier des charges §1) : on ne lit les
        # métadonnées EXIF (coûteux, un ou plusieurs accès fichier par
        # photo - voir utils.get_exif_metadata()) QUE si au moins un champ
        # de légende est effectivement configuré - comportement par défaut
        # (aucune légende) sans le moindre coût supplémentaire.
        caption_fields = profile.captions.effective_fields()

        for idx, thumb in enumerate(thumbnails):
            if idx >= effective_per_page or idx >= len(page.cells):
                break
            if thumb is None:
                continue

            if self.config.watermark_text:
                thumb = apply_watermark(
                    thumb,
                    self.config.watermark_text,
                    getattr(self.config, 'watermark_opacity', 40),
                    getattr(self.config, 'watermark_orientation', 'Horizontal')
                )

            cell = page.cells[idx]
            x, y = cell.photo_x, cell.photo_y + y_shift
            sheet.paste(thumb, (x, y))

            if caption_fields and cell.caption_x is not None:
                metadata = get_exif_metadata(images[idx]["path"])
                lines = resolve_caption_lines(profile, metadata)
                if lines:
                    self._draw_caption(
                        draw, lines, cell.caption_x, cell.caption_y + y_shift, cell.caption_w,
                        profile.captions, palette,
                    )

        self._draw_page_number(draw, canvas_w, canvas_h, page_num, total_pages, palette)
        return sheet

    def _draw_header(self, draw, canvas_w, palette):
        font_title = get_font(54, bold=True)
        font_author = get_font(36, bold=True)

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
            draw.text(((canvas_w - text_w) / 2, y), display_title, fill=palette.text, font=font_title)
            y += 58

        if self.author:
            bbox = draw.textbbox((0, 0), self.author, font=font_author)
            text_w = bbox[2] - bbox[0]
            draw.text(((canvas_w - text_w) / 2, y), self.author, fill=palette.text, font=font_author)
            y += 42

        return y

    def _draw_caption(self, draw, lines, x, y, width, caption_settings, palette):
        """Dessine les lignes de légende d'UNE photo (cahier des charges
        §1), déjà résolues par
        portfolio.presentation.captions.resolve_caption_lines() - cette
        méthode ne fait QUE les positionner/dessiner, aucune règle de
        formatage n'est dupliquée ici. `x`/`y` : coin haut-gauche de la
        zone de légende réservée pour cette photo ; `width` : largeur
        utile de cette zone, pour le centrage/alignement horizontal."""
        font_px = max(6, pt_to_px(caption_settings.font_size))
        font = get_font(font_px)
        line_height = font_px + 4

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            text_w = bbox[2] - bbox[0]
            if caption_settings.alignment == "left":
                text_x = x
            elif caption_settings.alignment == "right":
                text_x = x + width - text_w
            else:
                text_x = x + (width - text_w) / 2
            draw.text((text_x, y + i * line_height), line, fill=palette.text, font=font)

    def _draw_page_number(self, draw, canvas_w, canvas_h, page_num, total_pages, palette):
        font = get_font(26)
        font_small = get_font(20)

        page_text = f"Planche {page_num}/{total_pages}"
        bbox = draw.textbbox((0, 0), page_text, font=font)
        page_w = bbox[2] - bbox[0]
        draw.text(((canvas_w - page_w) / 2, canvas_h - 90), page_text, fill=palette.text, font=font)

        credit = "Planche générée par Planche-Contact"
        bbox = draw.textbbox((0, 0), credit, font=font_small)
        credit_w = bbox[2] - bbox[0]
        draw.text(((canvas_w - credit_w) / 2, canvas_h - 50), credit, fill=palette.text_secondary, font=font_small)
