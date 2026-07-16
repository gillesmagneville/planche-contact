#!/bin/bash
set -e

# ====================== CONFIGURATION ======================
PACKAGE_NAME="planche-contact"
VERSION="1.0.0"
MAINTAINER="Gilles MAGNEVILLE <ton@email.com>"
DESCRIPTION="Outil de génération de planches contact photographiques"
URL="https://github.com/gillesmagneville/planche-contact"

PROJECT_DIR="$HOME/Projects/planche-contact"
BUILD_DIR="$HOME/deb-build/$PACKAGE_NAME"
# ===========================================================

echo "=== Nettoyage du dossier de build ==="
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

echo "=== Création de l'arborescence ==="
mkdir -p "$BUILD_DIR/usr/bin"
mkdir -p "$BUILD_DIR/usr/share/$PACKAGE_NAME"
mkdir -p "$BUILD_DIR/usr/share/applications"
mkdir -p "$BUILD_DIR/usr/share/icons/hicolor/128x128/apps"
mkdir -p "$BUILD_DIR/DEBIAN"

echo "=== Création du virtualenv ==="
python3 -m venv "$BUILD_DIR/usr/share/$PACKAGE_NAME/venv"

echo "=== Installation des dépendances Python ==="
source "$BUILD_DIR/usr/share/$PACKAGE_NAME/venv/bin/activate"
pip install --upgrade pip
pip install Pillow reportlab
deactivate

echo "=== Copie des fichiers du projet ==="
cp "$PROJECT_DIR/planche-contact-gtk.py" "$BUILD_DIR/usr/share/$PACKAGE_NAME/"
cp -r "$PROJECT_DIR/portfolio" "$BUILD_DIR/usr/share/$PACKAGE_NAME/"

# Copie du fichier LICENSE
cp "$PROJECT_DIR/LICENSE" "$BUILD_DIR/usr/share/$PACKAGE_NAME/" 2>/dev/null || echo "LICENSE non trouvé, ignoré"

# Copie de l'icône (si elle existe)
if [ -f "$PROJECT_DIR/planche-contact.png" ]; then
    cp "$PROJECT_DIR/planche-contact.png" "$BUILD_DIR/usr/share/icons/hicolor/128x128/apps/"
fi

echo "=== Création du wrapper ==="
cat > "$BUILD_DIR/usr/bin/planche-contact-gtk" << 'EOF'
#!/bin/bash
exec /usr/share/planche-contact/venv/bin/python3 /usr/share/planche-contact/planche-contact-gtk.py "$@"
EOF
chmod +x "$BUILD_DIR/usr/bin/planche-contact-gtk"

echo "=== Création du fichier .desktop ==="
cat > "$BUILD_DIR/usr/share/applications/planche-contact.desktop" << EOF
[Desktop Entry]
Name=Planche-Contact
Comment=Outil de génération de planches contact photographiques
Exec=planche-contact-gtk
Icon=planche-contact
Terminal=false
Type=Application
Categories=Graphics;Photography;
EOF

echo "=== Création des scripts de maintenance ==="

# postinst
cat > "$BUILD_DIR/DEBIAN/postinst" << 'EOF'
#!/bin/bash
set -e
# Mise à jour du cache des icônes
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF
chmod 755 "$BUILD_DIR/DEBIAN/postinst"

# postrm
cat > "$BUILD_DIR/DEBIAN/postrm" << 'EOF'
#!/bin/bash
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    # Nettoyage du cache des icônes
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    fi
fi
exit 0
EOF
chmod 755 "$BUILD_DIR/DEBIAN/postrm"

echo "=== Création du paquet .deb ==="
cd "$HOME/deb-build"

fpm -s dir -t deb \
  -n "$PACKAGE_NAME" \
  -v "$VERSION" \
  --license MIT \
  --maintainer "$MAINTAINER" \
  --description "$DESCRIPTION" \
  --url "$URL" \
  --depends python3 \
  --deb-user root \
  --deb-group root \
  -C "$BUILD_DIR" \
  usr/ DEBIAN/

echo ""
echo "=== ✅ Paquet créé avec succès ==="
ls -lh "$HOME/deb-build/"*.deb
