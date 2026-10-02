import functools
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from PIL import Image, ImageDraw, ImageFont

from .rawloader import is_raw_file, get_original_dimensions

try:
    import exifread
    EXIFREAD_AVAILABLE = True
except ImportError:
    EXIFREAD_AVAILABLE = False


def setup_logging(log_path: Path) -> None:
    """Configure le logging (fichier + console)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


# Police embarquée avec le projet (portfolio/fonts/, licence Bitstream Vera
# - voir portfolio/fonts/LICENSE.txt), utilisée en priorité : garantit un
# rendu strictement identique sur toutes les plateformes, plutôt que de
# dépendre d'une police système trouvée à un chemin devinable (ex:
# C:/Windows/Fonts/arial.ttf), qui peut échouer silencieusement selon la
# machine et faire retomber sur la police minuscule intégrée à Pillow.
_BUNDLED_FONTS_DIR = Path(__file__).parent / "fonts"


@functools.lru_cache(maxsize=32)
def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Charge une police TrueType de manière cross-platform.
    Retourne la police par défaut si aucune police système n'est trouvée.
    Mise en cache : évite de relire/reparser le fichier de police à chaque
    appel (des centaines de fois sur une galerie de centaines de photos
    avec filigrane).
    """
    suffix = "-Bold" if bold else ""
    candidates = [
        _BUNDLED_FONTS_DIR / f"DejaVuSans{suffix}.ttf",
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{suffix}.ttf",
        f"C:/Windows/Fonts/arial{'bd' if bold else ''}.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def apply_watermark(
    image: Image.Image,
    text: str,
    opacity: int = 70,
    orientation: str = "Horizontal"
) -> Image.Image:
    """
    Filigrane en mosaïque répétée, utilisé de façon identique par les
    planches contact (et donc le PDF, qui réutilise ces mêmes images) et la
    galerie HTML - une seule implémentation, pour garantir un rendu
    strictement identique partout.

    `opacity` est un pourcentage (0-100), converti ici en canal alpha
    (0-255).
    """
    if not text:
        return image

    # Ajout automatique du symbole copyright (comportement des deux
    # implémentations d'origine, conservé ici).
    if not text.startswith("©"):
        text = "© " + text

    try:
        img = image.convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        font = get_font(14, bold=True)

        alpha = max(0, min(255, int(255 * (opacity / 100))))
        text_color = (255, 255, 255, alpha)

        # Gestion de l'orientation. PIL fait pivoter dans le sens
        # anti-horaire pour un angle positif : "horaire" correspond donc à
        # un angle négatif, et inversement.
        if orientation == "Diagonale horaire":
            angle = -32
        elif orientation == "Diagonale anti-horaire":
            angle = 32
        else:
            angle = 0

        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Espacement (identique aux planches)
        x_spacing = text_width + 220
        y_spacing = text_height + 160

        for y in range(-text_height, img.height + text_height, y_spacing):
            for x in range(-text_width, img.width + text_width, x_spacing):
                offset_x = (y // y_spacing) * 50 if angle != 0 else 0
                draw.text((x + offset_x, y), text, font=font, fill=text_color)

        # Rotation si besoin
        if angle != 0:
            overlay = overlay.rotate(angle, resample=Image.BICUBIC, expand=False, center=(img.width / 2, img.height / 2))

        return Image.alpha_composite(img, overlay).convert("RGB")

    except Exception as e:
        logging.getLogger(__name__).warning(f"Filigrane impossible : {e}")
        return image


def get_exif_date(path: Path) -> Optional[datetime]:
    """Extrait la date EXIF la plus pertinente (prise de vue), RAW compris.
    Centralisé ici : utilisé à la fois pour le tri des photos
    (scanner.py) et pour les informations affichées dans la visionneuse
    de la galerie HTML (htmlgallery.py)."""
    path = Path(path)
    if is_raw_file(path):
        if not EXIFREAD_AVAILABLE:
            return None
        try:
            with open(path, "rb") as f:
                tags = exifread.process_file(f, details=False, stop_tag="EXIF DateTimeOriginal")
            for key in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"):
                date_str = tags.get(key)
                if date_str:
                    try:
                        return datetime.strptime(str(date_str), "%Y:%m:%d %H:%M:%S")
                    except ValueError:
                        continue
        except Exception:
            pass
        return None

    try:
        with Image.open(path) as img:
            exif = img.getexif()
            # DateTimeOriginal (0x9003) et DateTimeDigitized (0x9004) vivent
            # dans le sous-IFD Exif, jamais dans l'IFD0 principal : exif.get()
            # direct ne les trouve pas, il faut passer par get_ifd(). Seul
            # DateTime (0x0132, date de MODIFICATION du fichier, moins
            # pertinente qu'une date de prise de vue) vit dans l'IFD0.
            exif_ifd = exif.get_ifd(0x8769)  # ExifTags.IFD.Exif
            for tag in (0x9003, 0x9004):
                date_str = exif_ifd.get(tag)
                if date_str:
                    try:
                        return datetime.strptime(str(date_str), "%Y:%m:%d %H:%M:%S")
                    except ValueError:
                        continue
            date_str = exif.get(0x0132)
            if date_str:
                try:
                    return datetime.strptime(str(date_str), "%Y:%m:%d %H:%M:%S")
                except ValueError:
                    pass
    except Exception:
        pass
    return None


#: Clés du dictionnaire renvoyé par get_exif_metadata() - correspondent
#: EXACTEMENT à portfolio.presentation.profile.CAPTION_FIELDS, pour un
#: usage direct par portfolio/presentation/captions.py (lookup par nom de
#: champ, sans table de correspondance intermédiaire).
_EXIF_TAG_MAKE = 0x010F
_EXIF_TAG_MODEL = 0x0110
_EXIF_TAG_LENS_MODEL = 0xA434
_EXIF_TAG_FOCAL_LENGTH = 0x920A
_EXIF_TAG_FOCAL_LENGTH_35MM = 0xA405
_EXIF_TAG_FNUMBER = 0x829D
_EXIF_TAG_EXPOSURE_TIME = 0x829A
_EXIF_TAG_ISO = 0x8827
_EXIF_IFD_EXIF = 0x8769
_EXIF_IFD_GPSINFO = 0x8825
_GPS_TAG_LAT_REF = 1
_GPS_TAG_LAT = 2
_GPS_TAG_LON_REF = 3
_GPS_TAG_LON = 4


def _combine_camera(make: Optional[str], model: Optional[str]) -> Optional[str]:
    """Combine fabricant + modèle en un seul champ "camera" lisible,
    évitant une répétition quand le modèle inclut déjà le fabricant (ex :
    Nikon rapporte souvent "NIKON D850" comme Model, Make valant
    "NIKON CORPORATION")."""
    make = make.strip() if make else None
    model = model.strip() if model else None
    if make and model:
        if model.lower().startswith(make.lower().split()[0].lower()):
            return model
        return f"{make} {model}"
    return make or model


def _rational_to_float(value: Any) -> Optional[float]:
    """Convertit une valeur EXIF potentiellement rationnelle (IFDRational
    de Pillow, nombre déjà décimal, ou tout objet exposant .num/.den comme
    exifread.utils.Ratio) en float. Ne lève jamais d'exception."""
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        return float(value.num) / float(value.den)
    except (AttributeError, ZeroDivisionError, TypeError, ValueError):
        return None


def _dms_to_decimal(dms: Any) -> Optional[float]:
    """Convertit un triplet (degrés, minutes, secondes) GPS - chaque
    composante potentiellement rationnelle - en degrés décimaux. Ne lève
    jamais d'exception ; renvoie None si le triplet est inexploitable."""
    try:
        degrees, minutes, seconds = dms
    except (TypeError, ValueError):
        return None
    d = _rational_to_float(degrees)
    m = _rational_to_float(minutes)
    s = _rational_to_float(seconds)
    if d is None or m is None or s is None:
        return None
    return d + m / 60.0 + s / 3600.0


def _gps_from_pil_ifd(gps_ifd: Any) -> Optional[tuple[float, float]]:
    if not gps_ifd:
        return None
    try:
        lat = _dms_to_decimal(gps_ifd.get(_GPS_TAG_LAT))
        lon = _dms_to_decimal(gps_ifd.get(_GPS_TAG_LON))
        if lat is None or lon is None:
            return None
        lat_ref = gps_ifd.get(_GPS_TAG_LAT_REF)
        lon_ref = gps_ifd.get(_GPS_TAG_LON_REF)
        if lat_ref and str(lat_ref).upper().startswith("S"):
            lat = -lat
        if lon_ref and str(lon_ref).upper().startswith("W"):
            lon = -lon
        return (lat, lon)
    except Exception:
        return None


def _fill_from_pil(path: Path, metadata: dict) -> None:
    """Remplit `metadata` (en place) à partir des tags EXIF d'une image
    standard (JPEG/PNG/TIFF...) lue par Pillow. Toute métadonnée absente
    ou mal formée est simplement omise - jamais d'exception propagée."""
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return

            make = exif.get(_EXIF_TAG_MAKE)
            model = exif.get(_EXIF_TAG_MODEL)
            camera = _combine_camera(
                str(make).strip() if make else None,
                str(model).strip() if model else None,
            )
            if camera:
                metadata["camera"] = camera

            # Objectif, focale, ouverture, vitesse, ISO vivent tous dans le
            # sous-IFD Exif (0x8769), jamais dans l'IFD0 principal - comme
            # DateTimeOriginal (voir get_exif_date() ci-dessus).
            exif_ifd = exif.get_ifd(_EXIF_IFD_EXIF)

            lens = exif_ifd.get(_EXIF_TAG_LENS_MODEL)
            if lens and str(lens).strip():
                metadata["lens"] = str(lens).strip()

            focal = _rational_to_float(exif_ifd.get(_EXIF_TAG_FOCAL_LENGTH))
            if focal is not None:
                metadata["focal_length"] = focal

            focal_35mm = exif_ifd.get(_EXIF_TAG_FOCAL_LENGTH_35MM)
            if isinstance(focal_35mm, (int, float)) and not isinstance(focal_35mm, bool):
                metadata["focal_35mm"] = int(focal_35mm)

            aperture = _rational_to_float(exif_ifd.get(_EXIF_TAG_FNUMBER))
            if aperture is not None:
                metadata["aperture"] = aperture

            shutter = _rational_to_float(exif_ifd.get(_EXIF_TAG_EXPOSURE_TIME))
            if shutter is not None:
                metadata["shutter_speed"] = shutter

            iso = exif_ifd.get(_EXIF_TAG_ISO)
            if isinstance(iso, (list, tuple)) and iso:
                iso = iso[0]
            if isinstance(iso, (int, float)) and not isinstance(iso, bool):
                metadata["iso"] = int(iso)

            gps = _gps_from_pil_ifd(exif.get_ifd(_EXIF_IFD_GPSINFO))
            if gps is not None:
                metadata["gps"] = gps
    except Exception as e:
        logging.getLogger(__name__).debug(f"Métadonnées EXIF illisibles pour {path.name} : {e}")


def _exifread_str(tags: dict, key: str) -> Optional[str]:
    tag = tags.get(key)
    if tag is None:
        return None
    text = str(tag).strip()
    return text or None


def _exifread_rational(tags: dict, key: str) -> Optional[float]:
    tag = tags.get(key)
    if tag is None:
        return None
    try:
        value = tag.values[0]
        return _rational_to_float(value)
    except (AttributeError, IndexError, TypeError):
        return _rational_to_float(str(tag))


def _exifread_int(tags: dict, key: str) -> Optional[int]:
    tag = tags.get(key)
    if tag is None:
        return None
    try:
        value = tag.values[0]
        return int(value)
    except (AttributeError, IndexError, TypeError, ValueError):
        try:
            return int(str(tag))
        except (TypeError, ValueError):
            return None


def _gps_from_exifread(tags: dict) -> Optional[tuple[float, float]]:
    lat_tag = tags.get("GPS GPSLatitude")
    lon_tag = tags.get("GPS GPSLongitude")
    if lat_tag is None or lon_tag is None:
        return None
    try:
        lat = _dms_to_decimal(lat_tag.values)
        lon = _dms_to_decimal(lon_tag.values)
        if lat is None or lon is None:
            return None
        lat_ref = _exifread_str(tags, "GPS GPSLatitudeRef")
        lon_ref = _exifread_str(tags, "GPS GPSLongitudeRef")
        if lat_ref and lat_ref.upper().startswith("S"):
            lat = -lat
        if lon_ref and lon_ref.upper().startswith("W"):
            lon = -lon
        return (lat, lon)
    except Exception:
        return None


def _fill_from_exifread(path: Path, metadata: dict) -> None:
    """Équivalent de _fill_from_pil() pour les fichiers RAW, via exifread
    (Pillow seul ne décode pas les RAW - voir rawloader.py). Toute
    métadonnée absente ou mal formée est simplement omise."""
    if not EXIFREAD_AVAILABLE:
        return
    try:
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)

        camera = _combine_camera(
            _exifread_str(tags, "Image Make"), _exifread_str(tags, "Image Model"),
        )
        if camera:
            metadata["camera"] = camera

        lens = _exifread_str(tags, "EXIF LensModel")
        if lens:
            metadata["lens"] = lens

        focal = _exifread_rational(tags, "EXIF FocalLength")
        if focal is not None:
            metadata["focal_length"] = focal

        focal_35mm = _exifread_int(tags, "EXIF FocalLengthIn35mmFilm")
        if focal_35mm is not None:
            metadata["focal_35mm"] = focal_35mm

        aperture = _exifread_rational(tags, "EXIF FNumber")
        if aperture is not None:
            metadata["aperture"] = aperture

        shutter = _exifread_rational(tags, "EXIF ExposureTime")
        if shutter is not None:
            metadata["shutter_speed"] = shutter

        iso = _exifread_int(tags, "EXIF ISOSpeedRatings")
        if iso is not None:
            metadata["iso"] = iso

        gps = _gps_from_exifread(tags)
        if gps is not None:
            metadata["gps"] = gps
    except Exception as e:
        logging.getLogger(__name__).debug(f"Métadonnées EXIF (RAW) illisibles pour {path.name} : {e}")


def get_exif_metadata(path: Path) -> dict:
    """Extrait un ensemble large de métadonnées EXIF d'UNE photo (RAW
    compris), pour les légendes personnalisables par photo (cahier des
    charges §1). Les clés du dictionnaire renvoyé correspondent EXACTEMENT
    à portfolio.presentation.profile.CAPTION_FIELDS, pour un usage direct
    par portfolio/presentation/captions.py :

        filename (str), datetime (datetime), camera (str), lens (str),
        focal_length (float, mm), focal_35mm (int, mm équivalent 24x36),
        aperture (float, f/N), shutter_speed (float, secondes), iso (int),
        dimensions (tuple[int, int]), gps (tuple[float, float] - latitude/
        longitude décimales SIGNÉES, positif = Nord/Est).

    Ne lève JAMAIS d'exception et ne garantit la présence d'AUCUNE clé
    autre que "filename" : toute métadonnée absente, illisible ou mal
    formée vaut simplement None - jamais une génération interrompue pour
    une photo dont certaines métadonnées manquent (cahier des charges §1).

    Les valeurs renvoyées restent BRUTES (nombres, tuples) : leur mise en
    forme textuelle (unités, arrondis, gabarit personnalisé par
    l'utilisateur) est du ressort de portfolio/presentation/captions.py,
    jamais de cette fonction - même séparation extraction/formatage que le
    reste du module (voir apply_watermark() ci-dessus pour le rendu, par
    opposition à get_exif_date() pour l'extraction).

    Note de performance : cette fonction réutilise get_exif_date() et
    rawloader.get_original_dimensions() (chacun déjà utilisé ailleurs dans
    le projet) plutôt que de dupliquer leur logique, au prix de plusieurs
    lectures d'en-tête du même fichier - un compromis déjà présent avant
    cette fonction (ces deux lectures existaient déjà séparément) et sans
    impact mesurable : ce sont des lectures de MÉTADONNÉES seules, jamais
    un décodage complet de l'image."""
    path = Path(path)
    metadata: dict = {"filename": path.name, "datetime": get_exif_date(path)}

    if is_raw_file(path):
        _fill_from_exifread(path, metadata)
    else:
        _fill_from_pil(path, metadata)

    dimensions = get_original_dimensions(path)
    if dimensions is not None:
        metadata["dimensions"] = dimensions

    return metadata


def format_file_size(num_bytes: int) -> str:
    """Taille de fichier lisible (ex: "4,2 Mo" en français, "4.2 MB" en
    anglais), utilisée pour les informations affichées dans la
    visionneuse de la galerie HTML. Unité ET séparateur décimal suivent
    la langue active (`portfolio.i18n`, pilotée par --language/l'onglet
    "À propos") - ce calcul a lieu APRÈS la génération de la galerie
    HTML elle-même (voir htmlgallery.py), donc la langue active à cet
    instant est toujours la bonne."""
    from .i18n import _, get_language

    size = float(num_bytes)
    decimal_separator = "," if get_language() != "en" else "."
    for key in ("unit.bytes", "unit.kb", "unit.mb", "unit.gb"):
        if size < 1024 or key == "unit.gb":
            unit = _(key)
            if key == "unit.bytes":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}".replace(".", decimal_separator)
        size /= 1024
    return f"{size:.1f} {_('unit.gb')}".replace(".", decimal_separator)
