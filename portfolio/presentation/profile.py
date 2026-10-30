# -*- coding: utf-8 -*-
"""
portfolio/presentation/profile.py - Modèle de données "Profil" (mise en
page + légendes + thème) et sa (dé)sérialisation JSON.

Un Profil regroupe tous les réglages des évolutions légendes/modèles de
mise en page/thèmes (cahier des charges §2, §4.4) :

- LayoutSettings  : modèle de mise en page, grille, marges, format de page...
- CaptionSettings : champs de légende affichés, ordre, format, police...
- ThemeSettings   : thème prédéfini + personnalisation des couleurs.

Un Profil peut être enregistré par l'utilisateur sous forme de fichier JSON
réutilisable et rechargé plus tard (interface graphique), ou pointé
directement en ligne de commande (--profile fichier.json).

Règle de rétrocompatibilité STRICTE (cahier des charges §2, §4.4, §8) :
l'absence totale de profil doit produire un rendu strictement identique au
comportement actuel de l'application (avant ces fonctionnalités). Chaque
valeur par défaut ci-dessous a donc été choisie pour correspondre
EXACTEMENT à ce qui est aujourd'hui codé en dur dans contactsheet.py (fond
blanc, texte noir, pas de légende par photo, grille par recherche du
meilleur nombre de colonnes, marge 12 mm, espacement 5 mm) et
htmlgallery.py (pas de légende par photo, palette claire actuelle). Un
champ absent ou invalide dans un JSON chargé retombe silencieusement sur
cette même valeur par défaut - jamais d'exception, jamais de génération
interrompue pour un fichier de profil corrompu ou produit par une version
antérieure du projet ne connaissant pas encore tel ou tel champ.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes de validation
# ---------------------------------------------------------------------------

#: Modèles de mise en page (cahier des charges §2). "grid" correspond au
#: seul algorithme existant aujourd'hui dans contactsheet.py (recherche du
#: nombre de colonnes maximisant la taille des vignettes) ; les quatre
#: autres sont de nouvelles stratégies du futur layout_engine.py.
LAYOUT_TEMPLATES = ("grid", "landscape", "portrait", "large_thumbs", "free")

#: Mode d'adaptation d'une photo à sa cellule (cahier des charges §2).
FIT_MODES = ("contain", "cover")

#: Formats de page pris en charge - doit rester synchronisé avec
#: ContactSheetGenerator._get_canvas_size() (contactsheet.py).
PAGE_FORMATS = ("A5", "A4", "A3", "A2", "Letter")

ORIENTATIONS = ("portrait", "landscape")

#: Positions possibles pour le titre/auteur en en-tête de planche.
HEADER_POSITIONS = ("top_left", "top_center", "top_right", "none")

#: Positions possibles pour la légende d'une photo par rapport à celle-ci.
CAPTION_POSITIONS = ("below", "above", "right", "none")

#: Alignement du texte des légendes.
CAPTION_ALIGNMENTS = ("left", "center", "right")

#: Champs de légende disponibles (cahier des charges §1). L'ordre réel
#: d'affichage choisi par l'utilisateur vit dans CaptionSettings.fields,
#: pas ici - ce tuple ne sert qu'à valider qu'une clé est reconnue.
#: "gps" est délibérément un champ comme un autre ici : c'est
#: CaptionSettings.show_gps qui agit comme interrupteur de confidentialité
#: explicite, voir plus bas.
CAPTION_FIELDS = (
    "filename", "datetime", "camera", "lens", "focal_length", "focal_35mm",
    "aperture", "shutter_speed", "iso", "dimensions", "gps",
)

#: Thèmes prédéfinis (cahier des charges §4.1). "light" correspond aux
#: couleurs actuellement codées en dur (fond blanc, texte noir, gris
#: #555555 pour le texte secondaire) - c'est le thème par défaut, pour ne
#: rien changer visuellement tant qu'aucun thème n'est choisi explicitement.
THEME_MODES = ("light", "dark", "neutral", "system")


def _coerce(value: Any, expected_type: type, default: Any, field_name: str) -> Any:
    """Renvoie `value` si son type correspond à `expected_type`, sinon
    `default` (avec un message de log) - jamais d'exception. `bool` est
    exclu de la coercition int/float implicite de Python (un bool est
    aussi un int) pour éviter qu'une valeur comme `true` soit acceptée là
    où un nombre est attendu, ou inversement."""
    if expected_type is float and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, expected_type) and not (expected_type in (int, float) and isinstance(value, bool)):
        return value
    if value is not None:
        logger.debug(f"Profil : valeur invalide pour '{field_name}' ({value!r}), valeur par défaut utilisée.")
    return default


def _coerce_choice(value: Any, choices: tuple, default: str, field_name: str) -> str:
    if isinstance(value, str) and value in choices:
        return value
    if value is not None:
        logger.debug(
            f"Profil : valeur '{value!r}' non reconnue pour '{field_name}' "
            f"(attendu parmi {choices}), valeur par défaut '{default}' utilisée."
        )
    return default


def _coerce_optional_int(value: Any, default: Optional[int], field_name: str) -> Optional[int]:
    if value is None:
        return default
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    logger.debug(f"Profil : entier positif attendu pour '{field_name}' ({value!r}), ignoré.")
    return default


# ---------------------------------------------------------------------------
# Mise en page
# ---------------------------------------------------------------------------

@dataclass
class LayoutSettings:
    #: Modèle de mise en page - voir LAYOUT_TEMPLATES.
    template: str = "grid"
    #: Nombre de colonnes/lignes imposé par l'utilisateur (modèle "free"
    #: notamment) - None laisse le moteur de mise en page les déterminer
    #: automatiquement, comme aujourd'hui.
    columns: Optional[int] = None
    rows: Optional[int] = None
    #: Nombre de photos par page - reprend le nom interne historique
    #: "num_per_sheet" de Config, mais vit désormais ici.
    per_page: int = 12
    margin_mm: float = 12.0
    spacing_mm: float = 5.0
    page_format: str = "A4"
    orientation: str = "portrait"
    fit_mode: str = "contain"
    title_position: str = "top_center"
    author_position: str = "top_center"
    page_numbering: bool = True
    #: "none" = pas de légende sous les photos - comportement actuel.
    caption_position: str = "none"
    caption_area_mm: float = 8.0

    @classmethod
    def from_dict(cls, data: dict) -> "LayoutSettings":
        d = cls()
        if not isinstance(data, dict):
            return d
        return cls(
            template=_coerce_choice(data.get("template"), LAYOUT_TEMPLATES, d.template, "layout.template"),
            columns=_coerce_optional_int(data.get("columns"), d.columns, "layout.columns"),
            rows=_coerce_optional_int(data.get("rows"), d.rows, "layout.rows"),
            per_page=_coerce_optional_int(data.get("per_page"), d.per_page, "layout.per_page") or d.per_page,
            margin_mm=_coerce(data.get("margin_mm"), float, d.margin_mm, "layout.margin_mm"),
            spacing_mm=_coerce(data.get("spacing_mm"), float, d.spacing_mm, "layout.spacing_mm"),
            page_format=_coerce_choice(data.get("page_format"), PAGE_FORMATS, d.page_format, "layout.page_format"),
            orientation=_coerce_choice(data.get("orientation"), ORIENTATIONS, d.orientation, "layout.orientation"),
            fit_mode=_coerce_choice(data.get("fit_mode"), FIT_MODES, d.fit_mode, "layout.fit_mode"),
            title_position=_coerce_choice(data.get("title_position"), HEADER_POSITIONS, d.title_position, "layout.title_position"),
            author_position=_coerce_choice(data.get("author_position"), HEADER_POSITIONS, d.author_position, "layout.author_position"),
            page_numbering=_coerce(data.get("page_numbering"), bool, d.page_numbering, "layout.page_numbering"),
            caption_position=_coerce_choice(data.get("caption_position"), CAPTION_POSITIONS, d.caption_position, "layout.caption_position"),
            caption_area_mm=_coerce(data.get("caption_area_mm"), float, d.caption_area_mm, "layout.caption_area_mm"),
        )


# ---------------------------------------------------------------------------
# Légendes
# ---------------------------------------------------------------------------

@dataclass
class CaptionSettings:
    #: Champs affichés, DANS L'ORDRE choisi par l'utilisateur. Liste vide
    #: par défaut = aucune légende, comportement actuel.
    fields: list[str] = field(default_factory=list)
    #: Format d'affichage par champ (ex: {"aperture": "f/{value}"}) - les
    #: champs non présents ici utilisent un format par défaut raisonnable
    #: (voir captions.py, à venir).
    format_overrides: dict[str, str] = field(default_factory=dict)
    #: Répartition sur plusieurs lignes (cahier des charges §1).
    lines: int = 1
    font_size: int = 9
    alignment: str = "center"
    separator: str = " · "
    #: Interrupteur de confidentialité EXPLICITE pour les coordonnées GPS
    #: (cahier des charges §1 : "option permettant explicitement de les
    #: masquer"). Même si "gps" figure dans `fields`, le champ n'est
    #: effectivement affiché QUE si show_gps vaut True - défaut à False
    #: pour ne jamais exposer une localisation par accident.
    show_gps: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "CaptionSettings":
        d = cls()
        if not isinstance(data, dict):
            return d

        fields_in = data.get("fields")
        fields_out: list[str] = []
        if isinstance(fields_in, list):
            for f in fields_in:
                if isinstance(f, str) and f in CAPTION_FIELDS and f not in fields_out:
                    fields_out.append(f)
                else:
                    logger.debug(f"Profil : champ de légende ignoré (inconnu ou dupliqué) : {f!r}")
        elif fields_in is not None:
            logger.debug("Profil : 'captions.fields' doit être une liste, ignoré.")

        overrides_in = data.get("format_overrides")
        overrides_out: dict[str, str] = {}
        if isinstance(overrides_in, dict):
            for key, value in overrides_in.items():
                if key in CAPTION_FIELDS and isinstance(value, str):
                    overrides_out[key] = value

        return cls(
            fields=fields_out,
            format_overrides=overrides_out,
            lines=_coerce_optional_int(data.get("lines"), d.lines, "captions.lines") or d.lines,
            font_size=_coerce_optional_int(data.get("font_size"), d.font_size, "captions.font_size") or d.font_size,
            alignment=_coerce_choice(data.get("alignment"), CAPTION_ALIGNMENTS, d.alignment, "captions.alignment"),
            separator=data.get("separator") if isinstance(data.get("separator"), str) else d.separator,
            show_gps=_coerce(data.get("show_gps"), bool, d.show_gps, "captions.show_gps"),
        )

    def effective_fields(self) -> list[str]:
        """Champs réellement à afficher, GPS filtré tant que `show_gps`
        n'est pas explicitement activé - à utiliser par captions.py plutôt
        que `fields` directement, pour qu'il soit structurellement
        impossible d'afficher un GPS « par erreur »."""
        if self.show_gps:
            return list(self.fields)
        return [f for f in self.fields if f != "gps"]


# ---------------------------------------------------------------------------
# Thèmes
# ---------------------------------------------------------------------------

@dataclass
class ThemeCustomColors:
    """Couleurs personnalisées (cahier des charges §4.3), toutes
    optionnelles : une couleur à None laisse le thème prédéfini choisi
    inchangé pour cette couleur précise. Valeurs attendues en hexadécimal
    ("#rrggbb"), validées par themes.py (à venir) plutôt qu'ici."""
    background: Optional[str] = None
    text: Optional[str] = None
    accent: Optional[str] = None
    border: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "ThemeCustomColors":
        if not isinstance(data, dict):
            return cls()

        def _hex_or_none(value: Any) -> Optional[str]:
            if isinstance(value, str) and value.startswith("#"):
                return value
            if value is not None:
                logger.debug(f"Profil : couleur personnalisée invalide ignorée : {value!r}")
            return None

        return cls(
            background=_hex_or_none(data.get("background")),
            text=_hex_or_none(data.get("text")),
            accent=_hex_or_none(data.get("accent")),
            border=_hex_or_none(data.get("border")),
        )


@dataclass
class ThemeSettings:
    #: Thème prédéfini - voir THEME_MODES. "light" = couleurs actuellement
    #: codées en dur, donc aucun changement visuel tant qu'aucun thème
    #: n'est choisi explicitement.
    mode: str = "light"
    custom: ThemeCustomColors = field(default_factory=ThemeCustomColors)

    @classmethod
    def from_dict(cls, data: dict) -> "ThemeSettings":
        d = cls()
        if not isinstance(data, dict):
            return d
        return cls(
            mode=_coerce_choice(data.get("mode"), THEME_MODES, d.mode, "theme.mode"),
            custom=ThemeCustomColors.from_dict(data.get("custom")),
        )


# ---------------------------------------------------------------------------
# Profil
# ---------------------------------------------------------------------------

@dataclass
class Profile:
    """Un profil complet : nom (pour l'affichage dans l'interface
    graphique) + les trois groupes de réglages. `default_profile()` est le
    profil "vide" dont le rendu doit être strictement identique au
    comportement actuel de l'application."""
    name: Optional[str] = None
    layout: LayoutSettings = field(default_factory=LayoutSettings)
    captions: CaptionSettings = field(default_factory=CaptionSettings)
    theme: ThemeSettings = field(default_factory=ThemeSettings)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        if not isinstance(data, dict):
            logger.warning("Profil : contenu JSON invalide (objet attendu), valeurs par défaut utilisées.")
            return cls()
        name = data.get("name")
        return cls(
            name=name if isinstance(name, str) else None,
            layout=LayoutSettings.from_dict(data.get("layout")),
            captions=CaptionSettings.from_dict(data.get("captions")),
            theme=ThemeSettings.from_dict(data.get("theme")),
        )


def default_profile() -> Profile:
    """Profil "vide" dont le rendu est strictement identique au
    comportement actuel de l'application, avant légendes/modèles de mise
    en page/thèmes - utilisé quand aucun profil n'est fourni (ni
    --profile en CLI, ni profil chargé dans l'interface graphique)."""
    return Profile()


def interface_default_profile() -> Profile:
    """Profil que l'INTERFACE GRAPHIQUE présente au démarrage et à
    « Réinitialiser » : celui de default_profile() avec, en plus, le nom du
    fichier sous chaque photo (légende « Nom du fichier » cochée).

    Volontairement distinct de default_profile(), qui reste ce que la ligne
    de commande applique sans --profile (aucune légende : rendu strictement
    identique à celui d'avant les légendes, dont dépendent les scripts
    existants) - l'interface, elle, transmet toujours son profil au CLI dès
    qu'il diffère de default_profile() (voir planche-contact-gtk.py)."""
    return Profile(
        layout=LayoutSettings(caption_position="below"),
        captions=CaptionSettings(fields=["filename"]),
    )


def load_profile(path: "str | Path") -> Profile:
    """Charge un profil depuis un fichier JSON. Jamais d'exception : un
    fichier absent, illisible, mal formé, ou partiellement reconnu (champs
    manquants ou d'une version plus récente/ancienne du projet) retombe
    sur les valeurs par défaut pour les champs concernés, avec un message
    de log - jamais une génération interrompue à cause d'un profil."""
    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.warning(f"Profil introuvable : {path} - valeurs par défaut utilisées.")
        return default_profile()
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Profil illisible ({path}) : {e} - valeurs par défaut utilisées.")
        return default_profile()

    try:
        return Profile.from_dict(data)
    except Exception as e:
        # Filet de sécurité final : même une erreur inattendue dans
        # from_dict() ne doit jamais interrompre une génération pour un
        # simple problème de profil.
        logger.warning(f"Profil invalide ({path}) : {e} - valeurs par défaut utilisées.")
        return default_profile()


def save_profile(profile: Profile, path: "str | Path") -> None:
    """Enregistre un profil au format JSON, lisible/modifiable à la main
    et rechargeable par load_profile() ou utilisable via --profile."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile.to_dict(), f, indent=2, ensure_ascii=False)
        f.write("\n")
