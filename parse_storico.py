import pandas as pd
import glob

path = 'C:/Users/gdeluca/Desktop/GoogleDrive/Projects/Fantacalcio/Dati Storici/'
files = glob.glob(path + '*.xlsx')

all_storico = []

for file in files:
    df = pd.read_excel(file, header=1)
    if 'Nome' in df.columns and 'Fm' in df.columns and 'Pv' in df.columns and 'Rm' in df.columns:
        df_subset = df[['Nome', 'Fm', 'Pv', 'Rm']].copy()
        df_subset['Fm'] = pd.to_numeric(df_subset['Fm'], errors='coerce')
        df_subset['Pv'] = pd.to_numeric(df_subset['Pv'], errors='coerce')
        df_subset = df_subset.dropna(subset=['Fm', 'Pv'])
        df_subset = df_subset[df_subset['Pv'] >= 5]
        all_storico.append(df_subset)

df_all = pd.concat(all_storico)

def weighted_avg(group):
    v = group['Fm']
    w = group['Pv']
    if w.sum() == 0: return 0
    return (v * w).sum() / w.sum()

storico_agg = df_all.groupby('Nome').apply(weighted_avg).reset_index(name='Fm_Triennio')

# Get the most recent Mantra role for each player
# We can just take the first one we find since we sort or assume they don't change often
# Actually let's just group and take the first 'Rm'
ruoli_mantra = df_all.groupby('Nome')['Rm'].first().reset_index()

storico_finale = pd.merge(storico_agg, ruoli_mantra, on='Nome')

storico_finale.to_csv('C:/Users/gdeluca/.gemini/antigravity/scratch/fantacalcio/storico_triennio.csv', index=False)
