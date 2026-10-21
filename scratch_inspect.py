import json

log_path = r"C:\Users\gdeluca\.gemini\antigravity\brain\b7e95405-14b5-4c71-900a-ba94688b2f9a\.system_generated\logs\transcript.jsonl"
with open(log_path, "r", encoding="utf-8") as f:
    for line in f:
        data = json.loads(line)
        if data.get("source") == "USER_EXPLICIT":
            c = str(data.get("content", ""))[:120].replace("\n", " ")
            print(f"{data.get('step_index')}: {c}")
