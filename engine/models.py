"""
Statistical Models and Expected FantaVoto (xFV) Engine.
Integrates Bayesian ratings, real advanced metrics (xG, xA, shots, pass accuracy, duels),
FDR opponent difficulty, and Mantra D-factor simulation with Goalkeeper inclusion and Clean Sheet bonus.
"""

import os
import sys
import math
import numpy as np
import pandas as pd

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.fanta_calendar import get_fixture_info, get_or_create_calendar, compute_dynamic_team_ratings
from engine.understat_loader import get_team_defensive_xga

def norm_cdf(x, mu=0.0, sigma=1.0):
    """Cumulative normal distribution function without external scipy dependency."""
    return 0.5 * (1.0 + math.erf((x - mu) / (sigma * math.sqrt(2.0))))

def calculate_expected_dfactor(ratings_list):
    """
    Computes expected Mantra D-Factor bonus for a defensive unit.
    Includes Goalkeeper + Defenders (3 or 4).
    Tiers:
      MV < 6.00: 0 pts
      6.00 <= MV < 6.25: +1 pt
      6.25 <= MV < 6.50: +2 pts
      6.50 <= MV < 6.75: +3 pts
      6.75 <= MV < 7.00: +4 pts
      MV >= 7.00: +5 pts
    """
    if not ratings_list or len(ratings_list) < 2:
        return 0.0, 0.0
        
    n = len(ratings_list)
    mu_unit = float(np.mean(ratings_list))
    # Typical standard error of the mean for defensive ratings in Serie A
    sigma_unit = 0.52 / math.sqrt(n)
    
    # Probabilities of reaching tiers
    p_ge_600 = 1.0 - norm_cdf(6.00, mu_unit, sigma_unit)
    p_ge_625 = 1.0 - norm_cdf(6.25, mu_unit, sigma_unit)
    p_ge_650 = 1.0 - norm_cdf(6.50, mu_unit, sigma_unit)
    p_ge_675 = 1.0 - norm_cdf(6.75, mu_unit, sigma_unit)
    p_ge_700 = 1.0 - norm_cdf(7.00, mu_unit, sigma_unit)
    
    # Expected points = sum of incremental tier values
    ev_dfactor = (p_ge_600 * 1.0) + (p_ge_625 * 1.0) + (p_ge_650 * 1.0) + (p_ge_675 * 1.0) + (p_ge_700 * 1.0)
    return round(ev_dfactor, 2), round(mu_unit, 2)

def predict_player_xfv(player_row, matchday=6, calendar=None, ratings_cache=None):
    """
    Calculates detailed expected performance and xFV for a player at a specific matchday.
    """
    base_dict = player_row.to_dict() if hasattr(player_row, 'to_dict') else dict(player_row)
    squadra = str(player_row.get('Squadra', '')).strip()
    giocatore = str(player_row.get('Giocatore', '')).strip()
    ruolo_mantra = str(player_row.get('RuoloMantra', '')).strip()
    ruolo_classic = str(player_row.get('RuoloClassic', '')).strip()
    
    fix = get_fixture_info(squadra, matchday, calendar, ratings_cache=ratings_cache)
    fdr = fix['FDR']
    is_home = fix['IsHome']
    opp_xga = fix['Opp_xGA']
    opp_xg_att = fix['Opp_xG_Attack']
    
    # Baselines
    mv_stag = float(player_row.get('MV_Stagione', 6.0))
    fm_stag = float(player_row.get('FM_Stagione', 6.0))
    mv_last3 = float(player_row.get('MV_Ultime3', mv_stag))
    mv_triennio = float(player_row.get('MV_Triennio', mv_stag))
    
    # Real In-Game Underlying Metrics (Understat & Match Data)
    xg_90 = float(player_row.get('xG_90', 0.0))
    xa_90 = float(player_row.get('xA_90', 0.0))
    tiri_90 = float(player_row.get('Tiri_90', 0.0))
    kp_90 = float(player_row.get('Key_Passes_90', 0.0))
    minuti_reali = float(player_row.get('Minuti_Reali', 0.0))
    delta_xg = float(player_row.get('Delta_xG', 0.0))
    delta_xa = float(player_row.get('Delta_xA', 0.0))
    pass_acc = float(player_row.get('Pass_Acc_Pct', 80.0))
    duels_pct = float(player_row.get('Duelli_Vinti_Pct', 50.0))
    recuperi_90 = float(player_row.get('Recuperi_90', 3.0))
    
    raw_presenze = float(player_row.get('Presenze', 0))
    presenze = max(1.0, raw_presenze)
    tot_giornate = 7.0  # Current Serie A matchdays played in season 2026/27
    
    gf_tot = float(player_row.get('GF', 0))
    gf_per_game = gf_tot / presenze
    
    ass_tot = float(player_row.get('ASS', 0))
    ass_per_game = ass_tot / presenze
    
    amm_tot = float(player_row.get('AMM', 0))
    amm_rate = min(0.35, max(0.05, (amm_tot / presenze) * 0.7 + 0.05 * (fdr >= 4)))
    
    is_por = 'Por' in ruolo_mantra or ruolo_classic == 'P'
    # D-Factor eligible roles in Mantra: Por, Dd, Ds, Dc, B, E, M
    is_dfactor_role = any(r in ruolo_mantra for r in ['Por', 'Dd', 'Ds', 'Dc', 'B', 'E', 'M']) or is_por

    # 0. Titolarità & Probabilità di Andare a Voto (P_Voto)
    min_per_app = (minuti_reali / raw_presenze) if raw_presenze > 0 else 0.0
    pct_min_tot = (minuti_reali / (tot_giornate * 90.0)) * 100.0 if tot_giornate > 0 else 0.0
    
    if raw_presenze <= 0:
        p_voto = 0.05
        status_titolarita = "🔴 RISERVA"
    else:
        # Realistic blend between attendance rate and actual minutes played per game:
        # A sub entering at minute 75 is NOT a full starter and faces high S.V. / low-rating risk.
        density = min(1.0, min_per_app / 70.0)
        att_frac = raw_presenze / tot_giornate
        p_voto = float(np.clip(
            0.05 + 0.35 * att_frac + 0.60 * (att_frac * density),
            0.05,
            0.98
        ))
        if (min_per_app >= 55.0 and pct_min_tot >= 45.0) or (min_per_app >= 68.0 and raw_presenze >= 3) or pct_min_tot >= 65.0:
            status_titolarita = "🟢 TITOLARE FISSO"
        elif (min_per_app >= 45.0 and pct_min_tot >= 28.0) or (min_per_app >= 40.0 and raw_presenze >= 4 and pct_min_tot >= 24.0):
            status_titolarita = "🟡 CO-TITOLARE"
        elif raw_presenze >= 2:
            status_titolarita = "🟠 SUBENTRANTE"
        else:
            status_titolarita = "🔴 RISERVA"

    # Medical Availability & Suspension Override
    try:
        from engine.injuries_manager import classify_injury_status
        inj_info = classify_injury_status(giocatore)
        if inj_info.get('Is_Injured', False):
            if inj_info.get('Is_Long_Term', False):
                p_voto = 0.01
                status_titolarita = "🔴 INFORTUNATO (LUNGO STOP)"
            elif inj_info.get('Stato') == 'Squalificato':
                p_voto = 0.01
                status_titolarita = "🔴 SQUALIFICATO"
            else:
                p_voto = min(0.35, p_voto * 0.40)
                status_titolarita = "🟠 IN DUBBIO (INFORTUNIO)"
    except Exception:
        pass

    # 1. Bayesian Shrinkage on Sample Size (Small Sample Correction)
    # A player with only 1 or 2 matches has high noise in MV and Sufficiency; regress towards prior
    prior_mv = mv_triennio if mv_triennio > 0 else 6.0
    w_sample = raw_presenze / (raw_presenze + 3.0) if raw_presenze > 0 else 0.0
    regressed_mv_stag = (w_sample * mv_stag) + ((1.0 - w_sample) * prior_mv)
    regressed_mv_last3 = mv_last3 if raw_presenze >= 3 else regressed_mv_stag

    # Sufficiency rate (% of match votes >= 6.0)
    pct_suff = float(player_row.get('Pct_Sufficienza', 0.0))
    if pct_suff <= 0 or raw_presenze < 3:
        bayesian_suff = 0.5 * (1.0 + math.erf((prior_mv - 6.0) / (0.45 * math.sqrt(2.0)))) * 100.0
        if raw_presenze > 0 and pct_suff > 0:
            pct_suff = round((w_sample * pct_suff) + ((1.0 - w_sample) * bayesian_suff), 1)
        else:
            pct_suff = round(bayesian_suff, 1)

    # Pure Vote Prediction (Voto Puro) using regressed ratings
    if is_dfactor_role:
        base_mv = (regressed_mv_stag * 0.60) + (regressed_mv_last3 * 0.20) + (prior_mv * 0.20)
    else:
        base_mv = (regressed_mv_stag * 0.45) + (regressed_mv_last3 * 0.35) + (prior_mv * 0.20)
    
    # Role-differentiated impact of real match activity on journalist ratings:
    att_action_delta = np.clip((tiri_90 - 1.8) * 0.05, -0.15, 0.20)
    create_action_delta = np.clip((kp_90 - 1.4) * 0.04, -0.12, 0.18)
    def_action_delta = (
        0.25 * ((duels_pct - 50.0) / 100.0) +
        0.15 * ((pass_acc - 80.0) / 100.0) +
        0.02 * (recuperi_90 - 3.5)
    )
    
    # Sufficiency impact for D-Factor players:
    # Serie A median sufficiency is ~60%. Above 75% represents defensive anchors; below 45% risks catastrophic sub-6 ratings.
    suff_impact = np.clip((pct_suff - 60.0) / 100.0 * 0.22, -0.15, 0.20) if is_dfactor_role else 0.0

    if any(r in ruolo_mantra for r in ['Pc', 'A']):
        action_delta = att_action_delta
    elif any(r in ruolo_mantra for r in ['T', 'W']):
        action_delta = (0.6 * create_action_delta) + (0.4 * att_action_delta)
    elif any(r in ruolo_mantra for r in ['C']):
        action_delta = (0.5 * create_action_delta) + (0.5 * def_action_delta) + (0.5 * suff_impact if is_dfactor_role else 0.0)
    elif any(r in ruolo_mantra for r in ['M', 'Dc', 'Dd', 'Ds', 'B']):
        action_delta = def_action_delta + suff_impact
    elif any(r in ruolo_mantra for r in ['E']):
        action_delta = (0.5 * create_action_delta) + (0.5 * def_action_delta) + suff_impact
    else:
        action_delta = suff_impact if is_dfactor_role else 0.0
        
    home_bonus = 0.12 if is_home else -0.06
    fdr_map = {1: 0.18, 2: 0.08, 3: 0.00, 4: -0.15, 5: -0.32}
    fdr_penalty = fdr_map.get(int(fdr), -0.08 * (fdr - 3.0))
    
    if is_por:
        # Goalkeeper pure vote reflects save capability and match reliability (no double FDR penalty)
        pred_voto = round(max(5.1, min(7.8, base_mv + suff_impact + home_bonus)), 2)
    else:
        pred_voto = round(max(5.1, min(7.8, base_mv + action_delta + home_bonus + fdr_penalty)), 2)
    
    # Opponent defense scaling and venue multiplier
    opp_factor = opp_xga / 1.30
    venue_factor = 1.10 if is_home else 0.90
    
    # D-Factor systemic value-add:
    # A reliable defender with high MV and sufficiency adds direct value to the defensive modifier for the whole team.
    if is_dfactor_role:
        dfactor_val_add = round(np.clip((pred_voto - 6.0) * 0.40 * (pct_suff / 100.0), -0.20, 0.35), 2)
        if pct_suff >= 78.0:
            dfactor_badge = f"🛡️ ANCORA DIFENSIVA ({pct_suff}% >=6)"
        elif pct_suff < 45.0:
            dfactor_badge = f"⚠️ RISCHIO D-FACTOR ({pct_suff}% >=6)"
        else:
            dfactor_badge = f"Sufficienza: {pct_suff}%"
    else:
        dfactor_val_add = 0.0
        dfactor_badge = ""
    
    # 2. Bonus & Malus Projections
    if is_por:
        exp_gf = 0.0
        exp_xa = 0.0
        
        # Goalkeeper Two-Factor Conceded Goals & Clean Sheet Model:
        # Factor 1: Goalkeeper Shot-Stopping, Goals Prevented & Blunders
        save_pct = float(player_row.get('Pct_Parate', 70.0))
        if math.isnan(save_pct) or save_pct <= 0:
            save_pct = 70.0
            
        psxg = float(player_row.get('PSxG', 0.0))
        goals_prevented = float(player_row.get('Goals_Prevented', 0.0))
        gp_90 = float(player_row.get('Goals_Prevented_90', 0.0))
        blunders = int(player_row.get('Errors_Leading_To_Goal', 0))
        blunder_rate = float(player_row.get('Blunder_Rate_90', 0.0))
        
        # Goals Prevented adjustment:
        # A goalkeeper who prevents goals on tough shots (e.g. Carnesecchi +0.72/90) reduces expected goals conceded
        # A goalkeeper with negative goals prevented (e.g. De Gea -0.56/90) leaks more goals
        gp_adj = float(np.clip(gp_90 * 0.16, -0.22, 0.25))
        
        # Blunder Risk:
        # A goalkeeper with blunders faces an elevated risk of conceding unforced soft goals
        blunder_penalty = float(min(0.30, blunders * 0.08))
        
        # Average Serie A save rate is ~70.0%. Each +10% above average reduces conceded goals.
        save_factor = 1.0 - ((save_pct - 70.0) / 100.0 * 0.55) - gp_adj + blunder_penalty
        save_factor = max(0.55, min(1.40, save_factor))
        
        # Factor 2: Team defensive capability (regressed with team structural rating)
        team_rating = ratings_cache.get(squadra, {}) if ratings_cache else {}
        power = float(team_rating.get('Power_Dinamico', 50.0))
        prior_xga = 1.40 - ((power - 50.0) / 100.0 * 1.15)
        raw_xga = get_team_defensive_xga(squadra)
        team_xga = round((0.40 * raw_xga) + (0.60 * prior_xga), 2)
        team_def_factor = max(0.55, min(1.55, team_xga / 1.40))
        
        # Venue factor (home defense concedes less than away)
        venue_factor_gk = 0.88 if is_home else 1.14
        
        # Expected goals conceded: lambda = opp_xg_att * team_def_factor * save_factor * venue_factor
        exp_gs = round(max(0.15, opp_xg_att * team_def_factor * save_factor * venue_factor_gk), 2)
        
        # Clean Sheet probability using Poisson P(0) = e^(-lambda)
        p_clean_sheet = round(math.exp(-exp_gs), 3)
        
        # Imbattibilità bonus: +1.0 pt * P(Clean Sheet)
        exp_imbattibilita = round(1.0 * p_clean_sheet, 2)
        exp_cards = round(0.04, 2)
        
        # Goalkeeper xFV: Voto - Malus Gol Subiti + Bonus Imbattibilita - Malus Cartellini + D-Factor
        raw_xfv = round(pred_voto - exp_gs + exp_imbattibilita - (exp_cards * 0.5) + dfactor_val_add, 2)
        # SV penalty for second/third keepers who rarely play:
        sv_penalty = round((1.0 - p_voto) * 2.0, 2)
        if p_voto <= 0.02:
            raw_xfv = 0.0
            xfv = 0.0
        elif p_voto <= 0.15 or (raw_presenze == 0 and p_voto <= 0.35):
            # Non-playing reserves are scaled directly by their playing probability
            xfv = round(p_voto * max(0.0, raw_xfv), 2)
        else:
            xfv = round(raw_xfv - sv_penalty, 2)
        rationale = (
            f"CS {int(p_clean_sheet*100)}% (+{exp_imbattibilita:.2f}pt) | "
            f"G.Prevented: {goals_prevented:+.2f} ({gp_90:+.2f}/90) | "
            f"Errori: {blunders} | Parate: {save_pct:.1f}% | Exp GS: {exp_gs:.2f}"
        )
        
        details = {
            **base_dict,
            'Giocatore': giocatore,
            'Squadra': squadra,
            'RuoloMantra': ruolo_mantra,
            'RuoloClassic': ruolo_classic,
            'Match': fix['Label'],
            'FDR': fdr,
            'IsHome': is_home,
            'Pred_Voto': pred_voto,
            'Exp_GF': 0.0,
            'Exp_ASS': 0.0,
            'Exp_GS': exp_gs,
            'Clean_Sheet_Prob': p_clean_sheet,
            'Bonus_Imbattibilita': exp_imbattibilita,
            'Pct_Parate': save_pct,
            'PSxG': round(psxg, 2),
            'Goals_Prevented': round(goals_prevented, 2),
            'Goals_Prevented_90': round(gp_90, 2),
            'Errors_Leading_To_Goal': blunders,
            'Blunder_Rate_90': round(blunder_rate, 2),
            'Team_xGA': team_xga,
            'P_Voto': round(p_voto, 2),
            'Status_Titolarita': status_titolarita,
            'Min_Per_App': int(min_per_app),
            'Presenze_Tot': int(raw_presenze),
            'SV_Penalty': sv_penalty,
            'xFV_Raw': raw_xfv,
            'Exp_Cards': exp_cards,
            'xFV': xfv,
            'D_Factor_Contribution': round(pred_voto, 2),
            'D_Factor_Val_Add': dfactor_val_add,
            'D_Factor_Badge': dfactor_badge,
            'Pct_Sufficienza': pct_suff,
            'Rationale': rationale
        }
    else:
        # Outfield player: Real Shot Volume & Chance Quality Model
        is_striker = any(r in ruolo_mantra for r in ['Pc', 'A'])
        is_w_or_t = any(r in ruolo_mantra for r in ['W', 'T'])
        
        # Bayesian shrinkage on goal/assist rates:
        # Avoid exploding projections for small sample sizes (e.g. 1 goal in 2 games)
        prior_gf_rate = 0.25 if is_striker else (0.10 if is_w_or_t else 0.03)
        prior_ass_rate = 0.12 if is_w_or_t else (0.08 if is_striker or 'C' in ruolo_mantra else 0.03)
        w_att_sample = raw_presenze / (raw_presenze + 4.0) if raw_presenze > 0 else 0.0
        shrunk_gf_rate = (w_att_sample * gf_per_game) + ((1.0 - w_att_sample) * prior_gf_rate)
        shrunk_ass_rate = (w_att_sample * ass_per_game) + ((1.0 - w_att_sample) * prior_ass_rate)
        
        shot_threat = tiri_90 * 0.105
        kp_threat = kp_90 * 0.095
        
        if minuti_reali >= 60 and (xg_90 > 0 or tiri_90 > 0):
            # Clinical finishing factor: ONLY for recognized strikers with meaningful sample
            finishing_factor = max(0.0, shrunk_gf_rate) if is_striker else 0.0
            base_goal_threat = (0.40 * xg_90) + (0.25 * shot_threat) + (0.35 * finishing_factor)
            regressed_xg = max(0.02, base_goal_threat)
            
            base_ass_threat = (0.45 * xa_90) + (0.25 * kp_threat) + (0.30 * shrunk_ass_rate)
            regressed_xa = max(0.01, base_ass_threat)
        else:
            role_base_goal = 0.22 if is_striker else (0.10 if is_w_or_t else 0.02)
            regressed_xg = max(0.01, (0.60 * shrunk_gf_rate) + (0.40 * role_base_goal))
            
            role_base_ass = 0.12 if is_w_or_t else (0.06 if 'C' in ruolo_mantra else 0.02)
            regressed_xa = max(0.01, (0.60 * shrunk_ass_rate) + (0.40 * role_base_ass))
            
        # Expected minutes scaling on attacking output (smooth scaling for active rotation players)
        min_factor = float(np.clip(min_per_app / 75.0, 0.15, 1.0)) if raw_presenze > 0 else 0.10
        exp_gf = round(max(0.0, regressed_xg * opp_factor * venue_factor * min_factor), 3)
        exp_ass = round(max(0.0, regressed_xa * opp_factor * venue_factor * min_factor), 3)
        exp_cards = round(amm_rate, 2)
        
        # Outfield xFV including D-Factor reliability value-add
        raw_xfv = round(
            pred_voto +
            (3.0 * exp_gf) +
            (1.0 * exp_ass) -
            (0.5 * exp_cards) -
            (1.0 * 0.015) +
            dfactor_val_add,
            2
        )
        
        # Progressive Titolarità / Senza Voto (S.V.) penalty
        # Nailed starters (p_voto >= 0.85) have minimal risk penalty;
        # Late substitutes (p_voto < 0.60) are progressively discounted to protect the starting XI
        p_absence = max(0.0, 1.0 - p_voto)
        sv_penalty = round((p_absence ** 1.3) * 1.65, 2)
        if p_voto <= 0.02:
            raw_xfv = 0.0
            xfv = 0.0
        elif p_voto <= 0.15 or (raw_presenze == 0 and p_voto <= 0.35):
            # Non-playing reserves are scaled directly by their playing probability
            xfv = round(p_voto * max(0.0, raw_xfv), 2)
        else:
            xfv = round(raw_xfv - sv_penalty, 2)
        
        # D-Factor contribution
        dfactor_val = round(pred_voto, 2) if is_dfactor_role else 0.0
        
        # Detailed Rationale
        if is_dfactor_role and not any(r in ruolo_mantra for r in ['Pc', 'A']):
            rationale = f"Suff. {pct_suff}% (voti>=6) | Titolarità {int(p_voto*100)}% | D-Factor base: {pred_voto:.2f}"
        elif any(r in ruolo_mantra for r in ['Pc', 'A']):
            rationale = f"Tiri: {tiri_90:.1f}/90 | xG: {xg_90:.2f} | Titolarità {int(p_voto*100)}% | Exp GF: {exp_gf:.2f}"
        elif any(r in ruolo_mantra for r in ['W', 'T']):
            rationale = f"KP: {kp_90:.1f}/90 | xA: {xa_90:.2f} | Titolarità {int(p_voto*100)}% | Exp ASS: {exp_ass:.2f}"
        else:
            rationale = f"Voto base: {pred_voto:.2f} | Titolarità {int(p_voto*100)}% | Exp GF: {exp_gf:.2f}"
            
        details = {
            **base_dict,
            'Giocatore': giocatore,
            'Squadra': squadra,
            'RuoloMantra': ruolo_mantra,
            'RuoloClassic': ruolo_classic,
            'Match': fix['Label'],
            'FDR': fdr,
            'IsHome': is_home,
            'Pred_Voto': pred_voto,
            'Exp_GF': exp_gf,
            'Exp_ASS': exp_ass,
            'Exp_GS': 0.0,
            'Clean_Sheet_Prob': 0.0,
            'Bonus_Imbattibilita': 0.0,
            'Pct_Parate': 0.0,
            'Team_xGA': 0.0,
            'P_Voto': round(p_voto, 2),
            'Status_Titolarita': status_titolarita,
            'Min_Per_App': int(min_per_app),
            'Presenze_Tot': int(raw_presenze),
            'SV_Penalty': sv_penalty,
            'xFV_Raw': raw_xfv,
            'Exp_Cards': exp_cards,
            'xFV': xfv,
            'D_Factor_Contribution': dfactor_val,
            'D_Factor_Val_Add': dfactor_val_add,
            'D_Factor_Badge': dfactor_badge,
            'Pct_Sufficienza': pct_suff,
            'Rationale': rationale
        }
        
    return details

def batch_predict_xfv(df_players, matchday=6, calendar=None, ratings_cache=None):
    """Computes projections for a collection of players for a specific matchday."""
    if calendar is None:
        calendar = get_or_create_calendar()
    if ratings_cache is None:
        ratings_cache, _ = compute_dynamic_team_ratings(matchday)
        
    results = []
    for _, row in df_players.iterrows():
        try:
            res = predict_player_xfv(row, matchday=matchday, calendar=calendar, ratings_cache=ratings_cache)
            results.append(res)
        except Exception as e:
            pass
            
    df_res = pd.DataFrame(results).sort_values(by='xFV', ascending=False)
    return df_res

if __name__ == '__main__':
    from engine.data_loader import sync_and_build_database
    import os
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    master_path = os.path.join(data_dir, "players_master.csv")
    if not os.path.exists(master_path):
        sync_and_build_database()
        
    df_m = pd.read_csv(master_path)
    cal = get_or_create_calendar()
    
    print("\n--- TEST TOP 10 PLAYERS BY xFV (GIORNATA 6) ---")
    df_preds = batch_predict_xfv(df_m, matchday=6, calendar=cal)
    print(df_preds[['Giocatore', 'Squadra', 'RuoloMantra', 'Match', 'FDR', 'Pred_Voto', 'Exp_GF', 'xFV']].head(10).to_string(index=False))
    
    print("\n--- TEST D-FACTOR DEFENSIVE SIMULATION ---")
    ev_df, mu = calculate_expected_dfactor([6.4, 6.3, 6.2, 6.1, 6.5])
    print(f"Mean Rating: {mu} -> Expected D-Factor Bonus: +{ev_df} pts")
