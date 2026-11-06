import functools
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from PIL import Image, ImageDraw, ImageFont

from .i18n import _
from .rawloader import is_raw_file, get_original_dimensions

try:
    import exifread
    EXIFREAD_AVAILABLE = True
except ImportError:
    EXIFREAD_AVAILABLE = False


#: Name of the developer cited in the "Developed by {name}, under the
#: GNU GPL v3 licence" credits (footer of the contact sheets/PDF, of the HTML
#: gallery and the "About" tab) - defined here only once.
AUTHOR_NAME = "Gilles MAGNEVILLE"


def setup_logging(log_path: Path) -> None:
    """Configures logging (file + console)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


# Font bundled with the project (portfolio/fonts/, Bitstream Vera licence
# - see portfolio/fonts/LICENSE.txt), used first: guarantees strictly
# identical rendering on all platforms, rather than depending on a system
# font found at a guessable path (e.g. C:/Windows/Fonts/arial.ttf), which
# may fail silently depending on the machine and fall back to Pillow's
# tiny built-in font.
_BUNDLED_FONTS_DIR = Path(__file__).parent / "fonts"


@functools.lru_cache(maxsize=32)
def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """
    Loads a TrueType font in a cross-platform way.
    Returns the default font if no system font is found.
    Cached: avoids re-reading/re-parsing the font file on every call
    (hundreds of times on a gallery of hundreds of photos with a
    watermark).
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
    Tiled, repeated watermark, used identically by the contact sheets (and
    therefore the PDF, which reuses those same images) and the HTML
    gallery - a single implementation, to guarantee strictly identical
    rendering everywhere.

    `opacity` is a percentage (0-100), converted here into an alpha channel
    (0-255).
    """
    if not text:
        return image

    # Automatic addition of the copyright symbol (behaviour of both
    # original implementations, kept here).
    if not text.startswith("©"):
        text = "© " + text

    try:
        img = image.convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        font = get_font(14, bold=True)

        alpha = max(0, min(255, int(255 * (opacity / 100))))
        text_color = (255, 255, 255, alpha)

        # Orientation handling. PIL rotates counter-clockwise for a positive
        # angle: "clockwise" therefore corresponds to a negative angle, and
        # vice versa.
        if orientation == "Diagonale horaire":
            angle = -32
        elif orientation == "Diagonale anti-horaire":
            angle = 32
        else:
            angle = 0

        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Spacing (identical to the sheets)
        x_spacing = text_width + 220
        y_spacing = text_height + 160

        for y in range(-text_height, img.height + text_height, y_spacing):
            for x in range(-text_width, img.width + text_width, x_spacing):
                offset_x = (y // y_spacing) * 50 if angle != 0 else 0
                draw.text((x + offset_x, y), text, font=font, fill=text_color)

        # Rotate if needed
        if angle != 0:
            overlay = overlay.rotate(angle, resample=Image.BICUBIC, expand=False, center=(img.width / 2, img.height / 2))

        return Image.alpha_composite(img, overlay).convert("RGB")

    except Exception as e:
        logging.getLogger(__name__).warning(_("engine.warn_watermark_failed", error=e))
        return image


def get_exif_date(path: Path) -> Optional[datetime]:
    """Extracts the most relevant EXIF date (shooting date), RAW included.
    Centralised here: used both for sorting the photos (scanner.py) and for
    the information shown in the HTML gallery viewer (htmlgallery.py)."""
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
            # DateTimeOriginal (0x9003) and DateTimeDigitized (0x9004) live in the
            # Exif sub-IFD, never in the main IFD0: a direct exif.get() does not
            # find them, get_ifd() is needed. Only DateTime (0x0132, the file's
            # MODIFICATION date, less relevant than a shooting date) lives in IFD0.
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


#: Keys of the dictionary returned by get_exif_metadata() - match
#: EXACTLY portfolio.presentation.profile.CAPTION_FIELDS, for direct use
#: by portfolio/presentation/captions.py (lookup by field name, without
#: an intermediate mapping table).
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
    """Combines make + model into a single readable "camera" field,
    avoiding a repetition when the model already includes the make (e.g.
    Nikon often reports "NIKON D850" as Model, with Make being
    "NIKON CORPORATION")."""
    make = make.strip() if make else None
    model = model.strip() if model else None
    if make and model:
        if model.lower().startswith(make.lower().split()[0].lower()):
            return model
        return f"{make} {model}"
    return make or model


def _rational_to_float(value: Any) -> Optional[float]:
    """Converts a potentially rational EXIF value (Pillow's IFDRational, an
    already decimal number, or any object exposing .num/.den such as
    exifread.utils.Ratio) to a float. Never raises an exception."""
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        return float(value.num) / float(value.den)
    except (AttributeError, ZeroDivisionError, TypeError, ValueError):
        return None


def _dms_to_decimal(dms: Any) -> Optional[float]:
    """Converts a GPS (degrees, minutes, seconds) triplet - each component
    potentially rational - to decimal degrees. Never raises an exception;
    returns None if the triplet is unusable."""
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
    """Fills `metadata` (in place) from the EXIF tags of a standard image
    (JPEG/PNG/TIFF...) read by Pillow. Any missing or malformed metadata is
    simply omitted - no exception is ever propagated."""
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

            # Lens, focal length, aperture, shutter speed and ISO all live in the
            # Exif sub-IFD (0x8769), never in the main IFD0 - like
            # DateTimeOriginal (see get_exif_date() above).
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
        logging.getLogger(__name__).debug(f"EXIF metadata unreadable for {path.name}: {e}")


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
    """Equivalent of _fill_from_pil() for RAW files, via exifread
    (Pillow alone does not decode RAW - see rawloader.py). Any missing or
    malformed metadata is simply omitted."""
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
        logging.getLogger(__name__).debug(f"EXIF metadata (RAW) unreadable for {path.name}: {e}")


def get_exif_metadata(path: Path) -> dict:
    """Extracts a wide set of EXIF metadata from ONE photo (RAW
    included), for the per-photo customisable captions (specification §1).
    The keys of the returned dictionary match EXACTLY
    portfolio.presentation.profile.CAPTION_FIELDS, for direct use
    by portfolio/presentation/captions.py:

        filename (str), datetime (datetime), camera (str), lens (str),
        focal_length (float, mm), focal_35mm (int, mm 24x36 equivalent),
        aperture (float, f/N), shutter_speed (float, seconds), iso (int),
        dimensions (tuple[int, int]), gps (tuple[float, float] - SIGNED
        decimal latitude/longitude, positive = North/East).

    NEVER raises an exception and does not guarantee the presence of ANY key
    other than "filename": any missing, unreadable or malformed metadata is
    simply None - never a generation interrupted for a photo with some
    metadata missing (specification §1).

    The returned values stay UNPROCESSED (numbers, tuples): their textual
    formatting (units, rounding, user-defined template) is the job of
    portfolio/presentation/captions.py, never of this function - the same
    extraction/formatting separation as the rest of the module (see
    apply_watermark() above for rendering, as opposed to get_exif_date() for
    extraction).

    Performance note: this function reuses get_exif_date() and
    rawloader.get_original_dimensions() (each already used elsewhere in the
    project) rather than duplicating their logic, at the cost of several
    header reads of the same file - a trade-off that already existed before
    this function (those two reads already existed separately) and with no
    measurable impact: they are METADATA-only reads, never a full decode of
    the image."""
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
    """Human-readable file size (e.g. "4,2 Mo" in French, "4.2 MB" in
    English), used for the information shown in the HTML gallery viewer.
    Unit AND decimal separator follow the active language
    (`portfolio.i18n`, driven by --language/the "About" tab) - this
    computation happens AFTER the HTML gallery itself is generated (see
    htmlgallery.py), so the active language at that moment is always the
    right one."""
    from .i18n import get_language

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
