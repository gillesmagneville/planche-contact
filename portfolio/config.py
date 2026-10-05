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
    # Joint à la galerie HTML les fichiers ORIGINAUX (pleine résolution,
    # copiés tels quels, RAW compris) pour que le bouton de téléchargement
    # de la visionneuse donne la photo de la prise de vue, et non la copie
    # réduite (2000 px) affichée à l'écran. Désactivé par défaut : la
    # galerie pèse alors autant que le dossier source, et ces originaux ne
    # portent ni le filigrane ni aucune retouche (voir htmlgallery.py).
    html_include_originals: bool = False

    # Header
    title: Optional[str] = None
    author: Optional[str] = None

    # Watermark
    watermark_text: Optional[str] = None
    watermark_orientation: str = "Horizontal"
    watermark_opacity: int = 40

    # Mise en page / légendes / thème personnalisés (cahier des charges
    # §1/§2/§4) - un Profil par défaut (default_profile()) reproduit
    # exactement le comportement actuel (grille simple, pas de légende,
    # thème "light"). Voir portfolio/presentation/profile.py.
    profile: Profile = field(default_factory=default_profile)

    def __post_init__(self):
        # Synchronisation rétrocompatible : page_format et num_per_sheet
        # sont les réglages "simples" historiques, déjà exposés par la
        # ligne de commande et l'interface graphique, bien avant
        # l'existence d'un Profil. Pour tout appelant qui ne fournit pas
        # de Profil explicite (la totalité des appelants existants avant
        # cette fonctionnalité), self.profile est un default_profile()
        # fraîchement créé dont layout.page_format/per_page valent encore
        # les valeurs par défaut de LayoutSettings (A4/12) : on les aligne
        # ici sur les réglages "simples" réellement demandés, pour un
        # calcul de géométrie identique à avant l'introduction du Profil.
        #
        # Si un Profil EXPLICITE a été fourni (ex : --profile, étape
        # ultérieure) et qu'il définit déjà un format ou un nombre par
        # planche DIFFÉRENT des valeurs par défaut de LayoutSettings, on
        # ne l'écrase PAS : c'est alors le profil, plus spécifique, qui
        # prévaut - la question de la priorité exacte entre un --profile
        # et un --format/--num explicitement fournis EN MÊME TEMPS reste
        # à trancher lors du câblage CLI/interface graphique de cette
        # fonctionnalité (étape ultérieure), pas ici.
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
