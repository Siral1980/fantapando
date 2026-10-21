import pandas as pd
from fanta_rating_reale_storico import calcola_fanta_rating

def main():
    print("Caricamento dati...")
    df_voti = pd.read_csv('voti_reali.csv')
    df_storico = pd.read_csv('storico_triennio.csv')
    
    print("Calcolo FantaRating globale...")
    classifica = calcola_fanta_rating(df_voti, df_storico)
    
    # Rinominiamo e sistemiamo alcune colonne per renderlo più leggibile in Excel
    classifica.rename(columns={
        'FM Storica 3 Anni': 'FantaMedia Storica (3 anni)',
        'FM Stagione': 'FantaMedia Stagione (Prime 5)',
        'FM Forma (Ult. 3)': 'FantaMedia Forma (Ultime 3)',
        'Mv (Pura)': 'Media Voto Pura',
        'Bonus D-Factor': 'Premio D-Factor Mantra'
    }, inplace=True)
    
    output_path = 'C:/Users/gdeluca/Desktop/GoogleDrive/Projects/Fantacalcio/FantaRating_Globale_Mantra.xlsx'
    
    print(f"Salvataggio file in {output_path}...")
    classifica.to_excel(output_path, index=False)
    print("Fatto!")

if __name__ == '__main__':
    main()
