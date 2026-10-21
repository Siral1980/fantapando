import pandas as pd

# -------------------------------------------------------------------
# 1. CONFIGURAZIONE: Fasce delle squadre di Serie A
# -------------------------------------------------------------------
FASCE_SQUADRE = {
    'Inter': 1, 'Juventus': 1, 'Milan': 1, 'Napoli': 1, 'Atalanta': 1, 'Roma': 1,
    'Lazio': 2, 'Fiorentina': 2, 'Bologna': 2, 'Torino': 2, 'Genoa': 2, 'Monza': 2,
    'Lecce': 3, 'Empoli': 3, 'Verona': 3, 'Cagliari': 3, 'Venezia': 3, 'Parma': 3, 'Como': 3, 'Udinese': 3
}

def calcola_fanta_rating(df_voti, prossimi_match=None, pesi=(0.4, 0.4, 0.2)):
    """
    Calcola il FantaRating generale basato su Voti Reali
    pesi = (Peso_Stagionale, Peso_Ultime3, Peso_Matchup)
    Nota: ho spostato la 'Forma' sulle ultime 3 essendo solo alla 5a giornata.
    """
    peso_storico, peso_forma, peso_matchup = pesi
    risultati = []
    
    # Raggruppiamo i giocatori per calcolare le loro statistiche
    for giocatore in df_voti['Giocatore'].unique():
        storico_giocatore = df_voti[df_voti['Giocatore'] == giocatore].copy()
        
        # Filtriamo chi ha giocato troppo poco (es. meno di 3 partite)
        if len(storico_giocatore) < 2:
            continue
            
        squadra_giocatore = storico_giocatore['Squadra'].iloc[0]
        ruolo = storico_giocatore['Ruolo'].iloc[0]
            
        # 1. VALORE STORICO (FantaMedia Stagionale)
        fm_stagionale = storico_giocatore['FantaVoto'].mean()
        
        # 2. STATO DI FORMA (FantaMedia ultime 3 giornate per reattività)
        ultime_3 = storico_giocatore.sort_values('Giornata').tail(3)
        fm_ultime3 = ultime_3['FantaVoto'].mean()
        
        # 3. INDICE MATCHUP 
        # Siccome nei file Excel grezzi non c'è l'avversario affrontato, per ora 
        # valutiamo il giocatore in base al suo stato di forma "puro".
        # (Se avessimo il calendario, incroceremmo con le fasce).
        # Calcoliamo un Rating "Generale" per ora.
        
        rating_finale = (fm_stagionale * 0.5) + (fm_ultime3 * 0.5) 
        
        risultati.append({
            'Squadra': squadra_giocatore,
            'Ruolo': ruolo,
            'Giocatore': giocatore,
            'Presenze': len(storico_giocatore),
            'FM Storica': round(fm_stagionale, 2),
            'FM Ultime 3': round(fm_ultime3, 2),
            'FANTARATING': round(rating_finale, 2)
        })
        
    df_risultati = pd.DataFrame(risultati).sort_values(by='FANTARATING', ascending=False)
    return df_risultati

def main():
    try:
        df_voti = pd.read_csv('voti_reali.csv')
        print(f"Dati caricati! Trovati {len(df_voti)} voti validi giocati in {df_voti['Giornata'].nunique()} giornate.")
    except Exception as e:
        print("Errore nel caricamento dei dati:", e)
        return

    # Calcola il rating
    classifica = calcola_fanta_rating(df_voti)
    
    print("\n=== TOP 10 GIOCATORI PIU' IN FORMA (FANTARATING) ===")
    print(classifica.head(10).to_string(index=False))

    print("\n=== TOP 5 ATTACCANTI ===")
    print(classifica[classifica['Ruolo'] == 'A'].head(5).to_string(index=False))

if __name__ == "__main__":
    main()
