import pandas as pd
import numpy as np

# -------------------------------------------------------------------
# 1. CONFIGURAZIONE: Fasce delle squadre di Serie A
# (Puoi modificarle in base alla tua percezione di difficoltà)
# 1 = Big/Top Team, 2 = Mid Table, 3 = Lotta Salvezza
# -------------------------------------------------------------------
FASCE_SQUADRE = {
    'Inter': 1, 'Juventus': 1, 'Milan': 1, 'Napoli': 1, 'Atalanta': 1, 'Roma': 1,
    'Lazio': 2, 'Fiorentina': 2, 'Bologna': 2, 'Torino': 2, 'Genoa': 2, 'Monza': 2,
    'Lecce': 3, 'Empoli': 3, 'Verona': 3, 'Cagliari': 3, 'Venezia': 3, 'Parma': 3, 'Como': 3, 'Udinese': 3
}

# -------------------------------------------------------------------
# 2. MOTORE DI CALCOLO
# -------------------------------------------------------------------
def calcola_fanta_rating(df_voti, prossimi_match, pesi=(0.4, 0.3, 0.3)):
    """
    Calcola il FantaRating in base a Storico, Stato di Forma (ultime 5) e Matchup.
    pesi = (Peso_Storico, Peso_Forma, Peso_Fascia_Avversario)
    """
    peso_storico, peso_forma, peso_matchup = pesi
    
    # Aggiungiamo la colonna della fascia avversario al dataset storico
    df_voti['Fascia_Avversario'] = df_voti['Avversario'].map(FASCE_SQUADRE)
    
    risultati = []
    
    for giocatore, prossimo_avversario in prossimi_match.items():
        # Filtriamo i voti solo per il giocatore in questione
        storico_giocatore = df_voti[df_voti['Giocatore'] == giocatore].copy()
        
        if storico_giocatore.empty:
            print(f"Attenzione: Nessun dato storico per {giocatore}")
            continue
            
        # 1. VALORE STORICO (FantaMedia Stagionale)
        fm_stagionale = storico_giocatore['FantaVoto'].mean()
        
        # 2. STATO DI FORMA (FantaMedia ultime 5 giornate giocate)
        # Ordiniamo per giornata e prendiamo le ultime 5
        ultime_5 = storico_giocatore.sort_values('Giornata').tail(5)
        fm_ultime5 = ultime_5['FantaVoto'].mean()
        
        # 3. INDICE INCISIVITÀ (FantaMedia contro squadre della stessa fascia del prossimo avversario)
        fascia_prossimo_avv = FASCE_SQUADRE.get(prossimo_avversario, 2) # Default fascia 2 se non trovata
        voti_vs_fascia = storico_giocatore[storico_giocatore['Fascia_Avversario'] == fascia_prossimo_avv]
        
        if not voti_vs_fascia.empty:
            fm_matchup = voti_vs_fascia['FantaVoto'].mean()
        else:
            # Se non ha mai giocato contro questa fascia quest'anno, usiamo la media stagionale come paracadute
            fm_matchup = fm_stagionale 
            
        # 4. CALCOLO FINALE (Formula)
        rating_finale = (fm_stagionale * peso_storico) + (fm_ultime5 * peso_forma) + (fm_matchup * peso_matchup)
        
        risultati.append({
            'Giocatore': giocatore,
            'Prossimo Match': prossimo_avversario,
            'FM Storica': round(fm_stagionale, 2),
            'FM Ultime 5': round(fm_ultime5, 2),
            f'FM vs Fascia {fascia_prossimo_avv}': round(fm_matchup, 2),
            'FANTARATING': round(rating_finale, 2)
        })
        
    return pd.DataFrame(risultati).sort_values(by='FANTARATING', ascending=False)

# -------------------------------------------------------------------
# 3. DATI DI ESEMPIO E TEST
# -------------------------------------------------------------------
def main():
    print("Inizializzazione Fanta-Algoritmo...\n")
    
    # Creiamo un dataset fittizio simulando le prime giornate di Serie A
    dati = [
        # Prestazioni altalenanti, ma esplode con le piccole
        {'Giocatore': 'Lautaro', 'Giornata': 1, 'Avversario': 'Genoa', 'FantaVoto': 6.5},
        {'Giocatore': 'Lautaro', 'Giornata': 2, 'Avversario': 'Lecce', 'FantaVoto': 10.0}, 
        {'Giocatore': 'Lautaro', 'Giornata': 3, 'Avversario': 'Atalanta', 'FantaVoto': 5.5},
        {'Giocatore': 'Lautaro', 'Giornata': 4, 'Avversario': 'Monza', 'FantaVoto': 6.0},
        {'Giocatore': 'Lautaro', 'Giornata': 5, 'Avversario': 'Milan', 'FantaVoto': 5.0},
        {'Giocatore': 'Lautaro', 'Giornata': 6, 'Avversario': 'Udinese', 'FantaVoto': 13.5},
        
        # Rendimento costante, fa bene anche nei Big Match
        {'Giocatore': 'Kvaratskhelia', 'Giornata': 1, 'Avversario': 'Verona', 'FantaVoto': 5.0},
        {'Giocatore': 'Kvaratskhelia', 'Giornata': 2, 'Avversario': 'Bologna', 'FantaVoto': 10.5},
        {'Giocatore': 'Kvaratskhelia', 'Giornata': 3, 'Avversario': 'Parma', 'FantaVoto': 6.5},
        {'Giocatore': 'Kvaratskhelia', 'Giornata': 4, 'Avversario': 'Cagliari', 'FantaVoto': 10.0},
        {'Giocatore': 'Kvaratskhelia', 'Giornata': 5, 'Avversario': 'Juventus', 'FantaVoto': 6.0},
        {'Giocatore': 'Kvaratskhelia', 'Giornata': 6, 'Avversario': 'Monza', 'FantaVoto': 7.0},
    ]
    
    df_voti = pd.DataFrame(dati)
    
    # Immagina che nel prossimo turno i match siano questi:
    prossimi_match = {
        'Lautaro': 'Venezia',       # Squadra di Fascia 3
        'Kvaratskhelia': 'Atalanta' # Squadra di Fascia 1
    }
    
    # Eseguiamo l'algoritmo
    # Pesi: 40% Stagione, 30% Ultime 5 (Forma), 30% Matchup (Avversario)
    classifica = calcola_fanta_rating(df_voti, prossimi_match, pesi=(0.4, 0.3, 0.3))
    
    print("=== RISULTATI FANTARATING PROSSIMA GIORNATA ===")
    print(classifica.to_string(index=False))
    print("\n")
    print("Analisi: Lautaro ha un rating altissimo perché gioca contro una squadra di Fascia 3, contro le quali storicamente domina (ha 11.75 di media contro Fascia 3), e viene da un ottimo stato di forma. Kvaratskhelia è penalizzato dall'avversario difficile (Fascia 1), abbassando leggermente il suo rating.")

if __name__ == "__main__":
    main()
