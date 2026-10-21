@echo off
title Riavvio Pulito Fantacalcio Mantra
echo =======================================================
echo PULIZIA TOTALE CACHE E RIAVVIO APPLICAZIONE
echo =======================================================
cd /d "%~dp0"
python clean_and_restart.py
echo.
echo Operazione completata.
timeout /t 5
