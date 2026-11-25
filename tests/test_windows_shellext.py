# -*- coding: utf-8 -*-
"""
Windows Explorer context menu ("Open in Planche-Contact").

The DLL, the package and the scripts can only really be exercised on Windows
(see windows/README.md). What can be checked anywhere is that the files that
must agree with each other still do: the supported photo formats, the name of
the temporary list file, the identifiers shared by the C++ build, the package
manifest, the embedded manifest and the registration scripts, and the
encoding rules that Windows PowerShell 5.1 and NSIS impose on the sources.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from portfolio.launch import SELECTION_FILE_PREFIX
from portfolio.scanner import ImageScanner

REPO = Path(__file__).resolve().parent.parent
WINDOWS = REPO / "windows"
SHELLEXT = WINDOWS / "shellext"
CPP = (SHELLEXT / "planche_shellext.cpp").read_text(encoding="utf-8")
BUILD_SCRIPT = (WINDOWS / "build-shellext.ps1").read_text(encoding="utf-8")
TEMPLATE_PATH = SHELLEXT / "AppxManifest.template.xml"


def _build_constant(name):
    match = re.search(rf'^\${name}\s*=\s*"([^"]+)"', BUILD_SCRIPT, re.MULTILINE)
    assert match, f"{name} not found in build-shellext.ps1"
    return match.group(1)


# ====================== values shared with the application ======================


def test_dll_photo_formats_match_the_scanner():
    block = re.search(r"kPhotoExtensions\[\]\s*=\s*\{(.*?)\};", CPP, re.DOTALL).group(1)
    in_dll = set(re.findall(r'L"(\.[a-z0-9]+)"', block))
    assert in_dll == set(ImageScanner.SUPPORTED_EXTENSIONS)


def test_dll_list_file_prefix_matches_the_application():
    in_dll = re.search(r'kListPrefix\[\]\s*=\s*L"([^"]+)"', CPP).group(1)
    assert in_dll == SELECTION_FILE_PREFIX


def test_dll_starts_the_application_with_paths_from():
    assert "--paths-from" in CPP
    assert "planche-contact-gtk.exe" in CPP


def test_dll_exports_the_com_entry_points():
    exports = (SHELLEXT / "planche_shellext.def").read_text(encoding="utf-8")
    assert "DllGetClassObject" in exports and "DllCanUnloadNow" in exports
    assert "STDAPI DllGetClassObject" in CPP and "STDAPI DllCanUnloadNow" in CPP


# ====================== identifiers shared by the build and the scripts ======================


def test_the_clsid_is_defined_once_and_only_in_the_build_script():
    clsid = _build_constant("Clsid")
    assert re.fullmatch(r"\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}", clsid)
    bare = clsid.strip("{}").lower()
    for path in [*SHELLEXT.iterdir(), WINDOWS / "installer.nsi", WINDOWS / "build-windows.ps1"]:
        assert bare not in path.read_text(encoding="utf-8-sig", errors="ignore").lower(), path.name
    assert bare in BUILD_SCRIPT.lower()


def test_the_cpp_gets_its_clsid_from_the_generated_header():
    assert '#include "pc_clsid.h"' in CPP
    assert "PC_CLSID_STRING" in BUILD_SCRIPT
    assert 'planche_shellext.def' in BUILD_SCRIPT and 'planche_shellext.rc' in BUILD_SCRIPT


def test_the_rc_embeds_the_manifest_the_build_script_generates():
    rc = (SHELLEXT / "planche_shellext.rc").read_text(encoding="utf-8")
    assert '2 24 "planche_shellext.manifest"' in rc
    assert "planche_shellext.manifest" in BUILD_SCRIPT


def test_embedded_manifest_and_package_share_name_publisher_and_application_id():
    # the three values come from the same variables of the build script
    assert 'publisher="$CertSubject"' in BUILD_SCRIPT
    assert 'packageName="$PackageName"' in BUILD_SCRIPT
    assert 'applicationId="$AppId"' in BUILD_SCRIPT
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    assert 'Name="@PACKAGE_NAME@" Publisher="@PUBLISHER@"' in template
    assert '<Application Id="@APP_ID@"' in template
    assert '.Replace("@PUBLISHER@", $CertSubject)' in BUILD_SCRIPT
    assert '.Replace("@PACKAGE_NAME@", $PackageName)' in BUILD_SCRIPT
    assert '.Replace("@APP_ID@", $AppId)' in BUILD_SCRIPT


def test_the_package_manifest_template():
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    root = ET.fromstring(text)  # well-formed
    placeholders = set(re.findall(r"@[A-Z_]+@", text))
    assert placeholders == {"@PACKAGE_NAME@", "@PUBLISHER@", "@VERSION@", "@APP_ID@", "@CLSID@"}
    for placeholder in placeholders:
        assert placeholder in BUILD_SCRIPT, f"{placeholder} is never replaced by build-shellext.ps1"

    ns = {
        "p": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
        "uap10": "http://schemas.microsoft.com/appx/manifest/uap/windows10/10",
        "d4": "http://schemas.microsoft.com/appx/manifest/desktop/windows10/4",
        "d5": "http://schemas.microsoft.com/appx/manifest/desktop/windows10/5",
        "com": "http://schemas.microsoft.com/appx/manifest/com/windows10",
    }
    # a sparse package: external content allowed
    assert root.find("p:Properties/uap10:AllowExternalContent", ns).text == "true"
    app = root.find("p:Applications/p:Application", ns)
    assert app.get("{%s}TrustLevel" % ns["uap10"]) == "mediumIL"
    assert app.get("{%s}RuntimeBehavior" % ns["uap10"]) == "win32App"
    # first level of the Windows 11 menu: photos (any file) and folders
    item_types = app.findall(".//d4:FileExplorerContextMenus/d5:ItemType", ns)
    assert {item.get("Type") for item in item_types} == {"*", "Directory"}
    clsids = {verb.get("Clsid") for item in item_types for verb in item.findall("d5:Verb", ns)}
    # the COM class behind the verb, declared in the manifest, same CLSID
    com_class = app.find(".//com:SurrogateServer/com:Class", ns)
    assert clsids == {com_class.get("Id")} == {"@CLSID@"}
    assert com_class.get("Path") == "planche_shellext.dll"


# ====================== the pieces of the package fit together ======================


def test_the_scripts_copied_by_the_build_exist():
    listed = re.findall(r'"((?:un)?register-context-menu\.(?:ps1|cmd))"', BUILD_SCRIPT)
    assert len(listed) == 4
    for name in listed:
        assert (SHELLEXT / name).is_file(), name


def test_the_installer_calls_the_scripts_the_build_ships():
    nsi = (WINDOWS / "installer.nsi").read_text(encoding="utf-8-sig")
    assert "register-context-menu.ps1" in nsi and "unregister-context-menu.ps1" in nsi
    # the DLLs the installer moves aside before an update are the ones built
    for dll in ("planche_shellext.dll", "planche_shellext_classic.dll"):
        assert f'MoveAsideDll "{dll}"' in nsi
        assert dll in BUILD_SCRIPT
    # the string of the optional component exists in the four languages
    for language in ("ENGLISH", "FRENCH", "SPANISH", "GERMAN"):
        assert f"LangString SEC_CONTEXT_MENU ${{LANG_{language}}}" in nsi


def test_build_windows_calls_the_shellext_build_without_depending_on_it():
    build = (WINDOWS / "build-windows.ps1").read_text(encoding="utf-8")
    call = build.index("build-shellext.ps1")
    assert "try {" in build[call - 200:call]          # a failure must not stop the build
    assert "catch" in build[call:call + 600]
    # and it runs after the freeze, before the zip and the installer are made
    assert build.index("Application frozen successfully") < call < build.index("Creating the portable version")


# ====================== encodings ======================


def test_windows_powershell_scripts_are_pure_ascii():
    """Windows PowerShell 5.1 reads a script without a byte order mark as ANSI:
    any accent or typographic quote would be garbled. The scripts stay ASCII."""
    scripts = [*WINDOWS.rglob("*.ps1"), *WINDOWS.rglob("*.cmd")]
    assert len(scripts) >= 6
    for script in scripts:
        data = script.read_bytes()
        assert not data.startswith(b"\xef\xbb\xbf"), f"{script.name}: unexpected byte order mark"
        data.decode("ascii")  # raises on any accent


def test_the_cpp_source_is_pure_ascii():
    """Written with \\u escapes: it compiles the same whatever the compiler's
    source character set."""
    (SHELLEXT / "planche_shellext.cpp").read_bytes().decode("ascii")


def test_cmd_wrappers_use_windows_line_endings():
    for name in ("register-context-menu.cmd", "unregister-context-menu.cmd"):
        data = (SHELLEXT / name).read_bytes()
        assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""), name


def test_installer_keeps_its_byte_order_mark():
    """NSIS needs it to read the accents of the French/Spanish/German texts."""
    assert (WINDOWS / "installer.nsi").read_bytes().startswith(b"\xef\xbb\xbf")
