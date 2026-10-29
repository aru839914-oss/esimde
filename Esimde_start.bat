@echo off
setlocal
chcp 65001 >nul
title Esimde - start
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\esimde.ps1" start %*
echo.
pause
