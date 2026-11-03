@echo off
title Configurazione FantaMantra AI per Nuovo PC
cd /d "%~dp0"

echo ========================================================
echo   Configurazione FantaMantra AI Manager per questo PC
echo ========================================================
echo.

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERRORE: Python non e installato o non e configurato nel PATH di sistema.
    echo Installa Python 3.10 o 3.11 da https://www.python.org/ spuntando "Add python.exe to PATH".
    pause
    exit /b 1
)

echo [1/3] Creazione ambiente virtuale locale (venv)...
if not exist "venv" (
    python -m venv venv
    echo      -> Ambiente virtuale creato.
) else (
    echo      -> Ambiente virtuale gia presente.
)

echo.
echo [2/3] Installazione dipendenze da requirements.txt...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo      -> Dipendenze installate con successo.

echo.
echo [3/3] Configurazione completata!
echo      Per avviare l'applicazione in qualsiasi momento, fai doppio click su:
echo      run_app.bat
echo.
pause
