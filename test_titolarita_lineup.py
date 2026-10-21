import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, r"C:\Users\gdeluca\.gemini\antigravity\scratch\fantacalcio")
from engine.roster_manager import get_roster_dataframe
from engine.models import get_or_create_calendar, predict_player_xfv
from engine.optimizer import optimize_best_mantra_lineup

df_master = pd.read_csv(r"C:\Users\gdeluca\.gemini\antigravity\scratch\fantacalcio\data\players_master.csv")
cal = get_or_create_calendar()

df_my_roster = get_roster_dataframe(df_master)
eligible_roster = df_my_roster[df_my_roster['Schierabile'] == True]

tot_giornate = 7.0

# Predict with Titolarità & Sample Size adjustments
results = []
for _, r in eligible_roster.iterrows():
    p = float(r.get('Presenze', 0))
    m = float(r.get('Minuti_Reali', 0))
    min_per_app = (m / p) if p > 0 else 0.0
    p_voto = np.clip(0.10 + 0.55 * (p / tot_giornate) + 0.35 * min(1.0, min_per_app / 70.0), 0.05, 0.98)
    
    # Status
    if p_voto >= 0.85:
        status_label = "TITOLARE FISSO"
    elif p_voto >= 0.65:
        status_label = "ROTAZIONE"
    elif p_voto >= 0.35:
        status_label = "BALLOTTAGGIO (Rischio SV)"
    else:
        status_label = "RISERVA"
        
    pred = predict_player_xfv(r, matchday=6, calendar=cal)
    
    # Apply titolarità adjustment to xFV
    sv_penalty = round((1.0 - p_voto) * 1.20, 2)
    min_factor = min(1.0, max(0.25, min_per_app / 80.0))
    
    # Adjust bonus projections by expected minutes
    raw_xfv = pred['xFV']
    adj_xfv = round(raw_xfv - sv_penalty, 2)
    
    pred['P_Voto'] = round(p_voto, 2)
    pred['Status_Titolarita'] = status_label
    pred['Min_Per_App'] = int(min_per_app)
    pred['Presenze_Share'] = f"{int(p)}/{int(tot_giornate)}"
    pred['xFV_Raw'] = raw_xfv
    pred['xFV'] = adj_xfv
    pred['SV_Penalty'] = sv_penalty
    results.append(pred)

df_preds = pd.DataFrame(results).sort_values(by='xFV', ascending=False)
opt = optimize_best_mantra_lineup(df_preds)

print("--- NEW OPTIMAL FORMATION WITH TITOLARITA FACTOR ---")
print("Formation:", opt['Modulo'], "Total Score:", opt['Punti_Attesi_Totali'])
print("\nTitolari:")
for t in opt['Titolari']:
    slot = t['Slot_Assegnato']
    print(
        f"[{slot:>3}] {t['Giocatore']:<12} | "
        f"Pres: {t['Presenze_Share']} ({t['Min_Per_App']}m/g) | "
        f"P(Voto): {int(t['P_Voto']*100)}% ({t['Status_Titolarita']:<14}) | "
        f"xFV: {t['xFV']:.2f}"
    )
