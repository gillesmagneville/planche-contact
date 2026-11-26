#Requires -Version 5.1
<#
.SYNOPSIS
    Builds the Windows Explorer context menu of Planche-Contact ("Open in
    Planche-Contact", right click on photos or folders).

.DESCRIPTION
    Called by build-windows.ps1 once the application is frozen; can also be run
    alone. Produces, in -OutDir (the folder of the frozen application):

      planche_shellext_classic.dll   the COM DLL (IExplorerCommand), registered
                                     the classic way: Windows 10, and the
                                     "Show more options" menu of Windows 11
      planche_shellext.dll           the same DLL with the package identity
                                     embedded, for the first level of the
                                     Windows 11 menu
      planche-contact-shell.msix     the sparse package declaring that DLL
      planche-contact-shell.cer      the public certificate that signed it
      shellext-info.json             the identifiers shared with the scripts
      register-context-menu.ps1 / .cmd, unregister-context-menu.ps1 / .cmd

    It needs the C++ build tools of Visual Studio ("Desktop development with
    C++" workload; build-windows.ps1 does not install them). The package
    additionally needs the Windows SDK
    (makeappx.exe, signtool.exe): without it, only the classic DLL and the
    scripts are produced and the first level of the Windows 11 menu will not be
    available (the classic menu still is). The package is signed with a
    self-signed certificate created once and kept in the "Current user >
    Personal" store of this machine: its private key never leaves it, and only
    the public .cer is shipped.

    Never stops the build of the application: build-windows.ps1 only reports a
    failure of this script.

.PARAMETER OutDir
    Folder of the frozen application, where the files are copied.
.PARAMETER Version
    Version of Planche-Contact (x.y.z).
.PARAMETER IconPng
    PNG icon of the application, for the logos of the package (optional).
.PARAMETER Python
    python.exe with Pillow, to resize the logos (optional).
.PARAMETER WorkDir
    Scratch folder (recreated).
#>

param(
    [Parameter(Mandatory = $true)][string]$OutDir,
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$IconPng,
    [string]$Python,
    [string]$WorkDir = "$env:TEMP\planche-contact-shellext"
)

$ErrorActionPreference = "Stop"

# ====================== IDENTIFIERS ======================
# Defined ONCE, here: injected in the C++ build (pc_clsid.h), in the manifest of
# the package and of the DLL, and written to shellext-info.json for the
# registration scripts. NEVER change the CLSID of a published version: the
# installed copies would keep registering the old one.
$Clsid       = "{F3A71A52-F1D6-4565-B0BC-9517786F4A73}"
$PackageName = "PlancheContact.ShellExtension"
$AppId       = "PlancheContactShell"
$CertSubject = "CN=Planche-Contact"
# =========================================================

$ShellExtDir = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "shellext"

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Invalid version '$Version' (x.y.z expected)."
}
$PackageVersion = "$Version.0"   # a package version has four numbers

function Find-VisualStudioBuildTools {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) { return $null }
    $path = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath
    if (-not $path) { return $null }
    $vcvars = Join-Path ($path | Select-Object -First 1) "VC\Auxiliary\Build\vcvars64.bat"
    if (Test-Path $vcvars) { return $vcvars }
    return $null
}

function Find-SdkTool([string]$name) {
    $kits = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (-not (Test-Path $kits)) { return $null }
    $found = Get-ChildItem "$kits\10.*\x64\$name" -ErrorAction SilentlyContinue |
        Sort-Object { [version]$_.Directory.Parent.Name } -Descending |
        Select-Object -First 1
    if ($found) { return $found.FullName }
    return $null
}

# --- Scratch folder and sources ---
if (Test-Path $WorkDir) { Remove-Item -Recurse -Force $WorkDir }
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
foreach ($file in @("planche_shellext.cpp", "planche_shellext.def", "planche_shellext.rc")) {
    Copy-Item (Join-Path $ShellExtDir $file) $WorkDir
}
Set-Content -Path "$WorkDir\pc_clsid.h" -Encoding ASCII -Value "#define PC_CLSID_STRING L`"$Clsid`""

# The manifest embedded in the DLL of the package: ties the DLL to the package
# (same name, publisher and application id as in AppxManifest.xml).
Set-Content -Path "$WorkDir\planche_shellext.manifest" -Encoding UTF8 -Value @"
<?xml version="1.0" encoding="utf-8"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <msix xmlns="urn:schemas-microsoft-com:msix.v1"
        publisher="$CertSubject"
        packageName="$PackageName"
        applicationId="$AppId" />
</assembly>
"@

# --- Compilation (MSVC) ---
$vcvars = Find-VisualStudioBuildTools
if (-not $vcvars) {
    throw "Visual Studio C++ build tools not found (needed to compile the context menu DLL)."
}
Write-Host ">>> Compiling the context menu DLLs (MSVC)..."
$libs = "ole32.lib shell32.lib shlwapi.lib uuid.lib user32.lib"
$cl = "cl /nologo /O2 /EHsc /std:c++17 /utf-8 /W3 /MT /LD /DUNICODE /D_UNICODE"
$buildCmd = "$WorkDir\build.cmd"
Set-Content -Path $buildCmd -Encoding ASCII -Value @"
@echo off
call "$vcvars" >nul || exit /b 1
cd /d "$WorkDir" || exit /b 1
rc /nologo /fo planche_shellext.res planche_shellext.rc || exit /b 1
$cl planche_shellext.cpp planche_shellext.res /Fe:planche_shellext.dll /link /DEF:planche_shellext.def $libs || exit /b 1
$cl planche_shellext.cpp /Fe:planche_shellext_classic.dll /link /DEF:planche_shellext.def $libs || exit /b 1
"@
& cmd.exe /c "`"$buildCmd`""
if ($LASTEXITCODE -ne 0 -or
    -not (Test-Path "$WorkDir\planche_shellext.dll") -or
    -not (Test-Path "$WorkDir\planche_shellext_classic.dll")) {
    throw "Compiling the context menu DLLs failed."
}

# --- Package (sparse MSIX) ---
$packageBuilt = $false
$makeappx = Find-SdkTool "makeappx.exe"
$signtool = Find-SdkTool "signtool.exe"
if (-not $makeappx -or -not $signtool) {
    Write-Host "Warning: Windows SDK (makeappx.exe / signtool.exe) not found - no first-level" -ForegroundColor Yellow
    Write-Host "         Windows 11 menu in this build (the classic menu is still provided)." -ForegroundColor Yellow
} else {
    try {
        $pkgDir = "$WorkDir\package"
        New-Item -ItemType Directory -Path "$pkgDir\Assets" -Force | Out-Null

        # Logos of the package, from the application icon.
        $logoScript = @"
import sys
from PIL import Image
target = sys.argv[1]
source = sys.argv[2] if len(sys.argv) > 2 else ''
if source:
    base = Image.open(source).convert('RGBA')
else:
    base = Image.new('RGBA', (256, 256), (60, 60, 60, 255))
for name, size in (('StoreLogo', 50), ('Square44x44Logo', 44), ('Square150x150Logo', 150)):
    base.resize((size, size), Image.LANCZOS).save(target + '\\' + name + '.png', 'PNG')
"@
        $logoScriptPath = "$WorkDir\make_logos.py"
        Set-Content -Path $logoScriptPath -Value $logoScript
        $pythonExe = if ($Python) { $Python } else { "python" }
        # No empty argument for the source icon: Windows PowerShell 5.1 does not
        # pass "" to a program, which would shift the arguments.
        $logoArgs = @($logoScriptPath, "$pkgDir\Assets")
        if ($IconPng -and (Test-Path $IconPng)) { $logoArgs += $IconPng }
        & $pythonExe @logoArgs
        if ($LASTEXITCODE -ne 0) { throw "Creating the logos of the package failed." }

        $manifest = Get-Content -Raw -Path (Join-Path $ShellExtDir "AppxManifest.template.xml")
        $manifest = $manifest.Replace("@PACKAGE_NAME@", $PackageName).Replace("@PUBLISHER@", $CertSubject).
            Replace("@VERSION@", $PackageVersion).Replace("@APP_ID@", $AppId).
            Replace("@CLSID@", $Clsid.Trim("{", "}"))
        if ($manifest -match '@[A-Z_]+@') { throw "Unreplaced value in the package manifest: $($Matches[0])" }
        Set-Content -Path "$pkgDir\AppxManifest.xml" -Value $manifest -Encoding UTF8

        $msix = "$WorkDir\planche-contact-shell.msix"
        & $makeappx pack /o /d $pkgDir /nv /p $msix | Out-Null
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $msix)) { throw "makeappx failed." }

        # Self-signed certificate (created once, kept in the user's store).
        $cert = Get-ChildItem Cert:\CurrentUser\My |
            Where-Object { $_.Subject -eq $CertSubject -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date).AddDays(30) } |
            Sort-Object NotAfter -Descending | Select-Object -First 1
        if (-not $cert) {
            Write-Host ">>> Creating the signing certificate ($CertSubject, self-signed, 10 years)..."
            $cert = New-SelfSignedCertificate -Type Custom -Subject $CertSubject `
                -KeyUsage DigitalSignature -FriendlyName "Planche-Contact Explorer menu (self-signed)" `
                -CertStoreLocation "Cert:\CurrentUser\My" -NotAfter (Get-Date).AddYears(10) `
                -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3", "2.5.29.19={text}")
        }
        & $signtool sign /fd SHA256 /sha1 $cert.Thumbprint /s My $msix | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "signtool failed." }
        Export-Certificate -Cert $cert -FilePath "$WorkDir\planche-contact-shell.cer" | Out-Null
        $packageBuilt = $true
    } catch {
        Write-Host "Warning: the Windows 11 package could not be built: $_" -ForegroundColor Yellow
        Write-Host "         No first-level Windows 11 menu in this build (the classic menu is still provided)." -ForegroundColor Yellow
    }
}

# --- Delivery to the folder of the application ---
Copy-Item "$WorkDir\planche_shellext_classic.dll" $OutDir -Force
if ($packageBuilt) {
    Copy-Item "$WorkDir\planche_shellext.dll" $OutDir -Force
    Copy-Item "$WorkDir\planche-contact-shell.msix" $OutDir -Force
    Copy-Item "$WorkDir\planche-contact-shell.cer" $OutDir -Force
}
foreach ($script in @("register-context-menu.ps1", "register-context-menu.cmd",
                      "unregister-context-menu.ps1", "unregister-context-menu.cmd")) {
    Copy-Item (Join-Path $ShellExtDir $script) $OutDir -Force
}
$info = [ordered]@{
    clsid       = $Clsid
    packageName = $PackageName
    appId       = $AppId
    certSubject = $CertSubject
    version     = $PackageVersion
    package     = $packageBuilt
}
Set-Content -Path "$OutDir\shellext-info.json" -Value ($info | ConvertTo-Json) -Encoding UTF8

if ($packageBuilt) {
    Write-Host ">>> Context menu built (classic menu + Windows 11 first level)."
} else {
    Write-Host ">>> Context menu built (classic menu only)."
}
