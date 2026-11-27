#Requires -Version 5.1
<#
.SYNOPSIS
    Removes "Open in Planche-Contact" from the context menu of the Windows
    Explorer: whatever register-context-menu.ps1 added (the package of the
    first level of the Windows 11 menu, its certificate, the classic entry).

.PARAMETER Machine
    Removes what was registered for all users (administrator rights required).
.PARAMETER Quiet
    No message.
#>
param(
    [switch]$Machine,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath)
    if ($Machine) { $arguments += "-Machine" }
    if ($Quiet) { $arguments += "-Quiet" }
    & "$env:windir\sysnative\WindowsPowerShell\v1.0\powershell.exe" @arguments
    exit $LASTEXITCODE
}

function Say([string]$message) { if (-not $Quiet) { Write-Host $message } }

$infoPath = Join-Path $PSScriptRoot "shellext-info.json"
if (-not (Test-Path $infoPath)) {
    Say "shellext-info.json not found: nothing to remove."
    exit 0
}
$info = Get-Content -Raw -Path $infoPath | ConvertFrom-Json

if ($Machine) {
    $registryRoot = [Microsoft.Win32.Registry]::LocalMachine
    $certStore = "Cert:\LocalMachine\TrustedPeople"
} else {
    $registryRoot = [Microsoft.Win32.Registry]::CurrentUser
    $certStore = "Cert:\CurrentUser\TrustedPeople"
}

# The package: a fresh PowerShell (see register-context-menu.ps1).
$allUsers = if ($Machine) { " -AllUsers" } else { "" }
$ErrorActionPreference = "Continue"   # a failure to remove the package must not stop the rest
& "$env:windir\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive `
    -WindowStyle Hidden -ExecutionPolicy Bypass -Command `
    "Get-AppxPackage$allUsers -Name '$($info.packageName)' | Remove-AppxPackage$allUsers" 2>&1 | Out-Null

$ErrorActionPreference = "Stop"

# The certificate of the package.
Get-ChildItem $certStore -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -eq $info.certSubject } |
    ForEach-Object { Remove-Item -LiteralPath $_.PSPath -ErrorAction SilentlyContinue }

# The classic entry.
foreach ($path in @(
        "Software\Classes\CLSID\$($info.clsid)",
        "Software\Classes\*\shell\PlancheContact",
        "Software\Classes\Directory\shell\PlancheContact")) {
    $registryRoot.DeleteSubKeyTree($path, $false)
}

Say "Planche-Contact was removed from the context menu."
