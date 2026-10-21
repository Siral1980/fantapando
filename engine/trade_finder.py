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
    - SUBENTRANTE: Late substitute / bench warmer (< 45 min/app or < 28% team minutes, e.g. Lucca, Nzola, Kevin Carlos, Beto)
    - MARGINALE: Rare or zero appearances (< 2 apps or < 70 min total)
    """
    pres = float(row.get('Presenze', 0))
    mins = float(row.get('Minuti_Reali', 0))
    tot_mins = tot_matchdays * 90.0
    
    m_per_app = (mins / pres) if pres > 0 else 0.0
    pct_mins = (mins / tot_mins * 100.0) if tot_mins > 0 else 0.0
    pct_suff = float(row.get('Pct_Sufficienza', 50.0))
    
    if (m_per_app >= 55.0 and pct_mins >= 45.0) or (m_per_app >= 68.0 and pres >= 3) or pct_mins >= 65.0:
        return {
            'Status': 'TITOLARE',
            'Badge': '🟢 TITOLARE FISSO',
            'Label': f'🟢 Titolare ({int(m_per_app)} min/p)',
            'Min_Per_Pres': round(m_per_app, 1),
            'Pct_Minuti': round(pct_mins, 1),
            'Tier_Weight': 1.0,
            'Is_Real_Starter': True
        }
    elif (m_per_app >= 45.0 and pct_mins >= 28.0) or (m_per_app >= 40.0 and pres >= 4 and pct_mins >= 24.0 and pct_suff >= 40.0):
        return {
            'Status': 'CO_TITOLARE',
            'Badge': '🟡 CO-TITOLARE',
            'Label': f'🟡 Co-Titolare ({int(m_per_app)} min/p)',
            'Min_Per_Pres': round(m_per_app, 1),
            'Pct_Minuti': round(pct_mins, 1),
            'Tier_Weight': 0.75,
            'Is_Real_Starter': True
        }
    elif pres >= 2 and mins >= 50:
        return {
            'Status': 'SUBENTRANTE',
            'Badge': '🟠 SUBENTRANTE',
            'Label': f'🟠 Subentrante ({int(m_per_app)} min/p)',
            'Min_Per_Pres': round(m_per_app, 1),
            'Pct_Minuti': round(pct_mins, 1),
            'Tier_Weight': 0.35,
            'Is_Real_Starter': False
        }
    else:
        return {
            'Status': 'MARGINALE',
            'Badge': '🔴 MARGINALE',
            'Label': '🔴 Riserva Marginale',
            'Min_Per_Pres': round(m_per_app, 1),
            'Pct_Minuti': round(pct_mins, 1),
            'Tier_Weight': 0.10,
            'Is_Real_Starter': False
        }


def analyze_squad_weaknesses(team_name, league_data, df_master, matchday=8):
    """
    Performs a deep diagnostic analysis of a fantasy team's roster:
    1. Evaluates departmental depth vs recommended Mantra quotas (filtering by active players).
    2. Measures starting quality (xFV), sufficiency reliability (D-Factor impact), and bonus threat.
    3. Identifies critical bottlenecks (Punti Deboli) and structural surpluses (Asset di Scambio).
    """
    if team_name not in league_data:
        return {'error': f"Squadra '{team_name}' non trovata nella lega."}

    team_players_all = league_data[team_name]
    # For market/trade analysis, only consider owned assets (Costo > 0, not temporary loans from other clubs)
    team_players = [p for p in team_players_all if not p.get('InPrestito', False) and p.get('Costo', 1) > 0]
    player_names = [p['Giocatore'] for p in team_players]
    
    df_squad = df_master[df_master['Giocatore'].isin(player_names)].copy()
    if df_squad.empty:
        return {'error': "Nessun calciatore della squadra trovato nel database master."}

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
    top_gk = max(pors, key=lambda p: float(p.get('Presenze', 0))) if pors else None
    
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
    if top_gk is not None and float(top_gk.get('Presenze', 0)) >= 2:
        gk_name = top_gk['Giocatore']
        gk_gp = float(top_gk.get('Goals_Prevented', 0.0))
        gk_gp90 = float(top_gk.get('Goals_Prevented_90', 0.0))
        gk_blunders = int(top_gk.get('Errors_Leading_To_Goal', 0))
        gk_save_pct = float(top_gk.get('Pct_Parate', 70.0))
        
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
        top_w_names = ', '.join(p['Giocatore'] for p in sorted(ws, key=lambda x: float(x.get('xFV', 0)), reverse=True)[:4])
        strengths.append(f"Arsenale ali offensive: {len(ws)} W attive ad alto potenziale ({top_w_names}).")
    if len(a_s) >= 3:
        top_a_names = ', '.join(p['Giocatore'] for p in sorted(a_s, key=lambda x: float(x.get('xFV', 0)), reverse=True)[:3])
        strengths.append(f"Profondità di seconde punte: {len(a_s)} A a disposizione ({top_a_names}), eccellente moneta di scambio sul mercato.")

    # 3. Identify Surplus Trade Assets (Calciatori spendibili sul mercato)
    # Note: Players whose ONLY roles are in critically deficient departments are NOT surplus!
    critically_weak_roles = set(w['Ruolo'] for w in weaknesses if w.get('Severita') in ('CRITICA', 'ELEVATA'))
    
    surplus_assets = []
    bench_df = df_proj[~df_proj['Giocatore'].isin(starter_names)].copy()
    
    for _, b_row in bench_df.iterrows():
        pname = b_row['Giocatore']
        
        # Medical Availability: CANNOT offer injured or suspended players in cession!
        from engine.injuries_manager import classify_injury_status
        inj_status = classify_injury_status(pname)
        if not inj_status['Can_Be_Traded_Out']:
            continue
            
        roles_str = b_row.get('RuoloMantra', '')
        xfv = float(b_row.get('xFV', 0))
        sig = str(b_row.get('Signal', 'NEUTRO'))
        roles = parse_mantra_roles(roles_str)
        presenze = int(b_row.get('Presenze', 0))
        
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
                'xFV': xfv,
                'FM_Stagione': float(b_row.get('FM_Stagione', 0)),
                'Costo': int(b_row.get('Costo', 0)),
                'GF': int(b_row.get('GF', 0)),
                'Signal': sig,
                'Motivo_Cessione': "; ".join(reasons),
                'Goals_Prevented': float(b_row.get('Goals_Prevented', 0.0)),
                'Goals_Prevented_90': float(b_row.get('Goals_Prevented_90', 0.0)),
                'Errors_Leading_To_Goal': int(b_row.get('Errors_Leading_To_Goal', 0)),
                'Pct_Parate': float(b_row.get('Pct_Parate', 70.0)),
                'xG_Tot': float(b_row.get('xG_Tot', 0.0)),
                'xG_90': float(b_row.get('xG_90', 0.0)),
                'Delta_xG': float(b_row.get('Delta_xG', 0.0)),
                'Tiri_90': float(b_row.get('Tiri_90', 0.0)),
                'Key_Passes_90': float(b_row.get('Key_Passes_90', 0.0)),
                'xA_90': float(b_row.get('xA_90', 0.0))
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


def is_trade_role_parity_credible(give_dict, receive_dict):
    """
    Validates whether a proposed 1-to-1 swap respects Fantacalcio Mantra role hierarchy
    and fantasy football market credibility:
    - Tier 1: Pc, A (Centre Forwards and Second Strikers - Scarcest assets, +3 goal impact)
    - Tier 2: W, T (Attacking Wings and Trequartisti)
    - Tier 3: M, C, E, Dc, Dd, Ds (Midfield and Defensive Tactical Foundation)
    - Tier 4: Por (Goalkeepers)
    
    Rule 1: Nobody trades a Pc or A for a standard M, C, or Defender unless the given player
            is an undisputed 'Top di Reparto' (FM >= 6.70, GF >= 2, or Costo >= 16) or an elite W/T.
    Rule 2: Nobody trades an established starting W or T for a zero-bonus defensive midfielder or bench defender.
    Rule 3: Tactical cross-exchanges within M, C, E, Dc, Dd, Ds are credible if xFV is balanced.
    Rule 4: Por is only exchanged for other Por or comparable tactical assets.
    """
    give_roles = parse_mantra_roles(give_dict.get('RuoloMantra', ''))
    rec_roles = parse_mantra_roles(receive_dict.get('RuoloMantra', ''))
    
    is_rec_striker = any(r in ['Pc', 'A'] for r in rec_roles)
    is_give_striker = any(r in ['Pc', 'A'] for r in give_roles)
    
    is_rec_wing_t = any(r in ['W', 'T'] for r in rec_roles)
    is_give_wing_t = any(r in ['W', 'T'] for r in give_roles)
    
    give_fm = float(give_dict.get('FM', give_dict.get('FM_Stagione', 0)) or 0)
    give_xfv = float(give_dict.get('xFV', 0) or 0)
    give_gf = int(give_dict.get('GF', 0) or 0)
    give_costo = int(give_dict.get('Costo', 0) or 0)
    
    # Top di Reparto criteria (e.g. McTominay, Calhanoglu, Dimarco, Barella, Koopmeiners, Pulisic):
    is_give_top_dept = (
        give_gf >= 2 or 
        (give_fm >= 6.70 and give_xfv >= 5.8) or 
        (give_costo >= 16 and give_fm >= 6.30)
    )
    
    # 1. TARGET IS A STRIKER (Pc or A)
    if is_rec_striker:
        # A) You give another striker (Pc or A)
        if is_give_striker:
            return True
        # B) You give an elite attacking wing / trequartista (W or T with strong fantasy output)
        if is_give_wing_t:
            if give_xfv >= 5.5 and (give_fm >= 6.35 or give_gf >= 1 or give_costo >= 14):
                return True
            return False
        # C) You give a Top di Reparto from midfield or defense
        if is_give_top_dept:
            return True
        # Standard M, C, D, or Por for a Pc/A is REJECTED
        return False
        
    # 2. TARGET IS AN ATTACKING WING OR TREQUARTISTA (W or T)
    if is_rec_wing_t:
        # A) You give a striker (Pc, A) or another W/T
        if is_give_striker or is_give_wing_t:
            return True
        # B) You give a quality central midfielder (C) or attacking wing-back (E) with bonus threat
        is_give_c_e = any(r in ['C', 'E'] for r in give_roles)
        if is_give_c_e and (give_fm >= 6.30 or give_gf >= 1 or give_xfv >= 5.6):
            return True
        # C) You give a top defensive midfielder (M) or top defender (D)
        if is_give_top_dept or (give_fm >= 6.55 and give_xfv >= 5.7):
            return True
        # Ordinary M or D without bonus for W/T is unrealistic
        return False

    # 3. TARGET IS A GOALKEEPER (Por)
    if 'Por' in rec_roles:
        # If target is a top starting goalkeeper (e.g. Maignan, Sommer, Di Gregorio with auction Costo >= 20 or 4+ starts):
        rec_costo = int(receive_dict.get('Costo', 0) or 0)
        rec_pres = int(receive_dict.get('Presenze', 0) or 0)
        is_rec_top_gk = (rec_costo >= 20 or rec_pres >= 4)
        if is_rec_top_gk:
            # A fantasy manager will not trade a top starting GK for an ordinary bench defender or midfielder
            if 'Por' in give_roles:
                return True
            if is_give_striker or is_give_top_dept:
                return True
            if is_give_wing_t and give_xfv >= 5.6 and (give_costo >= 16 or give_fm >= 6.4):
                return True
            return False
        return True

    # 4. TARGET IS TACTICAL MIDFIELD OR DEFENSE (M, C, E, Dc, Dd, Ds)
    # Tactical balance exchanges are credible if values are close
    return True


def find_win_win_trades(
    my_team_name, league_data, df_master, matchday=8, 
    target_role_filter=None, give_player_filter=None, opp_team_filter=None, 
    min_starter_filter='TITOLARI_E_CO', df_all_proj=None, max_proposals=30
):
    """
    Automated Win-Win Trade Finder:
    Scans opponent teams in the fantasy league.
    Finds trades where:
    - You offer a player from your SURPLUS (who currently sits on your bench or whose role you have in abundance).
    - The opponent has a DEFICIENCY in that role (so your player is an instant upgrade for them).
    - You receive a player in a role that improves your squad (Pc, M, Dd, Ds, Dc).
    - Filters by real Serie A starter status to prevent recommending subentranti (e.g. Lucca, Nzola, Kevin Carlos).
    
    Returns prioritized list of mutually advantageous trade proposals with tactical negotiation arguments.
    """
    my_diag = analyze_squad_weaknesses(my_team_name, league_data, df_master, matchday=matchday)
    if 'error' in my_diag:
        return []

    my_weak_roles = set(w['Ruolo'] for w in my_diag['Punti_Deboli'])
    # If no strict numerical weakness, consider natural upgrade target roles
    if not my_weak_roles:
        my_weak_roles = {'Pc', 'M', 'Dc', 'Dd', 'Ds'}

    my_surplus_players = my_diag['Surplus_Cedibili']
    if not my_surplus_players:
        return []

    # Filter by specific player to give if requested
    if give_player_filter and give_player_filter != 'TUTTI':
        my_surplus_players = [p for p in my_surplus_players if p['Giocatore'] == give_player_filter]
        if not my_surplus_players:
            return []

    # Pre-project all players in df_master for matchday if not provided
    if df_all_proj is None or df_all_proj.empty:
        df_all_proj = batch_predict_xfv(df_master, matchday=matchday)
    proj_map = {row['Giocatore']: row.to_dict() for _, row in df_all_proj.iterrows()}

    # Build league auction cost lookup (taking max cost to ensure true ownership cost)
    costo_map = {}
    for t_players in league_data.values():
        for p in t_players:
            if 'Giocatore' in p and 'Costo' in p:
                name = p['Giocatore']
                cost = int(p['Costo'] or 0)
                costo_map[name] = max(costo_map.get(name, 0), cost)

    trade_proposals = []

    for opp_team, opp_players in league_data.items():
        if opp_team == my_team_name:
            continue
        if opp_team_filter and opp_team_filter != 'TUTTI' and opp_team != opp_team_filter:
            continue

        # Only owned assets can be traded: exclude temporary loans (InPrestito == True or Costo == 0)
        opp_players_owned = [p for p in opp_players if not p.get('InPrestito', False) and p.get('Costo', 1) > 0]
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
        # Fast presumptive starters: top 11 by xFV
        opp_starters = set(df_opp_proj.sort_values('xFV', ascending=False).head(11)['Giocatore'])

        # Count opponent active roles
        opp_roles_active = {}
        for p in opp_proj_list:
            is_active = (p.get('Presenze', 0) >= 2 or p.get('P_Voto', 0) >= 0.50)
            for r in parse_mantra_roles(p.get('RuoloMantra', '')):
                if is_active:
                    opp_roles_active[r] = opp_roles_active.get(r, 0) + 1

        # Check where opponent is short (Deficiency) and where they are rich (Surplus)
        for my_give in my_surplus_players:
            my_give_roles = parse_mantra_roles(my_give['RuoloMantra'])
            
            # Opponent short in role I offer?
            opp_short_roles = [
                r for r in my_give_roles 
                if r in RECOMMENDED_QUOTAS and opp_roles_active.get(r, 0) <= RECOMMENDED_QUOTAS[r]['min_active']
            ]
            opp_needs_my_give = len(opp_short_roles) > 0
            
            # Loop over opponent players
            for opp_p in opp_proj_list:
                opp_p_name = opp_p['Giocatore']
                opp_p_roles = parse_mantra_roles(opp_p.get('RuoloMantra', ''))
                
                # Filter by target role if specified by user
                if target_role_filter and target_role_filter != 'TUTTI':
                    if target_role_filter not in opp_p_roles:
                        continue
                elif not target_role_filter:
                    # Default when no filter is provided: prioritize squad weaknesses
                    if my_weak_roles and not opp_p_roles.intersection(my_weak_roles):
                        continue

                # 0. Check medical availability for opponent player
                from engine.injuries_manager import classify_injury_status
                opp_inj = classify_injury_status(opp_p_name)

                # Disallow long-term injuries (>= 3 weeks, surgery, cruciate, months out)
                if opp_inj['Is_Long_Term']:
                    continue

                # Disallow suspended players if looking to solve urgent weakness
                if opp_inj.get('Stato') == 'Squalificato':
                    continue

                is_opp_injured = opp_inj['Is_Injured']
                is_stash_injury = False

                if is_opp_injured:
                    # If the user has a CRITICAL deficiency in this role, an injured player cannot solve it immediately!
                    role_has_critical_weakness = any(
                        w['Ruolo'] in opp_p_roles and w.get('Severita') in ('CRITICA', 'ELEVATA')
                        for w in my_diag['Punti_Deboli']
                    )
                    if role_has_critical_weakness:
                        continue  # Cannot solve an urgent hole with an unavailable player
                    
                    # If it's a minor/short-term injury for depth or upgrade, it's a smart "Stash" strategy
                    is_stash_injury = True

                # 0b. Role Parity & Hierarchy Credibility Check
                if not is_trade_role_parity_credible(my_give, opp_p):
                    continue

                # 1. Compute real starter status in Serie A
                opp_p_status = compute_real_starter_status(opp_p)
                
                # Filter by user's starter status preference
                if min_starter_filter == 'TITOLARI_SOLO':
                    if opp_p_status['Status'] != 'TITOLARE':
                        continue
                elif min_starter_filter == 'TITOLARI_E_CO':
                    if opp_p_status['Status'] not in ['TITOLARE', 'CO_TITOLARE']:
                        continue
                elif min_starter_filter == 'TUTTI':
                    # Allow all, but exclude completely marginal players (< 2 apps)
                    if opp_p_status['Status'] == 'MARGINALE':
                        continue

                opp_p_xfv = float(opp_p.get('xFV', 0))
                my_give_xfv = float(my_give['xFV'])
                
                # Check realistic exchange parity (within 1.85 xFV points)
                xfv_gap = opp_p_xfv - my_give_xfv
                if abs(xfv_gap) > 1.85:
                    continue

                # Don't swap same weak role unless it's a significant upgrade
                same_weak_roles = my_give_roles.intersection(opp_p_roles).intersection(my_weak_roles)
                if same_weak_roles and opp_p_xfv <= my_give_xfv + 0.3:
                    continue

                is_on_opp_bench = (opp_p_name not in opp_starters)
                is_buy_low = ('BUY-LOW' in str(opp_p.get('Signal', '')))
                is_sell_high = ('SELL-HIGH' in my_give.get('Signal', ''))
                opp_pct_suff = float(opp_p.get('Pct_Sufficienza', 50.0))
                
                # Calculate Win-Win Score
                score = 50.0
                reasons = []
                
                # A. Opponent Need satisfaction (High leverage)
                if opp_needs_my_give:
                    score += 35.0
                    short_str = "/".join(opp_short_roles)
                    cnt = opp_roles_active.get(opp_short_roles[0], 0)
                    reasons.append(f"Bisogno forte di {opp_team}: hanno solo {cnt} giocatori attivi in {short_str} e cercano urgentemente un titolare")
                elif any(opp_roles_active.get(r, 0) <= 3 for r in my_give_roles):
                    score += 15.0
                    reasons.append(f"{opp_team} ha rotazioni corte nel ruolo di {my_give['Giocatore']}")

                # B. Real Starter Quality & Weakness Resolution
                matching_weakness = [w for w in my_diag['Punti_Deboli'] if w['Ruolo'] in opp_p_roles]
                if opp_p_status['Status'] == 'TITOLARE':
                    score += 35.0
                    reasons.append(f"🟢 Titolare inamovibile in Serie A: media di {opp_p_status['Min_Per_Pres']} min/partita ({opp_p_status['Pct_Minuti']}% dei minuti totali)")
                    if matching_weakness:
                        w_obj = matching_weakness[0]
                        score += 30.0 if w_obj['Severita'] == 'CRITICA' else 20.0
                        reasons.append(f"Risolve un tuo punto debole: colma la carenza in {w_obj['Reparto']} ({w_obj['Ruolo']}) con un titolare fisso")
                    else:
                        reasons.append(f"Rinforzo di livello: inserisci un titolare comprovato nel reparto {list(opp_p_roles)[0]}")
                elif opp_p_status['Status'] == 'CO_TITOLARE':
                    score += 20.0
                    reasons.append(f"🟡 Co-titolare / rotazione frequente in Serie A: media di {opp_p_status['Min_Per_Pres']} min/partita ({opp_p_status['Pct_Minuti']}% minuti)")
                    if matching_weakness:
                        w_obj = matching_weakness[0]
                        score += 20.0 if w_obj['Severita'] == 'CRITICA' else 15.0
                        reasons.append(f"Risolve un tuo punto debole: garantisce una solida opzione in {w_obj['Reparto']} ({w_obj['Ruolo']})")
                else: # SUBENTRANTE
                    # If user has a critical weakness in this department, a subentrante does NOT solve it!
                    score -= 30.0
                    reasons.append(f"⚠️ Subentrante / Riserva in Serie A: gioca solo ~{opp_p_status['Min_Per_Pres']} min a partita; non garantisce titolarità")

                # C. Rating sufficiency reliability
                if opp_pct_suff >= 60.0:
                    score += 15.0
                    reasons.append(f"🛡️ Alta affidabilità di voto: {opp_pct_suff:.1f}% di partite con voto >= 6.0")
                elif opp_pct_suff < 35.0:
                    score -= 25.0
                    reasons.append(f"⚠️ Rischio insufficienze: solo il {opp_pct_suff:.1f}% di voti >= 6.0")

                # D. Advanced GK and Outfield Metrics Evaluation
                opp_gp = float(opp_p.get('Goals_Prevented', 0.0))
                opp_gp90 = float(opp_p.get('Goals_Prevented_90', 0.0))
                opp_errs = int(opp_p.get('Errors_Leading_To_Goal', 0))
                opp_save_pct = float(opp_p.get('Pct_Parate', 70.0))
                opp_xg_tot = float(opp_p.get('xG_Tot', 0.0))
                opp_xg90 = float(opp_p.get('xG_90', 0.0))
                opp_delta_xg = float(opp_p.get('Delta_xG', 0.0))
                opp_tiri = float(opp_p.get('Tiri_90', 0.0))
                opp_kp = float(opp_p.get('Key_Passes_90', 0.0))
                opp_xa90 = float(opp_p.get('xA_90', 0.0))

                if 'Por' in opp_p_roles:
                    if opp_gp >= +2.0:
                        score += 35.0
                        reasons.append(f"🧤 Shot-stopping d'élite: {opp_p_name} vanta {opp_gp:+.2f} gol evitati ({opp_gp90:+.2f}/90) e {opp_save_pct:.1f}% di parate")
                    elif opp_gp <= -1.0:
                        score -= 30.0
                        reasons.append(f"⚠️ Sotto-performance al tiro: {opp_p_name} ha concesso {abs(opp_gp):.2f} gol in più del previsto (PSxG)")
                    
                    if opp_errs > 0:
                        score -= 35.0 * opp_errs
                        reasons.append(f"⚠️ Rischio papere: {opp_p_name} ha all'attivo {opp_errs} blunders decisivi (voto <= 5.0)")
                    elif opp_errs == 0 and opp_gp >= +0.5:
                        score += 15.0
                        reasons.append(f"🛡️ Massima sicurezza tra i pali: zero errori decisivi e resa positiva sui tiri")
                else:
                    if opp_tiri >= 2.0 or opp_xg90 >= 0.25:
                        score += 15.0
                        reasons.append(f"🔥 Alto volume offensivo: {opp_tiri:.1f} tiri e {opp_xg90:.2f} xG/90 min")
                    elif opp_kp >= 1.5 or opp_xa90 >= 0.15:
                        score += 12.0
                        reasons.append(f"🎯 Macchina da assist: {opp_kp:.1f} passaggi chiave e {opp_xa90:.2f} xA/90 min")

                # E. Buy-Low leverage (Great opportunity)
                if is_buy_low:
                    score += 25.0
                    reasons.append(f"Opportunità BUY-LOW: {opp_p_name} produce molto volume (xG {opp_xg_tot:.2f}) ma ha segnato meno per sfortuna (ΔxG {opp_delta_xg:+.2f}); perfetto da acquistare a sconto")

                # E2. Short-term Injury Stash leverage
                if is_stash_injury:
                    score += 20.0
                    inj_det = opp_inj.get('Dettaglio', 'rientro previsto a breve')
                    reasons.append(f"🩹 Opportunità STASH (Infortunio lieve): {opp_p_name} è ai box ({inj_det}); ottima occasione per strapparlo a prezzo di saldo da una rivale che necessita di voti immediati")

                # F. Sell-High leverage (Smart cash-in)
                if is_sell_high:
                    score += 15.0
                    reasons.append(f"Momento SELL-HIGH: cedi {my_give['Giocatore']} al picco del valore dopo gol fortunati oltre l'xG")

                # G. Bench utilization in fantasy team (only valuable if the player is genuinely good!)
                if is_on_opp_bench and opp_p_status['Is_Real_Starter']:
                    score += 15.0
                    reasons.append(f"{opp_p_name} è attualmente sacrificato in panchina da {opp_team}: saranno più propensi a cederlo")

                # H. xFV Parity bonus
                if opp_p_xfv >= my_give_xfv:
                    score += 10.0
                    reasons.append(f"Guadagno statistico netto: +{round(opp_p_xfv - my_give_xfv, 2)} xFV sul cartellino")
                else:
                    score += 5.0

                # Formulate ready-to-use negotiation pitch
                target_role_str = "/".join(list(opp_p_roles))
                opp_dept_name = _get_department_name(opp_p_roles)
                short_str = "/".join(opp_short_roles) if opp_short_roles else my_give['RuoloMantra']
                
                if 'Por' in opp_p_roles:
                    target_desc = f"un portiere solido come {opp_p_name} ({opp_gp:+.2f} gol evitati vs PSxG)"
                elif opp_p_status['Status'] == 'TITOLARE':
                    target_desc = f"un titolare fisso come {opp_p_name} (gioca oltre {int(opp_p_status['Min_Per_Pres'])} min a partita)"
                elif opp_p_status['Status'] == 'CO_TITOLARE':
                    target_desc = f"una valida rotazione come {opp_p_name} ({int(opp_p_status['Min_Per_Pres'])} min a partita)"
                else:
                    target_desc = f"un cambio numerico come {opp_p_name}"

                if is_stash_injury:
                    inj_det = opp_inj.get('Dettaglio', 'rientro a breve')
                    pitch = (
                        f"Ciao! Ho visto che {opp_p_name} è momentaneamente ai box ({inj_det}), mentre a voi servono punti "
                        f"e titolari pronti subito nello slot {short_str}. Vi andrebbe di valutare uno scambio con {my_give['Giocatore']}, "
                        f"che è integro, titolare e garantisce voto fin da subito? A voi risolve l'emergenza di formazione per i prossimi turni, "
                        f"e noi possiamo attendere con calma il suo rientro. Che ne dite?"
                    )
                else:
                    pitch = (
                        f"Ciao! Ho notato che per {opp_team} farebbe comodo rinforzare lo slot {short_str} (avete poche rotazioni lì), "
                        f"mentre avete buone alternative {opp_dept_name}. Vi andrebbe di valutare uno scambio alla pari tra {my_give['Giocatore']} e {opp_p_name}? "
                        f"A voi garantisce un titolare affidabile dove siete scoperti, e a noi permetterebbe di inserire {target_desc}. È un'ottima soluzione win-win per entrambi!"
                    )

                trade_proposals.append({
                    'Score': round(score, 1),
                    'Squadra_Avversaria': opp_team,
                    'Is_Stash_Injury': is_stash_injury,
                    'Tu_Cedi': {
                        'Giocatore': my_give['Giocatore'],
                        'Squadra': my_give['Squadra'],
                        'RuoloMantra': my_give['RuoloMantra'],
                        'xFV': my_give['xFV'],
                        'FM': my_give['FM_Stagione'],
                        'Signal': my_give['Signal'],
                        'Goals_Prevented': float(my_give.get('Goals_Prevented', 0.0)),
                        'Goals_Prevented_90': float(my_give.get('Goals_Prevented_90', 0.0)),
                        'Errors_Leading_To_Goal': int(my_give.get('Errors_Leading_To_Goal', 0)),
                        'Pct_Parate': float(my_give.get('Pct_Parate', 70.0)),
                        'xG_Tot': float(my_give.get('xG_Tot', 0.0)),
                        'xG_90': float(my_give.get('xG_90', 0.0)),
                        'Delta_xG': float(my_give.get('Delta_xG', 0.0)),
                        'Tiri_90': float(my_give.get('Tiri_90', 0.0)),
                        'Key_Passes_90': float(my_give.get('Key_Passes_90', 0.0)),
                        'xA_90': float(my_give.get('xA_90', 0.0))
                    },
                    'Tu_Ricevi': {
                        'Giocatore': opp_p_name,
                        'Squadra': opp_p.get('Squadra', ''),
                        'RuoloMantra': opp_p.get('RuoloMantra', ''),
                        'xFV': opp_p_xfv,
                        'FM': float(opp_p.get('FM_Stagione', 0)),
                        'Signal': str(opp_p.get('Signal', 'NEUTRO')),
                        'Is_Buy_Low': is_buy_low,
                        'Is_Injured': is_opp_injured,
                        'Is_Stash_Injury': is_stash_injury,
                        'Injury_Detail': opp_inj.get('Dettaglio', ''),
                        'Injury_Severity': opp_inj.get('Severity_Label', 'DISPONIBILE'),
                        'Is_Bench_In_Opponent': is_on_opp_bench,
                        'Status_Titolarita': opp_p_status['Status'],
                        'Badge_Titolarita': opp_p_status['Badge'],
                        'Label_Titolarita': opp_p_status['Label'],
                        'Min_Per_Pres': opp_p_status['Min_Per_Pres'],
                        'Pct_Minuti': opp_p_status['Pct_Minuti'],
                        'Pct_Sufficienza': opp_pct_suff,
                        'Is_Subentrante': not opp_p_status['Is_Real_Starter'],
                        'Goals_Prevented': opp_gp,
                        'Goals_Prevented_90': opp_gp90,
                        'Errors_Leading_To_Goal': opp_errs,
                        'Pct_Parate': opp_save_pct,
                        'xG_Tot': opp_xg_tot,
                        'xG_90': opp_xg90,
                        'Delta_xG': opp_delta_xg,
                        'Tiri_90': opp_tiri,
                        'Key_Passes_90': opp_kp,
                        'xA_90': opp_xa90
                    },
                    'Ruolo_Target': list(opp_p_roles)[0] if opp_p_roles else 'N/D',
                    'Delta_xFV': round(opp_p_xfv - my_give_xfv, 2),
                    'Motivazioni': reasons,
                    'Messaggio_Trattativa': pitch
                })

    # Sort proposals by highest Win-Win score
    trade_proposals = sorted(trade_proposals, key=lambda x: x['Score'], reverse=True)
    return trade_proposals[:max_proposals]
