@echo off
title Configurazione FantaPandoAssistant per Nuovo PC
cd /d "%~dp0"

echo ========================================================
echo   Configurazione FantaPandoAssistant per questo PC
echo ========================================================
echo.

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERRORE: Python non e installato o non e configurato nel PATH di sistema.
    echo Installa Python 3.10 o 3.11 da https://www.python.org/ spuntando "Add python.exe to PATH".
    pause
    exit /b 1
)

:: Se ci troviamo su Google Drive (es. unità G:), posizioniamo venv su disco locale per non intasare il cloud
set "VENV_DIR=venv"
if /i "%~d0"=="G:" (
    echo [INFO] Rilevata esecuzione da Google Drive (%~d0).
    echo        L'ambiente virtuale verra salvato in locale (%LOCALAPPDATA%\FantaPandoAssistant\venv)
    echo        per mantenere Google Drive ultra-veloce e leggero.
    set "VENV_DIR=%LOCALAPPDATA%\FantaPandoAssistant\venv"
)

echo [1/3] Creazione ambiente virtuale locale...
if not exist "%VENV_DIR%" (
    python -m venv "%VENV_DIR%"
    echo      - Ambiente virtuale creato in: "%VENV_DIR%"
) else (
    echo      - Ambiente virtuale gia presente.
)

echo.
echo [2/3] Installazione dipendenze da requirements.txt...
call "%VENV_DIR%\Scripts\activate.bat"
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo      - Dipendenze installate con successo.

echo.
echo [3/3] Configurazione completata!
echo      Per avviare l'applicazione in qualsiasi momento, fai doppio click su:
echo      run_app.bat
echo.
pause
