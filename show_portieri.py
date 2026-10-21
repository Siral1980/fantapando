import pandas as pd
from fanta_rating_reale_storico import calcola_fanta_rating, MANTRA_OVERRIDES

def main():
    df_voti = pd.read_csv('voti_reali.csv')
    df_storico = pd.read_csv('storico_triennio.csv')
    
    classifica = calcola_fanta_rating(df_voti, df_storico)
    
    # Check explicitly for 'Por' or exactly 'P (*)'
    top_por = classifica[(classifica['Ruolo Mantra'] == 'Por') | (classifica['Ruolo Mantra'] == 'P (*)')]
    print("\n=== TOP 5 PORTIERI (Por) CON BONUS IMBATTIBILITA' (+1) ===")
    print(top_por.head(5).to_string(index=False))

if __name__ == '__main__':
    main()
