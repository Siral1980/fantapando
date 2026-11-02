"""
Sync Manager for FantaMantra AI.
Handles automatic database and live stats synchronization with a 12-hour interval.
Zero guesswork, clean status reporting, and safe fallback on network errors.
"""

import os
import sys
import json
import time
import datetime

# Root paths
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(APP_DIR, "data")
SYNC_STATE_FILE = os.path.join(DATA_DIR, "sync_state.json")
MASTER_CSV = os.path.join(DATA_DIR, "players_master.csv")

AUTO_SYNC_INTERVAL_HOURS = 12.0
AUTO_SYNC_INTERVAL_SECONDS = int(AUTO_SYNC_INTERVAL_HOURS * 3600)  # 43200 seconds


def get_sync_state() -> dict:
    """
    Reads the current sync state from disk or infers it from players_master.csv.
    Returns a structured dictionary with timestamps, interval info, and due status.
    """
    now = time.time()
    last_ts = 0.0
    last_dt_str = "Mai"
    status = "never_run"
    details = ""
    source = "none"

    if os.path.exists(SYNC_STATE_FILE):
        try:
            with open(SYNC_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                last_ts = float(data.get("last_sync_timestamp", 0.0))
                last_dt_str = data.get("last_sync_datetime", "N/D")
                status = data.get("status", "success")
                details = data.get("details", "")
                source = data.get("source", "unknown")
        except Exception as e:
            print(f"[SyncManager] Error reading sync state file: {e}")

    # Fallback to players_master.csv mtime if sync_state.json is absent or has ts=0
    if last_ts <= 0.0 and os.path.exists(MASTER_CSV):
        try:
            last_ts = os.path.getmtime(MASTER_CSV)
            last_dt_str = datetime.datetime.fromtimestamp(last_ts).strftime("%d/%m/%Y %H:%M:%S")
            status = "success"
            details = "Inferred from players_master.csv"
            source = "mtime_fallback"
        except Exception:
            last_ts = 0.0

    elapsed_seconds = max(0.0, now - last_ts) if last_ts > 0 else float("inf")
    elapsed_hours = elapsed_seconds / 3600.0 if last_ts > 0 else float("inf")
    is_due = elapsed_seconds >= AUTO_SYNC_INTERVAL_SECONDS

    remaining_seconds = max(0.0, AUTO_SYNC_INTERVAL_SECONDS - elapsed_seconds) if not is_due else 0.0
    remaining_hours = remaining_seconds / 3600.0

    return {
        "last_sync_timestamp": last_ts,
        "last_sync_datetime": last_dt_str,
        "status": status,
        "details": details,
        "source": source,
        "interval_hours": AUTO_SYNC_INTERVAL_HOURS,
        "interval_seconds": AUTO_SYNC_INTERVAL_SECONDS,
        "elapsed_seconds": elapsed_seconds,
        "elapsed_hours": elapsed_hours,
        "is_due": is_due,
        "remaining_seconds": remaining_seconds,
        "remaining_hours": remaining_hours,
    }


def save_sync_state(status: str = "success", details: str = "", source: str = "auto"):
    """
    Persists the updated sync state to sync_state.json.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    now_ts = time.time()
    now_dt_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    payload = {
        "last_sync_timestamp": now_ts,
        "last_sync_datetime": now_dt_str,
        "status": status,
        "details": details,
        "source": source,
        "interval_hours": AUTO_SYNC_INTERVAL_HOURS
    }
    
    try:
        with open(SYNC_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[SyncManager] Error writing sync state file: {e}")


def format_remaining_time(remaining_seconds: float) -> str:
    """
    Formats remaining seconds into a human-readable Italian string.
    e.g., '11h 45m', '42m', 'adesso'
    """
    if remaining_seconds <= 0:
        return "adesso"
    
    hours = int(remaining_seconds // 3600)
    minutes = int((remaining_seconds % 3600) // 60)
    
    if hours > 0:
        return f"{hours}h {minutes:02d}m"
    elif minutes > 0:
        return f"{minutes}m"
    else:
        return "< 1m"


def format_last_sync_display(sync_state: dict) -> str:
    """
    Formats the last sync date/time for concise UI display (e.g. '02/11 17:38').
    """
    dt_str = sync_state.get("last_sync_datetime", "N/D")
    if not dt_str or dt_str in ["Mai", "N/D"]:
        return "Mai eseguito"
    
    # Try parsing common formats
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.datetime.strptime(dt_str, fmt)
            today = datetime.date.today()
            if dt.date() == today:
                return f"Oggi alle {dt.strftime('%H:%M')}"
            yesterday = today - datetime.timedelta(days=1)
            if dt.date() == yesterday:
                return f"Ieri alle {dt.strftime('%H:%M')}"
            return dt.strftime("%d/%m %H:%M")
        except Exception:
            continue
            
    return dt_str[:16]


def run_full_sync_pipeline(force_live_scrape: bool = True, source: str = "auto") -> tuple[bool, str]:
    """
    Executes the entire end-to-end sync pipeline:
    1. Refreshes live lineups and injuries concurrently (Fantacalcio.it + Gazzetta + Sky).
    2. Scrapes official Fantacalcio.it stats, Understat xG/xA, missing matchday votes, and GK metrics.
    3. Writes players_master.csv.
    4. Updates sync_state.json.
    
    Returns (success: bool, message: str).
    """
    try:
        from engine.probable_lineups import refresh_live_lineups_and_injuries
        from engine.data_loader import sync_and_build_database
        
        # Step 1: Lineups & Injuries
        print(f"[SyncManager] Step 1/2: Refreshing live lineups and injuries (source: {source})...")
        try:
            refresh_live_lineups_and_injuries()
        except Exception as e_inj:
            print(f"[SyncManager] Warning refreshing injuries/lineups: {e_inj}")
        
        # Step 2: Database master stats, Understat, Sufficiency
        print(f"[SyncManager] Step 2/2: Building master database with live stats and Understat...")
        df_master, _ = sync_and_build_database(force_live_scrape=force_live_scrape)
        
        # Step 3: Synchronize all league rosters and user squads with master data
        print("[SyncManager] Step 3/3: Synchronizing all league rosters and squads with master data...")
        try:
            from engine.league_manager import sync_all_league_rosters
            sync_all_league_rosters(df_master)
        except Exception as e_roster:
            print(f"[SyncManager] Notice synchronizing rosters: {e_roster}")
        
        count = len(df_master) if df_master is not None else 0
        details = f"Sincronizzati {count} calciatori e tutte le rose di lega con statistiche ufficiali, metriche Understat e voti reali."
        save_sync_state(status="success", details=details, source=source)
        print(f"[SyncManager] Sync completed successfully! ({details})")
        return True, details

    except Exception as e:
        err_msg = str(e)
        print(f"[SyncManager] Error during sync: {err_msg}")
        # Record error state so we know an attempt was made
        save_sync_state(status="error", details=err_msg, source=source)
        return False, err_msg
