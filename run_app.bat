@echo off
title FantaPandoAssistant
cd /d "%~dp0"

echo ========================================================
echo       FantaPandoAssistant - Avvio Applicazione
echo ========================================================
echo.

:: 1. Attivazione ambiente virtuale se presente (locale o su disco locale se eseguito da Google Drive)
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else if exist "%LOCALAPPDATA%\FantaPandoAssistant\venv\Scripts\activate.bat" (
    call "%LOCALAPPDATA%\FantaPandoAssistant\venv\Scripts\activate.bat"
)

:: 2. Verifica e download automatico aggiornamenti cloud (Cross-PC)
where git >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [1/2] Controllo aggiornamenti da GitHub...
    git pull --quiet
    if %ERRORLEVEL% EQU 0 (
        echo      - Progetto e rose allineati all'ultima versione.
    ) else (
        echo      - Avvio offline o git non connesso. Uso dati locali.
    )
) else (
    echo [1/2] Git non rilevato nel PATH, continuo in modalita locale.
)

echo.
echo [2/2] Avvio del server Streamlit...
echo      - Accesso Locale:    http://localhost:8501
echo      - Accesso altri PC:  http://[IP-DI-QUESTO-PC]:8501
echo.
streamlit run app.py

pause
