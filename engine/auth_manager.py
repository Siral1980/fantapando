"""
Multi-User Authentication, Role Permissions, and League Isolation Manager.
- Auto-authenticates as 'admin' on localhost (unless explicitly testing another user or logged out).
- Enforces login screen on Streamlit Cloud / remote access.
- Stores passwords with salted PBKDF2-HMAC-SHA256 hashes in data/users_db.json.
- Isolates league visibility and default team selection per user.
"""

import os
import sys
import json
import hashlib
import secrets
import datetime
import streamlit as st

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
USERS_DB_FILE = os.path.join(DATA_DIR, "users_db.json")


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


def is_running_on_localhost() -> bool:
    """
    Detects if the app is running locally on the developer's Windows workstation
    versus on Streamlit Community Cloud / Linux container.
    """
    # Streamlit Cloud mounts repositories at /mount/src/... on Linux
    if os.path.exists('/mount/src') or os.environ.get('STREAMLIT_SHARING_MODE') or os.environ.get('IS_CLOUD'):
        return False
    if os.name == 'nt' and os.path.exists(r"C:\Users\gdeluca"):
        return True
    return False


def load_users_db() -> dict:
    """Loads the users database from data/users_db.json, initializing default admin if missing."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(USERS_DB_FILE):
        try:
            with open(USERS_DB_FILE, 'r', encoding='utf-8') as f:
                db = json.load(f)
                if isinstance(db, dict) and 'users' in db and 'admin' in db['users']:
                    return db
        except Exception as e:
            print(f"Warning loading users_db.json: {e}")

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
        }
    }
    save_users_db(default_db)
    return default_db


def save_users_db(db: dict):
    """Persists the users database to data/users_db.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(USERS_DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def authenticate_user(username: str, password: str):
    """
    Validates username and password.
    Returns (True, user_dict, "OK") or (False, None, error_msg).
    """
    uname = str(username).strip().lower()
    db = load_users_db()
    users = db.get('users', {})

    # Find case-insensitive match
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
    On localhost, auto-logs in as 'admin' unless the user manually switched account or logged out.
    """
    db = load_users_db()
    users = db.get('users', {})

    if 'auth_username' in st.session_state and st.session_state['auth_username']:
        uname = st.session_state['auth_username']
        if uname in users and users[uname].get('active', True):
            return users[uname]

    # Auto-login as admin on localhost unless user explicitly clicked 'Logout / Test Login'
    if is_running_on_localhost() and not st.session_state.get('force_login_screen', False):
        admin_u = users.get('admin')
        if admin_u:
            st.session_state['auth_username'] = 'admin'
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
    """Creates a new user or updates an existing user in users_db.json."""
    clean_u = str(username).strip().lower()
    if not clean_u or not clean_u.replace('_', '').replace('.', '').replace('-', '').isalnum():
        return False, "Username non valido (usa solo lettere, numeri, punto o trattino)."

    db = load_users_db()
    users = db.setdefault('users', {})
    existing = users.get(clean_u, {})

    if not existing and not password:
        return False, "Inserisci una password per il nuovo utente."

    if password:
        salt, pwd_hash = _hash_password(password)
    else:
        salt = existing.get('salt', '')
        pwd_hash = existing.get('password_hash', '')

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
        "created_at": existing.get('created_at', datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    }
    save_users_db(db)
    return True, f"Utente '{clean_u}' salvato con successo!"


def delete_user_account(username: str):
    """Deletes a user account (cannot delete 'admin')."""
    clean_u = str(username).strip().lower()
    if clean_u == 'admin':
        return False, "L'account 'admin' principale non può essere eliminato."
    db = load_users_db()
    users = db.get('users', {})
    if clean_u not in users:
        return False, "Utente non trovato."
    del users[clean_u]
    save_users_db(db)
    return True, f"Utente '{clean_u}' eliminato."


def grant_league_to_user(username: str, league_id: str):
    """Grants access to a newly created league to the user who created it."""
    clean_u = str(username).strip().lower()
    db = load_users_db()
    users = db.get('users', {})
    if clean_u in users:
        allowed = users[clean_u].setdefault('allowed_leagues', [])
        if '*' not in allowed and league_id not in allowed:
            allowed.append(league_id)
            save_users_db(db)


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
                    # Reset active league/team session keys so user's allowed league & default team load cleanly
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
                st.session_state['auth_username'] = 'admin'
                st.session_state['force_login_screen'] = False
                st.rerun()
