#!/bin/bash
set -euo pipefail

# ====================== CONFIGURATION ======================
PACKAGE_NAME="planche-contact"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION_FILE="$PROJECT_DIR/VERSION"
ARCH="$(uname -m)"
# Dossier de travail (hors du dépôt) : AppDir, venv pip, outils téléchargés.
BUILD_DIR="${APPIMAGE_BUILD_DIR:-$HOME/appimage-build}"
# Interpréteur Python embarqué (celui qui voit PyGObject et GTK4).
PYTHON="${PYTHON:-python3}"

# quick-sharun : l'outil de l'écosystème « Anylinux-AppImages »
# (https://github.com/pkgforge-dev/Anylinux-AppImages) qui embarque les
# bibliothèques dont GTK4 et Python ont besoin - y compris la glibc, ce qui
# rend l'AppImage indépendante de la distribution qui l'exécute - puis
# assemble le fichier .AppImage. Il est téléchargé à chaque construction, mais
# son empreinte SHA-256 est vérifiée : si le script amont change, la
# construction s'arrête au lieu d'exécuter un code qu'on n'a pas relu (voir
# les variables d'environnement QUICK_SHARUN_URL / QUICK_SHARUN_SHA256 pour
# adopter une nouvelle version après l'avoir examinée). Lui-même vérifie les
# empreintes de tout ce qu'il télécharge ensuite (sharun, appimagetool...).
QUICK_SHARUN_URL="${QUICK_SHARUN_URL:-https://raw.githubusercontent.com/pkgforge-dev/Anylinux-AppImages/refs/heads/main/useful-tools/quick-sharun.sh}"
QUICK_SHARUN_SHA256="${QUICK_SHARUN_SHA256:-fa9dbe2532d568e1c1b8eeaba94d1c57109b776b5541d21b74d3f44b74faf4d3}"
# ===========================================================

show_help() {
    cat << EOF
Usage: ./build-appimage.sh [options]

Construit l'AppImage de Planche Contact (un seul fichier exécutable, avec
Python, GTK4 et toutes les dépendances embarqués) et son empreinte SHA-256 :

    Planche-Contact-<version>-${ARCH}.AppImage
    Planche-Contact-<version>-${ARCH}.AppImage.sha256

La version est celle du fichier VERSION (lancez ./build-deb.sh avant pour
l'incrémenter, si besoin : les deux paquets portent alors le même numéro).

OPTIONS :
  --test       Après la construction, vérifie l'AppImage : ligne de commande
               (génération réelle d'un PDF) puis, si xvfb-run est installé,
               démarrage de l'interface graphique
  --clean      Supprime le dossier de travail et les AppImage générées
  --help, -h   Affiche cette aide

PRÉREQUIS (Debian / Ubuntu) :
  sudo apt install python3 python3-venv python3-gi gir1.2-gtk-4.0 \\
       patchelf binutils curl strace   # + xvfb pour --test

Construire sur Arch Linux est ce que recommande le projet Anylinux-AppImages
(chaque distribution range ses bibliothèques à sa façon) ; Debian/Ubuntu
fonctionne mais n'est pas le cas de référence de l'outil.
Voir README.md, section « AppImage ».

VARIABLES D'ENVIRONNEMENT :
  APPIMAGE_BUILD_DIR   Dossier de travail (défaut : ~/appimage-build)
  PYTHON               Python à embarquer (défaut : python3)
  QUICK_SHARUN_URL     Adresse de quick-sharun
  QUICK_SHARUN_SHA256  Empreinte attendue de ce script
EOF
}

RUN_TEST=false
CLEAN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --test)      RUN_TEST=true; shift ;;
        --clean)     CLEAN=true; shift ;;
        --help|-h)   show_help; exit 0 ;;
        *)
            echo "Option inconnue : $1"
            show_help
            exit 1
            ;;
    esac
done

run_test() {
    local image="$1" work photos
    work="$(mktemp -d)"
    photos="$work/photos"
    mkdir -p "$photos/sous-dossier"
    echo ">>> Vérification de $(basename "$image")..."

    # Trois photos de test, dont une dans un sous-dossier. Pillow vient du
    # dossier de dépendances de la construction.
    PYTHONPATH="$SITE_DIR" "$BUILD_DIR/venv/bin/python3" - "$photos" << 'PYEOF'
import sys
from PIL import Image

root = sys.argv[1]
for name in ("alpha.jpg", "beta.jpg", "sous-dossier/gamma.jpg"):
    Image.new("RGB", (640, 480), (90, 140, 200)).save(f"{root}/{name}")
PYEOF

    export APPIMAGE_EXTRACT_AND_RUN=1
    local ok=true

    # 1. Ligne de commande : une vraie génération (PDF + index CSV).
    if "$image" portfolio -i "$photos" -o "$work/out" -r --pdf --csv --language en > "$work/cli.log" 2>&1 \
            && [ -s "$work/out/portfolio.pdf" ] && [ "$(wc -l < "$work/out/index.csv")" -eq 4 ]; then
        echo "    [OK] ligne de commande : PDF et index CSV générés"
    else
        echo "    [ÉCHEC] ligne de commande (journal : $work/cli.log)"
        ok=false
    fi

    # 2. Interface graphique : doit rester ouverte (code 124 = arrêtée par
    # timeout, donc toujours en vie) - nécessite un affichage virtuel.
    if command -v xvfb-run > /dev/null 2>&1; then
        local status=0
        HOME="$work" timeout 15 xvfb-run -a "$image" > "$work/gui.log" 2>&1 || status=$?
        if [ "$status" -eq 124 ]; then
            echo "    [OK] interface graphique : démarre et reste ouverte"
        else
            echo "    [ÉCHEC] interface graphique (code $status, journal : $work/gui.log)"
            ok=false
        fi
    else
        echo "    [--] interface graphique non testée (xvfb-run absent : sudo apt install xvfb)"
    fi

    if [ "$ok" = true ]; then
        rm -rf "$work"
    else
        echo "    Fichiers de test conservés dans $work"
        return 1
    fi
}

# === Mode nettoyage ===
if [ "$CLEAN" = true ]; then
    echo ">>> Nettoyage du dossier de travail ($BUILD_DIR)..."
    rm -rf "$BUILD_DIR"
    echo ">>> Suppression des AppImage et empreintes générées..."
    rm -f "$PROJECT_DIR"/*.AppImage "$PROJECT_DIR"/*.AppImage.sha256
    echo ">>> Nettoyage terminé."
    exit 0
fi

# === Vérification des outils ===
missing=()
for tool in "$PYTHON" patchelf strings curl sha256sum tar; do
    command -v "$tool" > /dev/null 2>&1 || missing+=("$tool")
done
if [ "${#missing[@]}" -gt 0 ]; then
    echo "Erreur : outil(s) manquant(s) : ${missing[*]}"
    echo "Sur Debian/Ubuntu : sudo apt install python3 python3-venv patchelf binutils curl"
    exit 1
fi
if ! "$PYTHON" -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk' 2> /dev/null; then
    echo "Erreur : PyGObject et GTK4 sont introuvables pour $PYTHON."
    echo "Sur Debian/Ubuntu : sudo apt install python3-gi gir1.2-gtk-4.0"
    exit 1
fi
if ! "$PYTHON" -c 'import venv, ensurepip' 2> /dev/null; then
    echo "Erreur : le module venv de Python est incomplet."
    echo "Sur Debian/Ubuntu : sudo apt install python3-venv"
    exit 1
fi

if [ -f "$VERSION_FILE" ]; then
    VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
else
    VERSION="1.0.0"
fi

APPIMAGE_NAME="Planche-Contact-${VERSION}-${ARCH}.AppImage"
APPDIR="$BUILD_DIR/AppDir"
SHARE_DIR="$APPDIR/share/$PACKAGE_NAME"
SITE_DIR="$SHARE_DIR/site-packages"
OUT_DIR="$BUILD_DIR/dist"

# Python du système : c'est lui qui est embarqué (avec PyGObject, qui ne
# s'installe pas de façon fiable par pip - voir requirements.txt).
PYTHON_BIN="$(readlink -f "$(command -v "$PYTHON")")"
PY_MM="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_STDLIB="$("$PYTHON" -c 'import sysconfig; print(sysconfig.get_path("stdlib"))')"
GI_DIR="$("$PYTHON" -c 'import gi, os; print(os.path.dirname(gi.__file__))')"

echo ""
echo "========================================"
echo " AppImage $PACKAGE_NAME v$VERSION ($ARCH)"
echo " Python $PY_MM  -  $PYTHON_BIN"
echo " Dossier de travail : $BUILD_DIR"
echo "========================================"
echo ""

rm -rf "$BUILD_DIR"
mkdir -p "$SHARE_DIR" "$APPDIR/bin" "$OUT_DIR" "$BUILD_DIR/tmp"

# === 1. Les sources de l'application (comme build-deb.sh) ===
echo ">>> Copie des fichiers du projet..."
(
    cd "$PROJECT_DIR"
    items=(planche-contact-gtk.py portfolio docs)
    [ -f LICENSE ] && items+=(LICENSE)
    tar --exclude='__pycache__' -cf - "${items[@]}"
) | tar -xf - -C "$SHARE_DIR"
echo "$VERSION" > "$SHARE_DIR/VERSION"

# === 2. Dépendances Python (pip) dans un dossier à part ===
echo ">>> Installation des dépendances Python (Pillow, reportlab, rawpy, exifread)..."
"$PYTHON" -m venv "$BUILD_DIR/venv"
PIP_LOG="$BUILD_DIR/pip.log"
if ! "$BUILD_DIR/venv/bin/pip" install --quiet --target "$SITE_DIR" \
        Pillow reportlab rawpy exifread > "$PIP_LOG" 2>&1; then
    echo "Erreur : l'installation des dépendances Python a échoué."
    sed 's/^/  /' "$PIP_LOG"
    exit 1
fi
rm -rf "$SITE_DIR/bin"

# PyGObject (module « gi ») : celui du système, compilé pour ce Python.
echo ">>> Copie de PyGObject ($GI_DIR)..."
tar --exclude='__pycache__' -C "$(dirname "$GI_DIR")" -cf - "$(basename "$GI_DIR")" | tar -xf - -C "$SITE_DIR"

# === 3. La bibliothèque standard de Python ===
# quick-sharun sait embarquer Python quand la bibliothèque standard se trouve
# dans le dossier des bibliothèques du système (Arch) ; sur Debian/Ubuntu
# elle est dans /usr/lib/pythonX.Y : on la copie donc ici, quick-sharun ne
# s'occupant que de l'exécutable et des bibliothèques dont il dépend.
echo ">>> Copie de la bibliothèque standard de Python..."
mkdir -p "$APPDIR/lib"
tar -C "$(dirname "$PY_STDLIB")" -cf - \
    --exclude='__pycache__' --exclude='test' --exclude='tests' --exclude='idlelib' \
    --exclude='turtledemo' --exclude='tkinter' --exclude='lib2to3' --exclude='ensurepip' \
    --exclude='EXTERNALLY-MANAGED' "$(basename "$PY_STDLIB")" | tar -xf - -C "$APPDIR/lib"

# Modules d'extension qui dépendent d'une bibliothèque du système (hors libc) :
# on les passe à quick-sharun pour qu'il embarque ces bibliothèques. Exclus :
# SSL/hashlib (hashlib retombe sur ses versions internes), sqlite, curses,
# readline, tkinter et les bases dbm, dont l'application n'a pas besoin.
EXTRA_LIBS=()
for module in "$PY_STDLIB"/lib-dynload/*.so; do
    case "$(basename "$module")" in
        _ssl.*|_hashlib.*|_tkinter.*|_sqlite3.*|_curses*|_dbm.*|_gdbm.*|readline.*) continue ;;
    esac
    if ldd "$module" 2> /dev/null | grep -v 'linux-vdso\|libc\.so\|libm\.so\|ld-linux\|libpython' | grep -q '=>'; then
        EXTRA_LIBS+=("$module")
    fi
done

# === 4. Lanceurs, icône, métadonnées ===
echo ">>> Création des lanceurs, du .desktop et de l'icône..."
cat > "$APPDIR/bin/planche-contact" << 'EOF'
#!/bin/sh
# Interface graphique : Python embarqué + sources dans share/planche-contact.
HERE="${APPDIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SHARE="$HERE/share/planche-contact"
export PYTHONPATH="$SHARE/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
# Le python embarqué par son chemin complet, jamais « python3 » via le PATH :
# ce serait, selon la machine, un autre Python que celui des modules livrés.
exec "$HERE/bin/@PYBIN@" "$SHARE/planche-contact-gtk.py" "$@"
EOF
cat > "$APPDIR/bin/portfolio" << 'EOF'
#!/bin/sh
# Ligne de commande : ./Planche-Contact-*.AppImage portfolio -i PHOTOS --pdf
HERE="${APPDIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SHARE="$HERE/share/planche-contact"
export PYTHONPATH="$SHARE/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
exec "$HERE/bin/@PYBIN@" "$SHARE/portfolio/portfolio.py" "$@"
EOF
sed -i "s|@PYBIN@|python$PY_MM|" "$APPDIR/bin/planche-contact" "$APPDIR/bin/portfolio"
chmod +x "$APPDIR/bin/planche-contact" "$APPDIR/bin/portfolio"

cat > "$BUILD_DIR/$PACKAGE_NAME.desktop" << 'EOF'
[Desktop Entry]
Name=Planche Contact
Comment=Outil de génération de planches contact photographiques
Exec=planche-contact
Icon=planche-contact
Terminal=false
Type=Application
Categories=Graphics;Photography;
StartupWMClass=com.planchecontact.gtk
EOF

ICON_SOURCE="$PROJECT_DIR/screenshots/application-icon.png"
if [ -f "$ICON_SOURCE" ]; then
    # Pillow (déjà installé ci-dessus) évite de dépendre d'ImageMagick.
    PYTHONPATH="$SITE_DIR" "$BUILD_DIR/venv/bin/python3" - "$ICON_SOURCE" "$BUILD_DIR/$PACKAGE_NAME.png" << 'PYEOF'
import sys
from PIL import Image

Image.open(sys.argv[1]).convert("RGBA").resize((256, 256), Image.LANCZOS).save(sys.argv[2], "PNG")
PYEOF
else
    echo "Attention : icône introuvable ($ICON_SOURCE) - AppImage sans icône personnalisée." >&2
    exit 1
fi

if [ -f "$PROJECT_DIR/metainfo/$PACKAGE_NAME.metainfo.xml" ]; then
    mkdir -p "$APPDIR/share/metainfo"
    cp "$PROJECT_DIR/metainfo/$PACKAGE_NAME.metainfo.xml" "$APPDIR/share/metainfo/"
fi

# === 5. quick-sharun : bibliothèques, glibc, GTK4, assemblage ===
echo ">>> Téléchargement de quick-sharun (vérification de l'empreinte)..."
QUICK_SHARUN="$BUILD_DIR/quick-sharun.sh"
curl -fsSL "$QUICK_SHARUN_URL" -o "$QUICK_SHARUN"
if ! echo "$QUICK_SHARUN_SHA256  $QUICK_SHARUN" | sha256sum -c - > /dev/null 2>&1; then
    echo "Erreur : l'empreinte de quick-sharun ne correspond pas à celle attendue."
    echo "  attendue : $QUICK_SHARUN_SHA256"
    echo "  obtenue  : $(sha256sum "$QUICK_SHARUN" | cut -d' ' -f1)"
    echo "Le script amont a changé depuis la dernière vérification. Relisez-le"
    echo "($QUICK_SHARUN), puis relancez avec QUICK_SHARUN_SHA256=<nouvelle empreinte>."
    exit 1
fi

# libgirepository et GTK4 : chargées dynamiquement par PyGObject (fichiers
# .typelib), donc invisibles pour l'analyse des dépendances - on les nomme.
GI_EXT="$(ls "$SITE_DIR"/gi/_gi.*.so | head -n 1)"
find_lib() {
    ldconfig -p 2> /dev/null | awk -v n="$1" '$1 == n { print $NF; exit }'
}
GIREPO_LIB="$(ldd "$GI_EXT" | awk '/libgirepository/ { print $3; exit }')"
GTK_LIB="$(find_lib libgtk-4.so.1)"
if [ -z "$GIREPO_LIB" ] || [ -z "$GTK_LIB" ]; then
    echo "Erreur : libgirepository ou libgtk-4 introuvable (GTK4 est-il installé ?)."
    exit 1
fi
# libanl : sharun la précharge ; sans copie embarquée, c'est celle de la
# machine qui serait chargée, avec la glibc de CETTE machine (version
# différente de la glibc embarquée). Absente des glibc récentes : sans objet.
ANL_LIB="$(find_lib libanl.so.1)"
if [ -n "$ANL_LIB" ]; then
    EXTRA_LIBS+=("$ANL_LIB")
fi

echo ">>> Embarquement des bibliothèques et assemblage de l'AppImage (quelques minutes)..."
QS_LOG="$BUILD_DIR/quick-sharun.log"
if ! (
    cd "$BUILD_DIR"
    export TMPDIR="$BUILD_DIR/tmp"
    export APPDIR OUTPATH="$OUT_DIR" OUTNAME="$APPIMAGE_NAME"
    export MAIN_BIN=planche-contact
    export DESKTOP="$BUILD_DIR/$PACKAGE_NAME.desktop" ICON="$BUILD_DIR/$PACKAGE_NAME.png"
    export DEPLOY_GTK=1
    # Rendu logiciel de GTK (Cairo) : l'interface n'a besoin ni d'OpenGL ni de
    # Vulkan. Cela évite d'embarquer Mesa et LLVM (des dizaines de Mo) et de
    # dépendre des pilotes graphiques de la machine - cause classique d'une
    # AppImage qui démarre ici et pas là.
    export ALWAYS_SOFTWARE=1
    # Sans Mesa embarqué, libepoxy (GTK) tente tout de même d'ouvrir libEGL au
    # démarrage et trouverait celle de la machine, avec ses pilotes, LLVM, etc.
    # (compilés pour une autre glibc). On l'en empêche : GTK se rabat alors,
    # proprement, sur le rendu Cairo, identique sur toutes les machines.
    export ANYLINUX_DO_NOT_LOAD_LIBS='libEGL*:libGL.so*:libGLdispatch*:libgbm*'
    # Python : sa bibliothèque standard est copiée à la main (voir 3) ;
    # l'exécutable est passé en argument comme n'importe quel binaire.
    export STRACE_MODE=0
    export OUTPUT_APPIMAGE=1
    sh "$QUICK_SHARUN" "$PYTHON_BIN" "$GIREPO_LIB" "$GTK_LIB" "$GI_EXT" ${EXTRA_LIBS[@]+"${EXTRA_LIBS[@]}"}
) > "$QS_LOG" 2>&1; then
    echo "Erreur : quick-sharun a échoué. Fin du journal ($QS_LOG) :"
    tail -n 25 "$QS_LOG" | sed 's/^/  /'
    exit 1
fi

if [ ! -f "$OUT_DIR/$APPIMAGE_NAME" ]; then
    echo "Erreur : $APPIMAGE_NAME n'a pas été produit (voir $QS_LOG)."
    exit 1
fi

# === 6. Livraison : l'AppImage et son empreinte, à la racine du projet ===
rm -f "$PROJECT_DIR"/*.AppImage "$PROJECT_DIR"/*.AppImage.sha256
cp "$OUT_DIR/$APPIMAGE_NAME" "$PROJECT_DIR/$APPIMAGE_NAME"
chmod +x "$PROJECT_DIR/$APPIMAGE_NAME"
(cd "$PROJECT_DIR" && sha256sum "$APPIMAGE_NAME" > "$APPIMAGE_NAME.sha256")

echo ""
echo "AppImage générée :"
ls -lh "$PROJECT_DIR/$APPIMAGE_NAME" | awk '{print "   " $5 "  " $NF}'
echo "   $(cat "$PROJECT_DIR/$APPIMAGE_NAME.sha256")"

# === 7. Vérification facultative ===
if [ "$RUN_TEST" = true ]; then
    echo ""
    run_test "$PROJECT_DIR/$APPIMAGE_NAME"
fi
