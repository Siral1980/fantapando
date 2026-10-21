"""
Understat Integration Module for Fantacalcio Mantra Manager.
Fetches, caches, and syncs real-world advanced football metrics:
- Expected Goals (xG), Non-Penalty xG (npxG), xG/90
- Expected Assists (xA), xA/90
- Shots/90, Key Passes/90
- xG Chain & xG Buildup
- Delta indicators: Goal vs xG regression (Buy-Low / Sell-High signals)
"""

import os
import json
import gzip
import urllib.request
import pandas as pd
import numpy as np

from engine.roster_manager import match_player_name, normalize_str

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

UNDERSTAT_URL = "https://understat.com/getLeagueData/Serie_A/{season}"

def get_cache_path(season="2026"):
    return os.path.join(DATA_DIR, f"understat_serie_a_{season}.json")

def fetch_understat_serie_a(season="2026", force_refresh=False):
    """
    Downloads Understat data for Serie A season, decompresses gzip, and stores locally.
    Falls back to cached JSON if network request fails.
    """
    cache_file = get_cache_path(season)
    
    if os.path.exists(cache_file) and not force_refresh:
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and "players" in data:
                    return data
        except Exception as e:
            print(f"Warning: Failed reading Understat cache: {e}")

    url = UNDERSTAT_URL.format(season=season)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Encoding": "gzip, deflate",
            "Referer": f"https://understat.com/league/Serie_A/{season}"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read()
            if raw[:2] == b'\x1f\x8b':
                raw = gzip.decompress(raw)
            data = json.loads(raw.decode("utf-8"))
            
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
            return data
    except Exception as e:
        print(f"Network error fetching Understat: {e}")
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

def get_understat_players_df(season="2026"):
    """
    Returns a pandas DataFrame of Understat player metrics with proper numeric conversions.
    """
    data = fetch_understat_serie_a(season=season)
    players = data.get("players", [])
    if not players:
        return pd.DataFrame()
        
    df = pd.DataFrame(players)
    numeric_cols = [
        'games', 'time', 'goals', 'xG', 'assists', 'xA', 
        'shots', 'key_passes', 'yellow_cards', 'red_cards', 
        'npg', 'npxG', 'xGChain', 'xGBuildup'
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
            
    # Calculate per-90 metrics
    p90 = df['time'] / 90.0
    p90_valid = p90 > 0.3 # at least ~30 minutes
    
    df['xG_90'] = np.where(p90_valid, (df['xG'] / p90).round(2), 0.0)
    df['xA_90'] = np.where(p90_valid, (df['xA'] / p90).round(2), 0.0)
    df['npxG_90'] = np.where(p90_valid, (df['npxG'] / p90).round(2), 0.0)
    df['shots_90'] = np.where(p90_valid, (df['shots'] / p90).round(1), 0.0)
    df['key_passes_90'] = np.where(p90_valid, (df['key_passes'] / p90).round(1), 0.0)
    
    return df

UNDERSTAT_TO_FANTACALCIO_TEAM = {
    'AC Milan': 'Milan',
    'Milan': 'Milan',
    'Parma Calcio 1913': 'Parma',
    'Parma': 'Parma',
    'Inter': 'Inter',
    'Juventus': 'Juventus',
    'Roma': 'Roma',
    'Lazio': 'Lazio',
    'Napoli': 'Napoli',
    'Atalanta': 'Atalanta',
    'Fiorentina': 'Fiorentina',
    'Bologna': 'Bologna',
    'Torino': 'Torino',
    'Monza': 'Monza',
    'Udinese': 'Udinese',
    'Cagliari': 'Cagliari',
    'Lecce': 'Lecce',
    'Empoli': 'Empoli',
    'Verona': 'Verona',
    'Como': 'Como',
    'Venezia': 'Venezia',
    'Genoa': 'Genoa',
    'Sassuolo': 'Sassuolo',
    'Frosinone': 'Frosinone'
}

def sync_understat_metrics(df_master, season="2026"):
    """
    Takes the master Fantacalcio player DataFrame and enriches it with real Understat metrics.
    Replaces synthetic regression metrics with real xG, xA, shots, key passes, xGChain.
    Uses team-aware candidate matching to prevent homonym and cross-team collisions
    (e.g. Francesco Pio Esposito at Inter vs Sebastiano Esposito at Sassuolo).
    """
    if df_master.empty:
        return df_master
        
    df_u = get_understat_players_df(season=season)
    if df_u.empty:
        return df_master
        
    master_names = df_master['Giocatore'].tolist()
    # Team-aware lookup
    team_master_names = {}
    master_team_map = {}
    for _, r in df_master.iterrows():
        pname = r['Giocatore']
        squadra = str(r.get('Squadra', '')).strip()
        master_team_map[pname] = squadra
        if squadra not in team_master_names:
            team_master_names[squadra] = []
        team_master_names[squadra].append(pname)
    
    # Pre-index Understat records by matched master name
    matched_data = {}
    for _, u_row in df_u.iterrows():
        p_name = u_row['player_name']
        norm_p = normalize_str(p_name)
        u_team_raw = str(u_row.get('team_title', ''))
        u_teams = [UNDERSTAT_TO_FANTACALCIO_TEAM.get(t.strip(), t.strip()) for t in u_team_raw.split(',') if t.strip()]
        
        target = None
        # 1. Search within the player's team(s) first
        for sq in u_teams:
            candidates = team_master_names.get(sq, [])
            for c in candidates:
                if norm_p == normalize_str(c):
                    target = c
                    break
            if not target and candidates:
                target = match_player_name(p_name, candidates)
            if target:
                break
                
        # 2. Fallback to all master names only if team search yielded nothing
        if not target:
            target = match_player_name(p_name, master_names)
            
        if target:
            # If target already exists in matched_data, resolve conflict:
            # Prefer the Understat record whose team matches the master player's team
            if target in matched_data:
                existing_u = matched_data[target]
                existing_teams = [UNDERSTAT_TO_FANTACALCIO_TEAM.get(t.strip(), t.strip()) for t in str(existing_u.get('team_title', '')).split(',') if t.strip()]
                target_team = master_team_map.get(target, '')
                if target_team in u_teams and target_team not in existing_teams:
                    matched_data[target] = u_row
                elif target_team in existing_teams:
                    pass  # keep existing accurate team match
                elif float(u_row.get('time', 0)) > float(existing_u.get('time', 0)):
                    matched_data[target] = u_row
            else:
                matched_data[target] = u_row
            
    # Update df_master rows
    updated_records = []
    for _, row in df_master.iterrows():
        p_name = row['Giocatore']
        r_dict = row.to_dict()
        
        if p_name in matched_data:
            u_row = matched_data[p_name]
            
            real_time = float(u_row['time'])
            real_xg = round(float(u_row['xG']), 2)
            real_xa = round(float(u_row['xA']), 2)
            real_npxg = round(float(u_row['npxG']), 2)
            real_shots = float(u_row['shots'])
            real_kp = float(u_row['key_passes'])
            real_xg_chain = round(float(u_row['xGChain']), 2)
            real_xg_buildup = round(float(u_row['xGBuildup']), 2)
            
            p90 = max(0.5, real_time / 90.0) if real_time > 0 else 1.0
            
            r_dict['xG_Tot'] = real_xg
            r_dict['xG_90'] = round(real_xg / p90, 2)
            r_dict['npxG_90'] = round(real_npxg / p90, 2)
            r_dict['xA_Tot'] = real_xa
            r_dict['xA_90'] = round(real_xa / p90, 2)
            r_dict['Tiri_90'] = round(real_shots / p90, 1)
            r_dict['Key_Passes_90'] = round(real_kp / p90, 1)
            r_dict['xGChain'] = real_xg_chain
            r_dict['xGBuildup'] = real_xg_buildup
            r_dict['Minuti_Reali'] = int(real_time)
            r_dict['Understat_Matched'] = True
            
            # Recalculate Delta based on Fantacalcio actual goals & assists
            gf = float(r_dict.get('GF', 0.0))
            ass = float(r_dict.get('ASS', 0.0))
            delta_xg = round(gf - real_xg, 2)
            delta_xa = round(ass - real_xa, 2)
            r_dict['Delta_xG'] = delta_xg
            r_dict['Delta_xA'] = delta_xa
            
            # Dynamic signal based on real underlying metrics
            if delta_xg <= -0.75 or (real_xg >= 1.5 and gf == 0):
                r_dict['Signal'] = "BUY-LOW (Sottoperforma xG)"
            elif delta_xg >= 1.40:
                r_dict['Signal'] = "SELL-HIGH (Sovraperforma xG)"
            elif r_dict['xA_90'] >= 0.22 or r_dict['Key_Passes_90'] >= 2.0:
                r_dict['Signal'] = "CREATORE ELITE (High xA)"
            elif r_dict['xG_90'] >= 0.40:
                r_dict['Signal'] = "BOMBER PURO (High xG)"
            else:
                r_dict['Signal'] = "NEUTRO"
        else:
            r_dict['Understat_Matched'] = False
            r_dict['Minuti_Reali'] = int(r_dict.get('Presenze', 0) * 80)
            
        updated_records.append(r_dict)
        
    return pd.DataFrame(updated_records)

_TEAMS_METRICS_CACHE = {}

def get_understat_teams_metrics(season="2026"):
    """
    Returns team-level xG and xGA per match, useful for team strength / difficulty ranking.
    """
    global _TEAMS_METRICS_CACHE
    if season in _TEAMS_METRICS_CACHE:
        return _TEAMS_METRICS_CACHE[season]
        
    data = fetch_understat_serie_a(season=season)
    dates = data.get("dates", [])
    if not dates:
        return {}
        
    team_stats = {}
    for m in dates:
        if not m.get("isResult", False):
            continue
            
        h_title = m["h"]["title"]
        a_title = m["a"]["title"]
        h_xg = float(m["xG"]["h"])
        a_xg = float(m["xG"]["a"])
        
        for t in [h_title, a_title]:
            if t not in team_stats:
                team_stats[t] = {"matches": 0, "xG": 0.0, "xGA": 0.0}
                
        team_stats[h_title]["matches"] += 1
        team_stats[h_title]["xG"] += h_xg
        team_stats[h_title]["xGA"] += a_xg
        
        team_stats[a_title]["matches"] += 1
        team_stats[a_title]["xG"] += a_xg
        team_stats[a_title]["xGA"] += h_xg
        
    # Calculate per-game averages
    results = {}
    team_alias = {
        'AC Milan': 'Milan',
        'Parma Calcio 1913': 'Parma'
    }
    for t, s in team_stats.items():
        n = max(1, s["matches"])
        canonical_name = team_alias.get(t, t)
        results[canonical_name] = {
            "matches": n,
            "xG_per_game": round(s["xG"] / n, 2),
            "xGA_per_game": round(s["xGA"] / n, 2),
            "xG_Diff": round((s["xG"] - s["xGA"]) / n, 2)
        }
    _TEAMS_METRICS_CACHE[season] = results
    return results

def get_team_defensive_xga(team_name, season="2026"):
    """Returns the team's defensive xGA per match, with fallback to 1.40 (league average)."""
    metrics = get_understat_teams_metrics(season)
    if team_name in metrics:
        return float(metrics[team_name].get('xGA_per_game', 1.40))
    norm_t = str(team_name).lower().replace('ac ', '').replace('calcio', '').strip()
    for k, v in metrics.items():
        if norm_t in k.lower():
            return float(v.get('xGA_per_game', 1.40))
    return 1.40
