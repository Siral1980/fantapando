import pandas as pd

# -------------------------------------------------------------------
# OVERRIDE RUOLI MANTRA (Per i nuovi arrivi o assenti nello storico)
# -------------------------------------------------------------------
MANTRA_OVERRIDES = {
    'Moreira': 'E;W',
    'Kvernadze': 'W;A', 
    'Adzic': 'T',
    'Varela G.': 'A',
    'Mastantuono': 'T',
    'Raimondo': 'Pc'
}

def calcola_fanta_rating(df_voti, df_storico):
    risultati = []
    
    storico_fm_dict = df_storico.set_index('Nome')['Fm_Triennio'].to_dict()
    storico_mv_dict = df_storico.set_index('Nome')['Mv_Triennio'].to_dict()
    mantra_dict = df_storico.set_index('Nome')['Rm'].to_dict()
    
    for giocatore in df_voti['Giocatore'].unique():
        voti_giocatore = df_voti[df_voti['Giocatore'] == giocatore].copy()
        
        if len(voti_giocatore) < 2:
            continue
            
        squadra = voti_giocatore['Squadra'].iloc[0]
        ruolo_classic = voti_giocatore['Ruolo'].iloc[0]
        
        fm_stagionale = voti_giocatore['FantaVoto'].mean()
        mv_stagionale = voti_giocatore['Voto'].mean()
        
        ultime_3 = voti_giocatore.sort_values('Giornata').tail(3)
        fm_ultime3 = ultime_3['FantaVoto'].mean()
        
        fm_storico = storico_fm_dict.get(giocatore, None)
        mv_storico = storico_mv_dict.get(giocatore, None)
        ruolo_mantra = mantra_dict.get(giocatore, None)
        
        if giocatore in MANTRA_OVERRIDES:
            ruolo_mantra = MANTRA_OVERRIDES[giocatore]
        elif not ruolo_mantra or pd.isna(ruolo_mantra):
            ruolo_mantra = str(ruolo_classic) + " (*)"
            
        # Pesi della formula standard (FantaMedia)
        if fm_storico is not None and fm_storico > 0:
            rating_base = (fm_ultime3 * 0.45) + (fm_stagionale * 0.40) + (fm_storico * 0.15)
            mv_blended = (mv_stagionale * 0.70) + (mv_storico * 0.30)
        else:
            rating_base = (fm_ultime3 * 0.50) + (fm_stagionale * 0.50)
            mv_blended = mv_stagionale
            
        # -------------------------------------------------------------------
        # CALCOLO "D-FACTOR" (Modificatore Difesa Mantra)
        # -------------------------------------------------------------------
        d_bonus = 0.0
        # Ruoli validi per il D-Factor (Dc, Dd, Ds, M, E)
        ruoli_dfactor = ['Dc', 'Dd', 'Ds', 'M', 'E']
        
        # Verifica se il giocatore ha almeno un ruolo valido per la difesa
        is_dfactor_eligible = any(r in str(ruolo_mantra) for r in ruoli_dfactor)
        
        if is_dfactor_eligible:
            # Il D-Factor premia i giocatori con Media Voto (Mv) alta (es. Mv > 6.0)
            # Un difensore da 6.5 fisso garantisce punti modificatore a tutta la squadra!
            # Applichiamo un "Premio D-Factor" al rating base
            
            if mv_blended > 6.0:
                d_bonus = (mv_blended - 6.0) * 1.5  # Moltiplicatore 1.5 per dargli peso visibile
                
        rating_finale = rating_base + d_bonus
            
        risultati.append({
            'Squadra': squadra,
            'Ruolo Mantra': ruolo_mantra,
            'Giocatore': giocatore,
            'Mv (Pura)': round(mv_blended, 2),
            'Bonus D-Factor': round(d_bonus, 2) if d_bonus > 0 else '-',
            'FANTARATING': round(rating_finale, 2)
        })
        
    df_risultati = pd.DataFrame(risultati).sort_values(by='FANTARATING', ascending=False)
    return df_risultati

def main():
    df_voti = pd.read_csv('voti_reali.csv')
    df_storico = pd.read_csv('storico_triennio.csv')
    
    classifica = calcola_fanta_rating(df_voti, df_storico)
    
    print("\n=== TOP 5 DIFENSORI CENTRALI (Dc) PREMIATI DAL D-FACTOR ===")
    top_dc = classifica[classifica['Ruolo Mantra'].str.contains('Dc', na=False)]
    print(top_dc.head(5).to_string(index=False))

    print("\n=== TOP 5 ESTERNI (E) E MEDIANI (M) PER IL MODIFICATORE ===")
    top_em = classifica[classifica['Ruolo Mantra'].str.contains('E|M', na=False)]
    print(top_em.head(5).to_string(index=False))

if __name__ == '__main__':
    main()
