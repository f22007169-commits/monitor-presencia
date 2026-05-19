@echo off
title Monitor Docente - Sistema de Presencia Docente
echo.
echo  ============================================
echo   TEACHER MONITOR - Sistema de Presencia
echo  ============================================
echo.
echo  Iniciando sistema...
echo  Dashboard: http://127.0.0.1:5000
echo.
echo  Para DETENER: presiona Q o ESC en la ventana
echo              de camara, o cierra esta ventana.
echo.
cd /d "%~dp0"
call venv\Scripts\activate.bat
python app.py
echo.
echo  Sistema detenido.
pause
