# -*- coding: utf-8 -*-
"""
portfolio/presentation/captions.py - Résolution des légendes personnalisables
par photo (cahier des charges §1), à partir des métadonnées EXIF extraites
par portfolio.utils.get_exif_metadata() et des réglages CaptionSettings
d'un Profil.

Séparation stricte des responsabilités, cohérente avec le reste du
package : utils.get_exif_metadata() extrait des valeurs BRUTES (nombres,
tuples, datetime) sans aucune mise en forme textuelle ; ce module décide
de la représentation par défaut "raisonnable" de chaque champ (unités,
arrondis, gabarit "{value}") et applique l'éventuelle personnalisation de
l'utilisateur (CaptionSettings.format_overrides). Les générateurs de
sortie (contactsheet.py/pdfexport.py pour le rendu PIL, htmlgallery.py
pour le HTML, et la future prévisualisation GTK) consomment donc TOUS la
même fonction - aucune règle de formatage de légende n'est dupliquée
entre eux (cahier des charges §5).

Ne lève jamais d'exception : une métadonnée absente est simplement omise
de la légende (jamais une chaîne vide affichée, jamais une génération
interrompue) - cahier des charges §1 : "ne jamais produire d'erreur pour
les photos dont certaines métadonnées sont absentes". Le filtrage GPS
(show_gps) est déjà garanti en amont par CaptionSettings.effective_fields()
- ce module ne fait que le réutiliser, jamais une seconde vérification
redondante qui pourrait diverger.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from .profile import Profile


def _format_number(value: float, decimals: int = 1) -> str:
    """Nombre lisible, sans décimale inutile (ex: 50.0 -> "50", 2.8 ->
    "2.8")."""
    rounded = round(value, decimals)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.{decimals}f}".rstrip("0").rstrip(".")


def _format_shutter_speed(seconds: float) -> str:
    """Convention photographique habituelle : fraction pour les vitesses
    rapides ("1/250"), décimal pour les poses longues (>= 1 s, ex:
    "2.5")."""
    if seconds <= 0:
        return "0"
    if seconds >= 1:
        return _format_number(seconds, 1)
    denominator = round(1 / seconds)
    if denominator <= 0:
        return _format_number(seconds, 3)
    return f"1/{denominator}"


def _format_gps(lat: float, lon: float) -> str:
    lat_ref = "N" if lat >= 0 else "S"
    lon_ref = "E" if lon >= 0 else "W"
    return f"{abs(lat):.4f}°{lat_ref}, {abs(lon):.4f}°{lon_ref}"


def _default_display(field: str, value: Any) -> Optional[str]:
    """Représentation par défaut, "raisonnable", d'une valeur brute de
    métadonnée - voir le docstring du module. Renvoie None si la valeur
    n'est pas exploitable (type inattendu pour ce champ), plutôt que de
    lever une exception ou d'afficher une valeur absurde."""
    try:
        if field == "filename":
            text = str(value)
            return text or None
        if field == "datetime":
            return value.strftime("%Y-%m-%d") if isinstance(value, datetime) else None
        if field in ("camera", "lens"):
            text = str(value).strip()
            return text or None
        if field == "focal_length":
            return f"{_format_number(float(value))} mm"
        if field == "focal_35mm":
            return f"{int(value)} mm (éq. 24×36)"
        if field == "aperture":
            return f"f/{_format_number(float(value))}"
        if field == "shutter_speed":
            return f"{_format_shutter_speed(float(value))}s"
        if field == "iso":
            return f"ISO {int(value)}"
        if field == "dimensions":
            width, height = value
            return f"{int(width)} × {int(height)}"
        if field == "gps":
            lat, lon = value
            return _format_gps(float(lat), float(lon))
    except (TypeError, ValueError, AttributeError):
        return None
    return None


def _format_field(field: str, metadata: dict, overrides: dict) -> Optional[str]:
    value = metadata.get(field)
    if value is None:
        return None
    display = _default_display(field, value)
    if not display:
        return None
    template = overrides.get(field)
    if template:
        try:
            return template.format(value=display)
        except (KeyError, IndexError, ValueError):
            # Gabarit utilisateur invalide (ex: accolade non échappée,
            # référence à un nom absent) : on retombe sur l'affichage par
            # défaut plutôt que d'interrompre toute la génération pour une
            # faute de frappe dans un profil enregistré.
            return display
    return display


def _chunk_evenly(items: list[str], n: int) -> list[list[str]]:
    """Répartit `items` en au plus `n` groupes consécutifs aussi égaux que
    possible, dans l'ordre d'origine (les premiers groupes reçoivent
    l'élément supplémentaire en cas de division inégale). Les groupes
    vides (n > len(items)) sont omis plutôt que de produire des lignes de
    légende vides."""
    if n <= 1 or len(items) <= 1:
        return [items] if items else []
    base, extra = divmod(len(items), n)
    chunks = []
    start = 0
    for i in range(n):
        size = base + (1 if i < extra else 0)
        if size == 0:
            continue
        chunks.append(items[start:start + size])
        start += size
    return chunks


def resolve_caption_lines(profile: Profile, metadata: dict) -> list[str]:
    """Résout la ou les lignes de légende d'UNE photo, à partir de ses
    métadonnées (voir portfolio.utils.get_exif_metadata()) et des réglages
    CaptionSettings.fields/lines/format_overrides/separator du Profil.

    Renvoie une liste de chaînes (une par ligne réellement non vide) -
    liste VIDE si aucun champ n'est configuré ou si aucune métadonnée n'a
    pu être extraite pour les champs demandés (ex: photo sans EXIF) : dans
    ce cas, l'appelant ne doit rien dessiner, jamais une légende vide ou
    une exception."""
    captions = profile.captions
    fields = captions.effective_fields()
    if not fields or not metadata:
        return []

    parts = [
        text for text in (
            _format_field(field, metadata, captions.format_overrides)
            for field in fields
        )
        if text
    ]
    if not parts:
        return []

    chunks = _chunk_evenly(parts, max(1, captions.lines))
    return [captions.separator.join(chunk) for chunk in chunks]
