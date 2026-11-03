@echo off
title FantaPandoAssistant - Deploy su GitHub e Streamlit Cloud
cd /d "%~dp0"

echo ========================================================
echo   Pubblicazione Aggiornamenti su GitHub (Streamlit Cloud)
echo ========================================================
echo.

where git >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERRORE] Git non e installato su questo PC.
    echo Per installarlo automaticamente esegui in PowerShell:
    echo   winget install --id Git.Git -e --source winget
    pause
    exit /b 1
)

echo [1/4] Salvataggio modifiche sul branch dev...
git checkout dev
git add app.py engine/auth_manager.py engine/league_manager.py deploy_cloud.bat
git commit -m "feat(auth): accesso libero tramite link e Pannello Admin protetto da password"

echo.
echo [2/4] Invio branch dev su GitHub (remote: fantapando)...
git push fantapando dev

echo.
echo [3/4] Allineamento branch master (produzione Streamlit Cloud)...
git checkout master
git merge dev
git push fantapando master

echo.
echo [4/4] Ritorno sul branch dev...
git checkout dev

echo.
echo ========================================================
echo   COMPLETATO! Streamlit Cloud (fantapando.streamlit.app)
echo   si aggiornera automaticamente entro 30-60 secondi.
echo ========================================================
pause
