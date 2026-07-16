import csv
from pathlib import Path

class CSVIndexGenerator:
    def create(self, images: list[dict], output_path: Path) -> None:
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Numéro", "Fichier"])
            for item in images:
                writer.writerow([item["num"], item["filename"]])
