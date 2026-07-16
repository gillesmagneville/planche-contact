from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    input_dir: Path
    output_dir: Path

    # Scan options
    recursive: bool = False
    sort_by: str = "date"

    # Generation options
    num_per_sheet: int = 12
    thumb_size: int = 420
    page_format: str = "A4"
    background_color: str = "white"

    # Export options
    generate_pdf: bool = False
    generate_html: bool = False
    generate_csv: bool = False
    html_images_per_page: int = 48

    # Header
    title: Optional[str] = None
    author: Optional[str] = None

    # Watermark
    watermark_text: Optional[str] = None
    watermark_orientation: str = "Horizontal"
    watermark_opacity: int = 70
