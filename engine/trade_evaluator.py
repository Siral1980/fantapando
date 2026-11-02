"""
Hybrid Mantra & Classic Trade Evaluator (Valutatore di Scambi Ibrido).
Combines 4 analytical pillars into a unified, realistic evaluation:
1. Valore Netto Effettivo (Injury & Calendar Aware, 35% weight)
2. Momentum & Trend Recente (Forma Ultime Gare & Understat Buy-Low / Sell-High, 25% weight)
3. Solidità di Rosa & Garanzia Voto (Minutaggio, Titolari Fissi & D-Factor, 20% weight)
4. Fanta-Plusvalenza & Gerarchia Star (Quality over Quantity / Valore Slot, 20% weight)
"""

import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.fanta_calendar import get_or_create_calendar, get_fixture_info
from engine.models import predict_player_xfv
from engine.injuries_manager import load_injuries_data, get_player_status, parse_injury_details
from engine.probable_lineups import load_probable_lineups, get_player_probable_info
from engine.trade_finder import compute_real_starter_status


def compute_package_weights(df_package, weight_mode='rank_decay'):
    """
    Computes normalized weights (summing to 1.0) for players in a multi-player package.
    Modes:
    - 'rank_decay' (default): Decaying rank weights prioritizing the centerpiece / star.
    - 'simple_mean': Equal weights (1/K) -> simple arithmetic mean.
    - 'value_proportional': Weights proportional to player's season FM/MV.
    - 'raw_sum': Weight = 1.0 for each player (pure additive sum).
    """
    k = len(df_package)
    if k == 0:
        return {}
    if k == 1:
        return {df_package.iloc[0]['Giocatore']: 1.0}
    if weight_mode == 'raw_sum':
        return {p: 1.0 for p in df_package['Giocatore']}

    sort_key = 'FM_Stagione' if 'FM_Stagione' in df_package.columns else 'Costo'
    df_sorted = df_package.sort_values(by=sort_key, ascending=False).reset_index(drop=True)

    weights = {}
    if weight_mode == 'simple_mean':
        w_val = 1.0 / k
        for _, row in df_sorted.iterrows():
            weights[row['Giocatore']] = w_val
    elif weight_mode == 'value_proportional':
        vals = [max(1.0, float(r.get('FM_Stagione', 6.0))) for _, r in df_sorted.iterrows()]
        s_val = sum(vals)
        for i, row in df_sorted.iterrows():
            weights[row['Giocatore']] = vals[i] / s_val
    else:  # 'rank_decay'
        raw_alphas = [(k - i) ** 0.6 for i in range(k)]
        s_alpha = sum(raw_alphas)
        for i, row in df_sorted.iterrows():
            weights[row['Giocatore']] = raw_alphas[i] / s_alpha

    total_w = sum(weights.values())
    if total_w > 0:
        weights = {p: w / total_w for p, w in weights.items()}
    return weights


def _weighted_metric(df, weights, col, default=0.0):
    """Helper to compute weighted average of a column given player weights."""
    if col not in df.columns or df.empty:
        return default
    val = 0.0
    for _, r in df.iterrows():
        w = weights.get(r['Giocatore'], 0.0)
        raw_val = r.get(col, default)
        try:
            num = float(raw_val) if pd.notna(raw_val) else default
        except (ValueError, TypeError):
            num = default
        val += w * num
    return val


def _build_player_card(p_row, meta):
    """Constructs a clean, human-readable card dictionary for a player."""
    g_name = p_row['Giocatore']
    sq = p_row.get('Squadra', '-')
    ruolo_m = p_row.get('RuoloMantra', p_row.get('RuoloClassic', '-'))
    ruolo_c = p_row.get('RuoloClassic', '-')

    st_val = meta['st_val']
    motivo_inj = meta['motivo_inj']
    badge_rientro = meta['badge_rientro']

    if st_val == 'Infortunato':
        status_badge = f"🚑 {motivo_inj} ({badge_rientro})"
        status_color = "#ef4444"
    elif st_val == 'Squalificato':
        status_badge = "🟥 Squalificato (1 turno)"
        status_color = "#f97316"
    elif st_val == 'In dubbio':
        status_badge = f"⚠️ {motivo_inj or 'In dubbio'}"
        status_color = "#eab308"
    else:
        status_badge = "✅ Disponibile"
        status_color = "#10b981"

    st_starter = meta['starter']
    tit_label = st_starter.get('Label', 'Titolare')
    tit_status = st_starter.get('Status', 'TITOLARE')
    min_per_pres = st_starter.get('Min_Per_Pres', 0)

    fm_stag = float(p_row.get('FM_Stagione', 6.0))
    mv_stag = float(p_row.get('MV_Stagione', 6.0))
    fm_last3 = float(p_row.get('FM_Ultime3', fm_stag))
    gf = int(p_row.get('GF', 0))
    ass = int(p_row.get('ASS', 0))
    pct_suff = float(p_row.get('Pct_Sufficienza', 60.0))
    xg_90 = float(p_row.get('xG_90', 0.0))
    xa_90 = float(p_row.get('xA_90', 0.0))
    delta_xg = float(p_row.get('Delta_xG', 0.0))
    fvm = float(p_row.get('FVM', p_row.get('Costo', 10.0)))

    return {
        'Giocatore': g_name,
        'Squadra': sq,
        'RuoloMantra': ruolo_m,
        'RuoloClassic': ruolo_c,
        'Stato': st_val,
        'Status_Badge': status_badge,
        'Status_Color': status_color,
        'Titolarita_Label': tit_label,
        'Titolarita_Status': tit_status,
        'Min_Per_Pres': min_per_pres,
        'FM_Stagione': round(fm_stag, 2),
        'MV_Stagione': round(mv_stag, 2),
        'FM_Ultime3': round(fm_last3, 2),
        'GF': gf,
        'ASS': ass,
        'Pct_Sufficienza': round(pct_suff, 1),
        'xG_90': round(xg_90, 2),
        'xA_90': round(xa_90, 2),
        'Delta_xG': round(delta_xg, 2),
        'FVM': round(fvm, 1),
        'Signal': p_row.get('Signal', 'NEUTRO')
    }


def evaluate_trade(
    give_names, 
    receive_names, 
    df_master, 
    start_matchday=10, 
    horizon=None, 
    calendar=None, 
    weight_mode='rank_decay'
):
    """
    Evaluates an exchange between two packages of players using the 4-Pillar Hybrid Model
    across the remainder of the season through matchday 38.
    """
    if calendar is None:
        calendar = get_or_create_calendar()

    give_df = df_master[df_master['Giocatore'].isin(give_names)].copy()
    receive_df = df_master[df_master['Giocatore'].isin(receive_names)].copy()

    if give_df.empty or receive_df.empty:
        return {'error': 'Giocatori non trovati nel database.'}

    n_give = len(give_df)
    n_rec = len(receive_df)
    is_multi = (n_give > 1 or n_rec > 1)

    give_weights = compute_package_weights(give_df, weight_mode=weight_mode)
    receive_weights = compute_package_weights(receive_df, weight_mode=weight_mode)

    if horizon is None:
        horizon = max(1, 38 - start_matchday + 1)
    matchdays = list(range(start_matchday, min(39, start_matchday + horizon)))
    num_g = max(1, len(matchdays))

    # Caches for injuries & lineups
    inj_cache = load_injuries_data()
    prob_cache = load_probable_lineups(force_refresh=False)

    def extract_player_metadata(df):
        meta_dict = {}
        for _, r in df.iterrows():
            p = r['Giocatore']
            inj_st = get_player_status(p, inj_cache)
            st_val = inj_st.get('Stato', 'Disponibile')
            det_val = inj_st.get('Dettaglio', '')
            parsed_inj = parse_injury_details(det_val, st_val, current_giornata=start_matchday)

            pres = float(r.get('Presenze', 0) or 0)
            mins = float(r.get('Minuti_Reali', 0) or 0)
            p_healthy = min(0.98, max(0.40, (mins / max(1.0, pres)) / 90.0)) if pres >= 3 else 0.70

            st_starter = compute_real_starter_status(r.to_dict() if hasattr(r, 'to_dict') else r)

            meta_dict[p] = {
                'st_val': st_val,
                'det_val': det_val,
                'target_g': parsed_inj.get('Giornata_Target'),
                'motivo_inj': parsed_inj.get('Motivo', ''),
                'rientro_previsto': parsed_inj.get('Rientro_Previsto', ''),
                'badge_rientro': parsed_inj.get('Badge_Rientro', ''),
                'p_healthy': p_healthy,
                'starter': st_starter
            }
        return meta_dict

    give_meta = extract_player_metadata(give_df)
    rec_meta = extract_player_metadata(receive_df)

    # -------------------------------------------------------------
    # PILASTRO 1: VALORE NETTO EFFETTIVO (Infermeria & Calendario Reale)
    # -------------------------------------------------------------
    give_timeline = []
    receive_timeline = []
    give_total_weighted_xfv = 0.0
    receive_total_weighted_xfv = 0.0
    give_total_raw_xfv = 0.0
    receive_total_raw_xfv = 0.0
    give_fdr_sum = 0.0
    receive_fdr_sum = 0.0
    give_missed_games = 0
    rec_missed_games = 0

    for g in matchdays:
        g_give_weighted_xfv = 0.0
        g_receive_weighted_xfv = 0.0
        g_give_raw_sum = 0.0
        g_receive_raw_sum = 0.0
        g_give_weighted_fdr = 0.0
        g_receive_weighted_fdr = 0.0

        give_matches = []
        for _, p_row in give_df.iterrows():
            pname = p_row['Giocatore']
            w = give_weights.get(pname, 1.0)
            meta = give_meta[pname]

            is_out = False
            out_reason = ""
            if meta['st_val'] == 'Infortunato':
                if meta['target_g'] is not None and g < meta['target_g']:
                    is_out = True
                    out_reason = f"🚑 Out ({meta['motivo_inj']})"
                    give_missed_games += 1
                elif meta['target_g'] is None and g <= start_matchday + 2:
                    is_out = True
                    out_reason = f"🚑 Out ({meta['motivo_inj']})"
                    give_missed_games += 1
            elif meta['st_val'] == 'Squalificato':
                if g == start_matchday:
                    is_out = True
                    out_reason = "🟥 Squalificato"
                    give_missed_games += 1

            if is_out:
                pxfv = 0.0
                pfdr = 3.0
                give_matches.append(f"{pname}: {out_reason} -> 0.0 xFV")
            else:
                proj = predict_player_xfv(p_row, matchday=g, calendar=calendar)
                base_xfv = float(proj.get('xFV', 0.0))
                pfdr = float(proj.get('FDR', 3.0))
                p_voto = meta['p_healthy']
                if meta['st_val'] == 'In dubbio' and g == start_matchday:
                    p_voto *= 0.50
                pxfv = round(base_xfv * p_voto, 2)
                w_lbl = f" ({int(round(w*100))}%)" if is_multi else ""
                give_matches.append(f"{pname}{w_lbl}: {proj['Match']} [FDR {int(pfdr)}] -> {pxfv}")

            g_give_weighted_xfv += w * pxfv
            g_give_raw_sum += pxfv
            g_give_weighted_fdr += w * pfdr

        receive_matches = []
        for _, p_row in receive_df.iterrows():
            pname = p_row['Giocatore']
            w = receive_weights.get(pname, 1.0)
            meta = rec_meta[pname]

            is_out = False
            out_reason = ""
            if meta['st_val'] == 'Infortunato':
                if meta['target_g'] is not None and g < meta['target_g']:
                    is_out = True
                    out_reason = f"🚑 Out ({meta['motivo_inj']})"
                    rec_missed_games += 1
                elif meta['target_g'] is None and g <= start_matchday + 2:
                    is_out = True
                    out_reason = f"🚑 Out ({meta['motivo_inj']})"
                    rec_missed_games += 1
            elif meta['st_val'] == 'Squalificato':
                if g == start_matchday:
                    is_out = True
                    out_reason = "🟥 Squalificato"
                    rec_missed_games += 1

            if is_out:
                pxfv = 0.0
                pfdr = 3.0
                receive_matches.append(f"{pname}: {out_reason} -> 0.0 xFV")
            else:
                proj = predict_player_xfv(p_row, matchday=g, calendar=calendar)
                base_xfv = float(proj.get('xFV', 0.0))
                pfdr = float(proj.get('FDR', 3.0))
                p_voto = meta['p_healthy']
                if meta['st_val'] == 'In dubbio' and g == start_matchday:
                    p_voto *= 0.50
                pxfv = round(base_xfv * p_voto, 2)
                w_lbl = f" ({int(round(w*100))}%)" if is_multi else ""
                receive_matches.append(f"{pname}{w_lbl}: {proj['Match']} [FDR {int(pfdr)}] -> {pxfv}")

            g_receive_weighted_xfv += w * pxfv
            g_receive_raw_sum += pxfv
            g_receive_weighted_fdr += w * pfdr

        give_total_weighted_xfv += g_give_weighted_xfv
        receive_total_weighted_xfv += g_receive_weighted_xfv
        give_total_raw_xfv += g_give_raw_sum
        receive_total_raw_xfv += g_receive_raw_sum

        give_fdr_sum += g_give_weighted_fdr
        receive_fdr_sum += g_receive_weighted_fdr

        give_timeline.append({
            'Giornata': f"G{g}",
            'xFV_Ceduti': round(g_give_weighted_xfv, 2),
            'xFV_Ceduti_Somma': round(g_give_raw_sum, 2),
            'Dettagli_Ceduti': "; ".join(give_matches)
        })

        receive_timeline.append({
            'Giornata': f"G{g}",
            'xFV_Ricevuti': round(g_receive_weighted_xfv, 2),
            'xFV_Ricevuti_Somma': round(g_receive_raw_sum, 2),
            'Dettagli_Ricevuti': "; ".join(receive_matches)
        })

    df_timeline = pd.DataFrame({
        'Giornata': [t['Giornata'] for t in give_timeline],
        'xFV_Ceduti': [t['xFV_Ceduti'] for t in give_timeline],
        'xFV_Ricevuti': [t['xFV_Ricevuti'] for t in receive_timeline],
        'Delta_Giornata': [round(r['xFV_Ricevuti'] - g['xFV_Ceduti'], 2) for g, r in zip(give_timeline, receive_timeline)],
        'xFV_Ceduti_Somma': [t['xFV_Ceduti_Somma'] for t in give_timeline],
        'xFV_Ricevuti_Somma': [t['xFV_Ricevuti_Somma'] for t in receive_timeline],
        'Delta_Somma': [round(r['xFV_Ricevuti_Somma'] - g['xFV_Ceduti_Somma'], 2) for g, r in zip(give_timeline, receive_timeline)],
        'Match_Ceduti': [t['Dettagli_Ceduti'] for t in give_timeline],
        'Match_Ricevuti': [t['Dettagli_Ricevuti'] for t in receive_timeline]
    })

    p1_delta_tot = round(receive_total_weighted_xfv - give_total_weighted_xfv, 2)
    p1_delta_per_game = round(p1_delta_tot / num_g, 2)
    avg_fdr_give = round(give_fdr_sum / num_g, 2)
    avg_fdr_receive = round(receive_fdr_sum / num_g, 2)

    if p1_delta_per_game >= 0.20:
        p1_winner = 'RICEVI'
        p1_desc = f"Ricevi porta {p1_delta_tot:+.1f} xFV totali ({p1_delta_per_game:+.2f}/gara al netto di infortuni)"
    elif p1_delta_per_game <= -0.20:
        p1_winner = 'CEDI'
        p1_desc = f"Cedi porta {abs(p1_delta_tot):.1f} xFV in più ({abs(p1_delta_per_game):.2f}/gara)"
    else:
        p1_winner = 'PARI'
        p1_desc = f"Equilibrio sui punti attesi ({p1_delta_per_game:+.2f} xFV/gara di differenza)"

    # -------------------------------------------------------------
    # PILASTRO 2: MOMENTUM & TREND RECENTE (Understat Buy-Low / Sell-High)
    # -------------------------------------------------------------
    def compute_momentum_score(df, weights):
        m_score = 0.0
        for _, r in df.iterrows():
            w = weights.get(r['Giocatore'], 0.0)
            fm_s = float(r.get('FM_Stagione', 6.0))
            fm_u3 = float(r.get('FM_Ultime3', fm_s))
            delta_form = fm_u3 - fm_s
            delta_xg = float(r.get('Delta_xG', 0.0))
            xg90 = float(r.get('xG_90', 0.0))
            xa90 = float(r.get('xA_90', 0.0))
            # Base 50 + form delta + Buy-Low reward + underlying volume
            p_score = 50.0 + (delta_form * 12.0) - (delta_xg * 6.0) + ((xg90 + xa90) * 16.0)
            m_score += w * max(10.0, min(95.0, p_score))
        return round(m_score, 1)

    p2_score_give = compute_momentum_score(give_df, give_weights)
    p2_score_rec = compute_momentum_score(receive_df, receive_weights)
    p2_delta = round(p2_score_rec - p2_score_give, 1)

    if p2_delta >= 6.0:
        p2_winner = 'RICEVI'
        p2_desc = f"Ricevi ha trend in crescita e maggior potenziale bonus (+{p2_delta} pt)"
    elif p2_delta <= -6.0:
        p2_winner = 'CEDI'
        p2_desc = f"Cedi è in forma migliore / trend recente superiore (+{abs(p2_delta)} pt)"
    else:
        p2_winner = 'PARI'
        p2_desc = "Forma recente e volume offensivo sostanzialmente bilanciati"

    # -------------------------------------------------------------
    # PILASTRO 3: SOLIDITÀ DI ROSA & GARANZIA VOTO (Minuti & D-Factor)
    # -------------------------------------------------------------
    def compute_safety_score(df, weights, meta_dict):
        s_score = 0.0
        for _, r in df.iterrows():
            w = weights.get(r['Giocatore'], 0.0)
            m = meta_dict[r['Giocatore']]
            pct_suff = float(r.get('Pct_Sufficienza', 60.0))
            st_starter = m['starter']
            min_per_pres = float(st_starter.get('Min_Per_Pres', 60.0))
            pct_min = float(st_starter.get('Pct_Minuti', 60.0))

            amm = float(r.get('AMM', 0))
            esp = float(r.get('ESP', 0))
            cards_pen = min(15.0, amm * 1.2 + esp * 4.0)

            # D-Factor bonus for Por, Dc, Dd, Ds, E, M with high sufficiency
            ruolo_m = str(r.get('RuoloMantra', ''))
            is_dfactor = any(x in ruolo_m for x in ['Por', 'Dc', 'Dd', 'Ds', 'E', 'M']) or (r.get('RuoloClassic') == 'P')
            dfactor_bonus = 6.0 if is_dfactor and pct_suff >= 70.0 else 0.0

            p_safety = (0.42 * pct_suff) + (0.35 * (min_per_pres / 90.0 * 100.0)) + (0.15 * pct_min) - cards_pen + dfactor_bonus
            s_score += w * max(10.0, min(98.0, p_safety))
        return round(s_score, 1)

    p3_score_give = compute_safety_score(give_df, give_weights, give_meta)
    p3_score_rec = compute_safety_score(receive_df, receive_weights, rec_meta)
    p3_delta = round(p3_score_rec - p3_score_give, 1)

    if p3_delta >= 6.0:
        p3_winner = 'RICEVI'
        p3_desc = f"Ricevi garantisce più minuti e presenze sicure a voto (+{p3_delta} pt)"
    elif p3_delta <= -6.0:
        p3_winner = 'CEDI'
        p3_desc = f"Cedi offre maggiore affidabilità di titolarità e sufficienze (+{abs(p3_delta)} pt)"
    else:
        p3_winner = 'PARI'
        p3_desc = "Continuità di impiego e affidabilità difensiva equivalenti"

    # -------------------------------------------------------------
    # PILASTRO 4: FANTA-PLUSVALENZA & GERARCHIA STAR (Quality over Quantity)
    # -------------------------------------------------------------
    def compute_star_score(df, weights):
        st_score = 0.0
        max_fvm = 0.0
        for _, r in df.iterrows():
            w = weights.get(r['Giocatore'], 0.0)
            fvm = float(r.get('FVM', r.get('Costo', 10.0)))
            max_fvm = max(max_fvm, fvm)
            p_val = min(100.0, fvm * 1.5)
            st_score += w * p_val
        # Star concentration bonus if package has a clear top player (FVM > 35)
        if max_fvm >= 35.0:
            st_score = min(100.0, st_score + 10.0)
        return round(st_score, 1)

    p4_score_give = compute_star_score(give_df, give_weights)
    p4_score_rec = compute_star_score(receive_df, receive_weights)
    p4_delta = round(p4_score_rec - p4_score_give, 1)

    if p4_delta >= 7.0:
        p4_winner = 'RICEVI'
        p4_desc = f"Ricevi guadagna il calciatore di vertice di maggior valore (+{p4_delta} pt)"
    elif p4_delta <= -7.0:
        p4_winner = 'CEDI'
        p4_desc = f"Cedi il giocatore di punta più pregiato dello scambio (+{abs(p4_delta)} pt)"
    else:
        p4_winner = 'PARI'
        p4_desc = "Fanta-valore di mercato e appeal complessivo speculari"

    # -------------------------------------------------------------
    # SINTESI IBRIDA & VERDETTO GLOBALE
    # -------------------------------------------------------------
    # Normalized composite delta:
    # 35% P1 (Punti effettivi/gara), 25% P2 (Momentum), 20% P3 (Solidità), 20% P4 (Qualità Star)
    p1_contrib = float(np.clip((p1_delta_per_game / 0.50) * 35.0, -45.0, 45.0))
    p2_contrib = float(np.clip((p2_delta / 20.0) * 25.0, -30.0, 30.0))
    p3_contrib = float(np.clip((p3_delta / 20.0) * 20.0, -25.0, 25.0))
    p4_contrib = float(np.clip((p4_delta / 20.0) * 20.0, -25.0, 25.0))

    composite_score = round(p1_contrib + p2_contrib + p3_contrib + p4_contrib, 1)

    if composite_score >= 22.0:
        verdict = "SCAMBIO CONSIGLIATISSIMO"
        status_color = "green"
    elif composite_score >= 7.0:
        verdict = "SCAMBIO FAVOREVOLE"
        status_color = "lightgreen"
    elif composite_score >= -7.0:
        verdict = "SCAMBIO EQUILIBRATO"
        status_color = "gray"
    elif composite_score >= -22.0:
        verdict = "SCAMBIO SFAVOREVOLE"
        status_color = "orange"
    else:
        verdict = "SCAMBIO DA EVITARE"
        status_color = "red"

    # High-level human synthesis
    winners_count = [p1_winner, p2_winner, p3_winner, p4_winner].count('RICEVI')
    losers_count = [p1_winner, p2_winner, p3_winner, p4_winner].count('CEDI')

    if composite_score >= 12.0:
        sintesi_umana = f"Scambio chiaramente vantaggioso: guadagni circa {p1_delta_tot:+.1f} xFV netti nel resto della stagione, migliorando la qualità del reparto."
    elif composite_score >= 4.0:
        sintesi_umana = f"Operazione favorevole: leggero incremento di rendimento atteso ({p1_delta_per_game:+.2f} xFV/gara) con profilo statistico superiore."
    elif composite_score >= -4.0:
        sintesi_umana = "Scambio sostanzialmente alla pari: le due contropartite offrono rendimenti equivalenti, la scelta dipende dalle preferenze tattiche."
    elif composite_score >= -12.0:
        sintesi_umana = f"Operazione a rischio: cedi calciatori con continuità o punteggio potenziale superiore ({abs(p1_delta_per_game):.2f} xFV/gara persi)."
    else:
        sintesi_umana = f"Scambio fortemente sconsigliato: perdi circa {abs(p1_delta_tot):.1f} xFV complessivi o stai cedendo un top per giocatori non all'altezza."

    # Rationales, Advantages, and Risks
    vantaggi = []
    rischi = []
    note_cliniche = []

    # Injury notes
    if rec_missed_games > 0:
        note_cliniche.append(f"⚠️ Attenzione infermeria: i calciatori ricevuti salteranno circa **{rec_missed_games} presenze totali** per infortunio/squalifica prima del rientro.")
    if give_missed_games > 0:
        note_cliniche.append(f"💡 Cedi giocatori attualmente indisponibili (**{give_missed_games} partite saltate**): ti liberi di tempi di recupero pendenti.")
    if rec_missed_games == 0 and give_missed_games == 0:
        note_cliniche.append("✅ Situazione medica ottimale: tutti i calciatori coinvolti sono sani e arruolabili subito.")

    # Pillar-based reasons
    if p1_winner == 'RICEVI':
        vantaggi.append(f"**Punti Fanta Netto**: Guadagno atteso di **{p1_delta_tot:+.1f} xFV totali** ({p1_delta_per_game:+.2f} a partita) da qui alla 38ª giornata.")
    elif p1_winner == 'CEDI':
        rischi.append(f"**Punti Fanta Persi**: Stai rinunciando a **{abs(p1_delta_tot):.1f} xFV complessivi** nel corso del campionato.")

    if p2_winner == 'RICEVI':
        vantaggi.append(f"**Trend e Momentum**: Il pacchetto in entrata vanta un trend recente superiore e ottimi segnali Understat di pericolosità.")
    elif p2_winner == 'CEDI':
        rischi.append(f"**Flessione di Forma**: I calciatori ceduti sono attualmente più caldi e producono maggior volume al tiro.")

    if p3_winner == 'RICEVI':
        vantaggi.append(f"**Continuità e Titolarità**: Maggior garanzia del voto e minutaggio dal 1' minuto, riducendo il rischio di giocare in 10.")
    elif p3_winner == 'CEDI':
        rischi.append(f"**Rischio Ballottaggi**: Chi ricevi ha meno minuti garantiti a partita o espone a più turn-over.")

    if p4_winner == 'RICEVI':
        vantaggi.append(f"**Qualità Star**: Acquisisci il calciatore di vertice con il fanta-valore più alto, ottimizzando lo slot titolare.")
    elif p4_winner == 'CEDI':
        rischi.append(f"**Svalutazione del Top**: Cedi il calciatore più pregiato in cambio di comprimari che occupano slot aggiuntivi.")

    # Schedule comparison
    if avg_fdr_receive < avg_fdr_give - 0.2:
        vantaggi.append(f"**Calendario più agevole**: FDR medio di {avg_fdr_receive} vs {avg_fdr_give} dei ceduti da qui a fine campionato.")
    elif avg_fdr_receive > avg_fdr_give + 0.2:
        rischi.append(f"**Calendario più ostico**: FDR medio di {avg_fdr_receive} vs {avg_fdr_give} (più big match in trasferta).")

    # Build side-by-side player cards
    cards_give = [_build_player_card(r, give_meta[r['Giocatore']]) for _, r in give_df.iterrows()]
    cards_rec = [_build_player_card(r, rec_meta[r['Giocatore']]) for _, r in receive_df.iterrows()]

    # Advanced Understat & Goalkeeper metrics for optional deep-dive
    shots_give = round(_weighted_metric(give_df, give_weights, 'Tiri_90', 0.0), 1)
    shots_receive = round(_weighted_metric(receive_df, receive_weights, 'Tiri_90', 0.0), 1)
    xg_give = round(_weighted_metric(give_df, give_weights, 'xG_90', 0.0), 2)
    xg_receive = round(_weighted_metric(receive_df, receive_weights, 'xG_90', 0.0), 2)
    xgtot_give = round(_weighted_metric(give_df, give_weights, 'xG_Tot', 0.0), 2)
    xgtot_receive = round(_weighted_metric(receive_df, receive_weights, 'xG_Tot', 0.0), 2)
    deltaxg_give = round(_weighted_metric(give_df, give_weights, 'Delta_xG', 0.0), 2)
    deltaxg_receive = round(_weighted_metric(receive_df, receive_weights, 'Delta_xG', 0.0), 2)
    kp_give = round(_weighted_metric(give_df, give_weights, 'Key_Passes_90', 0.0), 1)
    kp_receive = round(_weighted_metric(receive_df, receive_weights, 'Key_Passes_90', 0.0), 1)
    xa_give = round(_weighted_metric(give_df, give_weights, 'xA_90', 0.0), 2)
    xa_receive = round(_weighted_metric(receive_df, receive_weights, 'xA_90', 0.0), 2)

    gk_give = give_df[(give_df['RuoloClassic'] == 'P') | (give_df['RuoloMantra'].str.contains('Por', na=False))]
    gk_receive = receive_df[(receive_df['RuoloClassic'] == 'P') | (receive_df['RuoloMantra'].str.contains('Por', na=False))]
    has_gk = (not gk_give.empty) or (not gk_receive.empty)
    gk_give_weights = compute_package_weights(gk_give, weight_mode=weight_mode) if not gk_give.empty else {}
    gk_recv_weights = compute_package_weights(gk_receive, weight_mode=weight_mode) if not gk_receive.empty else {}

    gp_give = round(_weighted_metric(gk_give, gk_give_weights, 'Goals_Prevented', 0.0), 2)
    gp_receive = round(_weighted_metric(gk_receive, gk_recv_weights, 'Goals_Prevented', 0.0), 2)
    gp90_give = round(_weighted_metric(gk_give, gk_give_weights, 'Goals_Prevented_90', 0.0), 2)
    gp90_receive = round(_weighted_metric(gk_receive, gk_recv_weights, 'Goals_Prevented_90', 0.0), 2)
    blunders_give = int(round(_weighted_metric(gk_give, gk_give_weights, 'Errors_Leading_To_Goal', 0.0)))
    blunders_receive = int(round(_weighted_metric(gk_receive, gk_recv_weights, 'Errors_Leading_To_Goal', 0.0)))
    save_pct_give = round(_weighted_metric(gk_give, gk_give_weights, 'Pct_Parate', 70.0), 1)
    save_pct_receive = round(_weighted_metric(gk_receive, gk_recv_weights, 'Pct_Parate', 70.0), 1)

    df_give_dfactor = give_df[give_df['RuoloMantra'].str.contains('Por|Dd|Ds|Dc|B|E|M', na=False) | (give_df['RuoloClassic'] == 'P')]
    df_recv_dfactor = receive_df[receive_df['RuoloMantra'].str.contains('Por|Dd|Ds|Dc|B|E|M', na=False) | (receive_df['RuoloClassic'] == 'P')]
    df_give_w = compute_package_weights(df_give_dfactor, weight_mode=weight_mode) if not df_give_dfactor.empty else {}
    df_recv_w = compute_package_weights(df_recv_dfactor, weight_mode=weight_mode) if not df_recv_dfactor.empty else {}
    mv_give = round(_weighted_metric(df_give_dfactor, df_give_w, 'MV_Stagione', 6.0), 2)
    mv_receive = round(_weighted_metric(df_recv_dfactor, df_recv_w, 'MV_Stagione', 6.0), 2)
    suff_give = round(_weighted_metric(df_give_dfactor, df_give_w, 'Pct_Sufficienza', 60.0), 1)
    suff_receive = round(_weighted_metric(df_recv_dfactor, df_recv_w, 'Pct_Sufficienza', 60.0), 1)

    reasons = vantaggi + [f"⚠️ {r}" for r in rischi] + note_cliniche

    return {
        'Verdetto': verdict,
        'StatusColor': status_color,
        'Sintesi_Umana': sintesi_umana,
        'Vantaggi': vantaggi,
        'Rischi': rischi,
        'Note_Cliniche': note_cliniche,
        'Composite_Score': composite_score,

        # 4 Pillars
        'Pilastro1': {
            'Nome': 'Valore Netto Effettivo (Infermeria & Calendario)',
            'Score_Give': round(give_total_weighted_xfv, 1),
            'Score_Rec': round(receive_total_weighted_xfv, 1),
            'Delta_Tot': p1_delta_tot,
            'Delta_Partita': p1_delta_per_game,
            'Missed_Games_Give': give_missed_games,
            'Missed_Games_Rec': rec_missed_games,
            'Winner': p1_winner,
            'Descrizione': p1_desc
        },
        'Pilastro2': {
            'Nome': 'Momentum & Trend Recente (Understat)',
            'Score_Give': p2_score_give,
            'Score_Rec': p2_score_rec,
            'Delta': p2_delta,
            'Winner': p2_winner,
            'Descrizione': p2_desc
        },
        'Pilastro3': {
            'Nome': 'Solidità di Rosa & Garanzia Voto',
            'Score_Give': p3_score_give,
            'Score_Rec': p3_score_rec,
            'Delta': p3_delta,
            'Winner': p3_winner,
            'Descrizione': p3_desc
        },
        'Pilastro4': {
            'Nome': 'Fanta-Plusvalenza & Gerarchia Star',
            'Score_Give': p4_score_give,
            'Score_Rec': p4_score_rec,
            'Delta': p4_delta,
            'Winner': p4_winner,
            'Descrizione': p4_desc
        },

        # Side-by-side cards data
        'Cards_Give': cards_give,
        'Cards_Rec': cards_rec,

        # Backward compatibility
        'Delta_Totale_xFV': p1_delta_tot,
        'Delta_Medio_Partita': p1_delta_per_game,
        'Delta_Totale_Raw': round(receive_total_raw_xfv - give_total_raw_xfv, 2),
        'xFV_Ceduti_Tot': round(give_total_weighted_xfv, 2),
        'xFV_Ricevuti_Tot': round(receive_total_weighted_xfv, 2),
        'xFV_Ceduti_Raw_Tot': round(give_total_raw_xfv, 2),
        'xFV_Ricevuti_Raw_Tot': round(receive_total_raw_xfv, 2),
        'xFV_Ceduti_Medio_Partita': round(give_total_weighted_xfv / num_g, 2),
        'xFV_Ricevuti_Medio_Partita': round(receive_total_weighted_xfv / num_g, 2),
        'FDR_Medio_Ceduti': avg_fdr_give,
        'FDR_Medio_Ricevuti': avg_fdr_receive,
        'Tiri_Ceduti_90': shots_give,
        'Tiri_Ricevuti_90': shots_receive,
        'xG_Ceduti_90': xg_give,
        'xG_Ricevuti_90': xg_receive,
        'xGTot_Ceduti': xgtot_give,
        'xGTot_Ricevuti': xgtot_receive,
        'Delta_xG_Ceduti': deltaxg_give,
        'Delta_xG_Ricevuti': deltaxg_receive,
        'KP_Ceduti_90': kp_give,
        'KP_Ricevuti_90': kp_receive,
        'xA_Ceduti_90': xa_give,
        'xA_Ricevuti_90': xa_receive,
        'MV_Ceduti_DFactor': mv_give,
        'MV_Ricevuti_DFactor': mv_receive,
        'Suff_Ceduti_DFactor': suff_give,
        'Suff_Ricevuti_DFactor': suff_receive,
        'Has_GK': has_gk,
        'GP_Ceduti': gp_give,
        'GP_Ricevuti': gp_receive,
        'GP90_Ceduti': gp90_give,
        'GP90_Ricevuti': gp90_receive,
        'Blunders_Ceduti': blunders_give,
        'Blunders_Ricevuti': blunders_receive,
        'SavePct_Ceduti': save_pct_give,
        'SavePct_Ricevuti': save_pct_receive,
        'Giornate_Valutate': num_g,
        'Motivazioni': reasons,
        'Timeline': df_timeline,
        'Pesi_Ceduti': give_weights,
        'Pesi_Ricevuti': receive_weights,
        'Num_Ceduti': n_give,
        'Num_Ricevuti': n_rec,
        'Is_Multi': is_multi,
        'Weight_Mode': weight_mode
    }


if __name__ == '__main__':
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    master_path = os.path.join(data_dir, "players_master.csv")
    df_m = pd.read_csv(master_path)

    print("\n--- TEST VALUTATORE IBRIDO 4 PILASTRI ---")
    res = evaluate_trade(['Bonny'], ['Malen'], df_m, start_matchday=10)
    print(f"VERDETTO: {res['Verdetto']}")
    print(f"Sintesi: {res['Sintesi_Umana']}")
    print(f"Pilastro 1: {res['Pilastro1']['Descrizione']}")
    print(f"Pilastro 2: {res['Pilastro2']['Descrizione']}")
    print(f"Pilastro 3: {res['Pilastro3']['Descrizione']}")
    print(f"Pilastro 4: {res['Pilastro4']['Descrizione']}")
