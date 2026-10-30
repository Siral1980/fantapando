"""
Injuries and Suspensions Manager for Fantacalcio Mantra.
Fetches official live injured/suspended players from Fantacalcio.it
and supports local manual overrides and custom player availability statuses.
"""

import os
import sys
import re
import html
import json
import urllib.request
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.roster_manager import match_player_name

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
INJURIES_FILE = os.path.join(DATA_DIR, "injuries_and_suspensions.json")
MASTER_CSV = os.path.join(DATA_DIR, "players_master.csv")

FANTACALCIO_INDISPONIBILI_URL = "https://www.fantacalcio.it/indisponibili-serie-a"

SERIE_A_TEAMS = [
    'Atalanta', 'Bologna', 'Cagliari', 'Como', 'Empoli', 'Fiorentina', 'Genoa',
    'Inter', 'Juventus', 'Lazio', 'Lecce', 'Milan', 'Monza', 'Napoli', 'Parma',
    'Roma', 'Sassuolo', 'Torino', 'Udinese', 'Venezia', 'Verona', 'Frosinone'
]


def load_injuries_data():
    """Loads current injuries and suspensions cache."""
    if os.path.exists(INJURIES_FILE):
        try:
            with open(INJURIES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            print(f"Error loading injuries cache: {e}")
    return {'auto': {}, 'manual_overrides': {}, 'last_updated': None}


def save_injuries_data(data):
    """Saves injuries and suspensions cache."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(INJURIES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return data


def fetch_live_injuries_from_fantacalcio():
    """
    Scrapes and parses official real-time injured, suspended, and booked players
    directly from Fantacalcio.it.
    Returns:
      parsed_dict: { 'Giocatore': {'Stato': 'Infortunato'|'Squalificato'|'Diffidato', 'Squadra': ..., 'Dettaglio': ...} }
    """
    master_names = []
    if os.path.exists(MASTER_CSV):
        try:
            df_m = pd.read_csv(MASTER_CSV)
            master_names = df_m['Giocatore'].dropna().tolist()
        except Exception:
            pass

    req = urllib.request.Request(
        FANTACALCIO_INDISPONIBILI_URL,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw_html = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Failed to fetch {FANTACALCIO_INDISPONIBILI_URL}: {e}")
        # Return existing cached auto data if network fails
        existing = load_injuries_data()
        return existing.get('auto', {})

    clean = re.sub(r'<script.*?</script>', '', raw_html, flags=re.DOTALL)
    clean = re.sub(r'<style.*?</style>', '', clean, flags=re.DOTALL)
    clean_text = re.sub(r'<[^>]+>', '\n', clean)
    lines = [html.unescape(l.strip()) for l in clean_text.split('\n') if l.strip()]

    team_indices = []
    for i, l in enumerate(lines):
        if l in SERIE_A_TEAMS and (i + 1 < len(lines) and lines[i + 1] in ['Infortunati', 'Squalificati']):
            team_indices.append((i, l))

    auto_dict = {}

    for k in range(len(team_indices)):
        start_idx, team = team_indices[k]
        end_idx = team_indices[k + 1][0] if k + 1 < len(team_indices) else start_idx + 80
        sec = None
        sublines = lines[start_idx + 1:end_idx]
        idx = 0

        while idx < len(sublines):
            line = sublines[idx]
            if line in ['Infortunati', 'Squalificati', 'Diffidati']:
                sec = line
                idx += 1
                continue
            if line == 'Nessuno':
                idx += 1
                continue

            if sec == 'Infortunati':
                player_raw = line
                desc = sublines[idx + 1] if idx + 1 < len(sublines) and sublines[idx + 1] not in ['Infortunati', 'Squalificati', 'Diffidati'] else ''
                
                # Clean and match player name
                m_target = player_raw if player_raw in master_names else match_player_name(player_raw, master_names)
                official_name = m_target if m_target else player_raw

                auto_dict[official_name] = {
                    'Giocatore': official_name,
                    'NomeOriginale': player_raw,
                    'Squadra': team,
                    'Stato': 'Infortunato',
                    'Dettaglio': desc.strip()
                }
                idx += 2

            elif sec in ['Squalificati', 'Diffidati']:
                player_raw = line
                m_target = player_raw if player_raw in master_names else match_player_name(player_raw, master_names)
                official_name = m_target if m_target else player_raw

                status = 'Squalificato' if sec == 'Squalificati' else 'Diffidato'
                auto_dict[official_name] = {
                    'Giocatore': official_name,
                    'NomeOriginale': player_raw,
                    'Squadra': team,
                    'Stato': status,
                    'Dettaglio': f'{status} per il prossimo turno' if status == 'Squalificato' else 'In diffida'
                }
                idx += 1
            else:
                idx += 1

    # Update cache while preserving manual overrides
    cache_data = load_injuries_data()
    cache_data['auto'] = auto_dict
    import datetime
    cache_data['last_updated'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_injuries_data(cache_data)

    print(f"Successfully scraped {len(auto_dict)} unavailable/booked players from Fantacalcio.it")
    return auto_dict


def get_player_status(player_name, cache_data=None):
    """
    Returns current status and notes for a player, applying manual overrides first.
    Statuses: 'Disponibile', 'Infortunato', 'Squalificato', 'In dubbio', 'Diffidato'
    """
    if cache_data is None:
        cache_data = load_injuries_data()

    manual = cache_data.get('manual_overrides', {})
    auto = cache_data.get('auto', {})

    clean_p = str(player_name).replace('*', '').strip()

    # 1. Check manual override
    if clean_p in manual:
        return manual[clean_p]

    # 2. Check auto scraper
    if clean_p in auto:
        return auto[clean_p]

    return {
        'Giocatore': clean_p,
        'Stato': 'Disponibile',
        'Dettaglio': ''
    }


def parse_injury_details(det, status, current_giornata=10):
    """
    Parses verbose medical bulletin text and returns structured fields:
    - Motivo: concise diagnosis (e.g. 'Lesione bicipite femorale', 'Rottura crociato', 'Squalifica')
    - Rientro_Previsto: human return timeframe (e.g. 'Metà Novembre')
    - Badge_Rientro: badge tied to matchday (e.g. '🟡 Rientro 12ª G.')
    - Giornata_Target: integer target matchday or None
    - Dettaglio_Completo: original full text
    """
    det_lower = str(det).lower()
    
    # 1. Status specific
    if status == 'Squalificato':
        target_g = current_giornata + 1 if current_giornata else 11
        return {
            'Tipo': '🟥 Squalifica',
            'Motivo': 'Squalificato per il turno',
            'Rientro_Previsto': f'{target_g}ª Giornata',
            'Badge_Rientro': f'🟢 Rientro {target_g}ª G.',
            'Giornata_Target': target_g,
            'Dettaglio_Completo': det or 'Squalificato per il turno di campionato'
        }
        
    if status == 'Diffidato':
        return {
            'Tipo': '🟨 Diffida',
            'Motivo': 'In diffida (a rischio)',
            'Rientro_Previsto': 'Disponibile',
            'Badge_Rientro': 'In campo',
            'Giornata_Target': current_giornata,
            'Dettaglio_Completo': det or 'In diffida'
        }
        
    # 2. Extract Motivo Sintetico
    motivo = 'Guaio fisico'
    if 'crociato' in det_lower:
        motivo = 'Rottura crociato'
    elif 'menisco' in det_lower:
        motivo = 'Lesione menisco'
    elif 'bicipite femorale' in det_lower:
        motivo = 'Lesione bicipite femorale'
    elif 'flessore' in det_lower or 'flessori' in det_lower:
        motivo = 'Problema ai flessori'
    elif 'retto femorale' in det_lower or 'retto-adduttoria' in det_lower:
        motivo = 'Problema retto femorale'
    elif 'adduttore' in det_lower or 'adduttori' in det_lower:
        motivo = 'Problema adduttori'
    elif 'polpaccio' in det_lower:
        motivo = 'Problema al polpaccio'
    elif 'caviglia' in det_lower:
        motivo = 'Distorsione/caviglia'
    elif 'ginocchio' in det_lower:
        motivo = 'Problema al ginocchio'
    elif 'tendine' in det_lower:
        motivo = 'Problema al tendine'
    elif 'frattura' in det_lower:
        motivo = 'Frattura'
    elif 'spalla' in det_lower:
        motivo = 'Problema alla spalla'
    elif 'risentimento' in det_lower:
        motivo = 'Risentimento muscolare'
    elif 'affaticamento' in det_lower or 'sovraccarico' in det_lower:
        motivo = 'Affaticamento muscolare'
    elif 'distrazione' in det_lower:
        motivo = 'Distrazione muscolare'
    elif 'lesione' in det_lower:
        motivo = 'Lesione muscolare'
    elif 'operat' in det_lower:
        motivo = 'Post-operatorio'
    elif 'trauma' in det_lower or 'contusion' in det_lower:
        motivo = 'Trauma contusivo'
        
    # 3. Extract Rientro & Mappa Giornata
    rientro_txt = 'Da valutare'
    g_target = None
    badge_rientro = '🟡 Da valutare'
    
    if any(k in det_lower for k in ['inizio novembre', 'inizio di novembre', "dall'inizio di novembre", 'prima metà di novembre', 'inizio nov']):
        rientro_txt = 'Inizio Novembre'
        g_target = 11
        badge_rientro = '🟢 Rientro 11ª G.'
    elif any(k in det_lower for k in ['metà novembre', 'metà di novembre', 'seconda metà di novembre', 'metà nov']):
        rientro_txt = 'Metà Novembre'
        g_target = 12
        badge_rientro = '🟡 Rientro 12ª G.'
    elif any(k in det_lower for k in ['fine novembre', 'fine di novembre', 'dalla fine di novembre', 'fine nov']):
        rientro_txt = 'Fine Novembre'
        g_target = 13
        badge_rientro = '🟠 Rientro 13ª G.'
    elif any(k in det_lower for k in ['inizio dicembre', 'inizio di dicembre', 'prima metà di dicembre']):
        rientro_txt = 'Inizio Dicembre'
        g_target = 14
        badge_rientro = '🟠 Rientro 14ª G.'
    elif any(k in det_lower for k in ['metà dicembre', 'metà di dicembre', 'dicembre']):
        rientro_txt = 'Dicembre'
        g_target = 15
        badge_rientro = '🔴 Rientro 15ª-16ª G.'
    elif any(k in det_lower for k in ['gennaio', 'inizio gennaio', 'metà gennaio']):
        rientro_txt = 'Gennaio 2027'
        g_target = 19
        badge_rientro = '🔴 Rientro ~19ª G.'
    elif 'febbraio' in det_lower:
        rientro_txt = 'Febbraio 2027'
        g_target = 23
        badge_rientro = '⛔ Rientro ~23ª G.'
    elif 'marzo' in det_lower:
        rientro_txt = 'Marzo 2027'
        g_target = 27
        badge_rientro = '⛔ Rientro ~27ª G.'
    elif 'aprile' in det_lower:
        rientro_txt = 'Aprile 2027'
        g_target = 31
        badge_rientro = '⛔ Rientro ~31ª G.'
    elif any(k in det_lower for k in ['maggio', 'stagione finita']):
        rientro_txt = 'Fine Stagione'
        g_target = 36
        badge_rientro = '⛔ Stagione finita'
    elif any(k in det_lower for k in ['fine ottobre', 'fine di ottobre']):
        rientro_txt = 'Fine Ottobre'
        g_target = 10
        badge_rientro = '🟢 Rientro 10ª-11ª G.'
    elif any(k in det_lower for k in ['prossimo turno', 'in dubbio', 'da valutare']):
        rientro_txt = 'In dubbio'
        g_target = current_giornata
        badge_rientro = '🟡 In dubbio'
        
    return {
        'Tipo': '🚑 Infortunio',
        'Motivo': motivo,
        'Rientro_Previsto': rientro_txt,
        'Badge_Rientro': badge_rientro,
        'Giornata_Target': g_target,
        'Dettaglio_Completo': det
    }


def classify_injury_status(player_name, cache_data=None):
    """
    Analyzes medical bulletin and return timeline for a player.
    Returns:
      {
        'Is_Injured': bool,
        'Stato': str ('Disponibile', 'Infortunato', 'Squalificato', 'In dubbio', 'Diffidato'),
        'Dettaglio': str,
        'Is_Long_Term': bool,  # >= 3 weeks, surgery, cruciate, months, next year
        'Is_Short_Term': bool, # <= 2 weeks, return end of October / early November, minor doubt
        'Severity_Label': 'DISPONIBILE' | 'DUBBIO_LIEVE' | 'INFORTUNIO_BREVE' | 'INFORTUNIO_LUNGO',
        'Can_Be_Traded_Out': bool, # False if injured/suspended!
        'Can_Be_Targeted_In': bool # False if long-term injured! True only if healthy or short-term stash
      }
    """
    info = get_player_status(player_name, cache_data)
    st = info.get('Stato', 'Disponibile')
    det = info.get('Dettaglio', '')
    det_lower = det.lower()

    if st == 'Disponibile' or 'Disponibile' in st:
        return {
            'Is_Injured': False,
            'Stato': st,
            'Dettaglio': det,
            'Is_Long_Term': False,
            'Is_Short_Term': False,
            'Severity_Label': 'DISPONIBILE',
            'Can_Be_Traded_Out': True,
            'Can_Be_Targeted_In': True
        }

    if st == 'Squalificato':
        return {
            'Is_Injured': True,
            'Stato': st,
            'Dettaglio': det or 'Squalificato per il turno di campionato',
            'Is_Long_Term': False,
            'Is_Short_Term': True,
            'Severity_Label': 'SQUALIFICATO',
            'Can_Be_Traded_Out': False,
            'Can_Be_Targeted_In': False
        }

    # Injured or in doubt
    long_keywords = [
        'crociato', 'rottura', 'operat', 'mesi', 'marzo', 'febbraio', 'aprile', 'maggio',
        'lungo stop', 'due mesi', 'tre mesi', 'quattro mesi', 'un mese', 'tre settimane',
        'quattro settimane', 'dicembre', 'gennaio', 'metà di novembre', 'seconda metà di novembre',
        'metà novembre', '2027', 'stagione finita'
    ]
    is_long = any(k in det_lower for k in long_keywords)

    short_keywords = [
        'inizio di novembre', 'prima metà di novembre', 'fine di ottobre', 'fine ottobre',
        'prossimo turno', 'da valutare', 'in dubbio', 'trauma', 'affaticamento', 'sovraccarico',
        'risentimento', 'in ripresa', 'lieve', 'affaticato'
    ]
    is_short = not is_long and any(k in det_lower for k in short_keywords)

    if is_long:
        sev_label = 'INFORTUNIO_LUNGO'
    elif is_short or st == 'In dubbio':
        sev_label = 'INFORTUNIO_BREVE'
    else:
        sev_label = 'INFORTUNIO_MEDIO'

    return {
        'Is_Injured': True,
        'Stato': st,
        'Dettaglio': det,
        'Is_Long_Term': is_long,
        'Is_Short_Term': (is_short or st == 'In dubbio'),
        'Severity_Label': sev_label,
        'Can_Be_Traded_Out': False,
        'Can_Be_Targeted_In': not is_long
    }


def set_player_manual_override(player_name, status, dettaglio=""):
    """
    Sets a manual override for a specific player:
    status can be: 'Disponibile', 'Infortunato', 'Squalificato', 'In dubbio'.
    """
    cache_data = load_injuries_data()
    clean_p = str(player_name).replace('*', '').strip()

    if 'manual_overrides' not in cache_data:
        cache_data['manual_overrides'] = {}

    if status == 'Disponibile' and clean_p in cache_data.get('auto', {}):
        # Explicit override to force availability even if auto scraped as injured
        cache_data['manual_overrides'][clean_p] = {
            'Giocatore': clean_p,
            'Stato': 'Disponibile (Forzato)',
            'Dettaglio': dettaglio or 'Disponibile da decisione utente'
        }
    elif status == 'Disponibile':
        # Remove manual override if was set
        cache_data['manual_overrides'].pop(clean_p, None)
    else:
        cache_data['manual_overrides'][clean_p] = {
            'Giocatore': clean_p,
            'Stato': status,
            'Dettaglio': dettaglio or f'Impostato manualmente come {status}'
        }

    save_injuries_data(cache_data)
    return cache_data


def clear_player_manual_override(player_name):
    """Clears any manual override for player, reverting to auto status."""
    cache_data = load_injuries_data()
    clean_p = str(player_name).replace('*', '').strip()
    if 'manual_overrides' in cache_data:
        cache_data['manual_overrides'].pop(clean_p, None)
        save_injuries_data(cache_data)
    return cache_data


def clear_all_manual_overrides():
    """Clears all manual overrides, reverting fully to automatic scraper data."""
    cache_data = load_injuries_data()
    cache_data['manual_overrides'] = {}
    save_injuries_data(cache_data)
    return cache_data


def get_all_unavailable_players(cache_data=None):
    """Returns a list of all currently unavailable players (injured, suspended, in doubt)."""
    if cache_data is None:
        cache_data = load_injuries_data()

    auto = dict(cache_data.get('auto', {}))
    manual = cache_data.get('manual_overrides', {})

    # Apply manual overrides on top of auto
    combined = auto.copy()
    for p, info in manual.items():
        if info['Stato'] == 'Disponibile' or 'Disponibile (Forzato)' in info['Stato']:
            combined.pop(p, None)
        else:
            combined[p] = info

    return list(combined.values())


def get_all_unavailable_df(df_master=None, current_giornata=10):
    """
    Returns a clean, sorted pandas DataFrame of all unavailable Serie A players
    with synthetic diagnosis, return date, and target Serie A matchday badge.
    """
    unavail = get_all_unavailable_players()
    if not unavail:
        return pd.DataFrame(columns=['Giocatore', 'Ruolo', 'Squadra', 'Stato', 'Diagnosi', 'Rientro Stimato', 'Giornata Prevista', 'Giornata_Target', 'Dettaglio Completo'])
    
    role_map = {}
    if df_master is not None and not df_master.empty:
        for _, row in df_master.iterrows():
            g = row.get('Giocatore')
            r = row.get('RuoloMantra') or row.get('RuoloClassic') or row.get('Ruolo', '')
            if g and r:
                role_map[g] = r

    rows = []
    for u in unavail:
        g_name = u.get('Giocatore', '')
        st_val = u.get('Stato', 'Infortunato')
        det_val = u.get('Dettaglio', '')
        parsed = parse_injury_details(det_val, st_val, current_giornata=current_giornata)
        
        rows.append({
            'Giocatore': g_name,
            'Ruolo': role_map.get(g_name, '-'),
            'Squadra': u.get('Squadra', '-'),
            'Stato': st_val,
            'Diagnosi': parsed['Motivo'],
            'Rientro Stimato': parsed['Rientro_Previsto'],
            'Giornata Prevista': parsed['Badge_Rientro'],
            'Giornata_Target': parsed['Giornata_Target'] or 99,
            'Dettaglio Completo': det_val
        })

    df = pd.DataFrame(rows)
    df = df.sort_values(by=['Giornata_Target', 'Squadra', 'Giocatore'], ascending=[True, True, True]).reset_index(drop=True)
    return df


if __name__ == '__main__':
    print("Testing live fetch from Fantacalcio.it...")
    data = fetch_live_injuries_from_fantacalcio()
    print(f"Total live entries: {len(data)}")
    for name in ['Locatelli', 'Conceicao', 'Leysen F.', 'Scalvini', 'Barella', 'Dybala']:
        st = get_player_status(name)
        print(f"  {name:15}: {st['Stato']} | {st['Dettaglio'][:70] if st['Dettaglio'] else 'OK'}")
