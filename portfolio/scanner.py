import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from .config import Config
from .rawloader import is_raw_file

try:
    import exifread
    EXIFREAD_AVAILABLE = True
except ImportError:
    EXIFREAD_AVAILABLE = False


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

    def _get_exif_date(self, path: Path) -> Any:
        """Extrait la date EXIF la plus pertinente, RAW compris."""
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
        return None

    def _get_sort_key(self, path: Path) -> Any:
        """Retourne une clé de tri (date EXIF si disponible, sinon date de modification)."""
        if self.config.sort_by == "name":
            return path.name.lower()

        exif_date = self._get_exif_date(path)
        if exif_date is not None:
            return exif_date

        # Fallback : date de modification du fichier
        try:
            return datetime.fromtimestamp(path.stat().st_mtime)
        except Exception:
            return datetime.min

    def _is_within(self, path: Path, ancestor: Path) -> bool:
        try:
            path.relative_to(ancestor)
            return True
        except ValueError:
            return False

    def scan(self) -> list[dict]:
        images = []
        pattern = "**/*" if self.config.recursive else "*"

        self.logger.info(f"Scan du dossier : {self.config.input_dir} (récursif={self.config.recursive})")

        # Sous-dossiers générés par une exécution précédente (planches/,
        # gallery/) à exclure du scan : sinon, une nouvelle génération en
        # mode récursif - en particulier quand le dossier de sortie est
        # imbriqué dans le dossier d'entrée, ou identique à lui - retrouve
        # et retraite ses propres images déjà générées. portfolio.pdf et
        # index.csv n'ont pas besoin d'exclusion équivalente : leur
        # extension ne correspond à aucun format image pris en charge.
        excluded_dirs = []
        output_dir = getattr(self.config, "output_dir", None)
        if output_dir:
            try:
                output_dir_resolved = Path(output_dir).resolve()
                excluded_dirs = [
                    output_dir_resolved / "planches",
                    output_dir_resolved / "gallery",
                ]
            except Exception:
                excluded_dirs = []

        skipped_output = 0
        for path in self.config.input_dir.glob(pattern):
            if not path.is_file() or not self._is_image_file(path):
                continue

            if excluded_dirs:
                resolved_path = path.resolve()
                if any(self._is_within(resolved_path, excl) for excl in excluded_dirs):
                    skipped_output += 1
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

        if skipped_output:
            self.logger.info(
                f"{skipped_output} fichier(s) ignoré(s) car situé(s) dans le dossier "
                f"de sortie (planches/gallery d'une génération précédente)."
            )
        self.logger.info(f"{len(images)} images trouvées et triées.")
        return images
