"""
Sync Manager for FantaMantra AI.
Handles automatic database and live stats synchronization with a 12-hour interval.
Includes Matchday Staleness Detection: forces sync if data lags behind Serie A calendar.
Enforces non-regression, clean status reporting, and automatic retry on network errors.
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
RETRY_INTERVAL_SECONDS = 300  # 5 minutes on error or degraded state


def get_sync_state() -> dict:
    """
    Reads the current sync state from disk or infers it from players_master.csv.
    Includes Matchday-Aware Staleness Detection: if players_master.csv has fewer
    presenze than expected for the current calendar matchday, is_due is forced to True.
    """
    now = time.time()
    last_ts = 0.0
    last_dt_str = "Mai"
    status = "never_run"
    details = ""
    source = "none"
    roster_imported = False
    roster_details = ""

    if os.path.exists(SYNC_STATE_FILE):
        try:
            with open(SYNC_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                last_ts = float(data.get("last_sync_timestamp", 0.0))
                last_dt_str = data.get("last_sync_datetime", "N/D")
                status = data.get("status", "success")
                details = data.get("details", "")
                source = data.get("source", "unknown")
                roster_imported = bool(data.get("roster_imported", False))
                roster_details = data.get("roster_details", "")
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

    # Matchday Staleness Gate:
    # If the database max presenze is significantly lagging behind the Serie A calendar,
    # we force is_due = True immediately regardless of elapsed time.
    is_stale_matchday = False
    max_presenze = 0
    expected_completed_matchday = 0
    current_giornata = 0
    try:
        if os.path.exists(MASTER_CSV):
            import pandas as pd
            from engine.fanta_calendar import get_matchday_from_date
            g_cal, cal_info = get_matchday_from_date()
            current_giornata = g_cal
            expected_completed_matchday = (g_cal - 1) if cal_info.get("status") == "upcoming" else g_cal
            expected_min_presenze = max(1, expected_completed_matchday - 1)

            df_check = pd.read_csv(MASTER_CSV, usecols=["Presenze"])
            if len(df_check) > 0 and "Presenze" in df_check.columns:
                max_presenze = int(df_check["Presenze"].max())
                if max_presenze < expected_min_presenze:
                    is_stale_matchday = True
    except Exception as e_check:
        print(f"[SyncManager] Matchday staleness check notice: {e_check}")

    # Active interval: use 5-minute retry if previous sync failed/degraded or was stale
    active_interval = RETRY_INTERVAL_SECONDS if status in ["error", "degraded", "partial", "stale_matchday"] else AUTO_SYNC_INTERVAL_SECONDS
    is_due = (elapsed_seconds >= active_interval) or is_stale_matchday

    due_reason = "time_elapsed" if is_due else "none"
    if is_stale_matchday:
        due_reason = f"Dati fermi alla {max_presenze}ª giornata (attese {expected_completed_matchday}+ per Giornata {current_giornata})"
        status = "stale_matchday"
    elif status in ["error", "degraded"]:
        due_reason = "retry_after_error"

    remaining_seconds = max(0.0, active_interval - elapsed_seconds) if not is_due else 0.0
    remaining_hours = remaining_seconds / 3600.0

    return {
        "last_sync_timestamp": last_ts,
        "last_sync_datetime": last_dt_str,
        "status": status,
        "details": details,
        "source": source,
        "roster_imported": roster_imported,
        "roster_details": roster_details,
        "interval_hours": AUTO_SYNC_INTERVAL_HOURS,
        "interval_seconds": AUTO_SYNC_INTERVAL_SECONDS,
        "elapsed_seconds": elapsed_seconds,
        "elapsed_hours": elapsed_hours,
        "is_due": is_due,
        "due_reason": due_reason,
        "is_stale_matchday": is_stale_matchday,
        "max_presenze": max_presenze,
        "remaining_seconds": remaining_seconds,
        "remaining_hours": remaining_hours,
    }


def save_sync_state(status: str = "success", details: str = "", source: str = "auto", roster_imported: bool = False, roster_details: str = ""):
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
        "roster_imported": roster_imported,
        "roster_details": roster_details,
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


def run_full_sync_pipeline(force_live_scrape: bool = True, source: str = "auto", force_roster_reimport: bool = False) -> tuple[bool, str]:
    """
    Executes the entire end-to-end sync pipeline:
    1. Refreshes live lineups and injuries concurrently (Fantacalcio.it + Gazzetta + Sky).
    2. Scrapes official Fantacalcio.it stats, Understat xG/xA, missing matchday votes, and GK metrics.
    3. Synchronizes all league rosters with df_master and auto-detects/imports new exports from Downloads.
    4. Enforces non-regression on players_master.csv and updates Statistiche_Fantacalcio_Live.xlsx.
    5. Updates sync_state.json.

    Returns (success: bool, message: str).
    """
    try:
        from engine.probable_lineups import refresh_live_lineups_and_injuries
        from engine.data_loader import sync_and_build_database

        # Step 1: Lineups & Injuries
        print(f"[SyncManager] Step 1/3: Refreshing live lineups and injuries (source: {source})...")
        try:
            refresh_live_lineups_and_injuries()
        except Exception as e_inj:
            print(f"[SyncManager] Warning refreshing injuries/lineups: {e_inj}")

        # Step 2: Database master stats, Understat, Sufficiency
        print(f"[SyncManager] Step 2/3: Building master database with live stats and Understat...")
        df_master, _, live_ok, live_err = sync_and_build_database(force_live_scrape=force_live_scrape, return_status=True)

        # Step 3: Synchronize all league rosters and user squads with master data
        print("[SyncManager] Step 3/3: Synchronizing all league rosters and squads with master data...")
        roster_imported = False
        roster_summary = ""
        try:
            from engine.league_manager import sync_all_league_rosters
            res_sync = sync_all_league_rosters(df_master, force_roster_reimport=force_roster_reimport)
            if isinstance(res_sync, tuple):
                if len(res_sync) >= 3:
                    _, roster_summary, roster_imported = res_sync
                elif len(res_sync) == 2:
                    _, roster_summary = res_sync
        except Exception as e_roster:
            print(f"[SyncManager] Notice synchronizing rosters: {e_roster}")

        count = len(df_master) if df_master is not None else 0
        max_p = int(df_master['Presenze'].max()) if (df_master is not None and 'Presenze' in df_master.columns) else 0

        if live_ok:
            if roster_imported:
                details = f"{roster_summary} ({count} calciatori Serie A sincronizzati live fino alla {max_p}ª giornata)."
            else:
                details = f"Sincronizzati live {count} calciatori Serie A (fino alla {max_p}ª giornata) e tutte le rose di lega con Fantacalcio.it e Understat."
            save_sync_state(status="success", details=details, source=source, roster_imported=roster_imported, roster_details=roster_summary)
            print(f"[SyncManager] Sync completed successfully! ({details})")
            return True, details
        else:
            # Degraded state: live scraping failed, but existing master was preserved by circuit breaker
            details = f"Scrape live non disponibile ({live_err}). Mantenuto database locale protetto con max {max_p} presenze."
            save_sync_state(status="degraded", details=details, source=source, roster_imported=roster_imported, roster_details=roster_summary)
            print(f"[SyncManager] Degraded sync finished: {details}")
            return False, details

    except Exception as e:
        err_msg = str(e)
        print(f"[SyncManager] Error during sync: {err_msg}")
        save_sync_state(status="error", details=err_msg, source=source)
        return False, err_msg
