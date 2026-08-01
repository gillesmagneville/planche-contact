#Requires -Version 5.1
<#
.SYNOPSIS
    Relais vers windows\build-windows.ps1, pour un usage symetrique a
    build-deb.sh (qui se lance depuis la racine du depot).

.DESCRIPTION
    Ce script ne fait que transmettre tous ses arguments a
    windows\build-windows.ps1, ou vit la logique de build reelle (voir
    windows\README.md pour le detail complet : prerequis, options,
    depannage). Rien n'est duplique : ce fichier reste a jour tout seul,
    puisqu'il ne fait qu'appeler l'autre script.

.EXAMPLE
    .\build-windows.ps1
    .\build-windows.ps1 -Major
    .\build-windows.ps1 -Clean
    .\build-windows.ps1 -Help
#>

& "$PSScriptRoot\windows\build-windows.ps1" @args
exit $LASTEXITCODE
