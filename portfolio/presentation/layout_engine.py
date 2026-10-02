# -*- coding: utf-8 -*-
"""
portfolio/presentation/layout_engine.py - Calcul de géométrie des planches
contact, INDÉPENDANT du rendu final (aucune dépendance à PIL/Pillow ni au
HTML : uniquement des nombres). Utilisé par contactsheet.py pour le rendu
JPEG/PDF, et par la future prévisualisation GTK - les deux obtiennent ainsi
TOUJOURS la même géométrie, par construction (cahier des charges §5 :
"Le moteur de mise en page doit être conçu [...] comme un composant commun
[...] pour éviter qu'une même règle de mise en page soit implémentée
différemment dans plusieurs parties du programme").

Le modèle "grid" reproduit EXACTEMENT l'algorithme actuellement codé en dur
dans ContactSheetGenerator.create_contact_sheet() (recherche du nombre de
colonnes maximisant la taille des vignettes, réservation fixe de 180 px
pour l'en-tête, clampage de la largeur de vignette après coup pour tenir
compte de l'espacement) - y compris ses petites imperfections déjà
présentes (ex : l'espacement vertical n'est pas clampé symétriquement à
l'espacement horizontal). Ce portage est DÉLIBÉRÉMENT fidèle au pixel près :
l'objectif de cette étape est de centraliser le calcul, pas de corriger un
comportement existant - toute amélioration de l'algorithme "grid" lui-même
se fera dans une étape ultérieure séparée, explicitement validée comme
telle (voir CHANGELOG.md), jamais mélangée à ce portage.

La galerie HTML (htmlgallery.py) n'utilise PAS directement les coordonnées
en pixels de ce module (une grille CSS responsive n'a pas de sens en
pixels fixes) : elle consomme le même Profil, via themes.py/captions.py,
pour que les RÉGLAGES restent une source unique de vérité, même si la
traduction finale en CSS est spécifique au HTML (voir PROJECT_CONTEXT.md
une fois ce module intégré).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .profile import Profile

#: Résolution de référence pour toutes les planches contact/PDF - reprise
#: telle quelle de contactsheet.py.
DPI = 300

#: Tailles de page en millimètres (largeur, hauteur), orientation portrait -
#: reprises telles quelles de contactsheet.py._get_canvas_size().
PAPER_SIZES_MM = {
    "A5": (148, 210),
    "A4": (210, 297),
    "A3": (297, 420),
    "A2": (420, 594),
    "Letter": (216, 279),
}

#: Réservation verticale fixe pour l'en-tête (titre/auteur) dans la
#: recherche de grille du modèle "grid", en pixels à 300 ppp - valeur
#: historique de contactsheet.py (~15,2 mm), indépendante du contenu réel
#: de l'en-tête (qui peut être plus court, ex : pas d'auteur). Conservée
#: ici pour une fidélité pixel près au comportement actuel ; voir le
#: docstring du module.
HEADER_RESERVED_PX_GRID = 180

#: Nombre de colonnes maximal testé par la recherche "grid" - valeur
#: historique de contactsheet.py (range(1, min(num_per_sheet + 1, 9))).
GRID_MAX_COLUMNS_TESTED = 8

#: Nombre de colonnes maximal testé par le modèle "grandes vignettes" :
#: volontairement bas, pour privilégier de grandes vignettes plutôt que
#: d'en caser le plus possible par page.
LARGE_THUMBS_MAX_COLUMNS_TESTED = 4

#: Taille de vignette minimale absolue (px), quel que soit le modèle -
#: reprise de contactsheet.py (max(best_thumb_size, 70)).
MIN_THUMB_SIZE_PX = 70


def mm_to_px(mm: float, dpi: int = DPI) -> int:
    return int(mm * dpi / 25.4)


def canvas_size_px(page_format: str, orientation: str = "portrait", dpi: int = DPI) -> tuple[int, int]:
    """Taille de la page en pixels. Reprend exactement
    contactsheet.py._get_canvas_size() quand orientation="portrait" (son
    seul cas d'usage actuel) ; "landscape" échange largeur/hauteur - cas
    nouveau, introduit avec le profil de mise en page."""
    width_mm, height_mm = PAPER_SIZES_MM.get(page_format, PAPER_SIZES_MM["A4"])
    if orientation == "landscape":
        width_mm, height_mm = height_mm, width_mm
    return mm_to_px(width_mm, dpi), mm_to_px(height_mm, dpi)


@dataclass
class CellLayout:
    """Emplacement d'UNE photo (+ sa légende éventuelle) sur la page, en
    pixels. Les coordonnées (x, y) sont le coin haut-gauche de chaque zone,
    cohérent avec PIL.Image.paste()/ImageDraw."""
    index: int
    row: int
    col: int
    photo_x: int
    photo_y: int
    photo_w: int
    photo_h: int
    caption_x: Optional[int] = None
    caption_y: Optional[int] = None
    caption_w: Optional[int] = None
    caption_h: Optional[int] = None


@dataclass
class PageLayout:
    """Géométrie complète d'une page. `cells` ne contient que les
    emplacements effectivement occupés par une photo (jusqu'à
    min(photo_count, layout.per_page)), jamais de cellules vides -
    cohérent avec la boucle actuelle de create_contact_sheet()."""
    canvas_w: int
    canvas_h: int
    margin_px: int
    spacing_px: int
    content_top_px: int
    cols: int
    rows: int
    thumb_size: int
    cells: list[CellLayout] = field(default_factory=list)


def _reserve_caption_px(profile: Profile) -> tuple[int, int]:
    """Espace (largeur, hauteur) en pixels à réserver par cellule pour la
    légende, selon layout.caption_position. Une seule des deux valeurs est
    non nulle à la fois (une légende est soit sous/sur la photo, soit à
    côté - jamais les deux)."""
    layout = profile.layout
    if layout.caption_position in ("below", "above"):
        return 0, mm_to_px(layout.caption_area_mm)
    if layout.caption_position == "right":
        return mm_to_px(layout.caption_area_mm), 0
    return 0, 0


def _apply_spacing_clamp(thumb_size: int, available_w: int, available_h: int,
                          cols: int, rows: int, spacing_px: int,
                          caption_w_px: int, caption_h_px: int,
                          clamp_vertical_spacing: bool) -> int:
    """Clampage a posteriori pour tenir compte de l'espacement ENTRE
    cellules, absent du calcul initial de cell_w/cell_h (qui divise
    seulement l'espace disponible par le nombre de colonnes/lignes, sans
    retrancher l'espacement entre elles).

    `clamp_vertical_spacing=False` reproduit fidèlement
    contactsheet.py : seul l'espacement HORIZONTAL est clampé (bug
    préexistant découvert en écrivant les tests de ce module - voir
    docstring du module et PROJECT_CONTEXT.md ; conservé tel quel pour le
    modèle "grid", qui doit rester pixel-identique au comportement actuel).
    `clamp_vertical_spacing=True` corrige ce défaut pour les NOUVEAUX
    modèles (large_thumbs/landscape/portrait, et le calcul explicite de
    "free") qui n'ont aucune contrainte de rétrocompatibilité : les
    cellules ne peuvent alors jamais déborder du bas de la page."""
    max_thumb_w = (available_w - (cols - 1) * spacing_px) // cols - caption_w_px
    thumb_size = min(thumb_size, max(1, max_thumb_w))
    if clamp_vertical_spacing:
        max_thumb_h = (available_h - (rows - 1) * spacing_px) // rows - caption_h_px
        thumb_size = min(thumb_size, max(1, max_thumb_h))
    return thumb_size


def _grid_search(available_w: int, available_h: int, per_page: int,
                  spacing_px: int, max_columns_tested: int,
                  caption_w_px: int, caption_h_px: int,
                  clamp_vertical_spacing: bool = False) -> tuple[int, int]:
    """Coeur de l'algorithme "grid" (et de "large_thumbs"/"landscape"/
    "portrait", qui n'en diffèrent que par `max_columns_tested` et/ou un
    post-traitement) : cherche, parmi les nombres de colonnes testés,
    celui qui maximise la taille de vignette obtenue. Reproduit fidèlement
    l'algorithme historique de contactsheet.py quand
    clamp_vertical_spacing=False (son comportement par défaut), étendu
    pour réserver l'espace de légende par cellule (nul quand il n'y a pas
    de légende, donc strictement équivalent à l'algorithme d'origine dans
    ce cas). Renvoie (thumb_size, cols)."""
    best_cols = 1
    best_thumb_size = 0

    for cols in range(1, min(per_page + 1, max_columns_tested + 1)):
        rows = math.ceil(per_page / cols)

        cell_w = available_w // cols if cols > 1 else available_w
        cell_h = available_h // rows if rows > 1 else available_h

        # Espace de légende retranché de la cellule AVANT de calculer la
        # taille de vignette : la légende doit être connue avant la
        # génération des vignettes elles-mêmes (voir docstring du module
        # et PROJECT_CONTEXT.md, limitation n°4 de l'analyse).
        photo_cell_w = max(1, cell_w - caption_w_px)
        photo_cell_h = max(1, cell_h - caption_h_px)
        thumb_size = min(photo_cell_w, photo_cell_h)

        if thumb_size > best_thumb_size:
            best_thumb_size = thumb_size
            best_cols = cols

    thumb_size = max(best_thumb_size, MIN_THUMB_SIZE_PX)
    cols = best_cols
    rows = math.ceil(per_page / cols)

    thumb_size = _apply_spacing_clamp(
        thumb_size, available_w, available_h, cols, rows, spacing_px,
        caption_w_px, caption_h_px, clamp_vertical_spacing,
    )

    return thumb_size, cols


def _free_layout(profile: Profile, available_w: int, available_h: int,
                  spacing_px: int, caption_w_px: int, caption_h_px: int) -> tuple[int, int]:
    """Modèle "libre" : colonnes/lignes explicitement fournies par
    l'utilisateur. Si l'une des deux (ou les deux) n'est pas renseignée,
    se comporte comme "grid" pour la dimension manquante - un modèle
    "libre" sans aucun réglage doit rester utilisable, pas produire une
    page vide ou une exception."""
    layout = profile.layout
    cols = layout.columns or None
    rows = layout.rows

    if cols is None and rows is None:
        return _grid_search(available_w, available_h, layout.per_page, spacing_px,
                             GRID_MAX_COLUMNS_TESTED, caption_w_px, caption_h_px)

    if cols is None:
        cols = max(1, math.ceil(layout.per_page / rows))
    if rows is None:
        rows = max(1, math.ceil(layout.per_page / cols))

    cell_w = available_w // cols if cols > 1 else available_w
    cell_h = available_h // rows if rows > 1 else available_h
    photo_cell_w = max(1, cell_w - caption_w_px)
    photo_cell_h = max(1, cell_h - caption_h_px)
    thumb_size = max(MIN_THUMB_SIZE_PX, min(photo_cell_w, photo_cell_h))

    # Contrairement à "grid" (voir _apply_spacing_clamp), le clampage
    # vertical est ici actif : des colonnes/lignes explicites sont un
    # réglage entièrement nouveau, sans contrainte de rétrocompatibilité à
    # respecter pixel près.
    thumb_size = _apply_spacing_clamp(
        thumb_size, available_w, available_h, cols, rows, spacing_px,
        caption_w_px, caption_h_px, clamp_vertical_spacing=True,
    )

    return thumb_size, cols


def compute_page_layout(profile: Profile, photo_count: int) -> PageLayout:
    """Calcule la géométrie d'une page pour le Profil donné.

    `photo_count` est le nombre de photos RÉELLEMENT présentes sur cette
    page (peut être inférieur à profile.layout.per_page pour la dernière
    page d'une série) - la géométrie de la grille elle-même se base
    toujours sur profile.layout.per_page (comme aujourd'hui dans
    contactsheet.py), pour que toutes les pages d'une même génération
    aient des cellules de taille identique ; seul le nombre de cellules
    effectivement remplies varie.

    Ne lève jamais d'exception : un Profil par défaut produit exactement
    la géométrie actuelle de contactsheet.py.
    """
    layout = profile.layout
    canvas_w, canvas_h = canvas_size_px(layout.page_format, layout.orientation)
    margin_px = mm_to_px(layout.margin_mm)
    spacing_px = mm_to_px(layout.spacing_mm)

    available_w = canvas_w - 2 * margin_px
    available_h = canvas_h - 2 * margin_px - HEADER_RESERVED_PX_GRID

    caption_w_px, caption_h_px = _reserve_caption_px(profile)

    if layout.template == "free":
        thumb_size, cols = _free_layout(profile, available_w, available_h, spacing_px,
                                         caption_w_px, caption_h_px)
    elif layout.template == "large_thumbs":
        # NOTE DE CONCEPTION (à valider avec le mainteneur) : restreindre le
        # nombre de colonnes testées, à per_page INCHANGÉ, ne peut par
        # construction jamais produire une vignette PLUS grande que la
        # recherche non restreinte de "grid" (qui explore déjà ces mêmes
        # colonnes parmi ses candidats) - seulement une vignette plus
        # petite ou égale, si per_page force de toute façon beaucoup de
        # lignes. Ce modèle ne garantit donc aujourd'hui "de grandes
        # vignettes" que combiné à un per_page modeste choisi par
        # ailleurs (ex : interface graphique proposant un per_page par
        # défaut plus bas quand ce modèle est sélectionné) ; il ne réduit
        # pas lui-même le nombre de photos par page. Une vraie garantie de
        # grande taille quel que soit per_page impliquerait de laisser ce
        # modèle décider lui-même du nombre de photos effectivement placées
        # par page (le reste basculant sur des pages suivantes) - un
        # changement de pagination plus large, hors du périmètre de cette
        # étape (voir la présentation de l'analyse).
        thumb_size, cols = _grid_search(available_w, available_h, layout.per_page, spacing_px,
                                         LARGE_THUMBS_MAX_COLUMNS_TESTED, caption_w_px, caption_h_px,
                                         clamp_vertical_spacing=True)
    elif layout.template in ("landscape", "portrait"):
        # Recherche identique à "grid", mais la préférence entre deux
        # nombres de colonnes donnant une taille de vignette quasi
        # identique (à 5 % près) va vers plus de colonnes ("landscape" -
        # cellules plus larges que hautes, moins de lignes) ou moins de
        # colonnes ("portrait" - cellules plus hautes que larges, plus de
        # lignes). Heuristique volontairement simple à ce stade ; à
        # affiner après une première prévisualisation visuelle réelle, la
        # demande ne spécifiant pas de règle exacte au-delà du nom des
        # modèles.
        thumb_size, cols = _grid_search(available_w, available_h, layout.per_page, spacing_px,
                                         GRID_MAX_COLUMNS_TESTED, caption_w_px, caption_h_px,
                                         clamp_vertical_spacing=True)
        rows_at_cols = math.ceil(layout.per_page / cols)
        prefer_more_cols = layout.template == "landscape"
        candidates = range(1, min(layout.per_page + 1, GRID_MAX_COLUMNS_TESTED + 1))
        for alt_cols in candidates:
            if (alt_cols > cols) != prefer_more_cols:
                continue
            alt_rows = math.ceil(layout.per_page / alt_cols)
            cell_w = available_w // alt_cols if alt_cols > 1 else available_w
            cell_h = available_h // alt_rows if alt_rows > 1 else available_h
            alt_thumb = min(max(1, cell_w - caption_w_px), max(1, cell_h - caption_h_px))
            if alt_thumb >= thumb_size * 0.95 and (
                (prefer_more_cols and alt_cols > cols) or (not prefer_more_cols and alt_cols < cols)
            ):
                cols, thumb_size, rows_at_cols = alt_cols, alt_thumb, alt_rows
        thumb_size = max(MIN_THUMB_SIZE_PX, _apply_spacing_clamp(
            thumb_size, available_w, available_h, cols, rows_at_cols, spacing_px,
            caption_w_px, caption_h_px, clamp_vertical_spacing=True,
        ))
    else:  # "grid", et filet de sécurité pour une valeur inconnue
        thumb_size, cols = _grid_search(available_w, available_h, layout.per_page, spacing_px,
                                         GRID_MAX_COLUMNS_TESTED, caption_w_px, caption_h_px)

    rows = math.ceil(layout.per_page / cols)
    content_top_px = margin_px + HEADER_RESERVED_PX_GRID

    cells: list[CellLayout] = []
    n_cells = min(photo_count, layout.per_page)
    for idx in range(n_cells):
        row = idx // cols
        col = idx % cols
        cell_x = margin_px + col * (thumb_size + caption_w_px + spacing_px)
        cell_y = content_top_px + row * (thumb_size + caption_h_px + spacing_px)

        if layout.caption_position == "above":
            caption_y, photo_y = cell_y, cell_y + caption_h_px
        else:
            photo_y, caption_y = cell_y, cell_y + thumb_size

        cell = CellLayout(
            index=idx, row=row, col=col,
            photo_x=cell_x, photo_y=photo_y, photo_w=thumb_size, photo_h=thumb_size,
        )
        if layout.caption_position == "right":
            cell.caption_x = cell_x + thumb_size
            cell.caption_y = cell_y
            cell.caption_w = caption_w_px
            cell.caption_h = thumb_size
        elif layout.caption_position in ("below", "above"):
            cell.caption_x = cell_x
            cell.caption_y = caption_y
            cell.caption_w = thumb_size
            cell.caption_h = caption_h_px
        cells.append(cell)

    return PageLayout(
        canvas_w=canvas_w, canvas_h=canvas_h,
        margin_px=margin_px, spacing_px=spacing_px,
        content_top_px=content_top_px,
        cols=cols, rows=rows, thumb_size=thumb_size,
        cells=cells,
    )
