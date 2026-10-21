import os
import sys
import pandas as pd

sys.path.insert(0, r"C:\Users\gdeluca\.gemini\antigravity\scratch\fantacalcio")
from engine.roster_manager import get_roster_dataframe
from engine.models import get_or_create_calendar, predict_player_xfv

df_master = pd.read_csv(r"C:\Users\gdeluca\.gemini\antigravity\scratch\fantacalcio\data\players_master.csv")
cal = get_or_create_calendar()

df_my_roster = get_roster_dataframe(df_master)
eligible_roster = df_my_roster[df_my_roster['Schierabile'] == True]
dc_players = eligible_roster[eligible_roster['RuoloMantra'].str.contains('Dc', na=False)]

rows = []
for _, r in dc_players.iterrows():
    p = float(r.get('Presenze', 0))
    m = float(r.get('Minuti_Reali', 0))
    min_per_app = (m / p) if p > 0 else 0.0
    p_voto = min(0.98, max(0.05, 0.10 + 0.55 * (p / 7.0) + 0.35 * min(1.0, min_per_app / 70.0)))
    
    pred = predict_player_xfv(r, matchday=6, calendar=cal)
    sv_penalty = round((1.0 - p_voto) * 1.20, 2)
    rows.append({
        'Giocatore': r['Giocatore'],
        'Squadra': r['Squadra'],
        'Match': pred['Match'],
        'FDR': pred['FDR'],
        'Presenze': f"{int(p)}/7",
        'Min/G': int(min_per_app),
        'P(Voto)': f"{int(p_voto*100)}%",
        'Raw xFV': pred['xFV'],
        'SV Penalty': sv_penalty,
        'Adj xFV': round(pred['xFV'] - sv_penalty, 2)
    })

print(pd.DataFrame(rows).sort_values(by='Adj xFV', ascending=False).to_string(index=False))
