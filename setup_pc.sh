#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "========================================================"
echo "   Configurazione FantaMantra AI Manager per questo PC"
echo "========================================================"
echo ""

if ! command -v python3 &> /dev/null; then
    echo "ERRORE: python3 non e installato."
    exit 1
fi

echo "[1/3] Creazione ambiente virtuale (venv)..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "      -> Ambiente virtuale creato."
else
    echo "      -> Ambiente virtuale gia presente."
fi

echo "[2/3] Installazione dipendenze da requirements.txt..."
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "      -> Dipendenze installate con successo."

chmod +x run_app.sh setup_pc.sh 2>/dev/null || true

echo ""
echo "[3/3] Configurazione completata!"
echo "      Per avviare l'applicazione esegui: ./run_app.sh"
echo ""
