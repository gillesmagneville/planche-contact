#!/bin/bash
set -euo pipefail
# With "set -e" a failing command stops the script; without this message the
# stop would be silent, and the user could not tell where it happened.
trap 'echo "Error: the script stopped at line $LINENO (command: $BASH_COMMAND)." >&2' ERR

# ====================== CONFIGURATION ======================
PACKAGE_NAME="planche-contact"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION_FILE="$PROJECT_DIR/VERSION"
ARCH="$(uname -m)"
# Working folder (outside the repository): AppDir, pip venv, downloaded tools.
BUILD_DIR="${APPIMAGE_BUILD_DIR:-$HOME/appimage-build}"
# Embedded Python interpreter (the one that sees PyGObject and GTK4).
PYTHON="${PYTHON:-python3}"

# quick-sharun: the tool of the "Anylinux-AppImages" ecosystem
# (https://github.com/pkgforge-dev/Anylinux-AppImages) that bundles the
# libraries GTK4 and Python need - glibc included, which makes the AppImage
# independent of the distribution that runs it - then assembles the
# .AppImage file. It is downloaded at every build, but its SHA-256 checksum
# is verified: if the upstream script changes, the build stops instead of
# running code nobody has read (see the QUICK_SHARUN_URL /
# QUICK_SHARUN_SHA256 environment variables to adopt a new version after
# reviewing it). It in turn verifies the checksums of everything it then
# downloads (sharun, appimagetool...).
QUICK_SHARUN_URL="${QUICK_SHARUN_URL:-https://raw.githubusercontent.com/pkgforge-dev/Anylinux-AppImages/refs/heads/main/useful-tools/quick-sharun.sh}"
QUICK_SHARUN_SHA256="${QUICK_SHARUN_SHA256:-fa9dbe2532d568e1c1b8eeaba94d1c57109b776b5541d21b74d3f44b74faf4d3}"
# ===========================================================

show_help() {
    cat << EOF
Usage: ./build-appimage.sh [options]

Builds the Planche Contact AppImage (a single executable file, with Python,
GTK4 and every dependency bundled) and its SHA-256 checksum:

    Planche-Contact-<version>-${ARCH}.AppImage
    Planche-Contact-<version>-${ARCH}.AppImage.sha256

The version is the one in the VERSION file (run ./build-deb.sh first to bump
it, if needed: both packages then carry the same number).

OPTIONS:
  --test       After the build, checks the AppImage: command line (real
               generation of a PDF) then, if xvfb-run is installed, starts
               the graphical interface
  --clean      Deletes the working folder and the generated AppImages
  --help, -h   Show this help

PREREQUISITES (Debian / Ubuntu):
  sudo apt install python3 python3-venv python3-gi gir1.2-gtk-4.0 \\
       patchelf binutils curl strace   # + xvfb for --test

Building on Arch Linux is what the Anylinux-AppImages project recommends
(each distribution lays out its libraries its own way); Debian/Ubuntu works
but is not the tool's reference case.
See README.md, "AppImage" section.

ENVIRONMENT VARIABLES:
  APPIMAGE_BUILD_DIR   Working folder (default: ~/appimage-build)
  PYTHON               Python to bundle (default: python3)
  QUICK_SHARUN_URL     Address of quick-sharun
  QUICK_SHARUN_SHA256  Expected checksum of that script
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
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

run_test() {
    local image="$1" work photos
    work="$(mktemp -d)"
    photos="$work/photos"
    mkdir -p "$photos/subfolder"
    echo ">>> Checking $(basename "$image")..."

    # Three test photos, one of them in a subfolder. Pillow comes from the
    # dependencies folder of the build.
    PYTHONPATH="$SITE_DIR" "$BUILD_DIR/venv/bin/python3" - "$photos" << 'PYEOF'
import sys
from PIL import Image

root = sys.argv[1]
for name in ("alpha.jpg", "beta.jpg", "subfolder/gamma.jpg"):
    Image.new("RGB", (640, 480), (90, 140, 200)).save(f"{root}/{name}")
PYEOF

    export APPIMAGE_EXTRACT_AND_RUN=1
    local ok=true

    # 1. Command line: a real generation (PDF + CSV index).
    if "$image" portfolio -i "$photos" -o "$work/out" -r --pdf --csv --language en > "$work/cli.log" 2>&1 \
            && [ -s "$work/out/portfolio.pdf" ] && [ "$(wc -l < "$work/out/index.csv")" -eq 4 ]; then
        echo "    [OK] command line: PDF and CSV index generated"
    else
        echo "    [FAIL] command line (log: $work/cli.log)"
        ok=false
    fi

    # 2. Graphical interface: must stay open (code 124 = stopped by the
    # timeout, hence still alive; 137 = it did not stop on the first signal
    # and was killed 5 seconds later, which is just as good) - needs a
    # virtual display. Without --kill-after, a program that ignores the
    # first signal would block the test (and Ctrl+C) forever.
    if command -v xvfb-run > /dev/null 2>&1; then
        local status=0
        HOME="$work" timeout --kill-after=5 15 xvfb-run -a "$image" > "$work/gui.log" 2>&1 || status=$?
        if [ "$status" -eq 124 ] || [ "$status" -eq 137 ]; then
            echo "    [OK] graphical interface: starts and stays open"
        else
            echo "    [FAIL] graphical interface (code $status, log: $work/gui.log)"
            ok=false
        fi
    else
        echo "    [--] graphical interface not tested (xvfb-run missing: sudo apt install xvfb)"
    fi

    if [ "$ok" = true ]; then
        rm -rf "$work"
    else
        echo "    Test files kept in $work"
        return 1
    fi
}

# === Clean mode ===
if [ "$CLEAN" = true ]; then
    echo ">>> Cleaning the working folder ($BUILD_DIR)..."
    rm -rf "$BUILD_DIR"
    echo ">>> Deleting the generated AppImages and checksums..."
    rm -f "$PROJECT_DIR"/*.AppImage "$PROJECT_DIR"/*.AppImage.sha256
    echo ">>> Cleaning done."
    exit 0
fi

# === Checking the tools ===
missing=()
for tool in "$PYTHON" patchelf strings curl sha256sum tar; do
    command -v "$tool" > /dev/null 2>&1 || missing+=("$tool")
done
if [ "${#missing[@]}" -gt 0 ]; then
    echo "Error: missing tool(s): ${missing[*]}"
    echo "On Debian/Ubuntu: sudo apt install python3 python3-venv patchelf binutils curl"
    exit 1
fi
if ! "$PYTHON" -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk' 2> /dev/null; then
    echo "Error: PyGObject and GTK4 not found for $PYTHON."
    echo "On Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-4.0"
    exit 1
fi
if ! "$PYTHON" -c 'import venv, ensurepip' 2> /dev/null; then
    echo "Error: Python's venv module is incomplete."
    echo "On Debian/Ubuntu: sudo apt install python3-venv"
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

# The system's Python: it is the one that gets bundled (with PyGObject, which
# cannot be installed reliably through pip - see requirements.txt).
PYTHON_BIN="$(readlink -f "$(command -v "$PYTHON")")"
PY_MM="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_STDLIB="$("$PYTHON" -c 'import sysconfig; print(sysconfig.get_path("stdlib"))')"
GI_DIR="$("$PYTHON" -c 'import gi, os; print(os.path.dirname(gi.__file__))')"

echo ""
echo "========================================"
echo " AppImage $PACKAGE_NAME v$VERSION ($ARCH)"
echo " Python $PY_MM  -  $PYTHON_BIN"
echo " Working folder: $BUILD_DIR"
echo "========================================"
echo ""

rm -rf "$BUILD_DIR"
mkdir -p "$SHARE_DIR" "$APPDIR/bin" "$OUT_DIR" "$BUILD_DIR/tmp"

# === 1. The application sources (like build-deb.sh) ===
echo ">>> Copying the project files..."
(
    cd "$PROJECT_DIR"
    items=(planche-contact-gtk.py portfolio docs)
    # The license and the code of conduct (Contributor Covenant 3.0, under
    # CC-BY-SA-4.0, in both languages).
    for extra in LICENSE CODE_OF_CONDUCT.md CODE_OF_CONDUCT.fr.md; do
        if [ -f "$extra" ]; then
            items+=("$extra")
        fi
    done
    tar --exclude='__pycache__' -cf - "${items[@]}"
) | tar -xf - -C "$SHARE_DIR"
echo "$VERSION" > "$SHARE_DIR/VERSION"

# === 2. Python dependencies (pip) in a separate folder ===
echo ">>> Installing the Python dependencies (Pillow, reportlab, rawpy, exifread)..."
"$PYTHON" -m venv "$BUILD_DIR/venv"
PIP_LOG="$BUILD_DIR/pip.log"
if ! "$BUILD_DIR/venv/bin/pip" install --quiet --target "$SITE_DIR" \
        Pillow reportlab rawpy exifread > "$PIP_LOG" 2>&1; then
    echo "Error: installing the Python dependencies failed."
    sed 's/^/  /' "$PIP_LOG"
    exit 1
fi
rm -rf "$SITE_DIR/bin"

# PyGObject ("gi" module): the system's, compiled for this Python.
echo ">>> Copying PyGObject ($GI_DIR)..."
tar --exclude='__pycache__' -C "$(dirname "$GI_DIR")" -cf - "$(basename "$GI_DIR")" | tar -xf - -C "$SITE_DIR"

# === 3. The Python standard library ===
# quick-sharun knows how to bundle Python when the standard library is in
# the system's library folder (Arch); on Debian/Ubuntu it is in
# /usr/lib/pythonX.Y: it is therefore copied here, quick-sharun only taking
# care of the executable and the libraries it depends on.
echo ">>> Copying the Python standard library..."
mkdir -p "$APPDIR/lib"
tar -C "$(dirname "$PY_STDLIB")" -cf - \
    --exclude='__pycache__' --exclude='test' --exclude='tests' --exclude='idlelib' \
    --exclude='turtledemo' --exclude='tkinter' --exclude='lib2to3' --exclude='ensurepip' \
    --exclude='EXTERNALLY-MANAGED' "$(basename "$PY_STDLIB")" | tar -xf - -C "$APPDIR/lib"

# Extension modules that depend on a system library (other than libc): they
# are passed to quick-sharun so that it bundles those libraries. Excluded:
# SSL/hashlib (hashlib falls back to its internal versions), sqlite, curses,
# readline, tkinter and the dbm databases, which the application does not
# need.
EXTRA_LIBS=()
for module in "$PY_STDLIB"/lib-dynload/*.so; do
    case "$(basename "$module")" in
        _ssl.*|_hashlib.*|_tkinter.*|_sqlite3.*|_curses*|_dbm.*|_gdbm.*|readline.*) continue ;;
    esac
    # No "grep -q" here: it quits at the first match, and with "pipefail" the
    # SIGPIPE received by ldd would then make the test fail at random.
    if ldd "$module" 2> /dev/null | grep -v 'linux-vdso\|libc\.so\|libm\.so\|ld-linux\|libpython' | grep '=>' > /dev/null; then
        EXTRA_LIBS+=("$module")
    fi
done

# === 4. Launchers, icon, metadata ===
echo ">>> Creating the launchers, the .desktop file and the icon..."
cat > "$APPDIR/bin/planche-contact" << 'EOF'
#!/bin/sh
# Graphical interface: bundled Python + sources in share/planche-contact.
HERE="${APPDIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SHARE="$HERE/share/planche-contact"
export PYTHONPATH="$SHARE/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
# The bundled python by its full path, never "python3" through the PATH:
# depending on the machine, that would be another Python than the one the
# shipped modules were built for.
exec "$HERE/bin/@PYBIN@" "$SHARE/planche-contact-gtk.py" "$@"
EOF
cat > "$APPDIR/bin/portfolio" << 'EOF'
#!/bin/sh
# Command line: ./Planche-Contact-*.AppImage portfolio -i PHOTOS --pdf
HERE="${APPDIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SHARE="$HERE/share/planche-contact"
export PYTHONPATH="$SHARE/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
exec "$HERE/bin/@PYBIN@" "$SHARE/portfolio/portfolio.py" "$@"
EOF
sed -i "s|@PYBIN@|python$PY_MM|" "$APPDIR/bin/planche-contact" "$APPDIR/bin/portfolio"
chmod +x "$APPDIR/bin/planche-contact" "$APPDIR/bin/portfolio"

# Same Comment lines as the .desktop file of the .deb (build-deb.sh).
cat > "$BUILD_DIR/$PACKAGE_NAME.desktop" << 'EOF'
[Desktop Entry]
Name=Planche Contact
Comment=Photographic contact sheet generator
Comment[de]=Generator für fotografische Kontaktbögen
Comment[es]=Generador de hojas de contacto fotográficas
Comment[fr]=Générateur de planches contact photographiques
Exec=planche-contact
Icon=planche-contact
Terminal=false
Type=Application
Categories=Graphics;Photography;
StartupWMClass=com.planchecontact.gtk
EOF

ICON_SOURCE="$PROJECT_DIR/screenshots/application-icon.png"
if [ -f "$ICON_SOURCE" ]; then
    # Pillow (already installed above) avoids depending on ImageMagick.
    PYTHONPATH="$SITE_DIR" "$BUILD_DIR/venv/bin/python3" - "$ICON_SOURCE" "$BUILD_DIR/$PACKAGE_NAME.png" << 'PYEOF'
import sys
from PIL import Image

Image.open(sys.argv[1]).convert("RGBA").resize((256, 256), Image.LANCZOS).save(sys.argv[2], "PNG")
PYEOF
else
    echo "Warning: icon not found ($ICON_SOURCE) - AppImage without a custom icon." >&2
    exit 1
fi

if [ -f "$PROJECT_DIR/metainfo/$PACKAGE_NAME.metainfo.xml" ]; then
    mkdir -p "$APPDIR/share/metainfo"
    cp "$PROJECT_DIR/metainfo/$PACKAGE_NAME.metainfo.xml" "$APPDIR/share/metainfo/"
fi

# === 5. quick-sharun: libraries, glibc, GTK4, assembly ===
echo ">>> Downloading quick-sharun (checksum verification)..."
QUICK_SHARUN="$BUILD_DIR/quick-sharun.sh"
if ! curl -fsSL "$QUICK_SHARUN_URL" -o "$QUICK_SHARUN"; then
    echo "Error: quick-sharun could not be downloaded from:"
    echo "  $QUICK_SHARUN_URL"
    echo "Check the network connection and run again."
    exit 1
fi
if ! echo "$QUICK_SHARUN_SHA256  $QUICK_SHARUN" | sha256sum -c - > /dev/null 2>&1; then
    echo "Error: the checksum of quick-sharun does not match the expected one."
    echo "  expected: $QUICK_SHARUN_SHA256"
    echo "  obtained: $(sha256sum "$QUICK_SHARUN" | cut -d' ' -f1)"
    echo "The upstream script has changed since the last verification. Read it"
    echo "($QUICK_SHARUN), then run again with QUICK_SHARUN_SHA256=<new checksum>."
    exit 1
fi

# libgirepository and GTK4: loaded dynamically by PyGObject (.typelib
# files), hence invisible to the dependency analysis - they are named.
GI_EXT="$(ls "$SITE_DIR"/gi/_gi.*.so | head -n 1)"
# The awk commands below read their whole input instead of quitting at the
# first match ("exit"): with "pipefail", the SIGPIPE that ldconfig or ldd
# would receive on a long output (a machine with many libraries) made the
# whole script stop silently.
find_lib() {
    ldconfig -p 2> /dev/null | awk -v n="$1" '$1 == n && !found { print $NF; found = 1 }'
}
GIREPO_LIB="$(ldd "$GI_EXT" | awk '/libgirepository/ && !found { print $3; found = 1 }')"
GTK_LIB="$(find_lib libgtk-4.so.1)"
if [ -z "$GIREPO_LIB" ] || [ -z "$GTK_LIB" ]; then
    echo "Error: libgirepository or libgtk-4 not found (is GTK4 installed?)."
    exit 1
fi
# libanl: sharun preloads it; without a bundled copy, the machine's own
# would be loaded, with THIS machine's glibc (a different version from the
# bundled glibc). Absent from recent glibc versions: nothing to do then.
ANL_LIB="$(find_lib libanl.so.1)"
if [ -n "$ANL_LIB" ]; then
    EXTRA_LIBS+=("$ANL_LIB")
fi

echo ">>> Bundling the libraries and assembling the AppImage (a few minutes)..."
QS_LOG="$BUILD_DIR/quick-sharun.log"
if ! (
    cd "$BUILD_DIR"
    export TMPDIR="$BUILD_DIR/tmp"
    export APPDIR OUTPATH="$OUT_DIR" OUTNAME="$APPIMAGE_NAME"
    export MAIN_BIN=planche-contact
    export DESKTOP="$BUILD_DIR/$PACKAGE_NAME.desktop" ICON="$BUILD_DIR/$PACKAGE_NAME.png"
    export DEPLOY_GTK=1
    # GTK software rendering (Cairo): the interface needs neither OpenGL nor
    # Vulkan. This avoids bundling Mesa and LLVM (tens of MB) and depending
    # on the machine's graphics drivers - the classic cause of an AppImage
    # that starts here and not there.
    export ALWAYS_SOFTWARE=1
    # Without a bundled Mesa, libepoxy (GTK) still tries to open libEGL at
    # startup and would find the machine's, with its drivers, LLVM, etc.
    # (built for another glibc). It is prevented from doing so: GTK then
    # falls back, cleanly, on Cairo rendering, identical on every machine.
    export ANYLINUX_DO_NOT_LOAD_LIBS='libEGL*:libGL.so*:libGLdispatch*:libgbm*'
    # Python: its standard library is copied by hand (see 3); the executable
    # is passed as an argument like any binary.
    export STRACE_MODE=0
    export OUTPUT_APPIMAGE=1
    sh "$QUICK_SHARUN" "$PYTHON_BIN" "$GIREPO_LIB" "$GTK_LIB" "$GI_EXT" ${EXTRA_LIBS[@]+"${EXTRA_LIBS[@]}"}
) > "$QS_LOG" 2>&1; then
    echo "Error: quick-sharun failed. End of the log ($QS_LOG):"
    tail -n 25 "$QS_LOG" | sed 's/^/  /'
    exit 1
fi

if [ ! -f "$OUT_DIR/$APPIMAGE_NAME" ]; then
    echo "Error: $APPIMAGE_NAME was not produced (see $QS_LOG)."
    exit 1
fi

# === 6. Delivery: the AppImage and its checksum, at the project root ===
rm -f "$PROJECT_DIR"/*.AppImage "$PROJECT_DIR"/*.AppImage.sha256
cp "$OUT_DIR/$APPIMAGE_NAME" "$PROJECT_DIR/$APPIMAGE_NAME"
chmod +x "$PROJECT_DIR/$APPIMAGE_NAME"
(cd "$PROJECT_DIR" && sha256sum "$APPIMAGE_NAME" > "$APPIMAGE_NAME.sha256")

echo ""
echo "AppImage generated:"
ls -lh "$PROJECT_DIR/$APPIMAGE_NAME" | awk '{print "   " $5 "  " $NF}'
echo "   $(cat "$PROJECT_DIR/$APPIMAGE_NAME.sha256")"

# === 7. Optional check ===
if [ "$RUN_TEST" = true ]; then
    echo ""
    run_test "$PROJECT_DIR/$APPIMAGE_NAME"
fi
