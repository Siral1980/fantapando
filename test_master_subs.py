import json
import os
import sys
import pandas as pd

sys.path.insert(0, r"C:\Users\gdeluca\.gemini\antigravity\scratch\fantacalcio")
from engine.models import batch_predict_xfv
from engine.optimizer import (
    optimize_best_mantra_lineup,
    simulate_master_substitutions,
    audit_master_bench_coverage
)

def run_regression_tests():
    data_dir = r"C:\Users\gdeluca\.gemini\antigravity\scratch\fantacalcio\data"
    with open(os.path.join(data_dir, "user_roster.json"), encoding="utf-8") as f:
        squad_names = json.load(f)

    df_all = pd.read_csv(os.path.join(data_dir, "players_master.csv"))
    df_squad = df_all[df_all['Giocatore'].isin(squad_names)].copy()
    df_proj = batch_predict_xfv(df_squad)
    res = optimize_best_mantra_lineup(df_proj)

    assert res is not None, "Optimization returned None"
    assert len(res['Titolari']) == 11, "Starters count != 11"
    assert len(res['Panchina']) <= 12, "Bench count > 12"
    
    # Check Pos 1 is 2nd GK
    assert 'Por' in res['Panchina'][0]['RuoloMantra'], "Pos 1 must be a Goalkeeper"
    assert res['Panchina'][0]['Posizione_Panchina'] == 1, "Pos 1 must have Posizione_Panchina == 1"
    
    # Check Top 5 Outfield changes (Pos 2 to 6)
    for b in res['Panchina'][1:6]:
        assert b['Fascia_Master'] == '⭐ TOP 5 CAMBIO', f"Pos {b['Posizione_Panchina']} should be ⭐ TOP 5 CAMBIO"
        
    # Check automated audit
    audit = res.get('Audit_Copertura')
    assert audit is not None and not audit.empty, "Coverage audit missing"
    assert all('✅' in esito for esito in audit['Esito']), "Some audit scenarios were not covered"

    # Test single substitution: Missing starting Por
    por_tit = [t for t in res['Titolari'] if 'Por' in t['Slot_Assegnato']][0]
    sim_por = simulate_master_substitutions(
        res['Titolari'],
        res['Panchina'],
        res['Modulo'],
        max_subs=5,
        simulated_missing_names=[por_tit['Giocatore']]
    )
    assert sim_por['Cambi_Effettuati'] == 1
    assert sim_por['Sostituzioni'][0]['In_Pos'] == 1

    # Test 3 substitutions simultaneously
    three_missing = [res['Titolari'][1]['Giocatore'], res['Titolari'][5]['Giocatore'], res['Titolari'][10]['Giocatore']]
    sim_3 = simulate_master_substitutions(
        res['Titolari'],
        res['Panchina'],
        res['Modulo'],
        max_subs=5,
        simulated_missing_names=three_missing
    )
    assert sim_3['Cambi_Effettuati'] == 3, f"Expected 3 subs, got {sim_3['Cambi_Effettuati']}"
    assert len(sim_3['Sostituzioni']) == 3

    print("All Mantra Master substitution regression tests PASSED successfully!")

if __name__ == '__main__':
    run_regression_tests()
