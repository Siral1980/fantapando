"""
FantaMantra AI - Applicazione di Gestione Rosa, Formazioni e Valutatore Scambi.
Combina statistiche del fantacalcio e metriche reali dei calciatori (xG, xA, tiri, passaggi, duelli).
"""

import os
import sys
import json
import datetime
import pandas as pd
import numpy as np
import streamlit as st
import altair as alt

# Setup paths
APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

from engine.data_loader import sync_and_build_database
from engine.fanta_calendar import (
    get_or_create_calendar, get_schedule_matrix, get_fixture_info,
    TEAM_TIERS, compute_dynamic_team_ratings, compute_current_standings,
    get_matchday_from_date, SERIE_A_SCHEDULE
)
from engine.models import batch_predict_xfv, calculate_expected_dfactor
from engine.optimizer import (
    optimize_best_mantra_lineup, MANTRA_FORMATIONS,
    simulate_master_substitutions, audit_master_bench_coverage, order_bench_master_mode,
    parse_mantra_roles,
    CLASSIC_FORMATIONS, optimize_best_classic_lineup, optimize_best_lineup,
    order_bench_classic_mode, simulate_classic_substitutions
)
from engine.trade_evaluator import evaluate_trade
import importlib
import engine.trade_finder
importlib.reload(engine.trade_finder)
from engine.trade_finder import (
    analyze_squad_weaknesses, find_win_win_trades, find_trades_for_target_players,
    RECOMMENDED_QUOTAS, RECOMMENDED_QUOTAS_CLASSIC,
    safe_float, safe_int
)
from engine.roster_manager import (
    load_user_roster, save_user_roster, add_player_to_roster,
    remove_player_from_roster, get_roster_dataframe
)
from engine.league_manager import (
    load_league_rosters, save_league_rosters, parse_official_league_excel,
    get_active_my_team, set_active_my_team, get_team_roster_df, get_league_summary,
    build_loan_registry, get_out_of_serie_a_summary, sync_user_roster_from_league,
    render_league_upload_section, get_league_metadata, save_league_metadata,
    terminate_loan, add_or_update_loan,
    get_available_leagues, get_active_league_id, set_active_league_id,
    create_new_league, delete_league, get_league_type, set_league_type,
    purge_team_and_league_session_state
)
from engine.understat_loader import sync_understat_metrics, get_understat_teams_metrics
from engine.injuries_manager import (
    fetch_live_injuries_from_fantacalcio, load_injuries_data,
    set_player_manual_override, clear_player_manual_override,
    clear_all_manual_overrides, get_all_unavailable_players,
    parse_injury_details, get_all_unavailable_df
)
from engine.probable_lineups import (
    load_probable_lineups, get_player_probable_info, refresh_live_lineups_and_injuries
)
from engine.player_profile_view import (
    show_player_profile_dialog, render_player_profile_content
)
from engine.theme_helper import get_global_theme_css
from engine.auth_manager import (
    get_current_user, is_current_user_admin, render_login_screen,
    load_users_db, save_users_db, create_or_update_user, delete_user_account,
    is_running_on_localhost, sync_users_and_leagues_to_github
)

# Page configuration
st.set_page_config(
    page_title="FantaMantra AI Manager",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS with Soccer Pitch Background, High-Contrast Palette & Larger Typography
st.markdown(get_global_theme_css(), unsafe_allow_html=True)

# Authentication Gate (Auto-login on Localhost, Login Screen on Cloud or after Logout)
current_user = get_current_user()
if not current_user:
    render_login_screen()
    st.stop()

def get_codebase_version():
    """Computes a fingerprint based on the latest modification timestamp of all source code files."""
    mtimes = [os.path.getmtime(__file__)]
    engine_dir = os.path.join(APP_DIR, "engine")
    if os.path.exists(engine_dir):
        for root, _, files in os.walk(engine_dir):
            for f in files:
                if f.endswith('.py'):
                    mtimes.append(os.path.getmtime(os.path.join(root, f)))
    return max(mtimes)

# Auto-invalidation on reload: if any Python file has been modified, clear cache automatically
current_code_version = get_codebase_version()
if '_last_code_version' not in st.session_state:
    st.session_state['_last_code_version'] = current_code_version
elif st.session_state['_last_code_version'] != current_code_version:
    st.cache_data.clear()
    st.cache_resource.clear()
    import importlib
    import engine.optimizer
    import engine.fanta_calendar
    import engine.auth_manager
    import engine.roster_manager
    import engine.league_manager
    importlib.reload(engine.optimizer)
    importlib.reload(engine.fanta_calendar)
    importlib.reload(engine.auth_manager)
    importlib.reload(engine.roster_manager)
    importlib.reload(engine.league_manager)
    from engine.optimizer import (
        MANTRA_FORMATIONS, optimize_best_mantra_lineup,
        CLASSIC_FORMATIONS, optimize_best_classic_lineup, optimize_best_lineup
    )
    from engine.fanta_calendar import get_matchday_from_date, SERIE_A_SCHEDULE
    from engine.auth_manager import (
        get_current_user, is_current_user_admin, render_login_screen,
        load_users_db, save_users_db, create_or_update_user, delete_user_account,
        is_running_on_localhost, sync_users_and_leagues_to_github
    )
    from engine.roster_manager import get_roster_dataframe
    from engine.league_manager import get_out_of_serie_a_summary, get_team_roster_df
    st.session_state['_last_code_version'] = current_code_version
    st.toast("🧹 Rilevate modifiche al codice: moduli ricaricati e cache pulita automaticamente!", icon="🔄")

@st.cache_data
def get_master_data(mtime=None, code_ver=None):
    master_csv = os.path.join(APP_DIR, "data", "players_master.csv")
    if not os.path.exists(master_csv):
        df_m, _ = sync_and_build_database()
        return df_m
    df_m = pd.read_csv(master_csv)
    if 'Pct_Sufficienza' not in df_m.columns or 'Pct_Parate' not in df_m.columns:
        from engine.data_loader import compute_sufficiency_metrics
        df_m = compute_sufficiency_metrics(df_m)
        try:
            df_m.to_csv(master_csv, index=False)
        except Exception:
            pass
    return df_m

@st.cache_data
def get_cached_calendar(cal_mtime=0, code_ver=None):
    return get_or_create_calendar()


def _league_signature(league, league_type=None):
    """Stable hash of the league rosters + league mode, used as cache key (cheap vs. hashing nested dicts)."""
    import hashlib, json
    try:
        payload = json.dumps({"rosters": league, "type": str(league_type)}, sort_keys=True, default=str)
    except Exception:
        payload = str(league) + "_" + str(league_type)
    return hashlib.md5(payload.encode('utf-8')).hexdigest()


@st.cache_data(show_spinner=False, max_entries=64)
def cached_analyze_squad_weaknesses(team_name, league_sig, matchday, code_ver, _league_data, _df_master, league_type=None):
    return analyze_squad_weaknesses(team_name, _league_data, _df_master, matchday=matchday, league_type=league_type)


@st.cache_data(show_spinner=False, max_entries=32, ttl=1800)
def cached_find_win_win_trades(my_team_name, league_sig, matchday, target_role_filter, give_player_filter,
                               opp_team_filter, min_starter_filter, trade_format_filter, max_proposals,
                               code_ver, _league_data, _df_master, league_type=None):
    return find_win_win_trades(
        my_team_name=my_team_name,
        league_data=_league_data,
        df_master=_df_master,
        matchday=matchday,
        target_role_filter=target_role_filter,
        give_player_filter=give_player_filter,
        opp_team_filter=opp_team_filter,
        min_starter_filter=min_starter_filter,
        trade_format_filter=trade_format_filter,
        max_proposals=max_proposals,
        league_type=league_type
    )

master_csv_path = os.path.join(APP_DIR, "data", "players_master.csv")
mtime_val = os.path.getmtime(master_csv_path) if os.path.exists(master_csv_path) else 0
cal_json_path = os.path.join(APP_DIR, "data", "calendar_serie_a.json")
cal_mtime_val = os.path.getmtime(cal_json_path) if os.path.exists(cal_json_path) else 0
df_master = get_master_data(mtime_val, current_code_version)
calendar = get_cached_calendar(cal_mtime_val, current_code_version)

# -------------------------------------------------------------
# ONBOARDING / SETUP WIZARD (FIRST LAUNCH OR RECONFIGURATION)
# -------------------------------------------------------------
CONFIG_FILE = os.path.join(APP_DIR, "data", "league_config.json")
LEAGUE_FILE = os.path.join(APP_DIR, "data", "league_rosters.json")

has_config = os.path.exists(CONFIG_FILE) and os.path.exists(LEAGUE_FILE)
is_setup_mode = st.session_state.get('setup_mode', not has_config)

if is_setup_mode:
    st.markdown("""
    <div style="text-align: center; margin-top: 15px; margin-bottom: 25px;">
        <h1 style="color: #38bdf8; font-size: 2.4rem; margin-bottom: 5px;">⚽ FantaMantra AI</h1>
        <p style="color: #94a3b8; font-size: 1.15rem;">Configurazione Iniziale: Carica la tua Lega</p>
    </div>
    """, unsafe_allow_html=True)
    
    w_col1, w_col2, w_col3 = st.columns([1, 4, 1])
    with w_col2:
        st.markdown("""
        <div style="background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin-bottom: 20px;">
            <h3 style="color: #f8fafc; margin-top: 0;">📁 Carica il file Excel Ufficiale della tua Lega</h3>
            <p style="color: #94a3b8; font-size: 0.95rem;">
                Carica il file Excel (<code>.xlsx</code>) esportato direttamente dal sito o dall'app Fantacalcio.it con le rose della tua lega.
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        uploaded_file = st.file_uploader(
            "Trascina o seleziona qui il file delle rose (.xlsx, .xls, .csv):",
            type=['xlsx', 'xls', 'csv'],
            key="wizard_league_uploader"
        )
        
        existing_league = load_league_rosters()
        parsed_league = None
        
        if uploaded_file is not None:
            try:
                with st.spinner("Lettura ed elaborazione delle rose in corso..."):
                    parsed_league = parse_official_league_excel(uploaded_file, df_master)
                    if parsed_league:
                        save_league_rosters(parsed_league)
                        st.success(f"✅ File elaborato con successo! Rilevate {len(parsed_league)} squadre.")
            except Exception as e:
                st.error(f"Errore durante l'elaborazione del file: {e}")
        elif existing_league:
            st.info(f"💡 È già presente un archivio di lega memorizzato ({len(existing_league)} squadre). Puoi caricare un nuovo file sopra oppure selezionare subito la tua squadra qui sotto.")
            parsed_league = existing_league
            
        if parsed_league:
            st.markdown("""
            <div style="background: rgba(16, 38, 26, 0.90); border: 1.5px solid rgba(74, 222, 128, 0.4); border-radius: 12px; padding: 20px; margin-top: 20px; margin-bottom: 20px;">
                <h3 style="color: #ffffff; margin-top: 0;">👉 Passo 2: Qual è la tua squadra?</h3>
                <p style="color: #cbd5e1; font-size: 0.95rem;">
                    Seleziona quale tra le squadre partecipanti è la tua per caricare automaticamente la tua rosa e calcolare la formazione.
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            teams_list = list(parsed_league.keys())
            current_choice = get_active_my_team()
            if 'Bluelock' in teams_list:
                choice_idx = teams_list.index('Bluelock')
            elif current_choice in teams_list:
                choice_idx = teams_list.index(current_choice)
            else:
                choice_idx = 0
            
            selected_team = st.selectbox(
                "Scegli la tua squadra:",
                options=teams_list,
                index=choice_idx,
                key="wizard_team_select"
            )
            
            df_team_preview = get_team_roster_df(selected_team, df_master)
            if not df_team_preview.empty:
                st.markdown(f"**Anteprima Rosa di {selected_team}** (`{len(df_team_preview)} calciatori`, `{int(df_team_preview['Costo'].sum())} crediti spesi`):")
                preview_cols = ['Giocatore', 'RuoloMantra', 'Squadra', 'Costo', 'FM_Stagione']
                st.dataframe(df_team_preview[preview_cols].head(8), width='stretch', hide_index=True)
                
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🚀 Conferma e Accedi al FantaMantra Manager", type="primary", width='stretch'):
                set_active_my_team(selected_team)
                sync_user_roster_from_league(parsed_league, selected_team)
                st.session_state['setup_mode'] = False
                st.success(f"Squadra '{selected_team}' impostata con successo! Avvio in corso...")
                st.rerun()
                
    st.stop()

# -------------------------------------------------------------
# SIDEBAR
# -------------------------------------------------------------
st.sidebar.title("⚽ FantaMantra AI")
st.sidebar.caption("Statistical & Tactical Engine con D-Factor")

# User Badge & Logout / Switch User
u_role_badge = "👑 Admin" if is_current_user_admin() else "👤 Utente"
u_env_badge = "💻 Localhost" if is_running_on_localhost() else "☁️ Cloud"
u_col1, u_col2 = st.sidebar.columns([1.65, 1.0])
with u_col1:
    st.markdown(
        f"<div style='background:rgba(30,41,59,0.85); border:1px solid #334155; border-radius:7px; padding:5px 9px; font-size:0.80rem; color:#e2e8f0;'>"
        f"<b>{current_user.get('display_name', current_user.get('username'))}</b><br>"
        f"<span style='color:#38bdf8; font-size:0.72rem;'>{u_role_badge} · {u_env_badge}</span></div>",
        unsafe_allow_html=True
    )
with u_col2:
    if st.button("🚪 Esci / Test", key="sb_btn_logout_switch", width='stretch', help="Esci o accedi con un altro account per testare la vista di un amico"):
        st.session_state.pop('auth_username', None)
        st.session_state.pop('active_league_id', None)
        st.session_state.pop('active_my_team', None)
        st.session_state['force_login_screen'] = True
        try:
            if hasattr(st, 'query_params'):
                st.query_params.pop('auth', None)
        except Exception:
            pass
        st.rerun()

# -------------------------------------------------------------
# MULTI-LEAGUE SELECTOR & MANAGEMENT
# -------------------------------------------------------------
leagues_dict = get_available_leagues()
league_ids = list(leagues_dict.keys())

if not league_ids:
    st.warning("⚠️ Il tuo account non ha ancora leghe associate.")
    if is_current_user_admin() or current_user.get('can_create_leagues', False):
        st.info("Usa il modulo qui sotto per creare la tua prima lega!")
        with st.form("empty_user_new_league_form"):
            new_lg_name_e = st.text_input("Nome della nuova lega:", placeholder="es. Fanta Amici 2026")
            new_lg_mode_e = st.radio("Tipologia lega:", ["Mantra", "Classic"], horizontal=True)
            if st.form_submit_button("➕ Crea Lega", type="primary"):
                if new_lg_name_e.strip():
                    ok_e, _, msg_e = create_new_league(new_lg_name_e.strip(), league_type=new_lg_mode_e.lower())
                    if ok_e:
                        st.success(msg_e)
                        st.rerun()
    st.stop()

active_league = get_active_league_id()

if active_league not in league_ids:
    active_league = league_ids[0]
    set_active_league_id(active_league, persist_disk=False)

curr_league_idx = league_ids.index(active_league)
active_league_type = get_league_type(active_league)
is_classic = (active_league_type == 'classic')

selected_league_id = st.sidebar.selectbox(
    "🏆 Lega Attiva:",
    options=league_ids,
    index=curr_league_idx,
    format_func=lambda x: f"🏆 {leagues_dict.get(x, {}).get('name', x)} ({'🟢 Classic' if leagues_dict.get(x, {}).get('type') == 'classic' else '🔴 Mantra'})",
    key="sb_active_league_select",
    help="Seleziona la lega da visualizzare e gestire. Ogni utente vede esclusivamente le leghe abilitate per il suo profilo."
)

if selected_league_id != active_league:
    set_active_league_id(selected_league_id, persist_disk=is_current_user_admin())
    st.rerun()

# 1-Click Toggle Mantra / Classic
col_m1, col_m2 = st.sidebar.columns([1.3, 1.2])
with col_m1:
    if is_classic:
        st.markdown("<div style='background:rgba(34,197,94,0.15); border:1px solid #22c55e; border-radius:6px; padding:5px 8px; font-weight:700; color:#4ade80; text-align:center; font-size:0.83rem;'>🟢 Classic Mode</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div style='background:rgba(239,68,68,0.15); border:1px solid #ef4444; border-radius:6px; padding:5px 8px; font-weight:700; color:#f87171; text-align:center; font-size:0.83rem;'>🔴 Mantra Mode</div>", unsafe_allow_html=True)
with col_m2:
    target_mode = "mantra" if is_classic else "classic"
    btn_label = "Passa a Mantra" if is_classic else "Passa a Classic"
    if st.button(btn_label, key="sb_btn_toggle_mode", width='stretch', help=f"Cambia la modalità di gioco di {leagues_dict[active_league]['name']}"):
        set_league_type(target_mode, persist_disk=is_current_user_admin())
        st.rerun()


# -------------------------------------------------------------
# ACTIVE SQUAD & ROSTER RESOLUTION
# -------------------------------------------------------------
league_dict = load_league_rosters()
league_teams = list(league_dict.keys()) if league_dict else []
current_active_team = get_active_my_team()

if league_teams:
    st.sidebar.markdown('---')
    idx_team = league_teams.index(current_active_team) if current_active_team in league_teams else 0
    selected_my_team = st.sidebar.selectbox(
        '👥 Squadra Attiva:',
        options=league_teams,
        index=idx_team,
        key=f'sb_team_select_{current_active_team}',
        help='Imposta quale delle squadre della lega è la tua squadra.'
    )
    if selected_my_team != current_active_team:
        set_active_my_team(selected_my_team)
        st.rerun()

if 'custom_league_data' in st.session_state:
    st.sidebar.info('👤 **Lega Ospite in Sessione** (privata)')
    if st.sidebar.button('🔄 Torna alla Lega Principale', width='stretch'):
        del st.session_state['custom_league_data']
        st.session_state.pop('custom_league_meta', None)
        st.session_state.pop('active_my_team', None)
        purge_team_and_league_session_state()
        st.rerun()

# Guarantee user squad is perfectly synchronized with active league team in session
if league_dict and current_active_team in league_dict:
    league_players = [p['Giocatore'] for p in league_dict[current_active_team]]
    user_squad_names = league_players
else:
    user_squad_names = load_user_roster()

# Automatic reload of Probable Lineups and Injuries/Suspensions every time the active team changes
current_team_sync_key = f'{active_league}::{current_active_team}'
if st.session_state.get('_last_live_synced_team') != current_team_sync_key:
    with st.spinner(f'🔄 Aggiornamento Probabili Formazioni e Infortunati/Squalificati per {current_active_team}...'):
        refresh_live_lineups_and_injuries()
        st.cache_data.clear()
    st.session_state['_last_live_synced_team'] = current_team_sync_key

# Top-level calculation of df_my_roster so all tabs immediately inherit the active team
df_my_roster = get_roster_dataframe(df_master, user_squad_names)

# -------------------------------------------------------------
# MATCHDAY SELECTOR & LIVE SYNC WIDGET IN SIDEBAR
# -------------------------------------------------------------
auto_giornata, matchday_info = get_matchday_from_date()

if 'selected_giornata' not in st.session_state or st.session_state.get('_last_auto_giornata') != auto_giornata:
    st.session_state['selected_giornata'] = auto_giornata
    st.session_state['_last_auto_giornata'] = auto_giornata

st.sidebar.markdown(f'''
<div style="background: linear-gradient(135deg, rgba(30,41,59,0.9), rgba(15,23,42,0.9)); border: 1px solid #334155; border-left: 4px solid #38bdf8; border-radius: 8px; padding: 8px 12px; margin-top: 10px; margin-bottom: 8px;">
    <div style="font-size: 0.70rem; color: #94a3b8; font-weight: 600; text-transform: uppercase;">Calendario Serie A</div>
    <div style="font-size: 1.0rem; font-weight: 700; color: #38bdf8;">{matchday_info['label']}</div>
    <div style="font-size: 0.78rem; color: {'#4ade80' if matchday_info['status'] == 'live' else '#facc15'};
    margin-top: 2px;">
        {'🟢 Turno in corso' if matchday_info['status'] == 'live' else '⏳ Prossimo turno'}
    </div>
</div>
''', unsafe_allow_html=True)

selected_giornata = st.sidebar.number_input(
    'Giornata da Schierare:',
    min_value=1,
    max_value=38,
    value=st.session_state['selected_giornata'],
    step=1,
    help='Impostata in automatico dalla data odierna e dal calendario ufficiale Serie A.'
)

if selected_giornata != st.session_state['selected_giornata']:
    st.session_state['selected_giornata'] = selected_giornata
    st.rerun()

if selected_giornata != auto_giornata:
    if st.sidebar.button(f'🎯 Riaggancia ad Oggi ({matchday_info["label"]})'):
        st.session_state['selected_giornata'] = auto_giornata
        st.rerun()

st.sidebar.markdown('---')
col_sb_s1, col_sb_s2 = st.sidebar.columns([1.35, 1.0])
with col_sb_s1:
    st.markdown("<div style='font-size:0.75rem; color:#94a3b8; margin-top:4px;'>🟢 <b>Dati Live Attivi</b><br><span style='font-size:0.70rem; color:#64748b;'>Fantacalcio.it + Understat</span></div>", unsafe_allow_html=True)
with col_sb_s2:
    if st.button('🔄 Sync', key='sb_quick_sync_btn', width='stretch', help='Aggiorna voti e statistiche ufficiali live da Fantacalcio.it e Understat'):
        st.cache_data.clear()
        st.cache_resource.clear()
        with st.spinner('Sincronizzazione dati live in corso...'):
            df_master, _ = sync_and_build_database(force_live_scrape=True)
        st.sidebar.success('Aggiornato!')
        st.rerun()

st.sidebar.caption(f'📋 Rosa `{current_active_team}`: **{len(user_squad_names)} calciatori**')

# -------------------------------------------------------------
# MAIN APP TABS
# -------------------------------------------------------------
tab_formazione, tab_rosa, tab_scambi, tab_esplora, tab_impostazioni = st.tabs([
    '🏟️ Formazione & Matchday',
    '📋 La Mia Rosa',
    '🤝 Trade Center',
    '🔍 Esplora & Scouting',
    '⚙️ Impostazioni & Sync'
])

with tab_formazione:
    if df_my_roster.empty:
        st.warning("La tua rosa è vuota! Aggiungi dei giocatori nella scheda 'La Mia Rosa'.")
    else:
        prob_cache = load_probable_lineups(force_refresh=False)
        prob_md = prob_cache.get('matchday_fanta', selected_giornata)
        prob_last_ts = prob_cache.get('last_scraped', 'N/D')
        sample_teams = list(prob_cache.get('teams_summary', {}).values())
        aligned_srcs = sample_teams[0].get('Fonti_Allineate', ['Fantacalcio.it']) if sample_teams else ['Fantacalcio.it']
        src_badges = " + ".join(aligned_srcs)

        # Compact Top Action Bar: Title + Modulo Selector + Live Refresh
        top_bar_c1, top_bar_c2, top_bar_c3 = st.columns([2.3, 1.2, 0.9])
        with top_bar_c1:
            st.subheader(f"🏆 Formazione {selected_giornata}ª Giornata — {current_active_team}")
            st.caption(f"📡 Fonti live allineate ({src_badges}) • Sincro: `{prob_last_ts}`")
        with top_bar_c2:
            forms_dict = CLASSIC_FORMATIONS if is_classic else MANTRA_FORMATIONS
            modulo_options = ["✨ Consigliato dall'AI (Migliore)"] + list(forms_dict.keys())
            selected_modulo_override = st.selectbox(
                "Modulo Tattico:",
                options=modulo_options,
                index=0,
                key=f"select_modulo_override_{current_active_team}"
            )
        with top_bar_c3:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            if st.button("🔄 Aggiorna Probabili", width='stretch', key="btn_refresh_prob_lineups"):
                with st.spinner("Scaricamento Probabili Formazioni e Infortuni/Squalifiche in corso..."):
                    refresh_live_lineups_and_injuries()
                    st.cache_data.clear()
                st.toast("Probabili formazioni e infortunati aggiornati con successo!", icon="✅")
                st.rerun()

        # Consolidated Coach Overrides & Injury Management (Collapsed by Default)
        curr_indisp = df_my_roster[df_my_roster['Stato_Disponibilita'] != 'Disponibile'].copy() if 'Stato_Disponibilita' in df_my_roster.columns else pd.DataFrame()
        n_indisp_badge = f" • 🚑 {len(curr_indisp)} indisponibili/dubbi" if not curr_indisp.empty else ""
        with st.expander(f"⚙️ Scelte del Mister & Gestione Indisponibili (Forza/Escludi Titolari o Modifica Stati{n_indisp_badge})", expanded=False):
            exclude_uneligible = st.checkbox(
                "🚫 Escludi automaticamente calciatori non schierabili (Infortunati, Squalificati, Prestiti OUT, Fuori Serie A *)",
                value=True,
                key=f"chk_excl_unel_{current_active_team}"
            )
            all_roster_names = sorted(df_my_roster['Giocatore'].unique().tolist())
            co1, co2 = st.columns(2)
            with co1:
                forced_starters = st.multiselect(
                    "📌 Forza nell'11 Titolare:",
                    options=all_roster_names,
                    default=[],
                    key=f"lineup_force_starters_{current_active_team}",
                    help="Schiera obbligatoriamente questi giocatori nell'11 iniziale."
                )
            with co2:
                excluded_starters = st.multiselect(
                    "🚫 Escludi dall'11 Titolare (Manda in Panchina):",
                    options=[p for p in all_roster_names if p not in forced_starters],
                    default=[],
                    key=f"lineup_exclude_starters_{current_active_team}",
                    help="Impedisce a questi giocatori di partire nell'11 titolare."
                )

            if not curr_indisp.empty:
                st.markdown("---")
                st.markdown("**📋 Indisponibili e Rientri Stimati nella Tua Rosa:**")
                role_col_disp = 'RuoloClassic' if is_classic else 'RuoloMantra'
                df_indisp_display = pd.DataFrame({
                    'Calciatore': curr_indisp['Giocatore'],
                    'Ruolo': curr_indisp.get(role_col_disp, curr_indisp.get('Ruolo', '-')),
                    'Squadra': curr_indisp.get('Squadra', '-'),
                    'Stato': curr_indisp['Stato_Disponibilita'],
                    'Diagnosi / Motivo': curr_indisp.get('Motivo_Indisponibilita', '-'),
                    'Rientro Stimato': curr_indisp.get('Rientro_Previsto', '-'),
                    'Giornata Prevista': curr_indisp.get('Badge_Rientro', '-')
                })
                st.dataframe(df_indisp_display, hide_index=True, width='stretch')

            st.markdown("---")
            st.markdown("**✍️ Modifica Manualmente Stato Medico (Notizie Ultim'Ora):**")
            ov_col1, ov_col2, ov_col3, ov_col4 = st.columns([2, 2, 1, 1])
            with ov_col1:
                sel_p = st.selectbox("Calciatore:", options=all_roster_names, key="override_sel_p")
            with ov_col2:
                sel_status = st.selectbox(
                    "Nuovo stato:",
                    options=["Disponibile (Forzato)", "Infortunato", "Squalificato", "In dubbio", "Ripristina Automatico"],
                    key="override_sel_st"
                )
            with ov_col3:
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button("💾 Applica", type="primary", key="btn_apply_override", width='stretch'):
                    if sel_status == "Ripristina Automatico":
                        clear_player_manual_override(sel_p)
                    else:
                        set_player_manual_override(sel_p, sel_status)
                    st.cache_data.clear()
                    st.rerun()
            with ov_col4:
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button("🗑️ Reset Tutti", key="btn_reset_all_overrides", width='stretch'):
                    clear_all_manual_overrides()
                    st.cache_data.clear()
                    st.rerun()

        eligible_roster = df_my_roster.copy()
        if exclude_uneligible and 'Schierabile' in eligible_roster.columns:
            uneligible_rows = eligible_roster[eligible_roster['Schierabile'] == False]
            if not uneligible_rows.empty:
                desc_items = []
                for _, r in uneligible_rows.iterrows():
                    st_disp = r.get('Stato_Disponibilita', 'Disponibile')
                    if st_disp == 'Infortunato':
                        motivo = f"🚑 {r.get('Badge_Rientro') or 'infortunato'}"
                    elif st_disp == 'Squalificato':
                        motivo = "🟥 squalificato"
                    elif r.get('Stato_Prestito') == 'Prestito OUT':
                        motivo = "📤 prestito OUT"
                    else:
                        motivo = "🚫 fuori Serie A"
                    desc_items.append(f"**{r['Giocatore']}** ({motivo})")
                st.caption(f"🚫 **Esclusi automaticamente ({len(uneligible_rows)}):** {' · '.join(desc_items)}")
            eligible_roster = eligible_roster[eligible_roster['Schierabile'] == True]

        # Predict xFV for current squad (automatically enriched with prob_cache)
        df_my_proj = batch_predict_xfv(eligible_roster, matchday=selected_giornata, calendar=calendar, prob_lineups_cache=prob_cache)

        # Prepare DataFrame for optimizer with temporary coach override weights, then restore true xFV/P_Voto
        df_opt_input = df_my_proj.copy()
        true_metrics_map = {
            r['Giocatore']: (float(r['xFV']), float(r['P_Voto']), float(r.get('D_Factor_Contribution', 6.0)))
            for _, r in df_my_proj.iterrows()
        }
        if forced_starters or excluded_starters:
            for idx_r, r in df_opt_input.iterrows():
                gn = r['Giocatore']
                if gn in forced_starters:
                    df_opt_input.at[idx_r, 'xFV'] = float(r['xFV']) + 50.0
                    df_opt_input.at[idx_r, 'P_Voto'] = max(0.95, float(r['P_Voto']))
                elif gn in excluded_starters:
                    df_opt_input.at[idx_r, 'xFV'] = 0.01
                    df_opt_input.at[idx_r, 'P_Voto'] = min(0.10, float(r['P_Voto']))

        # Optimize lineup
        allowed_forms = None if selected_modulo_override == "✨ Consigliato dall'AI (Migliore)" else [selected_modulo_override]
        if is_classic:
            opt_res = optimize_best_classic_lineup(df_opt_input, allowed_formations=allowed_forms)
        else:
            opt_res = optimize_best_mantra_lineup(df_opt_input, allowed_formations=allowed_forms)

        # Restore true xFV & P_Voto if coach overrides were used
        if opt_res and (forced_starters or excluded_starters):
            sum_true_xfv = 0.0
            for t_p in opt_res.get('Titolari', []):
                gn = t_p['Giocatore']
                if gn in true_metrics_map:
                    t_p['xFV'], t_p['P_Voto'], _ = true_metrics_map[gn]
                sum_true_xfv += float(t_p.get('xFV', 0.0))
            for b_p in opt_res.get('Panchina', []):
                gn = b_p['Giocatore']
                if gn in true_metrics_map:
                    b_p['xFV'], b_p['P_Voto'], _ = true_metrics_map[gn]
            opt_res['Somma_xFV_Titolari'] = round(sum_true_xfv, 2)
            opt_res['Punti_Attesi_Totali'] = round(sum_true_xfv + float(opt_res.get('D_Factor_Atteso', 0.0)), 2)
        
        if not opt_res:
            st.error("Impossibile schierare un modulo legale (verifica di avere almeno 1 Portiere e abbastanza difensori/attaccanti).")
        else:
            # 1. Compact Matchday HUD Strip
            d_label = "Bonus Difesa" if is_classic else "D-Factor"
            has_issues = opt_res.get('Ha_Problemi_Copertura', False)
            safe_alts = opt_res.get('Moduli_Sicuri_Alternativi', [])
            cambio_mod_slots = opt_res.get('Slot_Coperti_Cambio_Modulo', [])

            if has_issues:
                cop_badge = '<span style="color:#ef4444; font-weight:700;">🚨 Rischio Inferiorità</span>'
            elif cambio_mod_slots:
                cop_badge = '<span style="color:#38bdf8; font-weight:700;">🔄 Cambio Modulo OK</span>'
            else:
                cop_badge = '<span style="color:#34d399; font-weight:700;">🛡️ Copertura Blindata</span>'

            hud_html = f"""
            <div style="display: flex; flex-wrap: wrap; gap: 14px; align-items: center; justify-content: space-between; background: linear-gradient(90deg, rgba(15,23,42,0.90) 0%, rgba(30,41,59,0.90) 100%); border: 1px solid #1e293b; border-radius: 8px; padding: 10px 18px; margin: 4px 0 10px 0;">
                <div><span style="color:#94a3b8; font-size:0.75rem; text-transform:uppercase; font-weight:700;">Modulo Tattico</span><br><b style="color:#38bdf8; font-size:1.15rem;">{opt_res['Modulo']}</b></div>
                <div><span style="color:#94a3b8; font-size:0.75rem; text-transform:uppercase; font-weight:700;">Punti Attesi Totali</span><br><b style="color:#34d399; font-size:1.20rem;">{opt_res['Punti_Attesi_Totali']} pt</b></div>
                <div><span style="color:#94a3b8; font-size:0.75rem; text-transform:uppercase; font-weight:700;">xFV 11 Titolari</span><br><b style="color:#f1f5f9; font-size:1.15rem;">{opt_res['Somma_xFV_Titolari']}</b></div>
                <div><span style="color:#94a3b8; font-size:0.75rem; text-transform:uppercase; font-weight:700;">{d_label}</span><br><b style="color:#f59e0b; font-size:1.15rem;">+{opt_res['D_Factor_Atteso']} pt</b></div>
                <div><span style="color:#94a3b8; font-size:0.75rem; text-transform:uppercase; font-weight:700;">Stato Copertura</span><br>{cop_badge}</div>
            </div>
            """
            st.markdown(hud_html, unsafe_allow_html=True)

            # 2. Compact Coverage Alert (only if needed)
            if has_issues:
                uncovered_list = opt_res.get('Slot_Scoperti', [])
                uncovered_badges = " ".join([f"`{s}`" for s in uncovered_list])
                with st.expander(f"🚨 Attenzione: possibile inferiorità numerica nello slot {uncovered_badges} — Clicca per alternative", expanded=False):
                    if safe_alts:
                        cols_alt = st.columns(len(safe_alts))
                        for idx_a, safe_alt in enumerate(safe_alts):
                            with cols_alt[idx_a]:
                                delta_c = "#34d399" if abs(safe_alt['Delta_Punti']) <= 0.8 else "#f59e0b"
                                st.markdown(f"""
                                <div style="background: rgba(16, 185, 129, 0.08); border: 1.5px solid #10b981; border-radius: 8px; padding: 10px 14px; height: 100%;">
                                    <div style="display: flex; justify-content: space-between; align-items: center;">
                                        <span style="font-weight: 800; font-size: 1.05rem; color: #34d399;">🛡️ {safe_alt['Modulo']}</span>
                                        <span style="font-weight: 700; color: #ffffff;">{safe_alt['Punti_Totali']} pt <span style="color: {delta_c}; font-size: 0.85rem;">({safe_alt['Delta_Punti']:+.2f} pt)</span></span>
                                    </div>
                                    <div style="color: #cbd5e1; font-size: 0.82rem; margin-top: 5px;">{safe_alt['Dettaglio']}</div>
                                </div>
                                """, unsafe_allow_html=True)
                        st.caption("💡 *Puoi selezionare il modulo alternativo direttamente dal menu a tendina in alto se vuoi evitare il rischio di giocare in 10.*")

            titolari_list = opt_res['Titolari']

            # Prepare Starters Table Data
            starter_rows = []
            for p in titolari_list:
                slot = p['Slot_Assegnato']
                gn = p['Giocatore']
                sq = p.get('Squadra', '-')
                m = p.get('Match', '-')
                fdr = int(p.get('FDR', 3))
                fdr_badge = "🟢" if fdr <= 2 else ("🟡" if fdr == 3 else "🔴")
                
                p_voto_pct = int(float(p.get('P_Voto', 0.90)) * 100)
                bal_info = str(p.get('Ballottaggio_Info', '')).strip()
                if bal_info:
                    tit_str = f"⚖️ {p_voto_pct}% (Bal)"
                elif p_voto_pct >= 85:
                    tit_str = f"🟢 {p_voto_pct}%"
                elif p_voto_pct >= 60:
                    tit_str = f"🟡 {p_voto_pct}%"
                else:
                    tit_str = f"🔴 {p_voto_pct}%"
                
                exp_gf = float(p.get('Exp_GF', 0.0))
                exp_ass = float(p.get('Exp_ASS', 0.0))
                bonus_imb = float(p.get('Bonus_Imbattibilita', 0.0))
                if slot in ['Por', 'P']:
                    bonus_str = f"CS +{bonus_imb:.2f}" if bonus_imb > 0.05 else f"xGS -{float(p.get('Exp_GS', 0.0)):.2f}"
                else:
                    b_parts = []
                    if exp_gf >= 0.08:
                        b_parts.append(f"GF {exp_gf:.2f}")
                    if exp_ass >= 0.08:
                        b_parts.append(f"ASS {exp_ass:.2f}")
                    bonus_str = " + ".join(b_parts) if b_parts else "-"
                    
                pred_v = float(p.get('Pred_Voto', 6.0))
                xfv = float(p.get('xFV', 6.0))
                
                starter_rows.append({
                    'Slot': slot,
                    'Calciatore': gn,
                    'Squadra': sq,
                    'Match': f"{m} {fdr_badge}",
                    'Titolarità': tit_str,
                    'Voto': f"{pred_v:.2f}",
                    'Bonus Atteso': bonus_str,
                    'xFV': round(xfv, 2)
                })
            df_starters_display = pd.DataFrame(starter_rows)

            # Prepare Bench Table Data
            bench_rows = []
            for idx_b, b in enumerate(opt_res.get('Panchina', [])):
                pos = f"#{b.get('Posizione_Panchina', idx_b + 1)}"
                gn = b.get('Giocatore', '')
                sq = b.get('Squadra', '')
                ruoli = b.get('RuoloClassic' if is_classic else 'RuoloMantra', '')
                m = b.get('Match', '')
                fdr = int(b.get('FDR', 3))
                fdr_badge = "🟢" if fdr <= 2 else ("🟡" if fdr == 3 else "🔴")
                
                p_voto_pct = int(float(b.get('P_Voto', 0.85)) * 100)
                tit_str = f"🟢 {p_voto_pct}%" if p_voto_pct >= 80 else (f"🟡 {p_voto_pct}%" if p_voto_pct >= 50 else f"🔴 {p_voto_pct}%")
                score_p = round(float(b.get('Score_Panchina', b.get('EV', 5.0))), 2)
                
                bench_rows.append({
                    'Ord': pos,
                    'Calciatore': gn,
                    'Ruolo': ruoli,
                    'Squadra': sq,
                    'Match': f"{m} {fdr_badge}",
                    'Titolarità': tit_str,
                    'Score': score_p
                })
            df_bench_display = pd.DataFrame(bench_rows)

            # View Mode Selector
            v_col1, v_col2 = st.columns([2.6, 1.4])
            with v_col1:
                lineup_view_mode = st.radio(
                    "Modalità Formazione:",
                    options=["⚡ Vista Compatta Affiancata (Consigliata)", "🏟️ Lavagna Tattica", "🃏 Schede Dettagliate"],
                    horizontal=True,
                    key=f"lineup_view_mode_{current_active_team}"
                )
            with v_col2:
                st.caption("💡 *Clicca su un calciatore per aprire la scheda di approfondimento.*")

            # 3. Render Lineup Based on Mode
            if lineup_view_mode == "⚡ Vista Compatta Affiancata (Consigliata)":
                col_starters, col_bench = st.columns([1.35, 1.0])
                with col_starters:
                    st.markdown(f"**🟢 11 Titolari Consigliati ({opt_res['Modulo']})**")
                    starter_event = st.dataframe(
                        df_starters_display,
                        column_config={
                            "Slot": st.column_config.TextColumn("Slot", width="small"),
                            "Calciatore": st.column_config.TextColumn("Calciatore", width="medium"),
                            "Squadra": st.column_config.TextColumn("Eq", width="small"),
                            "Match": st.column_config.TextColumn("Match (FDR)", width="medium"),
                            "Titolarità": st.column_config.TextColumn("Titolarità", width="small"),
                            "Voto": st.column_config.TextColumn("Voto", width="small"),
                            "Bonus Atteso": st.column_config.TextColumn("Bonus Atteso", width="small"),
                            "xFV": st.column_config.NumberColumn("xFV", format="%.2f", width="small"),
                        },
                        hide_index=True,
                        width='stretch',
                        height=430,
                        selection_mode="single-row",
                        on_select="rerun",
                        key=f"starters_table_{current_active_team}"
                    )
                    if starter_event and hasattr(starter_event, 'selection'):
                        s_rows = starter_event.selection.get('rows', [])
                        if s_rows and len(s_rows) > 0:
                            r_idx = s_rows[0]
                            if r_idx < len(df_starters_display):
                                p_name = df_starters_display.iloc[r_idx]['Calciatore']
                                show_player_profile_dialog(
                                    p_name,
                                    df_master,
                                    calendar=calendar,
                                    matchday=selected_giornata,
                                    df_roster=df_my_roster
                                )

                with col_bench:
                    st.markdown("**🟡 Panchina (Ordine di Subentro 1-12)**")
                    bench_event = st.dataframe(
                        df_bench_display,
                        column_config={
                            "Ord": st.column_config.TextColumn("Ord", width="small"),
                            "Calciatore": st.column_config.TextColumn("Calciatore", width="medium"),
                            "Ruolo": st.column_config.TextColumn("Ruolo", width="small"),
                            "Squadra": st.column_config.TextColumn("Eq", width="small"),
                            "Match": st.column_config.TextColumn("Match (FDR)", width="medium"),
                            "Titolarità": st.column_config.TextColumn("Titolarità", width="small"),
                            "Score": st.column_config.NumberColumn("Score", format="%.2f", width="small"),
                        },
                        hide_index=True,
                        width='stretch',
                        height=430,
                        selection_mode="single-row",
                        on_select="rerun",
                        key=f"bench_table_{current_active_team}"
                    )
                    if bench_event and hasattr(bench_event, 'selection'):
                        b_rows = bench_event.selection.get('rows', [])
                        if b_rows and len(b_rows) > 0:
                            r_idx = b_rows[0]
                            if r_idx < len(df_bench_display):
                                p_name = df_bench_display.iloc[r_idx]['Calciatore']
                                show_player_profile_dialog(
                                    p_name,
                                    df_master,
                                    calendar=calendar,
                                    matchday=selected_giornata,
                                    df_roster=df_my_roster
                                )

            elif lineup_view_mode == "🏟️ Lavagna Tattica":
                por_line = [t for t in titolari_list if t['Slot_Assegnato'] in ['Por', 'P']]
                def_line = [t for t in titolari_list if t['Slot_Assegnato'] in ['Dc', 'Dd', 'Ds', 'Dc/B', 'B', 'D']]
                mid_line = [t for t in titolari_list if t['Slot_Assegnato'] in ['E', 'E/W', 'M', 'M/C', 'C', 'C/T', 'W', 'W/T', 'T', 'T/A']]
                att_line = [t for t in titolari_list if t['Slot_Assegnato'] in ['A/Pc', 'W/A', 'Pc', 'A', 'T/A/Pc']]

                def _render_line_chips(players):
                    chips = []
                    for pl in players:
                        slot_c = "#ef4444" if any(x in pl['Slot_Assegnato'] for x in ['A', 'Pc']) else (
                            "#a855f7" if any(x in pl['Slot_Assegnato'] for x in ['W', 'T']) else (
                                "#3b82f6" if any(x in pl['Slot_Assegnato'] for x in ['M', 'C', 'E']) else (
                                    "#22c55e" if any(x in pl['Slot_Assegnato'] for x in ['D', 'Dc', 'Dd', 'Ds', 'B']) else "#eab308"
                                )
                            )
                        )
                        fdr_c = "#22c55e" if pl.get('FDR', 3) <= 2 else ("#eab308" if pl.get('FDR', 3) == 3 else "#ef4444")
                        chips.append(f"""
                        <div style="background: rgba(15,23,42,0.88); border: 1.5px solid {slot_c}; border-radius: 8px; padding: 6px 10px; margin: 4px; min-width: 125px; text-align: center; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.5);">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
                                <span style="background: {slot_c}; color: #ffffff; padding: 1px 5px; border-radius: 4px; font-size: 0.72rem; font-weight: 800;">{pl['Slot_Assegnato']}</span>
                                <span style="font-size: 0.72rem; color: {fdr_c}; font-weight: 700;">{pl['Squadra']} vs {pl['Match']}</span>
                            </div>
                            <div style="font-weight: 700; font-size: 0.90rem; color: #f8fafc; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{pl['Giocatore']}</div>
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 3px; font-size: 0.78rem;">
                                <span style="color: #94a3b8;">Voto {float(pl.get('Pred_Voto', 6.0)):.1f}</span>
                                <span style="color: #00f0ff; font-weight: 800;">xFV {pl.get('xFV')}</span>
                            </div>
                        </div>
                        """)
                    return f"<div style='display: flex; justify-content: center; gap: 8px; flex-wrap: wrap;'>{''.join(chips)}</div>"

                pitch_html = f"""
                <div style="background: radial-gradient(circle, #1e3a24 0%, #0d1f12 100%); border: 2px solid #22c55e; border-radius: 12px; padding: 16px 12px; margin-bottom: 14px; position: relative;">
                    <div style="position: absolute; top: 50%; left: 0; right: 0; height: 1px; background: rgba(255,255,255,0.15);"></div>
                    <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 70px; height: 70px; border: 1px solid rgba(255,255,255,0.15); border-radius: 50%;"></div>
                    <div style="position: relative; z-index: 2; display: flex; flex-direction: column; gap: 14px;">
                        <div>{_render_line_chips(att_line)}</div>
                        <div>{_render_line_chips(mid_line)}</div>
                        <div>{_render_line_chips(def_line)}</div>
                        <div>{_render_line_chips(por_line)}</div>
                    </div>
                </div>
                """
                st.markdown(pitch_html, unsafe_allow_html=True)

                st.markdown("**🟡 Panchina Consigliata (Ordine 1-12)**")
                st.dataframe(df_bench_display, hide_index=True, width='stretch')

            else:
                # Detailed Tactical Cards View (Deep Dive)
                por_line = [t for t in titolari_list if t['Slot_Assegnato'] in ['Por', 'P']]
                def_line = [t for t in titolari_list if t['Slot_Assegnato'] in ['Dc', 'Dd', 'Ds', 'Dc/B', 'B', 'D']]
                mid_line = [t for t in titolari_list if t['Slot_Assegnato'] in ['E', 'E/W', 'M', 'M/C', 'C', 'C/T', 'W', 'W/T', 'T', 'T/A']]
                att_line = [t for t in titolari_list if t['Slot_Assegnato'] in ['A/Pc', 'W/A', 'Pc', 'A', 'T/A/Pc']]

                def def_title_lbl():
                    return "🛡️ DIFESA (MODIFICATORE)" if is_classic else "🛡️ DIFESA (D-FACTOR REPARTO)"
                def mid_title_lbl():
                    return "⚙️ CENTROCAMPO" if is_classic else "⚙️ CENTROCAMPO & TREQUARTI"
                for section_name, section_players in [
                    ("🧤 PORTIERE", por_line),
                    (def_title_lbl(), def_line),
                    (mid_title_lbl(), mid_line),
                    ("⚽ ATTACCO", att_line)
                ]:
                    if section_players:
                        st.markdown(f"**{section_name}**")
                        cols = st.columns(len(section_players))
                        for idx, p in enumerate(section_players):
                            with cols[idx]:
                                fdr = p['FDR']
                                fdr_class = f"badge-fdr-{fdr}"
                                slot = p.get('Slot_Assegnato', '')
                                
                                pct_suff = float(p.get('Pct_Sufficienza', 0.0))
                                df_badge = str(p.get('D_Factor_Badge', ''))
                                mv_stag = float(p.get('MV_Stagione', 6.0))
                                
                                if slot in ['Por', 'P']:
                                    save_pct = float(p.get('Pct_Parate', 70.0))
                                    gp = float(p.get('Goals_Prevented', 0.0))
                                    metric_html = f'<div style="font-size: 0.78rem; color: #38bdf8; margin-top: 3px;">🧤 Parate: <b>{save_pct:.0f}%</b> | Gol Evitati: <b>{gp:+.1f}</b></div>'
                                elif any(r in slot for r in ['Dc', 'Dd', 'Ds', 'B', 'D']):
                                    metric_html = f'<div style="font-size: 0.78rem; color: #93c5fd; margin-top: 3px;">🛡️ Suff: <b>{pct_suff:.0f}%</b> | MV: <b>{mv_stag:.2f}</b></div>'
                                elif any(r in slot for r in ['E', 'M']):
                                    kp = float(p.get('Key_Passes_90', 0.0))
                                    metric_html = f'<div style="font-size: 0.78rem; color: #93c5fd; margin-top: 3px;">🛡️ Suff: <b>{pct_suff:.0f}%</b> | KP: <b>{kp:.1f}/90</b></div>'
                                elif any(r in slot for r in ['W', 'T', 'C']):
                                    kp = float(p.get('Key_Passes_90', 0.0))
                                    xa = float(p.get('xA_90', 0.0))
                                    metric_html = f'<div style="font-size: 0.78rem; color: #c4b5fd; margin-top: 3px;">🎯 KP: <b>{kp:.1f}/90</b> | xA/90: <b>{xa:.2f}</b></div>'
                                else:
                                    tiri = float(p.get('Tiri_90', 0.0))
                                    xg = float(p.get('xG_90', 0.0))
                                    metric_html = f'<div style="font-size: 0.78rem; color: #6ee7b7; margin-top: 3px;">⚽ Tiri: <b>{tiri:.1f}/90</b> | xG/90: <b>{xg:.2f}</b></div>'
                                    
                                bonus_html = ""
                                exp_gf = float(p.get('Exp_GF', 0.0))
                                exp_ass = float(p.get('Exp_ASS', 0.0))
                                if slot in ['Por', 'P']:
                                    bonus_imb = float(p.get('Bonus_Imbattibilita', 0.0))
                                    exp_gs = float(p.get('Exp_GS', 0.0))
                                    if bonus_imb > 0.05:
                                        bonus_html += f'<span style="background: #0369a1; color: #bae6fd; padding: 1px 5px; border-radius: 3px; font-size: 0.74rem; margin-right: 4px;">🛡️ CS: +{bonus_imb:.2f}</span>'
                                    bonus_html += f'<span style="background: #7f1d1d; color: #fecaca; padding: 1px 5px; border-radius: 3px; font-size: 0.74rem;">xGS: -{exp_gs:.2f}</span>'
                                else:
                                    if exp_gf >= 0.08:
                                        bonus_html += f'<span style="background: #064e3b; color: #6ee7b7; padding: 1px 5px; border-radius: 3px; font-size: 0.74rem; margin-right: 4px;">+GF: {exp_gf:.2f}</span>'
                                    if exp_ass >= 0.08:
                                        bonus_html += f'<span style="background: #4c1d95; color: #c4b5fd; padding: 1px 5px; border-radius: 3px; font-size: 0.74rem;">+ASS: {exp_ass:.2f}</span>'

                                p_voto_pct = int(float(p.get('P_Voto', 0.90)) * 100)
                                tit_badge = str(p.get('Status_Titolarita', '🟢 TITOLARE'))
                                pres_val = int(p.get('Presenze_Tot', p.get('Presenze', 0)))
                                tot_g = int(p.get('Tot_Giornate', 0) or max(pres_val, int(selected_giornata - 1) if selected_giornata > 1 else 1))
                                tot_g = max(tot_g, pres_val, 1)
                                pres_txt = f"{pres_val}/{tot_g}"
                                bal_info = str(p.get('Ballottaggio_Info', '')).strip()
                                bal_line = f'<div style="font-size: 0.75rem; color: #fbbf24; margin-top: 2px;">⚖️ {bal_info}</div>' if bal_info else ''
                                tit_html = f'<div style="font-size: 0.78rem; color: #94a3b8; margin-top: 2px;">{tit_badge} • <b>{p_voto_pct}%</b> ({pres_txt} pres)</div>{bal_line}'
                                bonus_block = f'<div style="margin-top: 3px;">{bonus_html}</div>' if bonus_html else ''
                                
                                card_html = (
                                    f'<div class="player-card">'
                                    f'<div style="display: flex; justify-content: space-between; align-items: center;">'
                                    f'<strong style="color: #00f0ff; font-size: 1.05rem; text-shadow: 0 0 10px rgba(0, 240, 255, 0.4);">[{p["Slot_Assegnato"]}] {p["Giocatore"]}</strong>'
                                    f'<span class="{fdr_class}">FDR {fdr}</span>'
                                    f'</div>'
                                    f'<div style="font-size: 0.86rem; color: #f1f5f9; margin-top: 3px; font-weight: 600;">'
                                    f'{p["Squadra"]} vs <b>{p["Match"]}</b>'
                                    f'</div>'
                                    f'{tit_html}'
                                    f'{metric_html}'
                                    f'{bonus_block}'
                                    f'<hr style="margin: 6px 0; border: none; border-top: 1.5px solid #132d4e;">'
                                    f'<div style="display: flex; justify-content: space-between; font-size: 0.90rem; color: #f8fafc;">'
                                    f'<span>Voto: <b>{p["Pred_Voto"]}</b></span>'
                                    f'<span style="color: #00f0ff; font-weight: 900; font-size: 1.12rem; text-shadow: 0 0 12px rgba(0, 240, 255, 0.6);">xFV: {p["xFV"]}</span>'
                                    f'</div>'
                                    f'</div>'
                                )
                                st.markdown(card_html, unsafe_allow_html=True)

                st.markdown("---")
                st.markdown("**🟡 Panchina Consigliata (Ordine 1-12)**")
                st.dataframe(df_bench_display, hide_index=True, width='stretch')

            st.markdown("---")
            st.caption("🔬 **Approfondimenti & Strumenti Avanzati di Giornata** *(clicca per espandere)*:")

            # 1. Tactical Rationale Expander (Collapsed by Default)
            with st.expander("🔍 Perché l'AI ha scelto questi 11 titolari? (Analisi Dati Reali & Ballottaggi)", expanded=False):
                st.markdown("""
                L'algoritmo seleziona la formazione valutando le **metriche reali specifiche per ciascun ruolo**
                e confrontando la resa attesa contro l'avversario di giornata:
                """)
                analysis_rows = []
                for t in titolari_list:
                    slot_n = t['Slot_Assegnato']
                    tiri_v = float(t.get('Tiri_90', 0.0))
                    xg_v = float(t.get('xG_90', 0.0))
                    kp_v = float(t.get('Key_Passes_90', 0.0))
                    xa_v = float(t.get('xA_90', 0.0))
                    exp_gf_v = float(t.get('Exp_GF', 0.0))
                    exp_ass_v = float(t.get('Exp_ASS', 0.0))
                    suff_v = float(t.get('Pct_Sufficienza', 0.0))
                    mv_v = float(t.get('MV_Stagione', 6.0))
                    
                    if slot_n in ['Por', 'P']:
                        cs_p = int(t.get('Clean_Sheet_Prob', 0)*100)
                        imb_b = float(t.get('Bonus_Imbattibilita', 0.0))
                        parate_p = float(t.get('Pct_Parate', 70.0))
                        def_xga = float(t.get('Team_xGA', 1.40))
                        exp_gs = float(t.get('Exp_GS', 1.0))
                        gp = float(t.get('Goals_Prevented', 0.0))
                        gp90 = float(t.get('Goals_Prevented_90', 0.0))
                        blunders = int(t.get('Errors_Leading_To_Goal', 0))
                        blunder_txt = f"{blunders} blunders" if blunders > 0 else "0 errori decisivi"
                        metrica_chiave = f"🧤 Goals Prevented: {gp:+.2f} ({gp90:+.2f}/90) | Parate: {parate_p:.1f}% | {blunder_txt}"
                        impatto_bonus = f"Imbattibilità: +{imb_b:.2f} pt (xGS: -{exp_gs:.2f}) | CS: {cs_p}%"
                        motivo = f"Shot-stopping ({gp:+.2f} gol evitati vs PSxG, {parate_p:.1f}% parate) e tenuta difensiva ({def_xga:.2f} xGA contro {t['Match']})."
                    elif any(r in slot_n for r in ['Dc', 'Dd', 'Ds', 'B', 'D']):
                        metrica_chiave = f"🛡️ Sufficienza: {suff_v:.1f}% (>=6) | MV: {mv_v:.2f}"
                        impatto_bonus = f"{'Modificatore Difesa' if is_classic else 'D-Factor Reparto'} (Voto atteso: {t['Pred_Voto']})"
                        motivo = f"Pilastro difensivo: garantisce costanza di voto ({suff_v:.1f}% >= 6)."
                    elif any(r in slot_n for r in ['E', 'M']):
                        metrica_chiave = f"🛡️ Suff: {suff_v:.1f}% | KP: {kp_v:.1f}/90 | xA: {xa_v:.2f}"
                        impatto_bonus = f"+ASS: {exp_ass_v:.2f} | Filtro reparto"
                        motivo = f"Equilibrio difensivo ({suff_v:.1f}% sufficienze) con spinta in costruzione ({kp_v:.1f} passaggi chiave/90)."
                    elif any(r in slot_n for r in ['W', 'T', 'C']):
                        metrica_chiave = f"🎯 KP: {kp_v:.1f}/90 | xA: {xa_v:.2f} | MV: {mv_v:.2f}"
                        impatto_bonus = f"+ASS: {exp_ass_v:.2f} | +GF: {exp_gf_v:.2f}"
                        motivo = f"Generatore di bonus: produce {kp_v:.1f} occasioni e {xa_v:.2f} assist attesi/90 contro {t['Match']}."
                    else:
                        metrica_chiave = f"⚽ Tiri: {tiri_v:.1f}/90 | xG: {xg_v:.2f} | MV: {mv_v:.2f}"
                        impatto_bonus = f"+GF: {exp_gf_v:.2f} (Bonus +3 atteso)"
                        motivo = f"Finalizzatore primario: alto volume offensivo ({tiri_v:.1f} tiri e {xg_v:.2f} xG/90)."

                    p_voto_val = int(float(t.get('P_Voto', 0.90)) * 100)
                    stat_tit = t.get('Status_Titolarita', '🟢 TITOLARE')
                    mins_avg = int(t.get('Min_Per_App', 0))
                    bal_t = t.get('Ballottaggio_Info', '')
                    pres_tot = int(t.get('Presenze_Tot', t.get('Presenze', 0)))
                    tot_g = int(t.get('Tot_Giornate', 0) or max(pres_tot, int(selected_giornata - 1) if selected_giornata > 1 else 1))
                    tot_g = max(tot_g, pres_tot, 1)
                    tit_display = f"{stat_tit} | P(Voto): {p_voto_val}% ({pres_tot}/{tot_g} • {mins_avg}'/g)"
                    if bal_t:
                        tit_display += f" • ⚖️ {bal_t}"

                    analysis_rows.append({
                        'Slot': slot_n,
                        'Calciatore': t['Giocatore'],
                        'Squadra': t['Squadra'],
                        'Avversario (FDR)': f"{t['Match']} (FDR {t['FDR']})",
                        'Titolarità P(Voto)': tit_display,
                        'Metrica Chiave': metrica_chiave,
                        'Bonus Atteso': impatto_bonus,
                        'Voto Atteso': t['Pred_Voto'],
                        'xFV': t['xFV'],
                        'Razionale Tattico': motivo
                    })
                st.dataframe(pd.DataFrame(analysis_rows), width='stretch', hide_index=True)

                if 'Panchina' in opt_res and opt_res['Panchina']:
                    st.markdown("---")
                    st.markdown("##### ⚖️ Ballottaggi Chiave Decisi dall'Algoritmo (Chi è rimasto fuori e perché)")
                    ballottaggi = []
                    por_tit = [t for t in titolari_list if t['Slot_Assegnato'] in ['Por', 'P']]
                    por_bench = [b for b in opt_res['Panchina'] if ('Por' in b.get('RuoloMantra', '')) or (b.get('RuoloClassic') == 'P')]
                    if por_tit and por_bench:
                        pt = por_tit[0]
                        pb = por_bench[0]
                        diff = round(float(pt.get('xFV', 0)) - float(pb.get('xFV', 0)), 2)
                        ballottaggi.append(
                            f"🧤 **Portiere**: **{pt['Giocatore']}** ({pt['xFV']} xFV) preferito a **{pb['Giocatore']}** ({pb['xFV']} xFV, diff: +{diff} pt) "
                            f"per miglior proiezione complessiva contro {pt.get('Match')}."
                        )
                    if is_classic:
                        att_tits = [t for t in titolari_list if t.get('Slot_Assegnato') == 'A']
                        att_bench = [b for b in opt_res['Panchina'] if b.get('RuoloClassic') == 'A']
                        if att_tits and att_bench:
                            lowest_tit_att = min(att_tits, key=lambda x: float(x.get('xFV', 0)))
                            first_bench_att = att_bench[0]
                            diff_att = round(float(lowest_tit_att.get('xFV', 0)) - float(first_bench_att.get('xFV', 0)), 2)
                            ballottaggi.append(
                                f"⚽ **Reparto Attacco**: **{lowest_tit_att['Giocatore']}** ({lowest_tit_att['xFV']} xFV) "
                                f"preferito a **{first_bench_att['Giocatore']}** ({first_bench_att['xFV']} xFV, diff: {diff_att:+} pt)."
                            )
                    else:
                        att_tits = [t for t in titolari_list if any(r in t.get('Slot_Assegnato', '') for r in ['Pc', 'A', 'W', 'W/A', 'A/Pc'])]
                        att_bench = [b for b in opt_res['Panchina'] if any(r in parse_mantra_roles(b.get('RuoloMantra', '')) for r in ['Pc', 'A', 'W', 'W/T'])]
                        if att_tits and att_bench:
                            lowest_tit_att = min(att_tits, key=lambda x: float(x.get('xFV', 0)))
                            first_bench_att = att_bench[0]
                            diff_att = round(float(lowest_tit_att.get('xFV', 0)) - float(first_bench_att.get('xFV', 0)), 2)
                            ballottaggi.append(
                                f"⚽ **Reparto Offensivo**: **{lowest_tit_att['Giocatore']}** ({lowest_tit_att['xFV']} xFV) "
                                f"ha superato **{first_bench_att['Giocatore']}** ({first_bench_att['xFV']} xFV, diff: {diff_att:+} pt) "
                                f"nel modulo **{opt_res['Modulo']}**."
                            )
                    for b_text in ballottaggi:
                        st.markdown(f"- {b_text}")

            # 2. Probable Lineups & Field Notes Table (Collapsed by Default)
            with st.expander("📋 Tabellone Probabili Formazioni, Ballottaggi & Ultime dai Campi (La Tua Rosa)", expanded=False):
                prob_rows = []
                for _, prow in df_my_proj.iterrows():
                    p_info_det = prow.get('Dettaglio_Indisponibile', '') or prow.get('Ballottaggio_Info', '') or 'Nessun ballottaggio segnalato'
                    prob_rows.append({
                        'Giocatore': prow['Giocatore'],
                        'Squadra': prow['Squadra'],
                        'Ruolo': prow.get('RuoloClassic' if is_classic else 'RuoloMantra', ''),
                        'Partita': f"{prow['Match']} (FDR {prow['FDR']})",
                        'Stato & Consenso': prow.get('Status_Titolarita', ''),
                        'P(Voto) Modello': f"{int(float(prow.get('P_Voto', 0))*100)}%",
                        'xFV': prow.get('xFV', 0.0),
                        'Ballottaggi / Note Mediche': p_info_det,
                        'Ultime dai Campi': prow.get('Nota_Campo', '')
                    })
                st.dataframe(pd.DataFrame(prob_rows), width='stretch', hide_index=True)

            # 3. Interactive Substitution Simulator & Modules Comparison (Collapsed by Default)
            with st.expander(f"🛡️ Simulatore Sostituzioni & Confronto Altri Moduli {'Classic' if is_classic else 'Mantra'}", expanded=False):
                st.markdown("##### 🎮 Simulatore Interattivo Forfait / S.V. in Tempo Reale")
                starter_options = [t['Giocatore'] for t in titolari_list]
                sim_absent = st.multiselect(
                    "Simula assenza di uno o più titolari:",
                    options=starter_options,
                    default=[],
                    help="Seleziona fino a 5 titolari per testare chi subentra e quale modulo viene configurato."
                )
                if sim_absent:
                    if is_classic:
                        sim_result = simulate_classic_substitutions(
                            titolari_list, opt_res['Panchina'], opt_res['Modulo'], max_subs=5, simulated_missing_names=sim_absent
                        )
                    else:
                        sim_result = simulate_master_substitutions(
                            titolari_list, opt_res['Panchina'], opt_res['Modulo'], max_subs=5, simulated_missing_names=sim_absent
                        )
                    st.markdown(f"**Esito Simulazione: {sim_result['Cambi_Effettuati']} cambi effettuati su {len(sim_absent)} assenze simulate**")
                    for idx, sub in enumerate(sim_result['Sostituzioni']):
                        if '✅' in sub['Status']:
                            st.success(
                                f"**Cambio #{idx+1}**: Esce **{sub['Out']}** ({sub['Out_Slot']}) ➔ "
                                f"Subentra **{sub['In']}** (Pos #{sub['In_Pos']} - `{sub['In_Roles']}`). _{sub['Dettaglio']}_"
                            )
                        else:
                            st.error(f"**Cambio #{idx+1}**: Esce **{sub['Out']}** ({sub['Out_Slot']}) ➔ **{sub['In']}**. _{sub['Dettaglio']}_")
                    col_mod1, col_mod2, col_mod3 = st.columns(3)
                    col_mod1.metric("Modulo di Partenza", opt_res['Modulo'])
                    col_mod2.metric("Modulo Finale in Campo", sim_result['Modulo_Finale'])
                    all_covered = (sim_result['Cambi_Effettuati'] == len(sim_absent))
                    col_mod3.metric("Stato Formazione", "✅ Modulo Legale Completo" if all_covered else "⚠️ Squadra Incompleta")

                st.markdown("---")
                st.markdown(f"##### 📊 Confronto con gli altri moduli {'Classic' if is_classic else 'Mantra'} valutati")
                df_all_moduli = pd.DataFrame(opt_res['Tutti_Moduli_Valutati'])
                display_cols = ['Modulo', 'Punti_Totali', 'Delta_vs_Top', 'Stato_Copertura', 'xFV_Titolari', 'D_Factor', 'Punti_Robusti']
                cols_to_show = [c for c in display_cols if c in df_all_moduli.columns]
                st.dataframe(df_all_moduli[cols_to_show], width='stretch', hide_index=True)

# =============================================================
with tab_rosa:
    meta_roster = get_league_metadata()
    t_head_col1, t_head_col2 = st.columns([2.2, 1.0])
    with t_head_col1:
        st.subheader(f"📋 La Mia Rosa {'Classic' if is_classic else 'Mantra'} — {current_active_team}")
        st.caption(f"📅 Ultimo aggiornamento rose: **{meta_roster.get('last_updated')}** • Clicca su qualsiasi calciatore in tabella per aprire la scheda profilo completa.")
    with t_head_col2:
        if league_teams:
            cur_idx = league_teams.index(current_active_team) if current_active_team in league_teams else 0
            main_team_choice = st.selectbox(
                "🏆 Cambia Squadra Attiva:",
                options=league_teams,
                index=cur_idx,
                key=f"main_team_picker_{current_active_team}"
            )
            if main_team_choice != current_active_team:
                set_active_my_team(main_team_choice)
                st.rerun()
    
    # Prestiti, Infortuni & Svincoli Breakdown
    num_tot = len(df_my_roster)
    if not df_my_roster.empty and 'Stato_Disponibilita' in df_my_roster.columns:
        num_inf = len(df_my_roster[df_my_roster['Stato_Disponibilita'] == 'Infortunato'])
        num_squ = len(df_my_roster[df_my_roster['Stato_Disponibilita'] == 'Squalificato'])
    else:
        num_inf = 0
        num_squ = 0

    loans_in = df_my_roster[df_my_roster['Stato_Prestito'] == 'Prestito IN'] if 'Stato_Prestito' in df_my_roster.columns else pd.DataFrame()
    loans_out = df_my_roster[df_my_roster['Stato_Prestito'] == 'Prestito OUT'] if 'Stato_Prestito' in df_my_roster.columns else pd.DataFrame()
    out_serie_a = df_my_roster[df_my_roster['Da_Svincolare'] == True] if 'Da_Svincolare' in df_my_roster.columns else pd.DataFrame()
    num_schierabili = len(df_my_roster[df_my_roster['Schierabile'] == True]) if 'Schierabile' in df_my_roster.columns else num_tot
    if 'Categoria_Schierabile' in df_my_roster.columns:
        num_prob_titolari = len(df_my_roster[(df_my_roster['Schierabile'] == True) & (df_my_roster['Categoria_Schierabile'] == 'Probabile Titolare')])
    else:
        num_prob_titolari = num_schierabili
    costo_tot_rosa = int(df_my_roster['Costo'].sum()) if not df_my_roster.empty and 'Costo' in df_my_roster.columns else 0

    # Clean Single Row of 5 Key KPIs
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Rosa Totale</div>
            <div class="metric-val">{num_tot} <span style="font-size:0.78rem; color:#94a3b8;">({num_schierabili} disp.)</span></div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Prob. Titolari 🟢</div>
            <div class="metric-val" style="color: #4ade80;">{num_prob_titolari}</div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Indisponibili 🚑/🟥</div>
            <div class="metric-val" style="color: #f87171;">{num_inf + num_squ}</div>
        </div>
        """, unsafe_allow_html=True)
    with c4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Prestiti (IN / OUT) 🔄</div>
            <div class="metric-val" style="color: #38bdf8;">{len(loans_in)} IN · {len(loans_out)} OUT</div>
        </div>
        """, unsafe_allow_html=True)
    with c5:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Spesa Asta 💰</div>
            <div class="metric-val" style="color: #facc15;">{costo_tot_rosa} cr</div>
        </div>
        """, unsafe_allow_html=True)

    # 1. Compact Alert for Players OUTSIDE SERIE A (Da Svincolare)
    if not out_serie_a.empty:
        svincoli_tot_cr = int(out_serie_a['Costo'].sum())
        out_names = ", ".join([f"**{r['Giocatore']}** ({r['Costo']} cr)" for _, r in out_serie_a.iterrows()])
        st.warning(f"🚫 **Calciatori fuori dalla Serie A da svincolare (+{svincoli_tot_cr} cr recuperabili):** {out_names}")

    # 2. Compact Collapsible Loan Management
    cur_team_name = get_active_my_team()
    if not loans_in.empty or not loans_out.empty:
        with st.expander(f"📑 Accordi di Prestito Attivi ({len(loans_in)} in entrata, {len(loans_out)} in uscita) — Gestisci / Risolvi", expanded=False):
            col_l1, col_l2 = st.columns(2)
            with col_l1:
                st.markdown("**📥 Prestiti in Entrata (IN - Schierabili):**")
                if not loans_in.empty:
                    for _, r in loans_in.iterrows():
                        p_name_t = r['Giocatore']
                        st.markdown(f"- 📥 **{p_name_t}** ({r['RuoloClassic'] if is_classic else r['RuoloMantra']}): *{r['Dettaglio_Prestito']}*")
                        if st.button(f"🔴 Risolvi prestito di {p_name_t}", key=f"t1_term_in_{p_name_t}"):
                            ok, msg = terminate_loan(p_name_t, cur_team_name)
                            if ok:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                else:
                    st.caption("Nessun prestito in entrata.")
            with col_l2:
                st.markdown("**📤 Prestiti in Uscita (OUT - Non schierabili):**")
                if not loans_out.empty:
                    for _, r in loans_out.iterrows():
                        p_name_t = r['Giocatore']
                        borrower_t = r.get('Controparte', '')
                        st.markdown(f"- 📤 **{p_name_t}** ({r['RuoloClassic'] if is_classic else r['RuoloMantra']}): *{r['Dettaglio_Prestito']}* (asta: {r['Costo']} cr)")
                        if st.button(f"🟢 Richiama alla base {p_name_t}", key=f"t1_term_out_{p_name_t}"):
                            ok, msg = terminate_loan(p_name_t, borrower_t)
                            if ok:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
                else:
                    st.caption("Nessun prestito in uscita.")

    st.markdown("---")

    # Clean Filter Bar + Advanced Metrics Toggle
    f_col1, f_col2, f_col3 = st.columns([1.6, 1.4, 1.2])
    with f_col1:
        if is_classic:
            ruoli_filter = st.multiselect("Filtra per ruolo Classic:", options=['P', 'D', 'C', 'A'], default=[])
        else:
            ruoli_filter = st.multiselect("Filtra per ruolo Mantra:", options=['Por', 'Dc', 'B', 'Dd', 'Ds', 'E', 'M', 'C', 'W', 'T', 'A', 'Pc'], default=[])
    with f_col2:
        stato_filter = st.selectbox(
            "Filtra per stato:",
            options=[
                "TUTTI",
                "SOLO SCHIERABILI (TUTTI)",
                "🟢 SOLO PROBABILI TITOLARI",
                "🪑 SOLO PROBABILI PANCHINARI",
                "🔄 TUTTI I PRESTITI (IN & OUT)",
                "🚑 INFORTUNATI / SQUALIFICATI",
                "🚫 FUORI SERIE A (DA SVINCOLARE)"
            ],
            index=0
        )
    with f_col3:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        show_adv_cols = st.checkbox("🔬 Mostra metriche avanzate (xG, Tiri, KP)", value=False, key="chk_rosa_adv_cols")
    
    display_df = df_my_roster.copy()
    if ruoli_filter:
        if is_classic:
            display_df = display_df[display_df['RuoloClassic'].isin(ruoli_filter)]
        else:
            pattern = '|'.join(ruoli_filter)
            display_df = display_df[display_df['RuoloMantra'].str.contains(pattern, na=False)]
        
    if stato_filter in ("SOLO SCHIERABILI", "SOLO SCHIERABILI (TUTTI)") and 'Schierabile' in display_df.columns:
        display_df = display_df[display_df['Schierabile'] == True]
    elif stato_filter == "🟢 SOLO PROBABILI TITOLARI" and 'Categoria_Schierabile' in display_df.columns:
        display_df = display_df[(display_df['Schierabile'] == True) & (display_df['Categoria_Schierabile'] == 'Probabile Titolare')]
    elif stato_filter == "🪑 SOLO PROBABILI PANCHINARI" and 'Categoria_Schierabile' in display_df.columns:
        display_df = display_df[(display_df['Schierabile'] == True) & (display_df['Categoria_Schierabile'] == 'Probabile Panchinaro')]
    elif stato_filter == "🔄 TUTTI I PRESTITI (IN & OUT)" and 'Stato_Prestito' in display_df.columns:
        display_df = display_df[display_df['Stato_Prestito'].isin(['Prestito IN', 'Prestito OUT'])]
    elif stato_filter == "🚑 INFORTUNATI / SQUALIFICATI" and 'Stato_Disponibilita' in display_df.columns:
        display_df = display_df[display_df['Stato_Disponibilita'].isin(['Infortunato', 'Squalificato', 'In dubbio'])]
    elif stato_filter == "🚫 FUORI SERIE A (DA SVINCOLARE)" and 'Da_Svincolare' in display_df.columns:
        display_df = display_df[display_df['Da_Svincolare'] == True]
        
    role_col = 'RuoloClassic' if is_classic else 'RuoloMantra'
    base_cols = [
        'Badge_Disponibilita', 'Giocatore', 'Squadra', role_col, 'Costo', 'Presenze',
        'MV_Stagione', 'FM_Stagione', 'GF', 'ASS', 'Badge_Rientro'
    ]
    if not loans_in.empty or not loans_out.empty:
        base_cols.insert(1, 'Badge_Prestito')
    if show_adv_cols:
        adv_extra = ['Pct_Sufficienza', 'MV_Ultime3', 'Tiri_90', 'xG_90', 'Delta_xG', 'Key_Passes_90', 'xA_90', 'Pct_Parate', 'Goals_Prevented', 'Signal']
        cols_to_show = [c for c in (base_cols + adv_extra) if c in display_df.columns]
    else:
        cols_to_show = [c for c in base_cols if c in display_df.columns]
    
    sorted_display = display_df.sort_values(by=[role_col, 'Costo'], ascending=[True, False]).reset_index(drop=True)

    # Interactive Table with on_select (Click row -> Modal Profile)
    table_event = st.dataframe(
        sorted_display[cols_to_show],
        width='stretch',
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"roster_table_{active_league}_{current_active_team}"
    )

    clicked_player = None
    if table_event and hasattr(table_event, 'selection'):
        sel_rows = table_event.selection.get('rows', [])
        if sel_rows and len(sel_rows) > 0:
            r_idx = sel_rows[0]
            if r_idx < len(sorted_display):
                clicked_player = sorted_display.iloc[r_idx]['Giocatore']

    if clicked_player:
        if st.session_state.get('active_dialog_player') != clicked_player:
            st.session_state['active_dialog_player'] = clicked_player
            show_player_profile_dialog(
                clicked_player,
                df_master,
                calendar=calendar,
                matchday=selected_giornata,
                df_roster=df_my_roster
            )
        else:
            if st.button(f"🔍 Riapri Scheda Profilo: {clicked_player}", type="primary", key="btn_reopen_dlg"):
                show_player_profile_dialog(
                    clicked_player,
                    df_master,
                    calendar=calendar,
                    matchday=selected_giornata,
                    df_roster=df_my_roster
                )
    
    exp_c1, exp_c2, _ = st.columns([1, 1, 2])
    with exp_c1:
        st.download_button(
            "📥 Scarica Rosa in CSV",
            data=display_df[cols_to_show].to_csv(index=False),
            file_name=f"mia_rosa_{'classic' if is_classic else 'mantra'}.csv",
            mime="text/csv"
        )
    with exp_c2:
        st.download_button(
            "📥 Backup Rosa (JSON)",
            data=json.dumps(user_squad_names, indent=2, ensure_ascii=False),
            file_name="user_roster.json",
            mime="application/json"
        )

# =============================================================
with tab_scambi:
    st.subheader(f"🔄 Trade Center & Ottimizzazione Scambi {'Classic' if is_classic else 'Mantra'}")
    st.caption(
        "Valuta qualsiasi scambio con il modello ibrido a 4 pilastri, scopri le proposte Win-Win automatiche o cerca un obiettivo specifico."
    )
    
    subtab_sim, subtab_radar, subtab_target, subtab_diag = st.tabs([
        "⚖️ Valutatore Scambio Libero",
        "🤝 Proposte Automatiche (Win-Win)",
        "🎯 Cerca un Obiettivo",
        "🏥 Diagnosi Rosa & Esuberi"
    ])

    # -------------------------------------------------------------
    # SUBTAB 1: DIAGNOSI PUNTI DEBOLI & ASSET
    # -------------------------------------------------------------
    with subtab_diag:
        st.subheader("🏥 Check-up Strutturale & Analisi Carenze di Modulo")
        st.caption(
            f"L'algoritmo analizza la distribuzione dei ruoli {'Classic' if is_classic else 'Mantra'}, i giocatori con presenze continuative, "
            "la qualità media e la copertura del D-Factor per evidenziare rischi di squilibrio tattico."
        )
        
        my_team = get_active_my_team()
        diag_teams = league_teams if league_teams else [my_team]
        col_sel_d1, col_sel_d2 = st.columns([2, 1])
        with col_sel_d1:
            target_diag_team = st.selectbox(
                "Squadra da Analizzare:",
                options=diag_teams,
                index=diag_teams.index(my_team) if my_team in diag_teams else 0,
                key=f"diag_team_select_{my_team}"
            )
        with col_sel_d2:
            st.write("")
            st.caption(f"Squadra attiva dell'utente: **{my_team}**")
            
        diag_res = cached_analyze_squad_weaknesses(
            target_diag_team, _league_signature(league_dict, active_league_type),
            selected_giornata, current_code_version, league_dict, df_master,
            league_type=active_league_type
        )
        
        if 'error' in diag_res:
            st.error(diag_res['error'])
        else:
            # Top KPIs
            dk1, dk2, dk3, dk4 = st.columns(4)
            with dk1:
                st.metric("Modulo Benchmark Titolare", diag_res.get('Modulo_Titolare', 'N/D'))
            with dk2:
                st.metric("Punti Attesi Titolari (xFV)", f"{diag_res.get('Punti_Titolari', 0.0):.2f} pt")
            with dk3:
                num_w = len(diag_res.get('Punti_Deboli', []))
                st.metric("Punti Deboli Rilevati", num_w, delta="Attenzione" if num_w > 0 else "Nessuno", delta_color="inverse")
            with dk4:
                num_s = len(diag_res.get('Surplus_Cedibili', []))
                st.metric("Asset Spendibili (Esuberi)", num_s)
                
            st.markdown("---")
            
            # Punti Deboli Section
            st.subheader("🚨 Punti Deboli & Bottleneck Strutturali")
            weaknesses = diag_res.get('Punti_Deboli', [])
            if not weaknesses:
                st.success("✅ Congratulazioni! La rosa presenta una struttura bilanciata in tutti i reparti chiave.")
            else:
                for w in weaknesses:
                    sev = w.get('Severita', 'MEDIA')
                    bg_color = {
                        'CRITICA': '#450a0a',
                        'ELEVATA': '#431407',
                        'MEDIA': '#422006'
                    }.get(sev, '#1e293b')
                    border_color = {
                        'CRITICA': '#ef4444',
                        'ELEVATA': '#f97316',
                        'MEDIA': '#eab308'
                    }.get(sev, '#64748b')
                    badge_color = {
                        'CRITICA': '#ef4444',
                        'ELEVATA': '#f97316',
                        'MEDIA': '#eab308'
                    }.get(sev, '#64748b')
                    
                    st.markdown(f"""
                    <div style="background: {bg_color}; border-left: 5px solid {border_color}; border-radius: 8px; padding: 14px 18px; margin-bottom: 14px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <span style="font-weight: 700; font-size: 1.05rem; color: #f8fafc;">
                                {w['Reparto']} ({w['Ruolo']}) — {w['Titolo']}
                            </span>
                            <span style="background: {badge_color}; color: white; padding: 3px 9px; border-radius: 12px; font-weight: 700; font-size: 0.75rem;">
                                {sev}
                            </span>
                        </div>
                        <p style="margin: 4px 0 8px 0; color: #cbd5e1; font-size: 0.92rem;">{w['Diagnosi']}</p>
                        <div style="font-size: 0.88rem; color: #38bdf8; font-weight: 600;">
                            🎯 Obiettivo di Mercato: {w['Obiettivo_Mercato']}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
            # Punti di Forza
            strengths = diag_res.get('Punti_di_Forza', [])
            if strengths:
                with st.expander("⭐ Punti di Forza & Certezze della Rosa", expanded=False):
                    for s in strengths:
                        st.markdown(f"- ✅ **{s}**")
                        
            # Surplus Assets Table
            st.markdown("---")
            st.subheader("💰 Asset Spendibili sul Mercato (Esuberi di Fanta-Valore)")
            st.caption(
                "Calciatori di valore (o con segnale SELL-HIGH) che attualmente siedono in panchina o fanno parte "
                "di reparti sovraffollati. Sono la tua moneta di scambio ideale da offrire per colmare i punti deboli sopra evidenziati."
            )
            surplus = diag_res.get('Surplus_Cedibili', [])
            if surplus:
                df_surplus = pd.DataFrame(surplus)
                s_role_col = 'RuoloClassic' if is_classic and 'RuoloClassic' in df_surplus.columns else 'RuoloMantra'
                st.dataframe(
                    df_surplus[['Giocatore', s_role_col, 'Squadra', 'xFV', 'FM_Stagione', 'Signal', 'Motivo_Cessione']],
                    width='stretch',
                    hide_index=True
                )
            else:
                st.info("Nessun calciatore di rilievo attualmente in esubero.")
                
            # Quota Coverage Matrix
            with st.expander(f"📐 Matrice di Copertura Ruoli {'Classic' if is_classic else 'Mantra'} (Quote Consigliate vs Attivi)", expanded=False):
                matrix_rows = []
                c_all = diag_res.get('Conteggio_Totale', {})
                c_act = diag_res.get('Conteggio_Attivi', {})
                is_two_striker_mod = diag_res.get('Is_Two_Striker_Modulo', False)
                quotas_to_show = RECOMMENDED_QUOTAS_CLASSIC if is_classic else RECOMMENDED_QUOTAS
                for role, q in quotas_to_show.items():
                    act = c_act.get(role, 0)
                    tot = c_all.get(role, 0)
                    min_q = q['min_active']
                    tgt = q['target']
                    if role == 'Pc' and not is_classic and not is_two_striker_mod:
                        min_q = 2
                    
                    if act < min_q:
                        status = "🚨 Carente"
                    elif act == min_q:
                        status = "⚠️ Al Minimo"
                    elif act >= tgt + 2:
                        status = "➕ Esubero"
                    else:
                        status = "✅ Coperto"
                        
                    matrix_rows.append({
                        'Ruolo': role,
                        'Descrizione': q['name'],
                        'Attivi (Disponibili & Voto Sicuro)': act,
                        'Totali in Rosa': tot,
                        'Minimo Consigliato': min_q,
                        'Target Ideale': tgt,
                        'Stato Copertura': status
                    })
                st.dataframe(pd.DataFrame(matrix_rows), width='stretch', hide_index=True)

    # -------------------------------------------------------------
    # SUBTAB 2: RADAR SCAMBI INTELLIGENTI (WIN-WIN)
    # -------------------------------------------------------------
    with subtab_radar:
        st.subheader("🤝 Radar Scambi Intelligenti (Win-Win Reciproco)")
        st.markdown(
            "L'algoritmo incrocia la diagnosi della tua squadra con le rose di tutti gli 11 avversari di lega. "
            "Identifica opportunità a **somma positiva** dove tu cedi un giocatore spendibile e ricevi un elemento che "
            "risolve un tuo punto debole, garantendo allo stesso tempo all'avversario un titolare nel reparto in cui è scoperto."
        )
        
        my_team = get_active_my_team()
        
        # Pre-compute diagnosi for filters
        my_diag = cached_analyze_squad_weaknesses(
            my_team, _league_signature(league_dict, active_league_type),
            selected_giornata, current_code_version, league_dict, df_master,
            league_type=active_league_type
        )
        my_weak_roles = [w['Ruolo'] for w in my_diag.get('Punti_Deboli', [])]
        surplus_pnames = [p['Giocatore'] for p in my_diag.get('Surplus_Cedibili', [])]
        
        r_col1, r_col2, r_col3, r_col4, r_col5 = st.columns([1.1, 1.1, 1.2, 1.3, 1.3])
        with r_col1:
            all_roles = ['P', 'D', 'C', 'A'] if is_classic else ['Por', 'Dc', 'B', 'Dd', 'Ds', 'E', 'M', 'C', 'W', 'T', 'A', 'Pc']
            target_role_opts = ["TUTTI"] + list(dict.fromkeys(my_weak_roles + all_roles))
            selected_target_role = st.selectbox(
                "Ruolo che vuoi RICEVERE:",
                options=target_role_opts,
                index=1 if my_weak_roles else 0,
                key=f"trade_winwin_role_{my_team}",
                help="Seleziona il ruolo che intendi rinforzare. Di default è impostato sulla tua priorità debole principale."
            )
        with r_col2:
            give_opts = ["TUTTI"] + surplus_pnames
            selected_give_player = st.selectbox(
                "Calciatore che vuoi CEDERE:",
                options=give_opts,
                index=0,
                key=f"trade_winwin_give_{my_team}",
                help="Puoi filtrare per un tuo specifico esubero o lasciare TUTTI per esplorare tutte le combinazioni."
            )
        with r_col3:
            opp_opts = ["TUTTI"] + [t for t in league_teams if t != my_team]
            selected_opp_team = st.selectbox(
                "Filtra per Squadra Avversaria:",
                options=opp_opts,
                index=0,
                key=f"trade_winwin_opp_{my_team}",
                help="Scegli se trattare con un avversario specifico o scansionare l'intera lega."
            )
        with r_col4:
            format_filter_map = {
                "🎯 Tutti i Formati (1x1, 2x2, 2x1, 1x2)": "TUTTI",
                "🔄 Solo Scambi Multipli (2x2, 2x1, 1x2)": "SOLO_MULTIPLI",
                "⚖️ Solo Scambi Singoli (1x1)": "SOLO_SINGOLI"
            }
            selected_format_label = st.selectbox(
                "Formato Scambio:",
                options=list(format_filter_map.keys()),
                index=0,
                key=f"trade_winwin_fmt_{my_team}",
                help="Scegli se vedere tutti i formati, oppure focalizzarti su scambi singoli (1x1) o pacchetti multipli (combo titolari + riserve, 2x1, 1x2)."
            )
            selected_format_filter = format_filter_map[selected_format_label]
        with r_col5:
            starter_filter_map = {
                "🟡 Titolari + Co-Titolari (>40 min/p) [Consigliato]": "TITOLARI_E_CO",
                "🟢 Solo Titolari Fissi (>55 min/p)": "TITOLARI_SOLO",
                "🟠 Tutti (incluse riserve/subentranti)": "TUTTI"
            }
            selected_starter_label = st.selectbox(
                "Filtro Minutaggio Reale Serie A:",
                options=list(starter_filter_map.keys()),
                index=0,
                help="Esclude automaticamente riserve e subentranti occasionali (es. Lucca, Nzola, Kevin Carlos)."
            )
            selected_starter_filter = starter_filter_map[selected_starter_label]
            
        # Run search
        with st.spinner("Scansione rose avversarie e calcolo scambi Win-Win in corso..."):
            try:
                proposals = cached_find_win_win_trades(
                    my_team, _league_signature(league_dict, active_league_type), selected_giornata,
                    selected_target_role, selected_give_player, selected_opp_team,
                    selected_starter_filter, selected_format_filter, 30,
                    current_code_version, league_dict, df_master,
                    league_type=active_league_type
                )
            except TypeError:
                # Fallback for cached or legacy function signatures
                try:
                    proposals = find_win_win_trades(
                        my_team_name=my_team,
                        league_data=league_dict,
                        df_master=df_master,
                        matchday=selected_giornata,
                        target_role_filter=selected_target_role,
                        give_player_filter=selected_give_player,
                        opp_team_filter=selected_opp_team,
                        min_starter_filter=selected_starter_filter,
                        max_proposals=30,
                        league_type=active_league_type
                    )
                except Exception as inner_e:
                    import traceback
                    st.error(f"Errore durante l'elaborazione degli scambi: {inner_e}")
                    st.code(traceback.format_exc())
                    proposals = []
            except Exception as e:
                import traceback
                st.error(f"Errore durante l'elaborazione degli scambi: {e}")
                st.code(traceback.format_exc())
                proposals = []
            
        if not proposals:
            st.warning("Nessuna proposta Win-Win trovata con i filtri correnti. Prova a impostare 'TUTTI' nei filtri per allargare la ricerca.")
        else:
            st.success(f"🎯 Trovate **{len(proposals)} proposte di scambio Win-Win** su misura per la tua rosa!")
            
            for idx, prop in enumerate(proposals[:15], 1):
                opp = prop['Squadra_Avversaria']
                score = prop['Score']
                give_list = prop.get('Tu_Cedi_List', [prop['Tu_Cedi']])
                rec_list = prop.get('Tu_Ricevi_List', [prop['Tu_Ricevi']])
                label_tipo = prop.get('Label_Tipo', '⚖️ Scambio Diretto (1x1)')
                tipo_scambio = prop.get('Tipo_Scambio', '1x1')
                tot_c_give = prop.get('Tot_Costo_Cedi', sum(safe_int(p.get('Costo', 0)) for p in give_list))
                tot_c_rec = prop.get('Tot_Costo_Ricevi', sum(safe_int(p.get('Costo', 0)) for p in rec_list))
                tot_x_give = prop.get('Tot_xFV_Cedi', round(sum(safe_float(p.get('xFV', 0.0)) for p in give_list), 2))
                tot_x_rec = prop.get('Tot_xFV_Ricevi', round(sum(safe_float(p.get('xFV', 0.0)) for p in rec_list), 2))
                delta_xfv = prop.get('Delta_xFV', round(tot_x_rec - tot_x_give, 2))
                
                with st.container():
                    st.markdown(f"""
                    <div style="background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 16px 20px; margin-bottom: 18px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid #334155; padding-bottom: 8px;">
                            <div>
                                <span style="font-size: 1.15rem; font-weight: 700; color: #f8fafc;">#{idx} Proposta con: <span style="color: #38bdf8;">{opp}</span></span>
                                <span style="margin-left: 8px; background: #6366f1; color: white; padding: 2px 8px; border-radius: 6px; font-size: 0.78rem; font-weight: 600;">{label_tipo}</span>
                                <span style="margin-left: 6px; background: #0284c7; color: white; padding: 2px 8px; border-radius: 6px; font-size: 0.78rem; font-weight: 600;">Ruolo: {prop['Ruolo_Target']}</span>
                            </div>
                            <div>
                                <span style="background: #10b981; color: white; padding: 4px 10px; border-radius: 12px; font-weight: 700; font-size: 0.85rem;">
                                    Win-Win Index: {int(safe_float(score, 50.0))} / 200
                                </span>
                            </div>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    # Columns for Cedi and Ricevi
                    c_give, c_rec = st.columns(2)
                    with c_give:
                        n_g = len(give_list)
                        st.markdown(f"""
                        <div style="font-size: 0.82rem; color: #ef4444; font-weight: bold; text-transform: uppercase; margin-bottom: 6px;">
                            🔴 Tu Cedi ({n_g} calciator{'e' if n_g == 1 else 'i'}) | Tot FVM/1000: <b>{tot_c_give}</b> | Tot xFV: <b>{tot_x_give:.2f}</b>
                        </div>
                        """, unsafe_allow_html=True)
                        for cedi in give_list:
                            sig_badge = f"<span style='background:#f97316;color:white;padding:1px 6px;border-radius:4px;font-size:0.75rem;font-weight:bold;'>{cedi.get('Signal', '')}</span>" if 'SELL-HIGH' in cedi.get('Signal', '') else ""
                            role_disp_give = cedi.get('RuoloClassic' if is_classic else 'RuoloMantra', cedi.get('RuoloMantra', ''))
                            st.markdown(f"""
                            <div style="background: rgba(239, 68, 68, 0.08); border-left: 4px solid #ef4444; padding: 10px 14px; border-radius: 6px; margin-bottom: 8px;">
                                <div style="font-size: 1.05rem; font-weight: bold; color: #f8fafc;">
                                    {cedi['Giocatore']} {sig_badge}
                                    <span style="font-size: 0.78rem; color: #94a3b8; font-weight: normal;">(FVM: <b>{cedi.get('FVM', cedi.get('Costo', 0))}</b>)</span>
                                </div>
                                <div style="color: #cbd5e1; font-size: 0.85rem;">{cedi['Squadra']} — <b>{role_disp_give}</b></div>
                                <div style="color: #94a3b8; font-size: 0.80rem; margin-top: 2px;">xFV Giornata: <b>{cedi['xFV']:.2f}</b> | FM: <b>{cedi['FM']:.2f}</b></div>
                            </div>
                            """, unsafe_allow_html=True)
                        
                    with c_rec:
                        delta_color = "#10b981" if delta_xfv >= 0 else "#f59e0b"
                        n_r = len(rec_list)
                        st.markdown(f"""
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <span style="font-size: 0.82rem; color: #10b981; font-weight: bold; text-transform: uppercase;">
                                🟢 Tu Ricevi ({n_r} calciator{'e' if n_r == 1 else 'i'}) | Tot FVM/1000: <b>{tot_c_rec}</b>
                            </span>
                            <span style="color: {delta_color}; font-weight: bold; font-size: 0.85rem;">
                                Delta: {'+' if delta_xfv > 0 else ''}{delta_xfv} xFV
                            </span>
                        </div>
                        """, unsafe_allow_html=True)
                        for ricevi in rec_list:
                            sig_rec_badge = f"<span style='background:#0284c7;color:white;padding:1px 6px;border-radius:4px;font-size:0.75rem;font-weight:bold;'>BUY-LOW</span>" if ricevi.get('Is_Buy_Low') else ""
                            bench_badge = "<span style='background:#475569;color:white;padding:1px 6px;border-radius:4px;font-size:0.75rem;'>Panchina Avversaria</span>" if ricevi.get('Is_Bench_In_Opponent') else ""
                            status_tit = ricevi.get('Status_Titolarita', 'TITOLARE')
                            tit_color = {
                                'TITOLARE': '#16a34a',
                                'CO_TITOLARE': '#ca8a04',
                                'SUBENTRANTE': '#ea580c',
                                'MARGINALE': '#dc2626'
                            }.get(status_tit, '#64748b')
                            tit_badge = f"<span style='background:{tit_color};color:white;padding:1px 6px;border-radius:4px;font-size:0.75rem;font-weight:bold;'>{ricevi.get('Badge_Titolarita', status_tit)}</span>"
                            stash_badge = f"<span style='background:#d97706;color:white;padding:1px 6px;border-radius:4px;font-size:0.75rem;font-weight:bold;'>🩹 STASH INFORTUNIO</span>" if ricevi.get('Is_Stash_Injury') else ""

                            role_disp_rec = ricevi.get('RuoloClassic' if is_classic else 'RuoloMantra', ricevi.get('RuoloMantra', ''))
                            st.markdown(f"""
                            <div style="background: rgba(16, 185, 129, 0.08); border-left: 4px solid #10b981; padding: 10px 14px; border-radius: 6px; margin-bottom: 8px;">
                                <div style="font-size: 1.05rem; font-weight: bold; color: #f8fafc;">
                                    {ricevi['Giocatore']} {tit_badge} {stash_badge} {sig_rec_badge} {bench_badge}
                                    <span style="font-size: 0.78rem; color: #94a3b8; font-weight: normal;">(FVM: <b>{ricevi.get('FVM', ricevi.get('Costo', 0))}</b>)</span>
                                </div>
                                <div style="color: #cbd5e1; font-size: 0.85rem;">{ricevi['Squadra']} — <b>{role_disp_rec}</b></div>
                                <div style="color: #94a3b8; font-size: 0.80rem; margin-top: 2px;">
                                    xFV Giornata: <b>{ricevi['xFV']:.2f}</b> | FM: <b>{ricevi['FM']:.2f}</b> | Sufficienze: <b>{ricevi.get('Pct_Sufficienza', 0)}%</b>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                        
                    st.markdown("<div style='margin-top: 10px; font-weight: 600; font-size: 0.9rem; color: #e2e8f0;'>💡 Perché ha senso per entrambi:</div>", unsafe_allow_html=True)
                    for m in prop['Motivazioni']:
                        st.markdown(f"<div style='font-size: 0.85rem; color: #94a3b8; margin-left: 8px;'>• {m}</div>", unsafe_allow_html=True)
                        
                    # WhatsApp Pitch Box
                    st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
                    with st.expander("💬 Messaggio Pronto da Inviare su WhatsApp", expanded=False):
                        st.caption("Copia e incolla direttamente nella chat privata o di lega con il tuo avversario:")
                        st.code(prop['Messaggio_Trattativa'], language="text")
                        
                    # Action button to prefill simulator
                    btn_col1, btn_col2 = st.columns([1, 3])
                    with btn_col1:
                        if st.button(f"⚖️ Simula nel Valutatore", key=f"btn_sim_{idx}"):
                            g_names = [p['Giocatore'] for p in give_list]
                            r_names = [p['Giocatore'] for p in rec_list]
                            st.session_state['sim_prefill_give'] = g_names
                            st.session_state['sim_prefill_receive'] = r_names
                            st.session_state['sim_prefill_opp'] = opp
                            st.session_state['sim_prefill_mode'] = "🤝 Trattativa di Lega (Inter-Squadra)"
                            st.session_state['sim_last_trade_res'] = evaluate_trade(
                                g_names, r_names, df_master, start_matchday=selected_giornata, horizon=None, calendar=calendar
                            )
                            st.success(f"✅ Scambio con {opp} caricato e calcolato! Clicca sulla scheda '⚖️ Valutatore Scambio Libero' per il verdetto completo.")
                            
                    st.markdown("</div>", unsafe_allow_html=True)

    # -------------------------------------------------------------
    # SUBTAB 3: SCAMBIO MIRATO SU OBIETTIVO (REVERSE TRADE FINDER)
    # -------------------------------------------------------------
    with subtab_target:
        st.subheader("🎯 Scambio Mirato su Obiettivo (Reverse Trade Finder)")
        st.markdown(
            "Cerca uno o più calciatori che desideri strappare a un avversario di lega. "
            "L'algoritmo valuta l'**intera rosa senza discriminazioni** (titolari, panchinari ed esuberi) "
            "e formula pacchetti d'offerta **molti-a-molti (1x1, 2x1, 1x2, 2x2, 3x2, 2x3, 3x3...)** "
            "rigorosamente **migliorativi** per la tua formazione titolare e credibili per l'avversario."
        )

        my_team = get_active_my_team()
        opp_team_candidates = [t for t in league_teams if t != my_team]

        if not opp_team_candidates:
            st.info("Carica le rose della tua lega nella sidebar o nel wizard per attivare la funzione di scambio mirato.")
        else:
            col_sel_opp, col_sel_targs = st.columns([1, 2])
            with col_sel_opp:
                target_opp_team = st.selectbox(
                    "1. Seleziona Squadra Avversaria:",
                    options=opp_team_candidates,
                    key=f"target_finder_opp_team_{my_team}"
                )

            # Get target opponent roster (exclude loans and players to release / out of Serie A)
            opp_roster_df = get_team_roster_df(target_opp_team, df_master)
            mask_opp = pd.Series(True, index=opp_roster_df.index)
            if 'InPrestito' in opp_roster_df.columns:
                mask_opp &= ~opp_roster_df['InPrestito'].astype(bool)
            if 'Da_Svincolare' in opp_roster_df.columns:
                mask_opp &= ~opp_roster_df['Da_Svincolare'].astype(bool)
            if 'FuoriSerieA' in opp_roster_df.columns:
                mask_opp &= ~opp_roster_df['FuoriSerieA'].astype(bool)
            if 'Giocatore' in opp_roster_df.columns:
                mask_opp &= ~opp_roster_df['Giocatore'].astype(str).str.contains(r'\*')
            opp_owned_df = opp_roster_df[mask_opp]
            sort_cols = [c for c in ['Costo', 'FM_Stagione', 'MV_Stagione'] if c in opp_owned_df.columns]
            if sort_cols:
                opp_owned_df = opp_owned_df.sort_values(by=sort_cols, ascending=[False] * len(sort_cols))

            # Prepare player options
            opp_player_labels = []
            label_to_pname = {}
            for _, r_opp in opp_owned_df.iterrows():
                pname = r_opp['Giocatore']
                roles = r_opp.get('RuoloClassic' if is_classic else 'RuoloMantra', '')
                costo = int(r_opp.get('Costo', 0))
                fm = float(r_opp.get('FM_Stagione', 0.0))
                label = f"{pname} ({roles}) — {r_opp.get('Squadra', '')} [Costo {costo}, FM {fm:.2f}]"
                opp_player_labels.append(label)
                label_to_pname[label] = pname

            with col_sel_targs:
                selected_labels = st.multiselect(
                    "2. Scegli il/i Giocatore/i da Chiedere all'Avversario:",
                    options=opp_player_labels,
                    key=f"target_finder_selected_players_{my_team}",
                    help="Puoi selezionare un singolo obiettivo (es. una prima punta, un top difensore) o un pacchetto di 2 giocatori."
                )
                selected_target_pnames = [label_to_pname[lbl] for lbl in selected_labels]

            # Format Selector (Many-to-Many M x N)
            pkg_size_label = st.selectbox(
                "Formato Pacchetto Scambio:",
                options=[
                    "Tutti i formati Molti-a-Molti (1x1, 2x1, 1x2, 2x2, 3x2, 2x3, 3x3)",
                    "Solo Scambio Singolo Diretto (1x1)",
                    "Solo Pacchetti Multipli (M x N: 2x1, 1x2, 2x2, 3x2, 2x3, 3x3)"
                ],
                index=0,
                key=f"target_finder_pkg_size_{my_team}",
                help="Gli scambi possono coinvolgere qualsiasi combinazione molti-a-molti senza limiti. Vengono proposte offerte rigorosamente migliorative per la tua rosa."
            )
            pkg_types_map = {
                "Tutti i formati Molti-a-Molti (1x1, 2x1, 1x2, 2x2, 3x2, 2x3, 3x3)": 'ALL',
                "Solo Scambio Singolo Diretto (1x1)": 'SOLO_1X1',
                "Solo Pacchetti Multipli (M x N: 2x1, 1x2, 2x2, 3x2, 2x3, 3x3)": 'SOLO_MULTIPLI'
            }
            chosen_pkg_types = pkg_types_map[pkg_size_label]

            # Show Instant Rival Check-up Card
            with st.expander(f"🔍 Check-up Immediato Carenze di {target_opp_team} (Perché dovrebbero accettare)", expanded=False):
                opp_diag = cached_analyze_squad_weaknesses(
                    target_opp_team, _league_signature(league_dict, active_league_type),
                    selected_giornata, current_code_version, league_dict, df_master,
                    league_type=active_league_type
                )
                opp_w = opp_diag.get('Punti_Deboli', [])
                if opp_w:
                    st.markdown(f"**Criticità emerse nella rosa di {target_opp_team}:**")
                    for w in opp_w:
                        sev_badge = "🔴" if w['Severita'] == 'CRITICA' else ("🟠" if w['Severita'] == 'ELEVATA' else "🟡")
                        st.markdown(f"- {sev_badge} **{w['Reparto']} ({w['Ruolo']})**: {w['Diagnosi']} *({w['Obiettivo_Mercato']})*")
                else:
                    st.info(f"{target_opp_team} ha una rosa numericamente completa; accetterà scambi basati su valore tecnico e affinità tattica.")

            st.markdown("---")

            # Execution
            if not selected_target_pnames:
                st.info("👆 Seleziona almeno un calciatore dal menu a tendina sopra per generare le proposte di offerta su misura.")
            else:
                with st.spinner("Analisi delle criticità dell'avversario e formulazione offerte intelligenti in corso..."):
                    try:
                        target_proposals = find_trades_for_target_players(
                            my_team_name=my_team,
                            opp_team_name=target_opp_team,
                            target_player_names=selected_target_pnames,
                            league_data=league_dict,
                            df_master=df_master,
                            matchday=selected_giornata,
                            package_types=chosen_pkg_types,
                            league_type=active_league_type
                        )
                    except Exception as e:
                        st.error(f"Errore durante l'elaborazione delle proposte per {', '.join(selected_target_pnames)}: {e}")
                        target_proposals = []

                if not target_proposals:
                    st.warning(
                        f"Nessuna combinazione molti-a-molti trovata per acquisire **{', '.join(selected_target_pnames)}** "
                        "che risulti sia migliorativa per la tua rosa sia appetibile e sostenibile per l'avversario. "
                        "Prova a selezionare una rosa o un obiettivo differente."
                    )
                else:
                    st.success(f"🎯 Trovate **{len(target_proposals)} proposte di scambio migliorative** per acquisire **{', '.join(selected_target_pnames)}**!")

                    for p_idx, prop in enumerate(target_proposals):
                        delta_pts = prop['Delta_Punti_Titolari']
                        is_migliorativo = (delta_pts >= 0)
                        card_border = "#10b981" if is_migliorativo else "#38bdf8"
                        card_bg = "rgba(16, 185, 129, 0.06)" if is_migliorativo else "rgba(56, 189, 248, 0.05)"
                        fmt_badge = prop.get('Formato', prop.get('Tipo_Pacchetto', 'M x N'))
                        
                        st.markdown(f"""
                        <div style="background: {card_bg}; border: 1.5px solid {card_border}; border-radius: 10px; padding: 16px 20px; margin-bottom: 20px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                                <div>
                                    <span style="font-weight: 800; font-size: 1.15rem; color: #ffffff;">Offerta #{p_idx+1}</span>
                                    <span style="margin-left: 10px; background: rgba(56, 189, 248, 0.15); border: 1px solid #38bdf8; border-radius: 6px; padding: 3px 10px; font-weight: 800; font-size: 0.85rem; color: #38bdf8;">
                                        {fmt_badge}
                                    </span>
                                    <span style="margin-left: 6px; background: rgba(16, 185, 129, 0.15); border: 1px solid #10b981; border-radius: 6px; padding: 3px 10px; font-weight: 800; font-size: 0.85rem; color: #34d399;">
                                        📈 +{delta_pts:.2f} pt attesi
                                    </span>
                                </div>
                                <div style="display: flex; gap: 12px; align-items: center;">
                                    <span style="font-weight: 700; font-size: 0.95rem; color: #f59e0b;">🎯 Appetibilità Avversario: {prop['Appetibilita_Avversario']}%</span>
                                </div>
                            </div>
                        """, unsafe_allow_html=True)

                        col_give, col_rec = st.columns(2)
                        with col_give:
                            st.markdown("##### 🔴 Cosa Cedi Tu")
                            for p in prop['Tu_Cedi']:
                                role_display = p.get('RuoloClassic' if is_classic else 'RuoloMantra', p.get('Ruolo', ''))
                                st.markdown(f"""
                                <div style="background: rgba(255,255,255,0.04); border-left: 3px solid #38bdf8; padding: 8px 12px; border-radius: 6px; margin-bottom: 6px;">
                                    <div style="font-weight: 700; color: #ffffff;">{p['Giocatore']} <span style="font-weight: 450; color: #94a3b8; font-size: 0.85rem;">({role_display} - {p['Squadra']})</span></div>
                                    <div style="font-size: 0.8rem; color: #cbd5e1;">FM: <strong>{p['FM']:.2f}</strong> | xFV: <strong>{p['xFV']:.2f}</strong> | FVM: <strong>{p.get('FVM', p.get('Costo', 0))}</strong></div>
                                </div>
                                """, unsafe_allow_html=True)
                            st.caption(f"Totale xFV Offerto: **{prop['Totale_xFV_Ceduti']}**")

                        with col_rec:
                            st.markdown(f"##### 🟢 Cosa Ricevi da {target_opp_team}")
                            for p in prop['Tu_Ricevi']:
                                role_display = p.get('RuoloClassic' if is_classic else 'RuoloMantra', p.get('Ruolo', ''))
                                st.markdown(f"""
                                <div style="background: rgba(16, 185, 129, 0.08); border-left: 3px solid #10b981; padding: 8px 12px; border-radius: 6px; margin-bottom: 6px;">
                                    <div style="font-weight: 700; color: #ffffff;">{p['Giocatore']} <span style="font-weight: 450; color: #94a3b8; font-size: 0.85rem;">({role_display} - {p['Squadra']})</span></div>
                                    <div style="font-size: 0.8rem; color: #cbd5e1;">FM: <strong>{p['FM']:.2f}</strong> | xFV: <strong>{p['xFV']:.2f}</strong> | FVM: <strong>{p.get('FVM', p.get('Costo', 0))}</strong></div>
                                </div>
                                """, unsafe_allow_html=True)
                            st.caption(f"Totale xFV Ricevuto: **{prop['Totale_xFV_Ricevuti']}** (Δ xFV: **{prop['Delta_xFV']:+.2f}**)")

                        # Tactical rationale & opponent leverage
                        st.markdown("<div style='margin-top: 10px; font-weight: 700; font-size: 0.92rem; color: #38bdf8;'>💡 Perché l'avversario accetta (Leva di Trattativa):</div>", unsafe_allow_html=True)
                        st.markdown(f"<div style='font-size: 0.88rem; color: #cbd5e1; margin-bottom: 6px;'>{prop['Leva_di_Trattativa']}</div>", unsafe_allow_html=True)

                        col_imp1, col_imp2 = st.columns(2)
                        with col_imp1:
                            st.markdown(f"""
                            <div style='background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 8px 12px; margin-bottom: 8px;'>
                                <div style='font-size: 0.78rem; text-transform: uppercase; color: #94a3b8; font-weight: 700;'>📊 La Tua Formazione Titolare</div>
                                <div style='font-size: 0.95rem; font-weight: 700; color: #ffffff; margin: 2px 0;'>
                                    {prop['Punti_Titolari_Nuovi']:.2f} pt <span style='font-size: 0.85rem; color: {'#10b981' if prop['Delta_Punti_Titolari'] >= 0 else '#f97316'};'>({prop['Delta_Punti_Titolari']:+.2f} pt)</span>
                                </div>
                                <div style='font-size: 0.8rem; color: #94a3b8;'>Modulo {prop['Modulo_Titolare_Nuovo']} • {prop['Copertura_Nuova']}</div>
                            </div>
                            """, unsafe_allow_html=True)

                        with col_imp2:
                            opp_pts_txt = f"{prop.get('Punti_Avversario_Nuovi', 0):.2f} pt"
                            opp_delta_val = prop.get('Delta_Punti_Avversario', 0)
                            opp_delta_txt = f"{opp_delta_val:+.2f} pt"
                            opp_delta_color = "#10b981" if opp_delta_val >= 0 else "#f59e0b"
                            opp_mod = prop.get('Modulo_Avversario_Nuovo', 'N/D')
                            reassure_msg = prop['Reassurances_Avversario'][0] if prop.get('Reassurances_Avversario') else "✅ Nessuna nuova criticità creata per l'avversario"

                            st.markdown(f"""
                            <div style='background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; padding: 8px 12px; margin-bottom: 8px;'>
                                <div style='font-size: 0.78rem; text-transform: uppercase; color: #94a3b8; font-weight: 700;'>👔 Formazione {target_opp_team} Post-Scambio</div>
                                <div style='font-size: 0.95rem; font-weight: 700; color: #ffffff; margin: 2px 0;'>
                                    {opp_pts_txt} <span style='font-size: 0.85rem; color: {opp_delta_color};'>({opp_delta_txt})</span>
                                </div>
                                <div style='font-size: 0.8rem; color: #4ade80;'>Modulo {opp_mod} • {reassure_msg}</div>
                            </div>
                            """, unsafe_allow_html=True)

                        # Pairwise Matching & Titolarita Breakdown
                        pairs = prop.get('Accoppiamento_Coppie', [])
                        if pairs and len(pairs) >= 1:
                            with st.expander("⚖️ Dettaglio Accoppiamento a Coppie & Titolarità Reale (Vasi Comunicanti)", expanded=False):
                                st.caption("Ogni calciatore richiesto viene confrontato direttamente con una contropartita di pari status. Il minutaggio e la titolarità reale pesano il valore di mercato effettivo.")
                                for p_match in pairs:
                                    g_pct = int(p_match['give_itit'] * 100)
                                    t_pct = int(p_match['target_itit'] * 100)
                                    d_val = p_match['delta']
                                    d_color = "#10b981" if d_val >= 0 else "#f59e0b"
                                    st.markdown(f"""
                                    <div style='background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 6px; padding: 6px 12px; margin-bottom: 5px; font-size: 0.88rem; display: flex; justify-content: space-between; align-items: center;'>
                                        <div>
                                            🔴 <strong>{p_match['give_name']}</strong> (Titolarità {g_pct}%, {int(p_match.get('give_mins', 0))} min/p)
                                            &nbsp;⇄&nbsp;
                                            🟢 <strong>{p_match['target_name']}</strong> (Titolarità {t_pct}%, {int(p_match.get('target_mins', 0))} min/p)
                                        </div>
                                        <div>
                                            <span style='color: {d_color}; font-weight: 700;'>Δ Valore Effettivo: {d_val:+.2f}</span>
                                        </div>
                                    </div>
                                    """, unsafe_allow_html=True)
                                st.caption(f"Valore Mercato Effettivo Complessivo: Offerto **{prop.get('Valore_Mercato_Ceduti', 0):.2f}** vs Richiesto **{prop.get('Valore_Mercato_Ricevuti', 0):.2f}** (Δ **{prop.get('Delta_Valore_Mercato', 0):+.2f}**)")

                        # WhatsApp Box
                        with st.expander("💬 Messaggio Pronto da Inviare su WhatsApp all'Avversario", expanded=False):
                            st.caption("Copia e incolla direttamente nella chat per proporre lo scambio:")
                            st.code(prop['Messaggio_Trattativa'], language="text")

                        # Prefill Simulator Button
                        if st.button(f"⚖️ Simula nel Valutatore", key=f"btn_sim_target_{p_idx}"):
                            g_names_t = prop['Simulazione_Payload']['give_names']
                            r_names_t = prop['Simulazione_Payload']['receive_names']
                            st.session_state['sim_prefill_give'] = g_names_t
                            st.session_state['sim_prefill_receive'] = r_names_t
                            st.session_state['sim_prefill_opp'] = target_opp_team
                            st.session_state['sim_prefill_mode'] = "🤝 Trattativa di Lega (Inter-Squadra)"
                            st.session_state['sim_last_trade_res'] = evaluate_trade(
                                g_names_t, r_names_t, df_master, start_matchday=selected_giornata, horizon=None, calendar=calendar
                            )
                            st.success("✅ Scambio caricato e calcolato! Clicca sulla scheda '⚖️ Valutatore Scambio Libero' per il verdetto completo.")

                        st.markdown("</div>", unsafe_allow_html=True)

    # -------------------------------------------------------------
    # SUBTAB 4: SIMULATORE SCAMBI LIBERO
    # -------------------------------------------------------------
    @st.fragment
    def render_free_trade_simulator():
        """Rendered as a fragment: changing team/players reruns only this block, not the whole app."""
        st.subheader("⚖️ Simulatore Scambi Libero (1v1, 2v2, Pacchetti)")
        st.markdown(
            "Simula qualsiasi scambio. L'algoritmo proietta il valore atteso "
            "delle prossime giornate incrociando **calendario, fattore casa/trasferta, difficoltà avversari (FDR) e segnali Buy-Low / Sell-High**."
        )
    
        # Check prefill from radar
        prefill_mode = st.session_state.get('sim_prefill_mode', "🤝 Trattativa di Lega (Inter-Squadra)")
        prefill_give = st.session_state.get('sim_prefill_give', [])
        prefill_receive = st.session_state.get('sim_prefill_receive', [])
        prefill_opp = st.session_state.get('sim_prefill_opp', None)
    
        trade_mode = st.radio(
            "Modalità di Selezione Scambio:",
            options=["🤝 Trattativa di Lega (Inter-Squadra)", "🔍 Ricerca Libera (Tutta la Serie A)"],
            index=0 if prefill_mode == "🤝 Trattativa di Lega (Inter-Squadra)" else 1,
            horizontal=True,
            key="sim_trade_mode_radio"
        )
    
        give_selection = []
        receive_selection = []
    
        if trade_mode == "🤝 Trattativa di Lega (Inter-Squadra)" and league_teams:
            col_sc1, col_sc2 = st.columns(2)
            my_team = get_active_my_team()
            with col_sc1:
                st.subheader(f"🔴 La Tua Squadra ({my_team})")
                my_team_df = get_team_roster_df(my_team, df_master)
                # Exclude borrowed players and players to release from tradeable give list
                my_mask = pd.Series(True, index=my_team_df.index)
                if 'InPrestito' in my_team_df.columns:
                    my_mask &= ~my_team_df['InPrestito'].astype(bool)
                if 'Da_Svincolare' in my_team_df.columns:
                    my_mask &= ~my_team_df['Da_Svincolare'].astype(bool)
                if 'FuoriSerieA' in my_team_df.columns:
                    my_mask &= ~my_team_df['FuoriSerieA'].astype(bool)
                if 'Giocatore' in my_team_df.columns:
                    my_mask &= ~my_team_df['Giocatore'].astype(str).str.contains(r'\*')
                my_team_owned = my_team_df[my_mask]
                my_team_players = sorted(my_team_owned['Giocatore'].unique().tolist())
                valid_prefill_give = [p for p in prefill_give if p in my_team_players]
                give_selection = st.multiselect(
                    f"Calciatori di {my_team} che proponi di Cedere:",
                    options=my_team_players,
                    default=valid_prefill_give,
                    key=f"sim_multiselect_give_{my_team}"
                )
            with col_sc2:
                opp_teams = [t for t in league_teams if t != my_team]
                opp_index = opp_teams.index(prefill_opp) if (prefill_opp and prefill_opp in opp_teams) else 0
                selected_opp = st.selectbox(
                    "Seleziona Squadra della Lega con cui trattare:",
                    options=opp_teams,
                    index=opp_index,
                    key=f"sim_selectbox_opp_{my_team}"
                )
                st.subheader(f"🟢 Rosa Avversaria ({selected_opp})")
                opp_team_df = get_team_roster_df(selected_opp, df_master)
                # Exclude borrowed players and players to release from opponent receive list
                opp_mask = pd.Series(True, index=opp_team_df.index)
                if 'InPrestito' in opp_team_df.columns:
                    opp_mask &= ~opp_team_df['InPrestito'].astype(bool)
                if 'Da_Svincolare' in opp_team_df.columns:
                    opp_mask &= ~opp_team_df['Da_Svincolare'].astype(bool)
                if 'FuoriSerieA' in opp_team_df.columns:
                    opp_mask &= ~opp_team_df['FuoriSerieA'].astype(bool)
                if 'Giocatore' in opp_team_df.columns:
                    opp_mask &= ~opp_team_df['Giocatore'].astype(str).str.contains(r'\*')
                opp_team_owned = opp_team_df[opp_mask]
                opp_team_players = sorted(opp_team_owned['Giocatore'].unique().tolist())
                valid_prefill_rec = [p for p in prefill_receive if p in opp_team_players]
                receive_selection = st.multiselect(
                    f"Calciatori di {selected_opp} che chiedi in cambio:",
                    options=opp_team_players,
                    default=valid_prefill_rec,
                    key=f"sim_multiselect_receive_{my_team}"
                )
        else:
            col_sc1, col_sc2 = st.columns(2)
            with col_sc1:
                st.subheader("🔴 Calciatori che CEDI")
                all_pnames = sorted(df_master['Giocatore'].unique())
                valid_p_give = [p for p in prefill_give if p in all_pnames]
                if not valid_p_give and user_squad_names:
                    valid_p_give = [user_squad_names[0]]
                give_selection = st.multiselect(
                    "Seleziona calciatore/i dalla tua rosa (o da tutta la Serie A):",
                    options=all_pnames,
                    default=valid_p_give,
                    key="sim_multiselect_give_all"
                )
            
            with col_sc2:
                st.subheader("🟢 Calciatori che RICEVI")
                available_targets = [p for p in df_master['Giocatore'].unique() if p not in give_selection]
                valid_p_rec = [p for p in prefill_receive if p in available_targets]
                if not valid_p_rec and 'Martinez L.' in available_targets:
                    valid_p_rec = ['Martinez L.']
                receive_selection = st.multiselect(
                    "Seleziona calciatore/i che riceveresti in cambio:",
                    options=sorted(available_targets),
                    default=valid_p_rec,
                    key="sim_multiselect_receive_all"
                )
        
        col_hor1, col_hor2 = st.columns([1, 1])
        with col_hor1:
            rem_giornate = max(1, 38 - selected_giornata + 1)
            st.markdown(
                f"""
                <div style="background: rgba(15, 23, 42, 0.65); border: 1px solid #334155; border-radius: 8px; padding: 10px 14px; margin-top: 2px;">
                    <div style="font-size: 0.78rem; text-transform: uppercase; color: #94a3b8; font-weight: 700; letter-spacing: 0.5px;">📅 Orizzonte di Valutazione</div>
                    <div style="font-size: 0.95rem; color: #38bdf8; font-weight: 700; margin-top: 2px;">
                        Resto della Stagione: {rem_giornate} turni ({selected_giornata}ª ➔ 38ª Giornata)
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
        with col_hor2:
            weight_mode_label = st.selectbox(
                "Metodo Valutazione Pacchetto Multiplo:",
                options=[
                    "⚖️ Media Ponderata Decrescente (Consigliata: Priorità Star)",
                    "📊 Media Semplice (Tutti i calciatori equiparati)",
                    "➕ Somma Grezza (Cumulativa semplice)"
                ],
                index=0,
                key="sim_weight_mode_select",
                help="Negli scambi a pacchetto multiplo (es. 2v1 o 4v4), la media ponderata bilancia i valori normalizzandoli a livello di singolo slot titolare evitando che la pura somma condanni ingiustamente gli scambi asimmetrici."
            )
            weight_mode_map = {
                "⚖️ Media Ponderata Decrescente (Consigliata: Priorità Star)": "rank_decay",
                "📊 Media Semplice (Tutti i calciatori equiparati)": "simple_mean",
                "➕ Somma Grezza (Cumulativa semplice)": "raw_sum"
            }
            chosen_weight_mode = weight_mode_map[weight_mode_label]
    
        if st.button("⚡ Valuta Scambio", type="primary", key="sim_eval_button"):
            if not give_selection or not receive_selection:
                st.error("Seleziona almeno un giocatore da cedere e uno da ricevere.")
                st.session_state.pop('sim_last_trade_res', None)
            else:
                with st.spinner("Valutazione multi-algoritmo (4 Pilastri) in corso..."):
                    st.session_state['sim_last_trade_res'] = evaluate_trade(
                        give_selection,
                        receive_selection,
                        df_master,
                        start_matchday=selected_giornata,
                        horizon=None,
                        calendar=calendar,
                        weight_mode=chosen_weight_mode
                    )

        trade_res = st.session_state.get('sim_last_trade_res')
        if trade_res:
            if 'error' in trade_res:
                st.error(trade_res['error'])
            else:
                st.markdown("---")

                # 1. VERDICT HERO BANNER WITH GRADUAL NUANCES & GAUGE
                verdict_cfg = {
                    'emerald': ('#059669', 'rgba(5, 150, 105, 0.15)', 'border: 1px solid rgba(5, 150, 105, 0.5)'),
                    'green': ('#10b981', 'rgba(16, 185, 129, 0.12)', 'border: 1px solid rgba(16, 185, 129, 0.4)'),
                    'teal': ('#0d9488', 'rgba(13, 148, 136, 0.12)', 'border: 1px solid rgba(13, 148, 136, 0.4)'),
                    'lime': ('#84cc16', 'rgba(132, 204, 22, 0.12)', 'border: 1px solid rgba(132, 204, 22, 0.4)'),
                    'slate': ('#94a3b8', 'rgba(148, 163, 184, 0.10)', 'border: 1px solid rgba(148, 163, 184, 0.3)'),
                    'gray': ('#94a3b8', 'rgba(148, 163, 184, 0.10)', 'border: 1px solid rgba(148, 163, 184, 0.3)'),
                    'amber': ('#eab308', 'rgba(234, 179, 8, 0.12)', 'border: 1px solid rgba(234, 179, 8, 0.4)'),
                    'orange': ('#f97316', 'rgba(249, 115, 22, 0.12)', 'border: 1px solid rgba(249, 115, 22, 0.4)'),
                    'rose': ('#f43f5e', 'rgba(244, 63, 94, 0.12)', 'border: 1px solid rgba(244, 63, 94, 0.4)'),
                    'red': ('#ef4444', 'rgba(239, 68, 68, 0.14)', 'border: 1px solid rgba(239, 68, 68, 0.5)')
                }
                v_color, v_bg, v_border = verdict_cfg.get(trade_res.get('StatusColor', 'slate'), ('#94a3b8', 'rgba(148, 163, 184, 0.10)', 'border: 1px solid #334155'))
                is_multi_pkg = trade_res.get('Is_Multi', False)
                pkg_badge = f"Pacchetto {trade_res.get('Num_Ceduti', 1)} vs {trade_res.get('Num_Ricevuti', 1)}" if is_multi_pkg else "Scambio Singolo 1 vs 1"
                sub_title_mode = "Media Ponderata Decrescente (Priorità Star)" if chosen_weight_mode == "rank_decay" else ("Media Semplice" if chosen_weight_mode == "simple_mean" else "Somma Grezza")

                delta_tot = trade_res.get('Delta_Totale_xFV', 0.0)
                delta_p = trade_res.get('Delta_Medio_Partita', 0.0)
                delta_sign = '+' if delta_tot > 0 else ''
                delta_p_sign = '+' if delta_p > 0 else ''
                idx_conv = int(trade_res.get('Indice_Convenienza', 50))
                badge_lbl = trade_res.get('Verdict_Badge', '⚖️')
                archetipo_tit = trade_res.get('Archetipo_Titolo', '⚖️ Baratto Tattico')
                archetipo_desc = trade_res.get('Archetipo_Descrizione', '')
                tier_desc_txt = trade_res.get('Tier_Desc', '')

                st.markdown(f"""
                <div style="background: {v_bg}; {v_border}; border-radius: 12px; padding: 20px 24px; margin-top: 15px; margin-bottom: 16px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px;">
                        <div style="display: flex; gap: 8px; align-items: center;">
                            <span style="font-size: 0.80rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: {v_color}; background: rgba(0,0,0,0.25); padding: 3px 8px; border-radius: 4px;">
                                {pkg_badge} • {sub_title_mode}
                            </span>
                            <span style="font-size: 0.80rem; font-weight: 700; color: #38bdf8; background: rgba(56,189,248,0.12); padding: 3px 8px; border-radius: 4px; border: 1px solid rgba(56,189,248,0.25);">
                                {archetipo_tit}
                            </span>
                        </div>
                        <span style="font-size: 0.85rem; color: #94a3b8;">
                            Orizzonte: <b>{trade_res.get('Giornate_Valutate', 1)} turni</b> (fino alla 38ª)
                        </span>
                    </div>
                    <h2 style="color: {v_color}; margin: 2px 0 8px 0; font-size: 1.85rem; font-weight: 800; letter-spacing: -0.5px;">
                        {badge_lbl} — {trade_res.get('Verdetto', 'VALUTAZIONE')}
                    </h2>
                    <div style="color: #f1f5f9; font-size: 1.05rem; line-height: 1.45; margin-bottom: 14px; font-weight: 500;">
                        {trade_res.get('Sintesi_Umana', '')}
                    </div>

                    <!-- Gradual Convenience Gauge (0 - 100) -->
                    <div style="background: rgba(15, 23, 42, 0.45); border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; border: 1px solid rgba(255,255,255,0.06);">
                        <div style="display: flex; justify-content: space-between; font-size: 0.85rem; font-weight: 700; color: #cbd5e1; margin-bottom: 6px;">
                            <span>Indice di Convenienza dello Scambio:</span>
                            <span style="color: {v_color}; font-size: 0.95rem;"><b>{idx_conv} / 100</b> <span style="font-weight: 400; color: #94a3b8; font-size: 0.82rem;">({tier_desc_txt})</span></span>
                        </div>
                        <div style="background: rgba(15, 23, 42, 0.9); border-radius: 999px; height: 10px; width: 100%; overflow: hidden; border: 1px solid rgba(255,255,255,0.12);">
                            <div style="background: {v_color}; height: 100%; width: {idx_conv}%; border-radius: 999px;"></div>
                        </div>
                    </div>

                    <div style="display: flex; gap: 20px; align-items: center; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.08); font-size: 0.92rem; flex-wrap: wrap;">
                        <div>
                            <span style="color: #94a3b8;">Differenziale Totale:</span> 
                            <b style="color: {v_color}; font-size: 1.08rem; margin-left: 4px;">{delta_sign}{delta_tot:.1f} xFV</b>
                        </div>
                        <div style="color: #64748b;">•</div>
                        <div>
                            <span style="color: #94a3b8;">Impatto Medio a Gara:</span> 
                            <b style="color: {v_color}; font-size: 1.08rem; margin-left: 4px;">{delta_p_sign}{delta_p:.2f} xFV/partita</b>
                        </div>
                        <div style="color: #64748b;">•</div>
                        <div>
                            <span style="color: #94a3b8;">Sfumatura Tattica:</span> 
                            <span style="color: #e2e8f0; font-style: italic; margin-left: 4px;">{archetipo_desc}</span>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # Strategic Conditions & Tactical Guidelines
                conds = trade_res.get('Condizioni_Strategiche', [])
                if conds:
                    st.markdown(f"""
                    <div style="background: rgba(30, 41, 59, 0.65); border: 1px solid #334155; border-left: 4px solid {v_color}; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px;">
                        <div style="font-weight: 700; color: #f8fafc; font-size: 0.92rem; margin-bottom: 6px;">
                            💡 Il Consiglio Strategico del Modello (Condizioni Chiave per Concludere):
                        </div>
                    """, unsafe_allow_html=True)
                    for c in conds:
                        st.markdown(f"<div style='font-size: 0.86rem; color: #cbd5e1; margin-left: 6px; margin-bottom: 4px;'>• {c}</div>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)

                # 2. CLINICAL & SUSPENSION NOTES (if any)
                if trade_res.get('Note_Cliniche'):
                    st.markdown("""
                    <div style="background: rgba(239, 68, 68, 0.08); border-left: 4px solid #ef4444; border-radius: 6px; padding: 10px 14px; margin-bottom: 18px;">
                        <div style="font-weight: 700; color: #f87171; font-size: 0.9rem; margin-bottom: 4px;">
                            🚑 Aggiornamento Infermeria & Squalifiche (Impatto sulle proiezioni):
                        </div>
                    """, unsafe_allow_html=True)
                    for nc in trade_res['Note_Cliniche']:
                        st.markdown(f"<div style='font-size: 0.85rem; color: #cbd5e1; margin-left: 10px;'>• {nc}</div>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)

                # 3. SIDE-BY-SIDE COCKPIT
                st.markdown("### 👥 Confronto Diretto Calciatori")
                def _render_cockpit_card(card, is_give=True):
                    border_accent = "#f87171" if is_give else "#4ade80"
                    bg_card = "rgba(30, 41, 59, 0.70)"
                    sig = card.get('Signal', '')
                    sig_badge = f"<span style='background:rgba(56,189,248,0.2); color:#38bdf8; font-size:0.75rem; padding:2px 6px; border-radius:4px; margin-left:6px;'>{sig}</span>" if sig else ""
                    role = card.get('RuoloClassic' if is_classic else 'RuoloMantra', card.get('RuoloMantra', ''))
                    
                    return f"""
                    <div style="background: {bg_card}; border: 1px solid #334155; border-left: 4px solid {border_accent}; border-radius: 8px; padding: 12px 14px; margin-bottom: 10px;">
                        <div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px;">
                            <div>
                                <b style="color: #f8fafc; font-size: 1.05rem;">{card.get('Giocatore')}</b>
                                <span style="color: #94a3b8; font-size: 0.85rem; margin-left: 6px;">({card.get('Squadra')} · <code style='color:#38bdf8;'>{role}</code>)</span>
                                {sig_badge}
                            </div>
                            <span style="font-size: 0.75rem; font-weight: 700; color: {card.get('Status_Color', '#10b981')}; background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 4px;">
                                {card.get('Status_Badge', 'Disponibile')}
                            </span>
                        </div>
                        <div style="font-size: 0.82rem; color: #cbd5e1; margin-bottom: 8px;">
                            {card.get('Titolarita_Label', 'Titolare')}
                        </div>
                        <div style="display: flex; gap: 8px; flex-wrap: wrap; font-size: 0.78rem;">
                            <span style="background: rgba(15,23,42,0.6); padding: 3px 7px; border-radius: 4px; color: #94a3b8;">
                                FM: <b style="color: #f1f5f9;">{card.get('FM_Stagione', 0.0):.2f}</b>
                            </span>
                            <span style="background: rgba(15,23,42,0.6); padding: 3px 7px; border-radius: 4px; color: #94a3b8;">
                                MV: <b style="color: #f1f5f9;">{card.get('MV_Stagione', 0.0):.2f}</b>
                            </span>
                            <span style="background: rgba(15,23,42,0.6); padding: 3px 7px; border-radius: 4px; color: #94a3b8;">
                                Gol/Ass: <b style="color: #f1f5f9;">{card.get('GF', 0)}G / {card.get('ASS', 0)}A</b>
                            </span>
                            <span style="background: rgba(15,23,42,0.6); padding: 3px 7px; border-radius: 4px; color: #94a3b8;">
                                Sufficienza: <b style="color: #f1f5f9;">{card.get('Pct_Sufficienza', 0.0):.0f}%</b>
                            </span>
                            <span style="background: rgba(15,23,42,0.6); padding: 3px 7px; border-radius: 4px; color: #94a3b8;">
                                FVM: <b style="color: #38bdf8;">{int(card.get('FVM', 0))}</b>
                            </span>
                        </div>
                    </div>
                    """

                c_give_col, c_rec_col = st.columns(2)
                with c_give_col:
                    st.markdown(f"**🔴 Calciatori Ceduti ({len(trade_res['Cards_Give'])})**")
                    for c in trade_res['Cards_Give']:
                        st.markdown(_render_cockpit_card(c, is_give=True), unsafe_allow_html=True)
                with c_rec_col:
                    st.markdown(f"**🟢 Calciatori Ricevuti ({len(trade_res['Cards_Rec'])})**")
                    for c in trade_res['Cards_Rec']:
                        st.markdown(_render_cockpit_card(c, is_give=False), unsafe_allow_html=True)

                # 4. 4 PILLARS CONSENSUS COCKPIT
                st.markdown("### 🏛️ I 4 Pilastri di Valutazione (Consenso Multi-Algoritmo)")
                p1 = trade_res.get('Pilastro1', {})
                p2 = trade_res.get('Pilastro2', {})
                p3 = trade_res.get('Pilastro3', {})
                p4 = trade_res.get('Pilastro4', {})

                def _pillar_badge(winner):
                    if winner == 'RICEVI':
                        return "<span style='color: #4ade80; font-weight: 700;'>🟢 Vince Ricevi</span>"
                    elif winner == 'CEDI':
                        return "<span style='color: #f87171; font-weight: 700;'>🔴 Vince Cedi</span>"
                    return "<span style='color: #94a3b8; font-weight: 700;'>⚪ Sostanziale Parità</span>"

                pil_c1, pil_c2 = st.columns(2)
                with pil_c1:
                    st.markdown(f"""
                    <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid #334155; border-radius: 8px; padding: 14px; margin-bottom: 12px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <b style="color: #38bdf8; font-size: 0.95rem;">1. {p1.get('Nome', 'Valore Netto Effettivo')} (35%)</b>
                            {_pillar_badge(p1.get('Winner', 'PARI'))}
                        </div>
                        <div style="font-size: 0.88rem; color: #f1f5f9; margin-bottom: 6px;">
                            {p1.get('Descrizione', '')}
                        </div>
                        <div style="font-size: 0.78rem; color: #94a3b8;">
                            Partite saltate per infortunio/squalifica: Ceduti: <b>{p1.get('Missed_Games_Give', 0)}</b> vs Ricevuti: <b>{p1.get('Missed_Games_Rec', 0)}</b>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    st.markdown(f"""
                    <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid #334155; border-radius: 8px; padding: 14px; margin-bottom: 12px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <b style="color: #38bdf8; font-size: 0.95rem;">3. {p3.get('Nome', 'Solidità Rosa & Garanzia Voto')} (20%)</b>
                            {_pillar_badge(p3.get('Winner', 'PARI'))}
                        </div>
                        <div style="font-size: 0.88rem; color: #f1f5f9;">
                            {p3.get('Descrizione', '')}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                with pil_c2:
                    st.markdown(f"""
                    <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid #334155; border-radius: 8px; padding: 14px; margin-bottom: 12px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <b style="color: #38bdf8; font-size: 0.95rem;">2. {p2.get('Nome', 'Momentum & Trend Recente')} (25%)</b>
                            {_pillar_badge(p2.get('Winner', 'PARI'))}
                        </div>
                        <div style="font-size: 0.88rem; color: #f1f5f9;">
                            {p2.get('Descrizione', '')}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    st.markdown(f"""
                    <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid #334155; border-radius: 8px; padding: 14px; margin-bottom: 12px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <b style="color: #38bdf8; font-size: 0.95rem;">4. {p4.get('Nome', 'Gerarchia Star & FVM')} (20%)</b>
                            {_pillar_badge(p4.get('Winner', 'PARI'))}
                        </div>
                        <div style="font-size: 0.88rem; color: #f1f5f9;">
                            {p4.get('Descrizione', '')}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                # 5. DETAILED STRATEGIC ANALYSIS
                st.markdown("### 📋 Analisi Strategica Dettagliata")
                van_col, ris_col = st.columns(2)
                with van_col:
                    st.markdown("""
                    <div style="background: rgba(16, 185, 129, 0.08); border-left: 3px solid #10b981; border-radius: 6px; padding: 10px 14px; margin-bottom: 10px;">
                        <b style="color: #34d399; font-size: 0.95rem;">🟢 Vantaggi dello Scambio:</b>
                    </div>
                    """, unsafe_allow_html=True)
                    vantaggi_list = trade_res.get('Vantaggi', [])
                    if vantaggi_list:
                        for v in vantaggi_list:
                            st.markdown(f"- {v}")
                    else:
                        st.caption("Nessun vantaggio evidente segnalato dal modello.")
                with ris_col:
                    st.markdown("""
                    <div style="background: rgba(239, 68, 68, 0.08); border-left: 3px solid #ef4444; border-radius: 6px; padding: 10px 14px; margin-bottom: 10px;">
                        <b style="color: #f87171; font-size: 0.95rem;">🔴 Rischi e Controindicazioni:</b>
                    </div>
                    """, unsafe_allow_html=True)
                    rischi_list = trade_res.get('Rischi', [])
                    if rischi_list:
                        for r in rischi_list:
                            st.markdown(f"- {r}")
                    else:
                        st.caption("Nessuna controindicazione critica segnalata dal modello.")

                # 6. COLLAPSED ADVANCED STATISTICAL EXPANDER
                with st.expander("📊 Approfondimento Statistico Completo & Proiezione Temporale (Per Esperti)", expanded=False):
                    if is_multi_pkg and chosen_weight_mode != 'raw_sum':
                        st.markdown("**🔍 Pesi e Bilanciamento del Pacchetto Multiplo:**")
                        col_pw1, col_pw2 = st.columns(2)
                        with col_pw1:
                            st.markdown("**🔴 Pesi Calciatori Ceduti:**")
                            for p, w in trade_res.get('Pesi_Ceduti', {}).items():
                                st.write(f"- **{p}**: peso `{w*100:.1f}%`")
                            st.caption(f"Somma cumulativa grezza ceduti: **{trade_res.get('xFV_Ceduti_Raw_Tot', 0)} xFV**")
                        with col_pw2:
                            st.markdown("**🟢 Pesi Calciatori Ricevuti:**")
                            for p, w in trade_res.get('Pesi_Ricevuti', {}).items():
                                st.write(f"- **{p}**: peso `{w*100:.1f}%`")
                            st.caption(f"Somma cumulativa grezza ricevuti: **{trade_res.get('xFV_Ricevuti_Raw_Tot', 0)} xFV**")
                        st.markdown("---")

                    st.markdown("**Rendimento di Partenza & FDR:**")
                    t1, t2, t3, t4 = st.columns(4)
                    with t1:
                        lbl_r = "xFV Ponderato Ricevuti" if chosen_weight_mode != "raw_sum" else "Totale xFV Ricevuti"
                        st.metric(lbl_r, f"{trade_res['xFV_Ricevuti_Tot']} pts", delta=f"{trade_res.get('xFV_Ricevuti_Medio_Partita', 0):.2f} pt/g")
                    with t2:
                        lbl_c = "xFV Ponderato Ceduti" if chosen_weight_mode != "raw_sum" else "Totale xFV Ceduti"
                        st.metric(lbl_c, f"{trade_res['xFV_Ceduti_Tot']} pts", delta=f"{trade_res.get('xFV_Ceduti_Medio_Partita', 0):.2f} pt/g")
                    with t3:
                        st.metric("FDR Medio Ricevuti", f"{trade_res['FDR_Medio_Ricevuti']} / 5")
                    with t4:
                        st.metric("FDR Medio Ceduti", f"{trade_res['FDR_Medio_Ceduti']} / 5")

                    if trade_res.get('Has_GK'):
                        tg1, tg2, tg3, tg4 = st.columns(4)
                        with tg1:
                            st.metric("Goals Prevented Ricevuti", f"{trade_res.get('GP_Ricevuti', 0.0):+.2f} ({trade_res.get('GP90_Ricevuti', 0.0):+.2f}/90)")
                        with tg2:
                            st.metric("Goals Prevented Ceduti", f"{trade_res.get('GP_Ceduti', 0.0):+.2f} ({trade_res.get('GP90_Ceduti', 0.0):+.2f}/90)")
                        with tg3:
                            bl_rec = trade_res.get('Blunders_Ricevuti', 0)
                            bl_give = trade_res.get('Blunders_Ceduti', 0)
                            st.metric("Blunders Ricevuti", f"{bl_rec} (vs {bl_give} ceduti)", delta="Attenzione" if bl_rec > bl_give else "Affidabile", delta_color="inverse")
                        with tg4:
                            st.metric("% Parate Ricevuti", f"{trade_res.get('SavePct_Ricevuti', 0.0):.1f}% (vs {trade_res.get('SavePct_Ceduti', 0.0):.1f}%)")

                    ts1, ts2, ts3, ts4 = st.columns(4)
                    with ts1:
                        st.metric("Tiri/90 Ricevuti", f"{trade_res.get('Tiri_Ricevuti_90', 0.0)} / 90")
                    with ts2:
                        st.metric("Tiri/90 Ceduti", f"{trade_res.get('Tiri_Ceduti_90', 0.0)} / 90")
                    with ts3:
                        st.metric("xG/90 Ricevuti", f"{trade_res.get('xG_Ricevuti_90', 0.0)}")
                    with ts4:
                        st.metric("xG/90 Ceduti", f"{trade_res.get('xG_Ceduti_90', 0.0)}")

                    ta1, ta2, ta3, ta4 = st.columns(4)
                    with ta1:
                        st.metric("xA/90 Ricevuti", f"{trade_res.get('xA_Ricevuti_90', 0.0)}")
                    with ta2:
                        st.metric("xA/90 Ceduti", f"{trade_res.get('xA_Ceduti_90', 0.0)}")
                    with ta3:
                        st.metric("Delta xG Ricevuti", f"{trade_res.get('Delta_xG_Ricevuti', 0.0):+.2f}", help="Negativo = Buy-low")
                    with ta4:
                        st.metric("Delta xG Ceduti", f"{trade_res.get('Delta_xG_Ceduti', 0.0):+.2f}", help="Positivo = Sell-high")

                    td1, td2, td3, td4 = st.columns(4)
                    with td1:
                        st.metric("Sufficienza D-Factor Ricevuti", f"{trade_res.get('Suff_Ricevuti_DFactor', 0.0)}%")
                    with td2:
                        st.metric("Sufficienza D-Factor Ceduti", f"{trade_res.get('Suff_Ceduti_DFactor', 0.0)}%")
                    with td3:
                        st.metric("Media Voto D-Factor Ricevuti", f"{trade_res.get('MV_Ricevuti_DFactor', 0.0)}")
                    with td4:
                        st.metric("Media Voto D-Factor Ceduti", f"{trade_res.get('MV_Ceduti_DFactor', 0.0)}")

                    st.markdown("---")
                    st.markdown("**📈 Proiezione xFV Turno per Turno:**")
                    timeline_df = trade_res.get('Timeline')
                    if timeline_df is not None and not timeline_df.empty:
                        chart_data = timeline_df[['Giornata', 'xFV_Ceduti', 'xFV_Ricevuti']].set_index('Giornata')
                        st.bar_chart(chart_data)
                        st.dataframe(
                            timeline_df[['Giornata', 'xFV_Ceduti', 'xFV_Ricevuti', 'Delta_Giornata', 'Match_Ceduti', 'Match_Ricevuti']],
                            width='stretch',
                            hide_index=True
                        )

    with subtab_sim:
        render_free_trade_simulator()

# =============================================================
# =============================================================
# TAB 4: ESPLORA & SCOUTING
# =============================================================
with tab_esplora:
    st.subheader('🔍 Esplora, Scouting & Competizione')
    st.caption('Ricerca calciatori Serie A per metriche reali, monitoraggio infortuni/rientri, ispezione rose avversarie e calendario FDR.')
    sub_scout, sub_indisp, sub_lega_insp, sub_cal = st.tabs([
        '🎯 Scouting & Statistiche Serie A',
        '🚑 Indisponibili & Rientri',
        '👥 Rose & Prestiti di Lega',
        '📅 Calendario & Difficoltà (FDR)'
    ])
    with sub_scout:
        scout_view = st.radio(
            "Vista Scouting:",
            options=[
                "📊 Classifica & Ricerca Calciatori",
                "🎯 Opportunità Buy-Low in Lega",
                "📉 Grafici xG vs Gol & Segnali",
                "🛡️ Rendimento Squadre Serie A"
            ],
            horizontal=True,
            key="scout_main_view_radio"
        )
        st.markdown("---")

        # VISTA 1: CLASSIFICA & RICERCA UNIFICATA (INCLUDE FOCUS PORTIERI)
        if scout_view == "📊 Classifica & Ricerca Calciatori":
            f_c1, f_c2, f_c3, f_c4 = st.columns([1.1, 1.6, 1.1, 1.2])
            with f_c1:
                role_classic_filter = st.selectbox("Ruolo:", options=["TUTTI", "P (Portieri)", "D (Difensori)", "C (Centrocampisti)", "A (Attaccanti)"], key="sb_rc_filter")
            with f_c2:
                sort_metric = st.selectbox(
                    "Ordina per metrica:",
                    options=[
                        ("FM_Stagione", "FantaMedia Stagionale (FM)"),
                        ("MV_Stagione", "Media Voto Pura (MV)"),
                        ("xG_Tot", "xG Totali (Gol Attesi)"),
                        ("xG_90", "xG per 90 min"),
                        ("xA_Tot", "xA Totali (Assist Attesi)"),
                        ("xA_90", "xA per 90 min"),
                        ("Delta_xG", "Delta xG (Buy-Low / Sfortuna)"),
                        ("Tiri_90", "Tiri per 90 min"),
                        ("Key_Passes_90", "Passaggi Chiave per 90 min"),
                        ("Pct_Sufficienza", "Sufficienza (% Voti >= 6)"),
                        ("Goals_Prevented", "Portieri: Goals Prevented (PSxG-GA)"),
                        ("Pct_Parate", "Portieri: % Parate")
                    ],
                    format_func=lambda x: x[1],
                    key="sb_sort_metric"
                )
            with f_c3:
                min_minuti = st.slider("Minuti Minimi:", min_value=0, max_value=600, value=90, step=45, key="sb_min_mins")
            with f_c4:
                search_name = st.text_input("🔍 Cerca Calciatore:", placeholder="es. Lautaro, Pulisic...", key="sb_srch")
        
            df_lb = df_master.copy()
            if role_classic_filter != "TUTTI":
                rc_code = role_classic_filter.split()[0]
                df_lb = df_lb[df_lb['RuoloClassic'] == rc_code]
            if 'Minuti_Reali' in df_lb.columns:
                df_lb = df_lb[df_lb['Minuti_Reali'] >= min_minuti]
            if search_name:
                df_lb = df_lb[df_lb['Giocatore'].str.contains(search_name, case=False, na=False)]
        
            sort_col = sort_metric[0]
            sort_asc = True if sort_col == "Delta_xG" else False
            if sort_col in df_lb.columns:
                df_lb = df_lb.sort_values(sort_col, ascending=sort_asc)
    
            role_col_sc = 'RuoloClassic' if is_classic else 'RuoloMantra'
            if role_classic_filter == "P (Portieri)" or sort_col in ("Goals_Prevented", "Pct_Parate"):
                display_cols = [
                    'Giocatore', 'Squadra', role_col_sc, 'Presenze', 'MV_Stagione', 'FM_Stagione',
                    'Pct_Sufficienza', 'GS', 'Goals_Prevented', 'Goals_Prevented_90', 'Pct_Parate',
                    'Clean_Sheets_Tot', 'Errors_Leading_To_Goal'
                ]
            else:
                display_cols = [
                    'Giocatore', 'Squadra', role_col_sc, 'Presenze', 'MV_Stagione', 'FM_Stagione',
                    'Pct_Sufficienza', 'GF', 'xG_Tot', 'xG_90', 'Delta_xG',
                    'ASS', 'xA_Tot', 'xA_90', 'Tiri_90', 'Key_Passes_90', 'Signal'
                ]
            display_cols = [c for c in display_cols if c in df_lb.columns]
            st.caption("💡 Clicca su qualsiasi calciatore per aprire la scheda profilo dettagliata.")
            ev_lb = st.dataframe(
                df_lb[display_cols].reset_index(drop=True),
                width='stretch',
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="scout_lb_table"
            )
            if ev_lb and hasattr(ev_lb, 'selection'):
                s_rows = ev_lb.selection.get('rows', [])
                if s_rows:
                    idx_sel = s_rows[0]
                    df_lb_reset = df_lb.reset_index(drop=True)
                    if idx_sel < len(df_lb_reset):
                        show_player_profile_dialog(
                            df_lb_reset.iloc[idx_sel]['Giocatore'],
                            df_master,
                            calendar=calendar,
                            matchday=selected_giornata,
                            df_roster=df_my_roster
                        )

        # VISTA 2: BERSAGLI BUY-LOW NELLE ROSE AVVERSARIE
        elif scout_view == "🎯 Opportunità Buy-Low in Lega":
            st.markdown(
                "Calciatori nelle rose dei tuoi avversari che stanno creando molto più di quanto raccolto finora (**xG/xA superiori ai bonus reali**). "
                "Ideali da chiedere in uno scambio prima che si sblocchino."
            )
            my_team = get_active_my_team()
            league_rosters_dict = load_league_rosters()
    
            if not league_rosters_dict:
                st.info("Nessuna rosa di lega caricata.")
            else:
                opp_buylow = []
                for t_name, p_list in league_rosters_dict.items():
                    if t_name == my_team:
                        continue
                    df_t = get_team_roster_df(t_name, df_master)
                    for _, r in df_t.iterrows():
                        if r.get('InPrestito', False) or r.get('Costo', 1) == 0:
                            continue
                        d_xg = float(r.get('Delta_xG', 0.0))
                        sig = str(r.get('Signal', ''))
                        xg_tot = float(r.get('xG_Tot', 0.0))
                        if d_xg <= -0.6 or 'BUY-LOW' in sig or (xg_tot >= 1.5 and r.get('GF', 0) == 0):
                            opp_buylow.append({
                                'Squadra Lega': t_name,
                                'Giocatore': r['Giocatore'],
                                'Ruolo': r.get('RuoloClassic' if is_classic else 'RuoloMantra', r.get('RuoloMantra', '')),
                                'Club Serie A': r['Squadra'],
                                'Presenze': int(r.get('Presenze', 0)),
                                'GF': int(r.get('GF', 0)),
                                'xG Totali': r.get('xG_Tot', 0.0),
                                'Delta xG (Sfortuna)': d_xg,
                                'Tiri / 90': r.get('Tiri_90', 0.0),
                                'KP / 90': r.get('Key_Passes_90', 0.0),
                                'Suggerimento': '🔥 Forte Buy-Low' if d_xg < -1.5 else '⚡ Sottovalutato'
                            })
        
                if opp_buylow:
                    df_opp_bl = pd.DataFrame(opp_buylow).sort_values('Delta xG (Sfortuna)', ascending=True)
                    bl_col1, bl_col2 = st.columns(2)
                    with bl_col1:
                        filter_rival = st.selectbox(
                            "Filtra per Squadra Rivale:",
                            options=["TUTTE LE SQUADRE"] + sorted(list(set(df_opp_bl['Squadra Lega']))),
                            key=f"bl_rival_sel_{active_league}_{my_team}"
                        )
                    with bl_col2:
                        if is_classic:
                            filter_role = st.selectbox(
                                "Filtra per Reparto:",
                                options=["TUTTI", "Attaccanti (A)", "Centrocampisti (C)", "Difensori (D)"],
                                key=f"bl_role_sel_{active_league}_{my_team}"
                            )
                        else:
                            filter_role = st.selectbox(
                                "Filtra per Reparto:",
                                options=["TUTTI", "Attaccanti (Pc / A)", "Centrocampisti (C / T / W / M / E)", "Difensori (Dc / Dd / Ds / B)"],
                                key=f"bl_role_sel_{active_league}_{my_team}"
                            )
                
                    if filter_rival != "TUTTE LE SQUADRE":
                        df_opp_bl = df_opp_bl[df_opp_bl['Squadra Lega'] == filter_rival]
                    if is_classic:
                        if filter_role == "Attaccanti (A)":
                            df_opp_bl = df_opp_bl[df_opp_bl['Ruolo'] == 'A']
                        elif filter_role == "Centrocampisti (C)":
                            df_opp_bl = df_opp_bl[df_opp_bl['Ruolo'] == 'C']
                        elif filter_role == "Difensori (D)":
                            df_opp_bl = df_opp_bl[df_opp_bl['Ruolo'] == 'D']
                    else:
                        if filter_role == "Attaccanti (Pc / A)":
                            df_opp_bl = df_opp_bl[df_opp_bl['Ruolo'].str.contains('Pc|A', na=False)]
                        elif filter_role == "Centrocampisti (C / T / W / M / E)":
                            df_opp_bl = df_opp_bl[df_opp_bl['Ruolo'].str.contains('C|T|W|M|E', na=False)]
                        elif filter_role == "Difensori (Dc / Dd / Ds / B)":
                            df_opp_bl = df_opp_bl[df_opp_bl['Ruolo'].str.contains('Dc|Dd|Ds|B', na=False)]
                
                    st.dataframe(df_opp_bl, width='stretch', hide_index=True)
                else:
                    st.info("Nessun calciatore con marcata sotto-performance rilevato nelle altre squadre.")

        # VISTA 3: GRAFICI BUY-LOW & SELL-HIGH
        elif scout_view == "📉 Grafici xG vs Gol & Segnali":
            f_col1, f_col2 = st.columns([2, 1])
            with f_col1:
                st.caption("💡 **Passa il cursore sui pallini** per i dettagli. Chi sta **sotto la linea tratteggiata** ha segnato meno di quanto prodotto (*Candidato Buy-Low*).")
            with f_col2:
                role_options = ["Tutti i Ruoli", "Attaccanti (A)", "Centrocampisti (C)", "Difensori (D)"]
                sel_scatter_role = st.selectbox("Filtra per Ruolo:", options=role_options, index=0, key="sel_scat_role")
        
            df_plot_base = df_master[df_master['Presenze'] > 0].copy()
            if sel_scatter_role == "Attaccanti (A)":
                df_plot_base = df_plot_base[df_plot_base['RuoloClassic'] == 'A']
            elif sel_scatter_role == "Centrocampisti (C)":
                df_plot_base = df_plot_base[df_plot_base['RuoloClassic'] == 'C']
            elif sel_scatter_role == "Difensori (D)":
                df_plot_base = df_plot_base[df_plot_base['RuoloClassic'] == 'D']

            role_scale = alt.Scale(domain=['P', 'D', 'C', 'A'], range=['#f59e0b', '#10b981', '#3b82f6', '#ef4444'])
            sc_c1, sc_c2 = st.columns(2)
            with sc_c1:
                st.markdown("##### ⚽ xG Totali vs Gol Fatti (GF)")
                max_xg = float(max(df_plot_base['xG_Tot'].max() if not df_plot_base.empty else 1.0, df_plot_base['GF'].max() if not df_plot_base.empty else 1.0) + 1.0)
                diag_df1 = pd.DataFrame({'x': [0, max_xg], 'y': [0, max_xg]})
                ref_line1 = alt.Chart(diag_df1).mark_line(strokeDash=[4, 4], color='#94a3b8', opacity=0.6, strokeWidth=1.5).encode(x='x:Q', y='y:Q')
                points1 = alt.Chart(df_plot_base).mark_circle(opacity=0.75, stroke='#ffffff', strokeWidth=0.6).encode(
                    x=alt.X('xG_Tot:Q', title='xG Totali (Gol Attesi)'),
                    y=alt.Y('GF:Q', title='Gol Fatti (GF Reali)'),
                    color=alt.Color('RuoloClassic:N', title='Ruolo', scale=role_scale),
                    size=alt.Size('Presenze:Q', title='Presenze', scale=alt.Scale(range=[40, 260])),
                    tooltip=['Giocatore:N', 'Squadra:N', 'Presenze:Q', alt.Tooltip('xG_Tot:Q', format='.2f'), 'GF:Q', alt.Tooltip('Delta_xG:Q', format='+.2f'), alt.Tooltip('FM_Stagione:Q', format='.2f')]
                )
                st.altair_chart((ref_line1 + points1).properties(height=380).interactive(), width='stretch', theme="streamlit")
        
            with sc_c2:
                st.markdown("##### 🎯 xA Totali vs Assist Fatti (ASS)")
                max_xa = float(max(df_plot_base['xA_Tot'].max() if not df_plot_base.empty else 1.0, df_plot_base['ASS'].max() if not df_plot_base.empty else 1.0) + 1.0)
                diag_df2 = pd.DataFrame({'x': [0, max_xa], 'y': [0, max_xa]})
                ref_line2 = alt.Chart(diag_df2).mark_line(strokeDash=[4, 4], color='#94a3b8', opacity=0.6, strokeWidth=1.5).encode(x='x:Q', y='y:Q')
                points2 = alt.Chart(df_plot_base).mark_circle(opacity=0.75, stroke='#ffffff', strokeWidth=0.6).encode(
                    x=alt.X('xA_Tot:Q', title='xA Totali (Assist Attesi)'),
                    y=alt.Y('ASS:Q', title='Assist Fatti (ASS Reali)'),
                    color=alt.Color('RuoloClassic:N', title='Ruolo', scale=role_scale),
                    size=alt.Size('Presenze:Q', title='Presenze', scale=alt.Scale(range=[40, 260])),
                    tooltip=['Giocatore:N', 'Squadra:N', 'Presenze:Q', alt.Tooltip('xA_Tot:Q', format='.2f'), 'ASS:Q', alt.Tooltip('Delta_xA:Q', format='+.2f'), alt.Tooltip('FM_Stagione:Q', format='.2f')]
                )
                st.altair_chart((ref_line2 + points2).properties(height=380).interactive(), width='stretch', theme="streamlit")

            signal_filter = st.radio(
                "Filtra Tabella per Segnale di Mercato:",
                options=["BUY-LOW (Sottoperforma xG)", "SELL-HIGH (Sovraperforma xG)", "CREATORE ELITE (High xA)", "BOMBER PURO (High xG)", "TUTTI"],
                horizontal=True,
                key="sb_sig_filter"
            )
            df_signals = df_master.copy()
            if signal_filter != "TUTTI":
                df_signals = df_signals[df_signals['Signal'] == signal_filter]
            sig_cols = ['Giocatore', 'Squadra', 'RuoloClassic' if is_classic else 'RuoloMantra', 'Presenze', 'FM_Stagione', 'GF', 'xG_Tot', 'Delta_xG', 'ASS', 'xA_Tot', 'Tiri_90', 'Signal']
            sig_cols = [c for c in sig_cols if c in df_signals.columns]
            st.dataframe(df_signals[sig_cols].sort_values(by='Delta_xG', ascending=True), width='stretch', hide_index=True)

        # VISTA 4: RENDIMENTO SQUADRE SERIE A
        else:
            st.caption("Produzione offensiva (xG/partita) e tenuta difensiva (xGA/partita) delle 20 squadre di Serie A.")
            team_understat = get_understat_teams_metrics()
            if team_understat:
                t_records = []
                for t_name, t_data in team_understat.items():
                    t_records.append({
                        'Squadra': t_name,
                        'Partite': t_data['matches'],
                        'xG / Partita (Attacco)': t_data['xG_per_game'],
                        'xGA / Partita (Difesa)': t_data['xGA_per_game'],
                        'Differenziale xG': t_data['xG_Diff']
                    })
                df_tu = pd.DataFrame(t_records).sort_values('Differenziale xG', ascending=False)
                c_tu1, c_tu2 = st.columns([3, 2])
                with c_tu1:
                    st.dataframe(df_tu, width='stretch', hide_index=True)
                with c_tu2:
                    st.bar_chart(df_tu.set_index('Squadra')['Differenziale xG'])
            else:
                st.info("Dati di squadra Understat al momento non disponibili.")

    # SUBTAB 2: INDISPONIBILI & RIENTRI SERIE A
    with sub_indisp:
        df_all_unavail = get_all_unavailable_df(df_master, current_giornata=selected_giornata)
        top_c1, top_c2 = st.columns([3, 1])
        with top_c1:
            if not df_all_unavail.empty:
                n_inf = len(df_all_unavail[df_all_unavail['Stato'] == 'Infortunato'])
                n_squ = len(df_all_unavail[df_all_unavail['Stato'] == 'Squalificato'])
                n_dub = len(df_all_unavail[df_all_unavail['Stato'].isin(['In dubbio', 'Diffidato'])])
                st.markdown(
                    f"**Totale Segnalati:** `{len(df_all_unavail)}` calciatori · "
                    f"<span style='color:#ef4444; font-weight:700;'>🚑 {n_inf} Infortunati</span> · "
                    f"<span style='color:#f97316; font-weight:700;'>🟥 {n_squ} Squalificati</span> · "
                    f"<span style='color:#eab308; font-weight:700;'>⚠️ {n_dub} In dubbio/Diffidati</span>",
                    unsafe_allow_html=True
                )
            else:
                st.info("Nessun calciatore indisponibile registrato.")
        with top_c2:
            if st.button("🔄 Aggiorna Live", key="btn_sync_inj_esplora", type="primary", width='stretch'):
                with st.spinner("Scaricamento dati live in corso..."):
                    fetch_live_injuries_from_fantacalcio()
                    st.cache_data.clear()
                st.success("✅ Dati aggiornati!")
                st.rerun()

        if not df_all_unavail.empty:
            fb1, fb2, fb3 = st.columns([2, 2, 2])
            with fb1:
                search_p = st.text_input("🔍 Cerca calciatore:", key="search_indisp_p")
            with fb2:
                all_teams = ["TUTTE LE SQUADRE"] + sorted(df_all_unavail['Squadra'].unique().tolist())
                sel_sq = st.selectbox("Filtra per squadra:", options=all_teams, key="filter_indisp_sq")
            with fb3:
                all_stati = ["TUTTI GLI STATI", "Solo Infortunati", "Solo Squalificati", "Solo In dubbio", "Solo Diffidati"]
                sel_st = st.selectbox("Filtra per stato:", options=all_stati, key="filter_indisp_st")

            df_filtered_indisp = df_all_unavail.copy()
            if search_p:
                df_filtered_indisp = df_filtered_indisp[df_filtered_indisp['Giocatore'].str.contains(search_p, case=False, na=False)]
            if sel_sq != "TUTTE LE SQUADRE":
                df_filtered_indisp = df_filtered_indisp[df_filtered_indisp['Squadra'] == sel_sq]
            if sel_st == "Solo Infortunati":
                df_filtered_indisp = df_filtered_indisp[df_filtered_indisp['Stato'] == 'Infortunato']
            elif sel_st == "Solo Squalificati":
                df_filtered_indisp = df_filtered_indisp[df_filtered_indisp['Stato'] == 'Squalificato']
            elif sel_st == "Solo In dubbio":
                df_filtered_indisp = df_filtered_indisp[df_filtered_indisp['Stato'] == 'In dubbio']
            elif sel_st == "Solo Diffidati":
                df_filtered_indisp = df_filtered_indisp[df_filtered_indisp['Stato'] == 'Diffidato']

            show_cols = ['Giocatore', 'Ruolo', 'Squadra', 'Stato', 'Diagnosi', 'Rientro Stimato', 'Giornata Prevista']
            st.dataframe(df_filtered_indisp[show_cols], width='stretch', hide_index=True)

            with st.expander("📄 Consulta bollettini clinici estesi da Fantacalcio.it", expanded=False):
                for _, r in df_filtered_indisp.iterrows():
                    raw_txt = r.get('Dettaglio Completo', '')
                    if raw_txt:
                        st.markdown(f"- **{r['Giocatore']}** ({r['Squadra']}): *{raw_txt}*")

    # SUBTAB 3: ROSE & PRESTITI DI LEGA
    with sub_lega_insp:
        cur_insp_idx = league_teams.index(current_active_team) if current_active_team in league_teams else 0
        selected_inspect_team = st.selectbox(
            "🔍 Seleziona Squadra della Lega da Ispezionare:",
            options=league_teams,
            index=cur_insp_idx,
            key=f"inspect_team_select_{current_active_team}"
        )
        df_inspect = get_team_roster_df(selected_inspect_team, df_master)
        if not df_inspect.empty:
            c_i1, c_i2, c_i3, c_i4 = st.columns(4)
            c_i1.metric("Giocatori in Rosa", len(df_inspect))
            c_i2.metric("Spesa d'Asta Totale", f"{int(df_inspect['Costo'].sum())} cr")
            c_i3.metric("FantaMedia Squadra", round(df_inspect['FM_Stagione'].mean(), 2))
            if is_classic:
                c_i4.metric("Attaccanti (A)", len(df_inspect[df_inspect['RuoloClassic'] == 'A']) if 'RuoloClassic' in df_inspect.columns else 0)
            else:
                c_i4.metric("Punte Pc", len(df_inspect[df_inspect['RuoloMantra'].str.contains('Pc', na=False)]))
    
            insp_role_col = 'RuoloClassic' if is_classic else 'RuoloMantra'
            cols_inspect = [
                'Badge_Disponibilita', 'Badge_Prestito', 'Giocatore', 'Squadra', insp_role_col, 'Costo', 'Presenze',
                'MV_Stagione', 'FM_Stagione', 'GF', 'ASS', 'Signal'
            ]
            cols_inspect = [c for c in cols_inspect if c in df_inspect.columns]
            st.caption("💡 Clicca su qualsiasi riga per aprire la Scheda Profilo dettagliata.")
            event_insp = st.dataframe(
                df_inspect[cols_inspect],
                width='stretch',
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key=f"inspect_team_df_table_{active_league}_{selected_inspect_team}"
            )
            if event_insp and hasattr(event_insp, 'selection'):
                s_rows = event_insp.selection.get('rows', [])
                if s_rows:
                    insp_idx = s_rows[0]
                    if insp_idx < len(df_inspect):
                        show_player_profile_dialog(
                            df_inspect.iloc[insp_idx]['Giocatore'],
                            df_master,
                            calendar=calendar,
                            matchday=selected_giornata,
                            df_roster=df_inspect
                        )

        st.markdown("---")
        df_league_summary = get_league_summary(df_master)
        if not df_league_summary.empty:
            with st.expander("📊 Panoramica & Confronto Tutte le Squadre della Lega", expanded=True):
                st.dataframe(df_league_summary, width='stretch', hide_index=True)

        loan_map_all, df_all_loans = build_loan_registry()
        if not df_all_loans.empty:
            with st.expander(f"📑 Registro Prestiti di Lega ({len(df_all_loans)} attivi) & Gestione Accordi", expanded=False):
                st.dataframe(
                    df_all_loans[['Calciatore', 'Ruolo', 'Squadra', 'Proprietario', 'In_Prestito_A', 'Costo_Asta', 'Tipo']],
                    width='stretch',
                    hide_index=True
                )
                m_col1, m_col2 = st.columns(2)
                with m_col1:
                    st.markdown("##### ❌ Termina un Prestito Esistente")
                    loan_options = [f"{r['Calciatore']} ({r['Proprietario']} ➔ {r['In_Prestito_A']})" for _, r in df_all_loans.iterrows()]
                    selected_loan_to_term = st.selectbox("Seleziona il prestito da risolvere:", options=loan_options, key=f"select_loan_term_{active_league}")
                    if st.button("Termina Prestito Selezionato", type="secondary", key="btn_term_loan_tab4", width='stretch'):
                        sel_idx = loan_options.index(selected_loan_to_term)
                        row_sel = df_all_loans.iloc[sel_idx]
                        ok, msg = terminate_loan(row_sel['Calciatore'], row_sel['In_Prestito_A'])
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
                with m_col2:
                    st.markdown("##### ➕ Registra Nuovo Prestito Manuale")
                    owner_team_new = st.selectbox("Squadra Proprietaria:", options=league_teams, key="new_loan_owner_tab4")
                    all_rosters_dict = load_league_rosters()
                    avail_owner_players = sorted([p['Giocatore'] for p in all_rosters_dict.get(owner_team_new, []) if p.get('Costo', 0) > 0])
                    player_to_loan_new = st.selectbox("Calciatore da prestare:", options=avail_owner_players if avail_owner_players else ["Nessun giocatore"], key="new_loan_p_tab4")
                    borrower_team_new = st.selectbox("Squadra Ricevente:", options=[t for t in league_teams if t != owner_team_new], key="new_loan_borrower_tab4")
                    if st.button("Registra Prestito", type="primary", key="btn_add_loan_tab4", width='stretch'):
                        if player_to_loan_new and player_to_loan_new != "Nessun giocatore":
                            ok, msg = add_or_update_loan(player_to_loan_new, owner_team_new, borrower_team_new)
                            if ok:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)

        df_out_league = get_out_of_serie_a_summary()
        if not df_out_league.empty:
            with st.expander(f"🚫 Calciatori Fuori dalla Serie A in Lega ({len(df_out_league)} da svincolare)", expanded=False):
                st.dataframe(
                    df_out_league[['Calciatore', 'Squadra_Lega', 'Ruolo', 'Costo_Asta', 'Stato', 'Consiglio']],
                    width='stretch',
                    hide_index=True
                )

    # SUBTAB 4: CALENDARIO & FDR
    with sub_cal:
        st.caption(
            "Fixture Difficulty Rating (FDR 1 = Molto Facile, 5 = Difficilissimo) calcolato combinando classifica attuale, forza storica e fattore casa/trasferta."
        )
        col_cal1, col_cal2 = st.columns(2)
        with col_cal1:
            cal_start = st.number_input("Da Giornata:", min_value=1, max_value=35, value=selected_giornata, key="cal_st")
        with col_cal2:
            cal_end = st.number_input("A Giornata:", min_value=cal_start + 1, max_value=38, value=min(38, cal_start + 6), key="cal_en")
    
        matrix_df = get_schedule_matrix(start_giornata=cal_start, end_giornata=cal_end, calendar=calendar)
        st.dataframe(matrix_df, width='stretch', hide_index=True)

        c_fav1, c_fav2 = st.columns(2)
        with c_fav1:
            st.markdown("##### 🟢 Top 5 Calendari Più Agevoli")
            st.dataframe(matrix_df.head(5)[['Squadra', 'Power_Dinamico', 'Posizione_Attuale', 'FDR_Medio']], width='stretch', hide_index=True)
        with c_fav2:
            st.markdown("##### 🔴 Top 5 Calendari Più Ostici")
            st.dataframe(matrix_df.tail(5)[['Squadra', 'Power_Dinamico', 'Posizione_Attuale', 'FDR_Medio']], width='stretch', hide_index=True)

        with st.expander("📊 Classifica Reale Serie A & Power Rating Dinamico Squadre", expanded=False):
            ratings_dict, df_ratings = compute_dynamic_team_ratings(selected_giornata)
            cols_ratings = ['Posizione_Attuale', 'Squadra', 'Punti_Attuali', 'DR_Attuale', 'Power_Attuale', 'Power_Triennio', 'Power_Dinamico']
            st.dataframe(df_ratings[cols_ratings].sort_values(by='Posizione_Attuale', ascending=True), width='stretch', hide_index=True)

# =============================================================
# TAB 5: IMPOSTAZIONI & SYNC
# =============================================================
with tab_impostazioni:
    st.header('⚙️ Impostazioni, Leghe & Sincronizzazione Dati')
    st.caption('Pannello centralizzato per configurare le leghe, sincronizzare i dati e gestire gli accessi.')
    sub_imp_leghe, sub_imp_sync, sub_imp_admin = st.tabs([
        '🏆 Gestione Leghe',
        '🔄 Sincronizzazione Dati & File',
        '👑 Pannello Admin & Utenti'
    ])
    with sub_imp_leghe:
        st.caption(f"🔗 Link diretto a questa lega: `?league={active_league}&mode={active_league_type}`")

        if is_current_user_admin() or current_user.get('can_create_leagues', False):
            st.markdown("---")
            st.markdown("**➕ Crea Nuova Lega**")
            with st.form("new_league_form"):
                new_lg_name = st.text_input("Nome della nuova lega:", placeholder="es. Fanta Amici 2026")
                new_lg_mode = st.radio("Tipologia lega:", ["Mantra", "Classic"], horizontal=True, key="new_lg_mode_radio")
                create_btn = st.form_submit_button("Crea Nuova Lega", type="primary")
                if create_btn:
                    if not new_lg_name.strip():
                        st.warning("Inserisci un nome valido.")
                    else:
                        ok, new_lid, msg = create_new_league(new_lg_name.strip(), league_type=new_lg_mode.lower())
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
        else:
            st.caption("🔒 Solo l'amministratore o gli utenti abilitati possono creare nuove leghe.")
                
        if is_current_user_admin() and len(league_ids) > 1:
            st.markdown("---")
            st.markdown("**🗑️ Elimina Lega**")
            del_target = st.selectbox(
                "Seleziona lega da eliminare:",
                options=[lid for lid in league_ids if lid != active_league],
                format_func=lambda x: leagues_dict.get(x, {}).get('name', x),
                key="del_league_target"
            )
            if st.button("🗑️ Elimina Definitivamente", type="secondary"):
                ok_del, del_msg = delete_league(del_target)
                if ok_del:
                    st.success(del_msg)
                    st.rerun()
                else:
                    st.error(del_msg)

        # -------------------------------------------------------------

        st.markdown('---')
        st.markdown('**🔄 Riconfigurazione Rapida:**')
        if st.button('⚙️ Riconfigura Lega / Ricarica File Excel', key='btn_reconfig_tab_imp'):
            st.session_state['setup_mode'] = True
            st.rerun()
        meta_sidebar = get_league_metadata()
        st.caption(f"📅 Rose di Lega aggiornate al: {meta_sidebar.get('last_updated')}")
    with sub_imp_sync:
        render_league_upload_section("tab_imp", df_master, label_title="📥 Carica / Aggiorna File Rose della Lega (.xlsx, .xls, .csv)")
        st.markdown("---")

        col_sync1, col_sync2 = st.columns([2, 1])
        with col_sync1:
            if st.button("🚀 Sincronizza Tutti i Dati Live (Fantacalcio.it + Understat + Infortuni)", type="primary", width='stretch'):
                st.cache_data.clear()
                st.cache_resource.clear()
                with st.spinner("Sincronizzazione completa in corso da Fantacalcio.it e Understat..."):
                    fetch_live_injuries_from_fantacalcio()
                    df_master, _ = sync_and_build_database(force_live_scrape=True)
                st.success("✅ Database, statistiche, metriche Understat e infortuni aggiornati!")
                st.rerun()
        with col_sync2:
            if st.button("🧹 Svuota Cache", width='stretch'):
                st.cache_data.clear()
                st.cache_resource.clear()
                st.success("Cache svuotata!")
                st.rerun()

        with st.expander("🛠️ Opzioni Avanzate & Caricamento Manuale File Statistiche", expanded=False):
            st.markdown("**Carica manualmente file Statistiche_Fantacalcio (.xlsx):**")
            uploaded_stats_file = st.file_uploader(
                "Carica Statistiche_Fantacalcio (.xlsx):",
                type=['xlsx', 'xls'],
                key="upload_stats_file_direct"
            )
            if uploaded_stats_file is not None:
                file_sig = f"{uploaded_stats_file.name}_{uploaded_stats_file.size}"
                if st.session_state.get('last_processed_stats_sig') != file_sig:
                    dest_stats = os.path.join(APP_DIR, "data", "Statistiche_Fantacalcio_Live.xlsx")
                    with open(dest_stats, "wb") as f:
                        f.write(uploaded_stats_file.getbuffer())
                    with st.spinner("Sincronizzazione ruoli e statistiche ufficiali..."):
                        sync_and_build_database(dest_stats)
                        st.cache_data.clear()
                    st.session_state['last_processed_stats_sig'] = file_sig
                    st.success("✅ Statistiche e ruoli ufficiali caricati con successo!")
                    st.rerun()
                else:
                    st.success("✅ File statistiche sincronizzato e attivo!")

            st.markdown("---")
            c_adv1, c_adv2 = st.columns(2)
            with c_adv1:
                if st.button("🔄 Aggiorna Solo Understat (xG/xA)", key="sync_understat_btn", width='stretch'):
                    with st.spinner("Aggiornamento metriche Understat in corso..."):
                        df_updated = sync_understat_metrics(df_master)
                        from engine.data_loader import compute_sufficiency_metrics
                        df_updated = compute_sufficiency_metrics(df_updated)
                        master_csv = os.path.join(APP_DIR, "data", "players_master.csv")
                        df_updated.to_csv(master_csv, index=False)
                        st.cache_data.clear()
                    st.success("Dati Understat aggiornati!")
                    st.rerun()
            with c_adv2:
                if st.button("🚑 Aggiorna Solo Infortuni Live", key="btn_sync_injuries_sidebar", width='stretch'):
                    with st.spinner("Scraping indisponibili in tempo reale..."):
                        fetch_live_injuries_from_fantacalcio()
                        st.cache_data.clear()
                    st.success("✅ Infortuni e squalifiche aggiornati!")
                    st.rerun()

    with sub_imp_admin:
            st.caption("Gestisci gli utenti che possono accedere all'app pubblica su Streamlit Cloud e scegli quali leghe può vedere ciascun utente. Ogni salvataggio viene ora memorizzato in modo permanente in locale e sincronizzato in automatico con GitHub/Cloud.")
            if '_admin_user_saved_msg' in st.session_state:
                st.success(st.session_state.pop('_admin_user_saved_msg'))

            all_sys_leagues = get_available_leagues(include_all_for_admin=True)
            all_sys_league_ids = list(all_sys_leagues.keys())
            full_db_obj = load_users_db()
            users_db = full_db_obj.get("users", {})

            st.markdown("**👥 Utenti Registrati:**")
            for uname_k, u_info in users_db.items():
                u_leagues = u_info.get("allowed_leagues", [])
                if "*" in u_leagues or u_info.get("role") == "admin":
                    lg_str = "Tutte le leghe (*)"
                elif u_leagues:
                    lg_str = ", ".join([all_sys_leagues.get(l, {}).get("name", l) for l in u_leagues])
                else:
                    lg_str = "Nessuna lega"
                def_t_map = u_info.get("default_team_by_league", {}) or {}
                def_t_str = f" · Squadra: `{def_t_map.get(active_league)}`" if def_t_map.get(active_league) else ""
                st.markdown(
                    f"<div style='background:rgba(15,23,42,0.75); border-left:3px solid {'#f59e0b' if u_info.get('role')=='admin' else '#38bdf8'}; padding:6px 9px; border-radius:5px; margin-bottom:5px; font-size:0.78rem;'>"
                    f"<b>{u_info.get('display_name', uname_k)}</b> (<code>{uname_k}</code>) — <i>{u_info.get('role', 'user')}</i><br>"
                    f"<span style='color:#94a3b8;'>🏆 Leghe: {lg_str}{def_t_str}</span></div>",
                    unsafe_allow_html=True
                )

            st.markdown("---")
            st.markdown("**➕ Crea / Aggiorna Utente**")
            edit_mode_sel = st.selectbox(
                "Azione:",
                options=["➕ Nuovo Utente"] + [f"✏️ Modifica: {u}" for u in users_db.keys()],
                key="admin_user_edit_mode"
            )
            is_editing_existing = edit_mode_sel.startswith("✏️ Modifica: ")
            target_uname_prefill = edit_mode_sel.replace("✏️ Modifica: ", "").strip() if is_editing_existing else ""
            existing_u_obj = users_db.get(target_uname_prefill, {}) if is_editing_existing else {}

            with st.form("admin_create_update_user_form"):
                f_uname = st.text_input(
                    "Username (per il login):",
                    value=target_uname_prefill,
                    placeholder="es. marco"
                )
                f_dname = st.text_input(
                    "Nome Visualizzato:",
                    value=existing_u_obj.get("display_name", ""),
                    placeholder="es. Marco Rossi"
                )
                f_pwd = st.text_input(
                    "Password" + (" (lascia vuoto per non cambiarla):" if is_editing_existing else ":"),
                    type="password",
                    placeholder="Inserisci password"
                )
                f_role = st.selectbox(
                    "Ruolo:",
                    options=["user", "admin"],
                    index=1 if existing_u_obj.get("role") == "admin" else 0
                )
                default_lg_sel = [l for l in existing_u_obj.get("allowed_leagues", []) if l in all_sys_league_ids]
                if not is_editing_existing and active_league in all_sys_league_ids:
                    default_lg_sel = [active_league]
                f_leagues = st.multiselect(
                    "Leghe visibili a questo utente:",
                    options=all_sys_league_ids,
                    default=default_lg_sel,
                    format_func=lambda x: all_sys_leagues.get(x, {}).get("name", x)
                )
                f_can_create = st.checkbox(
                    "Consenti all'utente di creare nuove leghe in autonomia",
                    value=bool(existing_u_obj.get("can_create_leagues", False))
                )

                # Optional default team in active league
                curr_rosters_admin = load_league_rosters(active_league)
                team_opts_admin = ["(Nessuna predefinita)"] + (list(curr_rosters_admin.keys()) if curr_rosters_admin else [])
                existing_def_team = (existing_u_obj.get("default_team_by_league", {}) or {}).get(active_league, "(Nessuna predefinita)")
                def_team_idx = team_opts_admin.index(existing_def_team) if existing_def_team in team_opts_admin else 0
                f_def_team = st.selectbox(
                    f"Squadra predefinita in '{all_sys_leagues.get(active_league, {}).get('name', active_league)}':",
                    options=team_opts_admin,
                    index=def_team_idx
                )

                if st.form_submit_button("💾 Salva Utente", type="primary", width='stretch'):
                    def_team_dict = dict(existing_u_obj.get("default_team_by_league", {}) or {})
                    if f_def_team != "(Nessuna predefinita)":
                        def_team_dict[active_league] = f_def_team
                    else:
                        def_team_dict.pop(active_league, None)

                    ok_u, msg_u = create_or_update_user(
                        username=f_uname,
                        display_name=f_dname,
                        password=f_pwd if f_pwd else None,
                        role=f_role,
                        allowed_leagues=["*"] if f_role == "admin" else f_leagues,
                        can_create_leagues=f_can_create,
                        default_team_by_league=def_team_dict
                    )
                    if ok_u:
                        st.session_state['_admin_panel_expanded'] = True
                        st.session_state['_admin_user_saved_msg'] = msg_u
                        st.rerun()
                    else:
                        st.error(msg_u)

            non_admin_users = [u for u in users_db.keys() if u != "admin"]
            if non_admin_users:
                st.markdown("---")
                st.markdown("**🗑️ Rimuovi Utente**")
                del_u_sel = st.selectbox("Utente da eliminare:", options=non_admin_users, key="admin_del_user_sel")
                if st.button("🗑️ Elimina Utente", key="admin_btn_del_user", type="secondary", width='stretch'):
                    ok_du, msg_du = delete_user_account(del_u_sel)
                    if ok_du:
                        st.session_state['_admin_panel_expanded'] = True
                        st.session_state['_admin_user_saved_msg'] = msg_du
                        st.rerun()
                    else:
                        st.error(msg_du)

            st.markdown("---")
            st.markdown("**💾 Backup & Sincronizzazione Cloud**")
            st.download_button(
                "📥 Scarica Backup Utenti (JSON)",
                data=json.dumps(full_db_obj, indent=2, ensure_ascii=False),
                file_name="users_db_backup.json",
                mime="application/json",
                width='stretch'
            )
            uploaded_users_bk = st.file_uploader("📤 Ripristina Utenti da file JSON:", type=["json"], key="admin_restore_users_json")
            if uploaded_users_bk is not None:
                try:
                    loaded_bk = json.loads(uploaded_users_bk.read().decode('utf-8'))
                    if isinstance(loaded_bk, dict) and "users" in loaded_bk:
                        save_users_db(loaded_bk, trigger_git_sync=True)
                        st.session_state['_admin_panel_expanded'] = True
                        st.session_state['_admin_user_saved_msg'] = "✅ Backup utenti ripristinato e sincronizzato!"
                        st.rerun()
                except Exception as ex_bk:
                    st.error(f"File JSON non valido: {ex_bk}")

            if is_running_on_localhost():
                if st.button("🚀 Forza Push Utenti & Leghe sul Cloud", key="admin_btn_sync_cloud", width='stretch'):
                    with st.spinner("Sincronizzazione con GitHub (Streamlit Cloud) in corso..."):
                        sync_users_and_leagues_to_github(background=False)
                        st.success("✅ Utenti e leghe pubblicati su Streamlit Cloud (`master` e `dev`)!")

        # Calcolo automatico della giornata in base a data odierna e calendario ufficiale Serie A
