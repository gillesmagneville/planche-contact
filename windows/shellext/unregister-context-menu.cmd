@echo off
rem Removes "Open in Planche-Contact" from the Windows Explorer context menu (current user).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0unregister-context-menu.ps1"
pause
