"""
Fantacalcio.it Direct API Integration for FantaPando.
Communicates directly with apileague.fantacalcio.it microservices using the official
app_key and the user's league Bearer token.

Features:
- Live synchronization of league teams and rosters.
- Native loan synchronization (extracting sDay and eDay).
- Automatic matchday-based loan expiration and cleanup.
- Resilient local persistence (fallback to offline cache).
"""

import os
import sys
import json
import datetime
import requests
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.fanta_calendar import get_matchday_from_date
from engine.league_manager import (
    get_active_league_id,
    get_league_paths,
    load_loans_registry,
    save_loans_registry,
    save_league_rosters,
    save_league_metadata,
    reconcile_rosters_with_loans,
    DATA_DIR
)

# Official production app_key for leghe.fantacalcio.it client
PROD_APP_KEY = "ICiELOObd5DF5uJEATi77CRvHiiRuMU0"
BASE_API_URL = "https://apileague.fantacalcio.it"


def get_stored_api_token(league_id=None) -> str:
    """Retrieves the stored Fantacalcio API token from the league configuration."""
    paths = get_league_paths(league_id)
    cfg_file = paths.get('config')
    if cfg_file and os.path.exists(cfg_file):
        try:
            with open(cfg_file, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                return str(cfg.get('fantacalcio_token', '')).strip()
        except Exception:
            pass
    return ""


def save_stored_api_token(token: str, league_id=None) -> bool:
    """Saves the Fantacalcio API token into the league configuration."""
    paths = get_league_paths(league_id)
    cfg_file = paths.get('config')
    if not cfg_file:
        return False
    try:
        cfg = {}
        if os.path.exists(cfg_file):
            with open(cfg_file, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        cfg['fantacalcio_token'] = str(token).strip()
        cfg['token_updated_at'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(cfg_file, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def fetch_raw_league_data(token: str) -> dict:
    """
    Calls the apileague.fantacalcio.it endpoint to fetch all teams, rosters, and loans.
    """
    clean_token = str(token).strip()
    if clean_token.startswith("Bearer "):
        clean_token = clean_token[7:].strip()

    if not clean_token:
        raise ValueError("Token API non fornito o vuoto.")

    headers = {
        "app_key": PROD_APP_KEY,
        "Authorization": f"Bearer {clean_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Origin": "https://leghe.fantacalcio.it",
        "Referer": "https://leghe.fantacalcio.it/"
    }

    # Primary endpoint: onboarding league teams
    endpoints_to_try = [
        f"{BASE_API_URL}/onboarding/v1/league/teams",
        f"{BASE_API_URL}/market/v1/user/action/teamplayers/A"
    ]

    last_error = None
    for ep in endpoints_to_try:
        try:
            resp = requests.get(ep, headers=headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, (dict, list)):
                    return data
            elif resp.status_code == 401 or resp.status_code == 403:
                last_error = f"Errore autenticazione ({resp.status_code}): Token di sessione scaduto o non valido."
            else:
                last_error = f"Errore HTTP {resp.status_code} su endpoint {ep}."
        except Exception as e:
            last_error = f"Errore di rete: {str(e)}"

    raise RuntimeError(last_error or "Impossibile recuperare i dati da Fantacalcio.it.")


def sync_league_from_fantacalcio_api(token: str, league_id=None, df_master=None) -> tuple:
    """
    Performs full end-to-end synchronization from Fantacalcio.it:
    1. Fetches teams, players, and active loans with sDay and eDay.
    2. Maps players to official master dataset (names, Mantra roles, stats).
    3. Auto-expires loans where eDay < current_matchday.
    4. Updates loans_registry.json and league_rosters.json.
    5. Stores token for continuous zero-click background sync.
    
    Returns: (success: bool, message: str, stats: dict)
    """
    lid = league_id or get_active_league_id()

    # Load master player dictionary if not supplied
    if df_master is None or df_master.empty:
        master_csv = os.path.join(DATA_DIR, "players_master.csv")
        if os.path.exists(master_csv):
            try:
                df_master = pd.read_csv(master_csv)
            except Exception:
                df_master = pd.DataFrame()

    player_map_by_cod = {}
    if df_master is not None and not df_master.empty and 'Cod' in df_master.columns:
        for _, row in df_master.iterrows():
            try:
                cod_int = int(row['Cod'])
                player_map_by_cod[cod_int] = row.to_dict()
            except Exception:
                pass

    try:
        raw_payload = fetch_raw_league_data(token)
    except Exception as e:
        return False, str(e), {}

    # Extract team array
    teams_raw = []
    if isinstance(raw_payload, dict):
        if 'data' in raw_payload and isinstance(raw_payload['data'], list):
            teams_raw = raw_payload['data']
        elif 'teams' in raw_payload and isinstance(raw_payload['teams'], list):
            teams_raw = raw_payload['teams']
        elif 'squadre' in raw_payload and isinstance(raw_payload['squadre'], list):
            teams_raw = raw_payload['squadre']
    elif isinstance(raw_payload, list):
        teams_raw = raw_payload

    if not teams_raw:
        return False, "Nessuna squadra trovata nella risposta dell'API di Fantacalcio.it.", {}

    # Map team IDs to team names
    team_names_by_id = {}
    for t in teams_raw:
        tid = t.get('id')
        tname = str(t.get('n') or t.get('name') or t.get('squadra') or f"Squadra_{tid}").strip()
        if tid is not None:
            team_names_by_id[tid] = tname

    # Determine current Serie A matchday
    current_giornata = 1
    try:
        current_giornata, _ = get_matchday_from_date()
    except Exception:
        pass

    # Extract all loans across all teams
    all_loans_raw = []
    for t in teams_raw:
        pls = t.get('pl') or t.get('loans') or []
        for l in pls:
            all_loans_raw.append(l)

    # Process loans: active vs terminated
    active_loans_reg = []
    terminated_loans_reg = []
    loan_lookup_active = {}  # (player_cod, borrower_team_id) -> loan_dict

    for l in all_loans_raw:
        p_cod = l.get('id') or l.get('playerId')
        t_from = l.get('tFrom') or l.get('from')
        t_to = l.get('tTo') or l.get('to')
        s_day = int(l.get('sDay') or 1)
        e_day = int(l.get('eDay') or 38)

        owner_name = team_names_by_id.get(t_from, f"Team_{t_from}")
        borrower_name = team_names_by_id.get(t_to, f"Team_{t_to}")

        p_info = player_map_by_cod.get(int(p_cod)) if p_cod is not None else None
        p_name = p_info.get('Giocatore') if p_info else f"Calciatore_{p_cod}"

        is_expired = current_giornata > e_day

        loan_record = {
            'player_name': p_name,
            'player_cod': p_cod,
            'owner_team': owner_name,
            'owner_team_id': t_from,
            'borrower_team': borrower_name,
            'borrower_team_id': t_to,
            'start_matchday': s_day,
            'end_matchday': e_day,
            'sDay': s_day,
            'eDay': e_day,
            'scadenza_giornata': e_day,
            'cost': 1,
            'loan_fee': 0,
            'status': 'expired' if is_expired else 'active'
        }

        if is_expired:
            terminated_loans_reg.append({
                'player_name': p_name,
                'owner_team': owner_name,
                'borrower_team': borrower_name,
                'terminated_at': f"Auto-scaduto alla G{current_giornata} (scadenza: G{e_day})"
            })
        else:
            active_loans_reg.append(loan_record)
            if p_cod is not None:
                loan_lookup_active[(int(p_cod), t_to)] = loan_record

    # Parse rosters per team
    parsed_league_rosters = {}
    total_players = 0

    for t in teams_raw:
        t_id = t.get('id')
        t_name = team_names_by_id.get(t_id, f"Squadra_{t_id}")
        roster_list = []

        cal_str = t.get('cal') or ""
        cs_str = t.get('cs') or ""

        cal_ids = [int(x.strip()) for x in str(cal_str).split(';') if x.strip().isdigit()]
        costs = [int(x.strip()) for x in str(cs_str).split(';') if x.strip().isdigit()]

        while len(costs) < len(cal_ids):
            costs.append(1)

        for idx, cod in enumerate(cal_ids):
            cost_val = costs[idx] if idx < len(costs) else 1
            p_data = player_map_by_cod.get(cod)

            if p_data:
                player_entry = {
                    'Cod': cod,
                    'Giocatore': str(p_data.get('Giocatore', f'Calciatore {cod}')),
                    'NomeGrezzo': str(p_data.get('Giocatore', f'Calciatore {cod}')),
                    'Squadra': str(p_data.get('Squadra', 'Serie A')),
                    'RuoloClassic': str(p_data.get('RuoloClassic', 'C')),
                    'RuoloMantra': str(p_data.get('RuoloMantra', 'C')),
                    'Costo': cost_val,
                    'FuoriSerieA': False,
                    'InPrestito': False,
                    'Prestito_OUT': False
                }
            else:
                player_entry = {
                    'Cod': cod,
                    'Giocatore': f'Calciatore {cod}',
                    'NomeGrezzo': f'Calciatore {cod}',
                    'Squadra': 'Serie A',
                    'RuoloClassic': 'C',
                    'RuoloMantra': 'C',
                    'Costo': cost_val,
                    'FuoriSerieA': False,
                    'InPrestito': False,
                    'Prestito_OUT': False
                }

            # Check if this player is in an active loan into this team
            if (cod, t_id) in loan_lookup_active:
                loan_info = loan_lookup_active[(cod, t_id)]
                player_entry['InPrestito'] = True
                player_entry['Controparte'] = loan_info['owner_team']
                player_entry['Costo'] = loan_info.get('loan_fee', 0)
                player_entry['Prestito_OUT'] = False
            elif cost_val == 0:
                # If Cost == 0 but NOT in active loans -> expired ghost loan, skip it!
                continue

            roster_list.append(player_entry)

        parsed_league_rosters[t_name] = roster_list
        total_players += len(roster_list)

    # Flag Prestito_OUT on owner rosters
    for loan_info in active_loans_reg:
        o_name = loan_info['owner_team']
        p_cod = loan_info.get('player_cod')
        if o_name in parsed_league_rosters:
            for p in parsed_league_rosters[o_name]:
                if p.get('Cod') == p_cod or p.get('Giocatore').strip().lower() == loan_info['player_name'].strip().lower():
                    p['Prestito_OUT'] = True
                    p['Controparte'] = loan_info['borrower_team']
                    break

    # Update loans_registry.json
    existing_reg = load_loans_registry(lid)
    existing_term = existing_reg.get('terminated_loans', [])
    combined_term_map = {(t.get('player_name', '').strip().lower(), t.get('borrower_team', '').strip().lower()): t for t in existing_term}
    for t in terminated_loans_reg:
        combined_term_map[(t.get('player_name', '').strip().lower(), t.get('borrower_team', '').strip().lower())] = t

    updated_registry = {
        'league_id': lid,
        'loans': active_loans_reg,
        'terminated_loans': list(combined_term_map.values()),
        'last_updated': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'sync_source': 'Fantacalcio.it API'
    }
    save_loans_registry(updated_registry, lid)

    # Reconcile & save league rosters
    reconcile_rosters_with_loans(parsed_league_rosters, league_id=lid, df_master=df_master)
    save_league_rosters(parsed_league_rosters, league_id=lid)

    # Save token for continuous background synchronization
    save_stored_api_token(token, league_id=lid)

    # Update metadata
    save_league_metadata(
        source="Fantacalcio.it API Live Sync",
        filename=f"API_Live_{lid}",
        league_id=lid,
        extra={
            'last_imported_file': 'Fantacalcio.it Direct API',
            'teams_count': len(parsed_league_rosters),
            'players_count': total_players,
            'active_loans_count': len(active_loans_reg),
            'expired_loans_count': len(terminated_loans_reg)
        }
    )

    summary_stats = {
        'teams_count': len(parsed_league_rosters),
        'players_count': total_players,
        'active_loans': len(active_loans_reg),
        'expired_loans': len(terminated_loans_reg)
    }

    msg = f"Sincronizzazione API completata: {len(parsed_league_rosters)} squadre, {total_players} calciatori e {len(active_loans_reg)} prestiti attivi (G{current_giornata})."
    return True, msg, summary_stats
