"""
Multi-Source Probable Lineups Engine (Consenso Fantacalcio.it + Gazzetta dello Sport + Sky Sport).
Scrapes real-time Serie A probable lineups, starting 11s, bench percentages, runoffs (ballottaggi),
and tactical field notes ("Ultime dai campi"), aligning each secondary source with the active matchday
to guarantee zero stale-matchday contamination.
"""

import os
import sys
import re
import html
import json
import datetime
import urllib.request
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.roster_manager import normalize_str, match_player_name

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
LINEUPS_CACHE_FILE = os.path.join(DATA_DIR, "probable_lineups_cache.json")
MASTER_CSV = os.path.join(DATA_DIR, "players_master.csv")

FANTACALCIO_PROB_URL = "https://www.fantacalcio.it/probabili-formazioni-serie-a"
GAZZETTA_PROB_URL = "https://www.gazzetta.it/Calcio/prob_form/"
SKY_PROB_URL = "https://sport.sky.it/calcio/serie-a/probabili-formazioni"

SERIE_A_TEAMS = {
    'Atalanta', 'Bologna', 'Cagliari', 'Como', 'Empoli', 'Fiorentina', 'Frosinone',
    'Genoa', 'Inter', 'Juventus', 'Lazio', 'Lecce', 'Milan', 'Monza', 'Napoli',
    'Parma', 'Roma', 'Sassuolo', 'Torino', 'Udinese', 'Venezia', 'Verona'
}

FORM_RE = re.compile(r'^\d-\d(?:-\d)?(?:-\d)?$')
PCT_RE = re.compile(r'^(\d{1,3})%$')


def _load_master_lookup():
    """Returns (all_names, team_to_names_dict) from players_master.csv."""
    all_names = []
    team_map = {}
    if os.path.exists(MASTER_CSV):
        try:
            df = pd.read_csv(MASTER_CSV)
            for _, row in df.iterrows():
                pname = str(row.get('Giocatore', '')).strip()
                sq = str(row.get('Squadra', '')).strip()
                if pname:
                    all_names.append(pname)
                    team_map.setdefault(sq, []).append(pname)
        except Exception:
            pass
    return all_names, team_map


def match_player_in_team(raw_name, team_name, team_map, all_names):
    """
    Matches a player name from any source (Fantacalcio.it, Gazzetta, Sky)
    preferring exact/partial matches within the specific Serie A team first.
    """
    if not raw_name:
        return None
    clean_raw = re.sub(r'^\d+\s*', '', str(raw_name)).strip()
    clean_raw = re.sub(r'\s*\(.*?\)\s*$', '', clean_raw).strip()
    if not clean_raw or clean_raw.lower() in ('nessuno', 'nessun calciatore', '-'):
        return None

    team_candidates = team_map.get(team_name, [])
    norm_q = normalize_str(clean_raw)
    if not norm_q:
        return None

    # 1. Exact match in team
    for cand in team_candidates:
        if cand == clean_raw or normalize_str(cand) == norm_q:
            return cand

    # 2. Surname / token match in team
    q_tokens = [w for w in norm_q.split() if len(w) > 1]
    best_cand = None
    best_score = 0
    for cand in team_candidates:
        c_norm = normalize_str(cand)
        c_tokens = [w for w in c_norm.split() if len(w) > 1]
        common = set(q_tokens).intersection(set(c_tokens))
        score = 0
        if common:
            score += len(common) * 15
            if c_tokens and c_tokens[0] in q_tokens:
                score += 10
        elif any(len(qt) >= 4 and (qt in c_norm or any(ct.startswith(qt) for ct in c_tokens)) for qt in q_tokens):
            score += 12
        if score > best_score:
            best_score = score
            best_cand = cand

    if best_cand and best_score >= 12:
        return best_cand

    # 3. Global fallback
    if clean_raw in all_names:
        return clean_raw
    global_match = match_player_name(clean_raw, all_names)
    return global_match if global_match else clean_raw


def _fetch_html_lines(url, timeout=10):
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_html = resp.read().decode('utf-8', errors='ignore')
    clean = re.sub(r'<script.*?</script>', '', raw_html, flags=re.DOTALL)
    clean = re.sub(r'<style.*?</style>', '', clean, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '\n', clean)
    return [html.unescape(l.strip()) for l in text.split('\n') if l.strip()]


def scrape_fantacalcio_it(all_names, team_map):
    """
    Scrapes official probable lineups from Fantacalcio.it:
    - Matchday number
    - 20 teams with formation, 11 starters + %, bench + %, runoffs (ballottaggi)
    - Match fixtures (home vs away, kickoff time, last update timestamp)
    """
    lines = _fetch_html_lines(FANTACALCIO_PROB_URL)
    matchday = None
    for l in lines[:220]:
        m = re.match(r'^Giornata\s+(\d+)$', l, re.IGNORECASE)
        if m:
            matchday = int(m.group(1))
            break

    # Locate all 20 team formation headers: lines[i-1] in SERIE_A_TEAMS and FORM_RE.match(lines[i])
    team_headers = []
    for i in range(1, len(lines)):
        if FORM_RE.match(lines[i]) and lines[i - 1] in SERIE_A_TEAMS:
            team_headers.append((i - 1, lines[i - 1], lines[i]))

    teams_data = {}
    matches_list = []

    for idx_pos, (line_idx, team_name, modulo) in enumerate(team_headers):
        next_team_idx = team_headers[idx_pos + 1][0] if idx_pos + 1 < len(team_headers) else len(lines)
        block = lines[line_idx + 2:min(next_team_idx, line_idx + 120)]

        starters = {}
        bench = {}
        in_bench = False
        k = 0
        while k < len(block):
            tok = block[k]
            if tok == 'Panchina':
                in_bench = True
                k += 1
                continue
            if tok in ('Ultimo aggiornamento', 'Presentazione squadre', 'Dettaglio calciatori', 'Ballottaggi') or tok in SERIE_A_TEAMS:
                break
            if k + 1 < len(block):
                m_pct = PCT_RE.match(block[k + 1])
                if m_pct:
                    p_matched = match_player_in_team(tok, team_name, team_map, all_names)
                    pct_val = int(m_pct.group(1))
                    if p_matched:
                        if not in_bench and len(starters) < 11:
                            starters[p_matched] = pct_val
                        else:
                            bench[p_matched] = pct_val
                    k += 2
                    continue
            k += 1

        teams_data[team_name] = {
            'Squadra': team_name,
            'Modulo': modulo,
            'Titolari': starters,
            'Panchina': bench,
            'Ballottaggi': [],
            'Squalificati': [],
            'Diffidati': [],
            'Infortunati': {},
            'In_Dubbio': {},
            'Ultimo_Aggiornamento': '',
            'Avversario': '',
            'Data_Ora': ''
        }

    # Pair teams into 10 matches (0-1, 2-3, ..., 18-19) and parse match-level details (Ballottaggi, timestamp, Indisponibili)
    for pair_idx in range(0, len(team_headers) - 1, 2):
        h_idx, home_team, _ = team_headers[pair_idx]
        a_idx, away_team, _ = team_headers[pair_idx + 1]
        end_match_idx = team_headers[pair_idx + 2][0] if pair_idx + 2 < len(team_headers) else len(lines)

        # Look slightly before h_idx for kickoff date/time & stadium
        kickoff_str = ""
        for back in range(max(0, h_idx - 6), h_idx):
            if any(d in lines[back].lower() for d in ['luned', 'marted', 'mercoled', 'gioved', 'venerd', 'sabato', 'domenica']):
                kickoff_str = lines[back]
                break

        post_block = lines[a_idx:min(end_match_idx, a_idx + 220)]
        last_upd = ""
        ballottaggi_match = []

        def _resolve_match_player(raw_tok):
            mh = match_player_in_team(raw_tok, home_team, team_map, all_names)
            ma = match_player_in_team(raw_tok, away_team, team_map, all_names)
            if mh in team_map.get(home_team, []):
                return home_team, mh
            if ma in team_map.get(away_team, []):
                return away_team, ma
            if mh in teams_data[home_team]['Titolari'] or mh in teams_data[home_team]['Panchina']:
                return home_team, mh
            if ma in teams_data[away_team]['Titolari'] or ma in teams_data[away_team]['Panchina']:
                return away_team, ma
            return home_team, (mh or ma or raw_tok)

        j = 0
        current_sec = None
        while j < len(post_block):
            tok = post_block[j]
            if tok == 'Ultimo aggiornamento' and j + 1 < len(post_block):
                last_upd = post_block[j + 1]
                j += 2
                continue
            if tok == 'Grafico ballottaggio' and j + 4 < len(post_block):
                p1_raw = post_block[j + 1]
                m1 = PCT_RE.match(post_block[j + 2])
                p2_raw = post_block[j + 3]
                m2 = PCT_RE.match(post_block[j + 4])
                if m1 and m2:
                    pct1 = int(m1.group(1))
                    pct2 = int(m2.group(1))
                    t_owner, p1_name = _resolve_match_player(p1_raw)
                    p2_name = match_player_in_team(p2_raw, t_owner, team_map, all_names) or p2_raw
                    b_entry = {
                        'Squadra': t_owner,
                        'Player1': p1_name,
                        'Pct1': pct1,
                        'Player2': p2_name,
                        'Pct2': pct2,
                        'Label': f"{p1_name} {pct1}% - {p2_name} {pct2}%"
                    }
                    ballottaggi_match.append(b_entry)
                    teams_data[t_owner]['Ballottaggi'].append(b_entry)
                j += 5
                continue

            if tok in ('Squalificati', 'Diffidati', 'Infortunati', 'In dubbio'):
                current_sec = tok
                j += 1
                continue

            # Stop parsing unavailable section when next match header starts
            if current_sec and (tok in SERIE_A_TEAMS or re.match(r'^\d+$', tok)):
                break

            if current_sec in ('Squalificati', 'Diffidati'):
                if tok.lower() not in ('nessun calciatore', 'nessuno', '-'):
                    t_owner, p_name = _resolve_match_player(tok)
                    key_sec = 'Squalificati' if current_sec == 'Squalificati' else 'Diffidati'
                    if p_name not in teams_data[t_owner][key_sec]:
                        teams_data[t_owner][key_sec].append(p_name)
                j += 1
                continue

            if current_sec in ('Infortunati', 'In dubbio'):
                if tok.lower() in ('nessun calciatore', 'nessuno', '-'):
                    j += 1
                    continue
                desc = ""
                if j + 1 < len(post_block) and post_block[j + 1] not in ('Squalificati', 'Diffidati', 'Infortunati', 'In dubbio', 'Nessun calciatore') and post_block[j + 1] not in SERIE_A_TEAMS and not re.match(r'^\d+$', post_block[j + 1]):
                    desc = post_block[j + 1]
                    step = 2
                else:
                    step = 1
                t_owner, p_name = _resolve_match_player(tok)
                key_sec = 'Infortunati' if current_sec == 'Infortunati' else 'In_Dubbio'
                teams_data[t_owner][key_sec][p_name] = desc
                j += step
                continue

            j += 1

        teams_data[home_team]['Avversario'] = away_team
        teams_data[away_team]['Avversario'] = home_team
        teams_data[home_team]['Data_Ora'] = kickoff_str
        teams_data[away_team]['Data_Ora'] = kickoff_str
        teams_data[home_team]['Ultimo_Aggiornamento'] = last_upd
        teams_data[away_team]['Ultimo_Aggiornamento'] = last_upd

        matches_list.append({
            'Home': home_team,
            'Away': away_team,
            'Data_Ora': kickoff_str,
            'Ultimo_Aggiornamento': last_upd,
            'Ballottaggi': ballottaggi_match
        })

    return {
        'matchday': matchday,
        'teams': teams_data,
        'matches': matches_list
    }


def scrape_gazzetta(all_names, team_map, expected_opponents=None):
    """
    Scrapes La Gazzetta dello Sport probable lineups:
    - Extracts Home & Away 11 starters, bench, ballottaggi, and tactical field notes ("Ultime dai campi").
    - Validates that the fixture matches expected_opponents (from Fantacalcio.it) so stale matchdays are ignored.
    """
    lines = _fetch_html_lines(GAZZETTA_PROB_URL)
    teams_data = {}

    for i, tok in enumerate(lines):
        if tok == 'DISPOSIZIONE IN CAMPO' and i + 4 < len(lines):
            home_team = lines[i + 1]
            away_team = lines[i + 2]
            if home_team not in SERIE_A_TEAMS or away_team not in SERIE_A_TEAMS:
                continue

            # Check alignment with current matchday fixture
            is_aligned = True
            if expected_opponents and home_team in expected_opponents:
                if expected_opponents[home_team] != away_team:
                    is_aligned = False

            home_note = lines[i + 3] if i + 3 < len(lines) and not lines[i + 3].startswith('Panchina') else ''
            away_note = lines[i + 4] if i + 4 < len(lines) and not lines[i + 4].startswith('Panchina') else ''

            # Look backwards from i (up to 65 lines) to extract the 22 starters (11 home + 11 away)
            # In Gazzetta, between the second 'Allenatore:' + coach name and 'DISPOSIZIONE IN CAMPO',
            # players are listed with their shirt numbers.
            back_slice = lines[max(0, i - 65):i]
            coach_indices = [idx for idx, val in enumerate(back_slice) if val == 'Allenatore:']
            start_scan = (coach_indices[-1] + 2) if coach_indices else 0
            raw_tokens = back_slice[start_scan:]

            # Filter out pure shirt numbers, modules, dates/times
            candidate_names = [
                t for t in raw_tokens
                if not re.match(r'^\d+$', t)
                and not FORM_RE.match(t)
                and not t.startswith('Ore:')
                and t not in ('Modulo:', 'Allenatore:')
                and t not in SERIE_A_TEAMS
            ]

            home_starters = []
            away_starters = []
            if len(candidate_names) >= 22:
                h_raw = candidate_names[:11]
                a_raw = candidate_names[11:22]
            else:
                half = len(candidate_names) // 2
                h_raw = candidate_names[:half]
                a_raw = candidate_names[half:]

            for r_p in h_raw:
                m_p = match_player_in_team(r_p, home_team, team_map, all_names)
                if m_p and m_p not in home_starters:
                    home_starters.append(m_p)
            for r_p in a_raw:
                m_p = match_player_in_team(r_p, away_team, team_map, all_names)
                if m_p and m_p not in away_starters:
                    away_starters.append(m_p)

            # Parse bench & ballottaggi after i
            fwd_slice = lines[i + 3:min(len(lines), i + 35)]
            panchine = []
            ballottaggi = []
            for j, ftok in enumerate(fwd_slice):
                if ftok == 'Panchina:' and j + 1 < len(fwd_slice):
                    panchine.append(fwd_slice[j + 1])
                elif ftok == 'Ballottaggio:' and j + 1 < len(fwd_slice):
                    ballottaggi.append(fwd_slice[j + 1])

            home_bench = []
            away_bench = []
            if len(panchine) >= 1:
                for item in panchine[0].split(','):
                    mp = match_player_in_team(item, home_team, team_map, all_names)
                    if mp:
                        home_bench.append(mp)
            if len(panchine) >= 2:
                for item in panchine[1].split(','):
                    mp = match_player_in_team(item, away_team, team_map, all_names)
                    if mp:
                        away_bench.append(mp)

            teams_data[home_team] = {
                'Squadra': home_team,
                'Avversario': away_team,
                'Allineato_Giornata': is_aligned,
                'Titolari': home_starters,
                'Panchina': home_bench,
                'Nota_Campo': home_note,
                'Ballottaggio_Raw': ballottaggi[0] if len(ballottaggi) >= 1 and ballottaggi[0] != 'Nessuno' else ''
            }
            teams_data[away_team] = {
                'Squadra': away_team,
                'Avversario': home_team,
                'Allineato_Giornata': is_aligned,
                'Titolari': away_starters,
                'Panchina': away_bench,
                'Nota_Campo': away_note,
                'Ballottaggio_Raw': ballottaggi[1] if len(ballottaggi) >= 2 and ballottaggi[1] != 'Nessuno' else ''
            }

    return teams_data


def scrape_sky_sport(all_names, team_map, expected_opponents=None):
    """
    Scrapes Sky Sport probable lineups:
    - Extracts Home & Away 11 starters and bench.
    - Checks whether each match on Sky aligns with expected_opponents for the upcoming matchday.
    """
    lines = _fetch_html_lines(SKY_PROB_URL)
    matchday_sky = None
    for l in lines[:160]:
        m = re.match(r'^Giornata\s+(\d+)$', l, re.IGNORECASE)
        if m:
            matchday_sky = int(m.group(1))
            break

    teams_data = {}
    for i in range(1, len(lines) - 2):
        if lines[i] == 'VS' and lines[i - 1] in SERIE_A_TEAMS and lines[i + 1] in SERIE_A_TEAMS:
            home_team = lines[i - 1]
            away_team = lines[i + 1]

            is_aligned = True
            if expected_opponents and home_team in expected_opponents:
                if expected_opponents[home_team] != away_team:
                    is_aligned = False

            block = lines[i + 2:min(len(lines), i + 75)]
            if 'Titolari' not in block:
                continue
            t_idx = block.index('Titolari')
            r_idx = block.index('Riserve') if 'Riserve' in block else len(block)

            starters_Sub = block[t_idx + 1:r_idx]
            candidate_names = [
                t for t in starters_Sub
                if not re.match(r'^\d+$', t)
                and not FORM_RE.match(t)
                and t not in ('Disposizioni in campo', 'Titolari', 'Riserve')
            ]

            if len(candidate_names) >= 22:
                h_raw = candidate_names[:11]
                a_raw = candidate_names[11:22]
            else:
                half = len(candidate_names) // 2
                h_raw = candidate_names[:half]
                a_raw = candidate_names[half:]

            home_starters = []
            away_starters = []
            for r_p in h_raw:
                mp = match_player_in_team(r_p, home_team, team_map, all_names)
                if mp and mp not in home_starters:
                    home_starters.append(mp)
            for r_p in a_raw:
                mp = match_player_in_team(r_p, away_team, team_map, all_names)
                if mp and mp not in away_starters:
                    away_starters.append(mp)

            home_bench = []
            away_bench = []
            if r_idx + 2 < len(block):
                for item in block[r_idx + 1].split(','):
                    mp = match_player_in_team(item, home_team, team_map, all_names)
                    if mp:
                        home_bench.append(mp)
                for item in block[r_idx + 2].split(','):
                    mp = match_player_in_team(item, away_team, team_map, all_names)
                    if mp:
                        away_bench.append(mp)

            teams_data[home_team] = {
                'Squadra': home_team,
                'Avversario': away_team,
                'Allineato_Giornata': is_aligned,
                'Giornata_Sky': matchday_sky,
                'Titolari': home_starters,
                'Panchina': home_bench
            }
            teams_data[away_team] = {
                'Squadra': away_team,
                'Avversario': home_team,
                'Allineato_Giornata': is_aligned,
                'Giornata_Sky': matchday_sky,
                'Titolari': away_starters,
                'Panchina': away_bench
            }

    return {
        'matchday_sky': matchday_sky,
        'teams': teams_data
    }


def build_consensus_probable_lineups():
    """
    Scrapes Fantacalcio.it, Gazzetta dello Sport, and Sky Sport, aligns them on the
    active Serie A matchday, and builds a unified per-player and per-team consensus dictionary.
    """
    all_names, team_map = _load_master_lookup()

    fanta_res = {'matchday': None, 'teams': {}, 'matches': []}
    try:
        fanta_res = scrape_fantacalcio_it(all_names, team_map)
    except Exception as e:
        print(f"Warning scraping Fantacalcio.it probable lineups: {e}")

    expected_opponents = {
        t: info.get('Avversario', '')
        for t, info in fanta_res.get('teams', {}).items()
    }

    gazzetta_teams = {}
    sky_res = {'matchday_sky': None, 'teams': {}}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_g = pool.submit(scrape_gazzetta, all_names, team_map, expected_opponents)
        fut_s = pool.submit(scrape_sky_sport, all_names, team_map, expected_opponents)
        try:
            gazzetta_teams = fut_g.result(timeout=12)
        except Exception as e:
            print(f"Warning scraping Gazzetta probable lineups: {e}")
        try:
            sky_res = fut_s.result(timeout=12)
        except Exception as e:
            print(f"Warning scraping Sky Sport probable lineups: {e}")

    sky_teams = sky_res.get('teams', {})

    players_consensus = {}
    teams_summary = {}

    for team_name, f_team in fanta_res.get('teams', {}).items():
        g_team = gazzetta_teams.get(team_name, {})
        s_team = sky_teams.get(team_name, {})

        g_aligned = bool(g_team and g_team.get('Allineato_Giornata', False) and g_team.get('Titolari'))
        s_aligned = bool(s_team and s_team.get('Allineato_Giornata', False) and s_team.get('Titolari'))

        active_sources = ['Fantacalcio.it']
        if g_aligned:
            active_sources.append('Gazzetta')
        if s_aligned:
            active_sources.append('Sky')
        total_sources = len(active_sources)

        f_starters = f_team.get('Titolari', {})
        f_bench = f_team.get('Panchina', {})
        f_squal = set(f_team.get('Squalificati', []))
        f_diff = set(f_team.get('Diffidati', []))
        f_inf = f_team.get('Infortunati', {})
        f_dubbio = f_team.get('In_Dubbio', {})
        g_starters = set(g_team.get('Titolari', [])) if g_aligned else set()
        s_starters = set(s_team.get('Titolari', [])) if s_aligned else set()

        # Map player -> ballottaggio strings from Fantacalcio.it
        ballottaggio_by_player = {}
        for b in f_team.get('Ballottaggi', []):
            p1, pct1, p2, pct2 = b['Player1'], b['Pct1'], b['Player2'], b['Pct2']
            ballottaggio_by_player[p1] = f"{p1} {pct1}% vs {p2} {pct2}%"
            ballottaggio_by_player[p2] = f"{p2} {pct2}% vs {p1} {pct1}%"

        nota_campo = g_team.get('Nota_Campo', '') if g_team else ''

        teams_summary[team_name] = {
            'Squadra': team_name,
            'Avversario': f_team.get('Avversario', ''),
            'Data_Ora': f_team.get('Data_Ora', ''),
            'Modulo_Fanta': f_team.get('Modulo', ''),
            'Ultimo_Aggiornamento': f_team.get('Ultimo_Aggiornamento', ''),
            'Fonti_Allineate': active_sources,
            'Tot_Fonti': total_sources,
            'Nota_Campo': nota_campo,
            'Ballottaggi': f_team.get('Ballottaggi', []),
            'Squalificati': list(f_squal),
            'Infortunati': f_inf,
            'In_Dubbio': f_dubbio
        }

        # Evaluate all players of this team
        team_roster_names = (
            set(team_map.get(team_name, []))
            | set(f_starters.keys())
            | set(f_bench.keys())
            | g_starters
            | s_starters
            | f_squal
            | set(f_inf.keys())
            | set(f_dubbio.keys())
        )
        for pname in team_roster_names:
            sources_starting = []
            if pname in f_starters:
                sources_starting.append('Fantacalcio.it')
            if g_aligned and pname in g_starters:
                sources_starting.append('Gazzetta')
            if s_aligned and pname in s_starters:
                sources_starting.append('Sky')

            start_cnt = len(sources_starting)
            inf_desc = f_inf.get(pname, '')
            is_da_valutare = bool(inf_desc and any(kw in inf_desc.lower() for kw in ['da valutare', 'in dubbio', 'convocabile']))

            if pname in f_squal:
                f_pct = 0
                f_slot = 'SQUALIFICATO'
            elif pname in f_inf and not is_da_valutare and pname not in f_starters and pname not in f_bench:
                f_pct = 0
                f_slot = 'INFORTUNATO'
            elif pname in f_starters:
                f_pct = int(f_starters[pname])
                f_slot = 'TITOLARE'
            elif pname in f_bench:
                f_pct = int(f_bench[pname])
                f_slot = 'PANCHINA'
            elif pname in f_inf and is_da_valutare:
                f_pct = 25
                f_slot = 'IN_DUBBIO'
            elif pname in f_dubbio:
                f_pct = 30
                f_slot = 'IN_DUBBIO'
            else:
                # If starter on Gazzetta/Sky but missing from Fanta list
                f_pct = 55 if start_cnt > 0 else 0
                f_slot = 'TITOLARE' if start_cnt > 0 else 'NON_IN_LISTA'

            bal_str = ballottaggio_by_player.get(pname, '')
            if not bal_str and 0 < start_cnt < total_sources:
                missing_src = [s for s in active_sources if s not in sources_starting]
                bal_str = f"Titolare su {', '.join(sources_starting)} (Panchina su {', '.join(missing_src)})"
            if pname in f_dubbio and f_dubbio[pname]:
                bal_str = f"{bal_str} | ⚠️ {f_dubbio[pname]}" if bal_str else f"⚠️ In dubbio: {f_dubbio[pname]}"
            elif is_da_valutare and inf_desc:
                bal_str = f"{bal_str} | ⚠️ {inf_desc}" if bal_str else f"⚠️ Da valutare: {inf_desc}"

            dettaglio_indisp = ""
            if pname in f_squal:
                dettaglio_indisp = "Squalificato per questo turno"
            elif pname in f_inf:
                dettaglio_indisp = f_inf[pname]
            elif pname in f_dubbio:
                dettaglio_indisp = f_dubbio[pname]

            # Compute calibrated Live_P_Voto and Consensus_Status
            consensus_ratio = start_cnt / max(1, total_sources)
            f_prob = f_pct / 100.0

            if f_slot == 'SQUALIFICATO':
                live_p_voto = 0.01
                status_badge = "🔴 SQUALIFICATO (0%)"
                tier_code = "OUT"
            elif f_slot == 'INFORTUNATO':
                live_p_voto = 0.01
                status_badge = "🔴 INFORTUNATO (0%)"
                tier_code = "OUT"
            elif f_slot == 'IN_DUBBIO':
                live_p_voto = 0.25
                status_badge = f"🟠 IN DUBBIO ({start_cnt}/{total_sources} • ~{f_pct}%)"
                tier_code = "IN_DUBBIO"
            elif f_slot == 'NON_IN_LISTA' and start_cnt == 0:
                live_p_voto = 0.02
                status_badge = f"🔴 OUT / TRIBUNA (0/{total_sources})"
                tier_code = "OUT"
            elif start_cnt == total_sources and f_pct >= 70 and not ballottaggio_by_player.get(pname) and pname not in f_dubbio:
                # Unanimous starter across all active sources and high % on Fantacalcio.it
                live_p_voto = min(0.98, max(0.84, 0.55 * f_prob + 0.43 * consensus_ratio))
                status_badge = f"🟢 TITOLARE ({start_cnt}/{total_sources} • {f_pct}%)"
                tier_code = "TITOLARE_CERTO"
            elif start_cnt > 0:
                # In starting 11 on at least 1 source, or in a ballottaggio
                live_p_voto = min(0.90, max(0.55, 0.65 * f_prob + 0.30 * consensus_ratio))
                status_badge = f"🟡 BALLOTTAGGIO ({start_cnt}/{total_sources} • {f_pct}%)"
                tier_code = "BALLOTTAGGIO"
            else:
                # On bench on all sources (0/total_sources)
                if f_pct >= 30:
                    live_p_voto = min(0.68, max(0.25, f_prob * 0.90))
                    status_badge = f"🟠 PANCHINA ({start_cnt}/{total_sources} • Sub. {f_pct}%)"
                    tier_code = "SUBENTRANTE"
                else:
                    live_p_voto = max(0.03, f_prob * 0.75)
                    status_badge = f"⚪ RISERVA ({start_cnt}/{total_sources} • {f_pct}%)"
                    tier_code = "RISERVA"

            players_consensus[pname] = {
                'Giocatore': pname,
                'Squadra': team_name,
                'Avversario': f_team.get('Avversario', ''),
                'Data_Ora': f_team.get('Data_Ora', ''),
                'Fanta_Slot': f_slot,
                'Fanta_Pct': f_pct,
                'Fonti_Titolare': sources_starting,
                'Fonti_Titolare_Count': start_cnt,
                'Fonti_Totali_Count': total_sources,
                'Consenso_Str': f"{start_cnt}/{total_sources}",
                'Ballottaggio': bal_str,
                'Dettaglio_Indisponibile': dettaglio_indisp,
                'Is_Diffidato': pname in f_diff,
                'Live_P_Voto': round(float(live_p_voto), 3),
                'Status_Badge': status_badge,
                'Tier_Code': tier_code,
                'Nota_Campo': nota_campo,
                'Ultimo_Aggiornamento': f_team.get('Ultimo_Aggiornamento', '')
            }

    payload = {
        'last_scraped': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'matchday_fanta': fanta_res.get('matchday'),
        'matchday_sky': sky_res.get('matchday_sky'),
        'teams_summary': teams_summary,
        'players': players_consensus
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LINEUPS_CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return payload


_MEM_CACHE = {'data': None, 'ts': 0.0}


def load_probable_lineups(force_refresh=False, max_age_seconds=1800):
    """
    Loads probable lineups from memory/disk cache, or scrapes live if cache is missing/expired (default 30 min)
    or if force_refresh=True.
    """
    import time
    now = time.time()
    if not force_refresh and _MEM_CACHE['data'] is not None and (now - _MEM_CACHE['ts'] < max_age_seconds):
        return _MEM_CACHE['data']

    if not force_refresh and os.path.exists(LINEUPS_CACHE_FILE):
        try:
            mtime = os.path.getmtime(LINEUPS_CACHE_FILE)
            if (now - mtime) < max_age_seconds:
                with open(LINEUPS_CACHE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and data.get('players'):
                        _MEM_CACHE['data'] = data
                        _MEM_CACHE['ts'] = now
                        return data
        except Exception:
            pass

    try:
        data = build_consensus_probable_lineups()
        _MEM_CACHE['data'] = data
        _MEM_CACHE['ts'] = now
        return data
    except Exception as e:
        print(f"Error refreshing probable lineups: {e}")
        if os.path.exists(LINEUPS_CACHE_FILE):
            try:
                with open(LINEUPS_CACHE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {'players': {}, 'teams_summary': {}, 'matchday_fanta': None}


def get_player_probable_info(player_name, lineups_data=None):
    """Returns probable lineup consensus info for a single player."""
    if lineups_data is None:
        lineups_data = load_probable_lineups(force_refresh=False)
    players_map = lineups_data.get('players', {})
    clean_p = str(player_name).replace('*', '').strip()
    if clean_p in players_map:
        return players_map[clean_p]
    return None


def refresh_live_lineups_and_injuries():
    """
    Concurrently reloads both:
    1) Live multi-source probable lineups (Fantacalcio.it + Gazzetta + Sky Sport)
    2) Live injured, suspended, and booked players (Fantacalcio.it indisponibili)
    """
    from concurrent.futures import ThreadPoolExecutor
    from engine.injuries_manager import fetch_live_injuries_from_fantacalcio

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_prob = pool.submit(load_probable_lineups, True)
        f_inj = pool.submit(fetch_live_injuries_from_fantacalcio)
        try:
            prob_data = f_prob.result(timeout=18)
        except Exception as e:
            print(f"Error reloading probable lineups: {e}")
            prob_data = load_probable_lineups(force_refresh=False)
        try:
            inj_data = f_inj.result(timeout=15)
        except Exception as e:
            print(f"Error reloading injuries: {e}")
            inj_data = {}

    return prob_data, inj_data

