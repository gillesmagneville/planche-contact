; installer.nsi - Installeur Windows pour Planche-Contact
;
; Appele par build-windows.ps1, qui genere au prealable un petit fichier
; build-vars.nsh (dans ce meme dossier) contenant les !define suivants,
; avant d'invoquer makensis sur ce fichier :
;   PC_VERSION    version a afficher (ex: 1.4.0)
;   PC_DIST_DIR   dossier contenant l'application gelee (PyInstaller)
;   PC_OUTPUT     chemin complet du .exe installeur a generer
;   PC_ICON       chemin vers l'icone .ico
;
; (la directive "!getenv" utilisee dans une version precedente de ce
; fichier n'existe pas en NSIS - la methode standard et documentee pour
; faire passer des valeurs depuis l'exterieur est /D en ligne de commande
; de makensis, equivalent a !define. On passe ici par un fichier .nsh
; genere plutot que par /D directement, pour eviter tout probleme
; d'echappement avec des chemins contenant des espaces, par exemple
; "C:\Users\Jean Dupont\...".)

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
!include "FileFunc.nsh"  ; pour ${GetSize}, utilisé plus bas (EstimatedSize)

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

    ; Taille installée, affichée dans Parametres > Applications (colonne
    ; "Taille"). Sans cette valeur, Windows affiche parfois des tailles
    ; aberrantes ou n'affiche rien du tout. Doit être calculée après que
    ; tous les fichiers ont été copiés (File /r ci-dessus).
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
