#!/usr/bin/env python3
"""
export_chat_session.py
----------------------
Crea un archivio compresso (.zip) della sessione attiva di Antigravity
(C:\\Users\\<user>\\.gemini\\antigravity\\brain\\b7e95405-14b5-4c71-900a-ba94688b2f9a).
Questo file zip può essere trasferito su un altro PC (tramite USB, Drive o LAN)
ed estratto tramite 'restore_chat_session.py' per visualizzare la chat nativa
all'interno dell'applicazione Antigravity 2.0 sul secondo computer.
"""

import os
import sys
import zipfile
from datetime import datetime

CONVERSATION_ID = "b7e95405-14b5-4c71-900a-ba94688b2f9a"

def main():
    user_profile = os.environ.get("USERPROFILE", "")
    brain_dir = os.path.join(user_profile, ".gemini", "antigravity", "brain", CONVERSATION_ID)

    if not os.path.exists(brain_dir):
        print(f"[ERRORE] Cartella sessione non trovata in: {brain_dir}")
        sys.exit(1)

    repo_dir = os.path.dirname(os.path.abspath(__file__))
    zip_out = os.path.join(repo_dir, "antigravity_chat_session.zip")

    print(f"Archiviazione della sessione Antigravity: {CONVERSATION_ID}...")
    print(f"Sorgente: {brain_dir}")

    count = 0
    with zipfile.ZipFile(zip_out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(brain_dir):
            for f in files:
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, brain_dir)
                zf.write(full_path, rel_path)
                count += 1

    size_mb = os.path.getsize(zip_out) / (1024 * 1024)
    print(f"Archivio creato con successo: {zip_out}")
    print(f"File inclusi: {count} | Dimensione: {size_mb:.2f} MB")
    print("\nPuoi copiare questo file sul secondo PC ed eseguire:")
    print("  python restore_chat_session.py")

if __name__ == "__main__":
    main()
