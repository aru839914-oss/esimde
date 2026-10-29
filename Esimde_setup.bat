@echo off
setlocal
chcp 65001 >nul
title Esimde - setup
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\esimde.ps1" setup %*
echo.
pause
