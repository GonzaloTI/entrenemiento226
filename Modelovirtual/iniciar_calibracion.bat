@echo off
title CALIBRADOR DE LIMITES DE MANO - MEDIAPIPE
cd /d "%~dp0"

echo =====================================================================
echo    ASISTENTE DE CALIBRACION DE LIMITES (4 MOVIMIENTOS)
echo =====================================================================
echo.
echo Te guiara en 4 pasos con una cuenta de 3 segundos por movimiento:
echo   1. Mano Completamente Abierta
echo   2. Puno Completamente Cerrado
echo   3. Paz y Victoria
echo   4. Pulgar Doblado a la Palma
echo.
echo Al finalizar guardara 'calibracion_mano.json' automaticamente.
echo.

set PYTHON_CMD=python
if exist "..\..\venv\Scripts\python.exe" (
    set PYTHON_CMD="..\..\venv\Scripts\python.exe"
)

%PYTHON_CMD% calibrador_movimientos.py
pause
