# FantaPandoAssistant — Master Project Knowledge Base & Context Dossier

> **Dossier di Continuità Progetto e Conoscenza Chat**  
> Questo documento racchiude l'intera memoria storica, architetturale e decisionale della conversazione Antigravity (`b7e95405-14b5-4c71-900a-ba94688b2f9a`).  
> Permette a qualunque agente AI (su Antigravity, Cursor, VS Code o Claude) o sviluppatore di riprendere immediatamente il lavoro su un secondo PC con il 100% di accuratezza e zero perdita di contesto.

---

## 1. Panoramica del Progetto

- **Nome**: FantaPandoAssistant Cockpit
- **Framework**: Streamlit, Pandas, NumPy, PIL / Matplotlib, BeautifulSoup4 / Requests
- **Repository Git**: `https://github.com/Delu96/fantapando`
- **Branch Attivi**:
  - `dev`: Branch primario di sviluppo continuo.
  - `master`: Branch sincronizzato stabile.
  - **Remote Git**: `fantapando` (con fallback automatico su `origin`).

---

## 2. Architettura del Software e Moduli Core

### `app.py`
Entrypoint principale dell'applicazione Streamlit.
- **Tab 1: Dashboard & Monitor**: Panoramica delle rose, indici di titolarità, rating e indicatori di forma.
- **Tab 2: Rose & Mercato**: Gestione rosa attiva, svincolati, filtri di ruolo Mantra/Classic, crediti e quotazioni.
- **Tab 3: Lavagna Tattica Interattiva**:
  - Visualizzazione grafica del campo da gioco con moduli tattici Mantra (3-4-3, 4-3-3, 3-4-1-2, ecc.).
  - **Hover Tattico**: Preview del calciatore con statistiche, stato titolarità e matchday fixture.
  - **Formato Partite**: Rigorosamente a 3 lettere maiuscole separate da trattino (es. `NAP - JUV`, `INT - ATA`).
- **Tab 4: Simulatore Scambi Evoluto**:
  - Valutazione multi-giocatore (1v1, 2v2, pacchetti asimmetrici 4v5).
  - Algoritmo a **4 Pilastri** e **Verdetto Graduale a 9 Livelli**.
  - **Indice di Convenienza (0 - 100)** con barra visuale ad alta densità.
  - **Archetipi Tattici** e **Consigli Strategici** per negoziare la trattativa.
  - **Note Cliniche**: Monitoraggio infortuni, squalifiche e tempi di recupero.
- **Tab 5: Gestione Prestiti, Sync & Impostazioni**:
  - Pannello prestiti con storico bidirezionale e richiamo immediato.
  - Gestione auto-sync ogni 12 ore e aggiornamento forzato.
  - Sincronizzazione Cross-PC con GitHub (Pull/Push con un click).

### `engine/trade_evaluator.py`
Motore di valutazione quantitativa degli scambi:
1. **Pilastro 1 (xFV Differential)**: Punti effettivi attesi / gara e valore differenziale complessivo fino alla 38ª giornata.
2. **Pilastro 2 (Momentum & Trend)**: Forma recente calcolata sulle ultime 3/5 giornate vs media stagionale.
3. **Pilastro 3 (Solidità & Titolarità)**: Garanzia di voto, minutaggio medio e sufficienze (≥6).
4. **Pilastro 4 (Qualità Star & Rank Decay)**: Ponderazione decrescente che premia i top player di ruolo rispetto ai comprimari.
- **Scala Verdetto Graduale a 9 Livelli**:
  - `🟢 GRANDE AFFARE` (Score ≥ +28)
  - `🟢 MOLTO FAVOREVOLE` (Score ≥ +16)
  - `🟢 FAVOREVOLE` (Score ≥ +7)
  - `🟡 MARGINE POSITIVO` (Score ≥ +2)
  - `⚪ ALLA PARI` (Score tra -2 e +2)
  - `🟡 PRUDENZA` (Score ≤ -2)
  - `🟠 SCONSIGLIATO` (Score ≤ -7)
  - `🔴 PERDITA DI VALORE` (Score ≤ -16)
  - `🔴 DA EVITARE` (Score ≤ -28)

### `engine/tactical_board.py`
Generatore grafico della lavagna tattica:
- Calcolo coordinate dei ruoli Mantra sul campo.
- Generazione badge calciatore con status titolarità, voti attesi e prossima partita (formato 3 lettere).
- Supporto a rendering headless e responsive.

### `engine/loan_manager.py`
Registro persistente dei prestiti tra leghe:
- **Limite Massimo**: Rigidamente impostato a **8 prestiti attivi** per squadra.
- **Tracciamento Bidirezionale**: Salva squadra cedente, squadra ricevente, giornata di inizio e durata.
- **Ghost Loan Suppression**: Rimozione e filtraggio automatico dei prestiti fantasma o duplicati.
- **Funzione di Richiamo (Recall)**: Ripristina istantaneamente il giocatore nella rosa proprietaria.

### `engine/sync_manager.py` & `engine/data_loader.py`
Gestione dell'aggiornamento dati e persistenza:
- **Auto-Check ogni 12 Ore**: All'avvio dell'app verifica l'orario dell'ultimo sync; se > 12 ore, avvia la sincronizzazione automatica.
- **Scraping Fantacalcio & Understat**: Aggiornamento rose, voti reali (fino alla 10ª giornata e oltre) e metriche avanzate (xG, xA).
- **Risoluzione Percorsi Relativi**: Supporto completo Cross-PC senza percorsi assoluti hardcoded (`C:\Users\...`).

### `engine/auth_manager.py`
Gestione autenticazione Git e sincronizzazione remota:
- Rilevamento dinamico del remote (`fantapando` o `origin`).
- Supporto a Personal Access Token (PAT) GitHub.
- Push e Pull integrati nella UI di Streamlit.

---

## 3. Direttive di Stile e Vincoli Fissi di Progetto

1. **Politica Emoji Pulita**:
   - Vietate emoji decorative o superflue (tipo ⚽, 🚀, 🔥, 🏆, 📋).
   - **Consentiti unicamente i pallini di stato colorati**: `🟢` (positivo/eccellente), `🟡` (attenzione/neutro), `🔴` (critico/negativo), `🟠` (avviso/sconsigliato), `⚪` (parità/default).
2. **Nessun Testo Tagliato (No Text Clipping)**:
   - Tutti i pulsanti, badge, tabelle e card HTML devono avere layout elastico, `white-space: normal` o `flex-wrap: wrap` per impedire il troncamento dei testi.
3. **Formato Calendario Partite**:
   - Sotto i giocatori nella lavagna tattica, i nomi squadra devono essere abbreviazioni a 3 lettere maiuscole separate da trattino (es. `NAP - JUV`, `MIL - ROM`).
4. **Encoding e Compatibilità Windows**:
   - Tutti i file sorgente e script devono essere salvati in UTF-8 senza BOM.
   - Script di shell e batch devono gestire correttamente i percorsi con spazi (`"%~dp0..."`).

---

## 4. Come Usare Questo Progetto su un Altro PC

### Opzione A: Avvio su Nuovo PC (Consigliato via Git)
1. Clona il repository sul nuovo PC:
   ```bash
   git clone https://github.com/Delu96/fantapando.git
   cd fantapando
   git checkout dev
   ```
2. Esegui lo script di configurazione automatica:
   - Su Windows: doppio clic su `setup_pc.bat` (crea venv e installa librerie).
   - Su Linux/Mac: `./setup_pc.sh`
3. Avvia l'applicazione:
   - Doppio clic su `run_app.bat` (o `./run_app.sh`).
4. Se utilizzi un assistente AI (Antigravity, Cursor, ecc.) sul nuovo PC:
   - Apri una nuova chat e digita:
     > *"Sto lavorando a FantaPandoAssistant. Leggi `@docs/PROJECT_KNOWLEDGE_BASE.md` e dimmi lo stato del progetto."*
   - L'AI acquisirà immediatamente l'intero contesto operativo!

### Opzione B: Esportare la Trascrizione della Chat nel Repo
In questo repository è presente lo script:
```bash
python export_chat_history.py
```
Questo script genera `docs/CHAT_HISTORY_TRANSCRIPT.md` contenente tutti i messaggi scambiati in questa conversazione.  
Facendo `git push` qui e `git pull` sull'altro PC, l'intera cronologia testuale della chat sarà accessibile e consultabile in locale.

### Opzione C: Clonare la Sessione Antigravity Direttamente nell'IDE (PC 1 ➔ PC 2)
Se vuoi vedere **esattamente questa chat nativa** nella barra laterale dell'applicazione Antigravity 2.0 sul secondo computer:
1. Su questo PC (PC 1):
   - Fai doppio clic su `backup_chat_session.bat` (oppure esegui `python export_chat_session.py`).
   - Verrà creato il file compresso `antigravity_chat_session.zip`.
2. Trasferisci `antigravity_chat_session.zip` sul secondo PC (tramite chiavetta USB, Google Drive o cartella condivisa di rete) e posizionalo nella cartella del progetto.
3. Sul secondo PC (PC 2):
   - Fai doppio clic su `restore_chat_session.bat` (oppure esegui `python restore_chat_session.py`).
   - Lo script estrarrà la sessione direttamente in `%USERPROFILE%\.gemini\antigravity\brain\b7e95405-14b5-4c71-900a-ba94688b2f9a`.
4. Riavvia Antigravity sul secondo PC: la chat apparirà nella cronologia con tutti i suoi messaggi e artefatti!

---

## 5. Indice Documenti Chiave
- `docs/PROJECT_KNOWLEDGE_BASE.md`: Questo dossier master di architettura e contesto.
- `docs/CHAT_HISTORY_TRANSCRIPT.md`: Trascrizione cronologica completa di tutti i turni di conversazione.
- `docs/proposta_algoritmi_scambio.md`: Specifica matematica e logica dei 4 Pilastri di valutazione scambi.
- `docs/revamp_ui_plan.md`: Piano di riprogettazione visiva e ad alta densità delle card Streamlit.
- `app.py`: Codice applicativo completo.
