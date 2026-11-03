#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "========================================================"
echo "      FantaPandoAssistant - Avvio Applicazione"
echo "========================================================"
echo ""

if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

if command -v git &> /dev/null; then
    echo "[1/2] Sincronizzazione cloud con GitHub (verifica nuovi dati)..."
    git pull --quiet || echo "      -> Avvio offline o git non connesso. Uso dati locali."
else
    echo "[1/2] Git non rilevato, continuo in modalita locale."
fi

echo ""
echo "[2/2] Avvio del server Streamlit..."
echo "      - Accesso Locale:    http://localhost:8501"
echo "      - Accesso altri PC:  http://[IP-DI-QUESTO-PC]:8501"
echo ""

streamlit run app.py
