"""
Mantra Trade Evaluator (Valutatore di Scambi).
Projects performance of traded players over a custom horizon (e.g. 3 to 15 matchdays),
factoring in FDR opponent schedules, home/away splits, xFV projections,
and statistical Buy-Low / Sell-High signals.

Multi-player packages (e.g. 2v1, 4v4, 2v2) are evaluated via a balanced weighted average
(media ponderata con priorità decrescente al top player del pacchetto) to prevent
unrealistic additive inflation and ensure asymmetric trades are fairly evaluated.
"""

import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.fanta_calendar import get_or_create_calendar, get_fixture_info
from engine.models import predict_player_xfv


def compute_package_weights(df_package, weight_mode='rank_decay'):
    """
    Computes normalized weights (summing to 1.0) for players in a multi-player package.
    Modes:
    - 'rank_decay' (default / recommended): Decaying rank weights prioritizing the centerpiece / star.
      Formula: alpha_i = (K - i)^0.6 where players are ordered descending by FM_Stagione / Costo.
      For K=1: [1.0] (100%)
      For K=2: [0.6025, 0.3975] (for 100 and 80 -> ~92.05, close to 90 as per user specification).
      For K=3: [0.435, 0.341, 0.224]
      For K=4: [0.341, 0.287, 0.225, 0.148]
    - 'simple_mean': Equal weights (1/K) -> simple arithmetic mean (for 100 and 80 -> 90.0).
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

    # Sort descending by quality (FM_Stagione or Costo or MV_Stagione)
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
    else:  # 'rank_decay' (default)
        raw_alphas = [(k - i) ** 0.6 for i in range(k)]
        s_alpha = sum(raw_alphas)
        for i, row in df_sorted.iterrows():
            weights[row['Giocatore']] = raw_alphas[i] / s_alpha

    # Ensure exact normalization to 1.0
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


def evaluate_trade(
    give_names, 
    receive_names, 
    df_master, 
    start_matchday=6, 
    horizon=5, 
    calendar=None, 
    weight_mode='rank_decay'
):
    """
    Evaluates an exchange between two packages of players over N matchdays.
    Multi-player packages are balanced via weighted average (media ponderata)
    to normalize the evaluation scale to single-slot quality, eliminating
    the distortion of raw additive sums.

    Returns:
      Comprehensive comparison report including delta xFV, match-by-match projections,
      schedule difficulty comparison, regression signals, and tactical verdict.
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

    # Compute normalized package weights
    give_weights = compute_package_weights(give_df, weight_mode=weight_mode)
    receive_weights = compute_package_weights(receive_df, weight_mode=weight_mode)

    matchdays = list(range(start_matchday, min(39, start_matchday + horizon)))

    give_timeline = []
    receive_timeline = []

    give_total_weighted_xfv = 0.0
    receive_total_weighted_xfv = 0.0
    give_total_raw_xfv = 0.0
    receive_total_raw_xfv = 0.0

    give_fdr_sum = 0.0
    receive_fdr_sum = 0.0

    # Matchday breakdown
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
            proj = predict_player_xfv(p_row, matchday=g, calendar=calendar)
            pxfv = float(proj.get('xFV', 0.0))
            pfdr = float(proj.get('FDR', 3))
            g_give_weighted_xfv += w * pxfv
            g_give_raw_sum += pxfv
            g_give_weighted_fdr += w * pfdr
            w_label = f" (peso {int(round(w*100))}%)" if is_multi else ""
            give_matches.append(f"{pname}{w_label}: {proj['Match']} [FDR {int(pfdr)}] -> {pxfv}")

        receive_matches = []
        for _, p_row in receive_df.iterrows():
            pname = p_row['Giocatore']
            w = receive_weights.get(pname, 1.0)
            proj = predict_player_xfv(p_row, matchday=g, calendar=calendar)
            pxfv = float(proj.get('xFV', 0.0))
            pfdr = float(proj.get('FDR', 3))
            g_receive_weighted_xfv += w * pxfv
            g_receive_raw_sum += pxfv
            g_receive_weighted_fdr += w * pfdr
            w_label = f" (peso {int(round(w*100))}%)" if is_multi else ""
            receive_matches.append(f"{pname}{w_label}: {proj['Match']} [FDR {int(pfdr)}] -> {pxfv}")

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

    num_g = max(1, len(matchdays))
    avg_fdr_give = round(give_fdr_sum / num_g, 2)
    avg_fdr_receive = round(receive_fdr_sum / num_g, 2)

    delta_totale_ponderato = round(receive_total_weighted_xfv - give_total_weighted_xfv, 2)
    delta_medio_partita = round(delta_totale_ponderato / num_g, 2)
    delta_raw_totale = round(receive_total_raw_xfv - give_total_raw_xfv, 2)

    # Volume and attacking metrics: Weighted averages across the package
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

    # Goalkeeper advanced metrics comparison
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

    # Real starter status verification (e.g. Lucca, Nzola, Kevin Carlos subentranti)
    starter_warnings = []
    starter_bonuses = []
    from engine.trade_finder import compute_real_starter_status
    for _, r_p in receive_df.iterrows():
        st_rec = compute_real_starter_status(r_p)
        if st_rec['Status'] == 'SUBENTRANTE':
            starter_warnings.append(f"⚠️ Rischio titolarità per {r_p['Giocatore']}: in Serie A è una riserva/subentrante (media ~{st_rec['Min_Per_Pres']} min a partita, {st_rec['Pct_Minuti']}% minuti giocati).")
        elif st_rec['Status'] == 'MARGINALE':
            starter_warnings.append(f"🚨 Calciatore marginale {r_p['Giocatore']}: minutaggio quasi nullo (< 2 presenze o spezzoni rari).")
        elif st_rec['Status'] == 'TITOLARE':
            starter_bonuses.append(f"🟢 {r_p['Giocatore']} è un titolare inamovibile in Serie A (media {st_rec['Min_Per_Pres']} min a partita).")

    # D-Factor and sufficiency comparison (for Por, Dd, Ds, Dc, B, E, M)
    df_give_dfactor = give_df[give_df['RuoloMantra'].str.contains('Por|Dd|Ds|Dc|B|E|M', na=False) | (give_df['RuoloClassic'] == 'P')]
    df_recv_dfactor = receive_df[receive_df['RuoloMantra'].str.contains('Por|Dd|Ds|Dc|B|E|M', na=False) | (receive_df['RuoloClassic'] == 'P')]

    df_give_w = compute_package_weights(df_give_dfactor, weight_mode=weight_mode) if not df_give_dfactor.empty else {}
    df_recv_w = compute_package_weights(df_recv_dfactor, weight_mode=weight_mode) if not df_recv_dfactor.empty else {}

    mv_give = round(_weighted_metric(df_give_dfactor, df_give_w, 'MV_Stagione', 6.0), 2)
    mv_receive = round(_weighted_metric(df_recv_dfactor, df_recv_w, 'MV_Stagione', 6.0), 2)
    suff_give = round(_weighted_metric(df_give_dfactor, df_give_w, 'Pct_Sufficienza', 60.0), 1)
    suff_receive = round(_weighted_metric(df_recv_dfactor, df_recv_w, 'Pct_Sufficienza', 60.0), 1)

    # Buy-low / sell-high inspection
    buy_low_incoming = receive_df[receive_df['Signal'].str.contains('BUY-LOW', na=False)]['Giocatore'].tolist()
    sell_high_outgoing = give_df[give_df['Signal'].str.contains('SELL-HIGH', na=False)]['Giocatore'].tolist()
    sell_high_incoming = receive_df[receive_df['Signal'].str.contains('SELL-HIGH', na=False)]['Giocatore'].tolist()

    # Verdict and rationale logic (driven by normalized weighted metrics)
    reasons = []

    if is_multi:
        if n_give != n_rec:
            reasons.append(
                f"⚖️ Scambio asimmetrico ({n_give} ceduti vs {n_rec} ricevuti): "
                f"I dati sono bilanciati tramite media ponderata (anziché semplice somma), "
                f"pesando prioritariamente i calciatori di vertice di ciascun pacchetto per un confronto equo a livello di singolo slot titolare."
            )
        else:
            reasons.append(
                f"⚖️ Scambio pacchetto multiplo ({n_give} vs {n_rec}): "
                f"Valutato tramite media ponderata per misurare la qualità media a slot ed evitare le distorsioni della somma cumulativa."
            )

    # Thresholds on delta_totale_ponderato (scale normalized to single-starter equivalent across horizon)
    if delta_totale_ponderato >= 3.5:
        verdict = "SCAMBIO CONSIGLIATISSIMO"
        status_color = "green"
        reasons.append(f"Guadagno atteso significativo: +{delta_totale_ponderato} xFV complessivi (+{delta_medio_partita:+.2f} xFV a giornata) sull'orizzonte di {num_g} turni.")
    elif delta_totale_ponderato >= 1.0:
        verdict = "SCAMBIO FAVOREVOLE"
        status_color = "lightgreen"
        reasons.append(f"Margine positivo favorevole (+{delta_totale_ponderato} xFV ponderati, +{delta_medio_partita:+.2f} xFV/partita).")
    elif delta_totale_ponderato >= -1.0:
        verdict = "SCAMBIO EQUILIBRATO"
        status_color = "gray"
        reasons.append(f"Proiezione sostanzialmente alla pari (differenziale bilanciato {delta_totale_ponderato:+.2f} xFV, {delta_medio_partita:+.2f} xFV/partita).")
    elif delta_totale_ponderato >= -3.5:
        verdict = "SCAMBIO SFAVOREVOLE"
        status_color = "orange"
        reasons.append(f"Perdita di punti attesi prevista ({delta_totale_ponderato:+.2f} xFV ponderati, {delta_medio_partita:+.2f} xFV/partita).")
    else:
        verdict = "SCAMBIO DA EVITARE"
        status_color = "red"
        reasons.append(f"Forte svantaggio statistico ({delta_totale_ponderato:+.2f} xFV ponderati, {delta_medio_partita:+.2f} xFV/partita).")

    # Schedule comparison
    if avg_fdr_receive < avg_fdr_give:
        reasons.append(f"Calendario più agevole per i ricevuti (FDR medio ponderato {avg_fdr_receive} vs {avg_fdr_give}).")
    elif avg_fdr_receive > avg_fdr_give:
        reasons.append(f"Attenzione al calendario più ostico per i ricevuti (FDR medio ponderato {avg_fdr_receive} vs {avg_fdr_give}).")

    # Objective real-world volume commentary (normalized per 90 min)
    if shots_receive > shots_give + 0.5:
        reasons.append(f"🔥 Incremento volume offensivo al tiro (media ponderata /90 min): il pacchetto che ricevi produce {shots_receive} tiri/90 vs {shots_give} di quello ceduto (+{round(shots_receive - shots_give, 1)} tiri/90 per slot).")
    elif shots_give > shots_receive + 0.5:
        reasons.append(f"⚠️ Calo di volume al tiro: stai cedendo calciatori con produzione al tiro superiore ({shots_give} vs {shots_receive} tiri/90 medi ponderati).")

    if xg_receive > xg_give + 0.10:
        reasons.append(f"⚽ Qualità delle occasioni (xG/90 medio ponderato): i calciatori ricevuti producono {xg_receive} xG/90 vs {xg_give} di quelli ceduti.")
    elif xg_give > xg_receive + 0.10:
        reasons.append(f"⚠️ Calo di pericolosità attesa: i calciatori ceduti generano più occasioni da gol ({xg_give} vs {xg_receive} xG/90 medi ponderati).")

    if kp_receive > kp_give + 0.5:
        reasons.append(f"🎯 Più rifinitura e assist: i ricevuti producono +{round(kp_receive - kp_give, 1)} passaggi chiave/90 ({kp_receive} vs {kp_give} medi ponderati).")

    if xa_receive > xa_give + 0.08:
        reasons.append(f"👟 Assist attesi (xA/90 medio ponderato): i ricevuti producono {xa_receive} xA/90 vs {xa_give} dei ceduti.")

    # Small Sample Size Warning (< 270 minutes)
    for _, p_r in receive_df.iterrows():
        mins_p = float(p_r.get('Minuti_Reali', 0))
        pres_p = float(p_r.get('Presenze', 0))
        if pres_p > 0 and mins_p < 270:
            avg_m = round(mins_p / pres_p, 1)
            reasons.append(
                f"⚠️ Attenzione al minutaggio ridotto per {p_r['Giocatore']}: i suoi dati ({p_r.get('Tiri_90', 0)} tiri/90 e {p_r.get('xG_90', 0)} xG/90) "
                f"sono estrapolati su soli {int(mins_p)} minuti totali (media ~{avg_m} min/presenza). "
                f"Su un campione così ristretto (< 3 partite piene), la proiezione su 90 minuti risulta statisticamente gonfiata rispetto alla produzione effettiva."
            )

    # Goalkeeper metrics commentary
    if has_gk:
        if gp_receive > gp_give + 0.8:
            reasons.append(f"🧤 Enorme upgrade tra i pali: ricevi un portiere con resa shot-stopping superiore ({gp_receive:+.2f} vs {gp_give:+.2f} Goals Prevented/PSxG-GA, {gp90_receive:+.2f}/90 vs {gp90_give:+.2f}/90).")
        elif gp_give > gp_receive + 0.8:
            reasons.append(f"⚠️ Peggioramento tra i pali: stai cedendo un portiere più decisivo sui tiri ({gp_give:+.2f} vs {gp_receive:+.2f} Goals Prevented).")

        if blunders_receive < blunders_give:
            reasons.append(f"🛡️ Blindatura della porta: azzeri o riduci il rischio papere (da {blunders_give} a {blunders_receive} blunders stagionali).")
        elif blunders_receive > blunders_give:
            reasons.append(f"⚠️ Rischio errori decisivi: il portiere in arrivo ha già commesso {blunders_receive} blunders/papere con voto <= 5.0 in stagione.")

        if save_pct_receive > save_pct_give + 4.0:
            reasons.append(f"🧤 Maggior percentuale parate per i ricevuti ({save_pct_receive}% vs {save_pct_give}%).")

    # D-Factor and sufficiency comparison
    if not df_recv_dfactor.empty and not df_give_dfactor.empty:
        if suff_receive > suff_give + 6.0:
            reasons.append(f"🛡️ Protezione D-Factor: il pacchetto che ricevi offre una sufficienza (voti >= 6) del {suff_receive}% vs {suff_give}% dei ceduti (+{round(suff_receive - suff_give, 1)}% affidabilità voto puro).")
        elif suff_give > suff_receive + 6.0:
            reasons.append(f"⚠️ Attenzione al D-Factor: stai cedendo difensori/mediani con sufficienza più affidabile ({suff_give}% vs {suff_receive}% dei ricevuti).")

    # Real Starter status reasons
    for sw in starter_warnings:
        reasons.append(sw)
    for sb in starter_bonuses:
        reasons.append(sb)

    if buy_low_incoming:
        reasons.append(f"Ottimo tempismo d'acquisto: {', '.join(buy_low_incoming)} ha alti xG/xA e sta per sbloccarsi (Buy-Low).")
    if sell_high_outgoing:
        reasons.append(f"Ottima vendita al picco: {', '.join(sell_high_outgoing)} sta sovraperformando la fortuna (Sell-High).")
    if sell_high_incoming:
        reasons.append(f"Cautela: {', '.join(sell_high_incoming)} ha segnato più di quanto prodotto (rischio regressione negativa).")

    return {
        'Verdetto': verdict,
        'StatusColor': status_color,
        'Delta_Totale_xFV': delta_totale_ponderato,
        'Delta_Medio_Partita': delta_medio_partita,
        'Delta_Totale_Raw': delta_raw_totale,
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
        'xA_Ceduti_90': xa_give,
        'xA_Ricevuti_90': xa_receive,
        'xGTot_Ceduti': xgtot_give,
        'xGTot_Ricevuti': xgtot_receive,
        'Delta_xG_Ceduti': deltaxg_give,
        'Delta_xG_Ricevuti': deltaxg_receive,
        'KP_Ceduti_90': kp_give,
        'KP_Ricevuti_90': kp_receive,
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
        'Ceduti_Info': give_df[['Giocatore', 'Squadra', 'RuoloMantra', 'MV_Stagione', 'FM_Stagione', 'Tiri_90', 'xG_90', 'Signal']].to_dict(orient='records'),
        'Ricevuti_Info': receive_df[['Giocatore', 'Squadra', 'RuoloMantra', 'MV_Stagione', 'FM_Stagione', 'Tiri_90', 'xG_90', 'Signal']].to_dict(orient='records'),
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

    # Simulate a trade: Bonny + Pasalic for Malen (2 for 1)
    give = ['Bonny', 'Pasalic']
    receive = ['Malen']

    print("\n--- TEST VALUTATORE SCAMBI (Bonny + Pasalic vs Malen, 5 giornate) ---")
    res = evaluate_trade(give, receive, df_m, start_matchday=8, horizon=5)
    print(f"VERDETTO: {res['Verdetto']}")
    print(f"Delta Totale Ponderato: {res['Delta_Totale_xFV']} (Ceduti: {res['xFV_Ceduti_Tot']} vs Ricevuti: {res['xFV_Ricevuti_Tot']})")
    print(f"Delta Medio a Partita: {res['Delta_Medio_Partita']} xFV/partita")
    print(f"Tiri/90: Ceduti {res['Tiri_Ceduti_90']} vs Ricevuti {res['Tiri_Ricevuti_90']}")
    print(f"FDR: Ceduti {res['FDR_Medio_Ceduti']} vs Ricevuti {res['FDR_Medio_Ricevuti']}")
    print("Motivazioni:")
    for m in res['Motivazioni']:
        try:
            print(f" - {m}")
        except Exception:
            print(f" - {m.encode('ascii', 'replace').decode('ascii')}")
    print("\nTimeline:\n", res['Timeline'][['Giornata', 'xFV_Ceduti', 'xFV_Ricevuti', 'Delta_Giornata']])
