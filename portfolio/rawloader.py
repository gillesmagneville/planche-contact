"""
rawloader.py - Unified loading of images, RAW included.

Pillow alone cannot decode RAW files (.cr2, .cr3, .nef, .dng, .arw...).
This module provides a single entry point (`load_image`) used everywhere
in the application (thumbnails, contact sheets, HTML gallery) to load an
image file, whether it is a standard format (JPEG, PNG, TIFF...) or a RAW
format.

Strategy for RAW files:
1. We try to extract the thumbnail/JPEG preview embedded in the RAW file
   (almost instant, sufficient for thumbnails and contact sheets).
2. If no preview is available, or if it is too small for the requested
   use (see `target_size`), a full demosaicing is performed via LibRaw
   (much slower: of the order of a second per photo, against a few tens
   of milliseconds for the embedded preview).

The (optional) `target_size` parameter serves two performance-related
purposes:
- For a standard JPEG, it enables Pillow's "draft" decoding, which relies
  on a JPEG's native scaling (factors 1/2, 1/4, 1/8) to decode a smaller
  image directly, without ever decoding the full resolution and then
  resizing. Typical gain: several times faster on large JPEG photos.
- For a RAW, it determines whether the embedded preview (fast) is large
  enough for the requested use; otherwise, we fall back to full
  demosaicing.
"""

import io
import logging
from pathlib import Path

from PIL import Image

from .i18n import _

logger = logging.getLogger(__name__)

RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".dng", ".arw"}

try:
    import rawpy
    RAWPY_AVAILABLE = True
except ImportError:
    RAWPY_AVAILABLE = False
    logger.warning(
        "Le module 'rawpy' n'est pas installé : les fichiers RAW "
        "(.cr2, .cr3, .nef, .dng, .arw) ne pourront pas être traités."
    )


def is_raw_file(path: Path) -> bool:
    return Path(path).suffix.lower() in RAW_EXTENSIONS


def get_original_dimensions(path: Path):
    """Real resolution of the source file (width, height), with the EXIF/RAW
    orientation applied to reflect what the user actually sees - used to
    display information in the HTML gallery viewer (see htmlgallery.py).
    Always a metadata-only read (JPEG/TIFF header, or `rawpy.sizes` for a
    RAW): never a full decode, hence fast even on several hundred photos.

    Returns None if reading fails (corrupted file, unsupported format...) -
    it is up to the caller to handle the absence of a result.
    """
    path = Path(path)
    try:
        if is_raw_file(path):
            if not RAWPY_AVAILABLE:
                return None
            with rawpy.imread(str(path)) as raw:
                width, height = raw.sizes.width, raw.sizes.height
                # raw.sizes.flip is LibRaw's rotation code (0 = none, 3 = 180°,
                # 5/6 = 90° one way or the other): width/height stay in the sensor's
                # NATIVE orientation, to be swapped for 90° rotations.
                if raw.sizes.flip in (5, 6):
                    width, height = height, width
                return (width, height)

        with Image.open(path) as img:
            width, height = img.size
            exif = img.getexif()
            orientation = exif.get(0x0112)  # EXIF Orientation tag
            if orientation in (5, 6, 7, 8):
                width, height = height, width
            return (width, height)
    except Exception as e:
        logger.debug(f"Dimensions d'origine illisibles pour {path.name} : {e}")
        return None


def _large_enough(img_size, target_size, tolerance=0.9, fill=False):
    """True if img_size covers at least ~tolerance times the longest side
    requested. A small margin is tolerated: an embedded preview very
    slightly smaller than the target remains far preferable, in speed, to a
    full demosaicing for an imperceptible difference.

    `fill`: the thumbnail will be CROPPED to fill its whole cell ("cover"
    fit mode, see thumbnail.fit_thumbnail_image()) - it is then the SHORT
    side of the preview that must reach the target, not the long one: a 4:3
    preview whose long side alone would suffice would leave a cropped square
    smaller than its cell."""
    side = min(img_size) if fill else max(img_size)
    return side >= max(target_size) * tolerance


def _load_raw(path: Path, use_embedded_thumb: bool = True, target_size=None, fill: bool = False,
              min_ratio: float = 0.9) -> Image.Image:
    """Loads a RAW file and returns a PIL image in RGB mode.
    `min_ratio`: share of `target_size` that the embedded preview must
    cover to be accepted (see _large_enough())."""
    if not RAWPY_AVAILABLE:
        raise RuntimeError(_("engine.raw_module_missing", name=path.name))

    with rawpy.imread(str(path)) as raw:
        if use_embedded_thumb:
            try:
                thumb = raw.extract_thumb()
                img = None
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    img = Image.open(io.BytesIO(thumb.data))
                    if target_size is not None:
                        try:
                            img.draft("RGB", target_size)
                        except Exception:
                            pass
                    img.load()
                    img = img.convert("RGB")
                elif thumb.format == rawpy.ThumbFormat.BITMAP:
                    img = Image.fromarray(thumb.data).convert("RGB")

                if img is not None:
                    if target_size is None or _large_enough(img.size, target_size, tolerance=min_ratio, fill=fill):
                        return img
                    # Preview too small for the requested use: we continue below
                    # to a full demosaicing.
            except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
                pass
            except Exception as e:
                logger.debug(f"Aperçu embarqué inutilisable pour {path.name} : {e}")

        # No usable preview (or too small): full demosaicing.
        rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False, output_bps=8)
        return Image.fromarray(rgb)


def load_image(path: Path, use_embedded_thumb: bool = True, target_size=None, fill: bool = False) -> Image.Image:
    """
    Single entry point to load any image (RAW or standard).
    Always returns a PIL image in RGB mode. Raises an exception on failure
    (it is up to the caller to log/ignore).

    target_size: optional tuple (max_width, max_height) giving the
    approximate final size wanted. Supplying this information when it is
    known significantly speeds up decoding (see the module docstring); it
    has no effect on the final result if the caller resizes afterwards
    anyway (thumbnail(), etc.) - it is a pure speed optimisation.

    fill: set to True when the caller is going to CROP the image to fill a
    `target_size` area (thumbnail in "cover" mode) rather than fit it
    inside: an embedded RAW preview is then judged large enough only if its
    short side reaches the target (see _large_enough()). No effect for
    non-RAW images.
    """
    path = Path(path)
    if is_raw_file(path):
        return _load_raw(path, use_embedded_thumb=use_embedded_thumb, target_size=target_size, fill=fill)

    with Image.open(path) as img:
        if target_size is not None:
            try:
                img.draft("RGB", target_size)
            except Exception:
                pass
        img.load()
        return img


#: Share of the sensor resolution that an embedded JPEG preview must
#: cover to serve as the "full-size" image (see load_full_resolution()):
#: almost exact, unlike the 90% tolerance of the thumbnails - a preview
#: noticeably smaller than the shot is not the complete photo.
FULL_RESOLUTION_PREVIEW_MIN_RATIO = 0.98


def load_full_resolution(path: Path) -> Image.Image:
    """Image at the FULL resolution of the shot, in RGB - to produce a
    downloadable JPEG file from a RAW (HTML gallery, "full-size originals"
    option), unlike load_image() which settles for an image "large enough
    for the requested use".

    Non-RAW file: identical to load_image(). RAW: the embedded JPEG preview
    if it covers at least FULL_RESOLUTION_PREVIEW_MIN_RATIO of the sensor
    resolution (it is the camera's own rendering, and extraction is almost
    instant - many cameras store a full-size image there); otherwise, full
    demosaicing. Raises an exception on failure (rawpy missing, unreadable
    file...): never falls back to a smaller preview, which would be
    presented as the original."""
    path = Path(path)
    if not is_raw_file(path):
        return load_image(path)
    dimensions = get_original_dimensions(path)
    return _load_raw(
        path,
        # Sensor resolution unknown: impossible to judge the preview,
        # full demosaicing.
        use_embedded_thumb=dimensions is not None,
        target_size=dimensions,
        min_ratio=FULL_RESOLUTION_PREVIEW_MIN_RATIO,
    )
