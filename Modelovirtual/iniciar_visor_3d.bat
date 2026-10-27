@echo off
title VISOR 3D INDEPENDIENTE - CLON DE MANO MEDIAPIPE & BLENDER
cd /d "%~dp0"

echo =====================================================================
echo    CLON VIRTUAL 3D (MEDIAPIPE + BLENDER + URSINA)
echo =====================================================================
echo Selecciona la camara a utilizar:
echo   [0]     - Camara Integrada de la Laptop
echo   [1]     - Camara Externa USB
echo   [Enter] - Deteccion Automatica
echo =====================================================================
set /p CAM_OPT="Selecciona camara [0, 1 o Enter para Auto]: "

echo.
echo Controles interactivos:
echo   - Tecla [C]         : Cambiar entre camara USB e Integrada en vivo
echo   - Tecla [M]         : Alternar vista espejo
echo   - Clic Der + Arrast : Rotar vista 3D de la mano
echo   - Rueda raton       : Zoom
echo   - Barra Espaciadora : Centrar camara 3D
echo   - Tecla [ESC] / [Q] : Salir
echo.

set PYTHON_CMD=python
if exist "..\..\venv\Scripts\python.exe" (
    set PYTHON_CMD="..\..\venv\Scripts\python.exe"
)

if "%CAM_OPT%"=="" (
    %PYTHON_CMD% visor_ursina.py
) else (
    %PYTHON_CMD% visor_ursina.py %CAM_OPT%
)

pause
