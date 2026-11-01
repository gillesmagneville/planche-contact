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

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "French"

VIProductVersion "${PC_VERSION}.0"
VIAddVersionKey "ProductName" "Planche-Contact"
VIAddVersionKey "ProductVersion" "${PC_VERSION}"
VIAddVersionKey "CompanyName" "Gilles MAGNEVILLE"
VIAddVersionKey "LegalCopyright" "GNU GPL v3"
VIAddVersionKey "FileDescription" "Installeur Planche-Contact"
VIAddVersionKey "FileVersion" "${PC_VERSION}"

Section "Planche-Contact (obligatoire)" SecMain
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

Section "Raccourci menu Demarrer" SecStartMenu
    CreateDirectory "$SMPROGRAMS\Planche-Contact"
    CreateShortCut "$SMPROGRAMS\Planche-Contact\Planche-Contact.lnk" "$INSTDIR\planche-contact-gtk.exe"
    CreateShortCut "$SMPROGRAMS\Planche-Contact\Desinstaller.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section /o "Raccourci sur le Bureau" SecDesktop
    CreateShortCut "$DESKTOP\Planche-Contact.lnk" "$INSTDIR\planche-contact-gtk.exe"
SectionEnd

Section "Uninstall"
    RMDir /r "$INSTDIR"
    RMDir /r "$SMPROGRAMS\Planche-Contact"
    Delete "$DESKTOP\Planche-Contact.lnk"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\PlancheContact"
    DeleteRegKey HKLM "Software\Planche-Contact"
SectionEnd
