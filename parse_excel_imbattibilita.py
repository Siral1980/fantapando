import pandas as pd
import glob

path = 'C:/Users/gdeluca/Desktop/GoogleDrive/Projects/Fantacalcio/'
files = glob.glob(path + 'Voti_Fantacalcio_Stagione_*.xlsx')

all_data = []

for file in files:
    giornata = int(file.split('_')[-1].split('.')[0])
    df = pd.read_excel(file, header=None)
    
    current_team = None
    
    for index, row in df.iterrows():
        col0 = str(row[0]).strip() if pd.notna(row[0]) else ''
        
        if 'Voti' in col0 or 'www.' in col0 or 'QUESTO' in col0 or 'ESCLUSIVO' in col0 or col0 == 'Cod.' or col0 == '':
            continue
            
        if pd.isna(row[1]) and col0 != '':
            current_team = col0
            continue
            
        if current_team and pd.notna(row[1]) and str(row[1]) in ['P', 'D', 'C', 'A']:
            nome = str(row[2])
            ruolo = str(row[1])
            voto = row[3]
            gf = pd.to_numeric(row[4], errors='coerce')
            gs = pd.to_numeric(row[5], errors='coerce')
            rp = pd.to_numeric(row[6], errors='coerce')
            rs = pd.to_numeric(row[7], errors='coerce')
            au = pd.to_numeric(row[9], errors='coerce')
            amm = pd.to_numeric(row[10], errors='coerce')
            esp = pd.to_numeric(row[11], errors='coerce')
            ass = pd.to_numeric(row[12], errors='coerce')
            
            if pd.isna(voto) or str(voto).strip() in ['sv', 's.v.', '-']:
                continue
                
            try:
                voto_num = float(str(voto).replace(',', '.'))
            except:
                continue
                
            gf = 0 if pd.isna(gf) else gf
            gs = 0 if pd.isna(gs) else gs
            rp = 0 if pd.isna(rp) else rp
            rs = 0 if pd.isna(rs) else rs
            au = 0 if pd.isna(au) else au
            amm = 0 if pd.isna(amm) else amm
            esp = 0 if pd.isna(esp) else esp
            ass = 0 if pd.isna(ass) else ass
            
            # BONUS IMBATTIBILITA' PORTIERE (+1)
            imbattibilita = 1 if (ruolo == 'P' and gs == 0) else 0
            
            fantavoto = voto_num + (gf*3) - (gs*1) + (rp*3) - (rs*3) - (au*2) - (amm*0.5) - (esp*1) + (ass*1) + imbattibilita
            
            all_data.append({
                'Giornata': giornata,
                'Squadra': current_team,
                'Giocatore': nome,
                'Ruolo': ruolo,
                'Voto': voto_num,
                'FantaVoto': fantavoto,
                'GolSubiti': gs
            })

df_clean = pd.DataFrame(all_data)
df_clean.to_csv('C:/Users/gdeluca/.gemini/antigravity/scratch/fantacalcio/voti_reali.csv', index=False)
