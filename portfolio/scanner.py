import logging
import os
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

    def _is_within(self, path: Path, ancestor: Path, boundary: Path | None = None) -> bool:
        """Vrai si un des dossiers parents de `path` (jusqu'à `boundary`
        inclus, sans aller plus haut) est physiquement le même dossier que
        `ancestor`, en comparant l'identité réelle du fichier (via
        os.path.samefile) plutôt qu'une simple comparaison textuelle des
        chemins. Nécessaire notamment sous Windows : un lecteur réseau
        mappé (ex: Z:\\photos) et son équivalent en chemin UNC (ex:
        \\\\serveur\\partage\\photos) désignent le même dossier physique
        mais ont une représentation textuelle totalement différente, que
        Path.resolve() ne unifie pas - une comparaison purement textuelle
        laisse alors passer les fichiers déjà générés lors d'une exécution
        précédente.

        `boundary` (typiquement le dossier d'entrée scanné) arrête la
        remontée dès qu'elle en sort : samefile() fait un appel système par
        niveau, coûteux sur un partage réseau, et inutile au-delà du
        dossier d'entrée puisque aucun fichier candidat ne peut s'y
        trouver. La comparaison de frontière reste purement textuelle
        (elle ne sert qu'à optimiser, jamais à décider de l'exclusion) :
        en cas d'échec elle ne fait que remonter un peu plus haut, sans
        jamais compromettre la justesse du résultat.
        """
        if not ancestor.exists():
            return False
        for parent in path.parents:
            try:
                if os.path.samefile(parent, ancestor):
                    return True
            except OSError:
                continue
            if boundary is not None and parent == boundary:
                break
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

        try:
            input_dir_resolved = self.config.input_dir.resolve()
        except OSError:
            input_dir_resolved = None

        skipped_output = 0
        for path in self.config.input_dir.glob(pattern):
            if not path.is_file() or not self._is_image_file(path):
                continue

            if excluded_dirs:
                resolved_path = path.resolve()
                if any(
                    self._is_within(resolved_path, excl, input_dir_resolved)
                    for excl in excluded_dirs
                ):
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
