#!/bin/bash
set -euo pipefail

# ====================== CONFIGURATION ======================
PACKAGE_NAME="planche-contact"
MAINTAINER="Gilles MAGNEVILLE <gilles@magneville.fr>"
DESCRIPTION="Outil de génération de planches contact photographiques"
URL="https://github.com/gillesmagneville/planche-contact"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$HOME/deb-build/build"
VERSION_FILE="$PROJECT_DIR/VERSION"
# ===========================================================

show_help() {
    cat << EOF
Usage: ./build-deb.sh [options]

Script de construction du paquet Debian pour Planche Contact.

OPTIONS :
  --major               Incrémente le numéro majeur   (ex: 1.2.3 → 2.0.0)
  --minor               Incrémente le numéro mineur   (ex: 1.2.3 → 1.3.0)
  --patch               Incrémente le numéro de patch (ex: 1.2.3 → 1.2.4)
  --no-version-change   Reconstruit le paquet sans changer la version
  --clean               Nettoie le dossier de build et supprime tous les .deb
  --help, -h            Affiche cette aide

Sans argument → mode interactif (demande major / minor / patch / no-version-change)

EOF
}

INCREMENT=""
NO_VERSION_CHANGE=false
CLEAN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --major)              INCREMENT="major"; shift ;;
        --minor)              INCREMENT="minor"; shift ;;
        --patch)              INCREMENT="patch"; shift ;;
        --no-version-change)  NO_VERSION_CHANGE=true; shift ;;
        --clean)              CLEAN=true; shift ;;
        --help|-h)            show_help; exit 0 ;;
        *)
            echo "Option inconnue : $1"
            show_help
            exit 1
            ;;
    esac
done

# === Mode nettoyage ===
if [ "$CLEAN" = true ]; then
    echo ">>> Nettoyage du dossier de build..."
    rm -rf "$BUILD_DIR"
    echo ">>> Suppression des paquets .deb existants..."
    rm -f ./*.deb
    echo ">>> Nettoyage terminé."
    exit 0
fi

# Vérification de fpm
if ! command -v fpm &> /dev/null; then
    echo "Erreur: fpm n'est pas installé."
    echo "Installe-le avec : gem install --user-install fpm"
    exit 1
fi

# === Lecture de la version actuelle ===
if [ -f "$VERSION_FILE" ]; then
    CURRENT_VERSION=$(cat "$VERSION_FILE" | tr -d '[:space:]')
else
    CURRENT_VERSION="1.0.0"
fi

# Découpage de la version
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"
MAJOR=${MAJOR:-0}
MINOR=${MINOR:-0}
PATCH=${PATCH:-0}

# === Mode interactif si aucun argument ===
if [ -z "$INCREMENT" ] && [ "$NO_VERSION_CHANGE" = false ]; then
    echo ""
    echo "Version actuelle : $CURRENT_VERSION"
    echo ""
    echo "Que souhaitez-vous faire ?"
    echo "  1) major              (→ $((MAJOR+1)).0.0)"
    echo "  2) minor              (→ $MAJOR.$((MINOR+1)).0)"
    echo "  3) patch              (→ $MAJOR.$MINOR.$((PATCH+1)))"
    echo "  4) no-version-change  (reconstruire en $CURRENT_VERSION)"
    echo ""
    read -p "Votre choix [1/2/3/4] : " CHOICE

    case $CHOICE in
        1) INCREMENT="major" ;;
        2) INCREMENT="minor" ;;
        3) INCREMENT="patch" ;;
        4) NO_VERSION_CHANGE=true ;;
        *)
            echo "Choix invalide. Annulation."
            exit 1
            ;;
    esac
fi

# === Calcul de la nouvelle version ===
if [ "$NO_VERSION_CHANGE" = true ]; then
    NEW_VERSION="$CURRENT_VERSION"
else
    case $INCREMENT in
        major)
            MAJOR=$((MAJOR + 1))
            MINOR=0
            PATCH=0
            ;;
        minor)
            MINOR=$((MINOR + 1))
            PATCH=0
            ;;
        patch)
            PATCH=$((PATCH + 1))
            ;;
    esac
    NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"
fi

# === Demande de confirmation ===
echo ""
echo "========================================"
if [ "$NO_VERSION_CHANGE" = true ]; then
    echo "  Mode           : Reconstruction sans changement de version"
    echo "  Version        : $NEW_VERSION"
else
    echo "  Version actuelle : $CURRENT_VERSION"
    echo "  Nouvelle version : $NEW_VERSION"
fi
echo "========================================"
echo ""
read -p "Construire le paquet en version $NEW_VERSION ? [o/N] " CONFIRM

if [[ ! "$CONFIRM" =~ ^[oOyY]$ ]]; then
    echo "Construction annulée. Aucun fichier n'a été modifié."
    exit 0
fi

# === À partir d'ici, la construction est confirmée ===

echo ">>> Suppression des paquets .deb existants..."
rm -f ./*.deb

DEB_FILE="./${PACKAGE_NAME}_${NEW_VERSION}_amd64.deb"

echo ""
echo "========================================"
echo " Construction du paquet $PACKAGE_NAME v$NEW_VERSION"
echo "========================================"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

echo ">>> Création de l'arborescence..."
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$BUILD_DIR/usr/share/$PACKAGE_NAME"
mkdir -p "$BUILD_DIR/usr/share/applications"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/48x48/apps"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/64x64/apps"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/128x128/apps"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$BUILD_DIR/usr/share/metainfo"

echo ">>> Création du virtualenv..."
python3 -m venv --system-site-packages "$BUILD_DIR/usr/share/$PACKAGE_NAME/venv"

echo ">>> Installation des dépendances Python..."
source "$BUILD_DIR/usr/share/$PACKAGE_NAME/venv/bin/activate"
pip install --upgrade pip --quiet

PIP_LOG=$(mktemp)
if pip install --ignore-installed Pillow reportlab rawpy exifread --quiet >"$PIP_LOG" 2>&1; then
    rm -f "$PIP_LOG"
    deactivate
    echo ">>> Dépendances installées avec succès (Pillow, reportlab, rawpy, exifread)."
else
    echo ""
    echo "Erreur : l'installation des dépendances Python dans le virtualenv a échoué."
    echo ""
    echo "Détail de l'erreur pip :"
    sed 's/^/    /' "$PIP_LOG"
    rm -f "$PIP_LOG"
    echo ""
    echo "Causes possibles : pas de connexion réseau, miroir PyPI inaccessible,"
    echo "ou architecture non couverte par les roues binaires de rawpy."
    echo ""
    echo "Pour corriger le problème :"
    echo "    1) Vérifiez votre connexion réseau (et vos réglages de proxy éventuels)."
    echo "    2) Relancez : ./build-deb.sh --no-version-change"
    echo ""
    echo "Construction annulée : aucun paquet .deb incomplet n'a été généré."
    deactivate
    rm -rf "$BUILD_DIR"
    exit 1
fi

echo ">>> Copie des fichiers du projet..."
cp "$PROJECT_DIR/planche-contact-gtk.py" "$BUILD_DIR/usr/share/$PACKAGE_NAME/"
cp -r "$PROJECT_DIR/portfolio" "$BUILD_DIR/usr/share/$PACKAGE_NAME/"

# Le fichier VERSION du paquet reflète toujours NEW_VERSION, même si le
# fichier VERSION du projet n'est mis à jour qu'après un build réussi
# (voir plus bas).
echo "$NEW_VERSION" > "$BUILD_DIR/usr/share/$PACKAGE_NAME/VERSION"

mkdir -p "$BUILD_DIR/usr/share/$PACKAGE_NAME/docs"
[ -f "$PROJECT_DIR/docs/planche-contact-manual.html" ] && cp "$PROJECT_DIR/docs/planche-contact-manual.html" "$BUILD_DIR/usr/share/$PACKAGE_NAME/docs/"
[ -f "$PROJECT_DIR/LICENSE" ] && cp "$PROJECT_DIR/LICENSE" "$BUILD_DIR/usr/share/$PACKAGE_NAME/"

# Métadonnées AppStream : nécessaires pour qu'App Center (PackageKit +
# AppStream, depuis Ubuntu 26.04) reconnaisse pleinement le paquet - taille
# et description enrichie incluses - au lieu de se limiter au .desktop.
if [ -f "$PROJECT_DIR/metainfo/planche-contact.metainfo.xml" ]; then
    cp "$PROJECT_DIR/metainfo/planche-contact.metainfo.xml" "$BUILD_DIR/usr/share/metainfo/"
else
    echo "Attention : metainfo/planche-contact.metainfo.xml introuvable - le paquet sera construit sans métadonnées AppStream." >&2
fi

ICON_SOURCE="$PROJECT_DIR/screenshots/application-icon.png"
if [ -f "$ICON_SOURCE" ]; then
    echo ">>> Installation de l'icône de l'application (plusieurs tailles)..."
    # On utilise le python3 du venv qu'on vient de construire : Pillow y est
    # garanti présent (installé juste au-dessus), pas besoin de dépendre
    # d'un outil externe (ImageMagick...) sur la machine de build.
    "$BUILD_DIR/usr/share/$PACKAGE_NAME/venv/bin/python3" - "$ICON_SOURCE" "$BUILD_DIR" << 'PYEOF'
import sys
from PIL import Image

source, build_dir = sys.argv[1], sys.argv[2]
img = Image.open(source).convert("RGBA")
for size in (48, 64, 128, 256):
    resized = img.resize((size, size), Image.LANCZOS)
    resized.save(f"{build_dir}/usr/share/icons/hicolor/{size}x{size}/apps/planche-contact.png", "PNG")
PYEOF
    echo ">>> Icône installée aux tailles 48, 64, 128 et 256 px."
else
    echo "Attention : icône introuvable ($ICON_SOURCE) - le paquet sera construit sans icône personnalisée." >&2
fi

echo ">>> Création des scripts d'exécution..."
cat > "$BUILD_DIR/usr/bin/planche-contact-gtk" << 'EOF'
#!/bin/bash
exec /usr/share/planche-contact/venv/bin/python3 /usr/share/planche-contact/planche-contact-gtk.py "$@"
EOF
chmod +x "$BUILD_DIR/usr/bin/planche-contact-gtk"

cat > "$BUILD_DIR/usr/bin/portfolio" << 'EOF'
#!/bin/bash
exec /usr/share/planche-contact/venv/bin/python3 /usr/share/planche-contact/portfolio/portfolio.py "$@"
EOF
chmod +x "$BUILD_DIR/usr/bin/portfolio"

echo ">>> Création du fichier .desktop..."
cat > "$BUILD_DIR/usr/share/applications/planche-contact.desktop" << EOF
[Desktop Entry]
Name=Planche Contact
Comment=Outil de génération de planches contact photographiques
Exec=planche-contact-gtk
Icon=planche-contact
Terminal=false
Type=Application
Categories=Graphics;Photography;
EOF

# === Normalisation des permissions --------------------------------------
# `cp`/`cp -r` appliquent le umask du processus courant à la destination,
# pas les permissions du fichier source. Si build-deb.sh est lancé avec un
# umask restrictif (077, 027...), les fichiers embarqués dans le .deb
# peuvent devenir illisibles pour un utilisateur normal une fois installés
# (PermissionError au lancement de l'application). On force donc ici des
# permissions correctes, indépendamment du umask de la machine de build.
echo ">>> Normalisation des permissions..."
find "$BUILD_DIR" -type d -exec chmod 755 {} +
find "$BUILD_DIR" -type f -exec chmod 644 {} +

# Ré-applique les bits d'exécution perdus par le chmod 644 générique
# ci-dessus, sur tout ce qui doit réellement être exécutable.
chmod +x "$BUILD_DIR/usr/bin/planche-contact-gtk" "$BUILD_DIR/usr/bin/portfolio"
find "$BUILD_DIR/usr/share/$PACKAGE_NAME/venv/bin" -type f -exec chmod 755 {} +

echo ">>> Création du paquet .deb..."
# NOTE : contrairement à dpkg-deb --build natif, fpm ne traite jamais un
# dossier nommé "DEBIAN/" de façon spéciale au sein de ses sources -C. Un tel
# dossier, s'il est listé ici, finit comme simple contenu de données installé
# tel quel à /DEBIAN/ sur la machine cible - jamais exécuté par dpkg. Les
# scripts de maintenance doivent être déclarés via --after-install /
# --after-remove pour que dpkg les exécute réellement à l'installation et à
# la suppression du paquet.
fpm -s dir -t deb \
    -n "$PACKAGE_NAME" \
    -v "$NEW_VERSION" \
    --license "GPL-3.0" \
    --maintainer "$MAINTAINER" \
    --description "$DESCRIPTION" \
    --url "$URL" \
    --depends python3 \
    --depends python3-gi \
    --depends gir1.2-gtk-4.0 \
    --depends libgtk-4-1 \
    --after-install "$PROJECT_DIR/debian/postinst" \
    --after-remove "$PROJECT_DIR/debian/postrm" \
    -C "$BUILD_DIR" \
    usr/

echo ""
echo "✅ Paquet créé avec succès :"
echo "   $DEB_FILE"

# Le fichier VERSION du projet n'est mis à jour qu'ici, une fois le .deb
# effectivement construit. Ainsi, un échec de build (venv, pip, fpm...) ne
# laisse jamais le projet dans un état incohérent (VERSION incrémenté sans
# .deb correspondant).
if [ "$NO_VERSION_CHANGE" = true ]; then
    echo "   Version inchangée : $NEW_VERSION"
else
    echo "$NEW_VERSION" > "$VERSION_FILE"
    echo "   Version enregistrée : $NEW_VERSION"
fi
