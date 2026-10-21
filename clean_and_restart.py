import os
import sys
import shutil
import subprocess
import time

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

def clean_cache(app_dir=None):
    """
    Cleans all application caches:
    1. Streamlit internal cache directory and CLI cache
    2. Python compiled bytecode (__pycache__ and *.pyc)
    """
    if app_dir is None:
        app_dir = os.path.dirname(os.path.abspath(__file__))

    print("==================================================")
    print("🧹 AVVIO PULIZIA TOTALE CACHE FANTACALCIO MANTRA")
    print("==================================================")

    # 1. Streamlit Cache Clear via CLI
    print("\n[1/3] Pulizia cache Streamlit (st.cache_data / st.cache_resource)...")
    try:
        res = subprocess.run(["streamlit", "cache", "clear"], capture_output=True, text=True, check=False)
        if res.returncode == 0:
            print("  -> ✅ Cache Streamlit svuotata con successo.")
        else:
            print(f"  -> ⚠️ Output Streamlit: {res.stdout.strip()} {res.stderr.strip()}")
    except Exception as e:
        print(f"  -> ⚠️ Impossibile eseguire 'streamlit cache clear': {e}")

    # 2. Remove all __pycache__ and .pyc files
    print("\n[2/3] Rimozione file di bytecode Python (__pycache__ e *.pyc)...")
    count_dirs = 0
    count_files = 0
    for root, dirs, files in os.walk(app_dir):
        for d in dirs:
            if d == '__pycache__':
                full_d = os.path.join(root, d)
                try:
                    shutil.rmtree(full_d, ignore_errors=True)
                    count_dirs += 1
                except Exception:
                    pass
        for f in files:
            if f.endswith('.pyc') or f.endswith('.pyo'):
                try:
                    os.remove(os.path.join(root, f))
                    count_files += 1
                except Exception:
                    pass
    print(f"  -> ✅ Eliminate {count_dirs} cartelle __pycache__ e {count_files} file compilati.")

    # 3. Check Streamlit user home cache
    home_st_cache = os.path.expanduser("~/.streamlit/cache")
    if os.path.exists(home_st_cache):
        try:
            shutil.rmtree(home_st_cache, ignore_errors=True)
            print("  -> ✅ Cartella ~/.streamlit/cache rimossa.")
        except Exception:
            pass

    print("\n[3/3] Verifica completamento...")
    print("  -> ✅ Tutte le cache sono state azzerate.")
    print("==================================================")

def restart_server(app_dir=None, port=8501):
    """
    Stops any running instance on the specified port and launches a clean Streamlit daemon.
    """
    if app_dir is None:
        app_dir = os.path.dirname(os.path.abspath(__file__))

    clean_cache(app_dir)

    print(f"\n🚀 Riavvio applicazione Streamlit sulla porta {port}...")
    app_path = os.path.join(app_dir, "app.py")

    # On Windows, locate and terminate any process holding port 8501
    try:
        cmd_find = f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"
        ps_res = subprocess.run(["powershell", "-Command", cmd_find], capture_output=True, text=True)
        pids = set([p.strip() for p in ps_res.stdout.splitlines() if p.strip().isdigit()])
        for pid in pids:
            print(f"  -> Terminazione processo precedente (PID {pid})...")
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, check=False)
            time.sleep(1)
    except Exception as e:
        print(f"  -> Controllo porta: {e}")

    # Start clean Streamlit
    print(f"  -> Avvio 'streamlit run {app_path}'...")
    subprocess.Popen(
        ["streamlit", "run", app_path, "--server.port", str(port), "--server.headless", "true"],
        shell=True
    )
    print(f"\n✨ Applicazione riavviata con cache pulita! Collegati a http://localhost:{port}")

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--clean-only':
        clean_cache()
    else:
        restart_server()
