"""
League Manager for Fantacalcio Mantra.
Universal, resilient parser for multi-team league exports from Fantacalcio.it.
Supports:
- Excel (.xlsx, .xls) and CSV (.csv, .tsv) files.
- Any sheet name (auto-detects 'ROSE', 'Rose', 'Squadre', or falls back to first sheet).
- Matrix layout (Team columns side-by-side with or without empty separator columns).
- Tabular / Long layout (Squadra, Giocatore, Ruolo, Costo).
- 3-tier fuzzy & normalized player name matching to guarantee official Mantra roles and stats from df_master.
- Out of Serie A players flagged with '*' (to be released).
- Free loan players flagged with Costo == 0.
"""

import os
import sys
import io
import json
import unicodedata
import re
import datetime
import copy
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.roster_manager import save_user_roster, normalize_str, match_player_name

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
LEAGUES_DIR = os.path.join(DATA_DIR, "leagues")
REGISTRY_FILE = os.path.join(LEAGUES_DIR, "leagues_registry.json")
ACTIVE_LEAGUE_FILE = os.path.join(DATA_DIR, "active_league.json")

# Root fallback / compatibility files:
ROOT_LEAGUE_FILE = os.path.join(DATA_DIR, "league_rosters.json")
ROOT_CONFIG_FILE = os.path.join(DATA_DIR, "league_config.json")
ROOT_METADATA_FILE = os.path.join(DATA_DIR, "league_metadata.json")
ROOT_USER_ROSTER_FILE = os.path.join(DATA_DIR, "user_roster.json")

# Backwards compatibility aliases
LEAGUE_FILE = ROOT_LEAGUE_FILE
CONFIG_FILE = ROOT_CONFIG_FILE
METADATA_FILE = ROOT_METADATA_FILE


def sanitize_league_id(name):
    """Generates a clean filesystem-friendly directory name for a league."""
    if not name:
        return "Nuova_Lega"
    clean = re.sub(r'[^a-zA-Z0-9_\-\s]', '', str(name)).strip()
    clean = re.sub(r'\s+', '_', clean)
    return clean or "Nuova_Lega"


def ensure_default_league_migrated():
    """Ensures data/leagues/ directory and leagues_registry.json exist, migrating default files if needed."""
    os.makedirs(LEAGUES_DIR, exist_ok=True)
    
    registry = {}
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
                registry = json.load(f)
        except Exception:
            registry = {}

    default_league_id = "Lega_Principale"
    default_dir = os.path.join(LEAGUES_DIR, default_league_id)
    os.makedirs(default_dir, exist_ok=True)

    if default_league_id not in registry:
        registry[default_league_id] = {
            "id": default_league_id,
            "name": "Lega Principale",
            "type": "mantra",
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    elif 'type' not in registry[default_league_id]:
        registry[default_league_id]['type'] = 'mantra'
        try:
            with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
                json.dump(registry, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # Copy root files into default league dir if they don't exist there yet
    for root_f, dst_f in [
        (ROOT_LEAGUE_FILE, os.path.join(default_dir, "league_rosters.json")),
        (ROOT_CONFIG_FILE, os.path.join(default_dir, "league_config.json")),
        (ROOT_METADATA_FILE, os.path.join(default_dir, "league_metadata.json")),
        (ROOT_USER_ROSTER_FILE, os.path.join(default_dir, "user_roster.json")),
    ]:
        if os.path.exists(root_f) and not os.path.exists(dst_f):
            try:
                import shutil
                shutil.copy2(root_f, dst_f)
            except Exception:
                pass

    if not os.path.exists(ACTIVE_LEAGUE_FILE):
        try:
            with open(ACTIVE_LEAGUE_FILE, 'w', encoding='utf-8') as f:
                json.dump({"active_league": default_league_id}, f, indent=2)
        except Exception:
            pass

    return registry


def get_available_leagues(include_all_for_admin=False):
    """Returns dictionary of available leagues from registry, filtered by current user permissions unless include_all_for_admin=True."""
    ensure_default_league_migrated()
    reg = {"Lega_Principale": {"id": "Lega_Principale", "name": "Lega Principale", "type": "mantra"}}
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict) and len(loaded) > 0:
                    reg = loaded
        except Exception:
            pass
    if include_all_for_admin:
        return reg
    try:
        from engine.auth_manager import filter_leagues_for_current_user
        filtered = filter_leagues_for_current_user(reg)
        if isinstance(filtered, dict):
            return filtered
    except Exception:
        pass
    return reg


def get_active_league_id():
    """
    Resolves the active league ID:
    1. Streamlit session_state['active_league_id']
    2. Streamlit URL query parameter ?league=...
    3. File active_league.json
    4. First league in registry or 'Lega_Principale'
    """
    leagues = get_available_leagues()
    
    try:
        import streamlit as st
        # 1. Session state
        if 'active_league_id' in st.session_state and st.session_state['active_league_id'] in leagues:
            return st.session_state['active_league_id']
            
        # 2. Query param
        if hasattr(st, 'query_params') and 'league' in st.query_params:
            url_league = st.query_params.get('league')
            if isinstance(url_league, list) and len(url_league) > 0:
                url_league = url_league[0]
            if url_league and url_league in leagues:
                st.session_state['active_league_id'] = url_league
                return url_league
    except Exception:
        pass

    # 3. Disk fallback
    if os.path.exists(ACTIVE_LEAGUE_FILE):
        try:
            with open(ACTIVE_LEAGUE_FILE, 'r', encoding='utf-8') as f:
                d = json.load(f)
                cand = d.get('active_league')
                if cand in leagues:
                    return cand
        except Exception:
            pass

    if "Lega_Principale" in leagues:
        return "Lega_Principale"
    return list(leagues.keys())[0] if leagues else "Lega_Principale"


def get_league_type(league_id=None):
    """
    Returns 'mantra' or 'classic' for the active or specified league.
    Prioritizes:
    1. Specified or active league's config (paths['config'])
    2. Registry entry (leagues_registry.json)
    3. Session state active_league_type (if active league matches)
    4. Fallback ('mantra')
    """
    lid = league_id or get_active_league_id()

    # 1. League config file
    paths = get_league_paths(lid)
    if os.path.exists(paths['config']):
        try:
            with open(paths['config'], 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                lt = cfg.get('league_type')
                if lt and str(lt).lower() in ['mantra', 'classic']:
                    return str(lt).lower()
        except Exception:
            pass

    # 2. Registry file
    leagues = get_available_leagues(include_all_for_admin=True)
    if lid in leagues and 'type' in leagues[lid]:
        lt = leagues[lid]['type']
        if lt and str(lt).lower() in ['mantra', 'classic']:
            return str(lt).lower()

    # 3. Streamlit session state fallback
    try:
        import streamlit as st
        active_lid = st.session_state.get('active_league_id')
        if (not league_id or active_lid == lid) and 'active_league_type' in st.session_state:
            lt = st.session_state.get('active_league_type')
            if lt and str(lt).lower() in ['mantra', 'classic']:
                return str(lt).lower()
    except Exception:
        pass

    return 'mantra'


def set_league_type(league_type, persist_disk=True, league_id=None):
    """
    Sets the league type to 'mantra' or 'classic'.
    Updates session_state, URL query params, league_config.json, and leagues_registry.json.
    """
    lt = str(league_type).strip().lower()
    if lt not in ['mantra', 'classic']:
        lt = 'mantra'

    try:
        import streamlit as st
        st.session_state['active_league_type'] = lt
        if hasattr(st, 'query_params'):
            st.query_params['mode'] = lt
    except Exception:
        pass

    # Purge stale widget states across tabs
    purge_team_and_league_session_state()

    if persist_disk:
        paths = get_league_paths(league_id)
        cfg = {}
        if os.path.exists(paths['config']):
            try:
                with open(paths['config'], 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}
        cfg['league_type'] = lt
        try:
            with open(paths['config'], 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

        lid = league_id or get_active_league_id()
        reg = get_available_leagues(include_all_for_admin=True)
        if lid in reg:
            reg[lid]['type'] = lt
            try:
                with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
                    json.dump(reg, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        try:
            root_cfg = {}
            if os.path.exists(ROOT_CONFIG_FILE):
                with open(ROOT_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    root_cfg = json.load(f)
            root_cfg['league_type'] = lt
            with open(ROOT_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(root_cfg, f, indent=2)
        except Exception:
            pass

    return lt


def get_league_paths(league_id=None):
    """Returns a dict of filesystem paths for a specific league or the currently active league."""
    ensure_default_league_migrated()
    if not league_id:
        league_id = get_active_league_id()
    
    ldir = os.path.join(LEAGUES_DIR, league_id)
    os.makedirs(ldir, exist_ok=True)
    return {
        'id': league_id,
        'dir': ldir,
        'rosters': os.path.join(ldir, "league_rosters.json"),
        'config': os.path.join(ldir, "league_config.json"),
        'metadata': os.path.join(ldir, "league_metadata.json"),
        'user_roster': os.path.join(ldir, "user_roster.json")
    }


def purge_team_and_league_session_state():
    """
    Purges all team-specific and league-specific widget states and transient keys
    from Streamlit session_state, and clears @st.cache_data.
    Preserves core authentication, active IDs, and user settings.
    This guarantees that switching teams or leagues produces a 100% clean UI render,
    identical to an F5 browser reload.
    """
    try:
        import streamlit as st
        PRESERVED_KEYS = {
            'auth_username',
            'auth_user',
            'current_user',
            'force_login_screen',
            'active_league_id',
            'active_my_team',
            'active_league_type',
            'selected_giornata',
            '_last_auto_giornata',
            '_last_code_version',
            'last_processed_stats_sig',
            '_admin_panel_expanded',
            '_admin_user_saved_msg',
            'setup_mode',
            'custom_league_data',
            'custom_league_meta'
        }
        keys_to_delete = [
            k for k in list(st.session_state.keys())
            if k not in PRESERVED_KEYS and not str(k).endswith('_saved_file_sig')
        ]
        for k in keys_to_delete:
            st.session_state.pop(k, None)

        # Clear Streamlit computation caches
        st.cache_data.clear()
    except Exception:
        pass


def set_active_league_id(league_id, persist_disk=True):
    """
    Sets the active league ID, updates session_state, URL query_params,
    and optionally persists to active_league.json and syncs root files.
    Automatically aligns active_my_team and active_league_type with the newly selected league.
    """
    leagues = get_available_leagues()
    if league_id not in leagues:
        return get_active_league_id()

    paths = get_league_paths(league_id)

    # Read configured team and league_type for this league
    reg = get_available_leagues(include_all_for_admin=True)
    league_team = None
    league_type = None
    if os.path.exists(paths['config']):
        try:
            with open(paths['config'], 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                league_team = cfg.get('my_team')
                league_type = cfg.get('league_type')
        except Exception:
            pass

    if not league_type or str(league_type).lower() not in ['mantra', 'classic']:
        if league_id in reg and 'type' in reg[league_id]:
            league_type = str(reg[league_id]['type']).lower()
        else:
            league_type = 'mantra'
    else:
        league_type = str(league_type).lower()

    rosters = load_league_rosters(league_id=league_id)
    avail_teams = list(rosters.keys()) if rosters else []

    # Check if user has a default team configured for this league
    try:
        from engine.auth_manager import get_current_user
        curr_u = get_current_user()
        if curr_u:
            def_teams = curr_u.get('default_team_by_league', {}) or {}
            u_team = def_teams.get(league_id)
            if u_team and (not avail_teams or u_team in avail_teams):
                league_team = u_team
    except Exception:
        pass

    if not league_team or (avail_teams and league_team not in avail_teams):
        if 'Bluelock' in avail_teams:
            league_team = 'Bluelock'
        elif avail_teams:
            league_team = avail_teams[0]
        else:
            league_team = 'Bluelock'

    try:
        import streamlit as st
        st.session_state['active_league_id'] = league_id
        st.session_state['active_league_type'] = league_type
        st.session_state['active_my_team'] = league_team
        if hasattr(st, 'query_params'):
            st.query_params['league'] = league_id
            st.query_params['mode'] = league_type
            st.query_params['team'] = league_team
        # Clear custom session override if user switches to a stored league
        st.session_state.pop('custom_league_data', None)
        st.session_state.pop('custom_league_meta', None)
    except Exception:
        pass

    # Synchronize user_roster.json for the new league & team (without recursion)
    try:
        sync_user_roster_from_league(league_data=rosters, team_name=league_team, league_id=league_id, update_active_team=False)
    except Exception:
        pass

    # Purge all stale widget session state across all tabs and clear cache
    purge_team_and_league_session_state()

    if persist_disk:
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            with open(ACTIVE_LEAGUE_FILE, 'w', encoding='utf-8') as f:
                json.dump({"active_league": league_id}, f, indent=2)
        except Exception:
            pass
        # Ensure paths['config'] always records both my_team and league_type
        try:
            cfg = {}
            if os.path.exists(paths['config']):
                with open(paths['config'], 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
            cfg['my_team'] = league_team
            cfg['league_type'] = league_type
            with open(paths['config'], 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    # Mirror files to root data/ for backwards compatibility
    for src, dst in [
        (paths['rosters'], ROOT_LEAGUE_FILE),
        (paths['config'], ROOT_CONFIG_FILE),
        (paths['metadata'], ROOT_METADATA_FILE),
        (paths['user_roster'], ROOT_USER_ROSTER_FILE),
    ]:
        if os.path.exists(src):
            try:
                import shutil
                shutil.copy2(src, dst)
            except Exception:
                pass

    return league_id


def create_new_league(display_name, parsed_rosters=None, my_team=None, league_type='mantra'):
    """
    Creates a new league in the registry and filesystem, optionally initializing it with parsed rosters.
    Supports setting league_type to 'mantra' or 'classic'.
    Returns (success, league_id, message).
    """
    name = str(display_name).strip()
    if not name:
        return False, None, "Il nome della lega non può essere vuoto."

    lt = str(league_type).strip().lower()
    if lt not in ['mantra', 'classic']:
        lt = 'mantra'

    base_id = sanitize_league_id(name)
    registry = get_available_leagues(include_all_for_admin=True)

    # Ensure unique ID
    league_id = base_id
    counter = 2
    while league_id in registry:
        league_id = f"{base_id}_{counter}"
        counter += 1

    ldir = os.path.join(LEAGUES_DIR, league_id)
    os.makedirs(ldir, exist_ok=True)

    owner_uname = "admin"
    try:
        from engine.auth_manager import get_current_user, grant_league_to_user
        curr_u = get_current_user()
        if curr_u and curr_u.get('username'):
            owner_uname = curr_u['username']
    except Exception:
        pass

    registry[league_id] = {
        "id": league_id,
        "name": name,
        "type": lt,
        "owner": owner_uname,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

    try:
        from engine.auth_manager import grant_league_to_user
        grant_league_to_user(owner_uname, league_id)
    except Exception:
        pass

    paths = get_league_paths(league_id)

    if parsed_rosters:
        with open(paths['rosters'], 'w', encoding='utf-8') as f:
            json.dump(parsed_rosters, f, indent=2, ensure_ascii=False)

        meta = {
            'last_updated': datetime.datetime.now().strftime("%d/%m/%Y alle ore %H:%M"),
            'source': f"Creazione Lega ({name})",
            'filename': f"{name}.xlsx"
        }
        with open(paths['metadata'], 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        if not my_team and parsed_rosters:
            my_team = list(parsed_rosters.keys())[0]

        cfg_dict = {'my_team': my_team or '', 'league_type': lt}
        with open(paths['config'], 'w', encoding='utf-8') as f:
            json.dump(cfg_dict, f, indent=2)
            pnames = [p['Giocatore'] for p in parsed_rosters[my_team]]
            with open(paths['user_roster'], 'w', encoding='utf-8') as f:
                json.dump(pnames, f, indent=2, ensure_ascii=False)

    set_active_league_id(league_id, persist_disk=True)
    try:
        from engine.auth_manager import sync_users_and_leagues_to_github
        sync_users_and_leagues_to_github(background=True)
    except Exception:
        pass
    return True, league_id, f"Lega '{name}' creata e attivata con successo!"


def delete_league(league_id):
    """
    Deletes a league from registry and disk.
    Cannot delete if only 1 league exists.
    """
    registry = get_available_leagues(include_all_for_admin=True)
    if len(registry) <= 1:
        return False, "Impossibile eliminare l'unica lega presente."
    if league_id not in registry:
        return False, "Lega non trovata."

    del registry[league_id]
    with open(REGISTRY_FILE, 'w', encoding='utf-8') as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

    ldir = os.path.join(LEAGUES_DIR, league_id)
    if os.path.exists(ldir):
        try:
            import shutil
            shutil.rmtree(ldir, ignore_errors=True)
        except Exception:
            pass

    # If the active league was deleted, switch to the first remaining one
    active_now = get_active_league_id()
    if active_now == league_id:
        remaining = list(registry.keys())[0]
        set_active_league_id(remaining, persist_disk=True)

    return True, f"Lega eliminata con successo."


def clean_player_name(val):
    if not val or pd.isna(val):
        return ""
    s = str(val).strip()
    s = s.replace('*', '').strip()
    return s


def read_raw_league_file(file_or_path):
    """
    Reads an uploaded file buffer or path into a pandas DataFrame (without header).
    Resilient to:
    - BytesIO / Streamlit UploadedFile / filepath string
    - .xlsx, .xls, .csv, .tsv
    - Any sheet name
    """
    # 1. Determine if CSV or Excel
    is_csv = False
    filename = ""
    if hasattr(file_or_path, 'name'):
        filename = str(file_or_path.name).lower()
    elif isinstance(file_or_path, str):
        filename = file_or_path.lower()

    if filename.endswith('.csv') or filename.endswith('.tsv') or filename.endswith('.txt'):
        is_csv = True

    if is_csv:
        # Read CSV with separator sniffing
        encodings = ['utf-8', 'latin-1', 'cp1252']
        for enc in encodings:
            try:
                if hasattr(file_or_path, 'seek'):
                    file_or_path.seek(0)
                df = pd.read_csv(file_or_path, sep=None, engine='python', header=None, encoding=enc)
                if not df.empty:
                    return df
            except Exception:
                continue
        # Fallback standard comma
        if hasattr(file_or_path, 'seek'):
            file_or_path.seek(0)
        return pd.read_csv(file_or_path, header=None)

    # 2. Excel reading (.xlsx, .xls)
    try:
        if hasattr(file_or_path, 'seek'):
            file_or_path.seek(0)
        xl = pd.ExcelFile(file_or_path)
        sheet_names = xl.sheet_names
        
        # Pick best sheet
        chosen_sheet = None
        for s in sheet_names:
            if s.strip().upper() == 'ROSE':
                chosen_sheet = s
                break
        if not chosen_sheet:
            for s in sheet_names:
                s_lower = s.lower()
                if any(kw in s_lower for kw in ['rose', 'squadr', 'lega', 'formaz', 'elenco']):
                    chosen_sheet = s
                    break
        if not chosen_sheet and len(sheet_names) > 0:
            chosen_sheet = sheet_names[0]

        df = pd.read_excel(xl, sheet_name=chosen_sheet, header=None)
        return df
    except Exception as e:
        # In case it's actually a CSV renamed to .xlsx or raw text
        try:
            if hasattr(file_or_path, 'seek'):
                file_or_path.seek(0)
            return pd.read_csv(file_or_path, sep=None, engine='python', header=None)
        except Exception:
            raise ValueError(f"Impossibile leggere il file delle rose: {e}")


def parse_official_league_excel(file_or_path, df_master):
    """
    Parses multi-team league exports from Fantacalcio.it.
    Supports:
    - Multi-column matrix format (Team1, Costo, [empty], Team2, Costo, ...)
    - Tabular long format (Squadra, Calciatore, Ruolo, Costo)
    - 3-tier fuzzy & normalized matching with df_master
    """
    df_raw = read_raw_league_file(file_or_path)
    if df_raw is None or df_raw.empty:
        raise ValueError("Il file delle rose è vuoto.")

    # Clean empty rows and ensure standard 0..N-1 integer column indexing
    df_raw = df_raw.dropna(how='all').reset_index(drop=True)
    df_raw.columns = range(df_raw.shape[1])

    # Build 3-tier lookup dictionaries from df_master
    stats_map = {}
    norm_stats_map = {}
    all_master_names = []
    if df_master is not None and not df_master.empty and 'Giocatore' in df_master.columns:
        for _, row in df_master.iterrows():
            orig_name = str(row['Giocatore']).strip()
            row_dict = row.to_dict()
            stats_map[orig_name] = row_dict
            norm_stats_map[normalize_str(orig_name)] = row_dict
            all_master_names.append(orig_name)

    def match_player_data(raw_name):
        clean_name = raw_name.replace('*', '').strip()
        # 1. Exact match
        if clean_name in stats_map:
            return stats_map[clean_name], clean_name
        # 2. Normalized match (accents, punctuation, lower)
        norm = normalize_str(clean_name)
        if norm in norm_stats_map:
            p_info = norm_stats_map[norm]
            return p_info, p_info.get('Giocatore', clean_name)
        # 3. Fuzzy / Token / Alias match
        fuzzy = match_player_name(clean_name, all_master_names)
        if fuzzy and fuzzy in stats_map:
            return stats_map[fuzzy], fuzzy
        # Fallback: unmatched player
        return {}, clean_name

    # Check if 3-column ID format (e.g. Squadra, Cod/ID, Costo)
    is_id_format = False
    if df_raw.shape[1] >= 3:
        id_score = 0
        for test_r in range(min(10, len(df_raw))):
            row_v = df_raw.iloc[test_r]
            c0 = str(row_v.iloc[0]).strip()
            c1 = str(row_v.iloc[1]).strip()
            c2 = str(row_v.iloc[2]).strip()
            if c0 and c0 not in ['$', '$,$,$'] and c1.isdigit() and len(c1) >= 1 and (c2.isdigit() or c2.replace('.', '', 1).isdigit()):
                id_score += 1
        if id_score >= 3:
            is_id_format = True

    if is_id_format:
        league_data = {}
        id_master_map = {}
        if df_master is not None and not df_master.empty and 'Cod' in df_master.columns:
            id_master_map = {int(r['Cod']): r.to_dict() for _, r in df_master.iterrows() if pd.notna(r['Cod'])}

        for r in range(len(df_raw)):
            row_v = df_raw.iloc[r]
            t_name = str(row_v.iloc[0]).strip()
            if not t_name or t_name in ['$', '$,$,$', 'nan']:
                continue
            try:
                cid = int(float(str(row_v.iloc[1]).strip()))
                cost = int(float(str(row_v.iloc[2]).strip()))
            except (ValueError, TypeError):
                continue

            p_info = id_master_map.get(cid, {})
            p_name = p_info.get('Giocatore', f"Calciatore_{cid}")
            
            p_entry = {
                'Cod': cid,
                'Giocatore': p_name,
                'NomeGrezzo': p_name,
                'Squadra': p_info.get('Squadra', 'Serie A'),
                'RuoloClassic': p_info.get('RuoloClassic', 'C'),
                'RuoloMantra': p_info.get('RuoloMantra', 'C'),
                'FVM': p_info.get('FVM', 1),
                'Costo': cost,
                'InPrestito': (cost == 0),
                'FuoriSerieA': bool(p_info.get('FuoriSerieA', False)),
                'Presenze': p_info.get('Presenze', 0),
                'MV_Stagione': p_info.get('MV_Stagione', 0.0),
                'FM_Stagione': p_info.get('FM_Stagione', 0.0),
                'GF': p_info.get('GF', 0),
                'GS': p_info.get('GS', 0),
                'ASS': p_info.get('ASS', 0),
                'AMM': p_info.get('AMM', 0),
                'ESP': p_info.get('ESP', 0)
            }
            if t_name not in league_data:
                league_data[t_name] = []
            league_data[t_name].append(p_entry)

        # Deduplicate inside same team keeping highest cost
        for t_name, pls in league_data.items():
            uniq = {}
            for p in pls:
                cid = p['Cod']
                if cid not in uniq or p['Costo'] > uniq[cid]['Costo']:
                    uniq[cid] = p
            league_data[t_name] = list(uniq.values())

        if league_data:
            return league_data

    # Check if Tabular Long Format (e.g. Columns: Squadra, Giocatore/Calciatore, Ruolo, Costo)
    is_tabular = False
    col_map = {}
    for r_idx in range(min(5, len(df_raw))):
        row_vals = [str(x).strip().lower() for x in df_raw.iloc[r_idx] if pd.notna(x)]
        has_sq = any(any(k in v for k in ['squadra', 'fantasquadra', 'team']) for v in row_vals)
        has_gioc = any(any(k in v for k in ['calciatore', 'giocatore', 'nome']) for v in row_vals)
        if has_sq and has_gioc:
            is_tabular = True
            for c_idx, val in enumerate(df_raw.iloc[r_idx]):
                v_str = str(val).strip().lower() if pd.notna(val) else ""
                if 'fantasquadra' in v_str:
                    col_map['squadra'] = c_idx
                elif 'squadra' in v_str and 'squadra' not in col_map:
                    col_map['squadra'] = c_idx
                elif any(k in v_str for k in ['calciatore', 'giocatore', 'nome']):
                    col_map['giocatore'] = c_idx
                elif any(k in v_str for k in ['costo', 'prezzo', 'spesa']):
                    col_map['costo'] = c_idx
                elif 'mantra' in v_str:
                    col_map['ruolo_mantra'] = c_idx
                elif v_str in ['r.', 'r', 'ruolo']:
                    col_map['ruolo_classic'] = c_idx
                elif v_str in ['sq.', 'sq']:
                    col_map['squadra_serie_a'] = c_idx
                elif v_str in ['#', 'id', 'cod']:
                    col_map['cod'] = c_idx
                elif v_str in ['pgv', 'pg', 'presenze']:
                    col_map['presenze'] = c_idx
                elif v_str in ['mv']:
                    col_map['mv'] = c_idx
                elif v_str in ['fm']:
                    col_map['fm'] = c_idx
                elif 'fuori lista' in v_str:
                    col_map['fuori_lista'] = c_idx
                elif 'fvm' in v_str:
                    col_map['fvm'] = c_idx
            tabular_header_row = r_idx
            break

    league_data = {}

    if is_tabular and 'squadra' in col_map and 'giocatore' in col_map:
        # PARSE TABULAR FORMAT
        for r in range(tabular_header_row + 1, len(df_raw)):
            sq_val = df_raw.iloc[r, col_map['squadra']]
            p_val = df_raw.iloc[r, col_map['giocatore']]
            if pd.isna(sq_val) or pd.isna(p_val):
                continue
            team_name = str(sq_val).strip()
            p_str = str(p_val).strip()
            if not team_name or not p_str or p_str.lower() in ['totale', 'nan']:
                continue

            cost = 1
            if 'costo' in col_map:
                c_val = df_raw.iloc[r, col_map['costo']]
                if pd.notna(c_val):
                    try:
                        cost = int(float(str(c_val).strip()))
                    except Exception:
                        cost = 1

            p_info, matched_name = match_player_data(p_str)

            # Ruolo Mantra: prioritize raw value from file if present (e.g. 'B/Dd/E')
            ruolo_mantra = p_info.get('RuoloMantra', 'C')
            if 'ruolo_mantra' in col_map and pd.notna(df_raw.iloc[r, col_map['ruolo_mantra']]):
                raw_rm = str(df_raw.iloc[r, col_map['ruolo_mantra']]).strip()
                if raw_rm:
                    ruolo_mantra = raw_rm.replace('/', ';').replace(',', ';').strip()

            # Ruolo Classic:
            ruolo_classic = p_info.get('RuoloClassic', 'C')
            if 'ruolo_classic' in col_map and pd.notna(df_raw.iloc[r, col_map['ruolo_classic']]):
                raw_rc = str(df_raw.iloc[r, col_map['ruolo_classic']]).strip()
                if raw_rc:
                    ruolo_classic = raw_rc

            # Serie A Team:
            sq_sa = p_info.get('Squadra', 'Serie A')
            if 'squadra_serie_a' in col_map and pd.notna(df_raw.iloc[r, col_map['squadra_serie_a']]):
                raw_sa = str(df_raw.iloc[r, col_map['squadra_serie_a']]).strip()
                if raw_sa:
                    sq_sa = raw_sa

            # Fuori serie A:
            is_out = ('*' in p_str)
            if 'fuori_lista' in col_map and pd.notna(df_raw.iloc[r, col_map['fuori_lista']]):
                fl_val = str(df_raw.iloc[r, col_map['fuori_lista']]).strip().lower()
                if fl_val in ['si', 'sì', 'true', '1', '*']:
                    is_out = True

            # Cod:
            cod = p_info.get('Cod', 0)
            if 'cod' in col_map and pd.notna(df_raw.iloc[r, col_map['cod']]):
                try:
                    cod = int(float(str(df_raw.iloc[r, col_map['cod']]).strip()))
                except Exception:
                    pass

            fvm = p_info.get('FVM', 1)
            if 'fvm' in col_map and pd.notna(df_raw.iloc[r, col_map['fvm']]):
                try:
                    fvm = int(float(str(df_raw.iloc[r, col_map['fvm']]).strip()))
                except Exception:
                    pass

            player_entry = {
                'Cod': cod,
                'Giocatore': matched_name,
                'NomeGrezzo': p_str,
                'Squadra': sq_sa,
                'RuoloClassic': ruolo_classic,
                'RuoloMantra': ruolo_mantra,
                'FVM': fvm,
                'Costo': cost,
                'InPrestito': (cost == 0),
                'FuoriSerieA': is_out,
                'Presenze': p_info.get('Presenze', 0),
                'MV_Stagione': p_info.get('MV_Stagione', 0.0),
                'FM_Stagione': p_info.get('FM_Stagione', 0.0),
                'GF': p_info.get('GF', 0),
                'GS': p_info.get('GS', 0),
                'ASS': p_info.get('ASS', 0),
                'AMM': p_info.get('AMM', 0),
                'ESP': p_info.get('ESP', 0)
            }
            if team_name not in league_data:
                league_data[team_name] = []
            league_data[team_name].append(player_entry)

    else:
        # PARSE MULTI-COLUMN MATRIX FORMAT
        # Step 1: Detect header row (scanning first 6 rows)
        header_row_idx = 0
        best_team_count = 0
        for r in range(min(6, len(df_raw))):
            row_items = df_raw.iloc[r]
            # Count candidates for team names in this row
            t_candidates = sum(1 for x in row_items if pd.notna(x) and str(x).strip().lower() not in ['costo', 'totale', '', 'nan'])
            cost_count = sum(1 for x in row_items if pd.notna(x) and str(x).strip().lower() == 'costo')
            if cost_count >= 1 and t_candidates > best_team_count:
                best_team_count = t_candidates
                header_row_idx = r

        header_row = df_raw.iloc[header_row_idx]
        num_cols = df_raw.shape[1]
        col_idx = 0

        while col_idx < num_cols:
            raw_team = header_row.iloc[col_idx]
            if pd.isna(raw_team):
                col_idx += 1
                continue
            
            t_str = str(raw_team).strip()
            if t_str.lower() in ['costo', 'totale', '', 'nan']:
                col_idx += 1
                continue

            team_name = t_str
            # Detect cost column: check adjacent col_idx + 1
            cost_col_idx = None
            if col_idx + 1 < num_cols:
                adj_header = str(header_row.iloc[col_idx + 1]).strip().lower() if pd.notna(header_row.iloc[col_idx + 1]) else ""
                if adj_header == 'costo':
                    cost_col_idx = col_idx + 1
                else:
                    # Check if sample values in col_idx + 1 are numeric costs
                    sample_numeric = 0
                    for check_r in range(header_row_idx + 1, min(header_row_idx + 6, len(df_raw))):
                        val_chk = df_raw.iloc[check_r, col_idx + 1]
                        if pd.notna(val_chk):
                            try:
                                float(str(val_chk).strip())
                                sample_numeric += 1
                            except ValueError:
                                pass
                    if sample_numeric >= 2:
                        cost_col_idx = col_idx + 1

            players = []
            for r in range(header_row_idx + 1, len(df_raw)):
                raw_player = df_raw.iloc[r, col_idx]
                if pd.isna(raw_player):
                    continue
                p_str = str(raw_player).strip()
                if not p_str or p_str.lower() in ['totale', 'nan']:
                    continue

                is_out_of_serie_a = ('*' in p_str)
                cost = 1
                if cost_col_idx is not None:
                    c_val = df_raw.iloc[r, cost_col_idx]
                    if pd.notna(c_val):
                        try:
                            cost = int(float(str(c_val).strip()))
                        except Exception:
                            cost = 1

                p_info, matched_name = match_player_data(p_str)

                players.append({
                    'Cod': p_info.get('Cod', 0),
                    'Giocatore': matched_name,
                    'NomeGrezzo': p_str,
                    'Squadra': p_info.get('Squadra', 'Serie A'),
                    'RuoloClassic': p_info.get('RuoloClassic', 'C'),
                    'RuoloMantra': p_info.get('RuoloMantra', 'C'),
                    'Costo': cost,
                    'InPrestito': (cost == 0),
                    'FuoriSerieA': is_out_of_serie_a,
                    'Presenze': p_info.get('Presenze', 0),
                    'MV_Stagione': p_info.get('MV_Stagione', 0.0),
                    'FM_Stagione': p_info.get('FM_Stagione', 0.0),
                    'GF': p_info.get('GF', 0),
                    'GS': p_info.get('GS', 0),
                    'ASS': p_info.get('ASS', 0),
                    'AMM': p_info.get('AMM', 0),
                    'ESP': p_info.get('ESP', 0)
                })

            # Deduplicate inside same team keeping highest cost
            unique_players = {}
            for p in players:
                g = p['Giocatore']
                if g not in unique_players or p['Costo'] > unique_players[g]['Costo']:
                    unique_players[g] = p

            if unique_players:
                league_data[team_name] = list(unique_players.values())

            # Advance col_idx dynamically
            if cost_col_idx is not None:
                col_idx = cost_col_idx + 1
            else:
                col_idx += 1

            # Skip empty separator columns
            while col_idx < num_cols and pd.isna(header_row.iloc[col_idx]):
                col_idx += 1

    if not league_data:
        raise ValueError("Nessuna squadra o calciatore riconosciuto nel file caricato. Verifica che il file contenga le colonne delle squadre.")

    return league_data


# Backwards compatibility alias
parse_multi_column_league_csv = parse_official_league_excel


def save_league_rosters(league_data, league_id=None):
    """Saves parsed league rosters into the active league's directory and mirrors to root."""
    paths = get_league_paths(league_id)
    with open(paths['rosters'], 'w', encoding='utf-8') as f:
        json.dump(league_data, f, indent=2, ensure_ascii=False)
    # Mirror to root for compatibility
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ROOT_LEAGUE_FILE, 'w', encoding='utf-8') as f:
            json.dump(league_data, f, indent=2, ensure_ascii=False)
        from engine.auth_manager import sync_users_and_leagues_to_github
        sync_users_and_leagues_to_github(background=True)
    except Exception:
        pass
    return league_data


def load_league_rosters(league_id=None):
    """
    Loads league data. Prioritizes session-specific custom league data
    (allowing friends from other leagues to upload their own file in their session
    without overwriting the shared server league).
    Otherwise loads from the active league directory.
    """
    try:
        import streamlit as st
        if 'custom_league_data' in st.session_state and st.session_state['custom_league_data']:
            return st.session_state['custom_league_data']
    except Exception:
        pass

    paths = get_league_paths(league_id)
    active_rosters_file = paths['rosters']

    if os.path.exists(active_rosters_file):
        try:
            with open(active_rosters_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and len(data) > 0:
                    return data
        except Exception as e:
            print(f"Error loading league data from {active_rosters_file}: {e}")

    # Fallback to root LEAGUE_FILE
    if os.path.exists(ROOT_LEAGUE_FILE):
        try:
            with open(ROOT_LEAGUE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and len(data) > 0:
                    return data
        except Exception as e:
            print(f"Error loading league data from {ROOT_LEAGUE_FILE}: {e}")
    return {}


def get_active_my_team(league_id=None):
    """
    Returns the user's selected team for their specific session and active league.
    Validates that the returned team actually exists in the active league's rosters.
    Prioritizes:
    1. Streamlit session_state: st.session_state['active_my_team'] (if valid for this league)
    2. Streamlit URL query parameter: ?team=TeamName (if valid for this league)
    3. File on disk for active league: data/leagues/<league_id>/league_config.json
    4. Root fallback: data/league_config.json
    5. 'Bluelock' or first team in active league
    """
    rosters = load_league_rosters(league_id)
    valid_teams = set(rosters.keys()) if rosters else set()

    try:
        import streamlit as st
        # 1. Session State has TOP priority (if valid for current league)
        if 'active_my_team' in st.session_state and st.session_state['active_my_team']:
            team_cand = st.session_state['active_my_team']
            if not valid_teams or team_cand in valid_teams:
                return team_cand

        # 2. URL Query Parameter
        if hasattr(st, 'query_params') and 'team' in st.query_params:
            url_team = st.query_params.get('team')
            if isinstance(url_team, list) and len(url_team) > 0:
                url_team = url_team[0]
            if url_team and isinstance(url_team, str):
                if not valid_teams or url_team in valid_teams:
                    st.session_state['active_my_team'] = url_team
                    return url_team

        # 2b. Logged-in user's default team for this league
        from engine.auth_manager import get_current_user
        curr_u = get_current_user()
        if curr_u:
            lid_check = league_id or get_active_league_id()
            def_teams = curr_u.get('default_team_by_league', {}) or {}
            u_team = def_teams.get(lid_check)
            if u_team and (not valid_teams or u_team in valid_teams):
                st.session_state['active_my_team'] = u_team
                return u_team
    except Exception:
        pass

    # 3. Active league disk config
    paths = get_league_paths(league_id)
    if os.path.exists(paths['config']):
        try:
            with open(paths['config'], 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                val = cfg.get('my_team')
                if val and (not valid_teams or val in valid_teams):
                    return val
        except Exception:
            pass

    # 4. Root fallback
    if os.path.exists(ROOT_CONFIG_FILE):
        try:
            with open(ROOT_CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                val = cfg.get('my_team')
                if val and (not valid_teams or val in valid_teams):
                    return val
        except Exception:
            pass

    # 5. First team in active league if available
    if 'Bluelock' in valid_teams:
        return 'Bluelock'
    if valid_teams:
        return list(valid_teams)[0]

    return 'Bluelock'


def set_active_my_team(team_name, persist_disk=False, league_id=None):
    """
    Sets the active team for the user's current session in st.session_state.
    Cleans up all stale widget state across tabs so switching teams is 100% clean (like F5).
    Synchronizes user_roster.json with the new team's players.
    Optionally persists to the active league's config and root config.
    """
    lid = league_id or get_active_league_id()
    try:
        import streamlit as st
        st.session_state['active_my_team'] = team_name
        if hasattr(st, 'query_params'):
            st.query_params['team'] = team_name
    except Exception:
        pass

    # Synchronize user_roster.json for this team in this league (without recursion)
    try:
        sync_user_roster_from_league(team_name=team_name, league_id=lid, update_active_team=False)
    except Exception:
        pass

    # Purge all stale widget session state across all tabs and clear cache
    purge_team_and_league_session_state()

    if persist_disk:
        paths = get_league_paths(lid)
        curr_lt = get_league_type(lid)
        try:
            cfg = {}
            if os.path.exists(paths['config']):
                with open(paths['config'], 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
            cfg['my_team'] = team_name
            cfg['league_type'] = curr_lt
            with open(paths['config'], 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass
        try:
            root_cfg = {}
            if os.path.exists(ROOT_CONFIG_FILE):
                with open(ROOT_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    root_cfg = json.load(f)
            root_cfg['my_team'] = team_name
            root_cfg['league_type'] = curr_lt
            with open(ROOT_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(root_cfg, f, indent=2)
        except Exception:
            pass

    return team_name


def save_league_metadata(source="File Excel Fantacalcio.it", filename=None, league_id=None):
    """Stores provenance timestamp and source of the current rosters in active league and root."""
    paths = get_league_paths(league_id)
    meta = {
        'last_updated': datetime.datetime.now().strftime("%d/%m/%Y alle ore %H:%M"),
        'source': source,
        'filename': filename or "Rose_Lega_Ufficiale"
    }
    try:
        with open(paths['metadata'], 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
    try:
        with open(ROOT_METADATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
    return meta


def get_league_metadata(league_id=None):
    """Returns provenance and freshness info of current active league rosters."""
    try:
        import streamlit as st
        if 'custom_league_meta' in st.session_state and st.session_state['custom_league_meta']:
            return st.session_state['custom_league_meta']
    except Exception:
        pass

    paths = get_league_paths(league_id)
    if os.path.exists(paths['metadata']):
        try:
            with open(paths['metadata'], 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    if os.path.exists(paths['rosters']):
        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(paths['rosters']))
        return {
            'last_updated': mtime.strftime("%d/%m/%Y alle ore %H:%M"),
            'source': "File Excel/JSON su disco",
            'filename': os.path.basename(paths['rosters'])
        }

    if os.path.exists(ROOT_METADATA_FILE):
        try:
            with open(ROOT_METADATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    return {
        'last_updated': "Non disponibile",
        'source': "Non configurato",
        'filename': ""
    }


def terminate_loan(player_name, borrower_team, owner_team=None):
    """
    Terminates a loan: removes the loan entry (Costo == 0) from borrower_team.
    The player remains strictly owned by owner_team (where Costo > 0).
    Saves the updated rosters immediately.
    """
    rosters = load_league_rosters()
    if borrower_team in rosters:
        orig_len = len(rosters[borrower_team])
        rosters[borrower_team] = [
            p for p in rosters[borrower_team]
            if not (p['Giocatore'] == player_name and p.get('Costo', 0) == 0)
        ]
        if len(rosters[borrower_team]) < orig_len:
            save_league_rosters(rosters)
            save_league_metadata(source=f"Risoluzione prestito manuale: {player_name}")
            active_team = get_active_my_team()
            if active_team in rosters:
                sync_user_roster_from_league(rosters, active_team)
            return True, f"Prestito di {player_name} a {borrower_team} risolto con successo! Il calciatore rimane al 100% di proprietà."
    return False, f"Calciatore {player_name} a costo 0 non trovato in {borrower_team}."


def add_or_update_loan(player_name, owner_team, borrower_team):
    """
    Registers or updates a loan: creates an entry with Costo == 0 in borrower_team
    referencing player from owner_team.
    """
    rosters = load_league_rosters()
    if owner_team not in rosters or borrower_team not in rosters:
        return False, "Una o entrambe le squadre non esistono nella lega."
    
    owner_pls = rosters[owner_team]
    target_p = next((p for p in owner_pls if p['Giocatore'] == player_name and p.get('Costo', 0) > 0), None)
    if not target_p:
        target_p = next((p for p in owner_pls if p['Giocatore'] == player_name), None)
    if not target_p:
        return False, f"Calciatore '{player_name}' non trovato nella rosa di '{owner_team}'."
    
    # Check if already present in borrower_team
    if any(p['Giocatore'] == player_name for p in rosters[borrower_team]):
        return False, f"'{player_name}' è già presente nella rosa di '{borrower_team}'."
    
    loan_entry = copy.deepcopy(target_p)
    loan_entry['Costo'] = 0
    loan_entry['InPrestito'] = True
    rosters[borrower_team].append(loan_entry)
    save_league_rosters(rosters)
    save_league_metadata(source=f"Nuovo prestito manuale: {player_name} ({owner_team} -> {borrower_team})")
    active_team = get_active_my_team()
    if active_team in rosters:
        sync_user_roster_from_league(rosters, active_team)
    return True, f"Prestito di {player_name} da {owner_team} a {borrower_team} registrato con successo!"


def sync_user_roster_from_league(league_data=None, team_name='Bluelock', league_id=None, update_active_team=False):
    """Synchronizes user_roster.json directly from the specified team in league_data."""
    if league_data is None:
        league_data = load_league_rosters(league_id)
    if team_name in league_data:
        pnames = [p['Giocatore'] for p in league_data[team_name]]
        save_user_roster(pnames, league_id=league_id)
        if update_active_team:
            set_active_my_team(team_name, persist_disk=True, league_id=league_id)
        return pnames
    return []


def build_loan_registry(league_data=None):
    """
    Identifies all loans across the league:
    Where player has Costo == 0 in team A and Costo > 0 in team B.
    """
    if league_data is None:
        league_data = load_league_rosters()

    all_player_appearances = {}
    for team, players in league_data.items():
        for p in players:
            name = p['Giocatore']
            if name not in all_player_appearances:
                all_player_appearances[name] = []
            all_player_appearances[name].append({
                'team': team,
                'cost': p['Costo'],
                'fuori_serie_a': p.get('FuoriSerieA', False),
                'ruolo_mantra': p.get('RuoloMantra', 'C'),
                'squadra_serie_a': p.get('Squadra', '')
            })

    loan_map = {}
    loan_summary_list = []

    for name, appearances in all_player_appearances.items():
        if len(appearances) > 1:
            owner_entry = next((a for a in appearances if a['cost'] > 0), appearances[0])
            borrower_entries = [a for a in appearances if a['cost'] == 0]

            for b in borrower_entries:
                borrower_team = b['team']
                owner_team = owner_entry['team']

                loan_summary_list.append({
                    'Calciatore': name,
                    'Ruolo': owner_entry['ruolo_mantra'],
                    'Squadra': owner_entry['squadra_serie_a'],
                    'Proprietario': owner_team,
                    'In_Prestito_A': borrower_team,
                    'Costo_Asta': owner_entry['cost'],
                    'Tipo': 'Prestito Gratuito (Costo 0)'
                })

                # Mapping for borrower
                loan_map[(borrower_team, name)] = {
                    'Stato_Prestito': 'Prestito IN',
                    'Badge_Prestito': f"📥 IN PRESTITO (da {owner_team})",
                    'Dettaglio_Prestito': f"In prestito temporaneo da {owner_team} (costo d'asta originale: {owner_entry['cost']} cr.)",
                    'Controparte': owner_team,
                    'Schierabile': True,
                    'Da_Svincolare': b['fuori_serie_a']
                }

                # Mapping for owner
                loan_map[(owner_team, name)] = {
                    'Stato_Prestito': 'Prestito OUT',
                    'Badge_Prestito': f"📤 PRESTITO CEDUTO (a {borrower_team})",
                    'Dettaglio_Prestito': f"Cartellino di proprietà prestato gratuitamente a {borrower_team}",
                    'Controparte': borrower_team,
                    'Schierabile': False,
                    'Da_Svincolare': owner_entry['fuori_serie_a']
                }

    if loan_summary_list:
        df_loans = pd.DataFrame(loan_summary_list)
    else:
        df_loans = pd.DataFrame(columns=['Calciatore', 'Ruolo', 'Squadra', 'Proprietario', 'In_Prestito_A', 'Costo_Asta', 'Tipo'])

    return loan_map, df_loans


def get_out_of_serie_a_summary(league_data=None):
    """Returns a DataFrame of all players marked with '*' (out of Serie A / to be released)."""
    if league_data is None:
        league_data = load_league_rosters()

    out_list = []
    for team, players in league_data.items():
        for p in players:
            is_out = bool(
                p.get('FuoriSerieA', False)
                or p.get('Da_Svincolare', False)
                or '*' in str(p.get('NomeGrezzo', ''))
                or '*' in str(p.get('Giocatore', ''))
            )
            if is_out:
                out_list.append({
                    'Calciatore': p['Giocatore'],
                    'NomeGrezzo': p.get('NomeGrezzo', p['Giocatore']),
                    'Squadra_Lega': team,
                    'Ruolo': p.get('RuoloMantra', 'N/D'),
                    'Costo_Asta': p.get('Costo', 0),
                    'Stato': '🚫 Fuori Serie A (*)',
                    'Consiglio': 'Svincolare al prossimo mercato per recuperare crediti'
                })

    if out_list:
        return pd.DataFrame(out_list)
    return pd.DataFrame(columns=['Calciatore', 'NomeGrezzo', 'Squadra_Lega', 'Ruolo', 'Costo_Asta', 'Stato', 'Consiglio'])


def get_team_roster_df(team_name, league_data_or_master=None, df_master=None):
    """
    Returns a enriched DataFrame for a specific team, incorporating loan status and out-of-Serie A flags.
    Accepts (team_name, df_master), (team_name, league_data, df_master), or (league_data, team_name, df_master).
    """
    if isinstance(team_name, dict) and isinstance(league_data_or_master, str):
        team_name, league_data_or_master = league_data_or_master, team_name

    if df_master is None:
        if isinstance(league_data_or_master, pd.DataFrame):
            df_master = league_data_or_master
            league_data = load_league_rosters()
        else:
            league_data = league_data_or_master if isinstance(league_data_or_master, dict) else load_league_rosters()
            df_master = pd.DataFrame()
    else:
        league_data = league_data_or_master if isinstance(league_data_or_master, dict) else load_league_rosters()

    if not league_data or team_name not in league_data:
        return pd.DataFrame()

    players = league_data[team_name]
    loan_map, _ = build_loan_registry(league_data)

    stats_map = {}
    if df_master is not None and not df_master.empty and 'Giocatore' in df_master.columns:
        stats_map = {str(row['Giocatore']).strip(): row.to_dict() for _, row in df_master.iterrows()}

    try:
        from engine.probable_lineups import load_probable_lineups, get_player_probable_info
        from engine.injuries_manager import get_player_status, load_injuries_data
        inj_c = load_injuries_data()
        prob_c = load_probable_lineups(force_refresh=False)
    except Exception:
        inj_c = {}
        prob_c = {'players': {}}

    rows = []
    for p in players:
        p_name = p['Giocatore']
        cost = p['Costo']
        is_out = bool(
            p.get('FuoriSerieA', False) or 
            p.get('Da_Svincolare', False) or 
            '*' in str(p.get('NomeGrezzo', '')) or 
            '*' in str(p.get('Giocatore', ''))
        )

        m_info = stats_map.get(p_name, {})
        loan_info = loan_map.get((team_name, p_name), None)

        if loan_info:
            stato_prestito = loan_info['Stato_Prestito']
            badge_prestito = loan_info['Badge_Prestito']
            dettaglio_prestito = loan_info['Dettaglio_Prestito']
            schierabile = loan_info['Schierabile'] and not is_out
        else:
            stato_prestito = 'Proprietà'
            badge_prestito = '-'
            dettaglio_prestito = f"Cartellino di proprietà (acquistato per {cost} cr.)"
            schierabile = not is_out

        disp_status = 'Disponibile'
        badge_disp = '✅ DISPONIBILE'
        det_disp = ''
        tit_cat = 'Probabile Titolare'
        if is_out:
            disp_status = 'Fuori Serie A'
            badge_disp = '🚫 DA SVINCOLARE (*)'
            det_disp = 'Fuori dalla Serie A (*) — da svincolare al prossimo mercato'
            tit_cat = 'Non Schierabile'
        elif not schierabile:
            badge_disp = '📤 PRESTITO OUT'
            tit_cat = 'Non Schierabile'
        else:
            try:
                st_i = get_player_status(p_name, inj_c)
                st_v = st_i.get('Stato', 'Disponibile')
                pr_i = get_player_probable_info(p_name, prob_c)
                if st_v == 'Disponibile' and pr_i is not None:
                    if pr_i.get('Fanta_Slot') == 'INFORTUNATO':
                        st_v = 'Infortunato'
                    elif pr_i.get('Fanta_Slot') == 'SQUALIFICATO':
                        st_v = 'Squalificato'
                if st_v == 'Infortunato':
                    disp_status = 'Infortunato'
                    badge_disp = '🚑 INFORTUNATO'
                    det_disp = st_i.get('Dettaglio') or (pr_i.get('Dettaglio_Indisponibile', '') if pr_i else '')
                    schierabile = False
                    tit_cat = 'Non Schierabile'
                elif st_v == 'Squalificato':
                    disp_status = 'Squalificato'
                    badge_disp = '🟥 SQUALIFICATO'
                    det_disp = st_i.get('Dettaglio') or (pr_i.get('Dettaglio_Indisponibile', '') if pr_i else '')
                    schierabile = False
                    tit_cat = 'Non Schierabile'
                else:
                    if pr_i is not None:
                        f_slot_i = pr_i.get('Fanta_Slot', '')
                        f_pct_i = int(pr_i.get('Fanta_Pct', 0))
                        bal_i = pr_i.get('Ballottaggio', '')
                        if f_slot_i == 'TITOLARE':
                            pr_tit = f_pct_i
                            pr_sub = 0
                        else:
                            pr_sub = f_pct_i
                            m_b = re.search(r'(\d{1,3})%\s*vs\s*', bal_i)
                            pr_tit = int(m_b.group(1)) if m_b else 0
                        is_st = bool(f_slot_i == 'TITOLARE' and pr_tit >= 60)
                    else:
                        pres_v = float(m_info.get('Presenze', p.get('Presenze', 0)) or 0)
                        mins_v = float(m_info.get('Minuti_Reali', 0) or 0)
                        is_st = bool(pres_v >= 3 and (mins_v / max(1.0, pres_v)) >= 60.0)
                        pr_tit = 70 if is_st else 0
                        pr_sub = 0 if is_st else 25
                    tit_cat = 'Probabile Titolare' if is_st else 'Probabile Panchinaro'
                    if is_st:
                        badge_disp = f"🟢 PROB. TITOLARE ({pr_tit}%)"
                    else:
                        if pr_tit > 0 and pr_sub > 0:
                            lbl_p = f"Tit. {pr_tit}% · Sub. {pr_sub}%"
                        elif pr_tit > 0:
                            lbl_p = f"Tit. {pr_tit}%"
                        else:
                            lbl_p = f"Sub. {pr_sub}%"
                        badge_disp = f"🪑 PROB. PANCHINARO ({lbl_p})"
            except Exception:
                pass

        row_dict = dict(m_info) if m_info else {}
        row_dict.update({
            'Cod': p.get('Cod', m_info.get('Cod', 0)),
            'Giocatore': p_name,
            'NomeGrezzo': p.get('NomeGrezzo', p_name),
            'Squadra': m_info.get('Squadra', p.get('Squadra', 'Serie A')),
            'RuoloClassic': m_info.get('RuoloClassic', p.get('RuoloClassic', 'C')),
            'RuoloMantra': m_info.get('RuoloMantra', p.get('RuoloMantra', 'C')),
            'Costo': cost,
            'Stato_Prestito': stato_prestito,
            'Badge_Prestito': badge_prestito,
            'Dettaglio_Prestito': dettaglio_prestito,
            'Stato_Disponibilita': disp_status,
            'Badge_Disponibilita': badge_disp,
            'Dettaglio_Disponibilita': det_disp,
            'Categoria_Schierabile': tit_cat,
            'Schierabile': schierabile,
            'Da_Svincolare': is_out,
            'FuoriSerieA': is_out,
            'Presenze': m_info.get('Presenze', p.get('Presenze', 0)),
            'Minuti_Reali': m_info.get('Minuti_Reali', 0),
            'MV_Stagione': m_info.get('MV_Stagione', p.get('MV_Stagione', 0.0)),
            'Pct_Sufficienza': m_info.get('Pct_Sufficienza', 0.0),
            'FM_Stagione': m_info.get('FM_Stagione', p.get('FM_Stagione', 0.0)),
            'MV_Ultime3': m_info.get('MV_Ultime3', 0.0),
            'Pct_Parate': m_info.get('Pct_Parate', 0.0),
            'Goals_Prevented': m_info.get('Goals_Prevented', 0.0),
            'Goals_Prevented_90': m_info.get('Goals_Prevented_90', 0.0),
            'Errors_Leading_To_Goal': m_info.get('Errors_Leading_To_Goal', 0),
            'GF': m_info.get('GF', p.get('GF', 0)),
            'ASS': m_info.get('ASS', p.get('ASS', 0)),
            'Tiri_90': m_info.get('Tiri_90', 0.0),
            'xG_90': m_info.get('xG_90', 0.0),
            'Delta_xG': m_info.get('Delta_xG', 0.0),
            'Key_Passes_90': m_info.get('Key_Passes_90', 0.0),
            'xA_90': m_info.get('xA_90', 0.0),
            'Delta_xA': m_info.get('Delta_xA', 0.0),
            'Signal': m_info.get('Signal', 'NEUTRAL')
        })
        rows.append(row_dict)

    df_res = pd.DataFrame(rows)
    return df_res


def get_league_summary(league_data_or_master=None, df_master=None):
    """Returns a league summary DataFrame comparing all teams (credits, player count, loans, etc.)."""
    if df_master is None:
        if isinstance(league_data_or_master, pd.DataFrame):
            df_master = league_data_or_master
            league_data = load_league_rosters()
        else:
            league_data = league_data_or_master if isinstance(league_data_or_master, dict) else load_league_rosters()
            df_master = pd.DataFrame()
    else:
        league_data = league_data_or_master if isinstance(league_data_or_master, dict) else load_league_rosters()

    if not league_data:
        return pd.DataFrame()

    loan_map, _ = build_loan_registry(league_data)
    summary_rows = []

    for team, players in league_data.items():
        n_players = len(players)
        tot_cost = sum(p.get('Costo', 0) for p in players)
        n_loans_in = sum(1 for p in players if p.get('Costo', 0) == 0)
        n_loans_out = sum(1 for p in players if loan_map.get((team, p['Giocatore']), {}).get('Stato_Prestito') == 'Prestito OUT')
        n_out_serie_a = sum(
            1 for p in players 
            if p.get('FuoriSerieA', False) or p.get('Da_Svincolare', False) or '*' in str(p.get('NomeGrezzo', '')) or '*' in str(p.get('Giocatore', ''))
        )

        summary_rows.append({
            'Squadra': team,
            'Tot_Calciatori': n_players,
            'Crediti_Spesi': tot_cost,
            'Prestiti_IN': n_loans_in,
            'Prestiti_OUT': n_loans_out,
            'Fuori_Serie_A': n_out_serie_a
        })

    return pd.DataFrame(summary_rows)


def render_league_upload_section(key_prefix, df_master, label_title="📥 Carica / Aggiorna File delle Rose (.xlsx, .xls, .csv)"):
    """
    Renders an interactive, foolproof upload and confirmation widget for league rosters.
    Supports updating current league, creating a new named league, or guest session.
    """
    import streamlit as st
    with st.expander(label_title, expanded=False):
        st.markdown("""
        **Formati supportati**: File Excel (`.xlsx`, `.xls`) o CSV (`.csv`) esportato da **Fantacalcio.it**.  
        Supporta sia layout a colonne multiple (squadre affiancate con colonna costo) che layout tabellare ad elenco.  
        Gestisce automaticamente i **prestiti gratuiti (costo 0)** e rileva i **calciatori fuori dalla Serie A (`*`) da svincolare**.
        """)
        
        uploaded_file = st.file_uploader(
            "Trascina o carica il file delle rose (.xlsx, .xls, .csv):",
            type=['xlsx', 'xls', 'csv'],
            key=f"{key_prefix}_league_uploader"
        )
        
        if uploaded_file is not None:
            try:
                parsed_data = parse_official_league_excel(uploaded_file, df_master)
                if parsed_data:
                    tot_teams = len(parsed_data)
                    tot_players = sum(len(p) for p in parsed_data.values())
                    st.success(f"✅ File analizzato con successo! Rilevate **{tot_teams} squadre** e **{tot_players} calciatori**.")
                    
                    teams_found = list(parsed_data.keys())
                    current_active = get_active_my_team()
                    active_lid = get_active_league_id()
                    avail_leagues = get_available_leagues()
                    curr_league_name = avail_leagues.get(active_lid, {}).get('name', active_lid)
                    
                    # Choose default index (prefer 'Bluelock' if present, or current_active)
                    def_idx = 0
                    if 'Bluelock' in teams_found:
                        def_idx = teams_found.index('Bluelock')
                    elif current_active in teams_found:
                        def_idx = teams_found.index(current_active)
                        
                    scope_choice = st.radio(
                        "Destinazione delle rose caricate:",
                        options=[
                            f"💾 Salva e aggiorna la lega attiva: '{curr_league_name}'",
                            "➕ Salva come NUOVA LEGA separata (crea un archivio indipendente)",
                            "👤 Solo per questa mia sessione (ospite temporaneo, non tocca il disco)"
                        ],
                        index=0 if 'custom_league_data' not in st.session_state else 2,
                        key=f"{key_prefix}_scope_choice",
                        help="Puoi aggiornare la lega corrente oppure creare una lega completamente autonoma (es. 'Lega Fantacalcio 2')."
                    )

                    new_lg_custom_name = ""
                    if scope_choice.startswith("➕"):
                        new_lg_custom_name = st.text_input(
                            "Nome della nuova lega da creare:",
                            value=f"Lega {getattr(uploaded_file, 'name', 'Nuova').split('.')[0].replace('_', ' ').title()}",
                            key=f"{key_prefix}_new_league_name_input"
                        )

                    current_ltype = get_league_type()
                    regolamento_choice = st.radio(
                        "Tipo di Regolamento per questa lega:",
                        options=["Mantra (10 moduli tattici, ruoli specifici)", "Classic (P/D/C/A standard, moduli tradizionali)"],
                        index=0 if current_ltype == 'mantra' else 1,
                        horizontal=True,
                        key=f"{key_prefix}_regolamento_choice"
                    )
                    chosen_type = 'classic' if "Classic" in regolamento_choice else 'mantra'

                    sel_col1, sel_col2 = st.columns([1.5, 1])
                    with sel_col1:
                        target_team = st.selectbox(
                            "👉 Seleziona quale di queste squadre è la TUA SQUADRA (La Mia Rosa):",
                            options=teams_found,
                            index=def_idx,
                            key=f"{key_prefix}_select_my_team"
                        )
                    with sel_col2:
                        st.markdown("<br>", unsafe_allow_html=True)
                        apply_btn = st.button(
                            f"🚀 Salva ed Entra (Mia Rosa: {target_team})",
                            type="primary",
                            key=f"{key_prefix}_apply_btn",
                            width='stretch'
                        )

                    # Handle upload save
                    file_sig = f"{getattr(uploaded_file, 'name', '')}_{getattr(uploaded_file, 'size', 0)}_{scope_choice}_{new_lg_custom_name}"
                    saved_sig_key = f"{key_prefix}_saved_file_sig"
                    if apply_btn:
                        fname = getattr(uploaded_file, 'name', 'File_Rose_Lega')
                        if scope_choice.startswith("👤"):
                            st.session_state['custom_league_data'] = parsed_data
                            set_active_my_team(target_team, persist_disk=False)
                            st.session_state['custom_league_meta'] = {
                                'last_updated': datetime.datetime.now().strftime("%d/%m/%Y alle ore %H:%M"),
                                'source': f"Lega Ospite in Sessione ({fname})",
                                'filename': fname
                            }
                            sync_user_roster_from_league(parsed_data, target_team)
                            st.session_state[saved_sig_key] = file_sig
                            st.toast(f"✅ Lega ospite attivata per questa sessione!", icon="🏆")
                            st.rerun()
                        elif scope_choice.startswith("➕"):
                            nl_name = new_lg_custom_name.strip() or "Nuova Lega"
                            ok, new_lid, msg = create_new_league(nl_name, parsed_data, target_team, league_type=chosen_type)
                            if ok:
                                set_active_league_id(new_lid, persist_disk=True)
                                set_active_my_team(target_team, persist_disk=True, league_id=new_lid)
                                sync_user_roster_from_league(parsed_data, target_team, league_id=new_lid)
                                st.session_state[saved_sig_key] = file_sig
                                st.toast(f"🏆 {msg} ({chosen_type.upper()})", icon="🎉")
                                st.success(f"🏆 Nuova lega '{nl_name}' ({chosen_type.upper()}) creata con successo! Squadra attiva: **{target_team}**.")
                                st.rerun()
                            else:
                                st.error(msg)
                        else:
                            save_league_rosters(parsed_data)
                            set_league_type(chosen_type, persist_disk=True)
                            save_league_metadata(source=f"File caricato ({fname})", filename=fname)
                            set_active_my_team(target_team, persist_disk=True)
                            sync_user_roster_from_league(parsed_data, target_team)
                            st.session_state[saved_sig_key] = file_sig
                            st.toast(f"✅ Lega '{curr_league_name}' aggiornata con successo ({chosen_type.upper()})!", icon="🏆")
                            st.rerun()
                        
                    # Preview of the chosen team
                    if target_team in parsed_data:
                        team_pls = parsed_data[target_team]
                        tot_c = sum(p.get('Costo', 0) for p in team_pls)
                        st.markdown(f"**Anteprima Rosa di {target_team}** (`{len(team_pls)} calciatori`, `{tot_c} crediti spesi`):")
                        preview_df = pd.DataFrame([
                            {
                                'Giocatore': p['Giocatore'],
                                'Ruolo': p.get('RuoloMantra', 'C'),
                                'Squadra': p.get('Squadra', ''),
                                'Costo': p.get('Costo', 1),
                                'FM': p.get('FM_Stagione', 0.0),
                                'Stato': '🔄 Prestito' if p.get('InPrestito') else ('⚠️ Svincolo' if p.get('FuoriSerieA') else '✅ Proprietà')
                            }
                            for p in team_pls[:10]
                        ])
                        st.dataframe(preview_df, width='stretch', hide_index=True)
                        if len(team_pls) > 10:
                            st.caption(f"...e altri {len(team_pls) - 10} calciatori.")
            except Exception as e:
                st.error(f"❌ Errore durante l'elaborazione del file: {e}")
                st.info("💡 **Consiglio:** Assicurati di esportare il file direttamente da Fantacalcio.it in formato Excel (.xlsx) o CSV con l'elenco delle rose della tua lega.")
