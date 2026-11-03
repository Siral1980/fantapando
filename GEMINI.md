# FantaMantra AI — Antigravity Project Instructions & Context (GEMINI.md)

Questo file definisce le direttive operative, l'architettura tecnica e le regole di business per qualsiasi agente AI (Google Antigravity, Gemini Code Assist) che opera su questo repository.

---

## 🟢 1. Panoramica del Progetto
- **Applicazione**: Cockpit decisionale e analitico per leghe Fantacalcio Classic e Mantra.
- **Stack**: Python 3.11+, Streamlit, Pandas, NumPy, Matplotlib/PIL, BeautifulSoup4, Requests.
- **Repository Git**: `https://github.com/Delu96/fantapando` (branch `dev` per sviluppo, `master` per produzione/stabile).
- **Remote Git predefinito**: `fantapando` (con fallback su `origin`).

---

## 🟢 2. Regole di Stile e Vincoli UI Mandatori
1. **Politica Emoji Pulita (Rigida)**:
   - Vietate emoji decorative o superflue (ad es. 🚀, ⚽, 🔥, 🏆, 📋).
   - **Consentiti ESCLUSIVAMENTE i pallini di stato colorati**:
     - `🟢` (Positivo, Titolare certo, Ottimo affare, Operazione riuscita)
     - `🟡` (Attenzione, Ballottaggio, Margine positivo / Prudenza)
     - `🔴` (Critico, Indisponibile/Infortunato, Pessimo affare, Errore)
     - `🟠` (Avviso, Sconsigliato, Rischio moderato)
     - `⚪` (Parità, Scambio speculare, Neutro)
2. **Nessun Testo Tagliato (No Text Clipping)**:
   - Nei bottoni, riquadri, card e tabelle il testo non deve mai essere troncato o sovrapposto. Usare sempre `flex-wrap: wrap`, layout elastici e `white-space: normal`.
3. **Formato Calendario Partite nella Lavagna Tattica**:
   - Sotto ogni calciatore nel campo, la partita relativa deve essere mostrata rigorosamente nel formato con abbreviazioni a 3 lettere maiuscole separate da trattino (es. `NAP - JUV`, `MIL - INT`, `ROM - LAZ`).
4. **Lingua**:
   - Tutte le risposte, la UI e i commenti al codice devono essere in **Italiano**.

---

## 🟢 3. Logica di Business e Motori di Calcolo

### Algoritmo Scambi a 4 Pilastri (`engine/trade_evaluator.py`)
- **P1 (xFV Differential)**: Guadagno/perdita totale stimato da giornata corrente alla 38ª.
- **P2 (Momentum & Trend)**: Delta di forma ponderato sulle ultime 3/5 giornate vs media storica.
- **P3 (Solidità & Affidabilità)**: Garanzia titolarità, minutaggio medio, tasso di presenze e sufficienze.
- **P4 (Qualità Star & Rank Decay)**: Penalizzazione della dispersione del valore; i top player pesano di più dei comprimari (ponderazione decrescente).
- **Verdetto Graduale a 9 Livelli & Indice di Convenienza (0-100)**:
  - `🟢 GRANDE AFFARE` (Score ≥ 28)
  - `🟢 MOLTO FAVOREVOLE` (Score ≥ 16)
  - `🟢 FAVOREVOLE` (Score ≥ 7)
  - `🟡 MARGINE POSITIVO` (Score ≥ 2)
  - `⚪ SOSTANZIALE EQUILIBRIO / ALLA PARI` (-2 ≤ Score < 2)
  - `🟡 PRUDENZA` (-7 ≤ Score < -2)
  - `🟠 SCONSIGLIATO` (-16 ≤ Score < -7)
  - `🔴 PERDITA DI VALORE` (-28 ≤ Score < -16)
  - `🔴 DA EVITARE` (Score < -28)

### Gestione Prestiti (`engine/loan_manager.py`)
- **Limite Massimo**: Massimo **8 prestiti attivi** per squadra.
- **Bidirezionalità**: Registrazione accurata di prestatore e ricevente.
- **Ghost Loan Suppression**: Esclusione automatica di prestiti duplicati o fittizi.
- **Recall Immediato**: Pulsante dedicato per richiamare il giocatore alla base in qualsiasi momento.

### Sincronizzazione Dati (`engine/sync_manager.py`)
- **Auto-check all'avvio ogni 12 ore**: Se sono trascorse più di 12 ore dall'ultimo check, aggiorna automaticamente rose e voti da Fantacalcio.it e metriche avanzate da Understat (xG, xA).
- Con il tasto "SYNC" manuale vengono aggiornate forzatamente anche le rose delle leghe.

---

## 🟢 4. Comandi Utili e Runbook
```bash
# Avvio rapido applicazione Streamlit
run_app.bat       # Windows (controlla aggiornamenti git e avvia)
./run_app.sh      # Mac/Linux

# Setup primo avvio su nuovo PC
setup_pc.bat      # Crea venv e installa dipendenze
./setup_pc.sh     # Mac/Linux

# Esportazione cronologia chat per Git
python export_chat_history.py

# Backup sessione Antigravity nativa
backup_chat_session.bat

# Ripristino sessione Antigravity nativa sul secondo PC
restore_chat_session.bat
```
