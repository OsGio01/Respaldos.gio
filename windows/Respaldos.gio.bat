@echo off
REM Respaldos.Gio - version minima de terminal (sin Python)
REM Llama al script de PowerShell que esta en esta misma carpeta.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Respaldos.gio.ps1"
set CODIGO=%ERRORLEVEL%
if not "%CODIGO%"=="0" (
  echo.
  echo El script termino con codigo %CODIGO%.
)
endlocal
