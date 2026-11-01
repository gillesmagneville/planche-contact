#Requires -Version 5.1
<#
.SYNOPSIS
    Builds the Windows package of Planche-Contact (portable .zip version and,
    if NSIS is available, .exe installer).

.DESCRIPTION
    Windows equivalent of build-deb.sh: checks the prerequisites (Python, GTK4
    through gvsbuild, PyInstaller, NSIS), offers to install them automatically
    if they are missing, freezes the application with PyInstaller, then produces a
    portable .zip and, if NSIS is available, an .exe installer through NSIS.

    Unlike build-deb.sh, this script could not be tested on a real Windows
    machine when it was written; it has since been used on one to build the
    published packages (see windows\README.md).

.PARAMETER Major
    Bumps the major version number (e.g. 1.2.3 -> 2.0.0)
.PARAMETER Minor
    Bumps the minor version number (e.g. 1.2.3 -> 1.3.0)
.PARAMETER Patch
    Bumps the patch version number (e.g. 1.2.3 -> 1.2.4)
.PARAMETER NoVersionChange
    Rebuilds the package without changing the version
.PARAMETER Clean
    Cleans the build folder and deletes the generated .zip/.exe files
.PARAMETER Help
    Shows the help
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

# Script location: $MyInvocation.MyCommand.Path (falling back on
# $PSCommandPath) rather than $PSScriptRoot, the latter having proved
# unreliable when this script is invoked indirectly from the small relay
# script at the root of the repository (build-windows.ps1 -> windows\build-
# windows.ps1). This folder lives in windows/: the project is one level
# above.
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
Usage: .\build-windows.ps1 [options]

Builds the Windows package for Planche-Contact.

OPTIONS:
  -Major              Bumps the major number         (e.g. 1.2.3 -> 2.0.0)
  -Minor              Bumps the minor number         (e.g. 1.2.3 -> 1.3.0)
  -Patch              Bumps the patch number         (e.g. 1.2.3 -> 1.2.4)
  -NoVersionChange    Rebuilds the package without changing the version
  -Clean              Cleans the build folder and deletes the generated packages
  -Help               Shows this help

Without an argument -> interactive mode (asks major / minor / patch / no-version-change)

Prerequisites checked automatically (with an offer to install them if missing):
  - Python 3.10+
  - GTK4 (gvsbuild stack, downloaded and installed in C:\gtk if missing)
  - NSIS (optional: only needed to generate the .exe installer)
"@
}

if ($Help) { Show-Help; exit 0 }

# === Clean mode ===
if ($Clean) {
    Write-Host ">>> Cleaning the build folder..."
    if (Test-Path $BuildRoot) { Remove-Item -Recurse -Force $BuildRoot }
    Write-Host ">>> Deleting the generated packages..."
    Get-ChildItem -Path $ProjectDir -Filter "$PackageName*windows*" -File -ErrorAction SilentlyContinue | Remove-Item -Force
    Write-Host ">>> Cleaning done."
    exit 0
}

# === Reading the current version ===
Write-Host ">>> Project folder detected: $ProjectDir"
if (Test-Path $VersionFile) {
    $CurrentVersion = (Get-Content $VersionFile -Raw).Trim()
    Write-Host ">>> VERSION file found ($VersionFile): $CurrentVersion"
} else {
    $CurrentVersion = "1.0.0"
    Write-Host ""
    Write-Host "Warning: VERSION file not found at the expected location:" -ForegroundColor Yellow
    Write-Host "    $VersionFile"
    Write-Host "Fallback version used: $CurrentVersion (probably wrong - check"
    Write-Host "that the repository is complete at that location)."
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

# === Interactive mode if no argument ===
if (-not $Increment -and -not $NoVersionChange) {
    Write-Host ""
    Write-Host "Current version: $CurrentVersion"
    Write-Host ""
    Write-Host "What do you want to do?"
    Write-Host "  1) major              (-> $($MajorNum + 1).0.0)"
    Write-Host "  2) minor              (-> $MajorNum.$($MinorNum + 1).0)"
    Write-Host "  3) patch              (-> $MajorNum.$MinorNum.$($PatchNum + 1))"
    Write-Host "  4) no-version-change  (rebuild as $CurrentVersion)"
    Write-Host ""
    $choice = Read-Host "Your choice [1/2/3/4]"
    switch ($choice) {
        "1" { $Increment = "major" }
        "2" { $Increment = "minor" }
        "3" { $Increment = "patch" }
        "4" { $NoVersionChange = $true }
        default { Write-Host "Invalid choice. Cancelled."; exit 1 }
    }
}

# === Computing the new version ===
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
    Write-Host "  Mode           : Rebuild without changing the version"
    Write-Host "  Version        : $NewVersion"
} else {
    Write-Host "  Current version : $CurrentVersion"
    Write-Host "  New version     : $NewVersion"
}
Write-Host "========================================"
Write-Host ""
$confirm = Read-Host "Build the package in version $NewVersion? [y/N]"
if ($confirm -notmatch '^[yY]$') {
    Write-Host "Build cancelled. No file was modified."
    exit 0
}

# ====================== CHECKING THE PREREQUISITES ======================

Write-Host ""
Write-Host ">>> Checking the prerequisites..."

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
    Write-Host "Error: Python not found." -ForegroundColor Red
    Write-Host ""
    Write-Host "Install Python 3.10 or later from https://python.org"
    Write-Host "(tick 'Add python.exe to PATH' during the installation), or through winget:"
    Write-Host "    winget install Python.Python.3.12"
    Write-Host ""
    Write-Host "Then run this script again."
    exit 1
}
$pythonVersionStr = & $pythonCmd --version
Write-Host "  Python found: $pythonVersionStr ($pythonCmd)"

# This pipeline (gvsbuild, PyGObject/pycairo wheels, installer) is
# 64-bit only: a 32-bit Python would cause a confusing failure much
# further on (wheel incompatibility) - it is detected right away.
$pythonArch = & $pythonCmd -c "import struct; print(struct.calcsize('P') * 8)"
if ($pythonArch -ne "64") {
    Write-Host ""
    Write-Host "Error: 32-bit Python detected ($pythonCmd)." -ForegroundColor Red
    Write-Host ""
    Write-Host "This script only supports 64-bit Windows. Install a 64-bit version"
    Write-Host "of Python from https://python.org (the installer says"
    Write-Host "'Windows installer (64-bit)') or through winget:"
    Write-Host "    winget install Python.Python.3.12"
    Write-Host ""
    exit 1
}
Write-Host "  Python architecture: 64-bit (OK)"

# --- GTK4 (gvsbuild stack) ---
# The generic presence of DLLs in bin/ and of the PyGObject/pycairo wheels
# in wheels/ is checked, rather than a specific DLL file name: gvsbuild
# being built with MSVC (not MinGW), its DLLs do not necessarily have the
# "lib" prefix (e.g. gtk-4-1.dll, not libgtk-4-1.dll) - checking an exact
# name that cannot be guaranteed in advance caused a new download at every
# run, even when C:\gtk was already complete and valid.
$gtkBinHasDlls = (Test-Path "$GtkDir\bin") -and
    ((Get-ChildItem "$GtkDir\bin\*.dll" -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0)
$gtkWheelsPresent = (Test-Path "$GtkDir\wheels\PyGObject*.whl") -and (Test-Path "$GtkDir\wheels\pycairo*.whl")
if (-not $gtkBinHasDlls -or -not $gtkWheelsPresent) {
    Write-Host ""
    Write-Host "GTK4 (gvsbuild stack) not found in $GtkDir."
    $installGtk = Read-Host "Download and install it automatically now? [y/N]"
    if ($installGtk -match '^[yY]$') {
        Write-Host ">>> Looking for the latest gvsbuild version on GitHub..."
        try {
            $release = Invoke-RestMethod -Uri "https://api.github.com/repos/wingtk/gvsbuild/releases/latest"
            $asset = $release.assets | Where-Object { $_.name -match "^GTK4_Gvsbuild_.*_x64\.zip$" } | Select-Object -First 1
            if (-not $asset) {
                throw "No GTK4_Gvsbuild_*_x64.zip file found in the latest GitHub release."
            }
            $zipPath = "$env:TEMP\$($asset.name)"
            Write-Host ">>> Downloading $($asset.name) (several hundred MB, please wait)..."
            Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath
            Write-Host ">>> Extracting to $GtkDir..."
            if (-not (Test-Path $GtkDir)) { New-Item -ItemType Directory -Path $GtkDir -Force | Out-Null }
            Expand-Archive -Path $zipPath -DestinationPath $GtkDir -Force
            Remove-Item $zipPath -Force
            Write-Host ">>> GTK4 installed successfully in $GtkDir."
        } catch {
            Write-Host ""
            Write-Host "Error while downloading/installing GTK4: $_" -ForegroundColor Red
            Write-Host ""
            Write-Host "Manual installation:"
            Write-Host "    1) Download the GTK4_Gvsbuild_*_x64.zip file from:"
            Write-Host "       https://github.com/wingtk/gvsbuild/releases"
            Write-Host "    2) Unzip it into $GtkDir (the folder must contain bin/, lib/, wheels/...)"
            Write-Host "    3) Run this script again."
            exit 1
        }
    } else {
        Write-Host ""
        Write-Host "Build cancelled: GTK4 is required to build the application." -ForegroundColor Red
        Write-Host ""
        Write-Host "Manual installation:"
        Write-Host "    1) Download the GTK4_Gvsbuild_*_x64.zip file from:"
        Write-Host "       https://github.com/wingtk/gvsbuild/releases"
        Write-Host "    2) Unzip it into $GtkDir (the folder must contain bin/, lib/, wheels/...)"
        Write-Host "    3) Run this script again."
        exit 1
    }
} else {
    Write-Host "  GTK4 found in $GtkDir"
}

# --- Python <-> gvsbuild PyGObject/pycairo wheels compatibility -------------
# The wheels provided by gvsbuild are built for ONE specific Python version
# (e.g. cp314 = Python 3.14), not for "Python 3" in general. If the version
# detected above does not match, pip fails with an unclear message
# ("is not a supported wheel on this platform") much further on in the
# script: it is detected and fixed (or clearly explained) right away,
# before going on.
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
        Write-Host "The downloaded GTK4 package (gvsbuild) is built for Python $requiredVersion," -ForegroundColor Yellow
        Write-Host "but the detected interpreter is Python 3.$currentMinor ($pythonCmd)."

        # The "py" launcher allows several Python versions to be installed
        # side by side and a specific one to be chosen: we check whether the
        # required version is available that way before asking the user to
        # install anything.
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
            Write-Host "Python $requiredVersion found through the 'py' launcher: using it for this build." -ForegroundColor Green
            $PythonForVenv = @("py", "-$requiredVersion")
        } else {
            Write-Host ""
            Write-Host "Python $requiredVersion is not installed (required by this GTK4 package)." -ForegroundColor Yellow
            $installPy = Read-Host "Install it automatically through winget now? [y/N]"
            if ($installPy -match '^[yY]$') {
                try {
                    winget install --id "Python.Python.$requiredVersion" -e --accept-source-agreements --accept-package-agreements
                } catch {
                    Write-Host "Automatic installation through winget failed." -ForegroundColor Yellow
                }

                # Checking again: the 'py' launcher may need a short while
                # to see the newly installed version.
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
                Write-Host "Python $requiredVersion installed and detected successfully." -ForegroundColor Green
                $PythonForVenv = @("py", "-$requiredVersion")
            } else {
                Write-Host ""
                Write-Host "Error: Python $requiredVersion is still not available." -ForegroundColor Red
                Write-Host ""
                Write-Host "Manual installation:"
                Write-Host "    winget install --id Python.Python.$requiredVersion -e"
                Write-Host "or from https://python.org (version $requiredVersion, 64-bit)."
                Write-Host ""
                Write-Host "If you have just installed it, a new PowerShell window may be"
                Write-Host "needed for the 'py' launcher to detect it (the PATH is only read"
                Write-Host "again when a window is opened). Run this script again from"
                Write-Host "that new window."
                exit 1
            }
        }
    } else {
        Write-Host "  Python version compatible with the gvsbuild wheels (3.$requiredMinor)."
    }
} else {
    Write-Host "Warning: unable to determine the Python version required by the" -ForegroundColor Yellow
    Write-Host "gvsbuild wheels (unexpected file name) - going on with $pythonCmd as is."
}

# --- NSIS (optional: only for the .exe installer) ---
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
    Write-Host "NSIS not found (only needed to generate the .exe installer -"
    Write-Host "the portable .zip version will be produced in any case)."
    $installNsis = Read-Host "Install NSIS automatically through winget now? [y/N]"
    if ($installNsis -match '^[yY]$') {
        try {
            winget install --id NSIS.NSIS -e --accept-source-agreements --accept-package-agreements
            foreach ($candidate in $nsisCandidates) {
                if (Test-Path $candidate -ErrorAction SilentlyContinue) { $nsisCmd = $candidate; break }
            }
        } catch {
            Write-Host "Automatic installation of NSIS through winget failed." -ForegroundColor Yellow
        }
    }
    if (-not $nsisCmd) {
        Write-Host ""
        Write-Host "NSIS not available: only the portable version (.zip) will be generated." -ForegroundColor Yellow
        Write-Host "To generate the .exe installer too, install NSIS from:"
        Write-Host "    https://nsis.sourceforge.io/Download"
        Write-Host "then run this script again."
        $buildInstaller = $false
    }
} else {
    Write-Host "  NSIS found: $nsisCmd"
}

# ====================== BUILD ======================

Write-Host ""
Write-Host "========================================"
Write-Host " Building $PackageName v$NewVersion (Windows)"
Write-Host "========================================"

if (Test-Path $BuildRoot) { Remove-Item -Recurse -Force $BuildRoot }
New-Item -ItemType Directory -Path $VenvDir -Force | Out-Null
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null

Write-Host ">>> Creating the virtual environment..."
# Explicit construction rather than array slicing by index range (the
# former version could, depending on the context, fail to pass "-m venv"
# correctly to the interpreter, which then started in interactive mode
# instead of creating the venv).
if ($PythonForVenv.Count -gt 1) {
    Write-Host "    Command: $($PythonForVenv[0]) $($PythonForVenv[1]) -m venv $VenvDir"
    & $PythonForVenv[0] $PythonForVenv[1] -m venv $VenvDir
} else {
    Write-Host "    Command: $($PythonForVenv[0]) -m venv $VenvDir"
    & $PythonForVenv[0] -m venv $VenvDir
}
if ($LASTEXITCODE -ne 0 -or -not (Test-Path "$VenvDir\Scripts\python.exe")) {
    Write-Host ""
    Write-Host "Error: creating the virtual environment failed (venv missing after" -ForegroundColor Red
    Write-Host "running the command above)."
    exit 1
}
Write-Host ">>> Virtual environment created successfully."

$venvPython = "$VenvDir\Scripts\python.exe"
$venvPip = "$VenvDir\Scripts\pip.exe"

Write-Host ">>> Installing the Python dependencies..."
& $venvPython -m pip install --upgrade pip --quiet

$pipLog = "$env:TEMP\planche-contact-pip.log"
& $venvPip install Pillow reportlab rawpy exifread pyinstaller --quiet *> $pipLog
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Error: installing the Python dependencies failed." -ForegroundColor Red
    Write-Host ""
    Write-Host "Details:"
    Get-Content $pipLog | ForEach-Object { Write-Host "    $_" }
    Write-Host ""
    Write-Host "Possible causes: no network connection, PyPI mirror unreachable,"
    Write-Host "or an architecture not covered by rawpy's binary wheels."
    Write-Host ""
    Write-Host "Build cancelled: no incomplete package was generated."
    Remove-Item -Recurse -Force $BuildRoot -ErrorAction SilentlyContinue
    exit 1
}
Write-Host ">>> Python dependencies installed (Pillow, reportlab, rawpy, exifread, pyinstaller)."

# Adding C:\gtk\bin to the PATH for the whole duration of the build:
# recommended by gvsbuild itself, needed for "import gi" to work in the
# subprocesses PyInstaller launches to introspect the GTK modules
# (without it, PyInstaller falls back on a less precise mode, with
# "Failed to query GI module" warnings - not blocking, but cleaner to
# fix).
$env:Path = "$GtkDir\bin;$env:Path"

Write-Host ">>> Installing PyGObject/PyCairo (gvsbuild wheels)..."
$pygobjectWheel = Get-ChildItem "$GtkDir\wheels\PyGObject*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
$pycairoWheel = Get-ChildItem "$GtkDir\wheels\pycairo*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $pygobjectWheel -or -not $pycairoWheel) {
    Write-Host ""
    Write-Host "Error: PyGObject/pycairo wheels not found in $GtkDir\wheels\" -ForegroundColor Red
    Write-Host "Check that $GtkDir really holds a complete gvsbuild installation"
    Write-Host "(the wheels\ folder must contain PyGObject*.whl and pycairo*.whl)."
    Remove-Item -Recurse -Force $BuildRoot -ErrorAction SilentlyContinue
    exit 1
}
& $venvPip install --force-reinstall $pygobjectWheel.FullName $pycairoWheel.FullName --quiet

Write-Host ">>> Copying the project files..."
Copy-Item "$ProjectDir\planche-contact-gtk.py" "$WorkDir\" -Force
Copy-Item "$ProjectDir\portfolio" "$WorkDir\portfolio" -Recurse -Force
# The four manuals (French: planche-contact-manual.html; English, German,
# Spanish: planche-contact-manual.<language>.html). The "Help" tab opens the
# one for the interface language and falls back to the French manual if it
# is missing: all of them must therefore be shipped.
New-Item -ItemType Directory -Path "$WorkDir\docs" -Force | Out-Null
$manuals = @(Get-ChildItem "$ProjectDir\docs\planche-contact-manual*.html" -File -ErrorAction SilentlyContinue)
if ($manuals.Count -eq 0) {
    Write-Host "Warning: no manual (docs\planche-contact-manual*.html) found - build without a manual." -ForegroundColor Yellow
} else {
    foreach ($manual in $manuals) {
        Copy-Item $manual.FullName "$WorkDir\docs\" -Force
    }
}
if (Test-Path "$ProjectDir\LICENSE") {
    Copy-Item "$ProjectDir\LICENSE" "$WorkDir\" -Force
}
# The project documentation, in both languages: English by default (README.md,
# CHANGELOG.md, CODE_OF_CONDUCT.md) and French (the same names with .fr.md).
foreach ($doc in @("README.md", "README.fr.md", "CHANGELOG.md", "CHANGELOG.fr.md", "CODE_OF_CONDUCT.md", "CODE_OF_CONDUCT.fr.md")) {
    if (Test-Path "$ProjectDir\$doc") {
        Copy-Item "$ProjectDir\$doc" "$WorkDir\" -Force
    }
}
Set-Content -Path "$WorkDir\VERSION" -Value $NewVersion -NoNewline

Write-Host ">>> Converting the icon (.png -> .ico)..."
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
    Write-Host ">>> Icon converted: $iconIco"
} else {
    Write-Host "Warning: source icon not found ($iconSource) - build without a custom icon." -ForegroundColor Yellow
}

Write-Host ">>> Freezing the application with PyInstaller (may take several minutes)..."
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
        throw "PyInstaller failed (code $LASTEXITCODE)."
    }
} catch {
    Write-Host ""
    Write-Host "Error: the PyInstaller build failed: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "This step is the most fragile of the Windows port (bundling of GTK4)."
    Write-Host "See windows\README.md for the usual troubleshooting tips."
    Pop-Location
    exit 1
} finally {
    Pop-Location
}

$appDistDir = "$DistDir\$PackageName"
if (-not (Test-Path $appDistDir)) {
    Write-Host ""
    Write-Host "Error: PyInstaller output folder not found ($appDistDir)." -ForegroundColor Red
    exit 1
}
Write-Host ">>> Application frozen successfully in $appDistDir"

# --- Portable version (.zip) ---
Write-Host ">>> Creating the portable version (.zip)..."
$portableZip = "$ProjectDir\${PackageName}_${NewVersion}_windows-portable.zip"
if (Test-Path $portableZip) { Remove-Item $portableZip -Force }
Compress-Archive -Path "$appDistDir\*" -DestinationPath $portableZip -Force
Write-Host ">>> Portable version created: $portableZip"

# --- Installer (.exe, if NSIS is available) ---
if ($buildInstaller) {
    Write-Host ">>> Creating the installer (.exe) with NSIS..."
    $installerOutput = "$ProjectDir\${PackageName}_${NewVersion}_windows-setup.exe"

    # NSIS has no "!getenv" directive (contrary to what a previous
    # version of this script assumed): the standard, documented way
    # to pass values from outside is /D on the command line
    # (equivalent to !define). A generated .nsh file is used here
    # rather than /D directly on the command line, to avoid any
    # escaping problem with paths containing spaces
    # (e.g. "C:\Users\John Smith\...").
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
        Write-Host "Warning: NSIS failed (code $LASTEXITCODE) - the .exe installer was not created." -ForegroundColor Yellow
        Write-Host "The portable version (.zip) is still available."
    } else {
        Write-Host ">>> Installer created: $installerOutput"
    }
    Remove-Item "$WindowsDir\build-vars.nsh" -Force -ErrorAction SilentlyContinue
}

# ====================== END ======================

Write-Host ""
Write-Host "Package(s) generated:"
Write-Host "   $portableZip"
if ($buildInstaller -and (Test-Path "$ProjectDir\${PackageName}_${NewVersion}_windows-setup.exe")) {
    Write-Host "   $ProjectDir\${PackageName}_${NewVersion}_windows-setup.exe"
}

# The project's VERSION file is only updated here, once the build has
# really finished - a failure along the way never leaves the project
# in an inconsistent state (VERSION bumped without a matching
# package).
if ($NoVersionChange) {
    Write-Host "   Version unchanged: $NewVersion"
} else {
    Set-Content -Path $VersionFile -Value $NewVersion -NoNewline
    Write-Host "   Version recorded: $NewVersion"
}
