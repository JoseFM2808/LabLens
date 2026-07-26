@echo off
rem Arranque de LabLens en Windows con doble clic.
rem Busca Python, y le entrega el trabajo a iniciar.py, que prepara el entorno
rem virtual, descarga las dependencias y levanta el servidor.
setlocal
cd /d "%~dp0"
title LabLens

set "PYTHON="

rem 1) El lanzador oficial "py" es el mas confiable: elige la version correcta.
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=py -3"
    goto :encontrado
)

rem 2) Un python.exe del PATH. El alias de la Microsoft Store no sirve: no
rem    responde a --version, abre la tienda. Por eso se comprueba antes de usar.
python --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python"
    goto :encontrado
)

echo.
echo   No se encontro Python en este equipo.
echo.
echo   Instalalo desde https://www.python.org/downloads/
echo   Marca la casilla "Add python.exe to PATH" durante la instalacion.
echo   Despues volve a hacer doble clic en este archivo.
echo.
pause
exit /b 1

:encontrado
%PYTHON% "%~dp0iniciar.py" %*
set "SALIDA=%ERRORLEVEL%"
if not "%SALIDA%"=="0" (
    echo.
    echo   LabLens termino con error %SALIDA%.
    pause
)
exit /b %SALIDA%
