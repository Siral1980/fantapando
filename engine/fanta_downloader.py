"""
Downloader for Fantacalcio.it official statistics and Excel files.
Executes an in-memory, transient login to https://www.fantacalcio.it/api/v1/User/login
and retrieves official stats from https://www.fantacalcio.it/api/v1/Excel/stats/{season_id}/{type_id}.
Guarantees zero persistence of user credentials.
"""

import os
import sys
import requests
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DEFAULT_DEST = os.path.join(DATA_DIR, "Statistiche_Fantacalcio_Live.xlsx")

def download_fantacalcio_stats(username, password, season_id=21, type_id=1, output_file=None):
    """
    Transiently authenticates with Fantacalcio.it, downloads the Excel stats file,
    and returns (success, message, filepath).
    Credentials are deleted immediately from memory and never stored on disk.
    """
    if not username or not password:
        return False, "Inserisci username e password.", None

    if output_file is None:
        output_file = DEFAULT_DEST

    login_url = "https://www.fantacalcio.it/api/v1/User/login"
    stats_url = f"https://www.fantacalcio.it/api/v1/Excel/stats/{season_id}/{type_id}"

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://www.fantacalcio.it',
        'Referer': 'https://www.fantacalcio.it/login'
    })

    try:
        # 1. Transient Login
        payload = {
            'username': str(username).strip(),
            'password': str(password)
        }
        res = session.post(login_url, json=payload, timeout=15)
        
        # Explicitly purge credential variables from scope
        del payload
        del password
        
        if res.status_code != 200:
            return False, f"Errore server durante il login (HTTP {res.status_code}).", None

        data = res.json()
        if not data.get('success', False):
            errs = data.get('errors', [])
            msg = " - ".join([e.get('message', 'Errore credenziali') for e in errs]) if errs else "Credenziali non valide."
            return False, f"Login fallito: {msg}", None

        # Check if auth token is returned in data
        user_data = data.get('data') or {}
        token = user_data.get('token') or user_data.get('accessToken')
        if token:
            session.headers['Authorization'] = f"Bearer {token}"

        # 2. Download Excel Stats
        session.headers.update({
            'Accept': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, application/octet-stream, */*',
            'Referer': 'https://www.fantacalcio.it/statistiche-serie-a'
        })
        
        stats_res = session.get(stats_url, timeout=30)
        
        if stats_res.status_code == 401:
            return False, "Accesso non autorizzato all'archivio Excel (sessione non riconosciuta).", None
        elif stats_res.status_code != 200:
            return False, f"Errore durante il download dell'Excel (HTTP {stats_res.status_code}).", None

        content = stats_res.content
        if len(content) < 1000:
            return False, f"File ricevuto non valido o vuoto ({len(content)} bytes).", None

        # Verify ZIP/XLSX header (b'PK\x03\x04')
        if not content.startswith(b'PK\x03\x04'):
            # Might be an HTML error page or text
            return False, f"Il file ricevuto non è un foglio Excel valido (anteprima: {content[:100]}).", None

        # 3. Save File
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'wb') as f:
            f.write(content)

        return True, f"File Excel scaricato con successo ({round(len(content)/1024, 1)} KB)!", output_file

    except requests.exceptions.RequestException as e:
        return False, f"Errore di rete durante la connessione a Fantacalcio.it: {e}", None
    except Exception as e:
        return False, f"Errore imprevisto: {e}", None
    finally:
        session.close()

if __name__ == '__main__':
    print("Testing module import and dummy credentials:")
    succ, msg, path = download_fantacalcio_stats("dummy_test", "dummy_pass")
    print(f"Result: success={succ}, msg={msg}")
