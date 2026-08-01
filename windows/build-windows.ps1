#Requires -Version 5.1
<#
.SYNOPSIS
    Construit le paquet Windows de Planche-Contact (version portable .zip et,
    si NSIS est disponible, installeur .exe).

.DESCRIPTION
    Equivalent Windows de build-deb.sh : verifie les prerequis (Python, GTK4
    via gvsbuild, PyInstaller, NSIS), propose de les installer automatiquement
    s'ils manquent, gele l'application avec PyInstaller, puis produit un .zip
    portable et, si NSIS est disponible, un installeur .exe via NSIS.

    A la difference de build-deb.sh, ce script n'a pu etre teste sur une
    vraie machine Windows au moment de sa redaction : des ajustements seront
    tres probablement necessaires apres un premier essai reel.

.PARAMETER Major
    Incremente le numero de version majeur (ex: 1.2.3 -> 2.0.0)
.PARAMETER Minor
    Incremente le numero de version mineur (ex: 1.2.3 -> 1.3.0)
.PARAMETER Patch
    Incremente le numero de version de patch (ex: 1.2.3 -> 1.2.4)
.PARAMETER NoVersionChange
    Reconstruit le paquet sans changer la version
.PARAMETER Clean
    Nettoie le dossier de build et supprime les .zip/.exe generes
.PARAMETER Help
    Affiche l'aide
#>

param(
    [switch]$Major,
    [switch]$Minor,
    [switch]$Patch,
    [switch]$NoVersionChange,
    [switch]$Clean,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

# ====================== CONFIGURATION ======================
$PackageName = "planche-contact"
$Publisher   = "Gilles MAGNEVILLE"

# Localisation du script : $MyInvocation.MyCommand.Path (avec repli sur
# $PSCommandPath) plutot que $PSScriptRoot, ce dernier s'etant avere peu
# fiable lorsque ce script est invoque indirectement depuis le petit script
# relais place a la racine du depot (build-windows.ps1 -> windows\build-
# windows.ps1). Ce dossier vit dans windows/ : le projet est un niveau
# au-dessus.
$ScriptPath = $MyInvocation.MyCommand.Path
if (-not $ScriptPath) { $ScriptPath = $PSCommandPath }
$WindowsDir  = Split-Path -Parent $ScriptPath
$ProjectDir  = Split-Path -Parent $WindowsDir

$BuildRoot   = "$env:LOCALAPPDATA\planche-contact-build"
$GtkDir      = "C:\gtk"
$VenvDir     = "$BuildRoot\venv"
$WorkDir     = "$BuildRoot\work"
$PyInstallerWork = "$BuildRoot\pyinstaller-work"
$DistDir     = "$BuildRoot\dist"
$VersionFile = "$ProjectDir\VERSION"
# =============================================================

function Show-Help {
    @"
Usage : .\build-windows.ps1 [options]

Script de construction du paquet Windows pour Planche-Contact.

OPTIONS :
  -Major              Incremente le numero majeur   (ex: 1.2.3 -> 2.0.0)
  -Minor              Incremente le numero mineur   (ex: 1.2.3 -> 1.3.0)
  -Patch              Incremente le numero de patch (ex: 1.2.3 -> 1.2.4)
  -NoVersionChange    Reconstruit le paquet sans changer la version
  -Clean              Nettoie le dossier de build et supprime les paquets generes
  -Help               Affiche cette aide

Sans argument -> mode interactif (demande major / minor / patch / no-version-change)

Prerequis verifies automatiquement (avec proposition d'installation si absents) :
  - Python 3.10+
  - GTK4 (pile gvsbuild, telechargee et installee dans C:\gtk si absente)
  - NSIS (facultatif : necessaire uniquement pour generer l'installeur .exe)
"@
}

if ($Help) { Show-Help; exit 0 }

# === Mode nettoyage ===
if ($Clean) {
    Write-Host ">>> Nettoyage du dossier de build..."
    if (Test-Path $BuildRoot) { Remove-Item -Recurse -Force $BuildRoot }
    Write-Host ">>> Suppression des paquets generes..."
    Get-ChildItem -Path $ProjectDir -Filter "$PackageName*windows*" -File -ErrorAction SilentlyContinue | Remove-Item -Force
    Write-Host ">>> Nettoyage termine."
    exit 0
}

# === Lecture de la version actuelle ===
Write-Host ">>> Dossier du projet detecte : $ProjectDir"
if (Test-Path $VersionFile) {
    $CurrentVersion = (Get-Content $VersionFile -Raw).Trim()
    Write-Host ">>> Fichier VERSION trouve ($VersionFile) : $CurrentVersion"
} else {
    $CurrentVersion = "1.0.0"
    Write-Host ""
    Write-Host "Attention : fichier VERSION introuvable a l'emplacement attendu :" -ForegroundColor Yellow
    Write-Host "    $VersionFile"
    Write-Host "Version de repli utilisee : $CurrentVersion (probablement incorrect - verifiez"
    Write-Host "que le depot est complet a cet emplacement)."
    Write-Host ""
}

$versionParts = $CurrentVersion.Split(".")
$MajorNum = [int]$versionParts[0]
$MinorNum = [int]$versionParts[1]
$PatchNum = [int]$versionParts[2]

$Increment = $null
if ($Major) { $Increment = "major" }
elseif ($Minor) { $Increment = "minor" }
elseif ($Patch) { $Increment = "patch" }

# === Mode interactif si aucun argument ===
if (-not $Increment -and -not $NoVersionChange) {
    Write-Host ""
    Write-Host "Version actuelle : $CurrentVersion"
    Write-Host ""
    Write-Host "Que souhaitez-vous faire ?"
    Write-Host "  1) major              (-> $($MajorNum + 1).0.0)"
    Write-Host "  2) minor              (-> $MajorNum.$($MinorNum + 1).0)"
    Write-Host "  3) patch              (-> $MajorNum.$MinorNum.$($PatchNum + 1))"
    Write-Host "  4) no-version-change  (reconstruire en $CurrentVersion)"
    Write-Host ""
    $choice = Read-Host "Votre choix [1/2/3/4]"
    switch ($choice) {
        "1" { $Increment = "major" }
        "2" { $Increment = "minor" }
        "3" { $Increment = "patch" }
        "4" { $NoVersionChange = $true }
        default { Write-Host "Choix invalide. Annulation."; exit 1 }
    }
}

# === Calcul de la nouvelle version ===
if ($NoVersionChange) {
    $NewVersion = $CurrentVersion
} else {
    switch ($Increment) {
        "major" { $MajorNum++; $MinorNum = 0; $PatchNum = 0 }
        "minor" { $MinorNum++; $PatchNum = 0 }
        "patch" { $PatchNum++ }
    }
    $NewVersion = "$MajorNum.$MinorNum.$PatchNum"
}

# === Confirmation ===
Write-Host ""
Write-Host "========================================"
if ($NoVersionChange) {
    Write-Host "  Mode           : Reconstruction sans changement de version"
    Write-Host "  Version        : $NewVersion"
} else {
    Write-Host "  Version actuelle : $CurrentVersion"
    Write-Host "  Nouvelle version : $NewVersion"
}
Write-Host "========================================"
Write-Host ""
$confirm = Read-Host "Construire le paquet en version $NewVersion ? [o/N]"
if ($confirm -notmatch '^[oOyY]$') {
    Write-Host "Construction annulee. Aucun fichier n'a ete modifie."
    exit 0
}

# ====================== VERIFICATION DES PREREQUIS ======================

Write-Host ""
Write-Host ">>> Verification des prerequis..."

# --- Python ---
$pythonCmd = $null
foreach ($cmd in @("python", "py")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $pythonCmd = $cmd
        break
    }
}
if (-not $pythonCmd) {
    Write-Host ""
    Write-Host "Erreur : Python est introuvable." -ForegroundColor Red
    Write-Host ""
    Write-Host "Installez Python 3.10 ou plus recent depuis https://python.org"
    Write-Host "(cochez 'Add python.exe to PATH' pendant l'installation), ou via winget :"
    Write-Host "    winget install Python.Python.3.12"
    Write-Host ""
    Write-Host "Puis relancez ce script."
    exit 1
}
$pythonVersionStr = & $pythonCmd --version
Write-Host "  Python trouve : $pythonVersionStr ($pythonCmd)"

# Ce pipeline (gvsbuild, roues PyGObject/pycairo, installeur) est
# exclusivement 64 bits : un Python 32 bits provoquerait un echec confus
# bien plus loin (incompatibilite de roue) - on le detecte tout de suite.
$pythonArch = & $pythonCmd -c "import struct; print(struct.calcsize('P') * 8)"
if ($pythonArch -ne "64") {
    Write-Host ""
    Write-Host "Erreur : Python 32 bits detecte ($pythonCmd)." -ForegroundColor Red
    Write-Host ""
    Write-Host "Ce script ne prend en charge que Windows 64 bits. Installez une version"
    Write-Host "64 bits de Python depuis https://python.org (le programme d'installation"
    Write-Host "precise 'Windows installer (64-bit)') ou via winget :"
    Write-Host "    winget install Python.Python.3.12"
    Write-Host ""
    exit 1
}
Write-Host "  Architecture Python : 64 bits (OK)"

# --- GTK4 (pile gvsbuild) ---
# On verifie la presence generique de DLL dans bin/ et des roues
# PyGObject/pycairo dans wheels/, plutot qu'un nom de fichier DLL precis :
# gvsbuild etant compile avec MSVC (pas MinGW), ses DLL n'ont pas forcement
# le prefixe "lib" (ex: gtk-4-1.dll, pas libgtk-4-1.dll) - verifier un nom
# exact au'on ne peut pas garantir a l'avance provoquait un retelechargement
# a chaque lancement, meme quand C:\gtk etait deja complet et valide.
$gtkBinHasDlls = (Test-Path "$GtkDir\bin") -and
    ((Get-ChildItem "$GtkDir\bin\*.dll" -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0)
$gtkWheelsPresent = (Test-Path "$GtkDir\wheels\PyGObject*.whl") -and (Test-Path "$GtkDir\wheels\pycairo*.whl")
if (-not $gtkBinHasDlls -or -not $gtkWheelsPresent) {
    Write-Host ""
    Write-Host "GTK4 (pile gvsbuild) est introuvable dans $GtkDir."
    $installGtk = Read-Host "Le telecharger et l'installer automatiquement maintenant ? [o/N]"
    if ($installGtk -match '^[oOyY]$') {
        Write-Host ">>> Recherche de la derniere version de gvsbuild sur GitHub..."
        try {
            $release = Invoke-RestMethod -Uri "https://api.github.com/repos/wingtk/gvsbuild/releases/latest"
            $asset = $release.assets | Where-Object { $_.name -match "^GTK4_Gvsbuild_.*_x64\.zip$" } | Select-Object -First 1
            if (-not $asset) {
                throw "Aucun fichier GTK4_Gvsbuild_*_x64.zip trouve dans la derniere publication GitHub."
            }
            $zipPath = "$env:TEMP\$($asset.name)"
            Write-Host ">>> Telechargement de $($asset.name) (plusieurs centaines de Mo, patientez)..."
            Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath
            Write-Host ">>> Extraction vers $GtkDir..."
            if (-not (Test-Path $GtkDir)) { New-Item -ItemType Directory -Path $GtkDir -Force | Out-Null }
            Expand-Archive -Path $zipPath -DestinationPath $GtkDir -Force
            Remove-Item $zipPath -Force
            Write-Host ">>> GTK4 installe avec succes dans $GtkDir."
        } catch {
            Write-Host ""
            Write-Host "Erreur lors du telechargement/installation de GTK4 : $_" -ForegroundColor Red
            Write-Host ""
            Write-Host "Installation manuelle :"
            Write-Host "    1) Telechargez le fichier GTK4_Gvsbuild_*_x64.zip depuis :"
            Write-Host "       https://github.com/wingtk/gvsbuild/releases"
            Write-Host "    2) Decompressez-le dans $GtkDir (le dossier doit contenir bin/, lib/, wheels/...)"
            Write-Host "    3) Relancez ce script."
            exit 1
        }
    } else {
        Write-Host ""
        Write-Host "Construction annulee : GTK4 est indispensable pour construire l'application." -ForegroundColor Red
        Write-Host ""
        Write-Host "Installation manuelle :"
        Write-Host "    1) Telechargez le fichier GTK4_Gvsbuild_*_x64.zip depuis :"
        Write-Host "       https://github.com/wingtk/gvsbuild/releases"
        Write-Host "    2) Decompressez-le dans $GtkDir (le dossier doit contenir bin/, lib/, wheels/...)"
        Write-Host "    3) Relancez ce script."
        exit 1
    }
} else {
    Write-Host "  GTK4 trouve dans $GtkDir"
}

# --- Compatibilite Python <-> roues PyGObject/pycairo de gvsbuild -----------
# Les roues fournies par gvsbuild sont compilees pour UNE version precise de
# Python (ex: cp314 = Python 3.14), pas "Python 3" en general. Si la version
# detectee plus haut ne correspond pas, pip echoue avec un message peu clair
# ("is not a supported wheel on this platform") bien plus loin dans le
# script : on le detecte et on le corrige (ou on l'explique clairement) tout
# de suite, avant de continuer.
$PythonForVenv = @($pythonCmd)

$pygobjectWheelCheck = Get-ChildItem "$GtkDir\wheels\PyGObject*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($pygobjectWheelCheck -and $pygobjectWheelCheck.Name -match "-cp3(\d+)-") {
    $requiredMinor = $matches[1]
    $requiredVersion = "3.$requiredMinor"

    $currentVersionOutput = & $pythonCmd --version 2>&1
    $currentMinor = $null
    if ($currentVersionOutput -match "Python 3\.(\d+)") {
        $currentMinor = $matches[1]
    }

    if ($currentMinor -ne $requiredMinor) {
        Write-Host ""
        Write-Host "Le paquet GTK4 telecharge (gvsbuild) est compile pour Python $requiredVersion," -ForegroundColor Yellow
        Write-Host "mais l'interpreteur detecte est Python 3.$currentMinor ($pythonCmd)."

        # Le lanceur "py" permet d'avoir plusieurs versions de Python
        # installees en parallele et d'en choisir une precisement : on
        # verifie si la version requise est disponible par ce biais avant
        # de demander a l'utilisateur d'installer quoi que ce soit.
        $foundViaLauncher = $false
        if (Get-Command py -ErrorAction SilentlyContinue) {
            try {
                $launcherTest = & py "-$requiredVersion" --version 2>&1
                if ($LASTEXITCODE -eq 0) {
                    $foundViaLauncher = $true
                }
            } catch {
                $foundViaLauncher = $false
            }
        }

        if ($foundViaLauncher) {
            Write-Host "Python $requiredVersion trouve via le lanceur 'py' : on l'utilise pour ce build." -ForegroundColor Green
            $PythonForVenv = @("py", "-$requiredVersion")
        } else {
            Write-Host ""
            Write-Host "Python $requiredVersion n'est pas installe (necessaire pour ce paquet GTK4)." -ForegroundColor Yellow
            $installPy = Read-Host "L'installer automatiquement via winget maintenant ? [o/N]"
            if ($installPy -match '^[oOyY]$') {
                try {
                    winget install --id "Python.Python.$requiredVersion" -e --accept-source-agreements --accept-package-agreements
                } catch {
                    Write-Host "Echec de l'installation automatique via winget." -ForegroundColor Yellow
                }

                # Reverification : le lanceur 'py' peut avoir besoin d'un
                # court instant pour voir la nouvelle version installee.
                $foundViaLauncher = $false
                if (Get-Command py -ErrorAction SilentlyContinue) {
                    try {
                        $launcherTest = & py "-$requiredVersion" --version 2>&1
                        if ($LASTEXITCODE -eq 0) {
                            $foundViaLauncher = $true
                        }
                    } catch {
                        $foundViaLauncher = $false
                    }
                }
            }

            if ($foundViaLauncher) {
                Write-Host "Python $requiredVersion installe et detecte avec succes." -ForegroundColor Green
                $PythonForVenv = @("py", "-$requiredVersion")
            } else {
                Write-Host ""
                Write-Host "Erreur : Python $requiredVersion n'est toujours pas disponible." -ForegroundColor Red
                Write-Host ""
                Write-Host "Installation manuelle :"
                Write-Host "    winget install --id Python.Python.$requiredVersion -e"
                Write-Host "ou depuis https://python.org (version $requiredVersion, 64 bits)."
                Write-Host ""
                Write-Host "Si vous venez de l'installer, une nouvelle fenetre PowerShell peut"
                Write-Host "etre necessaire pour que le lanceur 'py' la detecte (le PATH n'est"
                Write-Host "relu qu'a l'ouverture d'une fenetre). Relancez alors ce script depuis"
                Write-Host "cette nouvelle fenetre."
                exit 1
            }
        }
    } else {
        Write-Host "  Version Python compatible avec les roues gvsbuild (3.$requiredMinor)."
    }
} else {
    Write-Host "Attention : impossible de determiner la version Python requise par les" -ForegroundColor Yellow
    Write-Host "roues gvsbuild (nom de fichier inattendu) - poursuite avec $pythonCmd tel quel."
}

# --- NSIS (facultatif : uniquement pour l'installeur .exe) ---
$nsisCmd = $null
$nsisCandidates = @(
    "makensis",
    "${env:ProgramFiles(x86)}\NSIS\makensis.exe",
    "$env:ProgramFiles\NSIS\makensis.exe"
)
foreach ($candidate in $nsisCandidates) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) { $nsisCmd = $candidate; break }
    if (Test-Path $candidate -ErrorAction SilentlyContinue) { $nsisCmd = $candidate; break }
}

$buildInstaller = $true
if (-not $nsisCmd) {
    Write-Host ""
    Write-Host "NSIS est introuvable (necessaire uniquement pour generer l'installeur .exe -"
    Write-Host "la version portable .zip sera produite dans tous les cas)."
    $installNsis = Read-Host "Installer NSIS automatiquement via winget maintenant ? [o/N]"
    if ($installNsis -match '^[oOyY]$') {
        try {
            winget install --id NSIS.NSIS -e --accept-source-agreements --accept-package-agreements
            foreach ($candidate in $nsisCandidates) {
                if (Test-Path $candidate -ErrorAction SilentlyContinue) { $nsisCmd = $candidate; break }
            }
        } catch {
            Write-Host "Echec de l'installation automatique de NSIS via winget." -ForegroundColor Yellow
        }
    }
    if (-not $nsisCmd) {
        Write-Host ""
        Write-Host "NSIS non disponible : seule la version portable (.zip) sera generee." -ForegroundColor Yellow
        Write-Host "Pour generer aussi l'installeur .exe, installez NSIS depuis :"
        Write-Host "    https://nsis.sourceforge.io/Download"
        Write-Host "puis relancez ce script."
        $buildInstaller = $false
    }
} else {
    Write-Host "  NSIS trouve : $nsisCmd"
}

# ====================== CONSTRUCTION ======================

Write-Host ""
Write-Host "========================================"
Write-Host " Construction de $PackageName v$NewVersion (Windows)"
Write-Host "========================================"

if (Test-Path $BuildRoot) { Remove-Item -Recurse -Force $BuildRoot }
New-Item -ItemType Directory -Path $VenvDir -Force | Out-Null
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null

Write-Host ">>> Creation de l'environnement virtuel..."
# Construction explicite plutot que par decoupage de tableau par plage
# d'indices (l'ancienne version pouvait, selon le contexte, ne pas
# transmettre correctement "-m venv" a l'interpreteur, qui demarrait alors
# en mode interactif au lieu de creer le venv).
if ($PythonForVenv.Count -gt 1) {
    Write-Host "    Commande : $($PythonForVenv[0]) $($PythonForVenv[1]) -m venv $VenvDir"
    & $PythonForVenv[0] $PythonForVenv[1] -m venv $VenvDir
} else {
    Write-Host "    Commande : $($PythonForVenv[0]) -m venv $VenvDir"
    & $PythonForVenv[0] -m venv $VenvDir
}
if ($LASTEXITCODE -ne 0 -or -not (Test-Path "$VenvDir\Scripts\python.exe")) {
    Write-Host ""
    Write-Host "Erreur : la creation de l'environnement virtuel a echoue (venv absent apres" -ForegroundColor Red
    Write-Host "l'execution de la commande ci-dessus)."
    exit 1
}
Write-Host ">>> Environnement virtuel cree avec succes."

$venvPython = "$VenvDir\Scripts\python.exe"
$venvPip = "$VenvDir\Scripts\pip.exe"

Write-Host ">>> Installation des dependances Python..."
& $venvPython -m pip install --upgrade pip --quiet

$pipLog = "$env:TEMP\planche-contact-pip.log"
& $venvPip install Pillow reportlab rawpy exifread pyinstaller --quiet *> $pipLog
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Erreur : l'installation des dependances Python a echoue." -ForegroundColor Red
    Write-Host ""
    Write-Host "Detail :"
    Get-Content $pipLog | ForEach-Object { Write-Host "    $_" }
    Write-Host ""
    Write-Host "Causes possibles : pas de connexion reseau, miroir PyPI inaccessible,"
    Write-Host "ou architecture non couverte par les roues binaires de rawpy."
    Write-Host ""
    Write-Host "Construction annulee : aucun paquet incomplet n'a ete genere."
    Remove-Item -Recurse -Force $BuildRoot -ErrorAction SilentlyContinue
    exit 1
}
Write-Host ">>> Dependances Python installees (Pillow, reportlab, rawpy, exifread, pyinstaller)."

# Ajout de C:\gtk\bin au PATH pour toute la duree du build : recommande par
# gvsbuild lui-meme, necessaire pour que "import gi" fonctionne dans les
# sous-processus que PyInstaller lance pour introspecter les modules GTK
# (sans ca, PyInstaller se rabat sur un mode moins precis, avec des
# avertissements "Failed to query GI module" - pas bloquant, mais plus
# propre a corriger).
$env:Path = "$GtkDir\bin;$env:Path"

Write-Host ">>> Installation de PyGObject/PyCairo (roues gvsbuild)..."
$pygobjectWheel = Get-ChildItem "$GtkDir\wheels\PyGObject*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
$pycairoWheel = Get-ChildItem "$GtkDir\wheels\pycairo*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $pygobjectWheel -or -not $pycairoWheel) {
    Write-Host ""
    Write-Host "Erreur : roues PyGObject/pycairo introuvables dans $GtkDir\wheels\" -ForegroundColor Red
    Write-Host "Verifiez que $GtkDir contient bien une installation complete de gvsbuild"
    Write-Host "(le dossier wheels\ doit contenir PyGObject*.whl et pycairo*.whl)."
    Remove-Item -Recurse -Force $BuildRoot -ErrorAction SilentlyContinue
    exit 1
}
& $venvPip install --force-reinstall $pygobjectWheel.FullName $pycairoWheel.FullName --quiet

Write-Host ">>> Copie des fichiers du projet..."
Copy-Item "$ProjectDir\planche-contact-gtk.py" "$WorkDir\" -Force
Copy-Item "$ProjectDir\portfolio" "$WorkDir\portfolio" -Recurse -Force
New-Item -ItemType Directory -Path "$WorkDir\docs" -Force | Out-Null
if (Test-Path "$ProjectDir\docs\planche-contact-manual.html") {
    Copy-Item "$ProjectDir\docs\planche-contact-manual.html" "$WorkDir\docs\" -Force
}
if (Test-Path "$ProjectDir\LICENSE") {
    Copy-Item "$ProjectDir\LICENSE" "$WorkDir\" -Force
}
Set-Content -Path "$WorkDir\VERSION" -Value $NewVersion -NoNewline

Write-Host ">>> Conversion de l'icone (.png -> .ico)..."
$iconSource = "$ProjectDir\screenshots\application-icon.png"
$iconIco = "$WorkDir\icon.ico"
if (Test-Path $iconSource) {
    $iconScript = @"
import sys
from PIL import Image
img = Image.open(sys.argv[1]).convert('RGBA')
img.save(sys.argv[2], format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
"@
    $iconScriptPath = "$env:TEMP\planche_make_icon.py"
    Set-Content -Path $iconScriptPath -Value $iconScript
    & $venvPython $iconScriptPath $iconSource $iconIco
    Remove-Item $iconScriptPath -Force
    Write-Host ">>> Icone convertie : $iconIco"
} else {
    Write-Host "Attention : icone source introuvable ($iconSource) - build sans icone personnalisee." -ForegroundColor Yellow
}

Write-Host ">>> Gel de l'application avec PyInstaller (peut prendre plusieurs minutes)..."
$env:PLANCHE_WORK_DIR = $WorkDir
$env:PLANCHE_GTK_DIR = $GtkDir
$env:PLANCHE_ICON = $iconIco

Push-Location $WindowsDir
try {
    & $venvPython -m PyInstaller `
        --distpath $DistDir `
        --workpath $PyInstallerWork `
        --noconfirm `
        "planche-contact.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller a echoue (code $LASTEXITCODE)."
    }
} catch {
    Write-Host ""
    Write-Host "Erreur : la construction PyInstaller a echoue : $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Cette etape est la plus fragile du portage Windows (bundling de GTK4)."
    Write-Host "Consultez windows\README.md pour les pistes de depannage courantes."
    Pop-Location
    exit 1
} finally {
    Pop-Location
}

$appDistDir = "$DistDir\$PackageName"
if (-not (Test-Path $appDistDir)) {
    Write-Host ""
    Write-Host "Erreur : dossier de sortie PyInstaller introuvable ($appDistDir)." -ForegroundColor Red
    exit 1
}
Write-Host ">>> Application gelee avec succes dans $appDistDir"

# --- Version portable (.zip) ---
Write-Host ">>> Creation de la version portable (.zip)..."
$portableZip = "$ProjectDir\${PackageName}_${NewVersion}_windows-portable.zip"
if (Test-Path $portableZip) { Remove-Item $portableZip -Force }
Compress-Archive -Path "$appDistDir\*" -DestinationPath $portableZip -Force
Write-Host ">>> Version portable creee : $portableZip"

# --- Installeur (.exe, si NSIS disponible) ---
if ($buildInstaller) {
    Write-Host ">>> Creation de l'installeur (.exe) avec NSIS..."
    $installerOutput = "$ProjectDir\${PackageName}_${NewVersion}_windows-setup.exe"

    # NSIS n'a pas de directive "!getenv" (contrairement a ce qu'une
    # version precedente de ce script supposait) : la methode standard et
    # documentee pour transmettre des valeurs depuis l'exterieur est /D en
    # ligne de commande (equivalent a !define). On passe ici par un fichier
    # .nsh genere plutot que par /D directement sur la ligne de commande,
    # pour eviter tout probleme d'echappement avec des chemins contenant
    # des espaces (ex: "C:\Users\Jean Dupont\...").
    $nshContent = @"
!define PC_VERSION "$NewVersion"
!define PC_DIST_DIR "$appDistDir"
!define PC_OUTPUT "$installerOutput"
!define PC_ICON "$iconIco"
"@
    Set-Content -Path "$WindowsDir\build-vars.nsh" -Value $nshContent -Encoding UTF8

    & $nsisCmd "$WindowsDir\installer.nsi"
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "Attention : NSIS a echoue (code $LASTEXITCODE) - l'installeur .exe n'a pas ete cree." -ForegroundColor Yellow
        Write-Host "La version portable (.zip) reste disponible."
    } else {
        Write-Host ">>> Installeur cree : $installerOutput"
    }
    Remove-Item "$WindowsDir\build-vars.nsh" -Force -ErrorAction SilentlyContinue
}

# ====================== FIN ======================

Write-Host ""
Write-Host "Paquet(s) cree(s) avec succes :"
Write-Host "   $portableZip"
if ($buildInstaller -and (Test-Path "$ProjectDir\${PackageName}_${NewVersion}_windows-setup.exe")) {
    Write-Host "   $ProjectDir\${PackageName}_${NewVersion}_windows-setup.exe"
}

# Le fichier VERSION du projet n'est mis a jour qu'ici, une fois la
# construction reellement terminee - un echec en cours de route ne laisse
# jamais le projet dans un etat incoherent (VERSION incremente sans paquet
# correspondant).
if ($NoVersionChange) {
    Write-Host "   Version inchangee : $NewVersion"
} else {
    Set-Content -Path $VersionFile -Value $NewVersion -NoNewline
    Write-Host "   Version enregistree : $NewVersion"
}
