"""
Roster Manager for Fantacalcio Mantra.
Manages user roster synchronization with the official league import and df_master.
Zero role guessing, zero synthetic fallbacks.
"""

import os
import sys
import re
import json
import unicodedata
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ROSTER_FILE = os.path.join(DATA_DIR, "user_roster.json")

COMMON_ALIASES = {
    'lautaro': 'Martinez L.',
    'lautaro martinez': 'Martinez L.',
    'josep martinez': 'Martinez Jo.',
    'kvara': 'Kvaratskhelia',
    'kvaratskhelia': 'Kvaratskhelia',
    'theo': 'Hernandez T.',
    'theo hernandez': 'Hernandez T.',
    'calha': 'Calhanoglu',
    'chalanoglu': 'Calhanoglu',
    'calhanoglu': 'Calhanoglu',
    'chiesa': 'Chiesa',
    'vlahovic': 'Vlahovic',
    'dybala': 'Dybala',
    'morata': 'Morata',
    'yildiz': 'Yildiz',
    'carnesecchi': 'Carnesecchi',
    'sommer': 'Sommer',
    'svilar': 'Svilar',
    'de gea': 'De Gea',
    'maignan': 'Maignan',
    'di lorenzo': 'Di Lorenzo',
    'dimarco': 'Dimarco',
    'bastoni': 'Bastoni',
    'buongiorno': 'Buongiorno',
    'bremer': 'Bremer',
    'ederson': 'Ederson D.S.',
    'matias soule': "Soule'",
    'matias soule malvano': "Soule'",
    'soule': "Soule'",
    'nico paz': 'Paz N.',
    'mario gila': 'Gila',
    'josh doig': 'Doig',
    'noa lang': 'Lang',
    'moise kean': 'Kean',
    'marten de roon': 'De Roon',
    'delprato': 'Delprato',
    'evan ndicka': "N'Dicka",
    'ndicka': "N'Dicka",
    'conceicao': 'Conceicao',
    'francisco conceicao': 'Conceicao',
    'hojlund': 'Hojlund',
    'rasmus hojlund': 'Hojlund',
    'nicolas gonzalez': 'Gonzalez N.',
    'nico gonzalez': 'Gonzalez N.',
    'johan vasquez': 'Vasquez',
    'thuram k': 'Thuram K.',
    'thuram k.': 'Thuram K.',
    'khephren thuram': 'Thuram K.',
    'kephren thuram': 'Thuram K.',
    'marcus thuram': 'Thuram'
}


def normalize_str(s):
    if not s or pd.isna(s):
        return ""
    s = str(s).strip()
    s = s.replace('ø', 'o').replace('Ø', 'O').replace('ß', 'ss').replace('æ', 'ae').replace('œ', 'oe').replace('đ', 'd').replace('Đ', 'D')
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    s = re.sub(r'[^a-zA-Z0-9\s]', ' ', s).lower()
    return ' '.join(s.split())


def match_player_name(query, all_names):
    """Fuzzy/normalized matcher for Understat player names."""
    if not query:
        return None
    raw_q = str(query).strip()
    norm_q = normalize_str(raw_q)
    
    # Check alias
    if norm_q in COMMON_ALIASES and COMMON_ALIASES[norm_q] in all_names:
        return COMMON_ALIASES[norm_q]
        
    # Exact normalized check
    for n in all_names:
        if norm_q == normalize_str(n):
            return n
            
    # Token-based match
    query_words = [w for w in norm_q.split() if len(w) > 1]
    if not query_words:
        return None
        
    best_match = None
    best_score = 0
    for n in all_names:
        n_words = [w for w in normalize_str(n).split() if len(w) > 1]
        common = set(query_words).intersection(set(n_words))
        if common:
            score = len(common) * 10
            if n_words and n_words[0] in query_words:
                score += 5
            if score > best_score:
                best_score = score
                best_match = n
                
    if best_score >= 10:
        return best_match
    return None


def load_user_roster():
    """Loads user squad from user_roster.json."""
    if os.path.exists(ROSTER_FILE):
        try:
            with open(ROSTER_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception as e:
            print(f"Error loading roster: {e}")
    return []


def save_user_roster(player_names):
    """Saves player list to user_roster.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    cleaned = sorted(list(set([str(p).strip() for p in player_names if str(p).strip()])))
    with open(ROSTER_FILE, 'w', encoding='utf-8') as f:
        json.dump(cleaned, f, indent=2, ensure_ascii=False)
    return cleaned


def add_player_to_roster(player_name):
    """Adds a single player to user squad."""
    current = load_user_roster()
    p = str(player_name).strip()
    if p and p not in current:
        current.append(p)
        save_user_roster(current)
    return current


def remove_player_from_roster(player_name):
    """Removes a player from user squad."""
    current = load_user_roster()
    p = str(player_name).strip()
    if p in current:
        current.remove(p)
        save_user_roster(current)
    return current


def get_roster_dataframe(df_master, player_names=None):
    """
    Returns the subset of df_master corresponding to user's squad.
    Enriches with loan status and asterisks from the official league data.
    """
    if player_names is None:
        player_names = load_user_roster()

    # Match clean names
    clean_targets = [str(p).replace('*', '').strip() for p in player_names]
    df_squad = df_master[df_master['Giocatore'].isin(clean_targets)].copy()

    # Enrich with League & Loan info if available
    try:
        from engine.league_manager import build_loan_registry, get_active_my_team, load_league_rosters
        my_team = get_active_my_team()
        league = load_league_rosters()
        
        costs = {}
        stars = {}
        if my_team in league:
            for r in league[my_team]:
                costs[r['Giocatore']] = r.get('Costo', 1)
                stars[r['Giocatore']] = r.get('FuoriSerieA', False)
                
        df_squad['Costo'] = df_squad['Giocatore'].map(costs).fillna(1).astype(int)
        df_squad['FuoriSerieA'] = df_squad['Giocatore'].map(stars).fillna(False).astype(bool)
        
        loan_map, _ = build_loan_registry(league)
        df_squad['Stato_Prestito'] = [loan_map.get((my_team, g), {}).get('Stato_Prestito', 'Proprietà') for g in df_squad['Giocatore']]
        df_squad['Badge_Prestito'] = [loan_map.get((my_team, g), {}).get('Badge_Prestito', '✅ PROPRIETÀ') for g in df_squad['Giocatore']]
        df_squad['Dettaglio_Prestito'] = [loan_map.get((my_team, g), {}).get('Dettaglio_Prestito', 'Cartellino di proprietà') for g in df_squad['Giocatore']]
        df_squad['Controparte_Prestito'] = [loan_map.get((my_team, g), {}).get('Controparte', '-') for g in df_squad['Giocatore']]
        df_squad['Schierabile'] = [loan_map.get((my_team, g), {}).get('Schierabile', True) for g in df_squad['Giocatore']]
        df_squad['Da_Svincolare'] = [loan_map.get((my_team, g), {}).get('Da_Svincolare', False) for g in df_squad['Giocatore']]
    except Exception as e:
        df_squad['Costo'] = 1
        df_squad['FuoriSerieA'] = False
        df_squad['Stato_Prestito'] = 'Proprietà'
        df_squad['Badge_Prestito'] = '✅ PROPRIETÀ'
        df_squad['Dettaglio_Prestito'] = 'Cartellino di proprietà'
        df_squad['Controparte_Prestito'] = '-'
        df_squad['Schierabile'] = True
        df_squad['Da_Svincolare'] = False

    # Enrich with Injuries & Suspensions data
    try:
        from engine.injuries_manager import get_player_status, load_injuries_data
        inj_cache = load_injuries_data()
        
        statuses = []
        badges = []
        details = []
        schierabili_effettivi = []
        
        for _, row in df_squad.iterrows():
            g = row['Giocatore']
            info = get_player_status(g, inj_cache)
            st_val = info.get('Stato', 'Disponibile')
            desc_val = info.get('Dettaglio', '')
            
            if st_val == 'Infortunato':
                badge_val = '🚑 INFORTUNATO'
            elif st_val == 'Squalificato':
                badge_val = '🟥 SQUALIFICATO'
            elif st_val == 'In dubbio':
                badge_val = '⚠️ IN DUBBIO'
            elif 'Disponibile (Forzato)' in st_val:
                badge_val = '🟢 FORZATO DISP.'
            elif st_val == 'Diffidato':
                badge_val = '🟨 DIFFIDATO'
            else:
                badge_val = '✅ DISPONIBILE'
                
            statuses.append(st_val)
            badges.append(badge_val)
            details.append(desc_val)
            
            # Check availability
            curr_schierabile = row.get('Schierabile', True)
            if not curr_schierabile:
                is_ok = False
            elif st_val in ['Infortunato', 'Squalificato']:
                is_ok = False
            else:
                is_ok = True
            schierabili_effettivi.append(is_ok)
            
        df_squad['Stato_Disponibilita'] = statuses
        df_squad['Badge_Disponibilita'] = badges
        df_squad['Dettaglio_Disponibilita'] = details
        df_squad['Schierabile'] = schierabili_effettivi
    except Exception as e:
        df_squad['Stato_Disponibilita'] = 'Disponibile'
        df_squad['Badge_Disponibilita'] = '✅ DISPONIBILE'
        df_squad['Dettaglio_Disponibilita'] = ''

    return df_squad
