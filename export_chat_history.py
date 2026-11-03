#!/usr/bin/env python3
"""
export_chat_history.py
----------------------
Esporta l'intera cronologia della conversazione e le decisioni del progetto
da Antigravity (transcript.jsonl) in un documento Markdown pulito e strutturato.
Questo file viene salvato direttamente nel repository Git (docs/CHAT_HISTORY_TRANSCRIPT.md)
rendendo disponibile la conversazione su qualsiasi altro PC tramite git pull.
"""

import os
import json
import re
from datetime import datetime

CONVERSATION_ID = "b7e95405-14b5-4c71-900a-ba94688b2f9a"

def find_transcript_path():
    # 1. Path diretto noto
    user_profile = os.environ.get("USERPROFILE", "")
    known_path = os.path.join(
        user_profile, ".gemini", "antigravity", "brain", 
        CONVERSATION_ID, ".system_generated", "logs", "transcript.jsonl"
    )
    if os.path.exists(known_path):
        return known_path

    # 2. Ricerca della cartella brain più recente se l'id differisce
    brain_root = os.path.join(user_profile, ".gemini", "antigravity", "brain")
    if os.path.exists(brain_root):
        sessions = [
            os.path.join(brain_root, d) for d in os.listdir(brain_root)
            if os.path.isdir(os.path.join(brain_root, d))
        ]
        sessions.sort(key=os.path.getmtime, reverse=True)
        for s in sessions:
            candidate = os.path.join(s, ".system_generated", "logs", "transcript.jsonl")
            if os.path.exists(candidate):
                return candidate
    return None

def clean_user_text(raw_text):
    text = re.sub(r'<USER_REQUEST>\s*', '', raw_text)
    text = re.sub(r'\s*</USER_REQUEST>.*', '', text, flags=re.DOTALL)
    # Rimuovi metadata
    text = re.sub(r'<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>', '', text, flags=re.DOTALL)
    return text.strip()

def export_transcript():
    transcript_file = find_transcript_path()
    if not transcript_file:
        print("[ERRORE] File transcript.jsonl non trovato.")
        return

    repo_dir = os.path.dirname(os.path.abspath(__file__))
    docs_dir = os.path.join(repo_dir, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    out_file = os.path.join(docs_dir, "CHAT_HISTORY_TRANSCRIPT.md")

    print(f"Lettura transcript da: {transcript_file}")
    
    turns = []
    total_lines = 0

    with open(transcript_file, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            total_lines += 1
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except Exception:
                continue

            msg_type = data.get("type")
            source = data.get("source")
            content = data.get("content", "")
            created_at = data.get("created_at", "")

            # Parsing timestamps
            time_str = ""
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    time_str = created_at

            if msg_type == "USER_INPUT" and source == "USER_EXPLICIT":
                clean = clean_user_text(content)
                if clean:
                    turns.append({
                        "role": "Utente",
                        "time": time_str,
                        "text": clean
                    })
            elif msg_type == "PLANNER_RESPONSE" and source == "MODEL":
                if content and content.strip():
                    turns.append({
                        "role": "Antigravity AI",
                        "time": time_str,
                        "text": content.strip()
                    })

    # Scrittura su file Markdown
    with open(out_file, "w", encoding="utf-8") as out:
        out.write("# Archivio Integrale Trascrizione Chat Antigravity\n\n")
        out.write(f"- **ID Conversazione**: `{CONVERSATION_ID}`\n")
        out.write(f"- **Data Esportazione**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        out.write(f"- **Totale Interazioni Registrate**: {len(turns)}\n\n")
        out.write("---\n\n")

        for idx, t in enumerate(turns, 1):
            role_icon = "👤" if t["role"] == "Utente" else "🤖"
            out.write(f"### {role_icon} Turno {idx} • {t['role']} ({t['time']})\n\n")
            out.write(f"{t['text']}\n\n")
            out.write("---\n\n")

    print(f"Esportazione completata con successo in: {out_file} ({len(turns)} turni).")

if __name__ == "__main__":
    export_transcript()
