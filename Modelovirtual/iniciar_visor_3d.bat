@echo off
title VISOR 3D INDEPENDIENTE - CLON DE MANO MEDIAPIPE & BLENDER
cd /d "%~dp0"
echo =====================================================================
echo    INICIANDO CLON VIRTUAL 3D (MEDIAPIPE + BLENDER + URSINA)
echo =====================================================================
echo.
echo Controles interactivos:
echo   - Clic Derecho + Arrastrar : Rotar vista 3D
echo   - Rueda del raton          : Zoom acercar / alejar
echo   - Barra Espaciadora        : Centrar camara 3D
echo   - Tecla [C]                : Cambiar entre camara USB e Integrada
echo   - Tecla [ESC] o [Q]        : Salir
echo.

if exist "..\..\venv\Scripts\python.exe" (
    echo [OK] Usando entorno virtual: ..\..\venv
    "..\..\venv\Scripts\python.exe" visor_ursina.py
) else (
    python visor_ursina.py
)
pause
