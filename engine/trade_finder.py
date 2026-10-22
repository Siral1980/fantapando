"""
Trade Finder & Squad Weakness Diagnostic Engine for Fantacalcio Mantra.
Analyzes roster structural bottlenecks, departmental depth, and D-Factor exposure,
and identifies win-win trade opportunities across all opposing fantasy managers in the league.
"""

import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.optimizer import parse_mantra_roles, optimize_best_mantra_lineup, solve_lineup_for_formation
from engine.models import batch_predict_xfv, predict_player_xfv


def safe_int(val, default=0):
    try:
        if val is None or pd.isna(val):
            return default
        return int(float(val))
    except Exception:
        return default

def safe_float(val, default=0.0):
    try:
        if val is None or pd.isna(val):
            return default
        return float(val)
    except Exception:
        return default


# Ideal role quotas for a balanced 25-30 player Mantra squad
RECOMMENDED_QUOTAS = {
    'Por': {'min_active': 2, 'target': 3, 'name': 'Portieri'},
    'Dc':  {'min_active': 4, 'target': 6, 'name': 'Difensori Centrali'},
    'B':   {'min_active': 1, 'target': 2, 'name': 'Braccetti Difesa a 3'},
    'Dd':  {'min_active': 2, 'target': 3, 'name': 'Terzini Destri'},
    'Ds':  {'min_active': 2, 'target': 3, 'name': 'Terzini Sinistri'},
    'E':   {'min_active': 3, 'target': 4, 'name': 'Esterni a tutta fascia'},
    'M':   {'min_active': 3, 'target': 5, 'name': 'Mediani (Slot M Obbligatorio)'},
    'C':   {'min_active': 4, 'target': 6, 'name': 'Centrocampisti / Mezzali'},
    'W':   {'min_active': 2, 'target': 4, 'name': 'Ali Offensive'},
    'T':   {'min_active': 2, 'target': 3, 'name': 'Trequartisti'},
    'A':   {'min_active': 2, 'target': 4, 'name': 'Seconde Punte'},
    'Pc':  {'min_active': 3, 'target': 5, 'name': 'Punte Centrali'}
}


def compute_real_starter_status(row, tot_matchdays=7):
    """
    Classifies a Serie A player based on real match minutes and continuous usage:
    - TITOLARE: Primary undisputed starter (>= 55 min/app AND >= 45% team minutes, or >= 68 min/app with >= 3 apps)
    - CO_TITOLARE: Solid regular rotation / staffetta (>= 45 min/app AND >= 28% team minutes, e.g. Scamacca, Cutrone)
    - SUPER_SUB: Regular impactful substitute with elite creation rates (xG90 + xA90 >= 0.35, e.g. Neres, Simeone)
    - SUBENTRANTE: Late substitute / bench warmer (< 45 min/app or < 28% team minutes, e.g. Lucca, Nzola, Kevin Carlos, Beto)
    - MARGINALE: Rare or zero appearances (< 2 apps or < 70 min total)
    """
    if not isinstance(row, dict):
        row = {}
    pres = safe_float(row.get('Presenze', 0))
    mins = safe_float(row.get('Minuti_Reali', 0))
    tot_mins = tot_matchdays * 90.0
    
    m_per_app = (mins / pres) if pres > 0 else 0.0
    pct_mins = (mins / tot_mins * 100.0) if tot_mins > 0 else 0.0
    pct_suff = safe_float(row.get('Pct_Sufficienza', 50.0))
    
    xg_90 = safe_float(row.get('xG_90_Regressed', row.get('xG_90', 0.0)))
    xa_90 = safe_float(row.get('xA_90_Regressed', row.get('xA_90', 0.0)))
    burst_rate = xg_90 + xa_90
    roles_str = str(row.get('RuoloMantra', ''))
    
    if (m_per_app >= 55.0 and pct_mins >= 45.0) or (m_per_app >= 68.0 and pres >= 3) or pct_mins >= 65.0:
        return {
            'Status': 'TITOLARE',
            'Badge': '🟢 TITOLARE FISSO',
            'Label': f'🟢 Titolare ({int(m_per_app)} min/p)',
            'Min_Per_Pres': round(m_per_app, 1),
            'Pct_Minuti': round(pct_mins, 1),
            'Tier_Weight': 1.0,
            'Is_Real_Starter': True,
            'Is_Super_Sub': False
        }
    elif (m_per_app >= 45.0 and pct_mins >= 28.0) or (m_per_app >= 40.0 and pres >= 4 and pct_mins >= 24.0 and pct_suff >= 40.0):
        return {
            'Status': 'CO_TITOLARE',
            'Badge': '🟡 CO-TITOLARE',
            'Label': f'🟡 Co-Titolare ({int(m_per_app)} min/p)',
            'Min_Per_Pres': round(m_per_app, 1),
            'Pct_Minuti': round(pct_mins, 1),
            'Tier_Weight': 0.75,
            'Is_Real_Starter': True,
            'Is_Super_Sub': False
        }
    elif pres >= 2 and mins >= 50:
        if burst_rate >= 0.35 and not 'Por' in roles_str:
            return {
                'Status': 'SUPER_SUB',
                'Badge': '⚡ JOLLY / SUPER-SUB',
                'Label': f'⚡ Super-Sub ({int(m_per_app)} min/p, {xg_90:.2f} xG/90)',
                'Min_Per_Pres': round(m_per_app, 1),
                'Pct_Minuti': round(pct_mins, 1),
                'Tier_Weight': 0.55,
                'Is_Real_Starter': False,
                'Is_Super_Sub': True
            }
        return {
            'Status': 'SUBENTRANTE',
            'Badge': '🟠 SUBENTRANTE',
            'Label': f'🟠 Subentrante ({int(m_per_app)} min/p)',
            'Min_Per_Pres': round(m_per_app, 1),
            'Pct_Minuti': round(pct_mins, 1),
            'Tier_Weight': 0.35,
            'Is_Real_Starter': False,
            'Is_Super_Sub': False
        }
    else:
        return {
            'Status': 'MARGINALE',
            'Badge': '🔴 MARGINALE',
            'Label': '🔴 Riserva Marginale',
            'Min_Per_Pres': round(m_per_app, 1),
            'Pct_Minuti': round(pct_mins, 1),
            'Tier_Weight': 0.10,
            'Is_Real_Starter': False,
            'Is_Super_Sub': False
        }


def compute_continuous_trade_value(player_dict, tot_matchdays=7):
    """
    Computes a continuous, objective market trade value based on:
    1. Base Long-Term Asset Value (blending season FM, MV, and model xFV).
    2. Continuous Playing Time & Starting Status Index (I_Tit in [0.12, 1.00])
       derived from real Serie A match minutes, appearances, and minutes-per-appearance.
    3. Underlying Expected Production:
       - Proven Volume: xG_Tot and xA_Tot (rewards consistent season-long chance generation).
       - Rate: Regressed xG_90 and xA_90 with Bayesian shrinkage on small samples (< 270 mins).
       - Super-Sub Upside: Recognizes game-changers (burst_rate >= 0.35) with elevated market liquidity.
    4. Buy-Low / Sell-High Delta_xG regression adjustment.
    5. Role Scarcity Factor (Mantra role hierarchy: Pc/A > W/T > Dd/Ds > M/C/E/D/Por).
    """
    raw_xfv = safe_float(player_dict.get('xFV', player_dict.get('FM_Stagione', 0.0)))
    fm_stag = safe_float(player_dict.get('FM_Stagione', 0.0))
    mv_stag = safe_float(player_dict.get('MV_Stagione', 6.0))
    pres = safe_float(player_dict.get('Presenze', 0))
    mins = safe_float(player_dict.get('Minuti_Reali', 0))
    roles = parse_mantra_roles(player_dict.get('RuoloMantra', ''))
    
    # Long-term baseline: avoids single-fixture distortion in permanent trades
    if fm_stag > 0:
        base_val = (0.55 * fm_stag) + (0.45 * raw_xfv)
    else:
        base_val = raw_xfv
        
    tot_team_mins = tot_matchdays * 90.0
    m_per_app = (mins / pres) if pres > 0 else 0.0
    pct_mins = (mins / tot_team_mins) if tot_team_mins > 0 else 0.0
    
    is_gk = ('Por' in roles)
    
    if is_gk:
        if pres >= 3 or safe_float(player_dict.get('P_Voto', 0)) >= 0.70:
            i_tit = 1.0
        elif pres >= 1:
            i_tit = 0.55
        else:
            i_tit = 0.30
    else:
        if pres >= 2:
            m_factor = min(1.0, m_per_app / 65.0)
            t_factor = min(1.0, pct_mins / 0.45)
            i_tit = float(np.clip(0.20 + 0.80 * (m_factor * 0.55 + t_factor * 0.45), 0.20, 1.0))
        elif pres == 1:
            i_tit = float(np.clip(0.15 + 0.35 * (mins / 90.0), 0.15, 0.45))
        else:
            i_tit = 0.12

    # Bayesian shrinkage on underlying per-90 rates (stabilization threshold 270 minutes ~ 3 games)
    is_striker = any(r in ['Pc', 'A'] for r in roles)
    is_w_or_t = any(r in ['W', 'T'] for r in roles)
    prior_xg90 = 0.32 if is_striker else (0.16 if is_w_or_t else 0.04)
    prior_xa90 = 0.18 if is_w_or_t else (0.10 if is_striker or 'C' in roles else 0.03)

    w_mins = mins / (mins + 270.0) if mins > 0 else 0.0
    raw_xg90 = safe_float(player_dict.get('xG_90', 0.0))
    raw_xa90 = safe_float(player_dict.get('xA_90', 0.0))
    reg_xg90 = (w_mins * raw_xg90) + ((1.0 - w_mins) * prior_xg90)
    reg_xa90 = (w_mins * raw_xa90) + ((1.0 - w_mins) * prior_xa90)

    xg_tot = safe_float(player_dict.get('xG_Tot', 0.0))
    xa_tot = safe_float(player_dict.get('xA_Tot', 0.0))
    delta_xg = safe_float(player_dict.get('Delta_xG', 0.0))

    # Super-Sub Recognition: elevate effective playing time for explosive game-changers
    if not is_gk and i_tit < 0.65 and (reg_xg90 + reg_xa90) >= 0.35 and pres >= 2:
        i_tit = min(0.80, i_tit + 0.18)

    # Underlying production value-add
    prod_boost = 0.0
    if is_striker or is_w_or_t:
        prod_boost = (min(3.5, xg_tot) * 0.10) + (min(2.5, xa_tot) * 0.06) + (reg_xg90 * 0.20) + (reg_xa90 * 0.12)
    elif 'C' in roles or 'E' in roles:
        prod_boost = (min(2.0, xg_tot) * 0.06) + (min(2.0, xa_tot) * 0.08) + (reg_xa90 * 0.15)

    # Buy-Low / Sell-High regression adjustment:
    # Buy-low players (ΔxG < -1.5) are undervalued by market; Sell-high (ΔxG > +2.0) carry negative reversion risk
    reversion_adj = 0.0
    if delta_xg <= -1.5:
        reversion_adj = +0.25  # Hidden intrinsic value upside
    elif delta_xg >= +2.0:
        reversion_adj = -0.20  # Risk of cold streak regression

    # Role Scarcity Multiplier (Goals and strikers are rarest and most decisive)
    if is_striker:
        w_role = 1.15
    elif is_w_or_t:
        w_role = 1.08
    elif any(r in ['Dd', 'Ds'] for r in roles):
        w_role = 1.03
    else:
        w_role = 1.00

    effective_val = (base_val + prod_boost + reversion_adj) * (0.28 + 0.72 * i_tit) * w_role
    return {
        'raw_xfv': round(raw_xfv, 2),
        'base_val': round(base_val, 2),
        'i_tit': round(i_tit, 2),
        'm_per_app': round(m_per_app, 1),
        'pct_mins': round(pct_mins * 100.0, 1),
        'reg_xg90': round(reg_xg90, 2),
        'reg_xa90': round(reg_xa90, 2),
        'w_role': round(w_role, 2),
        'effective_val': round(effective_val, 2)
    }


def evaluate_pairwise_trade_balance(give_pkg, target_pkg, tot_matchdays=7):
    """
    Evaluates multi-player trades via continuous Pairwise Ranking Matching (Vasi Comunicanti):
    1. Computes continuous effective market value for each player.
    2. Sorts give_pkg and target_pkg in descending order of effective value.
    3. Matches pairs:
       - Pair 1 (Anchors): Give[0] vs Target[0] -> delta_1 = Val(Give[0]) - Val(Target[0])
       - Pair 2 (Complements): Give[1] vs Target[1] -> delta_2 = Val(Give[1]) - Val(Target[1])
    4. Validates the Vasi Comunicanti balance:
       - If Pair 1 is balanced (delta_1 ~ 0), Pair 2 CANNOT have a severe deficit (cannot give a bench player for a starter)!
       - A deficit in secondary pairs is ONLY allowed if the primary anchor provides an equal or greater surplus!
       - In 1x2 (Give 1, Ask 2): The single given piece MUST have an effective value that covers the extra target player.
    """
    give_evals = [{**p, **compute_continuous_trade_value(p, tot_matchdays)} for p in give_pkg]
    target_evals = [{**p, **compute_continuous_trade_value(p, tot_matchdays)} for p in target_pkg]
    
    give_sorted = sorted(give_evals, key=lambda x: x['effective_val'], reverse=True)
    target_sorted = sorted(target_evals, key=lambda x: x['effective_val'], reverse=True)
    
    give_tot_eff = sum(p['effective_val'] for p in give_sorted)
    target_tot_eff = sum(p['effective_val'] for p in target_sorted)
    
    n_give = len(give_sorted)
    n_target = len(target_sorted)
    min_len = min(n_give, n_target)
    
    pairwise_pairs = []
    surplus_pool = 0.0
    is_valid = True
    rejection_reason = ""
    has_primary_starter = any(p['i_tit'] >= 0.65 for p in give_sorted)

    for i in range(min_len):
        g = give_sorted[i]
        t = target_sorted[i]
        d = g['effective_val'] - t['effective_val']
        pairwise_pairs.append({
            'give_name': g['Giocatore'],
            'give_val': g['effective_val'],
            'give_itit': g['i_tit'],
            'give_mins': g.get('m_per_app', 0),
            'target_name': t['Giocatore'],
            'target_val': t['effective_val'],
            'target_itit': t['i_tit'],
            'target_mins': t.get('m_per_app', 0),
            'delta': round(d, 2)
        })
        
        # Titolarità Asymmetry check:
        # If user offers ONLY benchwarmers/subentranti (no starting-caliber player at all) for top starters:
        if not has_primary_starter and t['i_tit'] >= 0.70:
            is_valid = False
            rejection_reason = (
                f"Nessun titolare offerto: proponi solo riserve/subentranti a fronte di titolari fissi richiesti."
            )
            break
        
        surplus_pool += d

    if is_valid:
        # Multi-target value floor: effective value must reach at least 65% of target value
        if target_tot_eff > 0 and (give_tot_eff / target_tot_eff) < 0.65:
            is_valid = False
            rejection_reason = (
                f"Valore complessivo offerto ({give_tot_eff:.2f}) troppo distante da quello richiesto ({target_tot_eff:.2f})."
            )
        elif n_target > n_give:
            # In 1x2 (give 1, ask 2): single given player must be of high caliber (not a bench piece)
            if not has_primary_starter or give_tot_eff < (target_tot_eff * 0.60):
                is_valid = False
                rejection_reason = (
                    f"Richiesta 1x2 insostenibile: il tuo pezzo principale ({give_sorted[0]['Giocatore']}) "
                    f"non genera valore sufficiente per richiedere un pacchetto multiplo."
                )

    return {
        'is_valid': is_valid,
        'rejection_reason': rejection_reason,
        'give_tot_eff': round(give_tot_eff, 2),
        'target_tot_eff': round(target_tot_eff, 2),
        'delta_eff': round(give_tot_eff - target_tot_eff, 2),
        'pairwise_pairs': pairwise_pairs
    }


def get_league_release_names(league_data):
    """
    Returns a set of all player names flagged as 'FuoriSerieA' or 'Da_Svincolare'
    (or marked with '*' in the official league roster export).
    These players must NEVER be proposed or accepted in trades.
    """
    release_names = set()
    if not league_data or not isinstance(league_data, dict):
        return release_names
    for team, players in league_data.items():
        if isinstance(players, list):
            for p in players:
                if isinstance(p, dict):
                    if (
                        p.get('FuoriSerieA', False) or 
                        p.get('Da_Svincolare', False) or 
                        '*' in str(p.get('NomeGrezzo', '')) or 
                        '*' in str(p.get('Giocatore', ''))
                    ):
                        g_clean = str(p.get('Giocatore', '')).replace('*', '').strip()
                        raw_clean = str(p.get('NomeGrezzo', '')).replace('*', '').strip()
                        if g_clean:
                            release_names.add(g_clean)
                        if raw_clean:
                            release_names.add(raw_clean)
    return release_names


def is_player_to_release(p, release_names=None):
    """Helper to check if a player dict or player name is marked as out of Serie A / to be released."""
    if isinstance(p, str):
        g = p.replace('*', '').strip()
        if '*' in p:
            return True
        if release_names and g in release_names:
            return True
        return False
    if not isinstance(p, dict):
        return False
    if p.get('FuoriSerieA', False) or p.get('Da_Svincolare', False):
        return True
    g = str(p.get('Giocatore', '')).replace('*', '').strip()
    raw = str(p.get('NomeGrezzo', '')).replace('*', '').strip()
    if '*' in str(p.get('NomeGrezzo', '')) or '*' in str(p.get('Giocatore', '')):
        return True
    if release_names and (g in release_names or raw in release_names):
        return True
    return False


def analyze_squad_weaknesses(team_name, league_data, df_master, matchday=8):
    """
    Performs a deep diagnostic analysis of a fantasy team's roster:
    1. Evaluates departmental depth vs recommended Mantra quotas (filtering by active players).
    2. Measures starting quality (xFV), sufficiency reliability (D-Factor impact), and bonus threat.
    3. Identifies critical bottlenecks (Punti Deboli) and structural surpluses (Asset di Scambio).
    """
    if team_name not in league_data:
        return {'error': f"Squadra '{team_name}' non trovata nella lega."}

    release_names = get_league_release_names(league_data)
    team_players_all = league_data[team_name]
    # For market/trade analysis, only consider owned assets (Costo > 0, not temporary loans from other clubs)
    # and exclude players marked as out of Serie A / to be released
    team_players = [
        p for p in team_players_all 
        if not p.get('InPrestito', False) and p.get('Costo', 1) > 0 and not is_player_to_release(p, release_names)
    ]
    player_names = [p['Giocatore'] for p in team_players]
    
    df_squad = df_master[df_master['Giocatore'].isin(player_names)].copy()
    if df_squad.empty:
        return {'error': "Nessun calciatore della squadra trovato nel database master."}

    cost_lookup = {p['Giocatore']: safe_int(p.get('Costo', 1), default=1) for p in team_players if isinstance(p, dict) and 'Giocatore' in p}
    df_squad['Costo'] = df_squad['Giocatore'].map(cost_lookup).fillna(1).astype(int)

    # Project squad performance for the target matchday
    df_proj = batch_predict_xfv(df_squad, matchday=matchday)
    
    # Identify optimal lineup and starters
    opt_res = optimize_best_mantra_lineup(df_proj)
    starters = opt_res['Titolari'] if opt_res else []
    starter_names = set(p['Giocatore'] for p in starters)

    # 1. Count Mantra roles across the roster (distinguishing total vs active players)
    role_roster_all = {r: [] for r in RECOMMENDED_QUOTAS.keys()}
    role_roster_active = {r: [] for r in RECOMMENDED_QUOTAS.keys()}
    
    for _, row in df_proj.iterrows():
        p_roles = parse_mantra_roles(row.get('RuoloMantra', ''))
        is_active = (row.get('Presenze', 0) >= 2 or row.get('P_Voto', 0) >= 0.50)
        for r in p_roles:
            if r in role_roster_all:
                role_roster_all[r].append(row)
                if is_active:
                    role_roster_active[r].append(row)

    # 2. Diagnose weaknesses and bottlenecks
    weaknesses = []
    strengths = []
    
    # Check Goalkeeper Department
    pors = role_roster_all['Por']
    por_starters = [p for p in pors if p.get('Presenze', 0) >= 3]
    teams_with_gk = set(p.get('Squadra') for p in pors)
    has_paired_gk = any(sum(1 for p in pors if p.get('Squadra') == sq) >= 2 for sq in teams_with_gk)
    top_gk = max(pors, key=lambda p: safe_float(p.get('Presenze', 0))) if pors else None
    
    if len(pors) < 3:
        weaknesses.append({
            'Reparto': 'Porta',
            'Ruolo': 'Por',
            'Severita': 'ELEVATA',
            'Titolo': 'Reparto Portieri numericamente incompleto',
            'Diagnosi': f"Hai solo {len(pors)} portieri in rosa (consigliati 3). Rischio concreto di rimanere scoperti in caso di infortunio o squalifica.",
            'Obiettivo_Mercato': 'Ingaggiare un secondo o terzo portiere di ruolo'
        })
    elif not has_paired_gk:
        weaknesses.append({
            'Reparto': 'Porta',
            'Ruolo': 'Por',
            'Severita': 'MEDIA',
            'Titolo': 'Manca la coppia di club per il portiere titolare',
            'Diagnosi': f"I tuoi portieri ({', '.join(set(p.get('Squadra') for p in pors))}) provengono da club diversi senza la riserva ufficiale garantita. Conviene acquisire il 2° portiere della tua squadra titolare per blindare la porta.",
            'Obiettivo_Mercato': 'Scambiare per la riserva ufficiale del tuo club titolare'
        })
    else:
        strengths.append(f"Porta blindata: hai la coppia di portieri dello stesso club.")

    # Advanced Goalkeeper Performance & Blunder Diagnostic
    if top_gk is not None and safe_float(top_gk.get('Presenze', 0)) >= 2:
        gk_name = top_gk['Giocatore']
        gk_gp = safe_float(top_gk.get('Goals_Prevented', 0.0))
        gk_gp90 = safe_float(top_gk.get('Goals_Prevented_90', 0.0))
        gk_blunders = safe_int(top_gk.get('Errors_Leading_To_Goal', 0))
        gk_save_pct = safe_float(top_gk.get('Pct_Parate', 70.0))
        
        if gk_gp <= -1.0 or gk_gp90 <= -0.20:
            weaknesses.append({
                'Reparto': 'Porta',
                'Ruolo': 'Por',
                'Severita': 'CRITICA' if gk_gp < -2.5 else 'ELEVATA',
                'Titolo': f'Sotto-performance Shot-Stopping ({gk_name}: {gk_gp:+.2f} Goals Prevented)',
                'Diagnosi': f"Il tuo portiere titolare ({gk_name}) concede più gol di quanti attesi dai tiri nello specchio subiti ({gk_gp:+.2f} gol evitati, {gk_gp90:+.2f}/90, parate {gk_save_pct:.1f}%). Concede costantemente malus evitabili.",
                'Obiettivo_Mercato': "Scambiare per un portiere salva-risultato (es. Carnesecchi, Mandas, Caprile, Falcone)"
            })
        elif gk_blunders >= 1:
            weaknesses.append({
                'Reparto': 'Porta',
                'Ruolo': 'Por',
                'Severita': 'ELEVATA' if gk_blunders >= 2 else 'MEDIA',
                'Titolo': f'Rischio papere e voti gravi ({gk_name}: {gk_blunders} errori decisivi)',
                'Diagnosi': f"Il tuo portiere titolare ({gk_name}) ha commesso {gk_blunders} errori gravi non forzati che hanno provocato direttamente gol con voti <= 5.0.",
                'Obiettivo_Mercato': 'Puntare a un portiere affidabile con 0 blunders stagionali'
            })
        elif gk_gp >= +2.5 and gk_blunders == 0:
            strengths.append(f"Porta di ferro: {gk_name} registra {gk_gp:+.2f} Goals Prevented ({gk_gp90:+.2f}/90) e zero errori gravi, neutralizzando i gol avversari.")

    # Check Central Defense (Dc & D-Factor)
    dcs = role_roster_active['Dc']
    dc_suff_avg = np.mean([p.get('Pct_Sufficienza', 50) for p in dcs]) if dcs else 0
    top_dc_mv = max([p.get('MV_Stagione', 0) for p in dcs]) if dcs else 0
    if len(dcs) < 4:
        weaknesses.append({
            'Reparto': 'Difesa Centrale',
            'Ruolo': 'Dc',
            'Severita': 'CRITICA',
            'Titolo': 'Numero insufficiente di Difensori Centrali attivi (Dc)',
            'Diagnosi': f"Solo {len(dcs)} Dc attivi con voto in rosa. Impossibile sostenere continuativamente moduli con difesa a 3 (3-5-2, 3-4-2-1) o a 4 senza rischiare penalità di cambio.",
            'Obiettivo_Mercato': 'Acquisire almeno 1-2 Dc titolari'
        })
    elif dc_suff_avg < 60.0 or top_dc_mv < 6.15:
        weaknesses.append({
            'Reparto': 'Difesa Centrale',
            'Ruolo': 'Dc',
            'Severita': 'MEDIA',
            'Titolo': 'Manca un top Dc per dominare il D-Factor (Modificatore Difesa)',
            'Diagnosi': f"La tua difesa centrale è regolare (sufficienza media {dc_suff_avg:.1f}%), ma manca un vero leader difensivo da MV >= 6.30 che garantisca i bonus massimi (+2/+3 pt) del D-Factor.",
            'Obiettivo_Mercato': 'Puntare a un Dc top di vertice (es. Buongiorno, Bastoni, Ndicka)'
        })
    else:
        strengths.append(f"Difesa Centrale solida: {len(dcs)} Dc attivi con sufficienza media al {dc_suff_avg:.1f}%.")

    # Check Fullbacks (Dd & Ds)
    dds = role_roster_active['Dd']
    dss = role_roster_active['Ds']
    if len(dds) < 2:
        weaknesses.append({
            'Reparto': 'Terzini Destri',
            'Ruolo': 'Dd',
            'Severita': 'ELEVATA',
            'Titolo': 'Carenza sul binario destro difensivo (Dd)',
            'Diagnosi': f"Hai solo {len(dds)} Dd attivi in rosa. Questo limita fortemente la flessibilità tattica verso moduli con difesa a 4 (4-3-3, 4-4-2, 4-2-3-1).",
            'Obiettivo_Mercato': 'Cercare un terzino destro (Dd) titolare fisso'
        })
    if len(dss) < 2:
        weaknesses.append({
            'Reparto': 'Terzini Sinistri',
            'Ruolo': 'Ds',
            'Severita': 'ELEVATA',
            'Titolo': 'Carenza sul binario sinistro difensivo (Ds)',
            'Diagnosi': f"Hai solo {len(dss)} Ds attivi in rosa. Copertura fragile per le formazioni a 4 difensori.",
            'Obiettivo_Mercato': 'Cercare un terzino sinistro (Ds) titolare'
        })
    if len(dds) >= 2 and len(dss) >= 2:
        strengths.append(f"Corsie difensive coperte: {len(dds)} Dd e {len(dss)} Ds consentono di schierare sia difesa a 3 che a 4.")

    # Check Wing-backs (E)
    es = role_roster_active['E']
    if len(es) < 3:
        weaknesses.append({
            'Reparto': 'Esterni a tutta fascia',
            'Ruolo': 'E',
            'Severita': 'MEDIA',
            'Titolo': 'Pochi esterni puri (E) per moduli a 3',
            'Diagnosi': f"Solo {len(es)} esterni a tutta fascia attivi. Se giochi col 3-5-2 o 3-4-2-1 hai pochi ricambi di ruolo.",
            'Obiettivo_Mercato': 'Cercare un esterno E con propensione al bonus'
        })
    elif len(es) >= 4:
        strengths.append(f"Fasce a tutta altezza presidiate: {len(es)} E disponibili per i moduli a 3.")

    # Check Medians (M - Mandatory slot in almost all Mantra formations)
    ms = role_roster_active['M']
    m_starters = [p for p in ms if p.get('P_Voto', 0) >= 0.70]
    top_m_fm = max([p.get('FM_Stagione', 0) for p in ms]) if ms else 0
    if len(ms) < 3:
        weaknesses.append({
            'Reparto': 'Centrocampo Mediani',
            'Ruolo': 'M',
            'Severita': 'CRITICA',
            'Titolo': 'Allarme Mediani (M) - Slot Obbligatorio a rischio',
            'Diagnosi': f"Hai solo {len(ms)} Mediani (M) in rosa. Lo slot M è tassativo nel 3-5-2, 4-3-3, 4-4-2, 4-3-1-2. Senza un M a voto si rischia di giocare in inferiorità numerica.",
            'Obiettivo_Mercato': 'Acquisire con priorità assoluta un Mediano M titolare'
        })
    elif top_m_fm < 6.4:
        weaknesses.append({
            'Reparto': 'Centrocampo Mediani',
            'Ruolo': 'M',
            'Severita': 'MEDIA',
            'Titolo': 'Mediani regolari ma privi di bonus pesanti',
            'Diagnosi': f"I tuoi mediani ({len(ms)} M) assicurano copertura tattica ma hanno un fanta-valore atteso moderato (FM max {top_m_fm:.2f}). Un M incursore o rigorista farebbe fare il salto di qualità.",
            'Obiettivo_Mercato': 'Puntare a un Mediano M di prima fascia con bonus (es. Calhanoglu, Ederson, McTominay)'
        })
    if len(ms) >= 6:
        strengths.append(f"Abbondanza di Mediani (M): {len(ms)} M attivi in rosa, ottima moneta di scambio per squadre scoperte.")

    # Check Central Midfielders (C - Mezzali / Costruttori)
    cs = role_roster_active['C']
    top_c_fm = max([p.get('FM_Stagione', 0) for p in cs]) if cs else 0
    if len(cs) < 3:
        weaknesses.append({
            'Reparto': 'Centrocampo (Mezzali)',
            'Ruolo': 'C',
            'Severita': 'ELEVATA',
            'Titolo': 'Carenza di Centrocampisti puri / Mezzali (C)',
            'Diagnosi': f"Hai solo {len(cs)} C attivi in rosa. Molti moduli Mantra (3-5-2, 4-3-3, 4-3-1-2) richiedono da 1 a 2 slot C.",
            'Obiettivo_Mercato': 'Acquisire un Centrocampista C titolare di inserimento'
        })
    elif top_c_fm < 6.4:
        weaknesses.append({
            'Reparto': 'Centrocampo (Mezzali)',
            'Ruolo': 'C',
            'Severita': 'MEDIA',
            'Titolo': 'Centrocampisti C con fanta-media modesta',
            'Diagnosi': f"I tuoi centrocampisti C hanno una fanta-media moderata (FM max {top_c_fm:.2f}). Una mezzala da bonus farebbe fare il salto di qualità.",
            'Obiettivo_Mercato': 'Puntare a un Centrocampista C di prima fascia con bonus'
        })
    elif len(cs) >= 5:
        strengths.append(f"Centrocampo profondo: {len(cs)} C attivi a disposizione.")

    # Check Braccetti (B - Difesa a 3)
    bs = role_roster_active['B']
    if len(bs) >= 2:
        strengths.append(f"Flessibilità difensiva a 3: {len(bs)} Braccetti (B) attivi per occupare lo slot Dc/B.")

    # Check Strikers (Pc - Pure Centre Forwards)
    pcs = role_roster_all['Pc']
    pc_active = role_roster_active['Pc']
    top_pc_gf = max([p.get('GF', 0) for p in pcs]) if pcs else 0
    
    if len(pc_active) < 3:
        weaknesses.append({
            'Reparto': 'Attacco (Punte Centrali)',
            'Ruolo': 'Pc',
            'Severita': 'CRITICA',
            'Titolo': 'Carenza critica di Punte Centrali (Pc) attive',
            'Diagnosi': f"Hai solo {len(pc_active)} Pc attive con voto costante ({', '.join(p['Giocatore'] for p in pc_active)}). Nei moduli a 2 punte (3-5-2, 4-3-1-2, 4-4-2) basta un solo infortunio o squalifica per rimanere senza riserve.",
            'Obiettivo_Mercato': 'Ingaggiare urgentemente una 3ª o 4ª Pc affidabile'
        })
    elif top_pc_gf < 3:
        weaknesses.append({
            'Reparto': 'Attacco (Punte Centrali)',
            'Ruolo': 'Pc',
            'Severita': 'ELEVATA',
            'Titolo': 'Mancanza di un bomber di vertice (Pc Top Tier)',
            'Diagnosi': f"Hai buone punte di rotazione ({', '.join(p['Giocatore'] for p in pc_active)}), ma nessun bomber da oltre 15 gol stagionali. Un attaccante d'élite massimizzerebbe il potenziale della rosa.",
            'Obiettivo_Mercato': 'Scambiare un pacchetto di esuberi per una Pc di prima fascia'
        })
    else:
        strengths.append(f"Reparto Punte ben strutturato con {len(pcs)} Pc disponibili.")

    # Check Wings & Second Strikers (W / A / T)
    ws = role_roster_active['W']
    a_s = role_roster_active['A']
    t_s = role_roster_active['T']
    
    if len(ws) >= 4:
        top_w_names = ', '.join(p['Giocatore'] for p in sorted(ws, key=lambda x: safe_float(x.get('xFV', 0)), reverse=True)[:4])
        strengths.append(f"Arsenale ali offensive: {len(ws)} W attive ad alto potenziale ({top_w_names}).")
    if len(a_s) >= 3:
        top_a_names = ', '.join(p['Giocatore'] for p in sorted(a_s, key=lambda x: safe_float(x.get('xFV', 0)), reverse=True)[:3])
        strengths.append(f"Profondità di seconde punte: {len(a_s)} A a disposizione ({top_a_names}), eccellente moneta di scambio sul mercato.")

    # 3. Identify Surplus Trade Assets (Calciatori spendibili sul mercato)
    # Note: Players whose ONLY roles are in critically deficient departments are NOT surplus!
    critically_weak_roles = set(w['Ruolo'] for w in weaknesses if w.get('Severita') in ('CRITICA', 'ELEVATA'))
    
    surplus_assets = []
    bench_df = df_proj[~df_proj['Giocatore'].isin(starter_names)].copy()
    
    for _, b_row in bench_df.iterrows():
        pname = b_row['Giocatore']
        
        # Release check: NEVER offer players to be released / out of Serie A
        if is_player_to_release(b_row.to_dict(), release_names) or is_player_to_release(pname, release_names):
            continue

        # Medical Availability: CANNOT offer injured or suspended players in cession!
        from engine.injuries_manager import classify_injury_status
        inj_status = classify_injury_status(pname)
        if not inj_status['Can_Be_Traded_Out']:
            continue
            
        roles_str = b_row.get('RuoloMantra', '')
        xfv = safe_float(b_row.get('xFV', 0))
        sig = str(b_row.get('Signal', 'NEUTRO'))
        roles = parse_mantra_roles(roles_str)
        presenze = safe_int(b_row.get('Presenze', 0))
        
        # Consider players with real presence and trade value
        if presenze < 2 and xfv < 5.4:
            continue
            
        # Protect critical shortage departments: if ALL roles are critically deficient, don't sacrifice
        if set(roles).issubset(critically_weak_roles):
            continue

        reasons = []
        if 'SELL-HIGH' in sig:
            reasons.append("Segnale SELL-HIGH (sta sovraperformando xG: momento ideale per monetizzare)")
        if xfv >= 5.8:
            reasons.append(f"Alto fanta-valore ({xfv:.2f} xFV) ma attualmente escluso dai titolari per vincoli di modulo")
        
        # Check if role has deep coverage in squad
        for r in roles:
            if len(role_roster_active.get(r, [])) >= RECOMMENDED_QUOTAS.get(r, {}).get('target', 4):
                reasons.append(f"Reparto '{r}' iper-coperto ({len(role_roster_active[r])} giocatori attivi)")
                break

        if reasons:
            surplus_assets.append({
                'Giocatore': pname,
                'Squadra': b_row.get('Squadra', ''),
                'RuoloMantra': roles_str,
                'xFV': safe_float(xfv),
                'FM_Stagione': safe_float(b_row.get('FM_Stagione', 0)),
                'Costo': safe_int(b_row.get('Costo', 0)),
                'GF': safe_int(b_row.get('GF', 0)),
                'Signal': sig,
                'Motivo_Cessione': "; ".join(reasons),
                'Goals_Prevented': safe_float(b_row.get('Goals_Prevented', 0.0)),
                'Goals_Prevented_90': safe_float(b_row.get('Goals_Prevented_90', 0.0)),
                'Errors_Leading_To_Goal': safe_int(b_row.get('Errors_Leading_To_Goal', 0)),
                'Pct_Parate': safe_float(b_row.get('Pct_Parate', 70.0)),
                'xG_Tot': safe_float(b_row.get('xG_Tot', 0.0)),
                'xG_90': safe_float(b_row.get('xG_90', 0.0)),
                'Delta_xG': safe_float(b_row.get('Delta_xG', 0.0)),
                'Tiri_90': safe_float(b_row.get('Tiri_90', 0.0)),
                'Key_Passes_90': safe_float(b_row.get('Key_Passes_90', 0.0)),
                'xA_90': safe_float(b_row.get('xA_90', 0.0))
            })

    surplus_assets = sorted(surplus_assets, key=lambda x: x['xFV'], reverse=True)

    return {
        'Squadra': team_name,
        'Modulo_Titolare': opt_res['Modulo'] if opt_res else 'N/D',
        'Punti_Titolari': opt_res['Punti_Attesi_Totali'] if opt_res else 0.0,
        'Punti_Deboli': weaknesses,
        'Punti_di_Forza': strengths,
        'Surplus_Cedibili': surplus_assets,
        'Conteggio_Totale': {r: len(role_roster_all[r]) for r in RECOMMENDED_QUOTAS.keys()},
        'Conteggio_Attivi': {r: len(role_roster_active[r]) for r in RECOMMENDED_QUOTAS.keys()}
    }


def _get_department_name(roles):
    if any(r in ['Pc', 'A'] for r in roles):
        return 'in attacco (punte)'
    if any(r in ['W', 'T'] for r in roles):
        return 'sulla trequarti / ali offensive'
    if any(r in ['M', 'C'] for r in roles):
        return 'a centrocampo'
    if any(r in ['Dd', 'Ds', 'E'] for r in roles):
        return 'sulle corsie esterne'
    if any(r in ['Dc'] for r in roles):
        return 'al centro della difesa'
    if any(r in ['Por'] for r in roles):
        return 'in porta'
    return 'in rosa'


def _format_trade_player(p, is_opponent=False):
    """Formats player dictionary for trade proposals with full stats and starter status."""
    from engine.injuries_manager import classify_injury_status
    if not isinstance(p, dict):
        p = {}
    status_info = compute_real_starter_status(p)
    p_name = p.get('Giocatore', '')
    inj_info = classify_injury_status(p_name) if (is_opponent and p_name) else {}
    is_buy_low = ('BUY-LOW' in str(p.get('Signal', '')))
    
    return {
        'Giocatore': p_name,
        'Squadra': p.get('Squadra', ''),
        'RuoloMantra': p.get('RuoloMantra', ''),
        'Costo': safe_int(p.get('Costo', 0)),
        'xFV': round(safe_float(p.get('xFV', 0.0)), 2),
        'FM': round(safe_float(p.get('FM', p.get('FM_Stagione', 0.0))), 2),
        'Signal': str(p.get('Signal', 'NEUTRO')),
        'Tier': p.get('Tier', 'TITOLARE'),
        'Status_Titolarita': status_info.get('Status', 'TITOLARE'),
        'Badge_Titolarita': status_info.get('Badge', '🟢 TITOLARE FISSO'),
        'Label_Titolarita': status_info.get('Label', '🟢 Titolare'),
        'Min_Per_Pres': safe_float(status_info.get('Min_Per_Pres', 0.0)),
        'Pct_Minuti': safe_float(status_info.get('Pct_Minuti', 0.0)),
        'Pct_Sufficienza': round(safe_float(p.get('Pct_Sufficienza', 50.0)), 1),
        'Is_Subentrante': not status_info.get('Is_Real_Starter', True),
        'Is_Buy_Low': is_buy_low,
        'Is_Injured': bool(inj_info.get('Is_Injured', False)),
        'Is_Stash_Injury': bool(inj_info.get('Is_Injured', False) and not inj_info.get('Is_Long_Term', False)),
        'Injury_Detail': str(inj_info.get('Dettaglio', '')),
        'Injury_Severity': str(inj_info.get('Severity_Label', 'DISPONIBILE')),
        'Is_Bench_In_Opponent': bool(p.get('Is_Bench_In_Opponent', False)),
        'Goals_Prevented': safe_float(p.get('Goals_Prevented', 0.0)),
        'Goals_Prevented_90': safe_float(p.get('Goals_Prevented_90', 0.0)),
        'Errors_Leading_To_Goal': safe_int(p.get('Errors_Leading_To_Goal', 0)),
        'Pct_Parate': safe_float(p.get('Pct_Parate', 70.0)),
        'xG_Tot': safe_float(p.get('xG_Tot', 0.0)),
        'xG_90': safe_float(p.get('xG_90', 0.0)),
        'Delta_xG': safe_float(p.get('Delta_xG', 0.0)),
        'Tiri_90': safe_float(p.get('Tiri_90', 0.0)),
        'Key_Passes_90': safe_float(p.get('Key_Passes_90', 0.0)),
        'xA_90': safe_float(p.get('xA_90', 0.0))
    }


def is_trade_role_parity_credible(give_dict, receive_dict):
    """
    Validates whether a proposed 1-to-1 swap respects Fantacalcio Mantra role hierarchy,
    capital investment parity, and fantasy football market credibility:
    - Tier 1: Pc, A (Centre Forwards and Second Strikers - Scarcest assets, +3 goal impact)
    - Tier 2: W, T (Attacking Wings and Trequartisti)
    - Tier 3: M, C, E, Dc, Dd, Ds (Midfield and Defensive Tactical Foundation)
    - Tier 4: Por (Goalkeepers)
    
    Rule 1: Nobody trades a Pc or A for a standard M, C, or Defender unless the given player
            is an undisputed 'Top di Reparto' (FM >= 6.70, GF >= 2, or Costo >= 16) or an elite W/T.
    Rule 2: Nobody trades an established starting W or T for a zero-bonus defensive midfielder or bench defender.
    Rule 3: Tactical cross-exchanges within M, C, E, Dc, Dd, Ds are credible if xFV is balanced.
    Rule 4: Por is only exchanged for other Por or comparable tactical assets.
    Rule 5: Extreme auction cost disparity (e.g. Costo 3 for Costo 232) is strictly rejected.
    Rule 6: Starting status parity: a marginal/deep bench player cannot be swapped 1x1 for an established Serie A starter.
    """
    give_roles = parse_mantra_roles(give_dict.get('RuoloMantra', ''))
    rec_roles = parse_mantra_roles(receive_dict.get('RuoloMantra', ''))
    
    is_rec_striker = any(r in ['Pc', 'A'] for r in rec_roles)
    is_give_striker = any(r in ['Pc', 'A'] for r in give_roles)
    
    is_rec_wing_t = any(r in ['W', 'T'] for r in rec_roles)
    is_give_wing_t = any(r in ['W', 'T'] for r in give_roles)
    
    is_rec_gk = 'Por' in rec_roles
    is_give_gk = 'Por' in give_roles

    give_fm = safe_float(give_dict.get('FM', give_dict.get('FM_Stagione', 0)))
    give_xfv = safe_float(give_dict.get('xFV', 0))
    give_gf = safe_int(give_dict.get('GF', 0))
    give_costo = safe_int(give_dict.get('Costo', 0))
    give_pres = safe_int(give_dict.get('Presenze', 0))

    rec_fm = safe_float(receive_dict.get('FM', receive_dict.get('FM_Stagione', 0)))
    rec_xfv = safe_float(receive_dict.get('xFV', 0))
    rec_gf = safe_int(receive_dict.get('GF', 0))
    rec_costo = safe_int(receive_dict.get('Costo', 0))
    rec_pres = safe_int(receive_dict.get('Presenze', 0))

    # -------------------------------------------------------------
    # 0. GOALKEEPER SANITY & INTEGRITY
    # -------------------------------------------------------------
    if is_rec_gk != is_give_gk:
        rec_is_starter_gk = is_rec_gk and (rec_pres >= 4 or rec_costo >= 20)
        give_is_starter_gk = is_give_gk and (give_pres >= 4 or give_costo >= 20)
        # Outfield for backup/reserve GK is completely unrealistic
        if is_rec_gk and not rec_is_starter_gk:
            return False
        if is_give_gk and not give_is_starter_gk:
            return False
        # Star striker for goalkeeper 1x1 is also rejected in real leagues
        if (is_give_striker and give_costo >= 40) or (is_rec_striker and rec_costo >= 40):
            return False

    # -------------------------------------------------------------
    # 1. CAPITAL INVESTMENT & AUCTION COST DISPARITY (1x1)
    # -------------------------------------------------------------
    if rec_costo >= 80:
        # Top star/bomber requires substantial value in return (at least 35% of cost or 35+ credits with high FM)
        if give_costo < 0.35 * rec_costo and not (give_costo >= 35 and give_fm >= 6.60):
            return False
    elif rec_costo >= 40:
        if give_costo < 0.25 * rec_costo and give_costo < 18:
            return False

    if give_costo >= 80:
        if rec_costo < 0.25 * give_costo and rec_costo < 25:
            return False

    # -------------------------------------------------------------
    # 2. REAL STARTER STATUS PARITY (1x1)
    # -------------------------------------------------------------
    give_status = compute_real_starter_status(give_dict)['Status']
    rec_status = compute_real_starter_status(receive_dict)['Status']
    if rec_status == 'TITOLARE' and give_status == 'MARGINALE':
        return False
    if rec_status == 'TITOLARE' and give_status == 'SUBENTRANTE' and give_costo < 25:
        return False
    if give_status == 'MARGINALE' and rec_status in ['TITOLARE', 'CO_TITOLARE']:
        return False

    # Top di Reparto criteria:
    is_give_top_dept = (
        give_gf >= 2 or 
        (give_fm >= 6.70 and give_xfv >= 5.8) or 
        (give_costo >= 16 and give_fm >= 6.30)
    )

    # -------------------------------------------------------------
    # 3. TARGET IS A STRIKER (Pc or A)
    # -------------------------------------------------------------
    if is_rec_striker:
        # A) You give another striker (Pc or A)
        if is_give_striker:
            max_c = max(give_costo, rec_costo, 1)
            min_c = min(give_costo, rec_costo)
            if max_c >= 50 and (min_c / max_c) < 0.25:
                return False
            return True
        # B) You give an elite attacking wing / trequartista (W or T)
        if is_give_wing_t:
            if give_xfv >= 5.5 and (give_fm >= 6.35 or give_gf >= 1 or give_costo >= 14):
                if rec_costo >= 100 and give_costo < 35:
                    return False
                return True
            return False
        # C) You give a Top di Reparto from midfield or defense
        if is_give_top_dept:
            if rec_costo >= 120 and give_costo < 45:
                return False
            return True
        return False

    # -------------------------------------------------------------
    # 4. TARGET IS AN ATTACKING WING OR TREQUARTISTA (W or T)
    # -------------------------------------------------------------
    if is_rec_wing_t:
        if is_give_striker or is_give_wing_t:
            return True
        is_give_c_e = any(r in ['C', 'E'] for r in give_roles)
        if is_give_c_e and (give_fm >= 6.30 or give_gf >= 1 or give_xfv >= 5.6):
            return True
        if is_give_top_dept or (give_fm >= 6.55 and give_xfv >= 5.7):
            return True
        return False

    # -------------------------------------------------------------
    # 5. TARGET IS A GOALKEEPER (Por)
    # -------------------------------------------------------------
    if is_rec_gk:
        if is_give_gk:
            return True
        is_rec_top_gk = (rec_costo >= 20 or rec_pres >= 4)
        if is_rec_top_gk:
            if is_give_striker or is_give_top_dept:
                return True
            if is_give_wing_t and give_xfv >= 5.6 and (give_costo >= 16 or give_fm >= 6.4):
                return True
            return False
        return False

    # -------------------------------------------------------------
    # 6. TARGET IS TACTICAL MIDFIELD OR DEFENSE (M, C, E, Dc, Dd, Ds)
    # -------------------------------------------------------------
    return True


def find_win_win_trades(
    my_team_name, league_data, df_master, matchday=8, 
    target_role_filter=None, give_player_filter=None, opp_team_filter=None, 
    min_starter_filter='TITOLARI_E_CO', trade_format_filter='TUTTI',
    df_all_proj=None, max_proposals=30, **kwargs
):
    if 'trade_format_filter' in kwargs:
        trade_format_filter = kwargs['trade_format_filter']
    """
    Automated Win-Win Trade Finder (Radar Scambi Intelligenti):
    Scans opponent teams in the fantasy league.
    Finds mutually advantageous trades across single (1x1) and multi-player formats (2x2, 2x1, 1x2):
    - 1x1: Strictly balanced 1-for-1 swaps respecting market credibility and auction cost parity.
    - 2x2: Combo Titolare + Riserva (Vasi Comunicanti): swaps a surplus starter + rotation piece for a target starter + depth piece, unlocking minutes for an existing bench reserve.
    - 2x1: Upgrade di Reparto: offers two solid starters/surplus players that fix multiple opponent holes for 1 elite target.
    - 1x2: Ristrutturazione Modulo / Profondità: trades 1 high-value piece from an overstocked role for 2 reliable starters.
    
    Returns prioritized list of mutually advantageous trade proposals with tactical negotiation arguments.
    """
    import itertools
    from engine.injuries_manager import classify_injury_status

    my_diag = analyze_squad_weaknesses(my_team_name, league_data, df_master, matchday=matchday)
    if 'error' in my_diag:
        return []

    my_weak_roles = set(w['Ruolo'] for w in my_diag.get('Punti_Deboli', []))
    if not my_weak_roles:
        my_weak_roles = {'Pc', 'M', 'Dc', 'Dd', 'Ds'}

    release_names = get_league_release_names(league_data)

    # Pre-project all players in df_master for matchday if not provided
    if df_all_proj is None or df_all_proj.empty:
        df_all_proj = batch_predict_xfv(df_master, matchday=matchday)
    proj_map = {row['Giocatore']: row.to_dict() for _, row in df_all_proj.iterrows()}

    # Build league auction cost lookup (taking max cost to ensure true ownership cost)
    costo_map = {}
    if isinstance(league_data, dict):
        for t_players in league_data.values():
            if isinstance(t_players, list):
                for p in t_players:
                    if isinstance(p, dict) and 'Giocatore' in p:
                        name = p['Giocatore']
                        cost = safe_int(p.get('Costo', 0))
                        costo_map[name] = max(costo_map.get(name, 0), cost)

    for name, p_data in proj_map.items():
        if name in costo_map:
            p_data['Costo'] = costo_map[name]

    # Diagnose My Team optimal lineup & offerable players
    my_owned = [
        p for p in league_data.get(my_team_name, [])
        if not p.get('InPrestito', False) and safe_int(p.get('Costo', 1)) > 0 and not is_player_to_release(p, release_names)
    ]
    my_pnames = [p['Giocatore'] for p in my_owned]
    my_proj_list = [proj_map[n] for n in my_pnames if n in proj_map]
    if not my_proj_list:
        return []
    df_my_proj = pd.DataFrame(my_proj_list)
    opt_my_curr = optimize_best_mantra_lineup(df_my_proj)
    my_starters_set = set(p['Giocatore'] for p in opt_my_curr.get('Titolari', []))
    my_surplus_set = set(s['Giocatore'] for s in my_diag.get('Surplus_Cedibili', []))

    # User active roles count to identify safe departments where starters can be traded
    my_roles_active = {}
    for p in my_proj_list:
        if safe_int(p.get('Presenze', 0)) >= 2 or safe_float(p.get('P_Voto', 0)) >= 0.50:
            for r in parse_mantra_roles(p.get('RuoloMantra', '')):
                my_roles_active[r] = my_roles_active.get(r, 0) + 1

    my_offerable = []
    for p_row in my_proj_list:
        pname = p_row['Giocatore']
        if is_player_to_release(p_row, release_names) or is_player_to_release(pname, release_names):
            continue
        inj = classify_injury_status(pname)
        if not inj.get('Can_Be_Traded_Out', True):
            continue

        pres = safe_int(p_row.get('Presenze', 0))
        xfv = safe_float(p_row.get('xFV', 0.0))
        roles = parse_mantra_roles(p_row.get('RuoloMantra', ''))
        is_gk = ('Por' in roles)

        if pname in my_surplus_set:
            tier = 'SURPLUS'
        elif pname in my_starters_set:
            # Starter: only offer if squad has deep coverage in that role (>= 4 active)
            has_depth = any(my_roles_active.get(r, 0) >= 4 for r in roles)
            if not has_depth and not is_gk:
                continue
            tier = 'TITOLARE'
        else:
            tier = 'PANCHINARO'

        if not is_gk and pres < 1 and xfv < 5.2 and tier != 'SURPLUS':
            continue

        p_info = dict(p_row)
        p_info['Tier'] = tier
        my_offerable.append(p_info)

    if not my_offerable:
        return []

    # Filter offerable players by specific give player if requested
    if give_player_filter and give_player_filter != 'TUTTI':
        if not any(p['Giocatore'] == give_player_filter for p in my_offerable):
            return []

    trade_proposals = []
    seen_trade_signatures = set()

    # Iterate over opponent teams
    for opp_team, opp_players in league_data.items():
        if opp_team == my_team_name:
            continue
        if opp_team_filter and opp_team_filter != 'TUTTI' and opp_team != opp_team_filter:
            continue

        opp_players_owned = [
            p for p in opp_players 
            if not p.get('InPrestito', False) and safe_int(p.get('Costo', 1)) > 0 and not is_player_to_release(p, release_names)
        ]
        opp_pnames = [p['Giocatore'] for p in opp_players_owned]
        opp_proj_list = []
        for name in opp_pnames:
            if name in proj_map:
                p_item = dict(proj_map[name])
                if name in costo_map:
                    p_item['Costo'] = costo_map[name]
                opp_proj_list.append(p_item)
        if not opp_proj_list:
            continue
            
        df_opp_proj = pd.DataFrame(opp_proj_list)
        opp_starters = set(df_opp_proj.sort_values('xFV', ascending=False).head(11)['Giocatore'])

        opp_diag = analyze_squad_weaknesses(opp_team, league_data, df_master, matchday=matchday)
        opp_weak_roles = {w['Ruolo']: w.get('Severita', 'MEDIA') for w in opp_diag.get('Punti_Deboli', [])}
        opp_surplus_pnames = set(s['Giocatore'] for s in opp_diag.get('Surplus_Cedibili', []))

        # Count opponent active roles
        opp_roles_active = {}
        for p in opp_proj_list:
            is_active = (safe_int(p.get('Presenze', 0)) >= 2 or safe_float(p.get('P_Voto', 0)) >= 0.50)
            for r in parse_mantra_roles(p.get('RuoloMantra', '')):
                if is_active:
                    opp_roles_active[r] = opp_roles_active.get(r, 0) + 1

        # Identify opponent target candidates that solve user's needs
        opp_target_candidates = []
        for opp_p in opp_proj_list:
            opp_p_name = opp_p['Giocatore']
            if is_player_to_release(opp_p, release_names) or is_player_to_release(opp_p_name, release_names):
                continue
            opp_p_roles = parse_mantra_roles(opp_p.get('RuoloMantra', ''))

            # Filter by target role if specified
            if target_role_filter and target_role_filter != 'TUTTI':
                if target_role_filter not in opp_p_roles:
                    continue
            elif not target_role_filter:
                if my_weak_roles and not opp_p_roles.intersection(my_weak_roles):
                    continue

            # Medical check
            opp_inj = classify_injury_status(opp_p_name)
            if opp_inj['Is_Long_Term'] or opp_inj.get('Stato') == 'Squalificato':
                continue

            # Criticality protection for opponent: don't take their last keeper or striker
            if 'Por' in opp_p_roles:
                opp_all_pors = [p for p in opp_proj_list if 'Por' in parse_mantra_roles(p.get('RuoloMantra', ''))]
                opp_rem_starters = [p for p in opp_all_pors if p['Giocatore'] != opp_p_name and (safe_int(p.get('Presenze', 0)) >= 3 or safe_float(p.get('P_Voto', 0)) >= 0.70)]
                if len(opp_rem_starters) == 0:
                    continue
            if 'Pc' in opp_p_roles and opp_roles_active.get('Pc', 0) <= 1:
                continue

            opp_p_status = compute_real_starter_status(opp_p)
            if min_starter_filter == 'TITOLARI_SOLO' and opp_p_status['Status'] != 'TITOLARE':
                continue
            elif min_starter_filter == 'TITOLARI_E_CO' and opp_p_status['Status'] not in ['TITOLARE', 'CO_TITOLARE']:
                continue
            elif min_starter_filter == 'TUTTI' and opp_p_status['Status'] == 'MARGINALE':
                continue

            opp_target_candidates.append(opp_p)

        if not opp_target_candidates:
            continue

        # Opponent secondary surplus/bench pieces for multi-player deals
        opp_secondary_pieces = [
            p for p in opp_proj_list
            if not is_player_to_release(p, release_names) and
               'Por' not in parse_mantra_roles(p.get('RuoloMantra', '')) and
               (p['Giocatore'] in opp_surplus_pnames or safe_float(p.get('xFV', 0)) <= 5.8)
        ]

        # -------------------------------------------------------------
        # GENERATION 1: 1x1 TRADES (Scambi Singoli Equilibrati)
        # -------------------------------------------------------------
        if trade_format_filter in ['TUTTI', 'SOLO_SINGOLI']:
            my_1x1_offers = [p for p in my_offerable if p['Tier'] in ['SURPLUS', 'PANCHINARO']]
            if not my_1x1_offers:
                my_1x1_offers = my_offerable

            for my_give in my_1x1_offers:
                if give_player_filter and give_player_filter != 'TUTTI' and my_give['Giocatore'] != give_player_filter:
                    continue
                my_give_roles = parse_mantra_roles(my_give['RuoloMantra'])
                opp_needs_my_give = any(r in opp_weak_roles for r in my_give_roles)

                for opp_p in opp_target_candidates:
                    opp_p_name = opp_p['Giocatore']
                    opp_p_roles = parse_mantra_roles(opp_p.get('RuoloMantra', ''))

                    # Role Parity & Hierarchy Credibility Check
                    if not is_trade_role_parity_credible(my_give, opp_p):
                        continue

                    # xFV Parity Check
                    my_give_xfv = safe_float(my_give.get('xFV', 0.0))
                    opp_p_xfv = safe_float(opp_p.get('xFV', 0.0))
                    if abs(opp_p_xfv - my_give_xfv) > 1.85:
                        continue

                    # Don't swap same weak role without improvement
                    same_weak = my_give_roles.intersection(opp_p_roles).intersection(my_weak_roles)
                    if same_weak and opp_p_xfv <= my_give_xfv + 0.3:
                        continue

                    sig_key = (opp_team, (my_give['Giocatore'],), (opp_p_name,))
                    if sig_key in seen_trade_signatures:
                        continue
                    seen_trade_signatures.add(sig_key)

                    # Win-Win Score & Rationale
                    score = 50.0
                    reasons = []
                    if opp_needs_my_give:
                        score += 35.0
                        reasons.append(f"Bisogno forte di {opp_team}: il ruolo di {my_give['Giocatore']} ({my_give['RuoloMantra']}) è un punto debole nella loro rosa")
                    elif any(opp_roles_active.get(r, 0) <= 3 for r in my_give_roles):
                        score += 15.0
                        reasons.append(f"{opp_team} ha rotazioni corte nel ruolo di {my_give['Giocatore']}")

                    opp_p_status = compute_real_starter_status(opp_p)
                    matching_weakness = [w for w in my_diag.get('Punti_Deboli', []) if w['Ruolo'] in opp_p_roles]
                    if opp_p_status['Status'] == 'TITOLARE':
                        score += 35.0
                        reasons.append(f"🟢 Titolare inamovibile in Serie A ({opp_p_status['Min_Per_Pres']} min/partita)")
                        if matching_weakness:
                            score += 30.0 if matching_weakness[0]['Severita'] == 'CRITICA' else 20.0
                            reasons.append(f"Risolve un tuo punto debole: colma la carenza in {matching_weakness[0]['Reparto']} ({matching_weakness[0]['Ruolo']})")
                    elif opp_p_status['Status'] == 'CO_TITOLARE':
                        score += 20.0
                        reasons.append(f"🟡 Co-titolare / rotazione frequente in Serie A ({opp_p_status['Min_Per_Pres']} min/partita)")

                    opp_inj = classify_injury_status(opp_p_name)
                    is_stash = opp_inj.get('Is_Injured', False) and not opp_inj.get('Is_Long_Term', False)
                    if is_stash:
                        score += 20.0
                        reasons.append(f"🩹 Opportunità Stash: {opp_p_name} è momentaneamente infortunato lieve ({opp_inj.get('Dettaglio', 'rientro a breve')}), prendibile a prezzo di saldo")

                    opp_dept_name = _get_department_name(opp_p_roles)
                    short_str = "/".join(list(my_give_roles))
                    pitch = (
                        f"Ciao! Ho notato che per {opp_team} farebbe comodo rinforzare lo slot {short_str}, "
                        f"mentre avete buone alternative {opp_dept_name}. Vi andrebbe di valutare uno scambio alla pari tra {my_give['Giocatore']} e {opp_p_name}? "
                        f"A voi garantisce un titolare affidabile dove siete scoperti, e a noi permette di inserire {opp_p_name}. Che ne dite?"
                    )

                    give_fmt = _format_trade_player(my_give, is_opponent=False)
                    rec_fmt = _format_trade_player(opp_p, is_opponent=True)

                    trade_proposals.append({
                        'Score': round(score, 1),
                        'Squadra_Avversaria': opp_team,
                        'Tipo_Scambio': '1x1',
                        'Label_Tipo': '⚖️ Scambio Diretto (1x1)',
                        'Is_Stash_Injury': is_stash,
                        'Tu_Cedi_List': [give_fmt],
                        'Tu_Ricevi_List': [rec_fmt],
                        'Tu_Cedi': give_fmt,
                        'Tu_Ricevi': rec_fmt,
                        'Tot_Costo_Cedi': give_fmt['Costo'],
                        'Tot_Costo_Ricevi': rec_fmt['Costo'],
                        'Tot_xFV_Cedi': give_fmt['xFV'],
                        'Tot_xFV_Ricevi': rec_fmt['xFV'],
                        'Delta_xFV': round(rec_fmt['xFV'] - give_fmt['xFV'], 2),
                        'Ruolo_Target': list(opp_p_roles)[0] if opp_p_roles else 'N/D',
                        'Motivazioni': reasons,
                        'Messaggio_Trattativa': pitch,
                        'Simulazione_Payload': {
                            'give_names': [give_fmt['Giocatore']],
                            'receive_names': [rec_fmt['Giocatore']],
                            'opp_team': opp_team
                        }
                    })

        # -------------------------------------------------------------
        # GENERATION 2: 2x2 COMBO TITOLARE + RISERVA (Vasi Comunicanti)
        # -------------------------------------------------------------
        if trade_format_filter in ['TUTTI', 'SOLO_MULTIPLI']:
            seen_2x2_anchors = set()
            primary_give_candidates = [
                p for p in my_offerable 
                if any(r in opp_weak_roles for r in parse_mantra_roles(p.get('RuoloMantra', ''))) or p['Tier'] == 'SURPLUS'
            ]
            primary_give_candidates = sorted(primary_give_candidates, key=lambda x: safe_float(x.get('xFV', 0)), reverse=True)[:6]
            secondary_give_candidates = [p for p in my_offerable if p['Tier'] in ['SURPLUS', 'PANCHINARO']][:8]

            for g1 in primary_give_candidates:
                g1_name = g1['Giocatore']
                for g2 in secondary_give_candidates:
                    g2_name = g2['Giocatore']
                    if g1_name == g2_name:
                        continue
                    if give_player_filter and give_player_filter != 'TUTTI' and give_player_filter not in [g1_name, g2_name]:
                        continue

                    give_pkg = [g1, g2]

                    for t1 in opp_target_candidates[:6]:
                        t1_name = t1['Giocatore']
                        anchor_key = (opp_team, g1_name, t1_name)
                        if anchor_key in seen_2x2_anchors:
                            continue
                        for t2 in opp_secondary_pieces[:6]:
                            t2_name = t2['Giocatore']
                            if t1_name == t2_name:
                                continue

                            rec_pkg = [t1, t2]

                            sig_key = (opp_team, tuple(sorted([str(g1_name), str(g2_name)])), tuple(sorted([str(t1_name), str(t2_name)])))
                            if sig_key in seen_trade_signatures:
                                continue

                            # Rule: Do not mix Goalkeepers and Outfielders in 2x2 multi-deals
                            give_has_por = any('Por' in parse_mantra_roles(p.get('RuoloMantra', '')) for p in give_pkg)
                            rec_has_por = any('Por' in parse_mantra_roles(p.get('RuoloMantra', '')) for p in rec_pkg)
                            if give_has_por != rec_has_por:
                                continue

                            # Rule: Capital investment balance in 2x2 (avoid extreme multi-package cost asymmetry)
                            tot_c_give_test = sum(safe_int(p.get('Costo', 0)) for p in give_pkg)
                            tot_c_rec_test = sum(safe_int(p.get('Costo', 0)) for p in rec_pkg)
                            max_c_2x2 = max(tot_c_give_test, tot_c_rec_test, 1)
                            min_c_2x2 = min(tot_c_give_test, tot_c_rec_test)
                            if max_c_2x2 >= 80 and (min_c_2x2 / max_c_2x2) < 0.28:
                                continue

                            pw = evaluate_pairwise_trade_balance(give_pkg, rec_pkg)
                            if not pw['is_valid']:
                                continue

                            seen_trade_signatures.add(sig_key)

                            g1_roles = parse_mantra_roles(g1.get('RuoloMantra', ''))
                            t1_roles = parse_mantra_roles(t1.get('RuoloMantra', ''))
                            t1_status = compute_real_starter_status(t1)

                            score = 65.0
                            reasons = []

                            if any(r in opp_weak_roles for r in g1_roles):
                                score += 35.0
                                reasons.append(f"Risolve debolezza chiave di {opp_team}: {g1_name} ({g1['RuoloMantra']}) copre una lacuna grave del loro 11 titolare")
                            if t1_status['Status'] == 'TITOLARE':
                                score += 35.0
                                reasons.append(f"🟢 Ti assicuri un titolare inamovibile ({t1_name}: {t1_status['Min_Per_Pres']} min/p)")
                            elif t1_status['Status'] == 'CO_TITOLARE':
                                score += 20.0
                                reasons.append(f"🟡 Ti assicuri una rotazione costante ({t1_name})")

                            score += 25.0
                            reasons.append(
                                f"🔄 Combo Vasi Comunicanti: scambi un titolare/top esubero coperto ({g1_name}) più una riserva ({g2_name}) "
                                f"per acquisire il titolare desiderato ({t1_name}) senza sguarnire la rosa, liberando spazio per le riserve già in rosa."
                            )

                            pitch = (
                                f"Ciao! Per bilanciare al meglio le nostre rose senza creare buchi di formazione, vi andrebbe di valutare uno scambio multiplo 2x2? "
                                f"Da parte nostra inseriamo {g1_name} ({g1['RuoloMantra']}) che vi sistema subito la titolarità dove siete corti, più {g2_name} ({g2['RuoloMantra']}) come valida rotazione. "
                                f"In cambio accoglieremmo {t1_name} ({t1['RuoloMantra']}) e {t2_name} ({t2['RuoloMantra']}). Così entrambi rinforziamo l'11 titolare e manteniamo coperte le riserve!"
                            )

                            g1_fmt = _format_trade_player(g1, is_opponent=False)
                            g2_fmt = _format_trade_player(g2, is_opponent=False)
                            t1_fmt = _format_trade_player(t1, is_opponent=True)
                            t2_fmt = _format_trade_player(t2, is_opponent=True)

                            give_list = [g1_fmt, g2_fmt]
                            rec_list = [t1_fmt, t2_fmt]

                            tot_c_give = sum(p['Costo'] for p in give_list)
                            tot_c_rec = sum(p['Costo'] for p in rec_list)
                            tot_x_give = round(sum(p['xFV'] for p in give_list), 2)
                            tot_x_rec = round(sum(p['xFV'] for p in rec_list), 2)

                            seen_2x2_anchors.add(anchor_key)
                            trade_proposals.append({
                                'Score': round(score, 1),
                                'Squadra_Avversaria': opp_team,
                                'Tipo_Scambio': '2x2',
                                'Label_Tipo': '🔄 Combo Titolare + Riserva (2x2)',
                                'Is_Stash_Injury': t1_fmt['Is_Stash_Injury'] or t2_fmt['Is_Stash_Injury'],
                                'Tu_Cedi_List': give_list,
                                'Tu_Ricevi_List': rec_list,
                                'Tu_Cedi': g1_fmt,
                                'Tu_Ricevi': t1_fmt,
                                'Tot_Costo_Cedi': tot_c_give,
                                'Tot_Costo_Ricevi': tot_c_rec,
                                'Tot_xFV_Cedi': tot_x_give,
                                'Tot_xFV_Ricevi': tot_x_rec,
                                'Delta_xFV': round(tot_x_rec - tot_x_give, 2),
                                'Ruolo_Target': list(t1_roles)[0] if t1_roles else 'N/D',
                                'Motivazioni': reasons,
                                'Messaggio_Trattativa': pitch,
                                'Simulazione_Payload': {
                                    'give_names': [g1_name, g2_name],
                                    'receive_names': [t1_name, t2_name],
                                    'opp_team': opp_team
                                }
                            })

        # -------------------------------------------------------------
        # GENERATION 3: 2x1 TRADES (Upgrade di Reparto / Due per Uno)
        # -------------------------------------------------------------
        if trade_format_filter in ['TUTTI', 'SOLO_MULTIPLI']:
            seen_2x1_targets = set()
            high_targets = [t for t in opp_target_candidates if safe_int(t.get('Costo', 0)) >= 35 or safe_float(t.get('xFV', 0)) >= 6.0]
            my_top_offers = sorted(my_offerable, key=lambda x: safe_float(x.get('xFV', 0)), reverse=True)[:10]

            for t1 in high_targets[:6]:
                t1_name = t1['Giocatore']
                target_key = (opp_team, t1_name)
                if target_key in seen_2x1_targets:
                    continue
                t1_roles = parse_mantra_roles(t1.get('RuoloMantra', ''))
                t1_status = compute_real_starter_status(t1)

                for pair in itertools.combinations(my_top_offers, 2):
                    g1, g2 = pair
                    g1_name, g2_name = g1['Giocatore'], g2['Giocatore']
                    if give_player_filter and give_player_filter != 'TUTTI' and give_player_filter not in [g1_name, g2_name]:
                        continue

                    give_pkg = [g1, g2]
                    rec_pkg = [t1]

                    sig_key = (opp_team, tuple(sorted([str(g1_name), str(g2_name)])), (str(t1_name),))
                    if sig_key in seen_trade_signatures:
                        continue

                    pw = evaluate_pairwise_trade_balance(give_pkg, rec_pkg)
                    if not pw['is_valid']:
                        continue

                    g_roles_all = set().union(*[parse_mantra_roles(p.get('RuoloMantra', '')) for p in give_pkg])
                    solved_w = [r for r in g_roles_all if r in opp_weak_roles]
                    if not solved_w:
                        continue

                    seen_trade_signatures.add(sig_key)

                    score = 70.0
                    reasons = []
                    score += 35.0
                    reasons.append(f"Risolve molteplici falle di {opp_team}: offri due giocatori complementari che coprono {', '.join(solved_w)}")
                    score += 30.0
                    reasons.append(f"🚀 Upgrade di Reparto: inserisci un top asset ({t1_name}) aumentando il picco qualitativo dei tuoi titolari")
                    reasons.append(f"📈 Libera uno slot a voto, consentendo alle tue riserve di reparto di scalare titolari.")

                    pitch = (
                        f"Ciao! Visto che a {opp_team} farebbe comodo rinforzare contemporaneamente più reparti scoperti, vi andrebbe di valutare un'offerta 2 per 1? "
                        f"Siamo pronti a mettere sul piatto sia {g1_name} ({g1['RuoloMantra']}) che {g2_name} ({g2['RuoloMantra']}) in cambio di {t1_name}. "
                        f"Ricevete due titolari pronti che aumentano il vostro punteggio medio ogni giornata e coprono i buchi di rosa!"
                    )

                    g1_fmt = _format_trade_player(g1, is_opponent=False)
                    g2_fmt = _format_trade_player(g2, is_opponent=False)
                    t1_fmt = _format_trade_player(t1, is_opponent=True)

                    give_list = [g1_fmt, g2_fmt]
                    rec_list = [t1_fmt]

                    tot_c_give = sum(p['Costo'] for p in give_list)
                    tot_c_rec = sum(p['Costo'] for p in rec_list)
                    tot_x_give = round(sum(p['xFV'] for p in give_list), 2)
                    tot_x_rec = round(sum(p['xFV'] for p in rec_list), 2)

                    seen_2x1_targets.add(target_key)
                    trade_proposals.append({
                        'Score': round(score, 1),
                        'Squadra_Avversaria': opp_team,
                        'Tipo_Scambio': '2x1',
                        'Label_Tipo': '🚀 Upgrade Reparto (2x1)',
                        'Is_Stash_Injury': t1_fmt['Is_Stash_Injury'],
                        'Tu_Cedi_List': give_list,
                        'Tu_Ricevi_List': rec_list,
                        'Tu_Cedi': g1_fmt,
                        'Tu_Ricevi': t1_fmt,
                        'Tot_Costo_Cedi': tot_c_give,
                        'Tot_Costo_Ricevi': tot_c_rec,
                        'Tot_xFV_Cedi': tot_x_give,
                        'Tot_xFV_Ricevi': tot_x_rec,
                        'Delta_xFV': round(tot_x_rec - tot_x_give, 2),
                        'Ruolo_Target': list(t1_roles)[0] if t1_roles else 'N/D',
                        'Motivazioni': reasons,
                        'Messaggio_Trattativa': pitch,
                        'Simulazione_Payload': {
                            'give_names': [g1_name, g2_name],
                            'receive_names': [t1_name],
                            'opp_team': opp_team
                        }
                    })

        # -------------------------------------------------------------
        # GENERATION 4: 1x2 TRADES (Ristrutturazione Modulo / Profondità)
        # -------------------------------------------------------------
        if trade_format_filter in ['TUTTI', 'SOLO_MULTIPLI']:
            high_give = [p for p in my_offerable if safe_int(p.get('Costo', 0)) >= 45 or safe_float(p.get('xFV', 0)) >= 6.2]
            for g1 in high_give[:4]:
                g1_name = g1['Giocatore']
                if give_player_filter and give_player_filter != 'TUTTI' and give_player_filter != g1_name:
                    continue

                for pair in itertools.combinations(opp_target_candidates[:8], 2):
                    t1, t2 = pair
                    t1_name, t2_name = t1['Giocatore'], t2['Giocatore']

                    give_pkg = [g1]
                    rec_pkg = [t1, t2]

                    sig_key = (opp_team, (str(g1_name),), tuple(sorted([str(t1_name), str(t2_name)])))
                    if sig_key in seen_trade_signatures:
                        continue

                    pw = evaluate_pairwise_trade_balance(give_pkg, rec_pkg)
                    if not pw['is_valid']:
                        continue

                    seen_trade_signatures.add(sig_key)

                    score = 65.0
                    reasons = [
                        f"Ristrutturazione / Profondità: cedi un top di reparto sovraffollato ({g1_name}) "
                        f"per ottenere 2 titolari ({t1_name} + {t2_name}) che completano diversi reparti scoperti."
                    ]

                    pitch = (
                        f"Ciao! Visto che avete ottima abbondanza nei ruoli di {t1_name} e {t2_name}, mentre vi servirebbe un pilastro di assoluto livello come {g1_name} ({g1['RuoloMantra']}), "
                        f"vi andrebbe di valutare un pacchetto in cui vi cediamo {g1_name} per accogliere {t1_name} e {t2_name}? Vi garantisce un top player inamovibile per fare il salto di qualità!"
                    )

                    g1_fmt = _format_trade_player(g1, is_opponent=False)
                    t1_fmt = _format_trade_player(t1, is_opponent=True)
                    t2_fmt = _format_trade_player(t2, is_opponent=True)

                    give_list = [g1_fmt]
                    rec_list = [t1_fmt, t2_fmt]

                    tot_c_give = sum(p['Costo'] for p in give_list)
                    tot_c_rec = sum(p['Costo'] for p in rec_list)
                    tot_x_give = round(sum(p['xFV'] for p in give_list), 2)
                    tot_x_rec = round(sum(p['xFV'] for p in rec_list), 2)

                    trade_proposals.append({
                        'Score': round(score, 1),
                        'Squadra_Avversaria': opp_team,
                        'Tipo_Scambio': '1x2',
                        'Label_Tipo': '📐 Ristrutturazione Modulo (1x2)',
                        'Is_Stash_Injury': t1_fmt['Is_Stash_Injury'] or t2_fmt['Is_Stash_Injury'],
                        'Tu_Cedi_List': give_list,
                        'Tu_Ricevi_List': rec_list,
                        'Tu_Cedi': g1_fmt,
                        'Tu_Ricevi': t1_fmt,
                        'Tot_Costo_Cedi': tot_c_give,
                        'Tot_Costo_Ricevi': tot_c_rec,
                        'Tot_xFV_Cedi': tot_x_give,
                        'Tot_xFV_Ricevi': tot_x_rec,
                        'Delta_xFV': round(tot_x_rec - tot_x_give, 2),
                        'Ruolo_Target': (list(parse_mantra_roles(t1.get('RuoloMantra', ''))) or ['N/D'])[0],
                        'Motivazioni': reasons,
                        'Messaggio_Trattativa': pitch,
                        'Simulazione_Payload': {
                            'give_names': [g1_name],
                            'receive_names': [t1_name, t2_name],
                            'opp_team': opp_team
                        }
                    })

    # Balance proposals across opponent teams so no single rival monopolizes the list
    team_counts = {}
    balanced_proposals = []
    seen_indices = set()
    sorted_proposals = sorted(trade_proposals, key=lambda x: safe_float(x.get('Score', 0.0)), reverse=True)
    
    # Pass 1: take up to 2-3 proposals per rival team to guarantee diverse league options
    for idx, p in enumerate(sorted_proposals):
        t = p.get('Squadra_Avversaria', '')
        if team_counts.get(t, 0) < 3:
            balanced_proposals.append(p)
            seen_indices.add(idx)
            team_counts[t] = team_counts.get(t, 0) + 1
        if len(balanced_proposals) >= max_proposals:
            break
            
    # Pass 2: if still under max_proposals, fill remaining spots
    if len(balanced_proposals) < max_proposals:
        for idx, p in enumerate(sorted_proposals):
            if idx not in seen_indices:
                balanced_proposals.append(p)
                seen_indices.add(idx)
                if len(balanced_proposals) >= max_proposals:
                    break
                    
    return balanced_proposals



def simulate_opponent_post_trade(
    opp_team_name,
    opp_proj_list,
    target_players,
    give_pkg,
    opt_opp_curr=None,
    allowed_formations=None
):
    """
    Simulates the opponent squad and starting 11 after the trade:
    1. Verifies that the trade does not leave the opponent uncovered in goal (< 2 Por or 0 starters).
    2. Verifies that the trade does not create critical deficiencies in core defensive or midfield slots.
    3. Solves the opponent's new optimal starting 11 and calculates net points gained/lost (delta_opp_pts).
    4. Evaluates rival appeal and generates tactical reassurance arguments.
    """
    target_pnames = set(p['Giocatore'] for p in target_players)
    opp_new_list = [p for p in opp_proj_list if p['Giocatore'] not in target_pnames] + give_pkg

    # 1. Goalkeeper check
    opp_pors_before = [p for p in opp_proj_list if 'Por' in parse_mantra_roles(p.get('RuoloMantra', ''))]
    opp_pors_after = [p for p in opp_new_list if 'Por' in parse_mantra_roles(p.get('RuoloMantra', ''))]
    opp_starters_before = [p for p in opp_pors_before if safe_int(p.get('Presenze', 0)) >= 3 or safe_float(p.get('P_Voto', 0)) >= 0.70]
    opp_starters_after = [p for p in opp_pors_after if safe_int(p.get('Presenze', 0)) >= 3 or safe_float(p.get('P_Voto', 0)) >= 0.70]

    target_has_por = any('Por' in parse_mantra_roles(p.get('RuoloMantra', '')) for p in target_players)
    give_has_por = any('Por' in parse_mantra_roles(p.get('RuoloMantra', '')) for p in give_pkg)

    is_goal_uncovered = False
    critical_flaws = []
    reassurances = []

    if target_has_por:
        if len(opp_pors_after) < 2 or len(opp_starters_after) == 0:
            is_goal_uncovered = True
            critical_flaws.append("🚨 Porta scoperta: l'avversario resterebbe con meno di 2 portieri o senza un titolare a voto.")
        elif give_has_por:
            por_names = [p['Giocatore'] for p in give_pkg if 'Por' in parse_mantra_roles(p.get('RuoloMantra', ''))]
            reassurances.append(f"🛡️ Porta salvaguardata al 100%: riceve {', '.join(por_names)} come titolare affidabile.")

    # 2. Outfield core depth checks (Dc, M, Pc)
    for r, min_safe, label in [('Dc', 3, 'Difensori Centrali'), ('M', 2, 'Mediani'), ('Pc', 1, 'Punte Centrali')]:
        c_before = sum(1 for p in opp_proj_list if r in parse_mantra_roles(p.get('RuoloMantra', '')) and (safe_int(p.get('Presenze', 0)) >= 2 or safe_float(p.get('P_Voto', 0)) >= 0.50))
        c_after = sum(1 for p in opp_new_list if r in parse_mantra_roles(p.get('RuoloMantra', '')) and (safe_int(p.get('Presenze', 0)) >= 2 or safe_float(p.get('P_Voto', 0)) >= 0.50))
        if c_before >= min_safe and c_after < min_safe:
            critical_flaws.append(f"⚠️ Carenza creata in {label} ({r}): scende a {c_after} giocatori attivi.")

    # 3. Simulate opponent lineup
    opt_opp_new = optimize_best_mantra_lineup(pd.DataFrame(opp_new_list), allowed_formations=allowed_formations)
    opp_curr_pts = opt_opp_curr['Punti_Attesi_Totali'] if opt_opp_curr else 0.0
    opp_new_pts = opt_opp_new['Punti_Attesi_Totali'] if opt_opp_new else 0.0
    delta_opp_pts = round(opp_new_pts - opp_curr_pts, 2)

    # 4. Tactical Opponent Dynamics: Internal Reserve Promotion & Module Switch
    curr_titolari_names = set(p['Giocatore'] for p in opt_opp_curr.get('Titolari', [])) if opt_opp_curr else set()
    new_titolari_names = set(p['Giocatore'] for p in opt_opp_new.get('Titolari', [])) if opt_opp_new else set()
    give_names_set = set(p['Giocatore'] for p in give_pkg)
    
    opp_starters_giving = [p['Giocatore'] for p in target_players if p['Giocatore'] in curr_titolari_names]
    opp_starters_received = [p['Giocatore'] for p in give_pkg if p['Giocatore'] in new_titolari_names]
    
    # Internal bench players promoted into the opponent's starting 11
    promoted_internal_reserves = [
        p['Giocatore'] for p in opt_opp_new.get('Titolari', [])
        if p['Giocatore'] not in give_names_set and p['Giocatore'] not in curr_titolari_names
    ]
    
    curr_mod = opt_opp_curr.get('Modulo', 'N/D') if opt_opp_curr else 'N/D'
    new_mod = opt_opp_new.get('Modulo', 'N/D') if opt_opp_new else 'N/D'
    is_module_changed = (curr_mod != new_mod and new_mod != 'N/D')
    
    # Positive tactical reassurances
    if promoted_internal_reserves:
        reassurances.append(
            f"🔄 Spazio titolare sbloccato per le riserve: la cessione promuove negli 11 {', '.join(promoted_internal_reserves)}, "
            f"precedentemente chiuso in panchina ma con fanta-valore comparabile."
        )
    if is_module_changed and delta_opp_pts >= -0.50:
        reassurances.append(
            f"📐 Cambio modulo proficuo: consente a {opp_team_name} di passare dal {curr_mod} al {new_mod}, "
            f"ottimizzando la resa complessiva della rosa."
        )

    # When is there a fatal starter deficit?
    # Only if:
    # 1. Net starters lost > 0 AND no internal reserve was promoted AND delta_opp_pts < -0.35
    # OR 2. Lineup collapses heavily (delta_opp_pts < -0.90)
    has_starter_deficit_flaw = False
    net_starters_lost = len(opp_starters_giving) - len(opp_starters_received)
    
    if net_starters_lost > 0:
        if not promoted_internal_reserves and delta_opp_pts < -0.35:
            has_starter_deficit_flaw = True
            critical_flaws.append(
                f"⚠️ Perdita netta di titolari: cede {len(opp_starters_giving)} titolari ({', '.join(opp_starters_giving)}) "
                f"senza avere riserve interne pronte a subentrare negli 11 ({delta_opp_pts:+.2f} pt)."
            )
        elif delta_opp_pts < -0.90:
            has_starter_deficit_flaw = True
            critical_flaws.append(
                f"⚠️ Peggioramento eccessivo della formazione: la perdita dei titolari non è compensata "
                f"dalle riserve interne ({delta_opp_pts:+.2f} pt attesi)."
            )

    return {
        'is_goal_uncovered': is_goal_uncovered,
        'critical_flaws': critical_flaws,
        'has_fatal_flaw': is_goal_uncovered or has_starter_deficit_flaw or (len(critical_flaws) >= 2),
        'opp_curr_pts': opp_curr_pts,
        'opp_new_pts': opp_new_pts,
        'delta_opp_pts': delta_opp_pts,
        'opp_curr_modulo': curr_mod,
        'opp_new_modulo': new_mod,
        'promoted_internal_reserves': promoted_internal_reserves,
        'is_module_changed': is_module_changed,
        'reassurances': reassurances,
        'opt_opp_new': opt_opp_new
    }


def find_trades_for_target_players(
    my_team_name,
    opp_team_name,
    target_player_names,
    league_data,
    df_master,
    matchday=8,
    allow_starters=True,
    package_types=('1x1', '2x1', '2x2'),
    df_all_proj=None,
    max_proposals=25
):
    """
    Reverse Targeted Trade Finder (Scambio Mirato su Obiettivo):
    Given one or more target players from a rival team:
    1. Analyzes the opponent's structural weaknesses, bottlenecks, and depth deficits.
    2. Identifies players from user's squad that solve those weaknesses, giving preference
       to Surplus (esuberi) first, but allowing bench and starters if advantageous.
    3. Simulates the user's starting 11 before and after trade to ensure positive net value.
    4. Evaluates rival feasibility/appeal and generates convincing negotiation pitches.
    """
    import itertools
    from engine.injuries_manager import classify_injury_status

    if not target_player_names or opp_team_name == my_team_name:
        return []
    if opp_team_name not in league_data or my_team_name not in league_data:
        return []

    release_names = get_league_release_names(league_data)

    # 1. Diagnose opponent squad
    opp_diag = analyze_squad_weaknesses(opp_team_name, league_data, df_master, matchday=matchday)
    if 'error' in opp_diag:
        return []
    opp_weaknesses = opp_diag.get('Punti_Deboli', [])
    opp_weak_roles = {w['Ruolo']: w.get('Severita', 'MEDIA') for w in opp_weaknesses}

    # 2. Diagnose my squad
    my_diag = analyze_squad_weaknesses(my_team_name, league_data, df_master, matchday=matchday)
    if 'error' in my_diag:
        return []

    if df_all_proj is None or df_all_proj.empty:
        df_all_proj = batch_predict_xfv(df_master, matchday=matchday)
    proj_map = {row['Giocatore']: row.to_dict() for _, row in df_all_proj.iterrows()}

    # My squad players (owned assets only, excluding to-be-released)
    my_owned = [
        p for p in league_data[my_team_name] 
        if not p.get('InPrestito', False) and p.get('Costo', 1) > 0 and not is_player_to_release(p, release_names)
    ]
    my_pnames = [p['Giocatore'] for p in my_owned]
    my_proj_list = [proj_map[n] for n in my_pnames if n in proj_map]
    if not my_proj_list:
        return []
    df_my_proj = pd.DataFrame(my_proj_list)

    # Current optimal lineup (My team)
    opt_my_curr = optimize_best_mantra_lineup(df_my_proj)
    my_curr_pts = opt_my_curr['Punti_Attesi_Totali'] if opt_my_curr else 0.0
    my_curr_modulo = opt_my_curr['Modulo'] if opt_my_curr else 'N/D'
    my_starters_set = set(p['Giocatore'] for p in opt_my_curr.get('Titolari', []))
    my_surplus_set = set(s['Giocatore'] for s in my_diag.get('Surplus_Cedibili', []))

    # Opponent target players and baseline lineup (owned assets only, excluding to-be-released)
    opp_owned = [
        p for p in league_data[opp_team_name] 
        if not p.get('InPrestito', False) and p.get('Costo', 1) > 0 and not is_player_to_release(p, release_names)
    ]
    opp_pnames = set(p['Giocatore'] for p in opp_owned)
    opp_proj_list = [proj_map[n] for n in opp_pnames if n in proj_map]
    if not opp_proj_list:
        return []
    df_opp_proj = pd.DataFrame(opp_proj_list)
    opt_opp_curr = optimize_best_mantra_lineup(df_opp_proj)
    opp_curr_pts = opt_opp_curr['Punti_Attesi_Totali'] if opt_opp_curr else 0.0
    opp_curr_modulo = opt_opp_curr['Modulo'] if opt_opp_curr else 'N/D'
    opp_sim_formations = list(dict.fromkeys([opp_curr_modulo, '3-5-2', '4-3-3', '4-2-3-1', '4-3-1-2']))[:4]
    
    target_players = []
    for tname in target_player_names:
        if is_player_to_release(tname, release_names):
            continue
        if tname in opp_pnames and tname in proj_map:
            p_data = dict(proj_map[tname])
            if is_player_to_release(p_data, release_names):
                continue
            target_players.append(p_data)

    if not target_players:
        return []

    target_xfv_sum = sum(safe_float(p.get('xFV', 0.0)) for p in target_players)
    target_cost_sum = sum(safe_int(p.get('Costo', 1)) for p in target_players)
    target_roles = set().union(*[parse_mantra_roles(p.get('RuoloMantra', '')) for p in target_players])
    num_targets = len(target_players)
    target_pnames_set = set(t['Giocatore'] for t in target_players)

    # Detect if taking target players creates an emergency for the opponent
    target_has_por = any('Por' in parse_mantra_roles(p.get('RuoloMantra', '')) for p in target_players)
    opp_pors_before = [p for p in opp_proj_list if 'Por' in parse_mantra_roles(p.get('RuoloMantra', ''))]
    opp_pors_rem = [p for p in opp_pors_before if p['Giocatore'] not in target_pnames_set]
    opp_pors_rem_starters = [p for p in opp_pors_rem if safe_int(p.get('Presenze', 0)) >= 3 or safe_float(p.get('P_Voto', 0)) >= 0.70]
    por_emergency = target_has_por and (len(opp_pors_rem) < 2 or len(opp_pors_rem_starters) == 0)

    # 3. Categorize my offerable players (Surplus, Bench, Starters, Goalkeepers)
    my_offerable = []
    my_gk_offerable = []
    my_outfield_offerable = []

    for p_row in my_proj_list:
        pname = p_row['Giocatore']
        # Release check: NEVER offer players to be released / out of Serie A
        if is_player_to_release(p_row, release_names) or is_player_to_release(pname, release_names):
            continue

        # Medical check: cannot trade injured or suspended players
        inj = classify_injury_status(pname)
        if not inj.get('Can_Be_Traded_Out', True):
            continue

        pres = safe_int(p_row.get('Presenze', 0))
        xfv = safe_float(p_row.get('xFV', 0.0))
        roles = parse_mantra_roles(p_row.get('RuoloMantra', ''))
        is_gk = ('Por' in roles)
        
        # Determine Tier
        if pname in my_surplus_set:
            tier = 'SURPLUS'
        elif pname in my_starters_set:
            # If target includes Por, allow user's starting GK to be traded as counterpart!
            if not allow_starters and not (is_gk and target_has_por):
                continue
            tier = 'TITOLARE'
        else:
            tier = 'PANCHINARO'

        # Basic activity filter: players with at least some presence or value
        if not is_gk and pres < 1 and xfv < 5.2 and tier != 'SURPLUS':
            continue

        p_info = dict(p_row)
        p_info['Tier'] = tier
        my_offerable.append(p_info)

        if is_gk:
            my_gk_offerable.append(p_info)
        else:
            my_outfield_offerable.append(p_info)

    # 4. Generate candidate packages to offer
    candidate_packages = []

    if por_emergency:
        # Crucial Rule: When target creates a goalkeeper emergency for the opponent,
        # every proposed package MUST include a reliable, active goalkeeper from our squad to avoid leaving their net empty!
        # (A reserve with 0 appearances cannot solve an emergency).
        viable_gks = [
            p for p in my_gk_offerable 
            if safe_int(p.get('Presenze', 0)) >= 2 or safe_float(p.get('P_Voto', 0)) >= 0.60 or p['Tier'] == 'TITOLARE'
        ]
        if not viable_gks and my_gk_offerable:
            viable_gks = my_gk_offerable

        if viable_gks:
            if num_targets == 1:
                if '1x1' in package_types:
                    for gk in viable_gks:
                        candidate_packages.append([gk])
                if '2x1' in package_types:
                    for gk in viable_gks:
                        for out in my_outfield_offerable[:16]:
                            candidate_packages.append([gk, out])
            elif num_targets == 2:
                if '2x2' in package_types:
                    for gk in viable_gks:
                        for out in my_outfield_offerable[:16]:
                            candidate_packages.append([gk, out])
                    if len(viable_gks) >= 2:
                        for gk_pair in itertools.combinations(viable_gks, 2):
                            candidate_packages.append(list(gk_pair))
                # 1x2 offer if user GK alone has high xFV
                for gk in viable_gks:
                    if safe_float(gk.get('xFV', 0)) >= target_xfv_sum * 0.70:
                        candidate_packages.append([gk])
                # 3x2 offers
                for gk in viable_gks:
                    for out_pair in itertools.combinations(my_outfield_offerable[:10], 2):
                        candidate_packages.append([gk, out_pair[0], out_pair[1]])
            else:
                for gk in viable_gks:
                    for comb in itertools.combinations(my_outfield_offerable[:10], num_targets - 1):
                        candidate_packages.append([gk] + list(comb))
    else:
        # Standard Outfield package sizes
        my_offerable_top = sorted(my_offerable, key=lambda x: safe_float(x.get('xFV', 0)), reverse=True)[:18]
        if num_targets == 1:
            if '1x1' in package_types:
                for p in my_offerable:
                    candidate_packages.append([p])
            if '2x1' in package_types:
                for pair in itertools.combinations(my_offerable_top, 2):
                    candidate_packages.append(list(pair))
        elif num_targets == 2:
            if '2x2' in package_types:
                for pair in itertools.combinations(my_offerable_top, 2):
                    candidate_packages.append(list(pair))
            for trio in itertools.combinations(my_offerable_top[:12], 3):
                candidate_packages.append(list(trio))
            for p in my_offerable:
                if safe_float(p.get('xFV', 0)) >= target_xfv_sum * 0.85:
                    candidate_packages.append([p])
        else:
            for comb in itertools.combinations(my_offerable_top, num_targets):
                candidate_packages.append(list(comb))

    pre_screened = []
    seen_combos = set()

    for give_pkg in candidate_packages:
        give_names = tuple(sorted(p['Giocatore'] for p in give_pkg))
        if give_names in seen_combos:
            continue
        seen_combos.add(give_names)

        give_xfv_sum = sum(safe_float(p.get('xFV', 0.0)) for p in give_pkg)
        give_cost_sum = sum(safe_int(p.get('Costo', 1)) for p in give_pkg)
        give_roles = set().union(*[parse_mantra_roles(p.get('RuoloMantra', '')) for p in give_pkg])
        give_n = len(give_pkg)

        # -------------------------------------------------------------
        # Filter A: Continuous Pairwise Status & Titolarità Balance (Vasi Comunicanti)
        # -------------------------------------------------------------
        pairwise_eval = evaluate_pairwise_trade_balance(give_pkg, target_players)
        if not pairwise_eval['is_valid']:
            continue

        give_eff_sum = pairwise_eval['give_tot_eff']
        target_eff_sum = pairwise_eval['target_tot_eff']

        if give_n == num_targets:
            # 1x1 or 2x2: effective value should be balanced (0.65x to 1.45x)
            if not (0.65 * target_eff_sum <= give_eff_sum <= 1.45 * target_eff_sum):
                continue
        elif give_n > num_targets:
            # Multi-to-one (2x1, 3x2): buyer can pay a slight premium (0.72x to 1.60x)
            if not (0.72 * target_eff_sum <= give_eff_sum <= 1.60 * target_eff_sum):
                continue
        else:
            # One-to-multi: giver gives high value (0.62x to 1.35x)
            if not (0.62 * target_eff_sum <= give_eff_sum <= 1.35 * target_eff_sum):
                continue

        # -------------------------------------------------------------
        # Filter B: Role Parity & Opponent Need Fit
        # -------------------------------------------------------------
        matched_weak_roles = []
        weakness_points = 0.0
        solved_bottlenecks = []

        for r in give_roles:
            if r in opp_weak_roles:
                sev = opp_weak_roles[r]
                matched_weak_roles.append(r)
                if sev == 'CRITICA':
                    weakness_points += 32.0
                    solved_bottlenecks.append(f"Risolve carenza CRITICA nel ruolo '{r}'")
                elif sev == 'ELEVATA':
                    weakness_points += 22.0
                    solved_bottlenecks.append(f"Colma buco ELEVATO nel ruolo '{r}'")
                else:
                    weakness_points += 12.0
                    solved_bottlenecks.append(f"Migliora profondità nel ruolo '{r}'")

        # Credibility check: if target has Pc or A, ensure offer is credible
        is_target_striker = any(r in ['Pc', 'A'] for r in target_roles)
        if is_target_striker and num_targets == 1 and give_n == 1:
            if not is_trade_role_parity_credible(give_pkg[0], target_players[0]):
                continue

        # If offer neither solves an opponent weakness nor offers superior value (and not goalkeeper replacement), skip
        if not matched_weak_roles and give_xfv_sum < target_xfv_sum and not por_emergency:
            continue

        # Package Tier Classification & Surplus Preference
        surplus_count = sum(1 for p in give_pkg if p['Tier'] == 'SURPLUS')
        starter_count = sum(1 for p in give_pkg if p['Tier'] == 'TITOLARE')

        if surplus_count == give_n:
            tipo_pacchetto = "🟢 Soli Surplus (Zero impatto titolari)"
            badge_tipo = "🟢 SOLI SURPLUS"
            tier_bonus = 45.0
        elif starter_count == 0:
            tipo_pacchetto = "🟡 Misto Surplus / Panchina"
            badge_tipo = "🟡 CON PANCHINARI"
            tier_bonus = 25.0
        else:
            tipo_pacchetto = "🔵 Con Titolare (Upgrade di Reparto)"
            badge_tipo = "🔵 CON TITOLARE"
            tier_bonus = 10.0

        # Special bonus if providing goalkeeper to solve goalkeeper emergency
        if por_emergency and any('Por' in parse_mantra_roles(p['RuoloMantra']) for p in give_pkg):
            tier_bonus += 35.0

        pre_score = (
            tier_bonus + 
            (weakness_points * 1.5) - 
            (abs(give_eff_sum - target_eff_sum) * 3.5)
        )
        pre_screened.append({
            'give_pkg': give_pkg,
            'give_xfv_sum': give_xfv_sum,
            'give_eff_sum': give_eff_sum,
            'target_eff_sum': target_eff_sum,
            'pairwise_pairs': pairwise_eval['pairwise_pairs'],
            'give_cost_sum': give_cost_sum,
            'give_roles': give_roles,
            'matched_weak_roles': matched_weak_roles,
            'weakness_points': weakness_points,
            'solved_bottlenecks': solved_bottlenecks,
            'tipo_pacchetto': tipo_pacchetto,
            'badge_tipo': badge_tipo,
            'tier_bonus': tier_bonus,
            'pre_score': pre_score
        })

    # Sort pre-screened packages by pre-score and simulate lineup on top 20 candidates for fast responsiveness
    pre_screened = sorted(pre_screened, key=lambda x: x['pre_score'], reverse=True)[:20]

    proposals = []
    # Identify relevant formations for fast simulation (My team)
    sim_formations = list(dict.fromkeys([my_curr_modulo, '3-5-2', '4-3-3', '4-2-3-1', '4-3-1-2']))[:4]

    for item in pre_screened:
        give_pkg = item['give_pkg']
        give_xfv_sum = item['give_xfv_sum']
        give_eff_sum = item['give_eff_sum']
        target_eff_sum = item['target_eff_sum']
        pairwise_pairs = item['pairwise_pairs']
        give_cost_sum = item['give_cost_sum']
        matched_weak_roles = item['matched_weak_roles']
        weakness_points = item['weakness_points']
        solved_bottlenecks = item['solved_bottlenecks']
        tipo_pacchetto = item['tipo_pacchetto']
        badge_tipo = item['badge_tipo']
        tier_bonus = item['tier_bonus']

        # -------------------------------------------------------------
        # Filter C: Fast Simulate Opponent Squad Post-Trade (Health & Lineup)
        # -------------------------------------------------------------
        opp_sim = simulate_opponent_post_trade(
            opp_team_name=opp_team_name,
            opp_proj_list=opp_proj_list,
            target_players=target_players,
            give_pkg=give_pkg,
            opt_opp_curr=opt_opp_curr,
            allowed_formations=opp_sim_formations
        )

        # STRICT RULE: Never leave the opponent with an uncovered net or fatal flaw!
        if opp_sim['is_goal_uncovered'] or opp_sim['has_fatal_flaw']:
            continue

        # -------------------------------------------------------------
        # Filter D: Fast Simulate My Squad Post-Trade
        # -------------------------------------------------------------
        give_pnames_set = set(p['Giocatore'] for p in give_pkg)
        my_new_roster_items = [p for p in my_proj_list if p['Giocatore'] not in give_pnames_set] + target_players
        df_my_new = pd.DataFrame(my_new_roster_items)
        
        opt_my_new = optimize_best_mantra_lineup(df_my_new, allowed_formations=sim_formations)
        if not opt_my_new:
            continue
        
        new_lineup_pts = opt_my_new['Punti_Attesi_Totali']
        delta_lineup_pts = round(new_lineup_pts - my_curr_pts, 2)

        # Starter sacrifice protection: if sacrificing a starter, lineup must NOT lose significant points!
        # Exception: if the starter is a direct positional replacement for an acquired target (e.g. Por for Por or Pc for Pc),
        # allow fixture-based single matchday variance down to -1.35 pts.
        has_starter = any(p['Tier'] == 'TITOLARE' for p in give_pkg)
        is_same_pos_replacement = any(
            any(r in target_roles for r in parse_mantra_roles(p.get('RuoloMantra', '')))
            for p in give_pkg if p['Tier'] == 'TITOLARE'
        )
        min_allowed_delta = -1.35 if is_same_pos_replacement else -0.15
        if has_starter and delta_lineup_pts < min_allowed_delta:
            continue

        # Opponent Appeal Score (0 to 100%)
        base_appeal = 38.0
        val_incentive = np.clip((give_eff_sum - target_eff_sum) * 6.0, -15.0, 25.0)
        opp_pts_incentive = np.clip(opp_sim['delta_opp_pts'] * 12.0, -25.0, 30.0)
        reassurance_bonus = 20.0 if opp_sim.get('reassurances') else 0.0
        flaw_penalty = 30.0 * len(opp_sim.get('critical_flaws', []))
        opp_appeal = int(np.clip(base_appeal + weakness_points + val_incentive + opp_pts_incentive + reassurance_bonus - flaw_penalty, 15.0, 98.0))

        # Overall Trade Ranking Score
        total_score = (
            (opp_appeal * 0.45) +
            (tier_bonus) +
            (delta_lineup_pts * 22.0) +
            (opp_sim['delta_opp_pts'] * 10.0) +
            (8.0 if not opt_my_new.get('Ha_Problemi_Copertura', False) else -8.0) +
            (12.0 if not opp_sim.get('critical_flaws') else -20.0)
        )

        # -------------------------------------------------------------
        # Filter E: Tailored Negotiation Argument & WhatsApp Pitch
        # -------------------------------------------------------------
        give_str = " + ".join([f"{p['Giocatore']} ({p['RuoloMantra']})" for p in give_pkg])
        target_str = " + ".join([f"{p['Giocatore']} ({p['RuoloMantra']})" for p in target_players])
        reassure_txt = ""
        if opp_sim.get('reassurances'):
            reassure_txt = f" Inoltre {' '.join(opp_sim['reassurances'])}"

        por_given = [p['Giocatore'] for p in give_pkg if 'Por' in parse_mantra_roles(p.get('RuoloMantra', ''))]
        out_given = [p['Giocatore'] for p in give_pkg if 'Por' not in parse_mantra_roles(p.get('RuoloMantra', ''))]
        pts_clause = f" (+{opp_sim['delta_opp_pts']:.2f} pt attesi)" if opp_sim['delta_opp_pts'] > 0 else ""

        if target_has_por and por_given:
            gk_txt = ", ".join(por_given)
            out_txt = f", e con {', '.join(out_given)} vi rinforzate in movimento" if out_given else ""
            leva = (
                f"Offerta strutturata per salvaguardare la porta avversaria: cedendo {target_str}, l'avversario riceve subito **{gk_txt}** "
                f"evitando di rimanere scoperto tra i pali{out_txt}. La sua formazione tipo resta al 100% coperta ({opp_sim['opp_new_modulo']}, {opp_sim['delta_opp_pts']:+.2f} pt)."
            )
            pitch_msg = (
                f"Ciao! Ho formulato una proposta pensata per proteggere la vostra formazione: per non lasciarvi scoperti tra i pali "
                f"dopo aver ceduto {target_str}, vi ho inserito {gk_txt} come titolare fisso in porta{out_txt}. In questo modo la vostra porta "
                f"resta blindata al 100% e la vostra formazione tipo ne esce solida e competitiva{pts_clause} ({opp_sim['opp_new_modulo']}). Che ne dite?"
            )
        elif matched_weak_roles:
            roles_txt = ", ".join(set(matched_weak_roles))
            leva = (
                f"L'avversario ha carenze su **{roles_txt}** ({'; '.join(solved_bottlenecks[:2])}). "
                f"Offrendo {give_str} colmi il suo bisogno più urgente senza creare nuove falle.{reassure_txt}"
            )
            pitch_msg = (
                f"Ciao! Ho visto che per {opp_team_name} farebbe comodo rinforzare lo slot {roles_txt} "
                f"dove avete rotazioni corte. Che ne dite se impostiamo uno scambio {give_str} per {target_str}? "
                f"A voi risolve l'emergenza di formazione garantendo copertura titolare immediata senza creare nuove falle{pts_clause}, "
                f"e per noi quadra a livello tattico. È un ottimo affare per entrambi!"
            )
        else:
            leva = (
                f"Offerta basata su equivalenza di fanta-valore ({give_xfv_sum:.2f} xFV vs {target_xfv_sum:.2f} xFV). "
                f"L'avversario riceve asset pronti all'uso e la sua formazione resta integra ({opp_sim['opp_new_modulo']}, {opp_sim['delta_opp_pts']:+.2f} pt attesi).{reassure_txt}"
            )
            pitch_msg = (
                f"Ciao! Ti andrebbe di valutare uno scambio tra {give_str} per {target_str}? "
                f"I valori tecnici sono allineati, la vostra formazione resta coperta e ben bilanciata{pts_clause} ({opp_sim['opp_new_modulo']}). Che ne pensi?"
            )

        proposals.append({
            'Score': round(total_score, 1),
            'Tipo_Pacchetto': tipo_pacchetto,
            'Badge_Tipo': badge_tipo,
            'Appetibilita_Avversario': opp_appeal,
            'Tu_Cedi': [
                {
                    'Giocatore': p['Giocatore'],
                    'Squadra': p.get('Squadra', ''),
                    'RuoloMantra': p.get('RuoloMantra', ''),
                    'xFV': safe_float(p.get('xFV', 0.0)),
                    'FM': safe_float(p.get('FM_Stagione', 0.0)),
                    'Costo': safe_int(p.get('Costo', 0)),
                    'Tier': p.get('Tier', 'PANCHINARO'),
                    'P_Voto': safe_float(p.get('P_Voto', 0.8)),
                    'Status_Titolarita': p.get('Status_Titolarita', '🟢 TITOLARE')
                } for p in give_pkg
            ],
            'Tu_Ricevi': [
                {
                    'Giocatore': p['Giocatore'],
                    'Squadra': p.get('Squadra', ''),
                    'RuoloMantra': p.get('RuoloMantra', ''),
                    'xFV': safe_float(p.get('xFV', 0.0)),
                    'FM': safe_float(p.get('FM_Stagione', 0.0)),
                    'Costo': safe_int(p.get('Costo', 0)),
                    'P_Voto': safe_float(p.get('P_Voto', 0.8)),
                    'Status_Titolarita': p.get('Status_Titolarita', '🟢 TITOLARE')
                } for p in target_players
            ],
            'Totale_xFV_Ceduti': round(give_xfv_sum, 2),
            'Totale_xFV_Ricevuti': round(target_xfv_sum, 2),
            'Delta_xFV': round(target_xfv_sum - give_xfv_sum, 2),
            'Valore_Mercato_Ceduti': round(give_eff_sum, 2),
            'Valore_Mercato_Ricevuti': round(target_eff_sum, 2),
            'Delta_Valore_Mercato': round(target_eff_sum - give_eff_sum, 2),
            'Accoppiamento_Coppie': pairwise_pairs,
            'Delta_Punti_Titolari': delta_lineup_pts,
            'Modulo_Titolare_Nuovo': opt_my_new.get('Modulo', my_curr_modulo),
            'Punti_Titolari_Nuovi': new_lineup_pts,
            'Copertura_Nuova': '✅ Copertura 100%' if not opt_my_new.get('Ha_Problemi_Copertura', False) else f"⚠️ Rischio ({len(opt_my_new.get('Slot_Scoperti', []))} scoperti)",
            'Carenze_Risolte': solved_bottlenecks,
            'Leva_di_Trattativa': leva,
            'Messaggio_Trattativa': pitch_msg,
            # OPPONENT FORMATION POST-TRADE INSIGHTS
            'Modulo_Avversario_Nuovo': opp_sim['opp_new_modulo'],
            'Punti_Avversario_Nuovi': opp_sim['opp_new_pts'],
            'Delta_Punti_Avversario': opp_sim['delta_opp_pts'],
            'Reassurances_Avversario': opp_sim.get('reassurances', []),
            'Nuove_Criticita_Avversario': opp_sim.get('critical_flaws', []),
            'Simulazione_Payload': {
                'give_names': [p['Giocatore'] for p in give_pkg],
                'receive_names': [p['Giocatore'] for p in target_players]
            }
        })

    # Sort proposals by highest Score (Surplus priority + Opponent fit + Net lineup benefit)
    proposals = sorted(proposals, key=lambda x: x['Score'], reverse=True)
    return proposals[:max_proposals]
