import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from .config import Config


class ImageScanner:
    SUPPORTED_EXTENSIONS = {
        ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp",
        ".heic", ".heif", ".cr2", ".cr3", ".nef", ".dng", ".arw"
    }

    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)

    def _is_image_file(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def _get_sort_key(self, path: Path) -> Any:
        """Retourne une clé de tri (date EXIF si disponible, sinon date de modification)."""
        if self.config.sort_by == "name":
            return path.name.lower()

        try:
            with Image.open(path) as img:
                exif = img.getexif()

                # Priorité aux dates EXIF les plus pertinentes
                for tag in (0x9003, 0x9004, 0x0132):  # DateTimeOriginal, DateTimeDigitized, DateTime
                    date_str = exif.get(tag)
                    if date_str:
                        try:
                            return datetime.strptime(str(date_str), "%Y:%m:%d %H:%M:%S")
                        except ValueError:
                            continue
        except Exception:
            pass

        # Fallback : date de modification du fichier
        try:
            return datetime.fromtimestamp(path.stat().st_mtime)
        except Exception:
            return datetime.min

    def scan(self) -> list[dict]:
        images = []
        pattern = "**/*" if self.config.recursive else "*"

        self.logger.info(f"Scan du dossier : {self.config.input_dir} (récursif={self.config.recursive})")

        for path in self.config.input_dir.glob(pattern):
            if not path.is_file() or not self._is_image_file(path):
                continue

            try:
                sort_key = self._get_sort_key(path)
                images.append({
                    "path": path,
                    "filename": path.name,
                    "sort_key": sort_key,
                })
            except Exception as e:
                self.logger.warning(f"Impossible de traiter {path.name}: {e}")

        # Tri des images
        images.sort(key=lambda x: x["sort_key"])

        # Ajout d'un numéro séquentiel
        for i, item in enumerate(images, 1):
            item["num"] = f"{i:03d}"

        self.logger.info(f"{len(images)} images trouvées et triées.")
        return images
