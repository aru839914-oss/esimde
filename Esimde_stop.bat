@echo off
setlocal
chcp 65001 >nul
title Esimde - stop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\esimde.ps1" stop %*
echo.
pause
