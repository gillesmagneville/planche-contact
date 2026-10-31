import logging
import os
import posixpath
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from .config import Config
from .utils import get_exif_date
from .i18n import _


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

        exif_date = get_exif_date(path)
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

    def _included_dirs(self) -> Optional[frozenset]:
        """Sous-dossiers retenus (chemins relatifs normalisés, "." = le
        dossier d'entrée lui-même), ou None quand toutes les photos sont
        prises en compte (comportement historique). Une entrée hors du
        dossier d'entrée est ignorée avec un avertissement."""
        wanted = getattr(self.config, "include_dirs", None)
        if wanted is None:
            return None
        kept = set()
        for entry in wanted:
            relative = normalize_include_dir(self.config.input_dir, entry)
            if relative is None:
                self.logger.warning(_("engine.warn_include_dir_outside", dir=entry))
            else:
                kept.add(relative)
        return frozenset(kept)

    def scan(self) -> list[dict]:
        images = []
        # Choisir des sous-dossiers suppose de les parcourir : la recherche
        # est alors forcément récursive, même sans l'option -r.
        include_dirs = self._included_dirs()
        recursive = self.config.recursive or include_dirs is not None
        pattern = "**/*" if recursive else "*"

        self.logger.info(_("engine.log_scan_folder", dir=self.config.input_dir, recursive=recursive))
        if include_dirs is not None:
            self.logger.info(_("engine.log_include_dirs", count=len(include_dirs)))

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

            # Seules comptent les photos situées DIRECTEMENT dans un des
            # dossiers retenus (pas celles de leurs sous-dossiers : chacun
            # se coche séparément).
            if include_dirs is not None:
                try:
                    relative_parent = path.parent.relative_to(self.config.input_dir).as_posix()
                except ValueError:
                    continue
                if relative_parent not in include_dirs:
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
        self.logger.info(_("engine.log_images_found_sorted", count=len(images)))
        return images


def normalize_include_dir(input_dir: Path, entry) -> Optional[str]:
    """Chemin relatif POSIX de `entry` par rapport à `input_dir` ("." pour
    le dossier d'entrée lui-même), ou None s'il désigne un endroit hors de
    ce dossier. Accepte un chemin relatif (la forme produite par
    list_image_folders()) comme un chemin absolu situé sous `input_dir`."""
    candidate = Path(str(entry))
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(input_dir)
        except ValueError:
            try:
                candidate = candidate.resolve().relative_to(Path(input_dir).resolve())
            except (ValueError, OSError):
                return None
    relative = posixpath.normpath(candidate.as_posix() or ".")
    if relative == ".." or relative.startswith("../") or relative.startswith("/"):
        return None
    return relative


def list_image_folders(input_dir: Path, output_dir: Optional[Path] = None) -> list[tuple[str, int]]:
    """Dossiers de `input_dir` (lui-même compris) qui contiennent DIRECTEMENT
    au moins une photo prise en charge, avec leur nombre de photos :
    `[(chemin relatif POSIX, nombre)]`, "." (le dossier d'entrée) en tête,
    puis par ordre alphabétique. C'est la liste proposée à l'utilisateur
    pour choisir les sous-dossiers à traiter (Config.include_dirs).

    Mêmes exclusions que ImageScanner.scan() : les sous-dossiers `planches`
    et `gallery` du dossier de sortie (une génération précédente) ne sont
    jamais proposés. Seuls les noms de fichiers sont lus - ni EXIF ni
    ouverture d'image -, ce qui reste rapide sur de grosses photothèques."""
    input_dir = Path(input_dir)
    excluded = []
    if output_dir:
        try:
            output_resolved = Path(output_dir).resolve()
            excluded = [output_resolved / "planches", output_resolved / "gallery"]
        except OSError:
            excluded = []

    def is_excluded(folder: str) -> bool:
        for excluded_dir in excluded:
            try:
                if excluded_dir.exists() and os.path.samefile(folder, excluded_dir):
                    return True
            except OSError:
                continue
        return False

    extensions = ImageScanner.SUPPORTED_EXTENSIONS
    found: dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(input_dir):
        if excluded:
            dirnames[:] = [
                name for name in dirnames
                if not (name in ("planches", "gallery") and is_excluded(os.path.join(dirpath, name)))
            ]
        dirnames.sort(key=str.lower)
        count = sum(1 for name in filenames if Path(name).suffix.lower() in extensions)
        if count:
            relative = os.path.relpath(dirpath, input_dir).replace(os.sep, "/")
            found[relative] = count

    return sorted(found.items(), key=lambda item: (item[0] != ".", item[0].lower(), item[0]))
