#!/bin/bash
set -euo pipefail

# ====================== CONFIGURATION ======================
PACKAGE_NAME="planche-contact"
MAINTAINER="Gilles MAGNEVILLE <gilles@magneville.fr>"
DESCRIPTION="Photographic contact sheet generator"
URL="https://github.com/gillesmagneville/planche-contact"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$HOME/deb-build/build"
VERSION_FILE="$PROJECT_DIR/VERSION"
# ===========================================================

show_help() {
    cat << EOF
Usage: ./build-deb.sh [options]

Builds the Debian package for Planche Contact.

OPTIONS:
  --major               Bump the major number         (e.g. 1.2.3 → 2.0.0)
  --minor               Bump the minor number         (e.g. 1.2.3 → 1.3.0)
  --patch               Bump the patch number         (e.g. 1.2.3 → 1.2.4)
  --no-version-change   Rebuild the package without changing the version
  --clean               Clean the build folder and delete every .deb
  --help, -h            Show this help

Without an argument → interactive mode (asks major / minor / patch / no-version-change)

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
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# === Clean mode ===
if [ "$CLEAN" = true ]; then
    echo ">>> Cleaning the build folder..."
    rm -rf "$BUILD_DIR"
    echo ">>> Deleting the existing .deb packages..."
    rm -f ./*.deb
    echo ">>> Cleaning done."
    exit 0
fi

# Checking for fpm
if ! command -v fpm &> /dev/null; then
    echo "Error: fpm is not installed."
    echo "Install it with: gem install --user-install fpm"
    exit 1
fi

# === Reading the current version ===
if [ -f "$VERSION_FILE" ]; then
    CURRENT_VERSION=$(cat "$VERSION_FILE" | tr -d '[:space:]')
else
    CURRENT_VERSION="1.0.0"
fi

# Splitting the version
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"
MAJOR=${MAJOR:-0}
MINOR=${MINOR:-0}
PATCH=${PATCH:-0}

# === Interactive mode if no argument ===
if [ -z "$INCREMENT" ] && [ "$NO_VERSION_CHANGE" = false ]; then
    echo ""
    echo "Current version: $CURRENT_VERSION"
    echo ""
    echo "What do you want to do?"
    echo "  1) major              (→ $((MAJOR+1)).0.0)"
    echo "  2) minor              (→ $MAJOR.$((MINOR+1)).0)"
    echo "  3) patch              (→ $MAJOR.$MINOR.$((PATCH+1)))"
    echo "  4) no-version-change  (rebuild as $CURRENT_VERSION)"
    echo ""
    read -p "Your choice [1/2/3/4]: " CHOICE

    case $CHOICE in
        1) INCREMENT="major" ;;
        2) INCREMENT="minor" ;;
        3) INCREMENT="patch" ;;
        4) NO_VERSION_CHANGE=true ;;
        *)
            echo "Invalid choice. Cancelled."
            exit 1
            ;;
    esac
fi

# === Computing the new version ===
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

# === Asking for confirmation ===
echo ""
echo "========================================"
if [ "$NO_VERSION_CHANGE" = true ]; then
    echo "  Mode           : Rebuild without changing the version"
    echo "  Version        : $NEW_VERSION"
else
    echo "  Current version : $CURRENT_VERSION"
    echo "  New version     : $NEW_VERSION"
fi
echo "========================================"
echo ""
read -p "Build the package in version $NEW_VERSION? [y/N] " CONFIRM

if [[ ! "$CONFIRM" =~ ^[yY]$ ]]; then
    echo "Build cancelled. No file was modified."
    exit 0
fi

# === From here on, the build is confirmed ===

echo ">>> Deleting the existing .deb packages..."
rm -f ./*.deb

DEB_FILE="./${PACKAGE_NAME}_${NEW_VERSION}_amd64.deb"

echo ""
echo "========================================"
echo " Building the package $PACKAGE_NAME v$NEW_VERSION"
echo "========================================"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

echo ">>> Creating the directory tree..."
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$BUILD_DIR/usr/share/$PACKAGE_NAME"
mkdir -p "$BUILD_DIR/usr/share/applications"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/48x48/apps"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/64x64/apps"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/128x128/apps"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$BUILD_DIR/usr/share/metainfo"

echo ">>> Creating the virtualenv..."
python3 -m venv --system-site-packages "$BUILD_DIR/usr/share/$PACKAGE_NAME/venv"

echo ">>> Installing the Python dependencies..."
source "$BUILD_DIR/usr/share/$PACKAGE_NAME/venv/bin/activate"
pip install --upgrade pip --quiet

PIP_LOG=$(mktemp)
if pip install --ignore-installed Pillow reportlab rawpy exifread --quiet >"$PIP_LOG" 2>&1; then
    rm -f "$PIP_LOG"
    deactivate
    echo ">>> Dependencies installed successfully (Pillow, reportlab, rawpy, exifread)."
else
    echo ""
    echo "Error: installing the Python dependencies in the virtualenv failed."
    echo ""
    echo "pip error details:"
    sed 's/^/    /' "$PIP_LOG"
    rm -f "$PIP_LOG"
    echo ""
    echo "Possible causes: no network connection, PyPI mirror unreachable,"
    echo "or an architecture not covered by rawpy's binary wheels."
    echo ""
    echo "To fix the problem:"
    echo "    1) Check your network connection (and your proxy settings, if any)."
    echo "    2) Run again: ./build-deb.sh --no-version-change"
    echo ""
    echo "Build cancelled: no incomplete .deb package was generated."
    deactivate
    rm -rf "$BUILD_DIR"
    exit 1
fi

echo ">>> Copying the project files..."
cp "$PROJECT_DIR/planche-contact-gtk.py" "$BUILD_DIR/usr/share/$PACKAGE_NAME/"
cp -r "$PROJECT_DIR/portfolio" "$BUILD_DIR/usr/share/$PACKAGE_NAME/"

# The package's VERSION file always reflects NEW_VERSION, even though the
# project's VERSION file is only updated after a successful build (see
# below).
echo "$NEW_VERSION" > "$BUILD_DIR/usr/share/$PACKAGE_NAME/VERSION"

# The four manuals (French: planche-contact-manual.html; English, German,
# Spanish: planche-contact-manual.<language>.html). The "Help" tab opens the
# one for the interface language and falls back to the French manual if it
# is missing: all of them must therefore be shipped.
mkdir -p "$BUILD_DIR/usr/share/$PACKAGE_NAME/docs"
MANUALS=0
for manual in "$PROJECT_DIR"/docs/planche-contact-manual*.html; do
    if [ -f "$manual" ]; then
        cp "$manual" "$BUILD_DIR/usr/share/$PACKAGE_NAME/docs/"
        MANUALS=$((MANUALS + 1))
    fi
done
if [ "$MANUALS" -eq 0 ]; then
    echo "Warning: no manual (docs/planche-contact-manual*.html) found - the package will be built without a manual." >&2
fi
[ -f "$PROJECT_DIR/LICENSE" ] && cp "$PROJECT_DIR/LICENSE" "$BUILD_DIR/usr/share/$PACKAGE_NAME/"

# The project documentation, in both languages: English by default
# (README.md, CHANGELOG.md, CODE_OF_CONDUCT.md) and French (README.fr.md,
# CHANGELOG.fr.md, CODE_OF_CONDUCT.fr.md). The code of conduct (Contributor
# Covenant 3.0) is under CC-BY-SA-4.0, hence the license expression given to
# fpm below.
mkdir -p "$BUILD_DIR/usr/share/doc/$PACKAGE_NAME"
for doc in README.md README.fr.md CHANGELOG.md CHANGELOG.fr.md CODE_OF_CONDUCT.md CODE_OF_CONDUCT.fr.md LICENSE; do
    if [ -f "$PROJECT_DIR/$doc" ]; then
        cp "$PROJECT_DIR/$doc" "$BUILD_DIR/usr/share/doc/$PACKAGE_NAME/"
    fi
done

# AppStream metadata: needed for App Center (PackageKit + AppStream, since
# Ubuntu 26.04) to fully recognize the package - size and enriched
# description included - instead of relying on the .desktop file alone.
if [ -f "$PROJECT_DIR/metainfo/planche-contact.metainfo.xml" ]; then
    cp "$PROJECT_DIR/metainfo/planche-contact.metainfo.xml" "$BUILD_DIR/usr/share/metainfo/"
else
    echo "Warning: metainfo/planche-contact.metainfo.xml not found - the package will be built without AppStream metadata." >&2
fi

ICON_SOURCE="$PROJECT_DIR/screenshots/application-icon.png"
if [ -f "$ICON_SOURCE" ]; then
    echo ">>> Installing the application icon (several sizes)..."
    # The python3 of the virtualenv just built is used: Pillow is guaranteed
    # to be there (installed right above), so there is no need to depend on
    # an external tool (ImageMagick...) on the build machine.
    "$BUILD_DIR/usr/share/$PACKAGE_NAME/venv/bin/python3" - "$ICON_SOURCE" "$BUILD_DIR" << 'PYEOF'
import sys
from PIL import Image

source, build_dir = sys.argv[1], sys.argv[2]
img = Image.open(source).convert("RGBA")
for size in (48, 64, 128, 256):
    resized = img.resize((size, size), Image.LANCZOS)
    resized.save(f"{build_dir}/usr/share/icons/hicolor/{size}x{size}/apps/planche-contact.png", "PNG")
PYEOF
    echo ">>> Icon installed in sizes 48, 64, 128 and 256 px."
else
    echo "Warning: icon not found ($ICON_SOURCE) - the package will be built without a custom icon." >&2
fi

echo ">>> Creating the launch scripts..."
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

# The Comment lines are the same texts as the command-line description of
# the program (portfolio/locales/*.py, "cli.description"); the menu shows
# the one of the session language, and English otherwise.
echo ">>> Creating the .desktop file..."
cat > "$BUILD_DIR/usr/share/applications/planche-contact.desktop" << EOF
[Desktop Entry]
Name=Planche Contact
Comment=Photographic contact sheet generator
Comment[de]=Generator für fotografische Kontaktbögen
Comment[es]=Generador de hojas de contacto fotográficas
Comment[fr]=Générateur de planches contact photographiques
Exec=planche-contact-gtk
Icon=planche-contact
Terminal=false
Type=Application
Categories=Graphics;Photography;
EOF

# === Normalizing the permissions ----------------------------------------
# `cp`/`cp -r` apply the current process's umask to the destination, not
# the permissions of the source file. If build-deb.sh is run with a
# restrictive umask (077, 027...), the files shipped in the .deb can become
# unreadable for a normal user once installed (PermissionError at launch).
# Correct permissions are therefore forced here, whatever the umask of the
# build machine.
echo ">>> Normalizing permissions..."
find "$BUILD_DIR" -type d -exec chmod 755 {} +
find "$BUILD_DIR" -type f -exec chmod 644 {} +

# Re-applies the execute bits lost by the generic chmod 644 above, on
# everything that must really be executable.
chmod +x "$BUILD_DIR/usr/bin/planche-contact-gtk" "$BUILD_DIR/usr/bin/portfolio"
find "$BUILD_DIR/usr/share/$PACKAGE_NAME/venv/bin" -type f -exec chmod 755 {} +

echo ">>> Creating the .deb package..."
# NOTE: unlike native dpkg-deb --build, fpm never treats a folder named
# "DEBIAN/" specially within its -C sources. Such a folder, if listed here,
# ends up as plain data installed as is in /DEBIAN/ on the target machine -
# never run by dpkg. The maintainer scripts must be declared through
# --after-install / --after-remove for dpkg to really run them when the
# package is installed and removed.
fpm -s dir -t deb \
    -n "$PACKAGE_NAME" \
    -v "$NEW_VERSION" \
    --license "GPL-3.0-only AND CC-BY-SA-4.0" \
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
echo "Package generated:"
echo "   $DEB_FILE"

# The project's VERSION file is only updated here, once the .deb has really
# been built. A build failure (venv, pip, fpm...) therefore never leaves the
# project in an inconsistent state (VERSION bumped without a matching .deb).
if [ "$NO_VERSION_CHANGE" = true ]; then
    echo "   Version unchanged: $NEW_VERSION"
else
    echo "$NEW_VERSION" > "$VERSION_FILE"
    echo "   Version recorded: $NEW_VERSION"
fi
