import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, r"C:\Users\gdeluca\.gemini\antigravity\scratch\fantacalcio")
from engine.roster_manager import load_user_roster

df = pd.read_csv(r"C:\Users\gdeluca\.gemini\antigravity\scratch\fantacalcio\data\players_master.csv")
tot_giornate = 7.0

records = []
user_p = load_user_roster()
sub = df[df['Giocatore'].isin(user_p)].copy()

for _, r in sub.iterrows():
    p = float(r.get('Presenze', 0))
    m = float(r.get('Minuti_Reali', 0))
    mv_stag = float(r.get('MV_Stagione', 6.0))
    mv_triennio = float(r.get('MV_Triennio', 6.0))
    if mv_triennio <= 0:
        mv_triennio = 6.0
        
    # 1. Bayesian shrinkage of MV based on sample size (K = 3.0 matches)
    w_sample = p / (p + 3.0)
    mv_bayesian = (w_sample * mv_stag) + ((1.0 - w_sample) * mv_triennio)
    
    # 2. Probability of vote / Titolarità
    min_per_app = (m / p) if p > 0 else 0.0
    p_voto = np.clip(0.10 + 0.55 * (p / tot_giornate) + 0.35 * min(1.0, min_per_app / 70.0), 0.05, 0.98)
    
    # 3. Status label
    if p_voto >= 0.85:
        status = "[TITOLARE FISSO]"
    elif p_voto >= 0.65:
        status = "[ROTAZIONE]"
    elif p_voto >= 0.35:
        status = "[BALLOTTAGGIO / RISCHIO SV]"
    else:
        status = "[RISERVA]"
        
    records.append({
        'Giocatore': r['Giocatore'],
        'Squadra': r['Squadra'],
        'Ruolo': r['RuoloMantra'],
        'Presenze': f"{int(p)}/{int(tot_giornate)}",
        'Min/Gara': int(min_per_app),
        'MV Raw': mv_stag,
        'MV Bayes': round(mv_bayesian, 2),
        'P(Voto)': f"{int(p_voto * 100)}%",
        'Status': status
    })

res_df = pd.DataFrame(records).sort_values(by='P(Voto)', ascending=False)
print("=== TITOLARITA & P(VOTO) SULLA TUA ROSA ===")
print(res_df.to_string(index=False))
