#Requires -Version 5.1
<#
.SYNOPSIS
    Adds "Open in Planche-Contact" to the context menu of the Windows Explorer
    (right click on photos, on a selection of photos, or on a folder).

.DESCRIPTION
    On Windows 11, the entry goes to the FIRST level of the menu: the sparse
    package planche-contact-shell.msix is registered, which needs its
    self-signed certificate (planche-contact-shell.cer, same folder) to be
    trusted first. If that is not possible (Windows 10, a build without the
    package, sideloading blocked...), the entry is registered the classic way:
    on Windows 11 it then lives in "Show more options".

    By default, for the current user only, without administrator rights. With
    -Machine (used by the installer, as administrator), the certificate is
    trusted by the whole machine and the classic entry is registered for all
    users.

    Removed by unregister-context-menu.ps1.

.PARAMETER Machine
    Registers for all users of the computer (administrator rights required).
.PARAMETER RestartExplorer
    Restarts the Windows Explorer after a first-level registration (Windows
    does not show the new entry before that). Its windows close for a moment.
.PARAMETER Quiet
    No message.
#>
param(
    [switch]$Machine,
    [switch]$RestartExplorer,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

# Registry and certificate stores must be the 64-bit ones, those of the 64-bit
# Explorer: a 32-bit PowerShell (started by a 32-bit installer, for example)
# relaunches itself as a 64-bit one.
if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath)
    if ($Machine) { $arguments += "-Machine" }
    if ($RestartExplorer) { $arguments += "-RestartExplorer" }
    if ($Quiet) { $arguments += "-Quiet" }
    & "$env:windir\sysnative\WindowsPowerShell\v1.0\powershell.exe" @arguments
    exit $LASTEXITCODE
}

function Say([string]$message) { if (-not $Quiet) { Write-Host $message } }

$AppDir = $PSScriptRoot
$infoPath = Join-Path $AppDir "shellext-info.json"
if (-not (Test-Path $infoPath)) {
    Write-Error "shellext-info.json not found next to this script: the context menu was not built in this package."
    exit 1
}
$info = Get-Content -Raw -Path $infoPath | ConvertFrom-Json
$classicDll = Join-Path $AppDir "planche_shellext_classic.dll"
$packageFile = Join-Path $AppDir "planche-contact-shell.msix"
$certFile = Join-Path $AppDir "planche-contact-shell.cer"

if ($Machine) {
    $registryRoot = [Microsoft.Win32.Registry]::LocalMachine
    $certStore = "Cert:\LocalMachine\TrustedPeople"
} else {
    $registryRoot = [Microsoft.Win32.Registry]::CurrentUser
    $certStore = "Cert:\CurrentUser\TrustedPeople"
}

# A fresh PowerShell for the package cmdlets, as in Microsoft's documentation:
# removing a package from an existing session sometimes fails (0x80073CFA).
function Invoke-FreshPowerShell([string]$command) {
    # "Continue": with "Stop", Windows PowerShell 5.1 turns any text the child
    # writes on its error output into an exception, hiding its exit code.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & "$env:windir\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile `
            -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass `
            -Command "`$ErrorActionPreference = 'Stop'; $command" 2>&1
        return [pscustomobject]@{ Code = $LASTEXITCODE; Output = ($output | Out-String).Trim() }
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Quote([string]$text) { return "'" + $text.Replace("'", "''") + "'" }

function Remove-Classic {
    foreach ($path in @(
            "Software\Classes\CLSID\$($info.clsid)",
            "Software\Classes\*\shell\PlancheContact",
            "Software\Classes\Directory\shell\PlancheContact")) {
        $registryRoot.DeleteSubKeyTree($path, $false)
    }
}

function Register-Classic {
    if (-not (Test-Path $classicDll)) { throw "planche_shellext_classic.dll not found." }
    $classKey = $registryRoot.CreateSubKey("Software\Classes\CLSID\$($info.clsid)")
    $classKey.SetValue("", "Planche-Contact Explorer menu")
    $server = $classKey.CreateSubKey("InprocServer32")
    $server.SetValue("", $classicDll)
    $server.SetValue("ThreadingModel", "Apartment")
    # "*" = every file (the DLL hides the entry unless a photo is selected).
    foreach ($target in @("*", "Directory")) {
        $verb = $registryRoot.CreateSubKey("Software\Classes\$target\shell\PlancheContact")
        $verb.SetValue("ExplorerCommandHandler", $info.clsid)
        # A COM verb takes any number of items in a single call.
        $verb.SetValue("MultiSelectModel", "Player")
    }
}

function Register-Package {
    if (-not $info.package -or -not (Test-Path $packageFile) -or -not (Test-Path $certFile)) { return $false }
    $build = [int](Get-CimInstance Win32_OperatingSystem).BuildNumber
    if ($build -lt 22000) { return $false }   # the new menu only exists on Windows 11
    try {
        Import-Certificate -FilePath $certFile -CertStoreLocation $certStore | Out-Null
        # A previous copy (this version or an older one) is removed first.
        Invoke-FreshPowerShell "Get-AppxPackage -Name $(Quote $info.packageName) | Remove-AppxPackage" | Out-Null
        $result = Invoke-FreshPowerShell "Add-AppxPackage -Path $(Quote $packageFile) -ExternalLocation $(Quote $AppDir)"
        if ($result.Code -ne 0) { throw $result.Output }
        return $true
    } catch {
        Say "The Windows 11 package could not be registered: $($_.Exception.Message)"
        return $false
    }
}

if (Register-Package) {
    Remove-Classic   # otherwise the entry would appear twice in "Show more options"
    Say "Planche-Contact is now in the first level of the Windows 11 context menu."
    if ($RestartExplorer) {
        Say "Restarting the Windows Explorer..."
        # Windows relaunches the shell by itself, with the user's rights.
        Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
    } else {
        Say "Sign out and back in (or restart the Windows Explorer) for the entry to appear."
    }
} else {
    Register-Classic
    Say "Planche-Contact is now in the classic context menu (on Windows 11: Show more options)."
}
