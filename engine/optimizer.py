"""
Mantra Lineup Optimizer.
Solves for the optimal Starting 11 and Bench across all 10 official Mantra tactical formations,
maximizing Total Expected Score = sum(xFV) + Expected D-Factor Bonus.
"""

import os
import sys
import re
import numpy as np
import pandas as pd
from itertools import combinations
from scipy.optimize import linear_sum_assignment

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.models import calculate_expected_dfactor

# 10 Official Mantra Formations and their slot requirements
MANTRA_FORMATIONS = {
    '4-3-3': {
        'def_type': '4-def',
        'slots': ['Por', 'Dd', 'Ds', 'Dc', 'Dc', 'M', 'M/C', 'C', 'W/A', 'W/A', 'A/Pc'],
        'max_pc': 1
    },
    '4-3-1-2': {
        'def_type': '4-def',
        'slots': ['Por', 'Dd', 'Ds', 'Dc', 'Dc', 'M', 'M/C', 'C', 'T', 'T/A/Pc', 'A/Pc'],
        'max_pc': 2
    },
    '4-2-3-1': {
        'def_type': '4-def',
        'slots': ['Por', 'Dd', 'Ds', 'Dc', 'Dc', 'M', 'M/C', 'W/T', 'T', 'W/A', 'A/Pc'],
        'max_pc': 1
    },
    '4-4-2': {
        'def_type': '4-def',
        'slots': ['Por', 'Dd', 'Ds', 'Dc', 'Dc', 'E', 'E/W', 'M/C', 'M/C', 'A/Pc', 'A/Pc'],
        'max_pc': 2
    },
    '4-4-1-1': {
        'def_type': '4-def',
        'slots': ['Por', 'Dd', 'Ds', 'Dc', 'Dc', 'M', 'C', 'E/W', 'E/W', 'T/A', 'A/Pc'],
        'max_pc': 1
    },
    '4-1-4-1': {
        'def_type': '4-def',
        'slots': ['Por', 'Dd', 'Ds', 'Dc', 'Dc', 'M', 'C/T', 'T', 'E/W', 'W', 'A/Pc'],
        'max_pc': 1
    },
    '3-5-2': {
        'def_type': '3-def',
        'slots': ['Por', 'Dc', 'Dc', 'Dc/B', 'E', 'E/W', 'M', 'M/C', 'C', 'A/Pc', 'A/Pc'],
        'max_pc': 2
    },
    '3-5-1-1': {
        'def_type': '3-def',
        'slots': ['Por', 'Dc', 'Dc', 'Dc/B', 'M', 'M', 'C', 'E/W', 'E/W', 'T/A', 'A/Pc'],
        'max_pc': 1
    },
    '3-4-1-2': {
        'def_type': '3-def',
        'slots': ['Por', 'Dc', 'Dc', 'Dc/B', 'E', 'E', 'M/C', 'C', 'T', 'A/Pc', 'A/Pc'],
        'max_pc': 2
    },
    '3-4-2-1': {
        'def_type': '3-def',
        'slots': ['Por', 'Dc', 'Dc', 'Dc/B', 'E', 'M', 'M/C', 'E/W', 'T', 'T/A', 'A/Pc'],
        'max_pc': 1
    },
    '3-4-3': {
        'def_type': '3-def',
        'slots': ['Por', 'Dc', 'Dc', 'Dc/B', 'E', 'E', 'M/C', 'C', 'W/A', 'W/A', 'A/Pc'],
        'max_pc': 1
    }
}

SLOT_ROLE_MAP = {
    'Por': {'Por'},
    'Dd': {'Dd'},
    'Ds': {'Ds'},
    'Dc': {'Dc'},               # In 4-man defense, strictly pure Dc
    'Dc/B': {'Dc', 'B'},         # In 3-man defense, both Dc and Braccetto (B) are allowed
    'B': {'B'},
    'E': {'E'},
    'E/W': {'E', 'W'},
    'M': {'M'},
    'M/C': {'M', 'C'},
    'C': {'C'},
    'C/T': {'C', 'T'},
    'W': {'W'},
    'W/T': {'W', 'T'},
    'W/A': {'W', 'A'},
    'T': {'T'},
    'T/A': {'T', 'A'},
    'T/A/Pc': {'T', 'A', 'Pc'},
    'A': {'A'},
    'A/Pc': {'A', 'Pc'},
    'Pc': {'Pc'}
}

def parse_mantra_roles(role_str):
    """Splits role string (e.g. 'B;Ds;E' or 'W;A' or 'C e T' or 'W/A') into a set of distinct roles."""
    if not role_str or pd.isna(role_str):
        return set()
    cleaned = str(role_str).replace('(*)', '').replace('/', ';').replace(',', ';').replace('&', ';').strip()
    # Only replace conjunction ' e ' between spaces (e.g. 'C e T'), NEVER touch role 'E'
    cleaned = re.sub(r'\s+e\s+', ';', cleaned, flags=re.IGNORECASE)
    return set([r.strip() for r in cleaned.split(';') if r.strip()])

def can_fill_slot(player_roles, slot_name):
    """Checks whether player's Mantra roles can satisfy the slot requirement."""
    accepted = SLOT_ROLE_MAP.get(slot_name, set())
    return bool(player_roles.intersection(accepted))

def solve_lineup_for_formation(formation_name, df_projected_roster):
    """
    Finds the optimal legal 11-player lineup for a specified Mantra tactical formation.
    Returns:
      (total_score, starting_11_records, expected_dfactor, formation_name)
    """
    form_cfg = MANTRA_FORMATIONS[formation_name]
    slots = form_cfg['slots']
    max_pc = form_cfg['max_pc']
    is_4def = (form_cfg['def_type'] == '4-def')
    
    # Pre-parse player roles
    players = []
    for _, row in df_projected_roster.iterrows():
        p_roles = parse_mantra_roles(row.get('RuoloMantra', ''))
        players.append({
            'Giocatore': row['Giocatore'],
            'Squadra': row['Squadra'],
            'RuoloMantra': row['RuoloMantra'],
            'Roles': p_roles,
            'xFV': float(row['xFV']),
            'Pred_Voto': float(row.get('Pred_Voto', 6.0)),
            'Is_Pc': ('Pc' in p_roles),
            'Raw': row.to_dict()
        })
        
    # Sort players by xFV descending for fast greedy pruning
    players = sorted(players, key=lambda x: x['xFV'], reverse=True)
    
    # Check minimum requirements
    has_por = any('Por' in p['Roles'] for p in players)
    if not has_por or len(players) < 11:
        return None
        
    # Check if formation has composite attack slots
    cases = []
    if 'T/A/Pc' in slots and 'A/Pc' in slots:
        i_tap = slots.index('T/A/Pc')
        i_ap = slots.index('A/Pc')
        subcases = [
            ('T', 'A'), ('T', 'Pc'),
            ('A', 'A'), ('A', 'Pc'),
            ('Pc', 'A')
        ]
        if max_pc >= 2:
            subcases.append(('Pc', 'Pc'))
        for r1, r2 in subcases:
            s = list(slots)
            s[i_tap] = r1
            s[i_ap] = r2
            cases.append(s)
    elif 'A/Pc' in slots:
        indices = [i for i, s in enumerate(slots) if s == 'A/Pc']
        if len(indices) == 1:
            idx = indices[0]
            s_a = list(slots); s_a[idx] = 'A'
            s_pc = list(slots); s_pc[idx] = 'Pc'
            cases = [s_a, s_pc]
        elif len(indices) == 2:
            i1, i2 = indices[0], indices[1]
            s1 = list(slots); s1[i1] = 'A'; s1[i2] = 'A'
            s2 = list(slots); s2[i1] = 'A'; s2[i2] = 'Pc'
            s3 = list(slots); s3[i1] = 'Pc'; s3[i2] = 'A'
            cases = [s1, s2, s3]
            if max_pc >= 2:
                s4 = list(slots); s4[i1] = 'Pc'; s4[i2] = 'Pc'
                cases.append(s4)
    else:
        cases = [list(slots)]
        
    best_score = -999.0
    best_assignment = None
    best_dfactor = 0.0
    best_slots = None
    
    n_players = len(players)
    for c_slots in cases:
        n_slots = len(c_slots)
        cost_matrix = np.full((n_slots, n_players), 1e6)
        for i, s_name in enumerate(c_slots):
            for j, p in enumerate(players):
                if can_fill_slot(p['Roles'], s_name):
                    # Deterministic micro-tie-breaker (< 0.005 pt):
                    # Prioritizes guaranteed starters (P_Voto), sample size (Presenze) and consistency (Pct_Sufficienza)
                    p_voto_val = float(p['Raw'].get('P_Voto', 0.5))
                    pres_val = min(1.0, float(p['Raw'].get('Presenze', 0)) / 7.0)
                    suff_val = float(p['Raw'].get('Pct_Sufficienza', 50.0)) / 100.0
                    fdr_val = float(p['Raw'].get('FDR', 3))
                    tie_breaker = (p_voto_val * 0.002) + (pres_val * 0.001) + (suff_val * 0.001) - (fdr_val * 0.0003)
                    
                    # Advanced metrics micro-adjustment:
                    if 'Por' in p['Roles']:
                        # Goalkeepers: favor high Goals Prevented/90 and penalize blunders
                        gp_90_val = float(p['Raw'].get('Goals_Prevented_90', 0.0))
                        blunders_val = float(p['Raw'].get('Errors_Leading_To_Goal', 0))
                        save_pct_val = (float(p['Raw'].get('Pct_Parate', 70.0)) - 70.0) / 100.0
                        tie_breaker += (gp_90_val * 0.002) + (save_pct_val * 0.001) - (blunders_val * 0.002)
                    else:
                        # Outfield players: favor real volume (xG_Tot, xA_Tot) and regular starter minutes
                        xg_val = float(p['Raw'].get('xG_90_Regressed', p['Raw'].get('xG_90', 0.0)))
                        xa_val = float(p['Raw'].get('xA_90_Regressed', p['Raw'].get('xA_90', 0.0)))
                        xgtot_val = float(p['Raw'].get('xG_Tot', 0.0))
                        xatot_val = float(p['Raw'].get('xA_Tot', 0.0))
                        mins_val = float(p['Raw'].get('Min_Per_App', 60.0))
                        
                        # Explicit Starter XI Volume Preference:
                        # Starting 11 strongly favors full-game starters (>= 65 mins) and proven season volume (xG_Tot);
                        # Substitutes (< 45 mins) receive an explicit starting penalty, pushing them to the bench
                        if mins_val >= 65.0:
                            mins_bias = 0.06 + min(0.06, (mins_val - 65.0) * 0.002)
                        elif mins_val < 45.0:
                            mins_bias = -0.22 - ((45.0 - mins_val) * 0.015)
                        else:
                            mins_bias = 0.0
                            
                        volume_bias = (xgtot_val * 0.002) + (xatot_val * 0.001)
                        rate_bias = (xg_val * 0.001) + (xa_val * 0.001)
                        tie_breaker += volume_bias + rate_bias + mins_bias
                    
                    cost_matrix[i, j] = - (p['xFV'] + tie_breaker)
                    
        row_ind, col_ind = linear_sum_assignment(cost_matrix)
        if len(row_ind) == n_slots:
            max_cost = cost_matrix[row_ind, col_ind].max()
            if max_cost > 1e5:
                # Infeasible (slot could not be legally satisfied)
                continue
            chosen_xfv = sum(players[j]['xFV'] for j in col_ind)
            def_ratings = []
            for i, j in zip(row_ind, col_ind):
                if c_slots[i] in ['Por', 'Dc', 'Dd', 'Ds', 'Dc/B', 'B']:
                    def_ratings.append(players[j]['Pred_Voto'])
            dfactor, _ = calculate_expected_dfactor(def_ratings)
            tot = chosen_xfv + dfactor
            if tot > best_score:
                best_score = tot
                best_assignment = (row_ind, col_ind)
                best_dfactor = dfactor
                best_slots = c_slots
                
    if not best_assignment:
        return None
        
    r_ind, c_ind = best_assignment
    slot_to_player = {i: players[j] for i, j in zip(r_ind, c_ind)}
    lineup_records = []
    for idx in range(len(best_slots)):
        p_obj = slot_to_player[idx]
        rec = dict(p_obj['Raw'])
        rec['Slot_Assegnato'] = slots[idx]
        lineup_records.append(rec)
        
    return {
        'Modulo': formation_name,
        'TipoDifesa': '4 Difensori' if is_4def else '3 Difensori',
        'Punti_Attesi_Totali': round(best_score, 2),
        'Somma_xFV_Titolari': round(sum(p['xFV'] for p in slot_to_player.values()), 2),
        'D_Factor_Atteso': best_dfactor,
        'Titolari': lineup_records
    }

def _is_playable_bench_backup(b_row, is_gk=False, starter_gk_team=None):
    """
    Checks if a bench player is healthy (not injured, suspended, or out of squad)
    and has a realistic probability of getting a rating according to probable lineups.
    """
    st_txt = str(b_row.get('Status_Titolarita', '')).upper()
    if any(k in st_txt for k in ['INFORTUNATO', 'SQUALIFICATO', 'OUT']):
        return False
    p_voto = float(b_row.get('P_Voto', 0.0))
    xfv = float(b_row.get('xFV', 0.0))
    if is_gk:
        if p_voto >= 0.35:
            return True
        if starter_gk_team and str(b_row.get('Squadra', '')).strip() == str(starter_gk_team).strip() and p_voto >= 0.02:
            return True
        return False
    return (p_voto >= 0.35 and xfv >= 2.0)


def optimize_best_mantra_lineup(df_projected_roster, allowed_formations=None):
    """
    Evaluates all permitted Mantra tactical formations and identifies the single best lineup.
    Also organizes the remaining players into a prioritized bench and verifies whether
    any missing role-for-role backup is covered via legal formation change (Cambio Modulo Master).
    """
    if allowed_formations is None:
        allowed_formations = list(MANTRA_FORMATIONS.keys())
        
    candidates = []
    for f_name in allowed_formations:
        if f_name not in MANTRA_FORMATIONS:
            continue
        res = solve_lineup_for_formation(f_name, df_projected_roster)
        if res:
            candidates.append(res)
            
    if not candidates:
        return None
        
    # Evaluate Squad Depth & Bench Robustness (Direct Role Coverage + Cambio Modulo Coverage):
    for c in candidates:
        tits = c['Titolari']
        tit_names = set(p['Giocatore'] for p in tits)
        bench = [r.to_dict() if hasattr(r, 'to_dict') else dict(r) for _, r in df_projected_roster.iterrows() if r['Giocatore'] not in tit_names]
        starter_por = next((t for t in tits if t.get('Slot_Assegnato') == 'Por'), None)
        starter_por_team = starter_por.get('Squadra') if starter_por else None

        playable_outfield_bench = sorted(
            [
                b for b in bench
                if 'Por' not in parse_mantra_roles(b.get('RuoloMantra', ''))
                and _is_playable_bench_backup(b, is_gk=False)
            ],
            key=lambda x: (float(x.get('P_Voto', 0)), float(x.get('xFV', 0))),
            reverse=True
        )

        uncovered_slots = 0
        uncovered_slot_names = []
        cambio_modulo_slots = []
        checked_slots = set()
        
        for s in tits:
            s_name = s.get('Slot_Assegnato', '')
            if s_name in checked_slots:
                continue
            checked_slots.add(s_name)
            allowed_roles = SLOT_ROLE_MAP.get(s_name, {s_name})
            if s_name == 'Por':
                backups = [
                    b['Giocatore'] for b in bench
                    if 'Por' in parse_mantra_roles(b.get('RuoloMantra', ''))
                    and _is_playable_bench_backup(b, is_gk=True, starter_gk_team=starter_por_team)
                ]
                if len(backups) == 0:
                    uncovered_slots += 1
                    uncovered_slot_names.append(s_name)
            else:
                direct_backups = [
                    b['Giocatore'] for b in playable_outfield_bench
                    if parse_mantra_roles(b.get('RuoloMantra', '')).intersection(allowed_roles)
                ]
                if len(direct_backups) == 0:
                    # Check if a playable bench player can enter via a valid formation switch (Cambio Modulo)
                    rem_10 = [t for t in tits if t['Giocatore'] != s['Giocatore']]
                    covered_by_switch = None
                    for b_cand in playable_outfield_bench:
                        is_ok, new_mod, _ = can_lineup_form_any_valid_mantra(rem_10 + [b_cand], preferred_formation=c['Modulo'])
                        if is_ok:
                            covered_by_switch = {
                                'Slot': s_name,
                                'Titolare': s['Giocatore'],
                                'Subentrante': b_cand['Giocatore'],
                                'Ruolo_Sub': b_cand.get('RuoloMantra', ''),
                                'Nuovo_Modulo': new_mod
                            }
                            break
                    if covered_by_switch:
                        cambio_modulo_slots.append(covered_by_switch)
                    else:
                        uncovered_slots += 1
                        uncovered_slot_names.append(s_name)
                
        # Fragility penalty ONLY for truly uncovered slots (where even formation switch fails)
        fragility_penalty = round(uncovered_slots * 1.5, 2)
        c['Slot_Scoperti'] = uncovered_slot_names
        c['Slot_Coperti_Cambio_Modulo'] = cambio_modulo_slots
        c['Penalita_Fragilita'] = fragility_penalty
        c['Punti_Benchmark_Robusto'] = round(c['Punti_Attesi_Totali'] - fragility_penalty, 2)

    # Sort primarily by HIGHEST Punti_Attesi_Totali (always recommend the absolute highest scoring potential)
    candidates = sorted(candidates, key=lambda x: x['Punti_Attesi_Totali'], reverse=True)
    best_formation_result = candidates[0]

    # Evaluate coverage safety (True ONLY when even formation switch cannot produce a valid 11)
    uncovered = best_formation_result.get('Slot_Scoperti', [])
    has_coverage_issues = (len(uncovered) > 0)
    best_formation_result['Ha_Problemi_Copertura'] = has_coverage_issues

    safe_alternatives = []
    if has_coverage_issues:
        # 1. Search for modules with 0 truly uncovered slots (either direct or via valid cambio modulo)
        fully_covered = [c for c in candidates[1:] if len(c.get('Slot_Scoperti', [])) == 0]
        if fully_covered:
            fully_covered = sorted(fully_covered, key=lambda x: x['Punti_Attesi_Totali'], reverse=True)
            for alt in fully_covered[:2]:
                delta = round(alt['Punti_Attesi_Totali'] - best_formation_result['Punti_Attesi_Totali'], 2)
                safe_alternatives.append({
                    'Modulo': alt['Modulo'],
                    'Punti_Totali': alt['Punti_Attesi_Totali'],
                    'Delta_Punti': delta,
                    'Slot_Scoperti': [],
                    'Somma_xFV_Titolari': alt['Somma_xFV_Titolari'],
                    'D_Factor': alt['D_Factor_Atteso'],
                    'Tipo': '🛡️ Copertura Garantita (11 Valido)',
                    'Dettaglio': f"{alt['Modulo']} garantisce una formazione valida anche in caso di assenze grazie alla panchina (scarto {delta:+.2f} pt)."
                })
        elif len(uncovered) > 1:
            fewer_uncovered = [c for c in candidates[1:] if len(c.get('Slot_Scoperti', [])) < len(uncovered)]
            if fewer_uncovered:
                fewer_uncovered = sorted(fewer_uncovered, key=lambda x: x['Punti_Attesi_Totali'], reverse=True)
                for alt in fewer_uncovered[:1]:
                    delta = round(alt['Punti_Attesi_Totali'] - best_formation_result['Punti_Attesi_Totali'], 2)
                    safe_alternatives.append({
                        'Modulo': alt['Modulo'],
                        'Punti_Totali': alt['Punti_Attesi_Totali'],
                        'Delta_Punti': delta,
                        'Slot_Scoperti': alt.get('Slot_Scoperti', []),
                        'Somma_xFV_Titolari': alt['Somma_xFV_Titolari'],
                        'D_Factor': alt['D_Factor_Atteso'],
                        'Tipo': '⚠️ Minor Rischio Inferiorità',
                        'Dettaglio': f"{alt['Modulo']} riduce gli slot critici non sostituibili a {len(alt['Slot_Scoperti'])} ({', '.join(alt['Slot_Scoperti'])}), scarto {delta:+.2f} pt."
                    })

    best_formation_result['Moduli_Sicuri_Alternativi'] = safe_alternatives
    
    # Build Official Mantra Modalità MASTER Bench (Panchina 1-12)
    tit_names = set([p['Giocatore'] for p in best_formation_result['Titolari']])
    bench_candidates = df_projected_roster[~df_projected_roster['Giocatore'].isin(tit_names)].copy()
    
    master_bench = order_bench_master_mode(best_formation_result['Titolari'], bench_candidates, max_subs=5)
    best_formation_result['Panchina'] = master_bench
    
    # Pre-calculate departmental coverage stress-test audit
    coverage_audit = audit_master_bench_coverage(
        best_formation_result['Titolari'],
        master_bench,
        best_formation_result['Modulo']
    )
    best_formation_result['Audit_Copertura'] = coverage_audit
    
    best_formation_result['Tutti_Moduli_Valutati'] = [
        {
            'Modulo': c['Modulo'],
            'Punti_Totali': c['Punti_Attesi_Totali'],
            'xFV_Titolari': c['Somma_xFV_Titolari'],
            'D_Factor': c['D_Factor_Atteso'],
            'Stato_Copertura': (
                '✅ Copertura 100% Diretta'
                if len(c.get('Slot_Scoperti', [])) == 0 and len(c.get('Slot_Coperti_Cambio_Modulo', [])) == 0
                else (
                    f"🔄 Coperto con Cambio Modulo ({', '.join(x['Slot'] + '→' + x['Nuovo_Modulo'] for x in c.get('Slot_Coperti_Cambio_Modulo', []))})"
                    if len(c.get('Slot_Scoperti', [])) == 0
                    else f"🚨 CRITICO ({len(c['Slot_Scoperti'])} non sostituibili: {', '.join(c['Slot_Scoperti'])})"
                )
            ),
            'Delta_vs_Top': round(c['Punti_Attesi_Totali'] - best_formation_result['Punti_Attesi_Totali'], 2),
            'Punti_Robusti': c.get('Punti_Benchmark_Robusto', c['Punti_Attesi_Totali']),
            'Slot_Scoperti': c.get('Slot_Scoperti', [])
        }
        for c in candidates
    ]
    
    return best_formation_result

def can_lineup_form_any_valid_mantra(players_list, preferred_formation=None):
    """
    Checks if an exact set of 11 players can legally configure AT LEAST ONE 
    of the 10 official Mantra tactical formations.
    Prioritizes preserving preferred_formation if legal, otherwise selects
    the legal formation that yields the highest expected score.
    Returns (True, matching_formation_name, scored_lineup) or (False, None, None).
    """
    if len(players_list) != 11:
        return False, None, None
        
    df_temp = pd.DataFrame(players_list)
    
    # 1. Test preferred formation first
    if preferred_formation and preferred_formation in MANTRA_FORMATIONS:
        res_pref = solve_lineup_for_formation(preferred_formation, df_temp)
        if res_pref is not None:
            return True, preferred_formation, res_pref
            
    # 2. Test other formations, pick highest score
    best_res = None
    best_form = None
    best_score = -999.0
    
    for f_name in MANTRA_FORMATIONS.keys():
        if f_name == preferred_formation:
            continue
        res = solve_lineup_for_formation(f_name, df_temp)
        if res is not None and res['Punti_Attesi_Totali'] > best_score:
            best_score = res['Punti_Attesi_Totali']
            best_res = res
            best_form = f_name
            
    if best_res is not None:
        return True, best_form, best_res
        
    return False, None, None

def compute_bench_priority_score(row):
    """
    Computes the explicit probability and value score of bringing a grade >= 6.0 
    or a bonus (+3 GF, +1 ASS, +1 Clean Sheet), weighted by titolarità P(Voto).
    Integrates Super-Sub / High-Impact metrics (xG/90 and xA/90):
    Bench Top Positions prioritize players who have explosive burst potential (+3 / +1)
    if called into action, avoiding passive 5.5-rated defenders at the top of the bench.
    """
    p_voto = float(row.get('P_Voto', 0.85))
    pct_suff = float(row.get('Pct_Sufficienza', 60.0))
    pred_voto = float(row.get('Pred_Voto', 6.0))
    exp_gf = float(row.get('Exp_GF', 0.0))
    exp_ass = float(row.get('Exp_ASS', 0.0))
    bonus_imb = float(row.get('Bonus_Imbattibilita', 0.0))
    
    # Expected bonus points
    exp_bonus_pts = (3.0 * exp_gf) + (1.0 * exp_ass) + bonus_imb
    
    # Underlying burst efficiency (/90)
    xg_90 = float(row.get('xG_90_Regressed', row.get('xG_90', 0.0)))
    xa_90 = float(row.get('xA_90_Regressed', row.get('xA_90', 0.0)))
    burst_pot = (3.0 * xg_90) + (1.0 * xa_90)
    
    # Probability of goal or assist
    p_bonus = 1.0 - np.exp(-(exp_gf + exp_ass)) if (exp_gf + exp_ass) > 0 else 0.0
    if 'Por' in str(row.get('RuoloMantra', '')):
        p_bonus = float(row.get('Clean_Sheet_Prob', 0.0))
        
    p_suff = pct_suff / 100.0
    # Probability of bringing EITHER a vote >= 6 OR a bonus, conditioned on playing:
    prob_voto_ge_6_or_bonus = p_suff + ((1.0 - p_suff) * p_bonus)
    net_prob_ge_6_or_bonus = round(p_voto * prob_voto_ge_6_or_bonus * 100.0, 1)
    
    raw_xfv = float(row.get('xFV', 6.0))
    
    # Super-Sub Upside Factor:
    # If a player has high offensive efficiency per 90 (burst_pot >= 0.60) and regular game participation (P_Voto >= 0.40),
    # boost bench priority score so game-changers (e.g. Neres, Pedro, Simeone) sit in the Top 5 Cambi
    supersub_boost = 0.0
    if burst_pot >= 0.60 and p_voto >= 0.40 and not 'Por' in str(row.get('RuoloMantra', '')):
        supersub_boost = min(1.25, (burst_pot - 0.40) * 0.45 * p_voto)
        
    # Bench priority score: scales expected fantasy value with probability of vote >= 6 or bonus + supersub burst
    bench_score = round(raw_xfv * (net_prob_ge_6_or_bonus / 100.0)**0.35 + supersub_boost, 2)
    
    return bench_score, net_prob_ge_6_or_bonus, round(exp_bonus_pts, 2)

def order_bench_master_mode(titolari, df_bench_candidates, max_subs=5):
    """
    Constructs the 12-man bench strictly ordered for Mantra Modalità MASTER (Positions 1 to 12).
    Schiera i calciatori rigorosamente in ordine di possibilità di portare voto superiore al 6
    o bonus alla squadra, combinato con la titolarità P(Voto).
    - Position 1: 2° Portiere (Por)
    - Positions 2 to 6 (TOP 5 CAMBI): I migliori 5 calciatori di movimento per Score Voto>=6 / Bonus
    - Positions 7 to 11: Rincalzi di movimento ordinati per Score Voto>=6 / Bonus
    - Position 12: 3° Portiere (se presente) oppure ultimo rincalzo di movimento
    """
    df_b = df_bench_candidates.copy()
    
    # Calculate Bench Priority Score and Voto>=6/Bonus probability for each candidate
    bench_scores = []
    prob_voto_bonus = []
    bonus_attesi = []
    
    for _, row in df_b.iterrows():
        s, p, b = compute_bench_priority_score(row)
        bench_scores.append(s)
        prob_voto_bonus.append(p)
        bonus_attesi.append(b)
        
    df_b['Score_Panchina'] = bench_scores
    df_b['Prob_Voto6_o_Bonus'] = prob_voto_bonus
    df_b['Bonus_Atteso'] = bonus_attesi
    if 'EV' not in df_b.columns:
        df_b['EV'] = df_b['Score_Panchina']

    por_df = df_b[df_b['RuoloMantra'].str.contains('Por')].sort_values('Score_Panchina', ascending=False)
    outfield_df = df_b[~df_b['RuoloMantra'].str.contains('Por')].sort_values('Score_Panchina', ascending=False)

    bench_final = []
    
    # Posizione 1: 2° Portiere
    if not por_df.empty:
        p1 = por_df.iloc[0].to_dict()
        p1['Fascia_Master'] = '🧤 2° PORTIERE'
        p1['Note_Tattiche'] = 'Subentra automaticamente solo se il Portiere titolare è S.V.'
        bench_final.append(p1)

    # Posizioni 2-6: I 5 migliori calciatori di movimento per possibilità di voto >= 6 o bonus
    outfield_top5 = outfield_df.head(5)
    for _, row in outfield_top5.iterrows():
        p_copy = row.to_dict()
        p_copy['Fascia_Master'] = '⭐ TOP 5 CAMBIO'
        p_copy['Note_Tattiche'] = 'Priorità assoluta: consuma quota 5 cambi massimi.'
        bench_final.append(p_copy)

    # Posizioni 7-11: Rincalzi di profondità ordinati per possibilità di voto >= 6 o bonus
    has_third_por = len(por_df) > 1
    depth_slots = 5 if has_third_por else 6
    outfield_depth = outfield_df.iloc[5:5 + depth_slots]
    for _, row in outfield_depth.iterrows():
        p_copy = row.to_dict()
        p_copy['Fascia_Master'] = '🪑 RINCALZO'
        p_copy['Note_Tattiche'] = 'Subentra se i primi 5 non configurano modulo valido o sono S.V.'
        bench_final.append(p_copy)

    # Posizione 12: 3° Portiere in coda (se presente)
    if has_third_por and len(bench_final) < 12:
        p3 = por_df.iloc[1].to_dict()
        p3['Fascia_Master'] = '🧤 3° PORTIERE'
        p3['Note_Tattiche'] = 'Copertura di emergenza estrema per la porta.'
        bench_final.append(p3)

    # Imposta Posizione_Panchina (1-12) e Copertura_Tattica
    for idx, b in enumerate(bench_final):
        b['Posizione_Panchina'] = idx + 1
        roles = parse_mantra_roles(b.get('RuoloMantra', ''))
        cov = []
        if 'Por' in roles:
            cov.append('Porta')
        if roles.intersection({'Dc', 'B'}):
            cov.append('Centro Difesa')
        if roles.intersection({'Dd', 'Ds'}):
            cov.append('Corsie Difensive')
        if roles.intersection({'E'}):
            cov.append('Fasce / Esterni')
        if roles.intersection({'M', 'C'}):
            cov.append('Mediana')
        if roles.intersection({'T', 'W'}):
            cov.append('Trequarti/Ali')
        if roles.intersection({'A', 'Pc'}):
            cov.append('Attacco')
        b['Copertura_Tattica'] = ' • '.join(cov) if cov else b.get('RuoloMantra', '')

    return bench_final

def simulate_master_substitutions(titolari, panchina, initial_formation, max_subs=5, simulated_missing_names=None):
    """
    Simulates official Fantacalcio.it Mantra MASTER substitutions.
    Comanda totalmente l'ordine panchina (1 to 12).
    Entra sempre il primo a voto in panchina che configura un modulo valido tra i 10 Mantra.
    Max 5 substitutions total.
    """
    if simulated_missing_names is None:
        simulated_missing_names = []
        
    missing_set = set(simulated_missing_names)
    simulated_missing = [p for p in titolari if p['Giocatore'] in missing_set]
    
    current_field = [dict(t) for t in titolari]
    subs_made = []
    bench_used_indices = set()
    current_module = initial_formation
    
    # 1. Handle Goalkeeper first if missing
    por_missing = [p for p in simulated_missing if 'Por' in p.get('Slot_Assegnato', '')]
    if por_missing and len(subs_made) < max_subs:
        for p_out in por_missing:
            sub_found = False
            for b_idx, b in enumerate(panchina):
                if b_idx in bench_used_indices:
                    continue
                b_roles = parse_mantra_roles(b.get('RuoloMantra', ''))
                if 'Por' in b_roles:
                    bench_used_indices.add(b_idx)
                    current_field = [p if p['Giocatore'] != p_out['Giocatore'] else b for p in current_field]
                    subs_made.append({
                        'Out': p_out['Giocatore'],
                        'Out_Slot': p_out['Slot_Assegnato'],
                        'In': b['Giocatore'],
                        'In_Pos': b_idx + 1,
                        'In_Roles': b.get('RuoloMantra', ''),
                        'In_Fascia': b.get('Fascia_Master', ''),
                        'Modulo_Nuovo': current_module,
                        'Status': '✅ CAMBIO EFFETTUATO',
                        'Dettaglio': f"Subentra il 2° portiere (Panchina #{b_idx+1}) mantenendo invariato il modulo {current_module}."
                    })
                    sub_found = True
                    break
            if not sub_found:
                subs_made.append({
                    'Out': p_out['Giocatore'],
                    'Out_Slot': p_out['Slot_Assegnato'],
                    'In': 'NESSUN PORTIERE A VOTO',
                    'In_Pos': '-',
                    'In_Roles': '-',
                    'In_Fascia': '-',
                    'Modulo_Nuovo': current_module,
                    'Status': '❌ PORTA SCOPERTA',
                    'Dettaglio': 'Nessun portiere di riserva disponibile a voto.'
                })

    # 2. Handle Outfield players
    outfield_missing = [p for p in simulated_missing if 'Por' not in p.get('Slot_Assegnato', '')]
    for p_out in outfield_missing:
        if len(subs_made) >= max_subs:
            subs_made.append({
                'Out': p_out['Giocatore'],
                'Out_Slot': p_out['Slot_Assegnato'],
                'In': 'LIMITE 5 CAMBI RAGGIUNTO',
                'In_Pos': '-',
                'In_Roles': '-',
                'In_Fascia': '-',
                'Modulo_Nuovo': current_module,
                'Status': '⚠️ CAMBI ESAURITI',
                'Dettaglio': f'Raggiunto il tetto massimo di {max_subs} sostituzioni consentite.'
            })
            continue

        remaining_10 = [p for p in current_field if p['Giocatore'] != p_out['Giocatore']]
        sub_found = False

        # Scan bench in strict sequential order 1 to 12
        for b_idx, b in enumerate(panchina):
            if b_idx in bench_used_indices:
                continue
            b_roles = parse_mantra_roles(b.get('RuoloMantra', ''))
            if 'Por' in b_roles:
                continue # Goalkeepers cannot sub for outfield players

            candidate_11 = remaining_10 + [b]
            is_valid, new_mod, _ = can_lineup_form_any_valid_mantra(candidate_11, preferred_formation=current_module)
            if is_valid:
                bench_used_indices.add(b_idx)
                current_field = candidate_11
                modulo_changed = (new_mod != current_module)
                trans_msg = f"Modulo variato da {current_module} a {new_mod}" if modulo_changed else f"Modulo confermato ({current_module})"
                current_module = new_mod
                subs_made.append({
                    'Out': p_out['Giocatore'],
                    'Out_Slot': p_out['Slot_Assegnato'],
                    'In': b['Giocatore'],
                    'In_Pos': b_idx + 1,
                    'In_Roles': b.get('RuoloMantra', ''),
                    'In_Fascia': b.get('Fascia_Master', ''),
                    'Modulo_Nuovo': current_module,
                    'Status': '✅ CAMBIO EFFETTUATO',
                    'Dettaglio': f"Entra #{b_idx+1} {b['Giocatore']} ({b.get('RuoloMantra', '')}). {trans_msg}."
                })
                sub_found = True
                break

        if not sub_found:
            subs_made.append({
                'Out': p_out['Giocatore'],
                'Out_Slot': p_out['Slot_Assegnato'],
                'In': 'NESSUN CAMBIO VALIDO (IN 10!)',
                'In_Pos': '-',
                'In_Roles': '-',
                'In_Fascia': '-',
                'Modulo_Nuovo': f'{current_module} (Incompleto)',
                'Status': '❌ SQUADRA IN 10',
                'Dettaglio': 'Nessun giocatore disponibile in panchina è in grado di completare un modulo valido.'
            })

    return {
        'Sostituzioni': subs_made,
        'Cambi_Effettuati': len([s for s in subs_made if s['Status'] == '✅ CAMBIO EFFETTUATO']),
        'Modulo_Finale': current_module,
        'Rosa_In_Campo': current_field
    }

def audit_master_bench_coverage(titolari, panchina, initial_formation):
    """
    Runs automated stress-tests simulating single and multi-player absences
    to verify that the Master bench provides 100% legal coverage across departments.
    """
    tests = []
    
    # 1. Portiere
    por_tits = [t for t in titolari if 'Por' in t.get('Slot_Assegnato', '')]
    if por_tits:
        sim = simulate_master_substitutions(titolari, panchina, initial_formation, simulated_missing_names=[por_tits[0]['Giocatore']])
        sub = sim['Sostituzioni'][0] if sim['Sostituzioni'] else {}
        tests.append({
            'Scenario': 'Assenza Portiere Titolare',
            'Titolare_Testato': f"{por_tits[0]['Giocatore']} ({por_tits[0]['Slot_Assegnato']})",
            'Giocatore_Subentrante': f"#{sub.get('In_Pos')} {sub.get('In')} ({sub.get('In_Roles')})",
            'Modulo_Risultante': sub.get('Modulo_Nuovo', initial_formation),
            'Esito': '✅ Coperto' if '✅' in sub.get('Status', '') else '❌ Scoperto'
        })
        
    # 2. Difensore Centrale (Dc)
    dc_tits = [t for t in titolari if 'Dc' in t.get('Slot_Assegnato', '')]
    if dc_tits:
        sim = simulate_master_substitutions(titolari, panchina, initial_formation, simulated_missing_names=[dc_tits[0]['Giocatore']])
        sub = sim['Sostituzioni'][0] if sim['Sostituzioni'] else {}
        tests.append({
            'Scenario': 'Assenza Difensore Centrale',
            'Titolare_Testato': f"{dc_tits[0]['Giocatore']} ({dc_tits[0]['Slot_Assegnato']})",
            'Giocatore_Subentrante': f"#{sub.get('In_Pos')} {sub.get('In')} ({sub.get('In_Roles')})",
            'Modulo_Risultante': sub.get('Modulo_Nuovo', initial_formation),
            'Esito': '✅ Coperto' if '✅' in sub.get('Status', '') else '❌ Scoperto'
        })
        
    # 3. Terzino / Esterno (Dd/Ds/E)
    wing_tits = [t for t in titolari if any(r in t.get('Slot_Assegnato', '') for r in ['Dd', 'Ds', 'E'])]
    if wing_tits:
        sim = simulate_master_substitutions(titolari, panchina, initial_formation, simulated_missing_names=[wing_tits[0]['Giocatore']])
        sub = sim['Sostituzioni'][0] if sim['Sostituzioni'] else {}
        tests.append({
            'Scenario': 'Assenza Esterno/Terzino',
            'Titolare_Testato': f"{wing_tits[0]['Giocatore']} ({wing_tits[0]['Slot_Assegnato']})",
            'Giocatore_Subentrante': f"#{sub.get('In_Pos')} {sub.get('In')} ({sub.get('In_Roles')})",
            'Modulo_Risultante': sub.get('Modulo_Nuovo', initial_formation),
            'Esito': '✅ Coperto' if '✅' in sub.get('Status', '') else '❌ Scoperto'
        })
        
    # 4. Mediano / Mezzala (M/C)
    mid_tits = [t for t in titolari if any(r in t.get('Slot_Assegnato', '') for r in ['M', 'C', 'M/C'])]
    if mid_tits:
        sim = simulate_master_substitutions(titolari, panchina, initial_formation, simulated_missing_names=[mid_tits[0]['Giocatore']])
        sub = sim['Sostituzioni'][0] if sim['Sostituzioni'] else {}
        tests.append({
            'Scenario': 'Assenza Centrocampista Mediano',
            'Titolare_Testato': f"{mid_tits[0]['Giocatore']} ({mid_tits[0]['Slot_Assegnato']})",
            'Giocatore_Subentrante': f"#{sub.get('In_Pos')} {sub.get('In')} ({sub.get('In_Roles')})",
            'Modulo_Risultante': sub.get('Modulo_Nuovo', initial_formation),
            'Esito': '✅ Coperto' if '✅' in sub.get('Status', '') else '❌ Scoperto'
        })
        
    # 5. Attaccante / Punta (Pc/A/W)
    att_tits = [t for t in titolari if any(r in t.get('Slot_Assegnato', '') for r in ['Pc', 'A', 'W', 'W/T', 'A/Pc'])]
    if att_tits:
        sim = simulate_master_substitutions(titolari, panchina, initial_formation, simulated_missing_names=[att_tits[0]['Giocatore']])
        sub = sim['Sostituzioni'][0] if sim['Sostituzioni'] else {}
        tests.append({
            'Scenario': 'Assenza Attaccante Primario',
            'Titolare_Testato': f"{att_tits[0]['Giocatore']} ({att_tits[0]['Slot_Assegnato']})",
            'Giocatore_Subentrante': f"#{sub.get('In_Pos')} {sub.get('In')} ({sub.get('In_Roles')})",
            'Modulo_Risultante': sub.get('Modulo_Nuovo', initial_formation),
            'Esito': '✅ Coperto' if '✅' in sub.get('Status', '') else '❌ Scoperto'
        })
        
    # 6. Doppia assenza contemporanea (Difensore + Centrocampista)
    if dc_tits and mid_tits:
        sim2 = simulate_master_substitutions(titolari, panchina, initial_formation, simulated_missing_names=[dc_tits[0]['Giocatore'], mid_tits[0]['Giocatore']])
        subs2 = sim2['Sostituzioni']
        in_names = " + ".join([f"#{s.get('In_Pos')} {s.get('In')}" for s in subs2])
        all_ok = all('✅' in s.get('Status', '') for s in subs2) and len(subs2) == 2
        tests.append({
            'Scenario': 'Doppia Assenza (Dc + M/C)',
            'Titolare_Testato': f"{dc_tits[0]['Giocatore']} + {mid_tits[0]['Giocatore']}",
            'Giocatore_Subentrante': in_names,
            'Modulo_Risultante': sim2.get('Modulo_Finale', initial_formation),
            'Esito': '✅ Coperto' if all_ok else '❌ Scoperto'
        })
        
    return pd.DataFrame(tests)

if __name__ == '__main__':
    from engine.models import batch_predict_xfv
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    master_path = os.path.join(data_dir, "players_master.csv")
    df_m = pd.read_csv(master_path)
    
    # Create a realistic sample squad (25 players)
    sample_names = [
        'Carnesecchi', 'Milinkovic-Savic V.', # Por
        'Akanji', 'Kolasinac', 'Scalvini', 'Balerdi', # Dc
        'Alberto Costa', 'Guilbert', # Dd;E
        'Gallo', 'Alhassane', # Ds;E
        'Ederson D.S.', 'Adopo', # M;C
        'Pasalic', 'Aebischer', 'Samardzic', # C, C;W;T
        'Moreira', 'Touré E.', # E;W
        'Pulisic', 'Adzic', # T;A, T
        'Kvernadze', 'Addai', # W;A
        'Martinez L.', 'Thuram', 'Scamacca', 'Raimondo' # Pc
    ]
    sample_roster = df_m[df_m['Giocatore'].isin(sample_names)].copy()
    print(f"Sample squad size: {len(sample_roster)} players")
    
    df_proj = batch_predict_xfv(sample_roster, matchday=6)
    best_res = optimize_best_mantra_lineup(df_proj)
    
    if best_res:
        print(f"\n==========================================")
        print(f"[BEST] FORMAZIONE OTTIMALE SCELTA: {best_res['Modulo']}")
        print(f"Punti Attesi Totali: {best_res['Punti_Attesi_Totali']}")
        print(f"xFV Titolari: {best_res['Somma_xFV_Titolari']} | D-Factor Bonus Atteso: +{best_res['D_Factor_Atteso']} pts")
        print(f"==========================================")
        print("\nTITOLARI:")
        for t in best_res['Titolari']:
            print(f"[{t['Slot_Assegnato']}] {t['Giocatore']} ({t['Squadra']}) - Ruolo: {t['RuoloMantra']} - xFV: {t['xFV']} (Voto: {t['Pred_Voto']})")
            
        print("\nPANCHINA (Primi 5):")
        for b in best_res['Panchina'][:5]:
            print(f"- {b['Giocatore']} ({b['RuoloMantra']}) - xFV: {b['xFV']}")
            
        print("\nCONFRONTO TUTTI I MODULI TESTATI:")
        for m in best_res['Tutti_Moduli_Valutati']:
            print(f"Modulo: {m['Modulo']} -> Totale: {m['Punti_Totali']} (xFV: {m['xFV_Titolari']} + D-Factor: +{m['D_Factor']})")


# =============================================================
# CLASSIC FORMATIONS & LINEUP OPTIMIZER
# =============================================================

CLASSIC_FORMATIONS = {
    '3-4-3': {
        'def_type': '3-def',
        'n_def': 3,
        'n_mid': 4,
        'n_att': 3,
        'slots': ['P', 'D', 'D', 'D', 'C', 'C', 'C', 'C', 'A', 'A', 'A']
    },
    '3-5-2': {
        'def_type': '3-def',
        'n_def': 3,
        'n_mid': 5,
        'n_att': 2,
        'slots': ['P', 'D', 'D', 'D', 'C', 'C', 'C', 'C', 'C', 'A', 'A']
    },
    '4-3-3': {
        'def_type': '4-def',
        'n_def': 4,
        'n_mid': 3,
        'n_att': 3,
        'slots': ['P', 'D', 'D', 'D', 'D', 'C', 'C', 'C', 'A', 'A', 'A']
    },
    '4-4-2': {
        'def_type': '4-def',
        'n_def': 4,
        'n_mid': 4,
        'n_att': 2,
        'slots': ['P', 'D', 'D', 'D', 'D', 'C', 'C', 'C', 'C', 'A', 'A']
    },
    '4-5-1': {
        'def_type': '4-def',
        'n_def': 4,
        'n_mid': 5,
        'n_att': 1,
        'slots': ['P', 'D', 'D', 'D', 'D', 'C', 'C', 'C', 'C', 'C', 'A']
    },
    '5-3-2': {
        'def_type': '5-def',
        'n_def': 5,
        'n_mid': 3,
        'n_att': 2,
        'slots': ['P', 'D', 'D', 'D', 'D', 'D', 'C', 'C', 'C', 'A', 'A']
    },
    '5-4-1': {
        'def_type': '5-def',
        'n_def': 5,
        'n_mid': 4,
        'n_att': 1,
        'slots': ['P', 'D', 'D', 'D', 'D', 'D', 'C', 'C', 'C', 'C', 'A']
    }
}


def solve_lineup_for_classic_formation(formation_name, df_projected_roster):
    """Finds the optimal legal 11-player lineup for a specified Classic formation."""
    if formation_name not in CLASSIC_FORMATIONS:
        return None

    cfg = CLASSIC_FORMATIONS[formation_name]
    n_def = cfg['n_def']
    n_mid = cfg['n_mid']
    n_att = cfg['n_att']

    gk_list = []
    def_list = []
    mid_list = []
    att_list = []

    for _, row in df_projected_roster.iterrows():
        p_dict = row.to_dict()
        rc = str(p_dict.get('RuoloClassic', '')).strip().upper()
        if not rc:
            rm = str(p_dict.get('RuoloMantra', ''))
            if 'Por' in rm:
                rc = 'P'
            elif any(r in rm for r in ['Dc', 'Dd', 'Ds', 'B']):
                rc = 'D'
            elif any(r in rm for r in ['A', 'Pc']):
                rc = 'A'
            else:
                rc = 'C'

        p_voto_val = float(p_dict.get('P_Voto', 0.5))
        pres_val = min(1.0, float(p_dict.get('Presenze', 0)) / 7.0)
        suff_val = float(p_dict.get('Pct_Sufficienza', 50.0)) / 100.0
        fdr_val = float(p_dict.get('FDR', 3))
        tie_breaker = (p_voto_val * 0.002) + (pres_val * 0.001) + (suff_val * 0.001) - (fdr_val * 0.0003)

        if rc == 'P':
            gp_90_val = float(p_dict.get('Goals_Prevented_90', 0.0))
            blunders_val = float(p_dict.get('Errors_Leading_To_Goal', 0))
            save_pct_val = (float(p_dict.get('Pct_Parate', 70.0)) - 70.0) / 100.0
            tie_breaker += (gp_90_val * 0.002) + (save_pct_val * 0.001) - (blunders_val * 0.002)
        else:
            xg_val = float(p_dict.get('xG_90_Regressed', p_dict.get('xG_90', 0.0)))
            xa_val = float(p_dict.get('xA_90_Regressed', p_dict.get('xA_90', 0.0)))
            mins_val = float(p_dict.get('Min_Per_App', 60.0))
            mins_bias = 0.06 if mins_val >= 65.0 else (-0.22 if mins_val < 45.0 else 0.0)
            tie_breaker += (xg_val * 0.002) + (xa_val * 0.002) + mins_bias

        p_entry = {
            'player': p_dict,
            'xFV': float(p_dict.get('xFV', 0.0)),
            'sort_score': float(p_dict.get('xFV', 0.0)) + tie_breaker,
            'Pred_Voto': float(p_dict.get('Pred_Voto', 6.0))
        }

        if rc == 'P':
            gk_list.append(p_entry)
        elif rc == 'D':
            def_list.append(p_entry)
        elif rc == 'C':
            mid_list.append(p_entry)
        elif rc == 'A':
            att_list.append(p_entry)

    if len(gk_list) < 1 or len(def_list) < n_def or len(mid_list) < n_mid or len(att_list) < n_att:
        return None

    gk_list = sorted(gk_list, key=lambda x: x['sort_score'], reverse=True)
    def_list = sorted(def_list, key=lambda x: x['sort_score'], reverse=True)
    mid_list = sorted(mid_list, key=lambda x: x['sort_score'], reverse=True)
    att_list = sorted(att_list, key=lambda x: x['sort_score'], reverse=True)

    chosen_gk = gk_list[:1]
    chosen_def = def_list[:n_def]
    chosen_mid = mid_list[:n_mid]
    chosen_att = att_list[:n_att]

    dfactor = 0.0
    if n_def >= 4:
        def_ratings = [chosen_gk[0]['Pred_Voto']] + [d['Pred_Voto'] for d in chosen_def]
        dfactor, _ = calculate_expected_dfactor(def_ratings)

    sum_xfv = sum(p['xFV'] for p in chosen_gk + chosen_def + chosen_mid + chosen_att)
    total_score = sum_xfv + dfactor

    titolari = []
    for p in chosen_gk:
        rec = dict(p['player'])
        rec['Slot_Assegnato'] = 'P'
        titolari.append(rec)
    for p in chosen_def:
        rec = dict(p['player'])
        rec['Slot_Assegnato'] = 'D'
        titolari.append(rec)
    for p in chosen_mid:
        rec = dict(p['player'])
        rec['Slot_Assegnato'] = 'C'
        titolari.append(rec)
    for p in chosen_att:
        rec = dict(p['player'])
        rec['Slot_Assegnato'] = 'A'
        titolari.append(rec)

    return {
        'Modulo': formation_name,
        'TipoDifesa': f"{n_def} Difensori",
        'Punti_Attesi_Totali': round(total_score, 2),
        'Somma_xFV_Titolari': round(sum_xfv, 2),
        'D_Factor_Atteso': round(dfactor, 2),
        'Titolari': titolari
    }


def optimize_best_classic_lineup(df_projected_roster, allowed_formations=None):
    """Evaluates all permitted Classic formations and identifies the best lineup and bench."""
    if allowed_formations is None:
        allowed_formations = list(CLASSIC_FORMATIONS.keys())

    candidates = []
    for f_name in allowed_formations:
        if f_name not in CLASSIC_FORMATIONS:
            continue
        res = solve_lineup_for_classic_formation(f_name, df_projected_roster)
        if res:
            candidates.append(res)

    if not candidates:
        return None

    for c in candidates:
        tits = c['Titolari']
        tit_names = set(p['Giocatore'] for p in tits)
        bench = [r.to_dict() if hasattr(r, 'to_dict') else dict(r) for _, r in df_projected_roster.iterrows() if r['Giocatore'] not in tit_names]
        starter_p = next((t for t in tits if t.get('Slot_Assegnato') == 'P'), None)
        starter_p_team = starter_p.get('Squadra') if starter_p else None

        playable_outfield = sorted(
            [b for b in bench if b.get('RuoloClassic') in ('D', 'C', 'A') and _is_playable_bench_backup(b, is_gk=False)],
            key=lambda x: (float(x.get('P_Voto', 0)), float(x.get('xFV', 0))),
            reverse=True
        )

        uncovered = []
        cambio_modulo_slots = []
        p_bench = [b for b in bench if b.get('RuoloClassic') == 'P' and _is_playable_bench_backup(b, is_gk=True, starter_gk_team=starter_p_team)]
        if not p_bench:
            uncovered.append('P')

        for r_code in ('D', 'C', 'A'):
            direct_b = [b for b in playable_outfield if b.get('RuoloClassic') == r_code]
            if not direct_b:
                r_starters = [t for t in tits if t.get('Slot_Assegnato') == r_code]
                if r_starters:
                    rem_10 = [t for t in tits if t['Giocatore'] != r_starters[0]['Giocatore']]
                    cov_switch = None
                    for b_cand in playable_outfield:
                        is_ok, new_mod, _ = can_lineup_form_any_valid_classic(rem_10 + [b_cand], preferred_formation=c['Modulo'])
                        if is_ok:
                            cov_switch = {
                                'Slot': r_code,
                                'Titolare': r_starters[0]['Giocatore'],
                                'Subentrante': b_cand['Giocatore'],
                                'Ruolo_Sub': b_cand.get('RuoloClassic', ''),
                                'Nuovo_Modulo': new_mod
                            }
                            break
                    if cov_switch:
                        cambio_modulo_slots.append(cov_switch)
                    else:
                        uncovered.append(r_code)

        c['Slot_Scoperti'] = uncovered
        c['Slot_Coperti_Cambio_Modulo'] = cambio_modulo_slots
        c['Penalita_Fragilita'] = round(len(uncovered) * 1.5, 2)
        c['Punti_Benchmark_Robusto'] = round(c['Punti_Attesi_Totali'] - c['Penalita_Fragilita'], 2)

    candidates = sorted(candidates, key=lambda x: x['Punti_Attesi_Totali'], reverse=True)
    best = candidates[0]
    best['Ha_Problemi_Copertura'] = len(best.get('Slot_Scoperti', [])) > 0

    safe_alts = []
    if best['Ha_Problemi_Copertura']:
        fully_cov = [c for c in candidates[1:] if len(c.get('Slot_Scoperti', [])) == 0]
        for alt in fully_cov[:2]:
            delta = round(alt['Punti_Attesi_Totali'] - best['Punti_Attesi_Totali'], 2)
            safe_alts.append({
                'Modulo': alt['Modulo'],
                'Punti_Totali': alt['Punti_Attesi_Totali'],
                'Delta_Punti': delta,
                'Slot_Scoperti': [],
                'Somma_xFV_Titolari': alt['Somma_xFV_Titolari'],
                'D_Factor': alt['D_Factor_Atteso'],
                'Dettaglio': "Copertura garantita al 100% (diretta o con cambio modulo valido)."
            })
    best['Moduli_Sicuri_Alternativi'] = safe_alts

    best_tit_names = set(p['Giocatore'] for p in best['Titolari'])
    df_bench_cand = df_projected_roster[~df_projected_roster['Giocatore'].isin(best_tit_names)].copy()
    panchina = order_bench_classic_mode(best['Titolari'], df_bench_cand)
    best['Panchina_Prioritizzata'] = panchina
    best['Panchina'] = panchina

    # Generate Classic Departmental Audit Matrix
    audit_tests = []
    for role_code, role_label in [('P', 'Assenza Portiere (P)'), ('D', 'Assenza Difensore (D)'), ('C', 'Assenza Centrocampista (C)'), ('A', 'Assenza Attaccante (A)')]:
        role_tits = [t for t in best['Titolari'] if t.get('Slot_Assegnato') == role_code]
        if role_tits:
            sim = simulate_classic_substitutions(best['Titolari'], panchina, best['Modulo'], simulated_missing_names=[role_tits[0]['Giocatore']])
            sub = sim['Sostituzioni'][0] if sim['Sostituzioni'] else {}
            audit_tests.append({
                'Scenario': role_label,
                'Titolare_Testato': f"{role_tits[0]['Giocatore']} ({role_code})",
                'Giocatore_Subentrante': f"#{sub.get('In_Pos')} {sub.get('In')} ({sub.get('In_Roles')})",
                'Modulo_Risultante': sub.get('Modulo_Nuovo', best['Modulo']),
                'Esito': '✅ Coperto' if ('✅' in sub.get('Status', '') or '🔄' in sub.get('Status', '')) else '❌ Scoperto'
            })
    best['Audit_Copertura'] = pd.DataFrame(audit_tests)

    top_score = best['Punti_Attesi_Totali']
    best['Tutti_Moduli_Valutati'] = [
        {
            'Modulo': c['Modulo'],
            'Punti_Totali': c['Punti_Attesi_Totali'],
            'Delta_vs_Top': round(c['Punti_Attesi_Totali'] - top_score, 2),
            'Stato_Copertura': '✅ Copertura Blindata' if len(c.get('Slot_Scoperti', [])) == 0 else f"⚠️ Scoperti: {', '.join(c.get('Slot_Scoperti', []))}",
            'xFV_Titolari': c['Somma_xFV_Titolari'],
            'D_Factor': c['D_Factor_Atteso'],
            'Punti_Robusti': c['Punti_Benchmark_Robusto'],
        }
        for c in candidates
    ]

    return best


def order_bench_classic_mode(titolari, df_bench_candidates, max_subs=5):
    """Constructs the 12-man bench strictly ordered for Classic mode."""
    df_b = df_bench_candidates.copy()
    bench_scores = []
    prob_voto_bonus = []
    bonus_attesi = []

    for _, row in df_b.iterrows():
        s, p, b = compute_bench_priority_score(row)
        bench_scores.append(s)
        prob_voto_bonus.append(p)
        bonus_attesi.append(b)

    df_b['Score_Panchina'] = bench_scores
    df_b['Prob_Voto6_o_Bonus'] = prob_voto_bonus
    df_b['Bonus_Atteso'] = bonus_attesi
    if 'EV' not in df_b.columns:
        df_b['EV'] = df_b['Score_Panchina']

    por_df = df_b[df_b['RuoloClassic'] == 'P'].sort_values('Score_Panchina', ascending=False)
    outfield_df = df_b[df_b['RuoloClassic'] != 'P'].sort_values('Score_Panchina', ascending=False)

    bench_final = []

    if not por_df.empty:
        p1 = por_df.iloc[0].to_dict()
        p1['Fascia_Master'] = '🧤 2° PORTIERE'
        p1['Note_Tattiche'] = 'Subentra automaticamente solo se il Portiere titolare è S.V.'
        bench_final.append(p1)

    outfield_top5 = outfield_df.head(5)
    for _, row in outfield_top5.iterrows():
        p_copy = row.to_dict()
        p_copy['Fascia_Master'] = '⭐ TOP 5 CAMBIO'
        p_copy['Note_Tattiche'] = f"Priorità cambio (Ruolo Classic: {p_copy.get('RuoloClassic')})."
        bench_final.append(p_copy)

    has_third_por = len(por_df) > 1
    depth_slots = 5 if has_third_por else 6
    outfield_depth = outfield_df.iloc[5:5 + depth_slots]
    for _, row in outfield_depth.iterrows():
        p_copy = row.to_dict()
        p_copy['Fascia_Master'] = '🪑 RINCALZO'
        p_copy['Note_Tattiche'] = f"Subentro di profondità (Ruolo Classic: {p_copy.get('RuoloClassic')})."
        bench_final.append(p_copy)

    if has_third_por and len(bench_final) < 12:
        p3 = por_df.iloc[1].to_dict()
        p3['Fascia_Master'] = '🧤 3° PORTIERE'
        p3['Note_Tattiche'] = 'Copertura di emergenza estrema per la porta.'
        bench_final.append(p3)

    for idx, b in enumerate(bench_final):
        b['Posizione_Panchina'] = idx + 1
        rc = b.get('RuoloClassic', '')
        b['Copertura_Tattica'] = f"Ruolo Classic: {rc}"

    return bench_final


def can_lineup_form_any_valid_classic(players_list):
    """Checks if 11 players can form any of the 7 Classic formations."""
    if len(players_list) != 11:
        return False, None

    counts = {'P': 0, 'D': 0, 'C': 0, 'A': 0}
    for p in players_list:
        rc = p.get('RuoloClassic', '')
        if rc in counts:
            counts[rc] += 1
        elif 'Por' in str(p.get('RuoloMantra', '')):
            counts['P'] += 1
        elif any(r in str(p.get('RuoloMantra', '')) for r in ['Dc', 'Dd', 'Ds', 'B']):
            counts['D'] += 1
        elif any(r in str(p.get('RuoloMantra', '')) for r in ['A', 'Pc']):
            counts['A'] += 1
        else:
            counts['C'] += 1

    if counts['P'] != 1:
        return False, None

    tuple_dca = (counts['D'], counts['C'], counts['A'])
    lookup = {
        (3, 4, 3): '3-4-3',
        (3, 5, 2): '3-5-2',
        (4, 3, 3): '4-3-3',
        (4, 4, 2): '4-4-2',
        (4, 5, 1): '4-5-1',
        (5, 3, 2): '5-3-2',
        (5, 4, 1): '5-4-1'
    }
    if tuple_dca in lookup:
        return True, lookup[tuple_dca]
    return False, None


def simulate_classic_substitutions(titolari, panchina, initial_formation, max_subs=5, simulated_missing_names=None):
    """Simulates substitutions for Classic mode."""
    if simulated_missing_names is None:
        simulated_missing_names = []

    missing_set = set(simulated_missing_names)
    current_field = [dict(t) for t in titolari]
    subs_made = []
    bench_used = set()
    current_mod = initial_formation

    # 1. Missing Goalkeeper
    por_missing = [p for p in titolari if p['Giocatore'] in missing_set and p.get('RuoloClassic') == 'P']
    for p_out in por_missing:
        sub_ok = False
        for b_idx, b in enumerate(panchina):
            if b_idx in bench_used:
                continue
            if b.get('RuoloClassic') == 'P':
                bench_used.add(b_idx)
                current_field = [p if p['Giocatore'] != p_out['Giocatore'] else b for p in current_field]
                subs_made.append({
                    'Out': p_out['Giocatore'],
                    'Out_Slot': 'P',
                    'In': b['Giocatore'],
                    'In_Pos': b_idx + 1,
                    'In_Roles': 'P',
                    'In_Fascia': b.get('Fascia_Master', ''),
                    'Modulo_Nuovo': current_mod,
                    'Status': '✅ CAMBIO EFFETTUATO',
                    'Dettaglio': f"Subentra il 2° portiere (Panchina #{b_idx+1}) mantenendo invariato il modulo {current_mod}."
                })
                sub_ok = True
                break
        if not sub_ok:
            subs_made.append({
                'Out': p_out['Giocatore'],
                'Out_Slot': 'P',
                'In': 'NESSUN PORTIERE A VOTO',
                'In_Pos': '-',
                'In_Roles': '-',
                'In_Fascia': '-',
                'Modulo_Nuovo': current_mod,
                'Status': '❌ PORTA SCOPERTA',
                'Dettaglio': 'Nessun portiere di riserva disponibile a voto.'
            })

    # 2. Missing Outfield
    outfield_missing = [p for p in titolari if p['Giocatore'] in missing_set and p.get('RuoloClassic') != 'P']
    for p_out in outfield_missing:
        if len(subs_made) >= max_subs:
            subs_made.append({
                'Out': p_out['Giocatore'],
                'Out_Slot': p_out.get('RuoloClassic', 'D'),
                'In': 'LIMITE 5 CAMBI RAGGIUNTO',
                'In_Pos': '-',
                'In_Roles': '-',
                'In_Fascia': '-',
                'Modulo_Nuovo': current_mod,
                'Status': '⚠️ CAMBI ESAURITI',
                'Dettaglio': f'Raggiunto il tetto massimo di {max_subs} sostituzioni consentite.'
            })
            continue

        target_rc = p_out.get('RuoloClassic', '')
        sub_ok = False
        for b_idx, b in enumerate(panchina):
            if b_idx in bench_used:
                continue
            if b.get('RuoloClassic') == target_rc:
                bench_used.add(b_idx)
                current_field = [p if p['Giocatore'] != p_out['Giocatore'] else b for p in current_field]
                subs_made.append({
                    'Out': p_out['Giocatore'],
                    'Out_Slot': target_rc,
                    'In': b['Giocatore'],
                    'In_Pos': b_idx + 1,
                    'In_Roles': target_rc,
                    'In_Fascia': b.get('Fascia_Master', ''),
                    'Modulo_Nuovo': current_mod,
                    'Status': '✅ CAMBIO DIRETTO RUOLO',
                    'Dettaglio': f"Sostituzione diretta ruolo su ruolo ({target_rc} ➔ {target_rc}). Modulo {current_mod} preservato."
                })
                sub_ok = True
                break

        if not sub_ok:
            for b_idx, b in enumerate(panchina):
                if b_idx in bench_used or b.get('RuoloClassic') == 'P':
                    continue
                test_field = [p if p['Giocatore'] != p_out['Giocatore'] else b for p in current_field]
                can_f, new_mod = can_lineup_form_any_valid_classic(test_field)
                if can_f:
                    bench_used.add(b_idx)
                    current_field = test_field
                    current_mod = new_mod
                    subs_made.append({
                        'Out': p_out['Giocatore'],
                        'Out_Slot': target_rc,
                        'In': b['Giocatore'],
                        'In_Pos': b_idx + 1,
                        'In_Roles': b.get('RuoloClassic', ''),
                        'In_Fascia': b.get('Fascia_Master', ''),
                        'Modulo_Nuovo': new_mod,
                        'Status': '🔄 CAMBIO CON CAMBIO MODULO',
                        'Dettaglio': f"Subentra {b.get('RuoloClassic')} ({b['Giocatore']}) adattando la disposizione tattica al modulo {new_mod}."
                    })
                    sub_ok = True
                    break

        if not sub_ok:
            subs_made.append({
                'Out': p_out['Giocatore'],
                'Out_Slot': target_rc,
                'In': 'NESSUNA RISERVA UTILE',
                'In_Pos': '-',
                'In_Roles': '-',
                'In_Fascia': '-',
                'Modulo_Nuovo': current_mod,
                'Status': '❌ INFERIORITÀ NUMERICA',
                'Dettaglio': f"Nessun calciatore disponibile in panchina in grado di coprire il ruolo {target_rc} o configurare un modulo Classic valido."
            })

    success_count = sum(1 for s in subs_made if 'CAMBIO' in s.get('Status', ''))
    return {
        'Modulo_Partenza': initial_formation,
        'Modulo_Finale': current_mod,
        'Cambi_Effettuati': success_count,
        'Sostituzioni': subs_made
    }


def optimize_best_lineup(df_projected_roster, allowed_formations=None, mode='mantra'):
    """Universal dispatcher for Mantra or Classic lineup optimization."""
    if str(mode).lower() == 'classic':
        return optimize_best_classic_lineup(df_projected_roster, allowed_formations=allowed_formations)
    return optimize_best_mantra_lineup(df_projected_roster, allowed_formations=allowed_formations)
