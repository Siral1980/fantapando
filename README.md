# 🟢 FantaPandoAssistant

Applicazione analitica e gestionale avanzata per leghe Fantacalcio Classic e Mantra, con ottimizzatore di formazione, valutazione scambi, D-Factor, integrazione statistiche Fantacalcio.it e Understat (xG, xA, PSxG).

---

## 🟢 Utilizzo Cross-PC e Multi-Dispositivo

L'applicazione è progettata per essere utilizzata su molteplici computer o dispositivi in **3 diverse modalità**:

### Modalità 1: Accesso Web Cloud (Senza installare nulla)
L'applicazione è collegata al repository GitHub (`https://github.com/Delu96/fantapando.git`) ed è distribuita su **Streamlit Community Cloud**.
- È accessibile da qualsiasi PC, Mac, tablet o smartphone semplicemente aprendo l'URL web nel browser.
- Non richiede Python o installazioni locali sul computer secondario.

### Modalità 2: Accesso tramite Rete Locale (Wi-Fi)
Se l'applicazione è in esecuzione sul tuo computer principale (es. PC fisso):
- Qualsiasi altro dispositivo connesso alla stessa rete Wi-Fi (portatile, tablet, smartphone) può collegarsi immediatamente aprendo nel browser l'indirizzo IP locale mostrato nella sidebar e nel tab impostazioni:
  `http://[IP-DEL-PC-PRINCIPALE]:8501` (es. `http://192.168.1.15:8501`).

### Modalità 3: Installazione Nativa su un Secondo PC (con Sincronizzazione Cloud)
Se desideri installare ed eseguire il progetto localmente su un altro computer:

1. **Clona il repository sul nuovo PC**:
   ```bash
   git clone https://github.com/Delu96/fantapando.git
   cd fantapando
   git checkout dev
   ```
2. **Configurazione Automatica (1-click)**:
   - **Windows**: Fai doppio click sul file `setup_pc.bat`
   - **Mac / Linux**: Esegui da terminale `./setup_pc.sh`
   Il file creerà l'ambiente virtuale (`venv`) e installerà automaticamente tutte le dipendenze da `requirements.txt`.
3. **Avvio dell'applicazione**:
   - **Windows**: Fai doppio click su `run_app.bat`
   - **Mac / Linux**: Esegui `./run_app.sh`
   `run_app.bat` e `run_app.sh` eseguono automaticamente un controllo da GitHub per scaricare eventuali modifiche salvate dall'altro PC prima di avviare il server Streamlit!

---

## 🟢 Trasferimento e Continuità della Chat AI tra PC

Se stai utilizzando un assistente AI (come Google Antigravity, Cursor o VS Code) e desideri che **tutte le informazioni, decisioni e la cronologia di questa chat siano disponibili sul secondo PC**:

1. **Conoscenza Completa Inclusa nel Repository Git**:
   - Consulta `docs/PROJECT_KNOWLEDGE_BASE.md`: contiene l'intero compendio architetturale, le formule, le regole di lega, i vincoli e le decisioni prese durante lo sviluppo.
   - Consulta `docs/CHAT_HISTORY_TRANSCRIPT.md`: contiene la trascrizione cronologica di tutti i turni di conversazione.
   - Aprendo una nuova chat AI sul secondo PC, ti basterà menzionare `@docs/PROJECT_KNOWLEDGE_BASE.md` per dare all'AI il 100% del contesto!
2. **Clonazione della Chat Nativa su Antigravity (PC 1 ➔ PC 2)**:
   - Su questo PC: esegui `backup_chat_session.bat` (crea `antigravity_chat_session.zip`).
   - Copia lo zip sul secondo PC ed esegui `restore_chat_session.bat`.
   - Riavviando Antigravity sul secondo computer, la sessione comparirà nella cronologia dell'applicazione con tutti i messaggi e gli artefatti.

---

## 🟢 Sincronizzazione Dati tra PC Diversi

Nel **Tab 5 (Impostazioni & Sync)** trovi i controlli dedicati per la sincronizzazione:
- **🟢 Scarica Ultimi Dati da GitHub (Pull)**: Scarica istantaneamente sul PC corrente le ultime rose, leghe, prestiti e utenti salvati dall'altro PC.
- **🟠 Invia Dati su GitHub Cloud (Push)**: Carica tutte le modifiche correnti su GitHub per renderle disponibili su tutti gli altri computer.

---

## 🟢 Avvio Manuale da Riga di Comando

Se preferisci avviare manualmente da terminale:

```bash
# Attiva ambiente virtuale (se creato)
# Windows: venv\Scripts\activate
# Linux/Mac: source venv/bin/activate

# Installa requisiti
pip install -r requirements.txt

# Avvia l'app
streamlit run app.py
```
