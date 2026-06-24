@echo off
REM Arranca P3 Autoroute (editor de rutas .rou de Patrician III).
REM Uso:  run.bat            -> ventana de escritorio (modo principal)
REM       run.bat --web      -> fallback en navegador (http://127.0.0.1:8765)
REM Cualquier argumento extra se pasa tal cual a p3autoroute.

setlocal
cd /d "%~dp0"

REM Elige el lanzador de Python disponible: primero "py", luego "python".
set "PY=py"
where py >nul 2>nul || set "PY=python"

REM Instala dependencias la primera vez (solo si falta pywebview, que se importa
REM como "webview"). El modo --web no lo necesita, pero instalarlo no estorba.
%PY% -c "import webview" >nul 2>nul
if errorlevel 1 (
    echo [P3 Autoroute] Instalando dependencias por primera vez...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [P3 Autoroute] No se pudieron instalar las dependencias.
        pause
        exit /b 1
    )
)

%PY% -m p3autoroute %*
set "ERR=%ERRORLEVEL%"

REM Si fallo el arranque, deja la ventana abierta para ver el error.
if not "%ERR%"=="0" (
    echo.
    echo [P3 Autoroute] termino con codigo de error %ERR%.
    pause
)

endlocal & exit /b %ERR%
