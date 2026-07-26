from PIL import Image, ImageOps
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import logging
import multiprocessing
import os
from functools import partial

from .rawloader import load_image


def _init_worker_logging(log_path):
    """Reconfigure le logging dans les processus enfants (nécessaire avec 'spawn',
    qui ne partage pas la configuration du processus parent)."""
    if log_path:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.FileHandler(log_path, encoding="utf-8")],
            force=True,
        )


def _process_single_thumbnail(args):
    """Fonction worker pour le multiprocessing."""
    image_path, max_size = args
    try:
        img = load_image(image_path, use_embedded_thumb=True, target_size=(max_size, max_size))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        return img
    except Exception as e:
        logging.getLogger(__name__).warning(f"Vignette impossible pour {Path(image_path).name}: {e}")
        return None


class ThumbnailGenerator:
    def __init__(self, config):
        self.config = config

    def create_thumbnail(self, item, max_size: int):
        """Version simple (pour usage unitaire)."""
        image_path = self._get_path(item)
        if not image_path:
            return None
        try:
            img = load_image(image_path, use_embedded_thumb=True, target_size=(max_size, max_size))
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            return img
        except Exception as e:
            logging.getLogger(__name__).warning(f"Vignette impossible pour {Path(image_path).name}: {e}")
            return None

    def _get_path(self, item):
        if isinstance(item, dict):
            return item.get('path') or item.get('file_path')
        return item

    def generate_parallel(self, items, max_size: int):
        """
        Génère les vignettes en parallèle avec des processus.
        Beaucoup plus rapide sur les gros dossiers.
        """
        # Prépare les arguments
        tasks = []
        for item in items:
            path = self._get_path(item)
            if path:
                tasks.append((path, max_size))

        if not tasks:
            return []

        max_workers = min(os.cpu_count() or 4, 8)

        # 'spawn' plutôt que le 'fork' par défaut sous Linux : rawpy utilise
        # OpenMP en interne, et OpenMP + fork() peut provoquer des deadlocks
        # (avertissement documenté par rawpy lui-même).
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
            initargs=(log_path,),
        ) as executor:
            # On mappe la fonction worker sur les tâches
            for result in executor.map(_process_single_thumbnail, tasks):
                results.append(result)

        return results
