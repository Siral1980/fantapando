"""
Serie A Calendar, Fixtures, and Dynamic Fixture Difficulty Rating (FDR) Engine.
Computes dynamic difficulty ratings combining the live Serie A standings and 3-year historical pedigree.
"""

import os
import json
import datetime
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CALENDAR_FILE = os.path.join(DATA_DIR, "calendar_serie_a.json")
UNDERSTAT_FILE = os.path.join(DATA_DIR, "understat_serie_a_2026.json")
VOTI_FILE = os.path.join(DATA_DIR, "voti_dettaglio.csv")

# 3-Year Historical Baseline Pedigree (2023/24, 2024/25, 2025/26) normalized on a 0-100 scale
HISTORICAL_3YR_POWER = {
    'Inter': 92.0,
    'Napoli': 86.0,
    'Juventus': 84.0,
    'Atalanta': 83.0,
    'Milan': 81.0,
    'Roma': 76.0,
    'Lazio': 74.0,
    'Fiorentina': 71.0,
    'Bologna': 69.0,
    'Torino': 58.0,
    'Genoa': 54.0,
    'Monza': 48.0,
    'Udinese': 46.0,
    'Sassuolo': 44.0,
    'Cagliari': 44.0,
    'Lecce': 42.0,
    'Como': 41.0,
    'Parma': 40.0,
    'Frosinone': 35.0,
    'Venezia': 32.0
}

TEAMS = list(HISTORICAL_3YR_POWER.keys())

_STANDINGS_CACHE = None
_RATINGS_CACHE = {}

def compute_current_standings(refresh=False):
    """
    Computes current Serie A league table from the actual match records in voti_dettaglio.csv.
    Returns:
      df_standings: DataFrame with columns [Posizione, Squadra, Punti, V, N, P, GF, GS, DR, PPG]
    """
    global _STANDINGS_CACHE
    if _STANDINGS_CACHE is not None and not refresh:
        return _STANDINGS_CACHE

    # 1. Prefer live Understat data if available (covers all matchdays through 9+)
    if os.path.exists(UNDERSTAT_FILE):
        try:
            with open(UNDERSTAT_FILE, 'r', encoding='utf-8') as f_u:
                u_data = json.load(f_u)
            u_teams = u_data.get('teams', {})
            if u_teams:
                from engine.understat_loader import UNDERSTAT_TO_FANTACALCIO_TEAM
                standings = []
                for tid, tdata in u_teams.items():
                    raw_title = tdata.get('title', '')
                    sq_name = UNDERSTAT_TO_FANTACALCIO_TEAM.get(raw_title, raw_title)
                    hist = tdata.get('history', [])
                    pts = sum(h.get('pts', 0) for h in hist)
                    gf = sum(h.get('scored', 0) for h in hist)
                    ga = sum(h.get('missed', 0) for h in hist)
                    w = sum(h.get('wins', 0) for h in hist)
                    d = sum(h.get('draws', 0) for h in hist)
                    l = sum(h.get('loses', 0) for h in hist)
                    standings.append({
                        'Squadra': sq_name,
                        'Partite': len(hist),
                        'Punti': pts,
                        'V': w,
                        'N': d,
                        'P': l,
                        'GF': gf,
                        'GS': ga,
                        'DR': gf - ga,
                        'PPG': round(pts / max(1, len(hist)), 2)
                    })
                df_stand = pd.DataFrame(standings).sort_values(by=['Punti', 'DR', 'GF'], ascending=False).reset_index(drop=True)
                df_stand.index += 1
                df_stand['Posizione'] = df_stand.index
                _STANDINGS_CACHE = df_stand
                return df_stand
        except Exception as e:
            print(f"Understat standings calculation notice: {e}")

    if not os.path.exists(VOTI_FILE):
        rows = [{'Squadra': t, 'Punti': 5, 'V': 1, 'N': 2, 'P': 2, 'GF': 5, 'GS': 5, 'DR': 0, 'Partite': 5} for t in TEAMS]
        df_fb = pd.DataFrame(rows)
        df_fb['PPG'] = 1.0
        df_fb['Posizione'] = range(1, len(df_fb) + 1)
        _STANDINGS_CACHE = df_fb
        return df_fb

    df_v = pd.read_csv(VOTI_FILE)
    standings = {}
    for sq in TEAMS:
        standings[sq] = {'Punti': 0, 'V': 0, 'N': 0, 'P': 0, 'GF': 0, 'GS': 0, 'Partite': 0}

    for g in sorted(df_v['Giornata'].unique()):
        df_g = df_v[df_v['Giornata'] == g]
        for sq in TEAMS:
            sub = df_g[df_g['Squadra'] == sq]
            if sub.empty:
                continue
            gf = sub['GF'].sum()
            gs_sub = sub[sub['RuoloClassic'] == 'P']['GS']
            gs = gs_sub.max() if not gs_sub.empty else 0
            
            standings[sq]['GF'] += int(gf)
            standings[sq]['GS'] += int(gs)
            standings[sq]['Partite'] += 1
            
            if gf > gs:
                standings[sq]['Punti'] += 3
                standings[sq]['V'] += 1
            elif gf == gs:
                standings[sq]['Punti'] += 1
                standings[sq]['N'] += 1
            else:
                standings[sq]['P'] += 1

    df_stand = pd.DataFrame.from_dict(standings, orient='index')
    df_stand['DR'] = df_stand['GF'] - df_stand['GS']
    df_stand = df_stand.sort_values(by=['Punti', 'DR', 'GF'], ascending=False).reset_index()
    df_stand.rename(columns={'index': 'Squadra'}, inplace=True)
    df_stand.index += 1
    df_stand['Posizione'] = df_stand.index
    df_stand['PPG'] = round(df_stand['Punti'] / df_stand['Partite'].clip(lower=1), 2)
    _STANDINGS_CACHE = df_stand
    return df_stand

def compute_dynamic_team_ratings(matchday=6, refresh=False):
    """
    Computes dynamic power ratings (0-100) blending:
      1. Live Current Serie A Standings (PPG, Goal Difference)
      2. 3-Year Historical Standings Pedigree
    The weight dynamically evolves with matchdays played.
    """
    global _RATINGS_CACHE
    if matchday in _RATINGS_CACHE and not refresh:
        return _RATINGS_CACHE[matchday]

    df_standings = compute_current_standings(refresh=refresh)
    
    # Dynamic blending weight based on matchdays played
    # Early matchdays: 3-year history has high weight
    # Later matchdays: current season performance dominates
    w_current = min(0.75, max(0.20, 0.18 + (0.025 * matchday)))
    w_historical = 1.0 - w_current
    
    ratings = {}
    rating_rows = []
    
    for _, row in df_standings.iterrows():
        sq = row['Squadra']
        ppg = float(row['PPG'])
        part = max(1, int(row['Partite']))
        drpg = float(row['DR']) / part
        
        # Current season power formula (scaled 15 to 95)
        # 1.35 PPG is league average
        score_curr = 50.0 + (22.0 * (ppg - 1.35)) + (8.5 * drpg)
        score_curr = max(15.0, min(95.0, score_curr))
        
        score_hist = HISTORICAL_3YR_POWER.get(sq, 50.0)
        
        dynamic_score = (w_current * score_curr) + (w_historical * score_hist)
        dynamic_score = round(max(10.0, min(98.0, dynamic_score)), 1)
        
        ratings[sq] = {
            'Squadra': sq,
            'Power_Dinamico': dynamic_score,
            'Power_Attuale': round(score_curr, 1),
            'Power_Triennio': score_hist,
            'Punti_Attuali': int(row['Punti']),
            'Posizione_Attuale': int(row['Posizione']),
            'DR_Attuale': int(row['DR']),
            'w_current': round(w_current * 100, 1),
            'w_historical': round(w_historical * 100, 1)
        }
        rating_rows.append(ratings[sq])
        
    df_ratings = pd.DataFrame(rating_rows).sort_values(by='Power_Dinamico', ascending=False)
    _RATINGS_CACHE[matchday] = (ratings, df_ratings)
    return ratings, df_ratings

def generate_round_robin_schedule(teams=TEAMS):
    """Generates a full 38-round double round-robin tournament schedule."""
    n = len(teams)
    temp_teams = list(teams)
    rounds = []
    
    for r in range(n - 1):
        round_matches = []
        for i in range(n // 2):
            t1 = temp_teams[i]
            t2 = temp_teams[n - 1 - i]
            if (r + i) % 2 == 0:
                round_matches.append({'home': t1, 'away': t2})
            else:
                round_matches.append({'home': t2, 'away': t1})
        rounds.append(round_matches)
        temp_teams = [temp_teams[0]] + [temp_teams[-1]] + temp_teams[1:-1]
        
    return_rounds = []
    for r in rounds:
        rev_round = [{'home': m['away'], 'away': m['home']} for m in r]
        return_rounds.append(rev_round)
        
    all_38_rounds = rounds + return_rounds
    
    calendar_dict = {}
    for idx, r_matches in enumerate(all_38_rounds):
        giornata_num = idx + 1
        calendar_dict[giornata_num] = r_matches
        
    return calendar_dict

def build_calendar_from_understat():
    """Builds the authentic 38-matchday Serie A calendar from understat_serie_a_2026.json."""
    if not os.path.exists(UNDERSTAT_FILE):
        return None
    try:
        with open(UNDERSTAT_FILE, 'r', encoding='utf-8') as f:
            d = json.load(f)
        dates = d.get('dates', [])
        if len(dates) < 380:
            return None
        team_map = {'AC Milan': 'Milan', 'Parma Calcio 1913': 'Parma'}
        cal = {}
        for g in range(1, 39):
            chunk = dates[(g - 1) * 10 : g * 10]
            cal[g] = [
                {
                    'home': team_map.get(m['h']['title'], m['h']['title']),
                    'away': team_map.get(m['a']['title'], m['a']['title']),
                    'datetime': m.get('datetime', '')
                }
                for m in chunk
            ]
        return cal
    except Exception:
        return None

def get_or_create_calendar(force_refresh=False):
    """Loads existing calendar or generates a full 38-matchday Serie A calendar, auto-refreshing if understat file is newer."""
    understat_newer = (
        os.path.exists(UNDERSTAT_FILE)
        and os.path.exists(CALENDAR_FILE)
        and os.path.getmtime(UNDERSTAT_FILE) > os.path.getmtime(CALENDAR_FILE)
    )
    if not force_refresh and not understat_newer and os.path.exists(CALENDAR_FILE):
        try:
            with open(CALENDAR_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                cal = {int(k): v for k, v in data.items()}
                # Quick verification that calendar matches authentic schedule (e.g. G8 has Inter vs Fiorentina)
                if 8 in cal and any(m.get('home') == 'Inter' and m.get('away') == 'Fiorentina' for m in cal[8]):
                    return cal
        except Exception:
            pass

    calendar = build_calendar_from_understat()
    if calendar is None:
        calendar = generate_round_robin_schedule()

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CALENDAR_FILE, 'w', encoding='utf-8') as f:
        json.dump(calendar, f, indent=2)
    return calendar

def calculate_dynamic_fdr(squadra, avversario, is_home, matchday=6, ratings_cache=None):
    """
    Calculates the Dynamic Fixture Difficulty Rating (1 to 5) for a match.
    Centered on FDR 3 (Neutral) when two teams are of equal strength, driven primarily
    by the relative power rating gap (delta) between the opponent and the team,
    modulated by opponent quality tier and home/away factor.
    """
    if ratings_cache is None:
        ratings_cache, _ = compute_dynamic_team_ratings(matchday)
        
    p_squadra = ratings_cache.get(squadra, {}).get('Power_Dinamico', 50.0)
    p_avv = ratings_cache.get(avversario, {}).get('Power_Dinamico', 50.0)
    
    # 1. Relative rating gap: difference between opponent and team
    # Range is approx -65 (Inter vs Venezia) to +65 (Venezia vs Inter)
    # Normalized by 22.0: range -3.0 to +3.0
    gap = (p_avv - p_squadra) / 22.0
    
    # 2. Opponent tier nuance: absolute strength relative to league average (50.0)
    # Range is approx -25 to +40, normalized by 25.0: range -1.0 to +1.6
    opp_tier = (p_avv - 50.0) / 25.0
    
    # 3. Location factor: Home vs Away
    # Playing at home lowers difficulty (-0.40); playing away raises it (+0.40)
    loc_factor = -0.40 if is_home else +0.40
    
    # Continuous score centered on 3.0 (Neutral parity match)
    # 75% weight on relative differential gap, 25% weight on opponent tier
    raw_score = 3.0 + (0.75 * gap) + (0.25 * opp_tier) + loc_factor
    
    # Convert to discrete FDR from 1 to 5
    fdr = int(round(raw_score))
    return max(1, min(5, fdr))

def get_fixture_info(squadra, giornata, calendar=None, ratings_cache=None):
    """
    Returns matchup detail for a team at a specific matchday using dynamic FDR.
    """
    if calendar is None:
        calendar = get_or_create_calendar()
    if ratings_cache is None:
        ratings_cache, _ = compute_dynamic_team_ratings(giornata)
        
    matches = calendar.get(giornata, [])
    for m in matches:
        if m['home'] == squadra:
            opp = m['away']
            is_home = True
            fdr = calculate_dynamic_fdr(squadra, opp, is_home=True, matchday=giornata, ratings_cache=ratings_cache)
            opp_pow = ratings_cache.get(opp, {}).get('Power_Dinamico', 50.0)
            
            # Dynamic expected conceded xGA and attack strength
            xga = max(0.65, min(2.10, 1.80 - (opp_pow / 75.0)))
            att = max(0.70, min(2.30, 0.70 + (opp_pow / 65.0)))
            
            return {
                'Giornata': giornata,
                'Squadra': squadra,
                'Avversario': opp,
                'IsHome': True,
                'Location': 'CASA',
                'Label': f"{opp} (C)",
                'FDR': fdr,
                'Opp_xGA': round(xga * 0.90, 2),
                'Opp_xG_Attack': round(att * 0.88, 2)
            }
        elif m['away'] == squadra:
            opp = m['home']
            is_home = False
            fdr = calculate_dynamic_fdr(squadra, opp, is_home=False, matchday=giornata, ratings_cache=ratings_cache)
            opp_pow = ratings_cache.get(opp, {}).get('Power_Dinamico', 50.0)
            
            xga = max(0.65, min(2.10, 1.80 - (opp_pow / 75.0)))
            att = max(0.70, min(2.30, 0.70 + (opp_pow / 65.0)))
            
            return {
                'Giornata': giornata,
                'Squadra': squadra,
                'Avversario': opp,
                'IsHome': False,
                'Location': 'TRASFERTA',
                'Label': f"{opp} (T)",
                'FDR': fdr,
                'Opp_xGA': round(xga * 1.15, 2),
                'Opp_xG_Attack': round(att * 1.15, 2)
            }
            
    # Default fallback
    return {
        'Giornata': giornata,
        'Squadra': squadra,
        'Avversario': 'Riposo',
        'IsHome': True,
        'Location': 'CASA',
        'Label': 'N/D',
        'FDR': 3,
        'Opp_xGA': 1.3,
        'Opp_xG_Attack': 1.3
    }

def get_schedule_matrix(start_giornata=6, end_giornata=15, calendar=None):
    """Generates a dynamic FDR schedule matrix for all 20 teams across upcoming matchdays."""
    if calendar is None:
        calendar = get_or_create_calendar()
        
    ratings_cache, _ = compute_dynamic_team_ratings(start_giornata)
    
    rows = []
    for team in sorted(TEAMS):
        team_info = ratings_cache.get(team, {})
        row = {
            'Squadra': team,
            'Power_Dinamico': team_info.get('Power_Dinamico', 50.0),
            'Posizione_Attuale': team_info.get('Posizione_Attuale', 10)
        }
        fdr_list = []
        for g in range(start_giornata, end_giornata + 1):
            info = get_fixture_info(team, g, calendar, ratings_cache)
            row[f"G{g}"] = f"{info['Label']} [{info['FDR']}]"
            fdr_list.append(info['FDR'])
        row['FDR_Medio'] = round(sum(fdr_list) / len(fdr_list), 2) if fdr_list else 3.0
        rows.append(row)
        
    df = pd.DataFrame(rows).sort_values(by='FDR_Medio')
    return df

# Official Serie A Matchday Schedule (38 Rounds)
SERIE_A_SCHEDULE = {
    1:  {'start_m': 8, 'start_d': 22, 'end_m': 8, 'end_d': 24, 'desc': '1ª Giornata (22-24 Ago)'},
    2:  {'start_m': 8, 'start_d': 29, 'end_m': 8, 'end_d': 31, 'desc': '2ª Giornata (29-31 Ago)'},
    3:  {'start_m': 9, 'start_d': 5,  'end_m': 9, 'end_d': 7,  'desc': '3ª Giornata (5-7 Set)'},
    4:  {'start_m': 9, 'start_d': 19, 'end_m': 9, 'end_d': 21, 'desc': '4ª Giornata (19-21 Set)'},
    5:  {'start_m': 9, 'start_d': 26, 'end_m': 9, 'end_d': 28, 'desc': '5ª Giornata (26-28 Set)'},
    6:  {'start_m': 10, 'start_d': 3, 'end_m': 10, 'end_d': 5, 'desc': '6ª Giornata (3-5 Ott)'},
    7:  {'start_m': 10, 'start_d': 17, 'end_m': 10, 'end_d': 19, 'desc': '7ª Giornata (17-19 Ott)'},
    8:  {'start_m': 10, 'start_d': 24, 'end_m': 10, 'end_d': 26, 'desc': '8ª Giornata (24-26 Ott)'},
    9:  {'start_m': 10, 'start_d': 28, 'end_m': 10, 'end_d': 29, 'desc': '9ª Giornata - Infrasettimanale (28-29 Ott)'},
    10: {'start_m': 10, 'start_d': 31, 'end_m': 11, 'end_d': 2,  'desc': '10ª Giornata (31 Ott - 2 Nov)'},
    11: {'start_m': 11, 'start_d': 7,  'end_m': 11, 'end_d': 9,  'desc': '11ª Giornata (7-9 Nov)'},
    12: {'start_m': 11, 'start_d': 21, 'end_m': 11, 'end_d': 23, 'desc': '12ª Giornata (21-23 Nov)'},
    13: {'start_m': 11, 'start_d': 28, 'end_m': 11, 'end_d': 30, 'desc': '13ª Giornata (28-30 Nov)'},
    14: {'start_m': 12, 'start_d': 5,  'end_m': 12, 'end_d': 7,  'desc': '14ª Giornata (5-7 Dic)'},
    15: {'start_m': 12, 'start_d': 12, 'end_m': 12, 'end_d': 14, 'desc': '15ª Giornata (12-14 Dic)'},
    16: {'start_m': 12, 'start_d': 19, 'end_m': 12, 'end_d': 21, 'desc': '16ª Giornata (19-21 Dic)'},
    17: {'start_m': 12, 'start_d': 26, 'end_m': 12, 'end_d': 28, 'desc': '17ª Giornata (26-28 Dic)'},
    18: {'start_m': 1,  'start_d': 2,  'end_m': 1,  'end_d': 4,  'desc': '18ª Giornata (2-4 Gen)'},
    19: {'start_m': 1,  'start_d': 6,  'end_m': 1,  'end_d': 7,  'desc': '19ª Giornata - Epifania (6-7 Gen)'},
    20: {'start_m': 1,  'start_d': 9,  'end_m': 1,  'end_d': 11, 'desc': '20ª Giornata (9-11 Gen)'},
    21: {'start_m': 1,  'start_d': 16, 'end_m': 1,  'end_d': 18, 'desc': '21ª Giornata (16-18 Gen)'},
    22: {'start_m': 1,  'start_d': 23, 'end_m': 1,  'end_d': 25, 'desc': '22ª Giornata (23-25 Gen)'},
    23: {'start_m': 1,  'start_d': 30, 'end_m': 2,  'end_d': 1,  'desc': '23ª Giornata (30 Gen - 1 Feb)'},
    24: {'start_m': 2,  'start_d': 6,  'end_m': 2,  'end_d': 8,  'desc': '24ª Giornata (6-8 Feb)'},
    25: {'start_m': 2,  'start_d': 13, 'end_m': 2,  'end_d': 15, 'desc': '25ª Giornata (13-15 Feb)'},
    26: {'start_m': 2,  'start_d': 20, 'end_m': 2,  'end_d': 22, 'desc': '26ª Giornata (20-22 Feb)'},
    27: {'start_m': 2,  'start_d': 27, 'end_m': 3,  'end_d': 1,  'desc': '27ª Giornata (27 Feb - 1 Mar)'},
    28: {'start_m': 3,  'start_d': 6,  'end_m': 3,  'end_d': 8,  'desc': '28ª Giornata (6-8 Mar)'},
    29: {'start_m': 3,  'start_d': 13, 'end_m': 3,  'end_d': 15, 'desc': '29ª Giornata (13-15 Mar)'},
    30: {'start_m': 3,  'start_d': 20, 'end_m': 3,  'end_d': 22, 'desc': '30ª Giornata (20-22 Mar)'},
    31: {'start_m': 4,  'start_d': 3,  'end_m': 4,  'end_d': 5,  'desc': '31ª Giornata (3-5 Apr)'},
    32: {'start_m': 4,  'start_d': 10, 'end_m': 4,  'end_d': 12, 'desc': '32ª Giornata (10-12 Apr)'},
    33: {'start_m': 4,  'start_d': 17, 'end_m': 4,  'end_d': 19, 'desc': '33ª Giornata (17-19 Apr)'},
    34: {'start_m': 4,  'start_d': 24, 'end_m': 4,  'end_d': 26, 'desc': '34ª Giornata (24-26 Apr)'},
    35: {'start_m': 5,  'start_d': 1,  'end_m': 5,  'end_d': 3,  'desc': '35ª Giornata (1-3 Mag)'},
    36: {'start_m': 5,  'start_d': 8,  'end_m': 5,  'end_d': 10, 'desc': '36ª Giornata (8-10 Mag)'},
    37: {'start_m': 5,  'start_d': 15, 'end_m': 5,  'end_d': 17, 'desc': '37ª Giornata (15-17 Mag)'},
    38: {'start_m': 5,  'start_d': 22, 'end_m': 5,  'end_d': 24, 'desc': '38ª Giornata (22-24 Mag)'}
}

_ITALIAN_MONTHS_SHORT = {
    1: 'Gen', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'Mag', 6: 'Giu',
    7: 'Lug', 8: 'Ago', 9: 'Set', 10: 'Ott', 11: 'Nov', 12: 'Dic'
}

def build_dynamic_serie_a_schedule():
    """
    Builds the 38-round Serie A schedule dynamically from the real match timestamps in calendar_serie_a.json.
    """
    schedule = {}
    try:
        cal = get_or_create_calendar()
    except Exception:
        cal = {}

    for g in range(1, 39):
        matches = cal.get(g, []) if isinstance(cal, dict) else []
        parsed_dts = []
        for m in matches:
            dt_str = m.get('datetime', '')
            if dt_str:
                try:
                    parsed_dts.append(datetime.datetime.strptime(dt_str[:19], '%Y-%m-%d %H:%M:%S'))
                except Exception:
                    pass

        if parsed_dts:
            min_dt = min(parsed_dts)
            max_dt = max(parsed_dts)
            if min_dt.date() == max_dt.date() and min_dt.weekday() == 6:
                start_date = min_dt.date() - datetime.timedelta(days=1)
                end_date = max_dt.date()
            else:
                start_date = min_dt.date()
                end_date = max_dt.date()

            s_m, s_d, s_y = start_date.month, start_date.day, start_date.year
            e_m, e_d, e_y = end_date.month, end_date.day, end_date.year

            if s_m == e_m:
                if s_d == e_d:
                    date_label = f"{s_d} {_ITALIAN_MONTHS_SHORT[s_m]}"
                else:
                    date_label = f"{s_d}-{e_d} {_ITALIAN_MONTHS_SHORT[e_m]}"
            else:
                date_label = f"{s_d} {_ITALIAN_MONTHS_SHORT[s_m]} - {e_d} {_ITALIAN_MONTHS_SHORT[e_m]}"

            schedule[g] = {
                'start_y': s_y, 'start_m': s_m, 'start_d': s_d,
                'end_y': e_y, 'end_m': e_m, 'end_d': e_d,
                'first_kickoff': min_dt,
                'last_kickoff': max_dt,
                'desc': f"{g}ª Giornata ({date_label})"
            }
        else:
            schedule[g] = dict(SERIE_A_SCHEDULE[g])

    return schedule

SERIE_A_SCHEDULE = build_dynamic_serie_a_schedule()

def get_matchday_from_date(dt=None):
    """
    Determines the current/upcoming Serie A matchday automatically based on the official calendar and today's date.
    Returns:
      giornata (int): 1..38
      info (dict): {
          'giornata': int,
          'start_date': str,
          'end_date': str,
          'label': str,
          'status': 'upcoming' | 'live' | 'completed',
          'desc': str
      }
    """
    if dt is None:
        dt = datetime.datetime.now()
    if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
        dt = datetime.datetime(dt.year, dt.month, dt.day, 12, 0)
        
    base_year = dt.year if dt.month >= 7 else dt.year - 1
    schedule = build_dynamic_serie_a_schedule()

    for g in range(1, 39):
        info = schedule[g]
        s_m, s_d = info['start_m'], info['start_d']
        e_m, e_d = info['end_m'], info['end_d']
        s_y = info.get('start_y', base_year if s_m >= 7 else base_year + 1)
        e_y = info.get('end_y', base_year if e_m >= 7 else base_year + 1)

        start_dt = datetime.datetime(s_y, s_m, s_d, 0, 0, 0)
        end_dt = datetime.datetime(e_y, e_m, e_d, 23, 59, 59)

        if dt <= end_dt:
            status = 'live' if dt >= start_dt else 'upcoming'
            return g, {
                'giornata': g,
                'start_date': start_dt.strftime('%Y-%m-%d'),
                'end_date': end_dt.strftime('%Y-%m-%d'),
                'label': f"{g}ª Giornata ({start_dt.strftime('%d/%m')} - {end_dt.strftime('%d/%m')})",
                'status': status,
                'desc': info['desc']
            }
            
    return 38, {
        'giornata': 38,
        'start_date': f"{base_year+1}-05-22",
        'end_date': f"{base_year+1}-05-24",
        'label': '38ª Giornata (Fine Campionato)',
        'status': 'completed',
        'desc': '38ª Giornata'
    }

# Backwards compatibility alias
TEAM_TIERS = {t: 1 if HISTORICAL_3YR_POWER[t] >= 75 else (2 if HISTORICAL_3YR_POWER[t] >= 50 else 3) for t in TEAMS}
calculate_fdr = calculate_dynamic_fdr

if __name__ == '__main__':
    print("Testing dynamic ratings and FDR:")
    ratings, df_r = compute_dynamic_team_ratings(6)
    print("\nTop 5 Team Dynamic Ratings (G6):\n", df_r[['Squadra', 'Posizione_Attuale', 'Punti_Attuali', 'Power_Attuale', 'Power_Triennio', 'Power_Dinamico']].head())
    
    matrix = get_schedule_matrix(6, 10)
    print("\nSchedule Matrix Top 5:\n", matrix[['Squadra', 'Power_Dinamico', 'FDR_Medio', 'G6', 'G7']].head())
