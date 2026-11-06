from PIL import Image, ImageOps
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import logging
import multiprocessing
import os
from functools import partial

from .i18n import _, get_language, set_language
from .rawloader import load_image


def _init_worker_logging(log_path, language=None):
    """Reconfigures logging in child processes (required with 'spawn',
    which does not share the parent process's configuration), and re-arms
    the active language there: a worker starts a new interpreter, in
    which the messages would otherwise come out in English."""
    if log_path:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.FileHandler(log_path, encoding="utf-8")],
            force=True,
        )
    if language:
        set_language(language)


def fit_thumbnail_image(img, max_size: int, fit_mode: str = "contain"):
    """Shrinks `img` for a square cell of `max_size` pixels per side,
    according to the Profile's fit mode (LayoutSettings.fit_mode).

    - "contain" (default, original behaviour): the WHOLE photo, with its
      proportions, fitted inside the cell (`Image.thumbnail`) - so the
      thumbnail is not square unless the photo is.
    - "cover": the photo is CROPPED to a centred square to fill the whole
      cell, with no empty margin.

    In both modes, an image smaller than the cell is NEVER enlarged (same
    rule as `Image.thumbnail`): in "cover", a photo whose short side is
    smaller than `max_size` gives a square smaller than the cell, which
    contactsheet.py then places in its cell (see _thumb_offset()). Any
    unknown `fit_mode` value behaves like "contain" - never an exception
    for a hand-edited profile.

    Pure function (one PIL image in, one out), shared by the single-image
    version and the parallel version (`spawn` workers) of
    ThumbnailGenerator - a single cropping rule, never two."""
    if fit_mode == "cover":
        short_side = min(img.width, img.height)
        if short_side > max_size:
            # Short side brought down to `max_size`; max() keeps the rounding of
            # the other side from dropping below max_size (incomplete final square).
            # reducing_gap=2.0: same speed-up as Image.thumbnail().
            scale = max_size / short_side
            img = img.resize(
                (max(max_size, round(img.width * scale)), max(max_size, round(img.height * scale))),
                Image.Resampling.LANCZOS,
                reducing_gap=2.0,
            )
        side = min(img.width, img.height)
        left = (img.width - side) // 2
        top = (img.height - side) // 2
        return img.crop((left, top, left + side, top + side))

    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return img


def _process_single_thumbnail(args):
    """Worker function for multiprocessing."""
    image_path, max_size, fit_mode = args
    try:
        img = load_image(
            image_path, use_embedded_thumb=True, target_size=(max_size, max_size),
            fill=(fit_mode == "cover"),
        )
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        return fit_thumbnail_image(img, max_size, fit_mode)
    except Exception as e:
        logging.getLogger(__name__).warning(_("engine.warn_thumbnail_failed", name=Path(image_path).name, error=e))
        return None


class ThumbnailGenerator:
    def __init__(self, config):
        self.config = config

    def create_thumbnail(self, item, max_size: int, fit_mode: str = "contain"):
        """Single-image version (for one-off use)."""
        image_path = self._get_path(item)
        if not image_path:
            return None
        try:
            img = load_image(
                image_path, use_embedded_thumb=True, target_size=(max_size, max_size),
                fill=(fit_mode == "cover"),
            )
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            return fit_thumbnail_image(img, max_size, fit_mode)
        except Exception as e:
            logging.getLogger(__name__).warning(_("engine.warn_thumbnail_failed", name=Path(image_path).name, error=e))
            return None

    def _get_path(self, item):
        if isinstance(item, dict):
            return item.get('path') or item.get('file_path')
        return item

    def generate_parallel(self, items, max_size: int, fit_mode: str = "contain"):
        """
        Generates the thumbnails in parallel with processes.
        Much faster on large folders.

        `fit_mode`: "contain" (whole photo, default) or "cover" (photo
        cropped to a square) - see fit_thumbnail_image().
        """
        # Prepare the arguments
        tasks = []
        for item in items:
            path = self._get_path(item)
            if path:
                tasks.append((path, max_size, fit_mode))

        if not tasks:
            return []

        max_workers = min(os.cpu_count() or 4, 64)

        # 'spawn' rather than Linux's default 'fork': rawpy uses OpenMP
        # internally, and OpenMP + fork() can cause deadlocks (a warning
        # documented by rawpy itself).
        ctx = multiprocessing.get_context("spawn")
        log_path = None
        for handler in logging.getLogger().handlers:
            if isinstance(handler, logging.FileHandler):
                log_path = handler.baseFilename
                break

        results = []
        with ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=ctx,
            initializer=_init_worker_logging,
            initargs=(log_path, get_language()),
        ) as executor:
            # Map the worker function over the tasks
            for result in executor.map(_process_single_thumbnail, tasks):
                results.append(result)

        return results
