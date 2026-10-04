from PIL import Image, ImageDraw, ImageOps
from pathlib import Path

from .utils import apply_watermark, get_font, get_exif_metadata
from .presentation import (
    compute_page_layout, compute_effective_per_page, resolve_theme, layout_caption_lines,
    canvas_size_px, pt_to_px, CAPTION_LINE_SPACING_PX,
)
from .i18n import _

#: Nombre maximal de lignes de légende que la mise en page ajoute d'elle-même
#: quand le texte, une fois passé à la ligne dans la largeur d'une vignette,
#: dépasse captions.lines (voir ContactSheetGenerator._plan_page()). Borne
#: de sécurité contre une boucle de réajustement sans fin sur des vignettes
#: extrêmement étroites : au-delà, _draw_caption() borne de toute façon le
#: texte à la hauteur réservée, jamais de débordement dans la photo suivante.
MAX_AUTO_CAPTION_LINES = 10


def _fit_text_to_width(draw, text, font, max_width):
    """Tronque `text` avec une ellipsis ("…") si sa largeur rendue dépasse
    `max_width`, sinon le renvoie inchangé. Dernier filet de sécurité de
    ContactSheetGenerator._draw_caption() : les légendes sont normalement
    déjà passées à la ligne dans la largeur disponible
    (presentation.captions.layout_caption_lines()), de sorte que cette
    troncature ne s'applique plus qu'à un MOT isolé plus large que la
    cellule (ex : nom de fichier interminable sur une vignette minuscule) -
    jamais à une légende ordinaire composée de plusieurs champs. Voir
    CHANGELOG.md.

    Recherche linéaire (retranche un caractère à la fois) : suffisant ici,
    une légende ne dépassant jamais quelques dizaines de caractères et
    cette fonction n'étant appelée qu'une fois par ligne/par photo."""
    if max_width <= 0:
        return ""
    bbox = draw.textbbox((0, 0), text, font=font)
    if bbox[2] - bbox[0] <= max_width:
        return text

    ellipsis = "…"
    bbox = draw.textbbox((0, 0), ellipsis, font=font)
    if bbox[2] - bbox[0] > max_width:
        # Même l'ellipsis seule ne tient pas (cellule extrêmement
        # étroite) : rien d'affichable ne rentre, mieux vaut ne rien
        # dessiner qu'un fragment trompeur.
        return ""

    truncated = text
    while truncated:
        truncated = truncated[:-1]
        candidate = truncated.rstrip() + ellipsis
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return candidate
    return ellipsis


def _thumb_offset(caption_position, alignment, thumb_wh, cell_size):
    """Décalage (dx, dy), en pixels, de la vignette À L'INTÉRIEUR de sa
    cellule carrée `cell_size x cell_size`, pour que la photo soit collée
    à sa légende au lieu de rester en haut à gauche de la cellule.

    Une vignette garde ses proportions (`Image.thumbnail`) : une photo en
    paysage 4:3 n'occupe que les trois quarts de la hauteur de la cellule,
    et la légende, placée sous la cellule (voir
    layout_engine.compute_page_layout()), était donc séparée de sa photo
    par un vide - d'autant plus visible que la légende fait plusieurs
    lignes. Le vide se retrouve maintenant du côté opposé à la légende,
    ce qui regroupe visuellement chaque photo avec sa légende ET garde les
    légendes alignées d'une photo à l'autre (la zone de légende, elle,
    n'a pas bougé) :

    - "below" : photo posée sur sa légende (alignée en bas) ;
    - "above" : photo collée sous sa légende (alignée en haut) ;
    - "right" : photo collée contre sa légende (alignée à droite) ;
    - horizontalement, pour "below"/"above", la photo suit l'alignement du
      texte (gauche/centre/droite) - auparavant toujours à gauche, alors
      que la légende était centrée sous la cellule.

    Sans légende (`caption_position` autre que ces trois valeurs, y compris
    "none" - la valeur à passer quand aucun champ n'est configuré) :
    (0, 0), strictement le comportement d'origine."""
    width, height = thumb_wh
    free_w = max(0, cell_size - width)
    free_h = max(0, cell_size - height)

    if caption_position == "right":
        return free_w, 0
    if caption_position not in ("below", "above"):
        return 0, 0

    dy = free_h if caption_position == "below" else 0
    if alignment == "left":
        dx = 0
    elif alignment == "right":
        dx = free_w
    else:
        dx = free_w // 2
    return dx, dy


def _fit_header_text(draw, text, size, bold, max_width, min_size):
    """Police et texte de l'en-tête (titre/auteur) tenant dans `max_width` :
    la plus grande taille <= `size` (par pas de 2 px, jamais sous
    `min_size`) pour laquelle `text` tient ; si même `min_size` ne suffit
    pas, le texte est tronqué avec "…" (_fit_text_to_width) en dernier
    recours. Un texte qui tient déjà garde exactement sa police d'origine.

    Sans cette garde, un titre long débordait de la page - sans conséquence
    visible tant qu'il était centré (rogné symétriquement), mais un titre
    aligné à droite aurait commencé HORS de la page."""
    font = get_font(size, bold=bold)
    for candidate in range(size, min_size - 1, -2):
        font = get_font(candidate, bold=bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font, text
    return font, _fit_text_to_width(draw, text, font, max_width)


def _header_x(position, canvas_w, margin_px, text_w):
    """Abscisse du texte d'en-tête selon HEADER_POSITIONS : aligné sur la
    marge de page à gauche/à droite, centré sinon (formule d'origine,
    inchangée : le centrage n'a jamais tenu compte des marges)."""
    if position == "top_left":
        return margin_px
    if position == "top_right":
        return canvas_w - margin_px - text_w
    return (canvas_w - text_w) / 2


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
        palette = resolve_theme(profile.theme)
        # La géométrie dépend du TEXTE des légendes (leur nombre de lignes
        # une fois passées à la ligne dans la largeur d'une vignette
        # détermine la hauteur à réserver, donc la taille des vignettes) :
        # voir _plan_page().
        page, caption_lines_by_idx = self._plan_page(images)

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

        # Mode d'ajustement (Profil, "Remplir" dans l'interface) : "cover"
        # recadre chaque photo en carré pour remplir toute sa cellule.
        thumbnails = self.thumb_gen.generate_parallel(
            images, thumb_size, fit_mode=profile.layout.fit_mode,
        )

        sheet = Image.new("RGB", (canvas_w, canvas_h), palette.background)
        draw = ImageDraw.Draw(sheet)

        header_bottom_y = self._draw_header(draw, canvas_w, margin, palette)
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

        # Position de légende réellement DESSINÉE : sans aucun champ
        # configuré, la zone est réservée mais reste vide - on garde alors
        # les vignettes exactement où elles étaient (voir _thumb_offset()).
        drawn_caption_position = (
            profile.layout.caption_position if profile.captions.effective_fields() else "none"
        )

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
            dx, dy = _thumb_offset(
                drawn_caption_position, profile.captions.alignment, thumb.size, thumb_size,
            )
            sheet.paste(thumb, (x + dx, y + dy))

            lines = caption_lines_by_idx.get(idx)
            if lines and cell.caption_x is not None:
                self._draw_caption(
                    draw, lines, cell.caption_x, cell.caption_y + y_shift,
                    cell.caption_w, cell.caption_h, profile.captions, palette,
                )

        self._draw_page_number(
            draw, canvas_w, canvas_h, page_num, total_pages, palette,
            show_page_number=profile.layout.page_numbering,
        )
        return sheet

    def _plan_page(self, images):
        """Calcule la géométrie de la page ET le texte (déjà passé à la
        ligne) des légendes de chaque photo - renvoie
        `(PageLayout, {index_photo: [lignes]})`.

        Sans légende sous/sur la photo (cas par défaut), strictement
        équivalent à un simple `compute_page_layout()` : aucune métadonnée
        EXIF n'est lue (coûteux, un ou plusieurs accès fichier par photo -
        voir utils.get_exif_metadata()), aucun coût supplémentaire.

        Avec une légende, les lignes à réserver dépendent du texte réel,
        lui-même dépendant de la largeur de la vignette, qui dépend à son
        tour de la hauteur réservée (plus de lignes -> vignettes plus
        petites -> légendes plus étroites -> parfois encore plus de
        lignes) : on part de captions.lines, on mesure le texte réel
        passé à la ligne dans la largeur d'une vignette
        (presentation.captions.layout_caption_lines()), et si une photo
        demande plus de lignes que celles réservées, on recalcule la
        géométrie avec ce nombre-là jusqu'à stabilité - au plus
        MAX_AUTO_CAPTION_LINES lignes, le nombre de lignes ne faisant que
        croître d'une itération à l'autre. Les légendes "à droite" n'ont
        pas besoin de cette boucle : leur largeur est fixe
        (caption_area_mm) et leur hauteur suit déjà celle de la vignette.

        Conséquence assumée : chaque PAGE ajuste la hauteur de légende à
        SES propres photos (une page dont une photo a un nom d'objectif
        très long peut avoir des vignettes légèrement plus petites que la
        précédente)."""
        profile = self.profile
        caption_fields = profile.captions.effective_fields()
        position = profile.layout.caption_position
        if not caption_fields or position not in ("below", "above", "right"):
            return compute_page_layout(profile, photo_count=len(images)), {}

        per_page = compute_effective_per_page(profile)
        metadata = [get_exif_metadata(img["path"]) for img in images[:per_page]]

        font = get_font(max(6, pt_to_px(profile.captions.font_size)))
        scratch = ImageDraw.Draw(Image.new("RGB", (1, 1)))

        def measure(text):
            bbox = scratch.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0]

        n_lines = max(1, profile.captions.lines)
        max_lines = max(n_lines, MAX_AUTO_CAPTION_LINES)
        while True:
            page = compute_page_layout(profile, photo_count=len(images), caption_lines=n_lines)
            texts = {}
            needed = 1
            for idx, cell in enumerate(page.cells):
                if idx >= len(metadata) or cell.caption_w is None:
                    continue
                lines = layout_caption_lines(profile, metadata[idx], cell.caption_w, measure)
                if lines:
                    texts[idx] = lines
                    needed = max(needed, len(lines))
            if position == "right" or needed <= n_lines or n_lines >= max_lines:
                return page, texts
            n_lines = min(needed, max_lines)

    def _draw_header(self, draw, canvas_w, margin_px, palette):
        """Titre puis auteur, l'un SOUS l'autre, chacun aligné selon
        LayoutSettings.title_position/author_position (gauche/centre/droite
        sur les marges de page, ou "none" pour le masquer). Renvoie
        l'ordonnée du bas de l'en-tête (la grille de vignettes démarre
        dessous). Positions par défaut (centrées) : rendu strictement
        identique à avant l'introduction de ces réglages."""
        layout = self.profile.layout
        max_width = canvas_w - 2 * margin_px

        # Marge haute réduite avant l'en-tête (6 mm, contre ~9,5 mm
        # auparavant) : le titre démarre nettement plus près du haut de la
        # planche/page.
        y = int(6 * 300 / 25.4)

        # Si aucun champ (titre, auteur, filigrane) n'a été renseigné, la
        # planche serait totalement anonyme : on affiche alors par défaut
        # le nom du dossier source (sans son chemin complet) en guise de
        # titre. Jamais quand l'utilisateur a explicitement masqué le titre
        # (title_position == "none").
        watermark_text = getattr(self.config, 'watermark_text', None)
        display_title = self.project_title
        if not display_title and not self.author and not watermark_text and self.input_dir:
            display_title = Path(self.input_dir).name

        if display_title and layout.title_position != "none":
            font_title, text = _fit_header_text(draw, display_title, 54, True, max_width, 28)
            bbox = draw.textbbox((0, 0), text, font=font_title)
            text_w = bbox[2] - bbox[0]
            x = _header_x(layout.title_position, canvas_w, margin_px, text_w)
            draw.text((x, y), text, fill=palette.text, font=font_title)
            y += 58

        if self.author and layout.author_position != "none":
            font_author, text = _fit_header_text(draw, self.author, 36, True, max_width, 20)
            bbox = draw.textbbox((0, 0), text, font=font_author)
            text_w = bbox[2] - bbox[0]
            x = _header_x(layout.author_position, canvas_w, margin_px, text_w)
            draw.text((x, y), text, fill=palette.text, font=font_author)
            y += 42

        return y

    def _draw_caption(self, draw, lines, x, y, width, height, caption_settings, palette):
        """Dessine les lignes de légende d'UNE photo (cahier des charges
        §1), déjà résolues ET passées à la ligne par _plan_page()
        (presentation.captions.layout_caption_lines()) - cette méthode ne
        fait QUE les positionner/dessiner, aucune règle de formatage ni de
        retour à la ligne n'est dupliquée ici. `x`/`y` : coin haut-gauche
        de la zone de légende réservée pour cette photo ; `width`/`height` :
        dimensions utiles de cette zone, pour le centrage/alignement
        horizontal et pour borner le nombre de lignes dessinées.

        Deux filets de sécurité, jamais un débordement dans les cellules
        voisines (bug signalé : légendes qui se chevauchaient, illisibles) :
        - une ligne plus large que `width` (un MOT isolé trop long) est
          tronquée avec "…" ;
        - s'il y a plus de lignes que `height` n'en peut contenir (légende
          "à droite" sur une petite vignette, ou plafond
          MAX_AUTO_CAPTION_LINES atteint), les lignes en trop sont
          supprimées et la dernière se termine par "…".
        Dans le cas ordinaire (plusieurs champs sur une vignette de taille
        normale), aucun des deux ne s'applique : tout le texte est visible.
        Voir CHANGELOG.md."""
        font_px = max(6, pt_to_px(caption_settings.font_size))
        font = get_font(font_px)
        # CAPTION_LINE_SPACING_PX : même constante que
        # layout_engine._reserve_caption_px(), qui calcule la hauteur à
        # réserver à partir de cette formule - jamais une valeur dupliquée
        # en dur ici, pour qu'une ligne dessinée ne puisse pas un jour
        # redevenir plus haute que l'espace réellement réservé.
        line_height = font_px + CAPTION_LINE_SPACING_PX

        max_lines = max(1, height // line_height)
        if len(lines) > max_lines:
            lines = list(lines[:max_lines])
            lines[-1] = lines[-1] + "…"

        for i, line in enumerate(lines):
            line = _fit_text_to_width(draw, line, font, width)
            bbox = draw.textbbox((0, 0), line, font=font)
            text_w = bbox[2] - bbox[0]
            if caption_settings.alignment == "left":
                text_x = x
            elif caption_settings.alignment == "right":
                text_x = x + width - text_w
            else:
                text_x = x + (width - text_w) / 2
            draw.text((text_x, y + i * line_height), line, fill=palette.text, font=font)

    def _draw_page_number(self, draw, canvas_w, canvas_h, page_num, total_pages, palette,
                          show_page_number=True):
        """Numéro de planche ("Planche 1/3") puis mention de crédit. Le
        numéro seul est optionnel (LayoutSettings.page_numbering) ; la
        mention de crédit en bas de page reste toujours affichée."""
        font = get_font(26)
        font_small = get_font(20)

        if show_page_number:
            page_text = _("sheet.page_label", page=page_num, total=total_pages)
            bbox = draw.textbbox((0, 0), page_text, font=font)
            page_w = bbox[2] - bbox[0]
            draw.text(((canvas_w - page_w) / 2, canvas_h - 90), page_text, fill=palette.text, font=font)

        credit = _("sheet.footer")
        bbox = draw.textbbox((0, 0), credit, font=font_small)
        credit_w = bbox[2] - bbox[0]
        draw.text(((canvas_w - credit_w) / 2, canvas_h - 50), credit, fill=palette.text_secondary, font=font_small)
