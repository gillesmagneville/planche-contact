#Requires -Version 5.1
<#
.SYNOPSIS
    Relay to windows\build-windows.ps1, for a usage symmetrical to
    build-deb.sh (which is run from the root of the repository).

.DESCRIPTION
    This script only forwards all its arguments to
    windows\build-windows.ps1, where the real build logic lives (see
    windows\README.md for the full details: prerequisites, options,
    troubleshooting). Nothing is duplicated: this file stays up to date by
    itself, since it only calls the other script.

.EXAMPLE
    .\build-windows.ps1
    .\build-windows.ps1 -Major
    .\build-windows.ps1 -Clean
    .\build-windows.ps1 -Help
#>

& "$PSScriptRoot\windows\build-windows.ps1" @args
exit $LASTEXITCODE
