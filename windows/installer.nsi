; installer.nsi - Windows installer for Planche-Contact
;
; Called by build-windows.ps1, which first generates a small build-vars.nsh
; file (in this same folder) holding the following !define lines, before
; invoking makensis on this file:
;   PC_VERSION    version to display (e.g. 1.4.0)
;   PC_DIST_DIR   folder holding the frozen application (PyInstaller)
;   PC_OUTPUT     full path of the installer .exe to generate
;   PC_ICON       path to the .ico icon
;
; (the "!getenv" directive used in a previous version of this file
; does not exist in NSIS - the standard, documented way to pass values
; from outside is /D on the command line of makensis, equivalent to
; !define. A generated .nsh file is used here rather than /D directly,
; to avoid any escaping problem with paths containing spaces, for
; example
; "C:\Users\John Smith\...".)
;
; The installer speaks the four languages of the program. NSIS picks that of
; Windows; English, declared first, is used when Windows is in another
; language. The uninstaller picks the same way: the Start Menu shortcut to it
; therefore exists under four possible names (see SecStartMenu).
;
; This file is UTF-8 with a byte order mark (BOM), which NSIS requires to
; read accents; do not save it without a BOM.

Unicode true

!include "build-vars.nsh"

!ifndef PC_VERSION
  !define PC_VERSION "0.0.0"
!endif

Name "Planche-Contact"
OutFile "${PC_OUTPUT}"
InstallDir "$PROGRAMFILES64\Planche-Contact"
InstallDirRegKey HKLM "Software\Planche-Contact" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!include "MUI2.nsh"
!include "FileFunc.nsh"  ; for ${GetSize}, used further down (EstimatedSize)

!define MUI_ABORTWARNING
!define MUI_ICON "${PC_ICON}"
!define MUI_UNICON "${PC_ICON}"

; Components page: lets the user tick the optional shortcuts (Start Menu,
; Desktop). Without it the two optional sections below would never be offered
; (the Desktop one, unticked by default, could never be chosen). No
; description area: the three entries speak for themselves.
!define MUI_COMPONENTSPAGE_NODESC

; "Run Planche-Contact" box on the last page. The installer runs as
; administrator, and a program started directly from here would too: the
; function goes through Explorer instead (see LaunchProgram).
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchProgram

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; English first: it is the fallback language.
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "French"
!insertmacro MUI_LANGUAGE "Spanish"
!insertmacro MUI_LANGUAGE "German"

; Texts of the installer, in each language.
LangString SEC_MAIN ${LANG_ENGLISH} "Planche-Contact (required)"
LangString SEC_MAIN ${LANG_FRENCH}  "Planche-Contact (obligatoire)"
LangString SEC_MAIN ${LANG_SPANISH} "Planche-Contact (obligatorio)"
LangString SEC_MAIN ${LANG_GERMAN}  "Planche-Contact (erforderlich)"

LangString SEC_START_MENU ${LANG_ENGLISH} "Start Menu shortcut"
LangString SEC_START_MENU ${LANG_FRENCH}  "Raccourci du menu Démarrer"
LangString SEC_START_MENU ${LANG_SPANISH} "Acceso directo del menú Inicio"
LangString SEC_START_MENU ${LANG_GERMAN}  "Verknüpfung im Startmenü"

LangString SEC_DESKTOP ${LANG_ENGLISH} "Desktop shortcut"
LangString SEC_DESKTOP ${LANG_FRENCH}  "Raccourci sur le Bureau"
LangString SEC_DESKTOP ${LANG_SPANISH} "Acceso directo en el Escritorio"
LangString SEC_DESKTOP ${LANG_GERMAN}  "Verknüpfung auf dem Desktop"

LangString LNK_UNINSTALL ${LANG_ENGLISH} "Uninstall"
LangString LNK_UNINSTALL ${LANG_FRENCH}  "Désinstaller"
LangString LNK_UNINSTALL ${LANG_SPANISH} "Desinstalar"
LangString LNK_UNINSTALL ${LANG_GERMAN}  "Deinstallieren"

VIProductVersion "${PC_VERSION}.0"
!macro VersionKeys LANG DESCRIPTION
    VIAddVersionKey /LANG=${LANG} "ProductName" "Planche-Contact"
    VIAddVersionKey /LANG=${LANG} "ProductVersion" "${PC_VERSION}"
    VIAddVersionKey /LANG=${LANG} "CompanyName" "Gilles MAGNEVILLE"
    VIAddVersionKey /LANG=${LANG} "LegalCopyright" "GNU GPL v3"
    VIAddVersionKey /LANG=${LANG} "FileDescription" "${DESCRIPTION}"
    VIAddVersionKey /LANG=${LANG} "FileVersion" "${PC_VERSION}"
!macroend
!insertmacro VersionKeys ${LANG_ENGLISH} "Planche-Contact installer"
!insertmacro VersionKeys ${LANG_FRENCH}  "Installeur Planche-Contact"
!insertmacro VersionKeys ${LANG_SPANISH} "Instalador de Planche-Contact"
!insertmacro VersionKeys ${LANG_GERMAN}  "Installationsprogramm für Planche-Contact"

Section "$(SEC_MAIN)" SecMain
    SectionIn RO
    SetOutPath "$INSTDIR"
    File /r "${PC_DIST_DIR}\*.*"

    WriteRegStr HKLM "Software\Planche-Contact" "InstallDir" "$INSTDIR"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\PlancheContact" \
                 "DisplayName" "Planche-Contact"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\PlancheContact" \
                 "DisplayVersion" "${PC_VERSION}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\PlancheContact" \
                 "Publisher" "Gilles MAGNEVILLE"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\PlancheContact" \
                 "DisplayIcon" "$INSTDIR\planche-contact-gtk.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\PlancheContact" \
                 "UninstallString" "$INSTDIR\Uninstall.exe"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\PlancheContact" \
                  "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\PlancheContact" \
                  "NoRepair" 1

    ; Installed size, shown in Settings > Apps (the "Size" column). Without
    ; this value, Windows sometimes shows absurd sizes or nothing at all.
    ; Must be computed after all the files have been copied (File /r
    ; above).
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%X" $0
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\PlancheContact" \
                  "EstimatedSize" "$0"

    WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "$(SEC_START_MENU)" SecStartMenu
    CreateDirectory "$SMPROGRAMS\Planche-Contact"
    CreateShortCut "$SMPROGRAMS\Planche-Contact\Planche-Contact.lnk" "$INSTDIR\planche-contact-gtk.exe"
    ; The uninstaller shortcut bears the name of the language of the
    ; installation. An earlier installation, perhaps in another language,
    ; may have left it under another name (up to 5.2.1 the only one was
    ; "Desinstaller.lnk"): we delete all the possible names first, so that
    ; only one remains.
    Delete "$SMPROGRAMS\Planche-Contact\Desinstaller.lnk"
    Delete "$SMPROGRAMS\Planche-Contact\Uninstall.lnk"
    Delete "$SMPROGRAMS\Planche-Contact\Désinstaller.lnk"
    Delete "$SMPROGRAMS\Planche-Contact\Desinstalar.lnk"
    Delete "$SMPROGRAMS\Planche-Contact\Deinstallieren.lnk"
    CreateShortCut "$SMPROGRAMS\Planche-Contact\$(LNK_UNINSTALL).lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section /o "$(SEC_DESKTOP)" SecDesktop
    CreateShortCut "$DESKTOP\Planche-Contact.lnk" "$INSTDIR\planche-contact-gtk.exe"
SectionEnd

; Called by the box of the last page (never shown by a silent installation).
; "explorer.exe <program>" asks the Explorer already running in the user's
; session to open the program, which therefore starts with the user's rights
; and not with the administrator rights of the installer.
Function LaunchProgram
    Exec '"$WINDIR\explorer.exe" "$INSTDIR\planche-contact-gtk.exe"'
FunctionEnd

Section "Uninstall"
    RMDir /r "$INSTDIR"
    RMDir /r "$SMPROGRAMS\Planche-Contact"
    Delete "$DESKTOP\Planche-Contact.lnk"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\PlancheContact"
    DeleteRegKey HKLM "Software\Planche-Contact"
SectionEnd
