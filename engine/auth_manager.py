"""
Multi-User Authentication, Role Permissions, and League Isolation Manager.
- Auto-authenticates as 'admin' on localhost (unless explicitly testing another user or logged out).
- Enforces login screen on Streamlit Cloud / remote access, persisting login across F5 refreshes via a signed HMAC token in URL query params.
- Dual-location persistence: saves users in both data/users_db.json AND ~/.fantamantra_storage/users_db.json (outside git working tree) and automatically merges them on load.
- Auto-syncs users_db.json and leagues to GitHub (master & dev) whenever users are created, updated, or deleted.
"""

import os
import sys
import json
import hmac
import base64
import hashlib
import secrets
import datetime
import threading
import subprocess
import urllib.request
import urllib.error
import streamlit as st

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
USERS_DB_FILE = os.path.join(DATA_DIR, "users_db.json")

PERSISTENT_STORAGE_DIR = os.path.join(os.path.expanduser("~"), ".fantamantra_storage")
PERSISTENT_USERS_DB_FILE = os.path.join(PERSISTENT_STORAGE_DIR, "users_db.json")
GITHUB_REPO = "Siral1980/fantapando"


def _hash_password(password: str, salt: str = None):
    """Computes PBKDF2-HMAC-SHA256 hash with a random or provided hex salt."""
    if not salt:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        'sha256',
        str(password).encode('utf-8'),
        str(salt).encode('utf-8'),
        120000
    )
    return salt, dk.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Constant-time password verification."""
    _, computed = _hash_password(password, salt)
    return secrets.compare_digest(computed, expected_hash)


def _make_auth_token(username: str, user_obj: dict) -> str:
    """Creates a signed HMAC token for URL query param persistence across F5 refreshes."""
    uname = str(username).strip().lower()
    secret_key = f"{user_obj.get('salt', '')}:{user_obj.get('password_hash', '')}"
    sig = hmac.new(secret_key.encode('utf-8'), uname.encode('utf-8'), hashlib.sha256).hexdigest()[:16]
    return f"{uname}.{sig}"


def _verify_auth_token(token: str, users_dict: dict):
    """Verifies a signed HMAC token from URL query params and returns the matching user dict or None."""
    if not token or '.' not in str(token):
        return None
    uname, sig = str(token).rsplit('.', 1)
    uname = uname.strip().lower()
    u = users_dict.get(uname)
    if not u or not u.get('active', True):
        return None
    expected = _make_auth_token(uname, u)
    if secrets.compare_digest(str(token), expected):
        return u
    return None


def is_running_on_localhost() -> bool:
    """
    Detects if the app is running locally on the developer's Windows workstation
    versus on Streamlit Community Cloud / Linux container.
    """
    if os.path.exists('/mount/src') or os.environ.get('STREAMLIT_SHARING_MODE') or os.environ.get('IS_CLOUD'):
        return False
    if os.name == 'nt' and os.path.exists(r"C:\Users\gdeluca"):
        return True
    return False


def _read_json_safe(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'users' in data and isinstance(data['users'], dict):
                return data
    except Exception:
        pass
    return None


def _write_json_safe(path: str, data: dict):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception as e:
        print(f"Warning writing {path}: {e}")


def _get_github_token():
    """Retrieves optional GITHUB_TOKEN from environment or st.secrets (for Cloud-to-GitHub API persistence)."""
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        return tok
    try:
        if hasattr(st, "secrets") and "GITHUB_TOKEN" in st.secrets:
            return str(st.secrets["GITHUB_TOKEN"]).strip()
    except Exception:
        pass
    return ""


def _push_file_via_github_api(rel_path: str, content_bytes: bytes, commit_msg: str):
    """Pushes a file directly to GitHub master & dev via GitHub Contents REST API if GITHUB_TOKEN is available."""
    token = _get_github_token()
    if not token:
        return False, "No GITHUB_TOKEN configured"

    b64_content = base64.b64encode(content_bytes).decode('ascii')
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "FantaMantra-AI"
    }

    for branch in ("master", "dev"):
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{rel_path}"
        sha = None
        try:
            req_get = urllib.request.Request(f"{url}?ref={branch}", headers=headers, method="GET")
            with urllib.request.urlopen(req_get, timeout=8) as resp:
                existing = json.loads(resp.read().decode('utf-8'))
                sha = existing.get("sha")
        except Exception:
            sha = None

        payload = {
            "message": commit_msg,
            "content": b64_content,
            "branch": branch
        }
        if sha:
            payload["sha"] = sha

        try:
            req_put = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                method="PUT"
            )
            with urllib.request.urlopen(req_put, timeout=10) as _:
                pass
        except Exception as e:
            return False, f"GitHub API error ({branch}): {e}"

    return True, "Synced via GitHub API"


def sync_users_and_leagues_to_github(background: bool = True):
    """
    Automatically commits and pushes data/users_db.json and data/leagues/ to GitHub (master & dev)
    so that saved users and leagues persist across restarts on both Localhost and Streamlit Cloud.
    """
    def _worker():
        try:
            if is_running_on_localhost():
                subprocess.run(
                    ["git", "add", "data/users_db.json", "data/leagues/"],
                    cwd=ROOT_DIR, check=False, capture_output=True
                )
                status_res = subprocess.run(
                    ["git", "status", "--porcelain", "data/users_db.json", "data/leagues/"],
                    cwd=ROOT_DIR, check=False, capture_output=True, text=True
                )
                if status_res.stdout.strip():
                    subprocess.run(
                        ["git", "commit", "-m", "Auto-persist users_db and leagues"],
                        cwd=ROOT_DIR, check=False, capture_output=True
                    )
                subprocess.run(
                    ["git", "push", "fantapando", "HEAD:master"],
                    cwd=ROOT_DIR, check=False, capture_output=True
                )
                subprocess.run(
                    ["git", "push", "fantapando", "HEAD:dev"],
                    cwd=ROOT_DIR, check=False, capture_output=True
                )
            else:
                if os.path.exists(USERS_DB_FILE):
                    with open(USERS_DB_FILE, "rb") as f:
                        raw_bytes = f.read()
                    _push_file_via_github_api("data/users_db.json", raw_bytes, "Auto-persist users_db from Cloud")
        except Exception as e:
            print(f"Auto-sync warning: {e}")

    if background:
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return True, "Sincronizzazione automatica avviata in background."
    else:
        _worker()
        return True, "Sincronizzazione completata!"


def load_users_db() -> dict:
    """
    Loads the users database by merging data/users_db.json and ~/.fantamantra_storage/users_db.json.
    This guarantees that git branch switches, pulls, or resets never erase created users.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(PERSISTENT_STORAGE_DIR, exist_ok=True)

    repo_db = _read_json_safe(USERS_DB_FILE)
    pers_db = _read_json_safe(PERSISTENT_USERS_DB_FILE)

    if repo_db or pers_db:
        merged_users = {}
        deleted_set = set()
        if repo_db:
            deleted_set.update(repo_db.get("deleted_users", []))
        if pers_db:
            deleted_set.update(pers_db.get("deleted_users", []))

        for source_db in (repo_db, pers_db):
            if not source_db:
                continue
            for uname, uobj in source_db.get("users", {}).items():
                if uname in deleted_set and uname != "admin":
                    continue
                if uname not in merged_users:
                    merged_users[uname] = uobj
                else:
                    # Keep whichever record has the newer updated_at / created_at timestamp
                    ts_existing = merged_users[uname].get("updated_at") or merged_users[uname].get("created_at") or ""
                    ts_new = uobj.get("updated_at") or uobj.get("created_at") or ""
                    if ts_new >= ts_existing:
                        merged_users[uname] = uobj

        if "admin" not in merged_users:
            salt, pwd_hash = _hash_password("admin2026")
            merged_users["admin"] = {
                "username": "admin",
                "display_name": "Amministratore",
                "role": "admin",
                "salt": salt,
                "password_hash": pwd_hash,
                "allowed_leagues": ["*"],
                "can_create_leagues": True,
                "default_team_by_league": {},
                "active": True,
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        merged_db = {
            "users": merged_users,
            "deleted_users": sorted(list(deleted_set))
        }

        # Keep both storage locations in sync if they differed
        if repo_db != merged_db:
            _write_json_safe(USERS_DB_FILE, merged_db)
        if pers_db != merged_db:
            _write_json_safe(PERSISTENT_USERS_DB_FILE, merged_db)

        return merged_db

    # Initialize default admin user (initial password: admin2026)
    salt, pwd_hash = _hash_password("admin2026")
    default_db = {
        "users": {
            "admin": {
                "username": "admin",
                "display_name": "Amministratore",
                "role": "admin",
                "salt": salt,
                "password_hash": pwd_hash,
                "allowed_leagues": ["*"],
                "can_create_leagues": True,
                "default_team_by_league": {},
                "active": True,
                "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        },
        "deleted_users": []
    }
    save_users_db(default_db, trigger_git_sync=False)
    return default_db


def save_users_db(db: dict, trigger_git_sync: bool = True):
    """
    Persists the users database to both data/users_db.json AND ~/.fantamantra_storage/users_db.json,
    and optionally auto-syncs to GitHub so Streamlit Cloud and Localhost never lose users on restart.
    """
    _write_json_safe(USERS_DB_FILE, db)
    _write_json_safe(PERSISTENT_USERS_DB_FILE, db)
    if trigger_git_sync:
        sync_users_and_leagues_to_github(background=True)


def authenticate_user(username: str, password: str):
    """
    Validates username and password.
    Returns (True, user_dict, "OK") or (False, None, error_msg).
    """
    uname = str(username).strip().lower()
    db = load_users_db()
    users = db.get('users', {})

    matched_key = None
    for k in users.keys():
        if k.lower() == uname:
            matched_key = k
            break

    if not matched_key:
        return False, None, "Username non trovato."

    u = users[matched_key]
    if not u.get('active', True):
        return False, None, "Questo account è stato disattivato dall'amministratore."

    if verify_password(password, u.get('salt', ''), u.get('password_hash', '')):
        return True, u, "Accesso effettuato!"

    return False, None, "Password non corretta."


def get_current_user():
    """
    Returns the currently logged-in user dictionary, or None if not authenticated.
    1. Checks st.session_state['auth_username']
    2. Checks signed HMAC token in st.query_params['auth'] (survives F5 page refreshes and server restarts)
    3. On localhost, auto-logs in as 'admin' unless the user manually clicked Logout/Test.
    """
    db = load_users_db()
    users = db.get('users', {})

    # 1. Check session_state
    if 'auth_username' in st.session_state and st.session_state['auth_username']:
        uname = st.session_state['auth_username']
        if uname in users and users[uname].get('active', True):
            u_obj = users[uname]
            try:
                if hasattr(st, 'query_params'):
                    expected_tok = _make_auth_token(uname, u_obj)
                    if st.query_params.get('auth') != expected_tok:
                        st.query_params['auth'] = expected_tok
            except Exception:
                pass
            return u_obj

    # 2. Check signed URL query parameter ?auth=username.signature (survives F5 refresh & server restart)
    if not st.session_state.get('force_login_screen', False):
        try:
            if hasattr(st, 'query_params') and 'auth' in st.query_params:
                raw_tok = st.query_params.get('auth')
                if isinstance(raw_tok, list) and raw_tok:
                    raw_tok = raw_tok[0]
                verified_u = _verify_auth_token(raw_tok, users)
                if verified_u:
                    st.session_state['auth_username'] = verified_u['username']
                    return verified_u
        except Exception:
            pass

    # 3. Auto-login as admin on localhost unless user explicitly clicked 'Logout / Test Login'
    if is_running_on_localhost() and not st.session_state.get('force_login_screen', False):
        admin_u = users.get('admin')
        if admin_u:
            st.session_state['auth_username'] = 'admin'
            try:
                if hasattr(st, 'query_params'):
                    st.query_params['auth'] = _make_auth_token('admin', admin_u)
            except Exception:
                pass
            return admin_u

    return None


def is_current_user_admin() -> bool:
    u = get_current_user()
    return bool(u and u.get('role') == 'admin')


def filter_leagues_for_current_user(all_leagues_dict: dict) -> dict:
    """
    Filters the available leagues dictionary according to the logged-in user's permissions.
    Admins (or users with '*' in allowed_leagues) see all leagues.
    Standard users see only leagues in their allowed_leagues list or leagues they created.
    """
    if not all_leagues_dict:
        return {}
    u = get_current_user()
    if not u:
        return {}
    if u.get('role') == 'admin':
        return all_leagues_dict
    allowed = set(u.get('allowed_leagues', []))
    if '*' in allowed:
        return all_leagues_dict

    uname = u.get('username', '')
    filtered = {}
    for lid, linfo in all_leagues_dict.items():
        if lid in allowed or (isinstance(linfo, dict) and linfo.get('owner') == uname):
            filtered[lid] = linfo
    return filtered


def create_or_update_user(
    username: str,
    password: str = None,
    display_name: str = None,
    role: str = "user",
    allowed_leagues: list = None,
    can_create_leagues: bool = False,
    default_team_by_league: dict = None,
    active: bool = True
):
    """Creates a new user or updates an existing user in users_db.json and persists immediately."""
    clean_u = str(username).strip().lower()
    if not clean_u or not clean_u.replace('_', '').replace('.', '').replace('-', '').isalnum():
        return False, "Username non valido (usa solo lettere, numeri, punto o trattino)."

    db = load_users_db()
    users = db.setdefault('users', {})
    deleted_list = db.setdefault('deleted_users', [])
    if clean_u in deleted_list:
        deleted_list.remove(clean_u)

    existing = users.get(clean_u, {})

    if not existing and not password:
        return False, "Inserisci una password per il nuovo utente."

    if password:
        salt, pwd_hash = _hash_password(password)
    else:
        salt = existing.get('salt', '')
        pwd_hash = existing.get('password_hash', '')

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    users[clean_u] = {
        "username": clean_u,
        "display_name": (display_name or existing.get('display_name') or clean_u).strip(),
        "role": role if role in ("admin", "user") else "user",
        "salt": salt,
        "password_hash": pwd_hash,
        "allowed_leagues": allowed_leagues if allowed_leagues is not None else existing.get('allowed_leagues', []),
        "can_create_leagues": bool(can_create_leagues),
        "default_team_by_league": default_team_by_league if default_team_by_league is not None else existing.get('default_team_by_league', {}),
        "active": bool(active),
        "created_at": existing.get('created_at', now_str),
        "updated_at": now_str
    }
    save_users_db(db, trigger_git_sync=True)
    return True, f"✅ Utente '{clean_u}' salvato in modo permanente (Locale + GitHub Cloud)!"


def delete_user_account(username: str):
    """Deletes a user account (cannot delete 'admin') and persists deletion across both stores."""
    clean_u = str(username).strip().lower()
    if clean_u == 'admin':
        return False, "L'account 'admin' principale non può essere eliminato."
    db = load_users_db()
    users = db.get('users', {})
    if clean_u not in users:
        return False, "Utente non trovato."
    del users[clean_u]
    deleted_list = db.setdefault('deleted_users', [])
    if clean_u not in deleted_list:
        deleted_list.append(clean_u)
    save_users_db(db, trigger_git_sync=True)
    return True, f"🗑️ Utente '{clean_u}' eliminato definitivamente."


def grant_league_to_user(username: str, league_id: str):
    """Grants access to a newly created league to the user who created it."""
    clean_u = str(username).strip().lower()
    db = load_users_db()
    users = db.get('users', {})
    if clean_u in users:
        allowed = users[clean_u].setdefault('allowed_leagues', [])
        if '*' not in allowed and league_id not in allowed:
            allowed.append(league_id)
            users[clean_u]['updated_at'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_users_db(db, trigger_git_sync=True)


def render_login_screen():
    """Renders the centered Login Screen when no user is authenticated."""
    st.markdown(
        """
        <div style="max-width: 460px; margin: 60px auto 20px auto; padding: 28px 32px; background: linear-gradient(145deg, #0f172a, #1e293b); border: 1.5px solid #00f0ff; border-radius: 14px; box-shadow: 0 0 25px rgba(0, 240, 255, 0.2);">
            <div style="text-align: center; font-size: 2.2rem; margin-bottom: 4px;">⚽🔐</div>
            <h2 style="text-align: center; color: #00f0ff; margin: 0 0 6px 0; font-weight: 800;">FantaManager AI</h2>
            <p style="text-align: center; color: #94a3b8; font-size: 0.9rem; margin-bottom: 16px;">
                Inserisci le tue credenziali per accedere alle tue leghe Mantra & Classic.
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )

    col_l, col_c, col_r = st.columns([1.2, 1.6, 1.2])
    with col_c:
        with st.form("login_auth_form"):
            in_user = st.text_input("👤 Username:", placeholder="es. admin o il tuo username")
            in_pass = st.text_input("🔑 Password:", type="password", placeholder="••••••••")
            submit_login = st.form_submit_button("🚀 Accedi all'App", type="primary", width='stretch')

            if submit_login:
                ok, u_obj, msg = authenticate_user(in_user, in_pass)
                if ok:
                    st.session_state['auth_username'] = u_obj['username']
                    st.session_state['force_login_screen'] = False
                    try:
                        if hasattr(st, 'query_params'):
                            st.query_params['auth'] = _make_auth_token(u_obj['username'], u_obj)
                    except Exception:
                        pass
                    st.session_state.pop('active_league_id', None)
                    st.session_state.pop('active_my_team', None)
                    st.session_state.pop('_last_live_synced_team', None)
                    st.success(f"Benvenuto, {u_obj.get('display_name', u_obj['username'])}!")
                    st.rerun()
                else:
                    st.error(f"❌ {msg}")

        if is_running_on_localhost():
            st.markdown("---")
            if st.button("⚡ Accesso Rapido Localhost (Admin)", width='stretch'):
                db = load_users_db()
                admin_u = db.get('users', {}).get('admin', {})
                st.session_state['auth_username'] = 'admin'
                st.session_state['force_login_screen'] = False
                try:
                    if hasattr(st, 'query_params') and admin_u:
                        st.query_params['auth'] = _make_auth_token('admin', admin_u)
                except Exception:
                    pass
                st.rerun()
