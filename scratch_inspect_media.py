import json

log_path = r"C:\Users\gdeluca\.gemini\antigravity\brain\b7e95405-14b5-4c71-900a-ba94688b2f9a\.system_generated\logs\transcript.jsonl"
with open(log_path, "r", encoding="utf-8") as f:
    for line in f:
        data = json.loads(line)
        if data.get("source") == "USER_EXPLICIT":
            media = data.get("media", [])
            content = data.get("content", "")
            step = data.get("step_index")
            if media:
                print(f"Step {step} has media: {media}")
            if "liberali" in content.lower() or "prestito" in content.lower() or "lestofanti" in content.lower():
                print(f"Step {step} mentioned: {content[:100].encode('ascii', 'ignore')}")
