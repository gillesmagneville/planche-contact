import csv
from pathlib import Path

from .i18n import _

class CSVIndexGenerator:
    def create(self, images: list[dict], output_path: Path) -> None:
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([_("csv.header_num"), _("csv.header_filename")])
            for item in images:
                writer.writerow([item["num"], item["filename"]])
