# -*- coding: utf-8 -*-
"""
Tests de portfolio.utils.get_exif_metadata() - extraction des métadonnées
EXIF utilisées par les légendes personnalisables par photo (cahier des
charges §1, voir aussi tests/test_captions.py pour leur mise en forme).

Les images de test sont de vrais JPEG produits par Pillow, avec de vraies
métadonnées EXIF écrites via PIL.Image.Exif (IFD0 + sous-IFD Exif/GPS) -
pas des mocks - pour vérifier un véritable aller-retour d'écriture/lecture
EXIF, cohérent avec la culture de vérification empirique du projet.

Le chemin RAW (exifread) n'est, lui, vérifié ici que pour sa RÉSILIENCE
(fichier absent/corrompu ne doit jamais lever d'exception) : fabriquer un
vrai fichier RAW (.cr2/.nef/.dng...) avec des tags EXIF contrôlés
dépasserait largement la portée de ce module de test ; le mapping exact
des tags exifread (EXIF FocalLength, GPS GPSLatitude...) suit néanmoins
exactement la même logique que le chemin Pillow ci-dessous, déjà vérifié.
"""
from datetime import datetime

import pytest
from PIL import Image
from PIL.ExifTags import IFD

from portfolio.utils import get_exif_metadata


def _make_jpeg_with_exif(path, *, make=None, model=None, lens=None,
                          focal_length=None, focal_35mm=None, aperture=None,
                          shutter_speed=None, iso=None, date_original=None,
                          gps=None, size=(800, 600)):
    """Crée un JPEG de test avec les tags EXIF fournis - voir le docstring
    du module pour la justification de cette approche (vrais fichiers,
    pas de mocks)."""
    img = Image.new("RGB", size, (120, 80, 200))
    exif = Image.Exif()

    if make is not None:
        exif[0x010F] = make
    if model is not None:
        exif[0x0110] = model

    exif_ifd = exif.get_ifd(IFD.Exif)
    if lens is not None:
        exif_ifd[0xA434] = lens
    if focal_length is not None:
        exif_ifd[0x920A] = focal_length
    if focal_35mm is not None:
        exif_ifd[0xA405] = focal_35mm
    if aperture is not None:
        exif_ifd[0x829D] = aperture
    if shutter_speed is not None:
        exif_ifd[0x829A] = shutter_speed
    if iso is not None:
        exif_ifd[0x8827] = iso
    if date_original is not None:
        exif_ifd[0x9003] = date_original

    if gps is not None:
        lat, lon = gps
        gps_ifd = exif.get_ifd(IFD.GPSInfo)
        gps_ifd[1] = "N" if lat >= 0 else "S"
        gps_ifd[2] = _decimal_to_dms(abs(lat))
        gps_ifd[3] = "E" if lon >= 0 else "W"
        gps_ifd[4] = _decimal_to_dms(abs(lon))

    img.save(path, format="JPEG", exif=exif.tobytes())


def _decimal_to_dms(value):
    degrees = int(value)
    minutes_float = (value - degrees) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    return (float(degrees), float(minutes), float(seconds))


def test_filename_always_present(tmp_path):
    """filename est renseigné même pour une image sans aucun EXIF - jamais
    une clé manquante, contrairement aux autres champs."""
    path = tmp_path / "sans_exif.jpg"
    Image.new("RGB", (100, 100)).save(path, format="JPEG")

    metadata = get_exif_metadata(path)
    assert metadata["filename"] == "sans_exif.jpg"


def test_missing_metadata_fields_are_none_not_raised(tmp_path):
    """Cahier des charges §1 : jamais d'erreur pour les champs EXIF
    absents - ils valent simplement None, les autres restent exploitables."""
    path = tmp_path / "partiel.jpg"
    _make_jpeg_with_exif(path, make="Fujifilm", model="X-T5")

    metadata = get_exif_metadata(path)
    assert metadata["camera"] == "Fujifilm X-T5"
    assert metadata.get("lens") is None
    assert metadata.get("aperture") is None
    assert metadata.get("gps") is None
    # Les dimensions, elles, restent toujours disponibles (lues via
    # rawloader, indépendamment de l'EXIF).
    assert metadata["dimensions"] == (800, 600)


def test_camera_combines_make_and_model_without_duplication():
    """Un modèle qui répète déjà le fabricant (convention Nikon : Make =
    "NIKON CORPORATION", Model = "NIKON D850") ne doit pas produire une
    chaîne doublée."""
    from portfolio.utils import _combine_camera

    assert _combine_camera("Canon", "Canon EOS R5") == "Canon EOS R5"
    assert _combine_camera("NIKON CORPORATION", "NIKON D850") == "NIKON D850"
    assert _combine_camera("Sony", "ILCE-7RM4") == "Sony ILCE-7RM4"
    assert _combine_camera("Canon", None) == "Canon"
    assert _combine_camera(None, "ILCE-7RM4") == "ILCE-7RM4"
    assert _combine_camera(None, None) is None


def test_full_metadata_round_trip(tmp_path):
    """Vérifie un aller-retour complet écriture -> lecture EXIF pour
    chaque champ pris en charge, y compris focale, ouverture, vitesse,
    ISO, focale équivalente 24x36 et date de prise de vue."""
    path = tmp_path / "complete.jpg"
    _make_jpeg_with_exif(
        path,
        make="Canon", model="Canon EOS R5", lens="RF 24-70mm F2.8",
        focal_length=50.0, focal_35mm=50, aperture=2.8, shutter_speed=0.004,
        iso=400, date_original="2024:05:01 12:00:00",
    )

    metadata = get_exif_metadata(path)
    assert metadata["camera"] == "Canon EOS R5"
    assert metadata["lens"] == "RF 24-70mm F2.8"
    assert metadata["focal_length"] == pytest.approx(50.0)
    assert metadata["focal_35mm"] == 50
    assert metadata["aperture"] == pytest.approx(2.8)
    assert metadata["shutter_speed"] == pytest.approx(0.004)
    assert metadata["iso"] == 400
    assert metadata["datetime"] == datetime(2024, 5, 1, 12, 0, 0)
    assert metadata["dimensions"] == (800, 600)


def test_gps_round_trip_and_hemisphere_signs(tmp_path):
    """Les coordonnées GPS doivent revenir en degrés décimaux SIGNÉS
    (positif = Nord/Est), peu importe l'hémisphère - vérifié dans les
    quatre cas (N/E, N/W, S/E, S/W)."""
    cases = [
        ((48.8566, 2.3522), (48.8566, 2.3522)),     # Paris : N, E
        ((48.8566, -122.3522), (48.8566, -122.3522)),  # N, W
        ((-33.8688, 151.2093), (-33.8688, 151.2093)),  # S, E
        ((-33.8688, -70.6693), (-33.8688, -70.6693)),  # S, W
    ]
    for i, (gps_in, expected) in enumerate(cases):
        path = tmp_path / f"gps_{i}.jpg"
        _make_jpeg_with_exif(path, gps=gps_in)
        metadata = get_exif_metadata(path)
        lat, lon = metadata["gps"]
        assert lat == pytest.approx(expected[0], abs=1e-3)
        assert lon == pytest.approx(expected[1], abs=1e-3)


def test_nonexistent_file_never_raises(tmp_path):
    """Un fichier qui n'existe plus (supprimé entre le scan et la
    génération, par exemple) ne doit jamais faire planter l'extraction -
    seulement produire des métadonnées vides au-delà du nom de fichier."""
    path = tmp_path / "introuvable.jpg"
    metadata = get_exif_metadata(path)
    assert metadata["filename"] == "introuvable.jpg"
    assert metadata.get("dimensions") is None


def test_corrupted_file_never_raises(tmp_path):
    """Un fichier portant une extension image mais au contenu corrompu ne
    doit jamais lever d'exception."""
    path = tmp_path / "corrompu.jpg"
    path.write_bytes(b"ceci n'est pas un JPEG valide")
    metadata = get_exif_metadata(path)
    assert metadata["filename"] == "corrompu.jpg"
    assert metadata.get("camera") is None


def test_raw_extension_never_raises_even_without_valid_raw_content(tmp_path):
    """Résilience du chemin RAW (exifread) : un fichier à extension RAW
    mais au contenu invalide (pas un vrai capteur RAW) ne doit jamais
    lever d'exception - voir le docstring du module pour la portée réelle
    de ce test."""
    path = tmp_path / "fake.nef"
    path.write_bytes(b"pas un vrai fichier RAW")
    metadata = get_exif_metadata(path)
    assert metadata["filename"] == "fake.nef"
    assert metadata.get("camera") is None
    assert metadata.get("dimensions") is None
