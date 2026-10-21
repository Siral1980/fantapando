import pandas as pd
import glob

path = 'C:/Users/gdeluca/Desktop/GoogleDrive/Projects/Fantacalcio/Dati Storici/'
files = glob.glob(path + '*.xlsx')

all_storico = []

for file in files:
    df = pd.read_excel(file, header=1)
    if all(k in df.columns for k in ['Nome', 'Fm', 'Mv', 'Pv', 'Rm']):
        df_subset = df[['Nome', 'Fm', 'Mv', 'Pv', 'Rm']].copy()
        df_subset['Fm'] = pd.to_numeric(df_subset['Fm'], errors='coerce')
        df_subset['Mv'] = pd.to_numeric(df_subset['Mv'], errors='coerce')
        df_subset['Pv'] = pd.to_numeric(df_subset['Pv'], errors='coerce')
        df_subset = df_subset.dropna(subset=['Fm', 'Mv', 'Pv'])
        df_subset = df_subset[df_subset['Pv'] >= 5]
        all_storico.append(df_subset)

df_all = pd.concat(all_storico)

def weighted_avg_fm(group):
    v = group['Fm']
    w = group['Pv']
    if w.sum() == 0: return 0
    return (v * w).sum() / w.sum()

def weighted_avg_mv(group):
    v = group['Mv']
    w = group['Pv']
    if w.sum() == 0: return 0
    return (v * w).sum() / w.sum()

storico_fm = df_all.groupby('Nome').apply(weighted_avg_fm).reset_index(name='Fm_Triennio')
storico_mv = df_all.groupby('Nome').apply(weighted_avg_mv).reset_index(name='Mv_Triennio')
ruoli_mantra = df_all.groupby('Nome')['Rm'].first().reset_index()

storico_finale = pd.merge(storico_fm, storico_mv, on='Nome')
storico_finale = pd.merge(storico_finale, ruoli_mantra, on='Nome')

storico_finale.to_csv('C:/Users/gdeluca/.gemini/antigravity/scratch/fantacalcio/storico_triennio.csv', index=False)
