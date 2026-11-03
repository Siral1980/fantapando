#!/usr/bin/env python3
"""
restore_chat_session.py
-----------------------
Estrae l'archivio compresso 'antigravity_chat_session.zip' nella directory brain
dell'utente sul PC corrente (%USERPROFILE%\\.gemini\\antigravity\\brain\\<conv_id>).
In questo modo la conversazione e tutti gli artefatti tornano visibili
nell'applicazione Antigravity 2.0 sul nuovo computer!
"""

import os
import sys
import zipfile

CONVERSATION_ID = "b7e95405-14b5-4c71-900a-ba94688b2f9a"

def main():
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    zip_source = os.path.join(repo_dir, "antigravity_chat_session.zip")

    if not os.path.exists(zip_source):
        print(f"[ERRORE] File archivio non trovato: {zip_source}")
        print("Assicurati di aver generato o copiato 'antigravity_chat_session.zip' in questa cartella.")
        sys.exit(1)

    user_profile = os.environ.get("USERPROFILE", "")
    if not user_profile:
        print("[ERRORE] Impossibile determinare USERPROFILE.")
        sys.exit(1)

    target_dir = os.path.join(user_profile, ".gemini", "antigravity", "brain", CONVERSATION_ID)
    os.makedirs(target_dir, exist_ok=True)

    print(f"Ripristino sessione Antigravity: {CONVERSATION_ID}")
    print(f"Destinazione: {target_dir}")

    with zipfile.ZipFile(zip_source, "r") as zf:
        zf.extractall(target_dir)

    print("\nSessione ripristinata con successo!")
    print("Ora puoi riavviare o aggiornare l'applicazione Antigravity su questo PC:")
    print(f"La chat '{CONVERSATION_ID}' sarà presente nella cronologia con tutti i suoi messaggi e artefatti.")

if __name__ == "__main__":
    main()
