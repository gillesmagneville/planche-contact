# -*- coding: utf-8 -*-
"""
Tests du moteur de mise en page (portfolio/presentation/layout_engine.py).

La partie la plus importante de ce fichier est la non-régression du modèle
"grid" : une copie fidèle de l'algorithme ACTUEL (corrigé - voir
CHANGELOG.md) de ContactSheetGenerator.create_contact_sheet() sert de
référence, et doit produire exactement les mêmes valeurs (thumb_size,
cols) que compute_page_layout() pour un Profil par défaut, sur toute la
plage de réglages existants (8 à 48 images/planche, par pas de 4 - valeurs
réellement proposées par le curseur de l'interface graphique - et les 5
formats de page pris en charge). Si cette référence diverge un jour de
contactsheet.py, les deux doivent être mis à jour ensemble.
"""
import math

import pytest

from portfolio.presentation import (
    Profile, LayoutSettings, CaptionSettings, compute_page_layout, compute_effective_per_page,
)
from portfolio.presentation.layout_engine import (
    PAPER_SIZES_MM, mm_to_px, pt_to_px, canvas_size_px, MIN_THUMB_SIZE_PX,
    LARGE_THUMBS_MAX_COLUMNS_TESTED, LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE,
    CAPTION_LINE_SPACING_PX, CAPTION_PHOTO_GAP_PX,
)


def _reference_grid_fit(num_per_sheet: int, page_format: str = "A4") -> tuple[int, int]:
    """Copie fidèle, pour comparaison, de l'algorithme actuellement codé
    en dur dans ContactSheetGenerator.create_contact_sheet() - voir
    portfolio/contactsheet.py (y compris son correctif du débordement
    vertical, voir CHANGELOG.md : l'espacement entre cellules est
    retranché aussi bien de la hauteur disponible que de la largeur)."""
    DPI = 300
    width_mm, height_mm = PAPER_SIZES_MM.get(page_format, PAPER_SIZES_MM["A4"])
    canvas_w, canvas_h = int(width_mm * DPI / 25.4), int(height_mm * DPI / 25.4)
    margin = int(12 * 300 / 25.4)
    spacing = int(5 * 300 / 25.4)

    best_cols = 1
    best_thumb_size = 0
    available_w = canvas_w - 2 * margin
    available_h = canvas_h - 2 * margin - 180
    for cols in range(1, min(num_per_sheet + 1, 9)):
        rows = math.ceil(num_per_sheet / cols)
        cell_w = available_w // cols if cols > 1 else available_w
        cell_h = available_h // rows if rows > 1 else available_h
        thumb_size = min(cell_w, cell_h)
        if thumb_size > best_thumb_size:
            best_thumb_size = thumb_size
            best_cols = cols

    thumb_size = max(best_thumb_size, 70)
    cols = best_cols
    rows = math.ceil(num_per_sheet / cols)
    max_thumb_w = (available_w - (cols - 1) * spacing) // cols
    thumb_size = min(thumb_size, max_thumb_w)
    max_thumb_h = (available_h - (rows - 1) * spacing) // rows
    thumb_size = min(thumb_size, max_thumb_h)
    return thumb_size, cols


@pytest.mark.parametrize("per_page", list(range(8, 49, 4)))
@pytest.mark.parametrize("page_format", list(PAPER_SIZES_MM.keys()))
def test_grid_template_matches_current_contactsheet_algorithm(per_page, page_format):
    """Non-régression : un Profil par défaut (modèle "grid", pas de
    légende) doit reproduire EXACTEMENT thumb_size et cols de l'algorithme
    actuel, pour tous les réglages réellement proposés par l'interface
    graphique (curseur 8 à 48 par pas de 4) et tous les formats de page."""
    expected_thumb_size, expected_cols = _reference_grid_fit(per_page, page_format)

    profile = Profile(layout=LayoutSettings(template="grid", per_page=per_page, page_format=page_format))
    page = compute_page_layout(profile, photo_count=per_page)

    assert page.thumb_size == expected_thumb_size
    assert page.cols == expected_cols


def test_grid_cells_count_matches_actual_photo_count_not_per_page():
    """La dernière page d'une série (moins de photos que per_page) ne doit
    produire que des cellules réellement occupées - la géométrie (taille
    de vignette, colonnes) reste en revanche celle de per_page, pour que
    toutes les pages d'une génération aient des cellules de taille
    identique (comportement actuel)."""
    profile = Profile(layout=LayoutSettings(template="grid", per_page=12))
    full_page = compute_page_layout(profile, photo_count=12)
    last_page = compute_page_layout(profile, photo_count=5)

    assert len(full_page.cells) == 12
    assert len(last_page.cells) == 5
    assert last_page.thumb_size == full_page.thumb_size
    assert last_page.cols == full_page.cols


def test_cells_do_not_overlap_and_stay_within_canvas():
    """Vérification géométrique générique, indépendante de contactsheet.py :
    quel que soit le modèle, aucune cellule ne doit déborder horizontalement
    NI verticalement du canevas, ni en chevaucher une autre. Le débordement
    vertical est désormais vérifié pour "grid" comme pour les autres
    modèles, puisque contactsheet.py lui-même a été corrigé (voir
    CHANGELOG.md) et que ce module reproduit son comportement corrigé."""
    for template in ("grid", "landscape", "portrait", "large_thumbs"):
        profile = Profile(layout=LayoutSettings(template=template, per_page=24, page_format="A4"))
        page = compute_page_layout(profile, photo_count=24)

        assert page.thumb_size >= MIN_THUMB_SIZE_PX
        seen_positions = set()
        for cell in page.cells:
            assert 0 <= cell.photo_x
            assert cell.photo_x + cell.photo_w <= page.canvas_w, template
            assert cell.photo_y + cell.photo_h <= page.canvas_h, template
            assert (cell.row, cell.col) not in seen_positions
            seen_positions.add((cell.row, cell.col))


def test_grid_vertical_overflow_bug_is_fixed():
    """Non-régression du correctif apporté à contactsheet.py (voir
    CHANGELOG.md) : le cas ayant révélé le débordement vertical (24 images
    en A4) ne doit plus déborder du bas physique de la planche, pour le
    modèle "grid" comme pour les autres. Avant le correctif, ce même test
    (alors nommé test_grid_known_preexisting_vertical_overflow_bug)
    vérifiait l'inverse - voir l'historique Git pour l'ancienne
    caractérisation du défaut."""
    profile = Profile(layout=LayoutSettings(template="grid", per_page=24, page_format="A4"))
    page = compute_page_layout(profile, photo_count=24)
    last_cell = page.cells[-1]
    assert last_cell.photo_y + last_cell.photo_h <= page.canvas_h


def test_caption_position_below_reserves_vertical_space():
    """Une légende "below" doit réduire thumb_size par rapport à l'absence
    de légende (l'espace réservé est retranché de la cellule AVANT le
    calcul de la taille de vignette - voir docstring du module), et
    chaque cellule doit avoir une zone de légende positionnée sous la
    photo."""
    no_caption = Profile(layout=LayoutSettings(template="grid", per_page=12, caption_position="none"))
    with_caption = Profile(layout=LayoutSettings(
        template="grid", per_page=12, caption_position="below", caption_area_mm=10,
    ))

    page_no_caption = compute_page_layout(no_caption, photo_count=12)
    page_with_caption = compute_page_layout(with_caption, photo_count=12)

    assert page_with_caption.thumb_size < page_no_caption.thumb_size
    cell = page_with_caption.cells[0]
    assert cell.caption_y == cell.photo_y + cell.photo_h + CAPTION_PHOTO_GAP_PX
    assert cell.caption_h == mm_to_px(10)


def test_caption_position_above_places_caption_before_photo():
    profile = Profile(layout=LayoutSettings(template="grid", per_page=12, caption_position="above", caption_area_mm=8))
    page = compute_page_layout(profile, photo_count=12)
    cell = page.cells[0]
    assert cell.caption_y < cell.photo_y
    assert cell.photo_y == cell.caption_y + cell.caption_h + CAPTION_PHOTO_GAP_PX


def test_caption_position_right_reserves_horizontal_space():
    """Une seule colonne (modèle "free", columns=1) pour garantir que la
    largeur est bien le facteur limitant : une légende "right" doit alors
    strictement réduire thumb_size. Avec plusieurs colonnes, selon le
    format de page, c'est parfois la hauteur qui limite déjà la taille de
    vignette - retrancher de la largeur ne changerait alors rien, sans que
    ce soit un bug (voir l'autre test, plus générique, qui vérifie
    uniquement le NON-dépassement, jamais une stricte diminution)."""
    no_caption = Profile(layout=LayoutSettings(template="free", per_page=1, columns=1, rows=1, caption_position="none"))
    with_caption = Profile(layout=LayoutSettings(template="free", per_page=1, columns=1, rows=1,
                                                  caption_position="right", caption_area_mm=15))

    page_no_caption = compute_page_layout(no_caption, photo_count=1)
    page_with_caption = compute_page_layout(with_caption, photo_count=1)

    assert page_with_caption.thumb_size < page_no_caption.thumb_size
    cell = page_with_caption.cells[0]
    assert cell.caption_x == cell.photo_x + cell.photo_w + CAPTION_PHOTO_GAP_PX
    assert cell.caption_w == mm_to_px(15)


def test_caption_area_grows_to_fit_configured_lines_and_font_size():
    """Non-régression : avec caption_area_mm laissé à une valeur par
    défaut/trop petite, mais plusieurs lignes de légende et/ou une grande
    police configurées, la hauteur RÉSERVÉE devait auparavant rester
    bornée à caption_area_mm - les dernières lignes dessinées par
    contactsheet.py._draw_caption() débordaient alors dans la photo de la
    rangée suivante (bug signalé, voir CHANGELOG.md). La hauteur réservée
    doit maintenant être le plus grand des deux : jamais plus petite que
    ce que contactsheet.py va réellement dessiner."""
    profile = Profile(layout=LayoutSettings(
        template="grid", per_page=12, caption_position="below", caption_area_mm=8,
    ), captions=CaptionSettings(fields=["filename"], lines=3, font_size=14))

    page = compute_page_layout(profile, photo_count=12)
    cell = page.cells[0]

    needed_h = 3 * (pt_to_px(14) + CAPTION_LINE_SPACING_PX)
    assert needed_h > mm_to_px(8), "le scénario doit bien dépasser caption_area_mm pour être significatif"
    assert cell.caption_h == needed_h

    # Et la propriété inverse : quand caption_area_mm est déjà suffisant,
    # il continue de piloter la hauteur réservée (comportement actuel
    # inchangé pour la configuration par défaut - lines=1, font_size=9).
    default_profile = Profile(layout=LayoutSettings(
        template="grid", per_page=12, caption_position="below", caption_area_mm=20,
    ))
    default_page = compute_page_layout(default_profile, photo_count=12)
    assert default_page.cells[0].caption_h == mm_to_px(20)


def test_caption_never_increases_thumb_size():
    """Propriété générique, plus faible mais toujours vraie : réserver de
    l'espace pour une légende ne peut jamais AGRANDIR la vignette,
    quelle que soit la configuration."""
    for position in ("below", "above", "right"):
        no_caption = Profile(layout=LayoutSettings(template="grid", per_page=12, caption_position="none"))
        with_caption = Profile(layout=LayoutSettings(template="grid", per_page=12,
                                                       caption_position=position, caption_area_mm=10))
        page_no_caption = compute_page_layout(no_caption, photo_count=12)
        page_with_caption = compute_page_layout(with_caption, photo_count=12)
        assert page_with_caption.thumb_size <= page_no_caption.thumb_size, position


def test_free_template_honors_explicit_columns_and_rows():
    profile = Profile(layout=LayoutSettings(template="free", per_page=20, columns=5, rows=4))
    page = compute_page_layout(profile, photo_count=20)
    assert page.cols == 5
    assert len(page.cells) == 20


def test_free_template_without_any_override_behaves_like_grid():
    """Un modèle "libre" sans aucun réglage explicite doit rester
    utilisable (pas de page vide, pas d'exception) - repli sur le même
    calcul que "grid"."""
    free_profile = Profile(layout=LayoutSettings(template="free", per_page=12))
    grid_profile = Profile(layout=LayoutSettings(template="grid", per_page=12))

    free_page = compute_page_layout(free_profile, photo_count=12)
    grid_page = compute_page_layout(grid_profile, photo_count=12)

    assert free_page.thumb_size == grid_page.thumb_size
    assert free_page.cols == grid_page.cols


def test_large_thumbs_never_exceeds_its_column_cap():
    """Le nombre de colonnes ne dépasse jamais
    LARGE_THUMBS_MAX_COLUMNS_TESTED, quel que soit per_page."""
    for per_page in (8, 12, 24, 48):
        profile = Profile(layout=LayoutSettings(template="large_thumbs", per_page=per_page))
        page = compute_page_layout(profile, photo_count=per_page)
        assert page.cols <= LARGE_THUMBS_MAX_COLUMNS_TESTED


def test_large_thumbs_reduces_effective_per_page_above_its_cap():
    """Cahier des charges : "pour le modèle « grandes vignettes », qu'il
    réduise lui-même ce nombre pour garantir de grandes vignettes dans
    tous les cas." compute_effective_per_page() doit donc plafonner le
    nombre de photos réellement placées par page à
    LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE dès que per_page le dépasse, et
    laisser per_page inchangé en-deçà."""
    for per_page in (8, 12, 24, 48):
        profile = Profile(layout=LayoutSettings(template="large_thumbs", per_page=per_page))
        expected = min(per_page, LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE)
        assert compute_effective_per_page(profile) == expected

        page = compute_page_layout(profile, photo_count=per_page)
        assert page.effective_per_page == expected
        assert len(page.cells) == expected


def test_large_thumbs_guarantees_same_thumb_size_whatever_per_page_is_configured():
    """LA garantie recherchée par le cahier des charges : contrairement à
    l'ancienne conception (qui ne bridait que le nombre de colonnes
    testées, donc ne garantissait rien dès que per_page forçait beaucoup
    de lignes - voir l'historique Git), la taille de vignette de
    "large_thumbs" ne dépend plus QUE du format de page une fois per_page
    au-delà de LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE : demander 12, 24 ou 48
    photos par planche produit alors exactement la même géométrie."""
    pages = []
    for per_page in (LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE, 24, 48):
        profile = Profile(layout=LayoutSettings(template="large_thumbs", per_page=per_page, page_format="A4"))
        pages.append(compute_page_layout(profile, photo_count=per_page))

    reference = pages[0]
    for page in pages[1:]:
        assert page.thumb_size == reference.thumb_size
        assert page.cols == reference.cols
        assert page.rows == reference.rows


def test_large_thumbs_never_overflows_canvas_regardless_of_per_page():
    for per_page in (8, 12, 24, 48):
        profile = Profile(layout=LayoutSettings(template="large_thumbs", per_page=per_page, page_format="A4"))
        page = compute_page_layout(profile, photo_count=per_page)
        for cell in page.cells:
            assert cell.photo_x + cell.photo_w <= page.canvas_w
            assert cell.photo_y + cell.photo_h <= page.canvas_h


def test_large_thumbs_matches_grid_columns_when_per_page_is_already_modest():
    """Dans le cas d'usage réellement visé (peu de photos par page, sous le
    plafond LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE), la réduction d'effectif
    de "large_thumbs" ne change rien (per_page déjà sous le plafond) : seule
    la restriction de colonnes testées distingue encore ce modèle de "grid"
    - avec un per_page assez petit pour que les deux recherches aboutissent
    au même nombre de colonnes, les deux produisent une géométrie identique
    (les deux appliquent désormais le même clampage d'espacement, voir
    CHANGELOG.md)."""
    per_page = min(8, LARGE_THUMBS_MAX_EFFECTIVE_PER_PAGE)
    profile_grid = Profile(layout=LayoutSettings(template="grid", per_page=per_page))
    profile_large = Profile(layout=LayoutSettings(template="large_thumbs", per_page=per_page))

    grid_page = compute_page_layout(profile_grid, photo_count=per_page)
    large_page = compute_page_layout(profile_large, photo_count=per_page)

    assert large_page.cols == grid_page.cols
    assert large_page.thumb_size == grid_page.thumb_size
    for cell in large_page.cells:
        assert cell.photo_y + cell.photo_h <= large_page.canvas_h


def test_landscape_orientation_swaps_canvas_dimensions():
    width, height = canvas_size_px("A4", orientation="portrait")
    swapped_width, swapped_height = canvas_size_px("A4", orientation="landscape")
    assert swapped_width == height
    assert swapped_height == width


@pytest.mark.parametrize("photo_count", [0, 1])
def test_edge_case_small_photo_counts_do_not_crash(photo_count):
    profile = Profile(layout=LayoutSettings(template="grid", per_page=12))
    page = compute_page_layout(profile, photo_count=photo_count)
    assert len(page.cells) == photo_count


def test_caption_lines_override_reserves_the_height_of_that_many_lines():
    """`caption_lines` permet à contactsheet.py de réserver la hauteur des
    lignes RÉELLEMENT nécessaires une fois les légendes passées à la ligne
    (voir ContactSheetGenerator._plan_page()), qui peut dépasser le réglage
    captions.lines : sans cela, les légendes plus hautes que prévu
    déborderaient dans la rangée suivante."""
    profile = Profile(layout=LayoutSettings(
        template="grid", per_page=12, caption_position="below", caption_area_mm=8,
    ), captions=CaptionSettings(fields=["filename"], lines=1, font_size=9))

    default_page = compute_page_layout(profile, photo_count=12)
    five_lines_page = compute_page_layout(profile, photo_count=12, caption_lines=5)

    line_h = pt_to_px(9) + CAPTION_LINE_SPACING_PX
    assert 5 * line_h > mm_to_px(8), "le scénario doit bien dépasser caption_area_mm pour être significatif"
    assert five_lines_page.cells[0].caption_h == 5 * line_h
    assert five_lines_page.cells[0].caption_h > default_page.cells[0].caption_h
    # Plus de place pour le texte = vignettes plus petites, jamais l'inverse.
    assert five_lines_page.thumb_size < default_page.thumb_size
    # Sans argument : strictement identique à captions.lines (compatibilité).
    assert compute_page_layout(profile, photo_count=12, caption_lines=1).cells[0].caption_h == \
        default_page.cells[0].caption_h


def test_caption_lines_override_is_ignored_for_right_captions():
    """Pour "right", la largeur est fixe (caption_area_mm) et la hauteur
    suit déjà celle de la vignette : le nombre de lignes ne change rien à
    la géométrie."""
    profile = Profile(layout=LayoutSettings(
        template="grid", per_page=12, caption_position="right", caption_area_mm=20,
    ), captions=CaptionSettings(fields=["filename"]))

    base = compute_page_layout(profile, photo_count=12)
    more_lines = compute_page_layout(profile, photo_count=12, caption_lines=9)

    assert more_lines.thumb_size == base.thumb_size
    assert more_lines.cells[0].caption_w == base.cells[0].caption_w
    assert more_lines.cells[0].caption_h == base.cells[0].caption_h


def test_photo_caption_gap_is_reserved_on_top_of_the_text_zone():
    """L'écart entre une photo et sa légende (CAPTION_PHOTO_GAP_PX) ne doit
    jamais être pris SUR la zone de texte réglée par l'utilisateur
    (caption_h reste « Zone de légende (mm) ») : il s'ajoute au pas entre
    deux rangées, sinon la dernière ligne d'une légende pourrait toucher
    la photo de la rangée suivante."""
    profile = Profile(layout=LayoutSettings(
        template="grid", per_page=12, caption_position="below", caption_area_mm=10,
    ))
    page = compute_page_layout(profile, photo_count=12)
    assert page.rows >= 2
    first, below_first = page.cells[0], page.cells[page.cols]

    assert first.caption_h == mm_to_px(10)
    assert first.caption_y - (first.photo_y + first.photo_h) == CAPTION_PHOTO_GAP_PX
    assert below_first.photo_y - first.photo_y == (
        page.thumb_size + CAPTION_PHOTO_GAP_PX + mm_to_px(10) + page.spacing_px
    )


def test_no_gap_is_reserved_without_a_caption():
    """Sans légende, la géométrie reste exactement celle d'origine - aucun
    écart fantôme réservé."""
    page = compute_page_layout(Profile(), photo_count=12)
    first, below_first = page.cells[0], page.cells[page.cols]
    assert below_first.photo_y - first.photo_y == page.thumb_size + page.spacing_px
    assert first.caption_x is None and first.caption_y is None


@pytest.mark.parametrize("position", ["below", "above", "right"])
@pytest.mark.parametrize("per_page", [6, 12, 24])
def test_caption_zone_never_overlaps_another_photo_nor_leaves_the_page(position, per_page):
    profile = Profile(
        layout=LayoutSettings(template="grid", per_page=per_page, caption_position=position, caption_area_mm=10),
        captions=CaptionSettings(fields=["filename"], lines=2),
    )
    page = compute_page_layout(profile, photo_count=per_page)

    for a in page.cells:
        cap_right = a.caption_x + a.caption_w
        cap_bottom = a.caption_y + a.caption_h
        assert cap_right <= page.canvas_w and cap_bottom <= page.canvas_h
        assert a.photo_x + a.photo_w <= page.canvas_w and a.photo_y + a.photo_h <= page.canvas_h
        for b in page.cells:
            if a.index == b.index:
                continue
            overlap_x = a.caption_x < b.photo_x + b.photo_w and b.photo_x < cap_right
            overlap_y = a.caption_y < b.photo_y + b.photo_h and b.photo_y < cap_bottom
            assert not (overlap_x and overlap_y), (position, per_page, a.index, b.index)


# ---------------------------------------------------------------------------
# Centrage horizontal de la grille sur la page. La taille de vignette est
# limitée par la largeur OU la hauteur : la grille est presque toujours moins
# large que la zone utile, et tout le vide restait à droite (jusqu'à ~6 cm).
# ---------------------------------------------------------------------------

def _horizontal_margins(page, caption_position, caption_w_px):
    """(marge gauche, marge droite) réelles de la grille, zones de légende
    à droite comprises."""
    reserved_w = (caption_w_px + CAPTION_PHOTO_GAP_PX) if caption_position == "right" else 0
    first = page.cells[0].photo_x
    last_right = page.cells[page.cols - 1].photo_x + page.thumb_size + reserved_w
    return first, page.canvas_w - last_right


@pytest.mark.parametrize("caption_position", ["none", "below", "above", "right"])
@pytest.mark.parametrize("template", ["grid", "landscape", "portrait", "large_thumbs"])
@pytest.mark.parametrize("orientation", ["portrait", "landscape"])
@pytest.mark.parametrize("page_format", ["A5", "A4", "A3", "Letter"])
@pytest.mark.parametrize("per_page", [8, 12, 24, 30, 48])
def test_grid_is_centered_horizontally_between_the_page_margins(
        per_page, page_format, orientation, template, caption_position):
    fields = [] if caption_position == "none" else ["filename", "datetime"]
    profile = Profile(
        layout=LayoutSettings(template=template, per_page=per_page, page_format=page_format,
                              orientation=orientation, caption_position=caption_position),
        captions=CaptionSettings(fields=fields),
    )
    page = compute_page_layout(profile, compute_effective_per_page(profile),
                               caption_lines=2 if fields else None)
    caption_w = page.cells[0].caption_w or 0
    left, right = _horizontal_margins(page, caption_position, caption_w)

    assert left >= page.margin_px, "la grille ne doit jamais empiéter sur la marge gauche"
    assert right >= page.margin_px or page.grid_w > page.canvas_w - 2 * page.margin_px
    assert abs(left - right) <= 1, f"marge gauche {left} px, marge droite {right} px"


def test_known_case_a4_portrait_8_photos_used_to_leave_all_the_empty_space_on_the_right():
    page = compute_page_layout(Profile(layout=LayoutSettings(per_page=8)), 8)
    left, right = _horizontal_margins(page, "none", 0)

    # Avant : 141 px à gauche (la marge), 846 px à droite.
    assert left == 493 and right == 494


def test_grid_extent_is_exposed_for_vertical_centering():
    page = compute_page_layout(Profile(layout=LayoutSettings(per_page=12)), 12)

    assert page.grid_w == page.cols * page.thumb_size + (page.cols - 1) * page.spacing_px
    assert page.grid_h == page.rows * page.thumb_size + (page.rows - 1) * page.spacing_px


def test_grid_extent_includes_caption_zones():
    profile = Profile(
        layout=LayoutSettings(per_page=12, caption_position="below"),
        captions=CaptionSettings(fields=["filename"]),
    )
    page = compute_page_layout(profile, 12, caption_lines=2)
    row_pitch = page.cells[page.cols].photo_y - page.cells[0].photo_y

    assert page.grid_h == page.rows * (row_pitch - page.spacing_px) + (page.rows - 1) * page.spacing_px


def test_centering_does_not_depend_on_the_number_of_photos_on_the_page():
    """Une page incomplète (dernière page) garde la même grille, donc les
    mêmes positions pour ses photos, que les pages pleines."""
    profile = Profile(layout=LayoutSettings(per_page=12))
    full = compute_page_layout(profile, 12)
    short = compute_page_layout(profile, 5)

    assert (short.grid_w, short.grid_h) == (full.grid_w, full.grid_h)
    assert [(c.photo_x, c.photo_y) for c in short.cells] == [(c.photo_x, c.photo_y) for c in full.cells[:5]]

