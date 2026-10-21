import pandas as pd

df = pd.read_csv(r"C:\Users\gdeluca\.gemini\antigravity\scratch\fantacalcio\data\players_master.csv")
print("All columns in players_master.csv:")
print(df.columns.tolist())

names = ['Corvi', 'Palma', 'Rrahmani', 'De Winter', 'Chukwueze', 'Belghali', 'Adzic', 'Gorter', 'Lontani', 'Schmid']
sub = df[df['Giocatore'].isin(names)]
cols_to_show = [c for c in ['Giocatore', 'Squadra', 'MV_Stagione', 'Mv', 'Pct_Sufficienza', 'Tiri_90', 'xG_90', 'Key_Passes_90', 'xA_90', 'Minuti_Reali', 'Presenze'] if c in df.columns]
print("\nValues for these players in players_master.csv:")
print(sub[cols_to_show].to_string(index=False))
