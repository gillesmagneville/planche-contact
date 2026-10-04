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


def fit_thumbnail_image(img, max_size: int, fit_mode: str = "contain"):
    """Réduit `img` pour une cellule carrée de `max_size` pixels de côté,
    selon le mode d'ajustement du Profil (LayoutSettings.fit_mode).

    - "contain" (défaut, comportement d'origine) : la photo ENTIÈRE, avec
      ses proportions, inscrite dans la cellule (`Image.thumbnail`) - la
      vignette n'est donc pas carrée sauf si la photo l'est.
    - "cover" : la photo est RECADRÉE au centre en carré pour remplir
      toute la cellule, aucune marge vide.

    Dans les deux modes, une image plus petite que la cellule n'est JAMAIS
    agrandie (même règle que `Image.thumbnail`) : en "cover", une photo
    dont le petit côté est inférieur à `max_size` donne un carré plus
    petit que la cellule, que contactsheet.py place ensuite dans sa
    cellule (voir _thumb_offset()). Toute valeur de `fit_mode` inconnue se
    comporte comme "contain" - jamais d'exception pour un profil modifié
    à la main.

    Fonction pure (une image PIL en entrée, une en sortie), partagée par la
    version unitaire et par la version parallèle (workers `spawn`) de
    ThumbnailGenerator - une seule règle de recadrage, jamais deux."""
    if fit_mode == "cover":
        short_side = min(img.width, img.height)
        if short_side > max_size:
            # Petit côté ramené à `max_size` ; max() garde l'arrondi de
            # l'autre côté de passer sous max_size (carré final incomplet).
            # reducing_gap=2.0 : même accélération que Image.thumbnail().
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
    """Fonction worker pour le multiprocessing."""
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
        logging.getLogger(__name__).warning(f"Vignette impossible pour {Path(image_path).name}: {e}")
        return None


class ThumbnailGenerator:
    def __init__(self, config):
        self.config = config

    def create_thumbnail(self, item, max_size: int, fit_mode: str = "contain"):
        """Version simple (pour usage unitaire)."""
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
            logging.getLogger(__name__).warning(f"Vignette impossible pour {Path(image_path).name}: {e}")
            return None

    def _get_path(self, item):
        if isinstance(item, dict):
            return item.get('path') or item.get('file_path')
        return item

    def generate_parallel(self, items, max_size: int, fit_mode: str = "contain"):
        """
        Génère les vignettes en parallèle avec des processus.
        Beaucoup plus rapide sur les gros dossiers.

        `fit_mode` : "contain" (photo entière, défaut) ou "cover" (photo
        recadrée en carré) - voir fit_thumbnail_image().
        """
        # Prépare les arguments
        tasks = []
        for item in items:
            path = self._get_path(item)
            if path:
                tasks.append((path, max_size, fit_mode))

        if not tasks:
            return []

        max_workers = min(os.cpu_count() or 4, 64)

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
