from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

from .presentation import Profile, LayoutSettings, default_profile


@dataclass
class Config:
    input_dir: Path
    output_dir: Path

    # Scan options
    recursive: bool = False
    # Subfolders to process (POSIX paths relative to input_dir, "." = the
    # input folder itself): only the photos located DIRECTLY in these folders
    # are kept. None (default) = all photos, the historical behaviour.
    # Choosing subfolders forces a recursive search (see ImageScanner.scan()).
    # The list of possible folders comes from scanner.list_image_folders().
    include_dirs: Optional[tuple] = None
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
    # Attaches the ORIGINAL files (full resolution, copied as-is, RAW
    # included) to the HTML gallery so that the viewer's download button
    # gives the photo as shot, not the reduced copy (2000 px) shown on
    # screen. Off by default: the gallery would then weigh as much as the
    # source folder, and these originals carry neither the watermark nor
    # any edit (see htmlgallery.py).
    html_include_originals: bool = False

    # Header
    title: Optional[str] = None
    author: Optional[str] = None

    # Watermark
    watermark_text: Optional[str] = None
    watermark_orientation: str = "Horizontal"
    watermark_opacity: int = 40

    # Custom layout / captions / theme (specification §1/§2/§4) - a default
    # Profile (default_profile()) reproduces the current behaviour exactly
    # (simple grid, no captions, "light" theme). See
    # portfolio/presentation/profile.py.
    profile: Profile = field(default_factory=default_profile)

    def __post_init__(self):
        # Backward-compatible synchronisation: page_format and num_per_sheet
        # are the historical "simple" settings, already exposed by the
        # command line and the graphical interface long before a Profile
        # existed. For any caller that does not supply an explicit Profile
        # (all the callers that existed before this feature), self.profile is a
        # freshly created default_profile() whose layout.page_format/per_page
        # still hold the LayoutSettings defaults (A4/12): they are aligned here
        # with the "simple" settings actually requested, so that the geometry
        # is computed exactly as before the Profile was introduced.
        #
        # If an EXPLICIT Profile was supplied (e.g. --profile, a later step)
        # and it already defines a format or a number per sheet DIFFERENT from
        # the LayoutSettings defaults, it is NOT overwritten: the more specific
        # profile then prevails - the exact priority between a --profile and a
        # --format/--num supplied AT THE SAME TIME remains to be decided when
        # this feature is wired into the CLI/graphical interface (a later
        # step), not here.
        default_layout = LayoutSettings()
        overrides = {}
        if (self.profile.layout.page_format == default_layout.page_format
                and self.page_format != default_layout.page_format):
            overrides["page_format"] = self.page_format
        if (self.profile.layout.per_page == default_layout.per_page
                and self.num_per_sheet != default_layout.per_page):
            overrides["per_page"] = self.num_per_sheet
        if overrides:
            self.profile = replace(self.profile, layout=replace(self.profile.layout, **overrides))
