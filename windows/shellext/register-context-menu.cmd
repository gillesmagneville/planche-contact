@echo off
rem Adds "Open in Planche-Contact" to the Windows Explorer context menu (current user).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0register-context-menu.ps1"
pause
