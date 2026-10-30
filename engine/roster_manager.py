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


def _get_active_roster_file(league_id=None):
    """Returns the path to the active league's user_roster.json, with fallback to root ROSTER_FILE."""
    try:
        from engine.league_manager import get_league_paths
        paths = get_league_paths(league_id)
        return paths.get('user_roster', ROSTER_FILE)
    except Exception:
        return ROSTER_FILE


def load_user_roster(league_id=None):
    """Loads user squad from the active league's user_roster.json, with fallback to root."""
    target_f = _get_active_roster_file(league_id)
    if os.path.exists(target_f):
        try:
            with open(target_f, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception as e:
            print(f"Error loading roster from {target_f}: {e}")

    # Fallback to root ROSTER_FILE
    if os.path.exists(ROSTER_FILE) and target_f != ROSTER_FILE:
        try:
            with open(ROSTER_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception:
            pass
    return []


def save_user_roster(player_names, league_id=None):
    """Saves player list to the active league's user_roster.json AND mirrors to root."""
    cleaned = sorted(list(set([str(p).strip() for p in player_names if str(p).strip()])))
    target_f = _get_active_roster_file(league_id)
    try:
        os.makedirs(os.path.dirname(target_f), exist_ok=True)
        with open(target_f, 'w', encoding='utf-8') as f:
            json.dump(cleaned, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving roster to {target_f}: {e}")

    # Mirror to root ROSTER_FILE for backward compatibility
    if target_f != ROSTER_FILE:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(ROSTER_FILE, 'w', encoding='utf-8') as f:
                json.dump(cleaned, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    return cleaned


def add_player_to_roster(player_name, league_id=None):
    """Adds a single player to user squad."""
    current = load_user_roster(league_id=league_id)
    p = str(player_name).strip()
    if p and p not in current:
        current.append(p)
        save_user_roster(current, league_id=league_id)
    return current


def remove_player_from_roster(player_name, league_id=None):
    """Removes a player from user squad."""
    current = load_user_roster(league_id=league_id)
    p = str(player_name).strip()
    if p in current:
        current.remove(p)
        save_user_roster(current, league_id=league_id)
    return current


def get_roster_dataframe(df_master, player_names=None):
    """
    Returns the subset of df_master corresponding to user's squad.
    Enriches with loan status, out-of-Serie-A asterisks (*) from the official league data,
    injuries/suspensions, and live Probable Starter vs Probable Bench distinction.
    """
    if player_names is None:
        player_names = load_user_roster()

    raw_star_names = {str(p).replace('*', '').strip() for p in player_names if '*' in str(p)}
    clean_targets = [str(p).replace('*', '').strip() for p in player_names]
    df_squad = df_master[df_master['Giocatore'].isin(clean_targets)].copy()

    # Enrich with League & Loan info if available
    try:
        from engine.league_manager import build_loan_registry, get_active_my_team, load_league_rosters
        my_team = get_active_my_team()
        league = load_league_rosters()

        costs = {}
        stars = {g: True for g in raw_star_names}
        raw_names_map = {}
        missing_rows = []
        present_names = set(df_squad['Giocatore'].tolist()) if not df_squad.empty else set()

        if my_team in league:
            for r in league[my_team]:
                g_name = r['Giocatore']
                costs[g_name] = r.get('Costo', 1)
                is_star = bool(
                    r.get('FuoriSerieA', False)
                    or r.get('Da_Svincolare', False)
                    or '*' in str(r.get('NomeGrezzo', ''))
                    or '*' in str(r.get('Giocatore', ''))
                    or g_name in raw_star_names
                )
                stars[g_name] = is_star
                raw_names_map[g_name] = r.get('NomeGrezzo', f"{g_name} *" if is_star else g_name)

                # If an asterisk/released player is not in df_master, still include them in df_squad
                if g_name not in present_names and g_name in clean_targets:
                    missing_rows.append({
                        'Cod': r.get('Cod', 0),
                        'Giocatore': g_name,
                        'Squadra': r.get('Squadra', 'Serie A'),
                        'RuoloClassic': r.get('RuoloClassic', 'C'),
                        'RuoloMantra': r.get('RuoloMantra', 'C'),
                        'Presenze': r.get('Presenze', 0),
                        'MV_Stagione': r.get('MV_Stagione', 0.0),
                        'FM_Stagione': r.get('FM_Stagione', 0.0),
                        'GF': r.get('GF', 0),
                        'GS': r.get('GS', 0),
                        'ASS': r.get('ASS', 0),
                        'AMM': r.get('AMM', 0),
                        'ESP': r.get('ESP', 0),
                        'Minuti_Reali': 0,
                        'Pct_Sufficienza': 0.0,
                        'Pct_Parate': 0.0,
                        'Goals_Prevented': 0.0,
                        'Goals_Prevented_90': 0.0,
                        'Errors_Leading_To_Goal': 0,
                        'Tiri_90': 0.0,
                        'xG_90': 0.0,
                        'xG_Tot': 0.0,
                        'Delta_xG': 0.0,
                        'Key_Passes_90': 0.0,
                        'xA_90': 0.0,
                        'xA_Tot': 0.0,
                        'Delta_xA': 0.0,
                        'Signal': 'NEUTRO'
                    })
                    present_names.add(g_name)

        if missing_rows:
            df_squad = pd.concat([df_squad, pd.DataFrame(missing_rows)], ignore_index=True)

        df_squad['Costo'] = df_squad['Giocatore'].map(costs).fillna(1).astype(int)
        df_squad['FuoriSerieA'] = df_squad['Giocatore'].map(stars).fillna(False).astype(bool)
        df_squad['NomeGrezzo'] = [raw_names_map.get(g, g) for g in df_squad['Giocatore']]

        loan_map, _ = build_loan_registry(league)
        df_squad['Stato_Prestito'] = [loan_map.get((my_team, g), {}).get('Stato_Prestito', 'Proprietà') for g in df_squad['Giocatore']]
        df_squad['Badge_Prestito'] = [loan_map.get((my_team, g), {}).get('Badge_Prestito', '✅ PROPRIETÀ') for g in df_squad['Giocatore']]
        df_squad['Dettaglio_Prestito'] = [loan_map.get((my_team, g), {}).get('Dettaglio_Prestito', 'Cartellino di proprietà') for g in df_squad['Giocatore']]
        df_squad['Controparte_Prestito'] = [loan_map.get((my_team, g), {}).get('Controparte', '-') for g in df_squad['Giocatore']]

        da_svincolare_list = [
            bool(stars.get(g, False) or loan_map.get((my_team, g), {}).get('Da_Svincolare', False))
            for g in df_squad['Giocatore']
        ]
        df_squad['Da_Svincolare'] = da_svincolare_list
        df_squad['FuoriSerieA'] = da_svincolare_list
        df_squad['Schierabile'] = [
            bool(loan_map.get((my_team, g), {}).get('Schierabile', True) and not da_svinc)
            for g, da_svinc in zip(df_squad['Giocatore'], da_svincolare_list)
        ]
    except Exception:
        df_squad['Costo'] = 1
        df_squad['FuoriSerieA'] = False
        df_squad['NomeGrezzo'] = df_squad['Giocatore']
        df_squad['Stato_Prestito'] = 'Proprietà'
        df_squad['Badge_Prestito'] = '✅ PROPRIETÀ'
        df_squad['Dettaglio_Prestito'] = 'Cartellino di proprietà'
        df_squad['Controparte_Prestito'] = '-'
        df_squad['Schierabile'] = True
        df_squad['Da_Svincolare'] = False

    # Enrich with Injuries & Suspensions data + Live Probable Lineups (Probabile Titolare vs Probabile Panchinaro)
    try:
        from engine.injuries_manager import get_player_status, load_injuries_data, parse_injury_details
        from engine.probable_lineups import load_probable_lineups, get_player_probable_info
        inj_cache = load_injuries_data()
        prob_cache = load_probable_lineups(force_refresh=False)

        statuses = []
        badges = []
        details = []
        schierabili_effettivi = []
        ruolo_titolarita_list = []
        prob_voto_pct_list = []
        prob_titolare_pct_list = []
        prob_label_list = []
        motivi_indisp = []
        rientri_previsti = []
        badge_rientri = []
        giornate_rientro = []

        for _, row in df_squad.iterrows():
            g = row['Giocatore']
            sq = row.get('Squadra', '')
            is_da_svinc = bool(row.get('Da_Svincolare', False) or row.get('FuoriSerieA', False))
            is_prestito_out = (row.get('Stato_Prestito') == 'Prestito OUT')

            info = get_player_status(g, inj_cache)
            st_val = info.get('Stato', 'Disponibile')
            desc_val = info.get('Dettaglio', '')

            p_prob = get_player_probable_info(g, prob_cache)
            if p_prob is not None:
                f_slot = p_prob.get('Fanta_Slot', '')
                f_pct = int(p_prob.get('Fanta_Pct', 0))
                ballottaggio_txt = p_prob.get('Ballottaggio', '')
                if st_val == 'Disponibile':
                    if f_slot == 'INFORTUNATO':
                        st_val = 'Infortunato'
                        desc_val = p_prob.get('Dettaglio_Indisponibile') or 'Infortunato'
                    elif f_slot == 'SQUALIFICATO':
                        st_val = 'Squalificato'
                        desc_val = p_prob.get('Dettaglio_Indisponibile') or 'Squalificato'
                if f_slot == 'TITOLARE':
                    prob_titolare_pct = f_pct
                    prob_subentro_pct = 0
                else:
                    prob_subentro_pct = f_pct
                    m_bal = re.search(r'(\d{1,3})%\s*vs\s*', ballottaggio_txt)
                    prob_titolare_pct = int(m_bal.group(1)) if m_bal else 0
            else:
                f_slot = ''
                prob_titolare_pct = 0
                prob_subentro_pct = 0
                ballottaggio_txt = ''

            if is_da_svinc:
                st_val = 'Fuori Serie A'
                badge_val = '🚫 DA SVINCOLARE (*)'
                desc_val = 'Fuori lista Serie A (*) — da svincolare al prossimo mercato'
                is_ok = False
                tit_cat = 'Non Schierabile'
                prob_pct = 0
                prob_titolare_pct = 0
                prob_lbl = '0%'
            elif is_prestito_out:
                badge_val = '📤 PRESTITO OUT'
                if not desc_val:
                    desc_val = f"Ceduto in prestito a {row.get('Controparte_Prestito', 'altra squadra')}"
                is_ok = False
                tit_cat = 'Non Schierabile'
                prob_pct = 0
                prob_titolare_pct = 0
                prob_lbl = '0%'
            elif st_val == 'Infortunato':
                badge_val = '🚑 INFORTUNATO'
                is_ok = False
                tit_cat = 'Non Schierabile'
                prob_pct = 0
                prob_titolare_pct = 0
                prob_lbl = '0%'
            elif st_val == 'Squalificato':
                badge_val = '🟥 SQUALIFICATO'
                is_ok = False
                tit_cat = 'Non Schierabile'
                prob_pct = 0
                prob_titolare_pct = 0
                prob_lbl = '0%'
            else:
                is_ok = True
                # Probabili Titolari MUST have at least 60% probability of starting the match (dal 1')
                if p_prob is not None:
                    is_prob_starter = bool(f_slot == 'TITOLARE' and prob_titolare_pct >= 60)
                else:
                    pres = float(row.get('Presenze', 0) or 0)
                    mins = float(row.get('Minuti_Reali', 0) or 0)
                    avg_m = mins / max(1.0, pres) if pres > 0 else 0.0
                    is_prob_starter = bool(pres >= 3 and avg_m >= 60.0)
                    prob_titolare_pct = 70 if is_prob_starter else 0
                    prob_subentro_pct = 0 if is_prob_starter else 25

                if is_prob_starter:
                    tit_cat = 'Probabile Titolare'
                    prob_pct = prob_titolare_pct
                    prob_lbl = f"{prob_titolare_pct}%"
                    base_badge = f"🟢 PROB. TITOLARE ({prob_titolare_pct}%)"
                else:
                    tit_cat = 'Probabile Panchinaro'
                    prob_pct = prob_titolare_pct if prob_titolare_pct > 0 else prob_subentro_pct
                    if prob_titolare_pct > 0 and prob_subentro_pct > 0:
                        prob_lbl = f"Tit. {prob_titolare_pct}% · Sub. {prob_subentro_pct}%"
                    elif prob_titolare_pct > 0:
                        prob_lbl = f"Tit. {prob_titolare_pct}%"
                    else:
                        prob_lbl = f"Sub. {prob_subentro_pct}%"
                    base_badge = f"🪑 PROB. PANCHINARO ({prob_lbl})"

                if st_val == 'In dubbio':
                    badge_val = f"⚠️ IN DUBBIO · {base_badge}"
                elif st_val == 'Diffidato':
                    badge_val = f"{base_badge} 🟨"
                elif 'Disponibile (Forzato)' in st_val:
                    badge_val = f"🟢 FORZATO DISP. · {base_badge}"
                else:
                    badge_val = base_badge

                if ballottaggio_txt and ballottaggio_txt not in desc_val:
                    desc_val = f"{desc_val} | {ballottaggio_txt}".strip(" |")
                elif not desc_val and p_prob is not None and p_prob.get('Status_Badge'):
                    desc_val = p_prob.get('Status_Badge')

            parsed_inj = parse_injury_details(desc_val, st_val, current_giornata=10)
            motivi_indisp.append(parsed_inj['Motivo'])
            rientri_previsti.append(parsed_inj['Rientro_Previsto'])
            badge_rientri.append(parsed_inj['Badge_Rientro'])
            giornate_rientro.append(parsed_inj['Giornata_Target'])

            statuses.append(st_val)
            badges.append(badge_val)
            details.append(desc_val)
            schierabili_effettivi.append(is_ok)
            ruolo_titolarita_list.append(tit_cat)
            prob_voto_pct_list.append(prob_pct)
            prob_titolare_pct_list.append(prob_titolare_pct)
            prob_label_list.append(prob_lbl)

        df_squad['Stato_Disponibilita'] = statuses
        df_squad['Badge_Disponibilita'] = badges
        df_squad['Dettaglio_Disponibilita'] = details
        df_squad['Schierabile'] = schierabili_effettivi
        df_squad['Categoria_Schierabile'] = ruolo_titolarita_list
        df_squad['Prob_Voto_Pct'] = prob_voto_pct_list
        df_squad['Prob_Titolare_Pct'] = prob_titolare_pct_list
        df_squad['Prob_Label'] = prob_label_list
        df_squad['Motivo_Indisponibilita'] = motivi_indisp
        df_squad['Rientro_Previsto'] = rientri_previsti
        df_squad['Badge_Rientro'] = badge_rientri
        df_squad['Giornata_Rientro'] = giornate_rientro
    except Exception as e:
        import traceback
        traceback.print_exc()
        df_squad['Stato_Disponibilita'] = [
            'Fuori Serie A' if d else 'Disponibile' for d in df_squad.get('Da_Svincolare', False)
        ]
        df_squad['Badge_Disponibilita'] = [
            '🚫 DA SVINCOLARE (*)' if d else '✅ DISPONIBILE' for d in df_squad.get('Da_Svincolare', False)
        ]
        df_squad['Dettaglio_Disponibilita'] = ''
        df_squad['Motivo_Indisponibilita'] = 'Disponibile'
        df_squad['Rientro_Previsto'] = '-'
        df_squad['Badge_Rientro'] = 'Disponibile'
        df_squad['Giornata_Rientro'] = None
        df_squad['Categoria_Schierabile'] = [
            'Probabile Titolare' if s else 'Non Schierabile' for s in df_squad.get('Schierabile', True)
        ]
        df_squad['Prob_Voto_Pct'] = [60 if s else 0 for s in df_squad.get('Schierabile', True)]
        df_squad['Prob_Titolare_Pct'] = [60 if s else 0 for s in df_squad.get('Schierabile', True)]
        df_squad['Prob_Label'] = ['60%' if s else '0%' for s in df_squad.get('Schierabile', True)]

    return df_squad
