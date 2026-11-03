@echo off
echo ========================================================
echo   FantaMantra AI - Esportazione Sessione Chat Antigravity
echo ========================================================
echo.
python "%~dp0export_chat_history.py"
echo.
python "%~dp0export_chat_session.py"
echo.
pause
