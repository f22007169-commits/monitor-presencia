@echo off
title Registrar Profesores - Teacher Monitor
echo.
echo  ============================================
echo   REGISTRAR NUEVOS PROFESORES
echo  ============================================
echo.
echo  Este script procesa las fotos de la carpeta
echo  "profesores/" y aprende los rostros.
echo.
echo  Ejecutar cuando:
echo   - Agregues un nuevo profesor
echo   - Cambies las fotos de alguien
echo.
cd /d "%~dp0"
call venv\Scripts\activate.bat
python register_faces.py
echo.
pause
