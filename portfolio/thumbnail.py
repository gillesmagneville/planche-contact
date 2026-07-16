from PIL import Image, ImageOps
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import os
from functools import partial


def _process_single_thumbnail(args):
    """Fonction worker pour le multiprocessing."""
    image_path, max_size = args
    try:
        with Image.open(image_path) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            return img
    except Exception:
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
            with Image.open(image_path) as img:
                img = ImageOps.exif_transpose(img)
                img = img.convert("RGB")
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                return img
        except Exception:
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

        results = []
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # On mappe la fonction worker sur les tâches
            for result in executor.map(_process_single_thumbnail, tasks):
                results.append(result)

        return results
