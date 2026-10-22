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
    parse_mantra_roles
)
from engine.trade_evaluator import evaluate_trade
from engine.trade_finder import (
    analyze_squad_weaknesses, find_win_win_trades, find_trades_for_target_players, RECOMMENDED_QUOTAS
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
    terminate_loan, add_or_update_loan
)
from engine.understat_loader import sync_understat_metrics, get_understat_teams_metrics
from engine.injuries_manager import (
    fetch_live_injuries_from_fantacalcio, load_injuries_data,
    set_player_manual_override, clear_player_manual_override,
    clear_all_manual_overrides, get_all_unavailable_players
)
from engine.player_profile_view import (
    show_player_profile_dialog, render_player_profile_content
)
from engine.theme_helper import get_global_theme_css

# Page configuration
st.set_page_config(
    page_title="FantaMantra AI Manager",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS with Soccer Pitch Background, High-Contrast Palette & Larger Typography
st.markdown(get_global_theme_css(), unsafe_allow_html=True)

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
    importlib.reload(engine.optimizer)
    from engine.optimizer import MANTRA_FORMATIONS, optimize_best_mantra_lineup
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
                st.dataframe(df_team_preview[preview_cols].head(8), use_container_width=True, hide_index=True)
                
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🚀 Conferma e Accedi al FantaMantra Manager", type="primary", use_container_width=True):
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

# Calcolo automatico della giornata in base a data odierna e calendario ufficiale Serie A
auto_giornata, matchday_info = get_matchday_from_date()

if 'selected_giornata' not in st.session_state:
    st.session_state['selected_giornata'] = auto_giornata

st.sidebar.markdown(f"""
<div style="background: linear-gradient(135deg, #1e293b, #0f172a); border: 1px solid #334155; border-left: 4px solid #38bdf8; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px;">
    <div style="font-size: 0.72rem; color: #94a3b8; font-weight: 600; text-transform: uppercase;">Calendario Ufficiale Serie A</div>
    <div style="font-size: 1.05rem; font-weight: 700; color: #38bdf8; margin: 2px 0;">{matchday_info['label']}</div>
    <div style="font-size: 0.8rem; color: #cbd5e1;">Data di oggi: <b>{datetime.date.today().strftime('%d/%m/%Y')}</b></div>
    <div style="font-size: 0.8rem; color: {'#4ade80' if matchday_info['status'] == 'live' else '#facc15'}; margin-top: 2px;">
        {'🟢 Turno in corso' if matchday_info['status'] == 'live' else '⏳ Prossimo turno in programma'}
    </div>
</div>
""", unsafe_allow_html=True)

selected_giornata = st.sidebar.number_input(
    "Giornata da Schierare / Analizzare:",
    min_value=1,
    max_value=38,
    value=st.session_state['selected_giornata'],
    step=1,
    help="Impostata in automatico dalla data odierna e dal calendario ufficiale Serie A. Puoi modificarla per analizzare qualsiasi turno."
)

if selected_giornata != st.session_state['selected_giornata']:
    st.session_state['selected_giornata'] = selected_giornata
    st.rerun()

if selected_giornata != auto_giornata:
    if st.sidebar.button(f"🎯 Riaggancia ad Oggi ({matchday_info['label']})"):
        st.session_state['selected_giornata'] = auto_giornata
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("Gestione Rapida Dati")

col_sync1, col_sync2 = st.sidebar.columns(2)
with col_sync1:
    if st.button("🔄 Sync Excel", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        with st.spinner("Sincronizzazione in corso dai file Excel..."):
            df_master, _ = sync_and_build_database()
        st.sidebar.success("Database aggiornato!")
        st.rerun()

with col_sync2:
    if st.button("🧹 Svuota Cache", use_container_width=True):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.sidebar.success("Cache svuotata!")
        st.rerun()

with st.sidebar.expander("🌐 Scarica Statistiche Live (Fantacalcio.it)", expanded=False):
    st.markdown("""
    Scarica il file Excel ufficiale aggiornato direttamente dall'API di Fantacalcio.it:  
    `https://www.fantacalcio.it/api/v1/Excel/stats/21/1`
    """)
    with st.form("fc_live_download_form"):
        fc_user = st.text_input("Username o Email Fantacalcio.it:", placeholder="es. mario.rossi")
        fc_pass = st.text_input("Password Fantacalcio.it:", type="password")
        st.caption("🔒 *Operazione 100% transitoria*: le credenziali vengono usate solo in memoria per la sessione HTTP e mai salvate su disco.")
        submit_fc = st.form_submit_button("🚀 Accedi e Scarica File Excel Live", type="primary")
        
        if submit_fc:
            if not fc_user or not fc_pass:
                st.warning("Inserisci sia username che password.")
            else:
                with st.spinner("Autenticazione su Fantacalcio.it e download statistiche..."):
                    from engine.fanta_downloader import download_fantacalcio_stats
                    succ, msg, out_f = download_fantacalcio_stats(fc_user, fc_pass)
                    if succ:
                        st.success(msg)
                        with st.spinner("Sincronizzazione database in corso..."):
                            df_master, _ = sync_and_build_database()
                        st.success("✅ Database calciatori e statistiche sincronizzate!")
                        st.rerun()
                    else:
                        st.error(msg)

    st.markdown("---")
    st.markdown("**Oppure carica il file già scaricato:**")
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

with st.sidebar.expander("⚡ Metriche Avanzate (Understat xG/xA)", expanded=False):
    st.markdown("""
    Metriche avanzate di rendimento estratte da **Understat Serie A**:
    - **xG (Expected Goals)** & **npxG**
    - **xA (Expected Assists)** & Key Passes
    - **Tiri/90** & Minuti effettivi
    - **xG Chain** & **xG Buildup**
    - **Indicatori di Regressione (Buy-Low / Sell-High)**
    """)
    n_understat = int(df_master['Understat_Matched'].sum()) if 'Understat_Matched' in df_master.columns else 0
    st.caption(f"Status: **{n_understat}** calciatori mappati su dati Understat.")
    if st.button("🔄 Aggiorna Understat Live", type="secondary", key="sync_understat_btn"):
        with st.spinner("Aggiornamento metriche Understat in corso..."):
            df_updated = sync_understat_metrics(df_master)
            from engine.data_loader import compute_sufficiency_metrics
            df_updated = compute_sufficiency_metrics(df_updated)
            master_csv = os.path.join(APP_DIR, "data", "players_master.csv")
            df_updated.to_csv(master_csv, index=False)
            st.cache_data.clear()
        st.success("Dati Understat aggiornati con successo!")
        st.rerun()

with st.sidebar.expander("🚑 Infortuni & Squalifiche Live", expanded=False):
    st.markdown("""
    Monitoraggio in tempo reale degli **infortunati, squalificati e diffidati** da **Fantacalcio.it**.
    """)
    inj_data = load_injuries_data()
    auto_count = len(inj_data.get('auto', {}))
    man_count = len(inj_data.get('manual_overrides', {}))
    last_up = inj_data.get('last_updated', 'Non ancora sincronizzato')
    
    st.markdown(f"- 📋 **Indisponibili Serie A**: `{auto_count}` calciatori")
    if man_count > 0:
        st.markdown(f"- ✍️ **Modifiche Manuali (Override)**: `{man_count}` attive")
    st.caption(f"Ultimo aggiornamento: *{last_up}*")
    
    if st.button("🔄 Scarica Live da Fantacalcio.it", key="btn_sync_injuries_sidebar"):
        with st.spinner("Scraping indisponibili in tempo reale da Fantacalcio.it..."):
            fetch_live_injuries_from_fantacalcio()
            st.cache_data.clear()
        st.success("✅ Infortuni e squalifiche Serie A aggiornati!")
        st.rerun()

user_squad_names = load_user_roster()

# League Integration in Sidebar
league_dict = load_league_rosters()
league_teams = list(league_dict.keys()) if league_dict else []

if league_teams:
    st.sidebar.markdown("---")
    st.sidebar.subheader("🏆 La Mia Lega")
    current_active_team = get_active_my_team()
    # Guarantee user squad is perfectly synchronized with active league team in session
    if current_active_team in league_dict:
        league_players = [p['Giocatore'] for p in league_dict[current_active_team]]
        user_squad_names = league_players
    else:
        user_squad_names = load_user_roster()

    idx_team = league_teams.index(current_active_team) if current_active_team in league_teams else 0
    selected_my_team = st.sidebar.selectbox(
        "Squadra Attiva:",
        options=league_teams,
        index=idx_team,
        key=f"sb_team_select_{current_active_team}",
        help="Imposta quale delle squadre della lega è la tua squadra."
    )
    if selected_my_team != current_active_team:
        set_active_my_team(selected_my_team)
        st.rerun()
        
    if st.sidebar.button("⚙️ Riconfigura Lega / Carica File"):
        st.session_state['setup_mode'] = True
        st.rerun()

    if 'custom_league_data' in st.session_state:
        st.sidebar.info("👤 **Lega Ospite in Sessione** (privata)")
        if st.sidebar.button("🔄 Torna alla Lega Principale", use_container_width=True):
            del st.session_state['custom_league_data']
            st.session_state.pop('custom_league_meta', None)
            st.session_state.pop('active_my_team', None)
            st.rerun()

st.sidebar.markdown(f"**Rosa Attuale ({current_active_team})**: `{len(user_squad_names)} calciatori`")
meta_sidebar = get_league_metadata()
st.sidebar.caption(f"📅 **Rose di Lega:** {meta_sidebar.get('last_updated')}")

# Top-level calculation of df_my_roster so all tabs immediately inherit the active team
df_my_roster = get_roster_dataframe(df_master, user_squad_names)

# -------------------------------------------------------------
# MAIN APP TABS
# -------------------------------------------------------------
tab_rosa, tab_formazione, tab_scambi, tab_lega, tab_stats, tab_calendario = st.tabs([
    "📋 La Mia Rosa",
    "🏆 Formazione Consigliata",
    "🔄 Valutatore Scambi",
    "👥 Tutte le Rose & Lega",
    "📊 Analisi xG & Statistiche",
    "📅 Calendario & FDR"
])

# =============================================================
# TAB 1: LA MIA ROSA
# =============================================================
with tab_rosa:
    t_head_col1, t_head_col2 = st.columns([2, 1.2])
    with t_head_col1:
        st.header("📋 Gestione della Mia Rosa Mantra")
        st.markdown(f"Visualizza, analizza e modifica la tua rosa. Attualmente stai gestendo: <b style='color:#00f0ff; font-size:1.15rem;'>{current_active_team}</b>", unsafe_allow_html=True)
    with t_head_col2:
        if league_teams:
            cur_idx = league_teams.index(current_active_team) if current_active_team in league_teams else 0
            main_team_choice = st.selectbox(
                "🏆 Seleziona Squadra da Gestire:",
                options=league_teams,
                index=cur_idx,
                key=f"main_team_picker_{current_active_team}",
                help="Seleziona quale squadra della lega visualizzare e ottimizzare in tutti i tab."
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

    # Top KPI Metrics (7 columns)
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
    with c1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Totale Rosa</div>
            <div class="metric-val">{num_tot}</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Schierabili Sani</div>
            <div class="metric-val" style="color: #15803d;">{num_schierabili}</div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Infortunati 🚑</div>
            <div class="metric-val" style="color: #dc2626;">{num_inf}</div>
        </div>
        """, unsafe_allow_html=True)
    with c4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Squalificati 🟥</div>
            <div class="metric-val" style="color: #ea580c;">{num_squ}</div>
        </div>
        """, unsafe_allow_html=True)
    with c5:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Prestiti IN 📥</div>
            <div class="metric-val" style="color: #0284c7;">{len(loans_in)}</div>
        </div>
        """, unsafe_allow_html=True)
    with c6:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Prestiti OUT 📤</div>
            <div class="metric-val" style="color: #d97706;">{len(loans_out)}</div>
        </div>
        """, unsafe_allow_html=True)
    with c7:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Da Svincolare 🚫</div>
            <div class="metric-val" style="color: #dc2626;">{len(out_serie_a)}</div>
        </div>
        """, unsafe_allow_html=True)

    # Second Row: Squad Offensive, Creative & D-Factor Metrics
    rk1, rk2, rk3, rk4, rk5 = st.columns(5)
    with rk1:
        tot_xg = round(float(df_my_roster['xG_Tot'].fillna(0).sum()), 2) if 'xG_Tot' in df_my_roster.columns else 0.0
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">xG Totali Rosa</div>
            <div class="metric-val" style="color: #38bdf8;">{tot_xg} xG</div>
        </div>
        """, unsafe_allow_html=True)
    with rk2:
        att_rows = df_my_roster[df_my_roster['RuoloClassic'] == 'A'] if 'RuoloClassic' in df_my_roster.columns else pd.DataFrame()
        mean_shots = round(float(att_rows['Tiri_90'].fillna(0).mean()), 1) if not att_rows.empty and 'Tiri_90' in att_rows.columns else 0.0
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Tiri/90 Attaccanti</div>
            <div class="metric-val" style="color: #4ade80;">{mean_shots} / 90</div>
        </div>
        """, unsafe_allow_html=True)
    with rk3:
        mid_rows = df_my_roster[df_my_roster['RuoloClassic'] == 'C'] if 'RuoloClassic' in df_my_roster.columns else pd.DataFrame()
        mean_kp = round(float(mid_rows['Key_Passes_90'].fillna(0).mean()), 1) if not mid_rows.empty and 'Key_Passes_90' in mid_rows.columns else 0.0
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">KP/90 Centrocampo</div>
            <div class="metric-val" style="color: #c084fc;">{mean_kp} / 90</div>
        </div>
        """, unsafe_allow_html=True)
    with rk4:
        df_def = df_my_roster[df_my_roster['RuoloMantra'].str.contains('Dc|Dd|Ds|B|E|M|Por', na=False)] if 'RuoloMantra' in df_my_roster.columns else pd.DataFrame()
        mean_suff = round(float(df_def['Pct_Sufficienza'].fillna(0).mean()), 1) if not df_def.empty and 'Pct_Sufficienza' in df_def.columns else 0.0
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Sufficienza D-Factor 🛡️</div>
            <div class="metric-val" style="color: #60a5fa;">{mean_suff}%</div>
        </div>
        """, unsafe_allow_html=True)
    with rk5:
        num_bl = len(df_my_roster[df_my_roster['Signal'].str.contains('BUY-LOW', na=False)]) if 'Signal' in df_my_roster.columns else 0
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Buy-Low in Rosa 🎯</div>
            <div class="metric-val" style="color: #38bdf8;">{num_bl}</div>
        </div>
        """, unsafe_allow_html=True)

    # 1. Alert for Players OUTSIDE SERIE A (Da Svincolare)
    if not out_serie_a.empty:
        svincoli_tot_cr = int(out_serie_a['Costo'].sum())
        st.markdown(f"""
        <div style="background: rgba(30, 10, 18, 0.90); border: 1.5px solid #ff3366; border-left: 6px solid #ff3366; border-radius: 10px; padding: 14px 18px; margin-bottom: 14px; box-shadow: 0 0 16px rgba(255, 51, 102, 0.25);">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h4 style="margin: 0; color: #ff4d6d; font-size: 1.05rem; font-weight: 800; text-shadow: 0 0 8px rgba(255, 77, 109, 0.4);">🚨 Calciatori Fuori dalla Serie A (Da Svincolare appena possibile)</h4>
                <span style="background: #ff3366; color: #ffffff; padding: 3px 10px; border-radius: 6px; font-weight: 800; font-size: 0.85rem; box-shadow: 0 0 10px rgba(255, 51, 102, 0.5);">+{svincoli_tot_cr} crediti recuperabili</span>
            </div>
            <p style="margin: 6px 0 10px 0; color: #e2e8f0; font-size: 0.92rem; font-weight: 500;">
                I calciatori contrassegnati con <code>*</code> non giocano più in Serie A (trasferiti all'estero, scesi in Serie B o svincolati). 
                Non porteranno voto né bonus: <b>svincolali alla prima sessione utile per liberare uno slot in rosa e recuperare i crediti spesi all'asta!</b>
            </p>
        """, unsafe_allow_html=True)
        for _, r in out_serie_a.iterrows():
            st.markdown(f"- 🚫 **{r['Giocatore']} \*** ({r['RuoloMantra']}) — Costo d'Asta: **{r['Costo']} cr** — *Fuori lista Serie A, non schierabile*")
        st.markdown("</div>", unsafe_allow_html=True)

    # 2. Loan Overview Callout
    cur_team_name = get_active_my_team()
    if not loans_in.empty or not loans_out.empty:
        st.markdown("""
        <div style="background: linear-gradient(135deg, rgba(11, 25, 45, 0.92) 0%, rgba(7, 18, 33, 0.95) 100%); border: 1.5px solid #00f0ff; border-left: 6px solid #00f0ff; border-radius: 10px; padding: 14px 18px; margin-bottom: 12px; box-shadow: 0 0 20px rgba(0, 240, 255, 0.25);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <h4 style="margin: 0; color: #00f0ff; font-size: 1.1rem; font-weight: 800; text-shadow: 0 0 10px rgba(0, 240, 255, 0.5);">📑 Accordi di Prestito Attivi della Tua Rosa</h4>
                <span style="background: rgba(0, 240, 255, 0.15); color: #00f0ff; border: 1px solid #00f0ff; border-radius: 6px; padding: 2px 8px; font-weight: 800; font-size: 0.82rem; box-shadow: 0 0 8px rgba(0, 240, 255, 0.3);">REGISTRO LEGA</span>
            </div>
        """, unsafe_allow_html=True)
        col_l1, col_l2 = st.columns(2)
        with col_l1:
            if not loans_in.empty:
                st.markdown("**📥 Prestiti in Entrata (IN):**")
                for _, r in loans_in.iterrows():
                    st.markdown(f"- 📥 **{r['Giocatore']}** ({r['RuoloMantra']}): *{r['Dettaglio_Prestito']}* (costo 0 cr) — <span style='color: #00f0ff; font-weight: 800;'>✅ Schierabile</span>", unsafe_allow_html=True)
            else:
                st.markdown("*(Nessun prestito in entrata)*")
        with col_l2:
            if not loans_out.empty:
                st.markdown("**📤 Prestiti in Uscita (OUT):**")
                for _, r in loans_out.iterrows():
                    st.markdown(f"- 📤 **{r['Giocatore']}** ({r['RuoloMantra']}): *{r['Dettaglio_Prestito']}* (asta: {r['Costo']} cr) — <span style='color: #ff9f1c; font-weight: 800;'>🚫 Non schierabile</span>", unsafe_allow_html=True)
            else:
                st.markdown("*(Nessun prestito in uscita)*")
        st.markdown("</div>", unsafe_allow_html=True)

        with st.expander("🛠️ Risolvi o Modifica Rapida Prestiti (Termina accordo)", expanded=False):
            st.markdown("Se un prestito è terminato o il giocatore è rientrato alla base, puoi risolverlo qui istantaneamente:")
            rc1, rc2 = st.columns(2)
            with rc1:
                if not loans_in.empty:
                    st.markdown("##### 📥 Termina Prestito in Entrata")
                    for _, r in loans_in.iterrows():
                        p_name_t = r['Giocatore']
                        if st.button(f"🔴 Risolvi prestito di {p_name_t}", key=f"t1_term_in_{p_name_t}", use_container_width=True):
                            ok, msg = terminate_loan(p_name_t, cur_team_name)
                            if ok:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
            with rc2:
                if not loans_out.empty:
                    st.markdown("##### 📤 Richiama Giocatore Prestato")
                    for _, r in loans_out.iterrows():
                        p_name_t = r['Giocatore']
                        borrower_t = r.get('Controparte', '')
                        if st.button(f"🟢 Richiama alla base {p_name_t}", key=f"t1_term_out_{p_name_t}", use_container_width=True):
                            ok, msg = terminate_loan(p_name_t, borrower_t)
                            if ok:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)

    meta_roster = get_league_metadata()
    st.markdown(f"""
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; background: linear-gradient(135deg, #0a1f38 0%, #061426 100%); border: 2px solid #00f0ff; border-radius: 10px; padding: 14px 22px; margin-top: 10px; margin-bottom: 16px; box-shadow: 0 0 22px rgba(0, 240, 255, 0.25);">
        <div style="display: flex; flex-direction: column; gap: 4px;">
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="font-size: 1.4rem; font-weight: 900; color: #ffffff; text-shadow: 0 0 12px rgba(0, 240, 255, 0.5);">🏆 Rosa Attiva: {cur_team_name}</span>
                <span style="background: linear-gradient(135deg, #0284c7, #00f0ff); color: #031326; border-radius: 6px; padding: 4px 12px; font-weight: 900; font-size: 0.95rem; box-shadow: 0 0 12px rgba(0, 240, 255, 0.5);">{len(df_my_roster)} calciatori</span>
            </div>
            <div style="font-size: 0.85rem; color: #7dd3fc; font-weight: 600;">
                📅 <b>Snapshot Rose:</b> {meta_roster.get('last_updated')} ({meta_roster.get('source')})
            </div>
        </div>
        <div style="color: #cbd5e1; font-weight: 700; font-size: 1.05rem;">
            Costo Asta: <b style="color: #00f0ff; font-size: 1.3rem; text-shadow: 0 0 12px rgba(0, 240, 255, 0.6);">{int(df_my_roster['Costo'].sum()) if not df_my_roster.empty and 'Costo' in df_my_roster.columns else 0} cr</b>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Universal Roster Import & Confirmation
    render_league_upload_section("tab1", df_master, label_title="📥 Carica / Aggiorna Rose di Lega da File (.xlsx, .xls, .csv)")

    st.subheader("Dettaglio Giocatori in Rosa")
    
    f_col1, f_col2 = st.columns([2, 1])
    with f_col1:
        # Filter by role
        ruoli_filter = st.multiselect(
            "Filtra per ruolo Mantra:",
            options=['Por', 'Dc', 'B', 'Dd', 'Ds', 'E', 'M', 'C', 'W', 'T', 'A', 'Pc'],
            default=[]
        )
    with f_col2:
        # Filter by loan / contract / injury status
        stato_filter = st.selectbox(
            "Filtra per stato prestito/disponibilità:",
            options=["TUTTI", "SOLO SCHIERABILI", "🔄 TUTTI I PRESTITI (IN & OUT)", "📥 PRESTITI IN", "📤 PRESTITI OUT", "🚑 INFORTUNATI / SQUALIFICATI", "🚫 FUORI SERIE A (DA SVINCOLARE)"],
            index=0
        )
    
    display_df = df_my_roster.copy()
    if ruoli_filter:
        pattern = '|'.join(ruoli_filter)
        display_df = display_df[display_df['RuoloMantra'].str.contains(pattern, na=False)]
        
    if stato_filter == "SOLO SCHIERABILI" and 'Schierabile' in display_df.columns:
        display_df = display_df[display_df['Schierabile'] == True]
    elif stato_filter == "🔄 TUTTI I PRESTITI (IN & OUT)" and 'Stato_Prestito' in display_df.columns:
        display_df = display_df[display_df['Stato_Prestito'].isin(['Prestito IN', 'Prestito OUT'])]
    elif stato_filter == "📥 PRESTITI IN" and 'Stato_Prestito' in display_df.columns:
        display_df = display_df[display_df['Stato_Prestito'] == 'Prestito IN']
    elif stato_filter == "📤 PRESTITI OUT" and 'Stato_Prestito' in display_df.columns:
        display_df = display_df[display_df['Stato_Prestito'] == 'Prestito OUT']
    elif stato_filter == "🚑 INFORTUNATI / SQUALIFICATI" and 'Stato_Disponibilita' in display_df.columns:
        display_df = display_df[display_df['Stato_Disponibilita'].isin(['Infortunato', 'Squalificato', 'In dubbio'])]
    elif stato_filter == "🚫 FUORI SERIE A (DA SVINCOLARE)" and 'Da_Svincolare' in display_df.columns:
        display_df = display_df[display_df['Da_Svincolare'] == True]
        
    cols_to_show = [
        'Badge_Disponibilita', 'Badge_Prestito', 'Giocatore', 'Dettaglio_Disponibilita', 'Dettaglio_Prestito', 'Squadra', 'RuoloMantra', 'Costo', 'Presenze',
        'MV_Stagione', 'Pct_Sufficienza', 'FM_Stagione', 'MV_Ultime3', 'Pct_Parate', 'Goals_Prevented', 'Errors_Leading_To_Goal', 'GF', 'ASS',
        'Tiri_90', 'xG_90', 'Delta_xG', 'Key_Passes_90', 'xA_90', 'Delta_xA', 'Signal'
    ]
    cols_to_show = [c for c in cols_to_show if c in display_df.columns]
    
    sorted_display = display_df.sort_values(by=['RuoloMantra', 'Costo'], ascending=[True, False]).reset_index(drop=True)
    
    # Quick Player Card Selector / Click hint
    qc1, qc2 = st.columns([2, 1])
    with qc1:
        squad_player_options = sorted(sorted_display['Giocatore'].unique().tolist())
        selected_quick_p = st.selectbox(
            "📋 Seleziona un calciatore per aprire la Scheda Dettagliata (Radar, Understat e Fanta):",
            options=["-- Seleziona o Clicca sulla Tabella --"] + squad_player_options,
            index=0,
            key="roster_player_card_select"
        )
    with qc2:
        st.caption("💡 **Interattività:** Clicca su qualsiasi riga della tabella per aprire istantaneamente il pop-up modale con grafici radar, statistiche reali e proiezioni.")

    # Interactive Table with on_select
    table_event = st.dataframe(
        sorted_display[cols_to_show],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row"
    )

    clicked_player = None
    if table_event and hasattr(table_event, 'selection'):
        sel_rows = table_event.selection.get('rows', [])
        if sel_rows and len(sel_rows) > 0:
            r_idx = sel_rows[0]
            if r_idx < len(sorted_display):
                clicked_player = sorted_display.iloc[r_idx]['Giocatore']

    if selected_quick_p and selected_quick_p != "-- Seleziona o Clicca sulla Tabella --":
        clicked_player = selected_quick_p

    if clicked_player:
        # Check if new player clicked to trigger dialog
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
            # Reopen button if closed
            col_b1, _ = st.columns([1, 2])
            with col_b1:
                if st.button(f"🔍 Riapri Scheda Profilo: {clicked_player}", type="primary", key="btn_reopen_dlg"):
                    show_player_profile_dialog(
                        clicked_player,
                        df_master,
                        calendar=calendar,
                        matchday=selected_giornata,
                        df_roster=df_my_roster
                    )

        # Also render a rich inline expander for immediate access without popups
        with st.expander(f"🔎 Scheda Calciatore: {clicked_player} (Visualizzazione Rapida in Pagina)", expanded=True):
            render_player_profile_content(
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
            file_name="mia_rosa_mantra.csv",
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
# TAB 2: FORMAZIONE CONSIGLIATA
# =============================================================
with tab_formazione:
    st.header(f"🏆 Formazione Consigliata per la Giornata {selected_giornata} — {current_active_team}")
    st.caption(f"💡 Formazione e modulo ottimizzati in tempo reale per la rosa di **{current_active_team}** ({len(df_my_roster)} calciatori).")
    st.markdown(
        "L'algoritmo valuta **tutti i 10 moduli ufficiali Mantra**, rispetta i vincoli di ruolo e massimizza la "
        "somma di $xFV$ + il **D-Factor Mantra con Portiere compreso** e bonus imbattibilità."
    )
    
    if df_my_roster.empty:
        st.warning("La tua rosa è vuota! Aggiungi dei giocatori nella scheda 'La Mia Rosa'.")
    else:
        # Prestiti in uscita and Fuori Serie A exclusion toggle
        c_opt1, c_opt2 = st.columns([3, 1])
        with c_opt1:
            exclude_uneligible = st.checkbox(
                "🚫 Escludi Calciatori Non Schierabili (Prestiti in uscita e Fuori Serie A *)",
                value=True,
                help="Se attivo, esclude automaticamente sia i calciatori che hai prestato ad altre squadre (Theate, Mrozek) sia quelli usciti dalla Serie A (Borrelli *)."
            )
            
        eligible_roster = df_my_roster.copy()
        if exclude_uneligible and 'Schierabile' in eligible_roster.columns:
            uneligible_rows = eligible_roster[eligible_roster['Schierabile'] == False]
            if not uneligible_rows.empty:
                desc_items = []
                for _, r in uneligible_rows.iterrows():
                    st_disp = r.get('Stato_Disponibilita', 'Disponibile')
                    if st_disp == 'Infortunato':
                        motivo = f"🚑 {r.get('Dettaglio_Disponibilita', 'infortunato')}"
                    elif st_disp == 'Squalificato':
                        motivo = "🟥 squalificato"
                    elif r.get('Stato_Prestito') == 'Prestito OUT':
                        motivo = f"prestito a {r.get('Controparte_Prestito', 'altra squadra')}"
                    else:
                        motivo = "fuori Serie A (* da svincolare)"
                    desc_items.append(f"**{r['Giocatore']}** ({motivo})")
                st.info(f"💡 Esclusi dalla formazione **{len(uneligible_rows)} giocatori non schierabili**: {'; '.join(desc_items)}.")
            eligible_roster = eligible_roster[eligible_roster['Schierabile'] == True]

        with st.expander("🚑 Gestione Disponibilità & Modifiche Manuali (Infortuni / Squalifiche / Dubbi)", expanded=False):
            st.markdown("""
            Visualizza lo stato medico ufficiale dei tuoi calciatori e **modificalo manualmente al volo** 
            (es. notizie dell'ultimo minuto da conferenze stampa o rientri anticipati).
            """)
            
            # List current injuries in squad
            curr_indisp = df_my_roster[df_my_roster['Stato_Disponibilita'] != 'Disponibile']
            if not curr_indisp.empty:
                st.markdown("**Calciatori della tua rosa con attenzioni mediche o disciplinari:**")
                for _, ci in curr_indisp.iterrows():
                    st.markdown(f"- {ci['Badge_Disponibilita']} **{ci['Giocatore']}** ({ci['Squadra']}): *{ci['Dettaglio_Disponibilita']}*")
            else:
                st.success("✅ Nessun infortunato o squalificato rilevato nella tua rosa!")
                
            st.markdown("---")
            st.markdown("**Modifica Stato per un Calciatore:**")
            ov_col1, ov_col2, ov_col3 = st.columns([2, 2, 1])
            with ov_col1:
                all_squad_sorted = sorted(df_my_roster['Giocatore'].unique().tolist())
                sel_p = st.selectbox("Seleziona calciatore:", options=all_squad_sorted, key="override_sel_p")
            with ov_col2:
                sel_status = st.selectbox(
                    "Imposta nuovo stato:",
                    options=["Disponibile (Forzato)", "Infortunato", "Squalificato", "In dubbio", "Ripristina Automatico"],
                    key="override_sel_st"
                )
            with ov_col3:
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button("💾 Applica", type="primary", key="btn_apply_override"):
                    if sel_status == "Ripristina Automatico":
                        clear_player_manual_override(sel_p)
                        st.success(f"Ripristinato stato automatico per {sel_p}!")
                    else:
                        set_player_manual_override(sel_p, sel_status)
                        st.success(f"Stato di {sel_p} impostato su '{sel_status}'!")
                    st.cache_data.clear()
                    st.rerun()
                    
            if st.button("🗑️ Azzera Tutti gli Override Manuali", key="btn_reset_all_overrides"):
                clear_all_manual_overrides()
                st.success("Tutti gli override manuali azzerati!")
                st.cache_data.clear()
                st.rerun()

        # Predict xFV for current squad
        df_my_proj = batch_predict_xfv(eligible_roster, matchday=selected_giornata, calendar=calendar)
        
        c_mod1, c_mod2 = st.columns([2, 1])
        with c_mod1:
            st.markdown(f"### 🎯 Ottimizzazione Tattica per la **{selected_giornata}ª Giornata**")
        with c_mod2:
            modulo_options = ["✨ Consigliato dall'AI (Migliore)"] + list(MANTRA_FORMATIONS.keys())
            selected_modulo_override = st.selectbox(
                "Modulo Tattico:",
                options=modulo_options,
                index=0,
                key="select_modulo_override"
            )
        
        # Optimize lineup
        if selected_modulo_override != "✨ Consigliato dall'AI (Migliore)":
            opt_res = optimize_best_mantra_lineup(df_my_proj, allowed_formations=[selected_modulo_override])
        else:
            opt_res = optimize_best_mantra_lineup(df_my_proj)
        
        if not opt_res:
            st.error("Impossibile schierare un modulo legale (verifica di avere almeno 1 Portiere e abbastanza difensori/attaccanti).")
        else:
            # Score KPIs
            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-title">Punti Attesi Totali</div>
                    <div class="metric-val">{opt_res['Punti_Attesi_Totali']}</div>
                </div>
                """, unsafe_allow_html=True)
            with k2:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-title">Modulo Consigliato</div>
                    <div class="metric-val" style="color: #34d399;">{opt_res['Modulo']}</div>
                </div>
                """, unsafe_allow_html=True)
            with k3:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-title">Somma xFV Titolari</div>
                    <div class="metric-val">{opt_res['Somma_xFV_Titolari']}</div>
                </div>
                """, unsafe_allow_html=True)
            with k4:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-title">Bonus D-Factor Atteso</div>
                    <div class="metric-val" style="color: #f59e0b;">+{opt_res['D_Factor_Atteso']} pts</div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("---")
            
            # Coverage Warning & Safe Alternatives Callout
            has_issues = opt_res.get('Ha_Problemi_Copertura', False)
            safe_alts = opt_res.get('Moduli_Sicuri_Alternativi', [])

            if has_issues:
                uncovered_list = opt_res.get('Slot_Scoperti', [])
                uncovered_badges = " ".join([f"`{s}`" for s in uncovered_list])
                st.warning(f"""
                ⚠️ **Attenzione alla Copertura Panchina per il modulo {opt_res['Modulo']}**:
                Questo modulo massimizza il punteggio potenziale assoluto (**{opt_res['Punti_Attesi_Totali']} pt**), ma in panchina **mancano riserve affidabili per gli slot: {uncovered_badges}**.  
                In caso di forfait o S.V. di un titolare in questi ruoli, la squadra rischia di non riuscire a effettuare una sostituzione legale o di dover forzare un cambio modulo.
                """, icon="⚠️")
                
                if safe_alts:
                    st.markdown("<div style='font-size: 0.95rem; font-weight: 700; color: #38bdf8; margin-top: 6px; margin-bottom: 4px;'>🛡️ Moduli Alternativi Consigliati Più Sicuri (Copertura 100%):</div>", unsafe_allow_html=True)
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
                    st.caption("💡 *Puoi selezionare il modulo alternativo direttamente dal menu a tendina in alto se preferisci una formazione a zero rischi di inferiorità numerica.*")
            else:
                st.success(f"🛡️ **Copertura Panchina Blindata (100%)**: Il modulo **{opt_res['Modulo']}** offre sia il punteggio più alto (**{opt_res['Punti_Attesi_Totali']} pt**) sia una copertura al 100% con riserve affidabili su ogni reparto in panchina!", icon="✅")

            st.markdown("---")
            
            # Starting 11 Layout
            st.subheader(f"🟢 Gli 11 Titolari (Modulo: {opt_res['Modulo']})")
            
            titolari_list = opt_res['Titolari']
            
            # Group into tactical lines: Portiere, Difesa, Centrocampo/Trequarti, Attacco
            por_line = [t for t in titolari_list if t['Slot_Assegnato'] == 'Por']
            def_line = [t for t in titolari_list if t['Slot_Assegnato'] in ['Dc', 'Dd', 'Ds', 'Dc/B', 'B']]
            mid_line = [t for t in titolari_list if t['Slot_Assegnato'] in ['E', 'E/W', 'M', 'M/C', 'C', 'C/T', 'W', 'W/T', 'T', 'T/A']]
            att_line = [t for t in titolari_list if t['Slot_Assegnato'] in ['A/Pc', 'W/A', 'Pc', 'A', 'T/A/Pc']]

            for section_name, section_players in [
                ("🧤 PORTIERE", por_line),
                ("🛡️ DIFESA (D-FACTOR REPARTO)", def_line),
                ("⚙️ CENTROCAMPO & TREQUARTI", mid_line),
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
                            
                            # Underlying metric details by role
                            metric_html = ""
                            pct_suff = float(p.get('Pct_Sufficienza', 0.0))
                            df_badge = str(p.get('D_Factor_Badge', ''))
                            mv_stag = float(p.get('MV_Stagione', 6.0))
                            
                            if slot == 'Por':
                                cs_p = int(float(p.get('Clean_Sheet_Prob', 0.0)) * 100)
                                exp_gs = float(p.get('Exp_GS', 0.0))
                                save_pct = float(p.get('Pct_Parate', 70.0))
                                team_xga = float(p.get('Team_xGA', 1.40))
                                bonus_imb = float(p.get('Bonus_Imbattibilita', 0.0))
                                gp = float(p.get('Goals_Prevented', 0.0))
                                gp90 = float(p.get('Goals_Prevented_90', 0.0))
                                blunders = int(p.get('Errors_Leading_To_Goal', 0))
                                blunder_badge = f' | <span style="color: #f87171;">⚠️ Blunders: {blunders}</span>' if blunders > 0 else ' | <span style="color: #4ade80;">🛡️ 0 blunder</span>'
                                metric_html = f'<div style="font-size: 0.8rem; color: #38bdf8; margin-top: 3px;">🧤 Prevented: <b>{gp:+.2f} ({gp90:+.2f}/90)</b> | Parate: <b>{save_pct:.1f}%</b>{blunder_badge} | Difesa: <b>{team_xga:.2f} xGA</b></div>'
                            elif any(r in slot for r in ['Dc', 'Dd', 'Ds', 'B']):
                                metric_html = f'<div style="font-size: 0.8rem; color: #93c5fd; margin-top: 3px;">🛡️ Sufficienza: <b>{pct_suff}%</b> | MV: <b>{mv_stag:.2f}</b></div>'
                            elif any(r in slot for r in ['E', 'M']):
                                kp = float(p.get('Key_Passes_90', 0.0))
                                metric_html = f'<div style="font-size: 0.8rem; color: #93c5fd; margin-top: 3px;">🛡️ Sufficienza: <b>{pct_suff}%</b> | KP: <b>{kp:.1f}/90</b></div>'
                            elif any(r in slot for r in ['W', 'T', 'C']):
                                kp = float(p.get('Key_Passes_90', 0.0))
                                xa = float(p.get('xA_90', 0.0))
                                metric_html = f'<div style="font-size: 0.8rem; color: #c4b5fd; margin-top: 3px;">🎯 KP: <b>{kp:.1f}/90</b> | xA: <b>{xa:.2f}</b></div>'
                            else:
                                tiri = float(p.get('Tiri_90', 0.0))
                                xg = float(p.get('xG_90', 0.0))
                                metric_html = f'<div style="font-size: 0.8rem; color: #6ee7b7; margin-top: 3px;">⚽ Tiri: <b>{tiri:.1f}/90</b> | xG: <b>{xg:.2f}</b></div>'
                                
                            bonus_html = ""
                            exp_gf = float(p.get('Exp_GF', 0.0))
                            exp_ass = float(p.get('Exp_ASS', 0.0))
                            if slot == 'Por':
                                bonus_imb = float(p.get('Bonus_Imbattibilita', 0.0))
                                exp_gs = float(p.get('Exp_GS', 0.0))
                                if bonus_imb > 0.05:
                                    bonus_html += f'<span style="background: #0369a1; color: #bae6fd; padding: 1px 5px; border-radius: 3px; font-size: 0.75rem; margin-right: 4px;">🛡️ CS: +{bonus_imb:.2f}pt</span>'
                                bonus_html += f'<span style="background: #7f1d1d; color: #fecaca; padding: 1px 5px; border-radius: 3px; font-size: 0.75rem;">⚠️ Gol subiti: -{exp_gs:.2f}</span>'
                            else:
                                if exp_gf >= 0.08:
                                    bonus_html += f'<span style="background: #064e3b; color: #6ee7b7; padding: 1px 5px; border-radius: 3px; font-size: 0.75rem; margin-right: 4px;">+GF: {exp_gf:.2f}</span>'
                                if exp_ass >= 0.08:
                                    bonus_html += f'<span style="background: #4c1d95; color: #c4b5fd; padding: 1px 5px; border-radius: 3px; font-size: 0.75rem;">+ASS: {exp_ass:.2f}</span>'
                                
                            sig = str(p.get('Signal', ''))
                            sig_html = ""
                            if 'BUY-LOW' in sig:
                                sig_html = f'<div class="metric-pill-buylow">🎯 BUY-LOW (ΔxG: {p.get("Delta_xG", 0)})</div>'
                            elif 'BOMBER PURO' in sig:
                                sig_html = '<div class="metric-pill-attack">🔥 BOMBER PURO</div>'
                            elif 'CREATORE ELITE' in sig:
                                sig_html = '<div class="metric-pill-create">👑 CREATORE ELITE</div>'
                            elif 'ANCORA' in df_badge:
                                sig_html = f'<div class="metric-pill-def">{df_badge}</div>'
                            elif 'RISCHIO' in df_badge:
                                sig_html = f'<div class="metric-pill-sellhigh">{df_badge}</div>'

                            bonus_block = f'<div style="margin-top: 3px;">{bonus_html}</div>' if bonus_html else ''
                            p_voto_pct = int(float(p.get('P_Voto', 0.90)) * 100)
                            tit_badge = str(p.get('Status_Titolarita', '🟢 TITOLARE FISSO'))
                            pres_txt = f"{p.get('Presenze_Tot', p.get('Presenze', 0))}/7 pres"
                            tit_html = f'<div style="font-size: 0.8rem; color: #94a3b8; margin-top: 2px;">{tit_badge} • <b>{p_voto_pct}%</b> a voto ({pres_txt})</div>'
                            
                            card_html = (
                                f'<div class="player-card">'
                                f'<div style="display: flex; justify-content: space-between; align-items: center;">'
                                f'<strong style="color: #00f0ff; font-size: 1.08rem; text-shadow: 0 0 10px rgba(0, 240, 255, 0.4);">[{p["Slot_Assegnato"]}] {p["Giocatore"]}</strong>'
                                f'<span class="{fdr_class}">FDR {fdr}</span>'
                                f'</div>'
                                f'<div style="font-size: 0.88rem; color: #f1f5f9; margin-top: 3px; font-weight: 600;">'
                                f'{p["Squadra"]} vs <b>{p["Match"]}</b>'
                                f'</div>'
                                f'{tit_html}'
                                f'<div style="font-size: 0.82rem; color: #94a3b8; margin-top: 2px;">'
                                f'Ruoli: <code style="background: rgba(0, 240, 255, 0.15); color: #00f0ff; border: 1px solid #00f0ff; border-radius: 4px; padding: 1px 6px; font-weight: bold;">{p["RuoloMantra"]}</code>'
                                f'</div>'
                                f'{metric_html}'
                                f'{bonus_block}'
                                f'{sig_html}'
                                f'<hr style="margin: 6px 0; border: none; border-top: 1.5px solid #132d4e;">'
                                f'<div style="display: flex; justify-content: space-between; font-size: 0.92rem; color: #f8fafc;">'
                                f'<span>Voto: <b>{p["Pred_Voto"]}</b></span>'
                                f'<span style="color: #00f0ff; font-weight: 900; font-size: 1.15rem; text-shadow: 0 0 12px rgba(0, 240, 255, 0.6);">xFV: {p["xFV"]}</span>'
                                f'</div>'
                                f'</div>'
                            )
                            st.markdown(card_html, unsafe_allow_html=True)

            # Tactical Rationale Expander
            with st.expander("🔍 Perché l'AI ha scelto questi 11 titolari? (Analisi Dati Reali & Sottostanti)", expanded=True):
                st.markdown("""
                L'algoritmo seleziona la formazione valutando le **metriche reali specifiche per ciascun ruolo**,
                evitando numeri irrilevanti e confrontando la resa attesa contro l'avversario di giornata:
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
                    df_b = str(t.get('D_Factor_Badge', ''))
                    
                    if slot_n == 'Por':
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
                        motivo = f"Shot-stopping d'élite ({gp:+.2f} gol evitati vs PSxG, {parate_p:.1f}% parate) e tenuta difensiva ({def_xga:.2f} xGA contro {t['Match']})."
                    elif any(r in slot_n for r in ['Dc', 'Dd', 'Ds', 'B']):
                        metrica_chiave = f"🛡️ Sufficienza: {suff_v:.1f}% (>=6) | MV: {mv_v:.2f}"
                        impatto_bonus = f"D-Factor Reparto (Voto atteso: {t['Pred_Voto']})"
                        motivo = f"Pilastro difensivo: garantisce costanza di voto ({suff_v:.1f}% >= 6) per massimizzare il bonus D-Factor."
                    elif any(r in slot_n for r in ['E', 'M']):
                        metrica_chiave = f"🛡️ Suff: {suff_v:.1f}% | KP: {kp_v:.1f}/90 | xA: {xa_v:.2f}"
                        impatto_bonus = f"+ASS: {exp_ass_v:.2f} | D-Factor filtro"
                        motivo = f"Equilibrio difensivo ({suff_v:.1f}% sufficienze) con spinta in costruzione ({kp_v:.1f} passaggi chiave/90)."
                    elif any(r in slot_n for r in ['W', 'T', 'C']):
                        metrica_chiave = f"🎯 KP: {kp_v:.1f}/90 | xA: {xa_v:.2f} | MV: {mv_v:.2f}"
                        impatto_bonus = f"+ASS: {exp_ass_v:.2f} | +GF: {exp_gf_v:.2f}"
                        motivo = f"Generatore di bonus: produce {kp_v:.1f} occasioni e {xa_v:.2f} assist attesi/90 contro {t['Match']}."
                    else: # Pc, A
                        metrica_chiave = f"⚽ Tiri: {tiri_v:.1f}/90 | xG: {xg_v:.2f} | MV: {mv_v:.2f}"
                        impatto_bonus = f"+GF: {exp_gf_v:.2f} (Bonus +3 atteso)"
                        motivo = f"Finalizzatore primario: alto volume offensivo ({tiri_v:.1f} tiri e {xg_v:.2f} xG/90), matchup favorevole."

                    p_voto_val = int(float(t.get('P_Voto', 0.90)) * 100)
                    pres_tot = t.get('Presenze_Tot', t.get('Presenze', 0))
                    stat_tit = t.get('Status_Titolarita', '🟢 TITOLARE')
                    mins_avg = int(t.get('Min_Per_App', 0))
                    tit_display = f"{p_voto_val}% ({pres_tot}/7) | ⏱️ {mins_avg}'/g"

                    analysis_rows.append({
                        'Slot': slot_n,
                        'Calciatore': t['Giocatore'],
                        'Squadra': t['Squadra'],
                        'Ruoli': t['RuoloMantra'],
                        'Avversario (FDR)': f"{t['Match']} (FDR {t['FDR']})",
                        'Titolarità P(Voto)': tit_display,
                        'Metrica Chiave di Ruolo': metrica_chiave,
                        'Bonus / Malus Atteso': impatto_bonus,
                        'Voto Atteso': t['Pred_Voto'],
                        'xFV': t['xFV'],
                        'Razionale Tattico': motivo
                    })
                df_anal = pd.DataFrame(analysis_rows)
                st.dataframe(df_anal, use_container_width=True, hide_index=True)

                # Ballottaggi Chiave Decisi dall'Algoritmo
                if 'Panchina' in opt_res and opt_res['Panchina']:
                    st.markdown("---")
                    st.markdown("##### ⚖️ Ballottaggi Chiave Decisi dall'Algoritmo (Chi è rimasto fuori e perché)")
                    
                    ballottaggi = []
                    
                    # 1. Ballottaggio Portiere
                    por_tit = [t for t in titolari_list if t['Slot_Assegnato'] == 'Por']
                    por_bench = [b for b in opt_res['Panchina'] if 'Por' in b.get('RuoloMantra', '')]
                    if por_tit and por_bench:
                        pt = por_tit[0]
                        pb = por_bench[0]
                        diff = round(float(pt.get('xFV', 0)) - float(pb.get('xFV', 0)), 2)
                        
                        pt_par = float(pt.get('Pct_Parate', 70))
                        pb_par = float(pb.get('Pct_Parate', 70))
                        pt_mv = float(pt.get('MV_Stagione', 6.0))
                        pb_mv = float(pb.get('MV_Stagione', 6.0))
                        pt_suff = float(pt.get('Pct_Sufficienza', 60.0))
                        pb_suff = float(pb.get('Pct_Sufficienza', 60.0))
                        pt_fdr = int(pt.get('FDR', 3))
                        pb_fdr = int(pb.get('FDR', 3))
                        pt_gp = float(pt.get('Goals_Prevented', 0.0))
                        pb_gp = float(pb.get('Goals_Prevented', 0.0))
                        pt_gp90 = float(pt.get('Goals_Prevented_90', 0.0))
                        pb_gp90 = float(pb.get('Goals_Prevented_90', 0.0))
                        pt_err = int(pt.get('Errors_Leading_To_Goal', 0))
                        pb_err = int(pb.get('Errors_Leading_To_Goal', 0))
                        
                        p_reasons = []
                        if pt_gp > pb_gp + 0.3:
                            p_reasons.append(f"maggior efficacia nel prevenire gol ({pt_gp:+.2f} vs {pb_gp:+.2f} Goals Prevented, {pt_gp90:+.2f}/90 vs {pb_gp90:+.2f}/90)")
                        elif pt_gp < pb_gp - 0.5:
                            p_reasons.append(f"nonostante un differenziale PSxG inferiore ({pt_gp:+.2f} vs {pb_gp:+.2f})")

                        if pt_err < pb_err:
                            p_reasons.append(f"maggior affidabilità e assenza di blunders ({pt_err} vs {pb_err} errori decisivi)")
                        elif pt_err > pb_err:
                            p_reasons.append(f"nonostante i {pt_err} errori decisivi commessi")

                        if pt_par > pb_par + 2.0:
                            p_reasons.append(f"maggior percentuale di parate ({pt_par:.1f}% vs {pb_par:.1f}%)")
                        elif pt_par < pb_par - 2.0:
                            p_reasons.append(f"nonostante la percentuale parate inferiore ({pt_par:.1f}% vs {pb_par:.1f}%)")

                        if pt_mv > pb_mv + 0.05:
                            p_reasons.append(f"miglior media voto ({pt_mv:.2f} vs {pb_mv:.2f})")
                        elif pt_mv < pb_mv - 0.05:
                            p_reasons.append(f"nonostante la media voto inferiore ({pt_mv:.2f} vs {pb_mv:.2f})")
                            
                        if pt_suff > pb_suff + 10:
                            p_reasons.append(f"maggior regolarità di sufficienze ({pt_suff:.0f}% vs {pb_suff:.0f}%)")
                            
                        if pt_fdr < pb_fdr:
                            p_reasons.append(f"matchup più agevole ({pt.get('Match')} FDR {pt_fdr} vs {pb.get('Match')} FDR {pb_fdr})")
                        elif pt_fdr > pb_fdr:
                            p_reasons.append(f"tenuta difensiva affidabile contro il matchup severo ({pt.get('Match')} FDR {pt_fdr} vs {pb.get('Match')} FDR {pb_fdr})")
                            
                        reason_txt = ", ".join(p_reasons) if p_reasons else "maggior fanta-valore atteso proiettato"
                        ballottaggi.append(
                            f"🧤 **Portiere**: **{pt['Giocatore']}** ({pt['xFV']} xFV) preferito a **{pb['Giocatore']}** ({pb['xFV']} xFV, diff: +{diff} pt) "
                            f"per {reason_txt}."
                        )
                        
                    # 2. Scelte d'Attacco e Ballottaggi di Reparto
                    att_tits = [t for t in titolari_list if any(r in t.get('Slot_Assegnato', '') for r in ['Pc', 'A', 'W', 'W/A', 'A/Pc'])]
                    att_bench = [b for b in opt_res['Panchina'] if any(r in parse_mantra_roles(b.get('RuoloMantra', '')) for r in ['Pc', 'A', 'W', 'W/T'])]
                    
                    if att_tits and att_bench:
                        first_bench_att = att_bench[0]
                        pc_in_tit = [t for t in att_tits if 'Pc' in parse_mantra_roles(t.get('RuoloMantra', ''))]
                        
                        if len(pc_in_tit) >= 2:
                            # Doppia Punta Centrale schierata
                            names_pc = " & ".join([f"**{p['Giocatore']}** ({p['xFV']} xFV)" for p in pc_in_tit])
                            ballottaggi.append(
                                f"⚽ **Tandem d'Attacco (Doppia Pc autorizzata nel modulo {opt_res['Modulo']})**: Schierati titolari insieme {names_pc}. "
                                f"**{first_bench_att['Giocatore']}** ({first_bench_att.get('RuoloMantra', '')}, {first_bench_att['xFV']} xFV) si posiziona in panchina come 1° cambio offensivo con massimo punteggio di subentro (EV {first_bench_att.get('Score_Panchina', 0):.2f})."
                            )
                        elif pc_in_tit and any('Pc' in parse_mantra_roles(b.get('RuoloMantra', '')) for b in att_bench):
                            pc_b = [b for b in att_bench if 'Pc' in parse_mantra_roles(b.get('RuoloMantra', ''))][0]
                            diff_pc = round(float(pc_in_tit[0].get('xFV', 0)) - float(pc_b.get('xFV', 0)), 2)
                            xg_tit = float(pc_in_tit[0].get('xG_90', 0.0))
                            xg_b = float(pc_b.get('xG_90', 0.0))
                            tiri_tit = float(pc_in_tit[0].get('Tiri_90', 0.0))
                            tiri_b = float(pc_b.get('Tiri_90', 0.0))
                            ballottaggi.append(
                                f"⚽ **Punta Centrale (Slot Pc)**: **{pc_in_tit[0]['Giocatore']}** ({pc_in_tit[0]['xFV']} xFV, {xg_tit:.2f} xG/90, {tiri_tit:.1f} tiri/90) "
                                f"ha vinto il ballottaggio su **{pc_b['Giocatore']}** ({pc_b['xFV']} xFV, diff: {diff_pc:+} pt, {xg_b:.2f} xG/90, {tiri_b:.1f} tiri/90) "
                                f"per maggior volume offensivo e titolarità contro {pc_in_tit[0].get('Match')}."
                            )
                        else:
                            lowest_tit_att = min(att_tits, key=lambda x: float(x.get('xFV', 0)))
                            diff_att = round(float(lowest_tit_att.get('xFV', 0)) - float(first_bench_att.get('xFV', 0)), 2)
                            ballottaggi.append(
                                f"⚽ **Reparto Offensivo**: **{lowest_tit_att['Giocatore']}** ({lowest_tit_att['xFV']} xFV) "
                                f"ha superato **{first_bench_att['Giocatore']}** ({first_bench_att['xFV']} xFV, diff: {diff_att:+} pt) "
                                f"in base alla configurazione tattica ottimale per il modulo **{opt_res['Modulo']}**."
                            )
                        
                    # 3. Equilibratore Tattico Mediano (Slot M obbligatorio)
                    m_tit = [t for t in titolari_list if t.get('Slot_Assegnato') == 'M']
                    if m_tit:
                        mt = m_tit[0]
                        ballottaggi.append(
                            f"🛡️ **Mediano Tattico (Slot M Obbligatorio)**: **{mt['Giocatore']}** ({mt['RuoloMantra']}) "
                            f"schierato come mediano di rottura obbligatorio per garantire la validità del modulo **{opt_res['Modulo']}**, "
                            f"mentre i centrocampisti offensivi (es. Adzic `C;T`) vengono valorizzati come mezzali d'inserimento o trequartisti."
                        )
                        
                    for b_text in ballottaggi:
                        st.markdown(f"- {b_text}")

            # Bench Section - Modalità MASTER
            st.markdown("---")
            st.subheader("🟡 Panchina Ufficiale Modalità MASTER - Ordine Posizionale Rigoroso (1-12)")
            st.info(
                "📋 **Regolamento Modalità MASTER Fantacalcio.it**: "
                "Comanda totalmente l'ordine di panchina (1-12). Se un titolare non prende voto (S.V./N.G.), "
                "il sistema scorre la panchina ed entra **sempre il primo calciatore a voto che configura un modulo valido** tra i 10 Mantra ufficiali. "
                "Numero massimo di sostituzioni consentite per incontro: **5**."
            )

            df_panchina = pd.DataFrame(opt_res['Panchina'])
            if not df_panchina.empty:
                bench_display = []
                for _, b in df_panchina.iterrows():
                    p_voto_pct = int(float(b.get('P_Voto', 0.85)) * 100)
                    pres_str = f"{b.get('Presenze_Tot', b.get('Presenze', 0))}/7 pres"
                    score_panchina = float(b.get('Score_Panchina', b.get('EV', 5.0)))
                    prob_voto6_bonus = float(b.get('Prob_Voto6_o_Bonus', 50.0))
                    bonus_pts = float(b.get('Bonus_Atteso', 0.0))
                    pct_suff = float(b.get('Pct_Sufficienza', 60.0))
                    pred_v = float(b.get('Pred_Voto', 6.0))
                    
                    bench_display.append({
                        'Pos': f"#{b.get('Posizione_Panchina', '-')}",
                        'Fascia Subentro': b.get('Fascia_Master', 'Rincalzo'),
                        'Calciatore': b.get('Giocatore', ''),
                        'Squadra': b.get('Squadra', ''),
                        'Ruoli': b.get('RuoloMantra', ''),
                        'Match (FDR)': f"{b.get('Match', '')} (FDR {b.get('FDR', 3)})",
                        'P(Voto ≥ 6 o Bonus)': f"{prob_voto6_bonus:.1f}%",
                        'Voto Atteso (Suff)': f"{pred_v:.2f} ({pct_suff:.0f}% >=6)",
                        'Bonus Atteso': f"+{bonus_pts:.2f} pt",
                        'Score Panchina': round(score_panchina, 2),
                        'Titolarità P(Voto)': f"{p_voto_pct}% ({pres_str})",
                        'Copertura Tattica': b.get('Copertura_Tattica', '')
                    })
                df_bench_view = pd.DataFrame(bench_display)
                st.dataframe(df_bench_view, use_container_width=True, hide_index=True)
                st.caption(
                    "🎯 **Criterio di Ordinamento Panchina**: I calciatori sono schierati in ordine decrescente di *Score Panchina*, "
                    "che misura la capacità del calciatore di portare un **voto superiore al 6.0** (sufficienza e rendimento difensivo) "
                    "o un **bonus (+3 GF, +1 ASS, Clean Sheet)**, moltiplicato per la titolarità $P(Voto)$."
                )

            # Interactive Master Substitution Simulator & Departmental Audit Expander
            with st.expander("🛡️ Simulatore & Stress-Test Sostituzioni MASTER (Cosa succede se manca un titolare?)", expanded=True):
                st.markdown(
                    "Verifica la tenuta tattica della panchina. L'algoritmo testa se la sequenza 1-12 garantisce "
                    "la copertura automatica per qualsiasi defezione dell'11 titolare."
                )
                
                # Part 1: Automated Departmental Stress-Test Matrix
                if 'Audit_Copertura' in opt_res and opt_res['Audit_Copertura'] is not None and not opt_res['Audit_Copertura'].empty:
                    st.markdown("##### 🧪 Matrice di Tenuta Reparti (Test di Simulazione Automatico)")
                    st.dataframe(opt_res['Audit_Copertura'], use_container_width=True, hide_index=True)

                st.markdown("---")
                st.markdown("##### 🎮 Simulatore Interattivo Forfait / S.V. in Tempo Reale")
                st.markdown("Seleziona uno o più titolari per simulare un'assenza e osservare in diretta la catena di subentro ufficiale MASTER:")
                
                starter_options = [t['Giocatore'] for t in titolari_list]
                sim_absent = st.multiselect(
                    "Simula assenza di:",
                    options=starter_options,
                    default=[],
                    help="Seleziona fino a 5 titolari per testare chi subentra e quale modulo viene configurato."
                )
                
                if sim_absent:
                    sim_result = simulate_master_substitutions(
                        titolari_list,
                        opt_res['Panchina'],
                        opt_res['Modulo'],
                        max_subs=5,
                        simulated_missing_names=sim_absent
                    )
                    
                    st.markdown(f"**Esito Simulazione: {sim_result['Cambi_Effettuati']} cambi effettuati su {len(sim_absent)} assenze simulate (Massimo 5 consentiti)**")
                    
                    for idx, sub in enumerate(sim_result['Sostituzioni']):
                        if '✅' in sub['Status']:
                            st.success(
                                f"**Cambio #{idx+1}**: Esce **{sub['Out']}** ({sub['Out_Slot']}) ➔ "
                                f"Subentra **{sub['In']}** (Posizione #{sub['In_Pos']} - `{sub['In_Roles']}`) [{sub['In_Fascia']}]. "
                                f"_{sub['Dettaglio']}_"
                            )
                        else:
                            st.error(
                                f"**Cambio #{idx+1}**: Esce **{sub['Out']}** ({sub['Out_Slot']}) ➔ "
                                f"**{sub['In']}**. _{sub['Dettaglio']}_"
                            )
                            
                    col_mod1, col_mod2, col_mod3 = st.columns(3)
                    with col_mod1:
                        st.metric("Modulo di Partenza", opt_res['Modulo'])
                    with col_mod2:
                        st.metric("Modulo Finale in Campo", sim_result['Modulo_Finale'])
                    with col_mod3:
                        all_covered = (sim_result['Cambi_Effettuati'] == len(sim_absent))
                        st.metric("Stato Formazione", "✅ Modulo Legale Completo" if all_covered else "⚠️ Squadra Incompleta")
                else:
                    st.caption("💡 *Seleziona uno o più giocatori dal menu a tendina qui sopra per simulare il loro forfait e vedere l'adattamento del modulo.*")

            # Formations Comparison Section
            with st.expander("📊 Confronto con gli altri moduli Mantra valutati", expanded=False):
                df_all_moduli = pd.DataFrame(opt_res['Tutti_Moduli_Valutati'])
                display_cols = ['Modulo', 'Punti_Totali', 'Delta_vs_Top', 'Stato_Copertura', 'xFV_Titolari', 'D_Factor', 'Punti_Robusti']
                cols_to_show = [c for c in display_cols if c in df_all_moduli.columns]
                st.dataframe(
                    df_all_moduli[cols_to_show],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        'Modulo': st.column_config.TextColumn('Modulo', width='medium'),
                        'Punti_Totali': st.column_config.NumberColumn('Punti Totali', format='%.2f'),
                        'Delta_vs_Top': st.column_config.NumberColumn('Δ vs Top', format='%+.2f'),
                        'Stato_Copertura': st.column_config.TextColumn('Copertura Panchina', width='large'),
                        'xFV_Titolari': st.column_config.NumberColumn('xFV Titolari', format='%.2f'),
                        'D_Factor': st.column_config.NumberColumn('D-Factor', format='%.2f'),
                        'Punti_Robusti': st.column_config.NumberColumn('Punteggio Robusto', format='%.2f'),
                    }
                )
                st.bar_chart(df_all_moduli.set_index('Modulo')['Punti_Totali'])

# =============================================================
# TAB 3: HUB SCAMBI & OTTIMIZZAZIONE ROSA
# =============================================================
with tab_scambi:
    st.header("🔄 Hub Scambi & Ottimizzazione Rosa Mantra")
    st.markdown(
        "Diagnostica i punti deboli strutturali della tua squadra, individua gli esuberi di fanta-valore "
        "e scopri le proposte di scambio **Win-Win** con i tuoi avversari di lega generate dall'algoritmo."
    )
    
    subtab_diag, subtab_radar, subtab_target, subtab_sim = st.tabs([
        "🏥 Diagnosi Punti Deboli & Asset",
        "🤝 Radar Scambi Intelligenti (Win-Win)",
        "🎯 Scambio Mirato su Obiettivo",
        "⚖️ Simulatore Scambi Libero"
    ])

    # -------------------------------------------------------------
    # SUBTAB 1: DIAGNOSI PUNTI DEBOLI & ASSET
    # -------------------------------------------------------------
    with subtab_diag:
        st.subheader("🏥 Check-up Strutturale & Analisi Carenze di Modulo")
        st.caption(
            "L'algoritmo analizza la distribuzione dei ruoli Mantra, i giocatori con presenze continuative, "
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
            
        diag_res = analyze_squad_weaknesses(target_diag_team, league_dict, df_master, matchday=selected_giornata)
        
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
                st.dataframe(
                    df_surplus[['Giocatore', 'RuoloMantra', 'Squadra', 'xFV', 'FM_Stagione', 'Signal', 'Motivo_Cessione']],
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Nessun calciatore di rilievo attualmente in esubero.")
                
            # Quota Coverage Matrix
            with st.expander("📐 Matrice di Copertura Ruoli Mantra (Quote Consigliate vs Attivi)", expanded=False):
                matrix_rows = []
                c_all = diag_res.get('Conteggio_Totale', {})
                c_act = diag_res.get('Conteggio_Attivi', {})
                for role, q in RECOMMENDED_QUOTAS.items():
                    act = c_act.get(role, 0)
                    tot = c_all.get(role, 0)
                    min_q = q['min_active']
                    tgt = q['target']
                    
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
                        'Attivi (con Presenze)': act,
                        'Totali in Rosa': tot,
                        'Minimo Consigliato': min_q,
                        'Target Ideale': tgt,
                        'Stato Copertura': status
                    })
                st.dataframe(pd.DataFrame(matrix_rows), use_container_width=True, hide_index=True)

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
        my_diag = analyze_squad_weaknesses(my_team, league_dict, df_master, matchday=selected_giornata)
        my_weak_roles = [w['Ruolo'] for w in my_diag.get('Punti_Deboli', [])]
        surplus_pnames = [p['Giocatore'] for p in my_diag.get('Surplus_Cedibili', [])]
        
        r_col1, r_col2, r_col3, r_col4 = st.columns([1.1, 1.1, 1.1, 1.3])
        with r_col1:
            target_role_opts = ["TUTTI"] + list(dict.fromkeys(my_weak_roles + ['Pc', 'M', 'Dc', 'Dd', 'Ds', 'W', 'A', 'T', 'E']))
            selected_target_role = st.selectbox(
                "Ruolo che vuoi RICEVERE:",
                options=target_role_opts,
                index=1 if my_weak_roles else 0,
                help="Seleziona il ruolo che intendi rinforzare. Di default è impostato sulla tua priorità debole principale."
            )
        with r_col2:
            give_opts = ["TUTTI"] + surplus_pnames
            selected_give_player = st.selectbox(
                "Calciatore che vuoi CEDERE:",
                options=give_opts,
                index=0,
                help="Puoi filtrare per un tuo specifico esubero o lasciare TUTTI per esplorare tutte le combinazioni."
            )
        with r_col3:
            opp_opts = ["TUTTI"] + [t for t in league_teams if t != my_team]
            selected_opp_team = st.selectbox(
                "Filtra per Squadra Avversaria:",
                options=opp_opts,
                index=0,
                help="Scegli se trattare con un avversario specifico o scansionare l'intera lega."
            )
        with r_col4:
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
            proposals = find_win_win_trades(
                my_team_name=my_team,
                league_data=league_dict,
                df_master=df_master,
                matchday=selected_giornata,
                target_role_filter=selected_target_role,
                give_player_filter=selected_give_player,
                opp_team_filter=selected_opp_team,
                min_starter_filter=selected_starter_filter,
                max_proposals=30
            )
            
        if not proposals:
            st.warning("Nessuna proposta Win-Win trovata con i filtri correnti. Prova a impostare 'TUTTI' nei filtri per allargare la ricerca.")
        else:
            st.success(f"🎯 Trovate **{len(proposals)} proposte di scambio Win-Win** su misura per la tua rosa!")
            
            for idx, prop in enumerate(proposals[:15], 1):
                opp = prop['Squadra_Avversaria']
                score = prop['Score']
                cedi = prop['Tu_Cedi']
                ricevi = prop['Tu_Ricevi']
                delta_xfv = prop['Delta_xFV']
                
                with st.container():
                    st.markdown(f"""
                    <div style="background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 16px 20px; margin-bottom: 18px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid #334155; padding-bottom: 8px;">
                            <div>
                                <span style="font-size: 1.15rem; font-weight: 700; color: #f8fafc;">#{idx} Proposta con: <span style="color: #38bdf8;">{opp}</span></span>
                                <span style="margin-left: 10px; background: #0284c7; color: white; padding: 2px 8px; border-radius: 6px; font-size: 0.78rem; font-weight: 600;">Ruolo: {prop['Ruolo_Target']}</span>
                            </div>
                            <div>
                                <span style="background: #10b981; color: white; padding: 4px 10px; border-radius: 12px; font-weight: 700; font-size: 0.85rem;">
                                    Win-Win Index: {int(score)} / 200
                                </span>
                            </div>
                        </div>
                    """, unsafe_allow_html=True)
                    
                    # Columns for Cedi and Ricevi
                    c_give, c_rec = st.columns(2)
                    with c_give:
                        sig_badge = f"<span style='background:#f97316;color:white;padding:1px 6px;border-radius:4px;font-size:0.75rem;font-weight:bold;'>{cedi['Signal']}</span>" if 'SELL-HIGH' in cedi['Signal'] else ""
                        if 'Por' in cedi.get('RuoloMantra', ''):
                            adv_give_html = f"<div style='color: #38bdf8; font-size: 0.80rem; margin-top: 2px;'>🧤 G.Prevented: <b>{cedi.get('Goals_Prevented', 0.0):+.2f} ({cedi.get('Goals_Prevented_90', 0.0):+.2f}/90)</b> | Parate: <b>{cedi.get('Pct_Parate', 70.0):.1f}%</b> | Blunders: <b>{cedi.get('Errors_Leading_To_Goal', 0)}</b></div>"
                        else:
                            adv_give_html = f"<div style='color: #6ee7b7; font-size: 0.80rem; margin-top: 2px;'>⚽ xG: <b>{cedi.get('xG_Tot', 0.0):.2f} ({cedi.get('xG_90', 0.0):.2f}/90)</b> | Tiri: <b>{cedi.get('Tiri_90', 0.0):.1f}/90</b> | ΔxG: <b>{cedi.get('Delta_xG', 0.0):+.2f}</b></div>"
                        st.markdown(f"""
                        <div style="background: rgba(239, 68, 68, 0.08); border-left: 4px solid #ef4444; padding: 10px 14px; border-radius: 6px;">
                            <div style="font-size: 0.82rem; color: #ef4444; font-weight: bold; text-transform: uppercase;">🔴 Tu Cedi</div>
                            <div style="font-size: 1.1rem; font-weight: bold; color: #f8fafc;">{cedi['Giocatore']} {sig_badge}</div>
                            <div style="color: #cbd5e1; font-size: 0.88rem;">{cedi['Squadra']} — <b>{cedi['RuoloMantra']}</b></div>
                            <div style="color: #94a3b8; font-size: 0.82rem; margin-top: 4px;">xFV Giornata: <b>{cedi['xFV']:.2f}</b> | FM Stagione: <b>{cedi['FM']:.2f}</b></div>
                            {adv_give_html}
                        </div>
                        """, unsafe_allow_html=True)
                        
                    with c_rec:
                        delta_color = "#10b981" if delta_xfv >= 0 else "#f59e0b"
                        sig_rec_badge = f"<span style='background:#0284c7;color:white;padding:1px 6px;border-radius:4px;font-size:0.75rem;font-weight:bold;'>BUY-LOW</span>" if ricevi['Is_Buy_Low'] else ""
                        bench_badge = "<span style='background:#475569;color:white;padding:1px 6px;border-radius:4px;font-size:0.75rem;'>Panchina Avversaria</span>" if ricevi['Is_Bench_In_Opponent'] else ""
                        
                        # Real Starter Status Badge
                        status_tit = ricevi.get('Status_Titolarita', 'TITOLARE')
                        tit_color = {
                            'TITOLARE': '#16a34a',
                            'CO_TITOLARE': '#ca8a04',
                            'SUBENTRANTE': '#ea580c',
                            'MARGINALE': '#dc2626'
                        }.get(status_tit, '#64748b')
                        tit_badge = f"<span style='background:{tit_color};color:white;padding:1px 6px;border-radius:4px;font-size:0.75rem;font-weight:bold;'>{ricevi.get('Badge_Titolarita', status_tit)}</span>"
                        stash_badge = f"<span style='background:#d97706;color:white;padding:1px 6px;border-radius:4px;font-size:0.75rem;font-weight:bold;'>🩹 STASH INFORTUNIO</span>" if ricevi.get('Is_Stash_Injury') else ""

                        if 'Por' in ricevi.get('RuoloMantra', ''):
                            adv_rec_html = f"<div style='color: #38bdf8; font-size: 0.80rem; margin-top: 2px;'>🧤 G.Prevented: <b>{ricevi.get('Goals_Prevented', 0.0):+.2f} ({ricevi.get('Goals_Prevented_90', 0.0):+.2f}/90)</b> | Parate: <b>{ricevi.get('Pct_Parate', 70.0):.1f}%</b> | Blunders: <b>{ricevi.get('Errors_Leading_To_Goal', 0)}</b></div>"
                        else:
                            adv_rec_html = f"<div style='color: #6ee7b7; font-size: 0.80rem; margin-top: 2px;'>⚽ xG: <b>{ricevi.get('xG_Tot', 0.0):.2f} ({ricevi.get('xG_90', 0.0):.2f}/90)</b> | KP: <b>{ricevi.get('Key_Passes_90', 0.0):.1f}/90</b> | ΔxG: <b>{ricevi.get('Delta_xG', 0.0):+.2f}</b></div>"

                        st.markdown(f"""
                        <div style="background: rgba(16, 185, 129, 0.08); border-left: 4px solid #10b981; padding: 10px 14px; border-radius: 6px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <span style="font-size: 0.82rem; color: #10b981; font-weight: bold; text-transform: uppercase;">🟢 Tu Ricevi</span>
                                <span style="color: {delta_color}; font-weight: bold; font-size: 0.85rem;">Delta: {'+' if delta_xfv > 0 else ''}{delta_xfv} xFV</span>
                            </div>
                            <div style="font-size: 1.1rem; font-weight: bold; color: #f8fafc; margin: 3px 0;">
                                {ricevi['Giocatore']} {tit_badge} {stash_badge} {sig_rec_badge} {bench_badge}
                            </div>
                            <div style="color: #cbd5e1; font-size: 0.88rem;">{ricevi['Squadra']} — <b>{ricevi['RuoloMantra']}</b></div>
                            <div style="color: #94a3b8; font-size: 0.82rem; margin-top: 4px;">
                                xFV Giornata: <b>{ricevi['xFV']:.2f}</b> | FM: <b>{ricevi['FM']:.2f}</b> | Sufficienze: <b>{ricevi.get('Pct_Sufficienza', 0)}%</b>
                            </div>
                            {adv_rec_html}
                            <div style="color: #38bdf8; font-size: 0.80rem; margin-top: 2px;">
                                ⏱️ Minuti Reali: <b>~{ricevi.get('Min_Per_Pres', 0)} min/partita</b> ({ricevi.get('Pct_Minuti', 0)}% dei minuti totali)
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                        if ricevi.get('Is_Stash_Injury'):
                            st.caption(f"🩹 *Opportunità Stash: {ricevi['Giocatore']} ha un problema fisico lieve ({ricevi.get('Injury_Detail', 'rientro a breve')}). Ottima occasione per strappare un giocatore di valore a un avversario che cerca titolari sani subito.*")
                        elif ricevi.get('Is_Subentrante'):
                            st.caption("⚠️ *Attenzione: questo giocatore è una riserva/subentrante in Serie A (entra solo negli spezzoni finali).*")
                        
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
                            st.session_state['sim_prefill_give'] = [cedi['Giocatore']]
                            st.session_state['sim_prefill_receive'] = [ricevi['Giocatore']]
                            st.session_state['sim_prefill_opp'] = opp
                            st.session_state['sim_prefill_mode'] = "🤝 Trattativa di Lega (Inter-Squadra)"
                            st.success(f"✅ Scambio tra {cedi['Giocatore']} e {ricevi['Giocatore']} pre-impostato! Apri la scheda '⚖️ Simulatore Scambi Libero' per l'analisi completa.")
                            
                    st.markdown("</div>", unsafe_allow_html=True)

    # -------------------------------------------------------------
    # SUBTAB 3: SCAMBIO MIRATO SU OBIETTIVO (REVERSE TRADE FINDER)
    # -------------------------------------------------------------
    with subtab_target:
        st.subheader("🎯 Scambio Mirato su Obiettivo (Reverse Trade Finder)")
        st.markdown(
            "Cerca uno o più calciatori che desideri strappare a un avversario di lega. "
            "L'algoritmo analizza le **criticità strutturali dell'avversario** e formula pacchetti d'offerta su misura per convincerlo, "
            "dando **priorità ai tuoi esuberi (surplus)** e attingendo a panchinari o titolari solo se necessario per chiudere uno scambio vantaggioso."
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
                    key="target_finder_opp_team"
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
                roles = r_opp.get('RuoloMantra', '')
                costo = int(r_opp.get('Costo', 0))
                fm = float(r_opp.get('FM_Stagione', 0.0))
                label = f"{pname} ({roles}) — {r_opp.get('Squadra', '')} [Costo {costo}, FM {fm:.2f}]"
                opp_player_labels.append(label)
                label_to_pname[label] = pname

            with col_sel_targs:
                selected_labels = st.multiselect(
                    "2. Scegli il/i Giocatore/i da Chiedere all'Avversario:",
                    options=opp_player_labels,
                    key="target_finder_selected_players",
                    help="Puoi selezionare un singolo obiettivo (es. una prima punta, un top difensore) o un pacchetto di 2 giocatori."
                )
                selected_target_pnames = [label_to_pname[lbl] for lbl in selected_labels]

            # Options Row
            col_opt1, col_opt2 = st.columns([1.6, 1])
            with col_opt1:
                allow_starters_flag = st.checkbox(
                    "Attingi anche ai tuoi Titolari/Panchinari chiave se necessario",
                    value=True,
                    help="Se attivo, consente all'algoritmo di inserire nei pacchetti anche giocatori della tua rotazione o titolari se i soli surplus non bastano per valore. Vengono proposti SOLO scambi in cui la tua formazione ne esce complessivamente migliorata o equivalente."
                )
            with col_opt2:
                pkg_size_label = st.selectbox(
                    "Formato Pacchetto Offerta:",
                    options=["Tutti i formati (1x1, 2x1, 2x2)", "Solo 1x1 (Scambio Diretto)", "Solo Pacchetti Multipli (2x1, 2x2)"],
                    key="target_finder_pkg_size"
                )
                pkg_types_map = {
                    "Tutti i formati (1x1, 2x1, 2x2)": ('1x1', '2x1', '2x2'),
                    "Solo 1x1 (Scambio Diretto)": ('1x1',),
                    "Solo Pacchetti Multipli (2x1, 2x2)": ('2x1', '2x2')
                }
                chosen_pkg_types = pkg_types_map[pkg_size_label]

            # Show Instant Rival Check-up Card
            with st.expander(f"🔍 Check-up Immediato Carenze di {target_opp_team} (Perché dovrebbero accettare)", expanded=False):
                opp_diag = analyze_squad_weaknesses(target_opp_team, league_dict, df_master, matchday=selected_giornata)
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
                    target_proposals = find_trades_for_target_players(
                        my_team_name=my_team,
                        opp_team_name=target_opp_team,
                        target_player_names=selected_target_pnames,
                        league_data=league_dict,
                        df_master=df_master,
                        matchday=selected_giornata,
                        allow_starters=allow_starters_flag,
                        package_types=chosen_pkg_types
                    )

                if not target_proposals:
                    st.warning(
                        f"Non sono state trovate combinazioni compatibili per acquisire **{', '.join(selected_target_pnames)}**. "
                        "Suggerimento: prova ad attivare l'opzione per includere anche titolari/panchinari, "
                        "oppure valuta una contropartita diversa."
                    )
                else:
                    st.success(f"🎯 Trovate **{len(target_proposals)} proposte di scambio strutturate** per acquisire **{', '.join(selected_target_pnames)}**!")

                    for p_idx, prop in enumerate(target_proposals):
                        card_bg = "rgba(16, 185, 129, 0.05)" if "Soli Surplus" in prop['Tipo_Pacchetto'] else "rgba(14, 165, 233, 0.05)"
                        card_border = "#10b981" if "Soli Surplus" in prop['Tipo_Pacchetto'] else "#0ea5e9"
                        
                        st.markdown(f"""
                        <div style="background: {card_bg}; border: 1.5px solid {card_border}; border-radius: 10px; padding: 16px 20px; margin-bottom: 20px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                                <div>
                                    <span style="font-weight: 800; font-size: 1.15rem; color: #ffffff;">Offerta #{p_idx+1}</span>
                                    <span style="margin-left: 10px; background: rgba(255,255,255,0.1); border-radius: 6px; padding: 4px 10px; font-weight: 700; font-size: 0.85rem; color: #38bdf8;">
                                        {prop['Tipo_Pacchetto']}
                                    </span>
                                </div>
                                <div style="display: flex; gap: 12px; align-items: center;">
                                    <span style="font-weight: 700; font-size: 0.95rem; color: #f59e0b;">🎯 Appetibilità Avversario: {prop['Appetibilita_Avversario']}%</span>
                                    <span style="font-weight: 800; font-size: 0.95rem; color: {'#10b981' if prop['Delta_Punti_Titolari'] >= 0 else '#f97316'};">
                                        📈 Impatto Titolari: {prop['Delta_Punti_Titolari']:+.2f} pt
                                    </span>
                                </div>
                            </div>
                        """, unsafe_allow_html=True)

                        col_give, col_rec = st.columns(2)
                        with col_give:
                            st.markdown("##### 🔴 Cosa Cedi Tu")
                            for p in prop['Tu_Cedi']:
                                tier_color = "#10b981" if p['Tier'] == 'SURPLUS' else ("#0ea5e9" if p['Tier'] == 'PANCHINARO' else "#f59e0b")
                                st.markdown(f"""
                                <div style="background: rgba(255,255,255,0.04); border-left: 3px solid {tier_color}; padding: 8px 12px; border-radius: 6px; margin-bottom: 6px;">
                                    <div style="font-weight: 700; color: #ffffff;">{p['Giocatore']} <span style="font-weight: 450; color: #94a3b8; font-size: 0.85rem;">({p['RuoloMantra']} - {p['Squadra']})</span></div>
                                    <div style="font-size: 0.8rem; color: #cbd5e1;">Status: <strong style="color: {tier_color};">{p['Tier']}</strong> | FM: <strong>{p['FM']:.2f}</strong> | xFV: <strong>{p['xFV']:.2f}</strong> | Costo: <strong>{p['Costo']}</strong></div>
                                </div>
                                """, unsafe_allow_html=True)
                            st.caption(f"Totale xFV Offerto: **{prop['Totale_xFV_Ceduti']}**")

                        with col_rec:
                            st.markdown(f"##### 🟢 Cosa Ricevi da {target_opp_team}")
                            for p in prop['Tu_Ricevi']:
                                st.markdown(f"""
                                <div style="background: rgba(16, 185, 129, 0.08); border-left: 3px solid #10b981; padding: 8px 12px; border-radius: 6px; margin-bottom: 6px;">
                                    <div style="font-weight: 700; color: #ffffff;">{p['Giocatore']} <span style="font-weight: 450; color: #94a3b8; font-size: 0.85rem;">({p['RuoloMantra']} - {p['Squadra']})</span></div>
                                    <div style="font-size: 0.8rem; color: #cbd5e1;">FM: <strong>{p['FM']:.2f}</strong> | xFV: <strong>{p['xFV']:.2f}</strong> | Costo: <strong>{p['Costo']}</strong></div>
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
                        if st.button(f"⚖️ Apri nel Simulatore Scambi Libero", key=f"btn_sim_target_{p_idx}"):
                            st.session_state['sim_prefill_give'] = prop['Simulazione_Payload']['give_names']
                            st.session_state['sim_prefill_receive'] = prop['Simulazione_Payload']['receive_names']
                            st.session_state['sim_prefill_opp'] = target_opp_team
                            st.session_state['sim_prefill_mode'] = "🤝 Trattativa di Lega (Inter-Squadra)"
                            st.success("✅ Scambio pre-impostato nel simulatore! Apri la scheda '⚖️ Simulatore Scambi Libero' per l'analisi completa.")

                        st.markdown("</div>", unsafe_allow_html=True)

    # -------------------------------------------------------------
    # SUBTAB 4: SIMULATORE SCAMBI LIBERO
    # -------------------------------------------------------------
    with subtab_sim:
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
            horizon = st.slider("Orizzonte di valutazione (Giornate future):", min_value=3, max_value=15, value=6, step=1, key="sim_horizon_slider")
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
            else:
                trade_res = evaluate_trade(
                    give_selection,
                    receive_selection,
                    df_master,
                    start_matchday=selected_giornata,
                    horizon=horizon,
                    calendar=calendar,
                    weight_mode=chosen_weight_mode
                )
                
                if 'error' in trade_res:
                    st.error(trade_res['error'])
                else:
                    st.markdown("---")
                    
                    # Verdict Banner
                    verdict_color = {
                        'green': '#15803d',
                        'lightgreen': '#16a34a',
                        'gray': '#475569',
                        'orange': '#ea580c',
                        'red': '#dc2626'
                    }.get(trade_res['StatusColor'], '#334155')
                    
                    is_multi_pkg = trade_res.get('Is_Multi', False)
                    pkg_badge = f"Pacchetto {trade_res.get('Num_Ceduti', 1)} vs {trade_res.get('Num_Ricevuti', 1)}" if is_multi_pkg else "Scambio Singolo 1 vs 1"
                    sub_title_mode = "Valutazione a Media Ponderata Bilanciata" if chosen_weight_mode != "raw_sum" else "Valutazione a Somma Grezza Cumulativa"

                    st.markdown(f"""
                    <div style="background-color: {verdict_color}; padding: 18px; border-radius: 10px; color: white; text-align: center; margin-bottom: 20px;">
                        <div style="font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1px; opacity: 0.9; margin-bottom: 4px;">{pkg_badge} • {sub_title_mode}</div>
                        <h2 style="margin: 0; color: white;">{trade_res['Verdetto']}</h2>
                        <p style="margin: 5px 0 0 0; font-size: 1.15rem;">
                            Differenziale Atteso: <b>{'+' if trade_res['Delta_Totale_xFV'] > 0 else ''}{trade_res['Delta_Totale_xFV']} xFV</b> 
                            sulle prossime {trade_res['Giornate_Valutate']} giornate 
                            (<b>{'+' if trade_res.get('Delta_Medio_Partita', 0) > 0 else ''}{trade_res.get('Delta_Medio_Partita', 0):.2f} xFV/partita</b> a slot)
                        </p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Package Weights Breakdown (if multi-player)
                    if is_multi_pkg and chosen_weight_mode != 'raw_sum':
                        with st.expander("🔍 Dettaglio Pesi e Bilanciamento del Pacchetto", expanded=False):
                            col_pw1, col_pw2 = st.columns(2)
                            with col_pw1:
                                st.markdown("**🔴 Pesi Assegnati ai Calciatori Ceduti:**")
                                for p, w in trade_res.get('Pesi_Ceduti', {}).items():
                                    st.write(f"- **{p}**: peso `{w*100:.1f}%`")
                                st.caption(f"Somma cumulativa grezza ceduti: **{trade_res.get('xFV_Ceduti_Raw_Tot', 0)} xFV**")
                            with col_pw2:
                                st.markdown("**🟢 Pesi Assegnati ai Calciatori Ricevuti:**")
                                for p, w in trade_res.get('Pesi_Ricevuti', {}).items():
                                    st.write(f"- **{p}**: peso `{w*100:.1f}%`")
                                st.caption(f"Somma cumulativa grezza ricevuti: **{trade_res.get('xFV_Ricevuti_Raw_Tot', 0)} xFV**")
                            st.info("💡 La media ponderata tutela il valore degli scambi multipli (es. 2v1 o 4v4): il confronto avviene a livello di rendimento per slot titolare, pesando maggiormente il calciatore di vertice di ciascun gruppo.")

                    # Metric comparison
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

                    # If Goalkeepers are involved in the trade, display specialized shot-stopping metrics
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
                        st.metric("Tiri/90 Ricevuti (pond.)", f"{trade_res.get('Tiri_Ricevuti_90', 0.0)} / 90")
                    with ts2:
                        st.metric("Tiri/90 Ceduti (pond.)", f"{trade_res.get('Tiri_Ceduti_90', 0.0)} / 90")
                    with ts3:
                        st.metric("xG/90 Ricevuti (pond.)", f"{trade_res.get('xG_Ricevuti_90', 0.0)}")
                    with ts4:
                        st.metric("xG/90 Ceduti (pond.)", f"{trade_res.get('xG_Ceduti_90', 0.0)}")

                    ta1, ta2, ta3, ta4 = st.columns(4)
                    with ta1:
                        st.metric("xA/90 Ricevuti (pond.)", f"{trade_res.get('xA_Ricevuti_90', 0.0)}")
                    with ta2:
                        st.metric("xA/90 Ceduti (pond.)", f"{trade_res.get('xA_Ceduti_90', 0.0)}")
                    with ta3:
                        st.metric("Delta xG Ricevuti", f"{trade_res.get('Delta_xG_Ricevuti', 0.0):+.2f}", help="Negativo = Buy-low (sfortuna)")
                    with ta4:
                        st.metric("Delta xG Ceduti", f"{trade_res.get('Delta_xG_Ceduti', 0.0):+.2f}", help="Positivo = Sell-high (fortuna)")

                    td1, td2, td3, td4 = st.columns(4)
                    with td1:
                        st.metric("Sufficienza D-Factor Ricevuti", f"{trade_res.get('Suff_Ricevuti_DFactor', 0.0)}%")
                    with td2:
                        st.metric("Sufficienza D-Factor Ceduti", f"{trade_res.get('Suff_Ceduti_DFactor', 0.0)}%")
                    with td3:
                        st.metric("Media Voto D-Factor Ricevuti", f"{trade_res.get('MV_Ricevuti_DFactor', 0.0)}")
                    with td4:
                        st.metric("Media Voto D-Factor Ceduti", f"{trade_res.get('MV_Ceduti_DFactor', 0.0)}")
                        
                    st.subheader("💡 Analisi e Motivazioni Statistiche")
                    for mot in trade_res['Motivazioni']:
                        st.markdown(f"- {mot}")
                        
                    st.subheader("📈 Proiezione Giornata per Giornata")
                    timeline_df = trade_res['Timeline']
                    
                    # Chart
                    chart_data = timeline_df[['Giornata', 'xFV_Ceduti', 'xFV_Ricevuti']].set_index('Giornata')
                    st.bar_chart(chart_data)
                    
                    # Detailed breakdown table
                    st.dataframe(
                        timeline_df[['Giornata', 'xFV_Ceduti', 'xFV_Ricevuti', 'Delta_Giornata', 'Match_Ceduti', 'Match_Ricevuti']],
                        use_container_width=True,
                        hide_index=True
                    )

# =============================================================
# TAB 4: TUTTE LE ROSE & LEGA
# =============================================================
with tab_lega:
    st.header("👥 Tutte le Rose & Partecipanti della Lega")
    st.markdown("Esplora e confronta le rose di tutte le 12 squadre della lega per pianificare strategie, prestiti e scambi mirati.")
    
    # League Summary Table
    df_league_summary = get_league_summary(df_master)
    if not df_league_summary.empty:
        st.subheader("📊 Panoramica & Confronto Squadre della Lega")
        st.dataframe(df_league_summary, use_container_width=True, hide_index=True)
        
    st.markdown("---")

    # League Loans & Agreements Registry
    loan_map_all, df_all_loans = build_loan_registry()
    if not df_all_loans.empty:
        st.subheader("📑 Tabellone Accordi & Prestiti di Lega")
        st.markdown("Tutti i prestiti in entrata, in uscita e contratti speciali formalizzati tra le squadre della lega.")
        
        l_c1, l_c2, l_c3, l_c4 = st.columns(4)
        l_c1.metric("Prestiti Attivi", len(df_all_loans))
        tot_loan_credits = int(df_all_loans['Costo_Asta'].sum())
        l_c2.metric("Valore Crediti d'Asta", f"{tot_loan_credits} cr")
        teams_involved = len(set(df_all_loans['Proprietario'].tolist() + df_all_loans['In_Prestito_A'].tolist()))
        l_c3.metric("Squadre Coinvolte", f"{teams_involved} / 12")
        l_c4.metric("Media Valore Prestito", f"{round(tot_loan_credits / len(df_all_loans), 1)} cr")
        
        st.dataframe(
            df_all_loans[['Calciatore', 'Ruolo', 'Squadra', 'Proprietario', 'In_Prestito_A', 'Costo_Asta', 'Tipo']],
            use_container_width=True,
            hide_index=True
        )

        with st.expander("🛠️ Gestione & Risoluzione Accordi di Lega (Termina o Aggiungi Prestiti)", expanded=False):
            st.markdown("Gestisci direttamente i prestiti tra le 12 squadre della lega in tempo reale:")
            m_col1, m_col2 = st.columns(2)
            with m_col1:
                st.markdown("##### ❌ Termina un Prestito Esistente")
                loan_options = [f"{r['Calciatore']} ({r['Proprietario']} ➔ {r['In_Prestito_A']})" for _, r in df_all_loans.iterrows()]
                selected_loan_to_term = st.selectbox("Seleziona il prestito da risolvere:", options=loan_options, key="select_loan_term_tab4")
                if st.button("Termina Prestito Selezionato", type="secondary", key="btn_term_loan_tab4", use_container_width=True):
                    sel_idx = loan_options.index(selected_loan_to_term)
                    row_sel = df_all_loans.iloc[sel_idx]
                    p_to_term = row_sel['Calciatore']
                    b_to_term = row_sel['In_Prestito_A']
                    ok, msg = terminate_loan(p_to_term, b_to_term)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            with m_col2:
                st.markdown("##### ➕ Registra Nuovo Prestito Manuale")
                owner_team_new = st.selectbox("Squadra Proprietaria (Cartellino):", options=league_teams, key="new_loan_owner_tab4")
                all_rosters_dict = load_league_rosters()
                avail_owner_players = sorted([p['Giocatore'] for p in all_rosters_dict.get(owner_team_new, []) if p.get('Costo', 0) > 0])
                player_to_loan_new = st.selectbox("Calciatore da prestare:", options=avail_owner_players if avail_owner_players else ["Nessun giocatore"], key="new_loan_p_tab4")
                borrower_team_new = st.selectbox("Squadra Ricevente (In Prestito A):", options=[t for t in league_teams if t != owner_team_new], key="new_loan_borrower_tab4")
                if st.button("Registra Prestito", type="primary", key="btn_add_loan_tab4", use_container_width=True):
                    if player_to_loan_new and player_to_loan_new != "Nessun giocatore":
                        ok, msg = add_or_update_loan(player_to_loan_new, owner_team_new, borrower_team_new)
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
        st.markdown("---")

    # Out of Serie A Table
    df_out_league = get_out_of_serie_a_summary()
    if not df_out_league.empty:
        st.subheader("🚫 Calciatori Fuori dalla Serie A (Da Svincolare appena possibile)")
        st.markdown(
            "Calciatori contrassegnati con `*` nel file della lega: hanno lasciato la Serie A (trasferiti all'estero, scesi in Serie B o svincolati). "
            "Le squadre titolari devono svincolarli per recuperare crediti d'asta e liberare spazio in rosa."
        )
        s_c1, s_c2, s_c3 = st.columns(3)
        s_c1.metric("Giocatori da Svincolare in Lega", len(df_out_league))
        tot_out_cr = int(df_out_league['Costo_Asta'].sum())
        s_c2.metric("Crediti Totali da Recuperare", f"{tot_out_cr} cr")
        teams_with_out = len(df_out_league['Squadra_Lega'].unique())
        s_c3.metric("Squadre Coinvolte", f"{teams_with_out} squadre")
        
        st.dataframe(
            df_out_league[['Calciatore', 'Squadra_Lega', 'Ruolo', 'Costo_Asta', 'Stato', 'Consiglio']],
            use_container_width=True,
            hide_index=True
        )
        st.markdown("---")

    st.subheader("🔍 Ispezione Rosa Completa di una Squadra")
    cur_insp_idx = league_teams.index(current_active_team) if current_active_team in league_teams else 0
    selected_inspect_team = st.selectbox(
        "Seleziona quale squadra della lega visualizzare:",
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
        c_i4.metric("Punte Pc Disponibili", len(df_inspect[df_inspect['RuoloMantra'].str.contains('Pc', na=False)]))
        
        cols_inspect = [
            'Badge_Prestito', 'Giocatore', 'Dettaglio_Prestito', 'Squadra', 'RuoloMantra', 'Costo', 'Presenze',
            'MV_Stagione', 'FM_Stagione', 'xG_90', 'xA_90', 'Delta_xG', 'Signal'
        ]
        cols_inspect = [c for c in cols_inspect if c in df_inspect.columns]
        
        st.caption("💡 Clicca su qualsiasi riga per aprire la Scheda Profilo dettagliata con radar e statistiche avanzate.")
        event_insp = st.dataframe(
            df_inspect[cols_inspect],
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="inspect_team_df_table"
        )
        if event_insp and hasattr(event_insp, 'selection'):
            s_rows = event_insp.selection.get('rows', [])
            if s_rows and len(s_rows) > 0:
                insp_idx = s_rows[0]
                if insp_idx < len(df_inspect):
                    insp_p = df_inspect.iloc[insp_idx]['Giocatore']
                    show_player_profile_dialog(
                        insp_p,
                        df_master,
                        calendar=calendar,
                        matchday=selected_giornata,
                        df_roster=df_inspect
                    )
        
    st.markdown("---")
    render_league_upload_section("tab4", df_master, label_title="📥 Aggiorna / Ricarica File con Tutte le Rose della Lega (.xlsx, .xls, .csv)")

# =============================================================
# TAB 4: ANALISI REAL METRICS (BUY-LOW / SELL-HIGH & UNDERSTAT)
# =============================================================
with tab_stats:
    st.header("📊 Analisi Statistiche Reali & Indicatori di Regressione (Understat)")
    st.markdown(
        "Analizza i calciatori incrociando i punteggi fantacalcistici con le metriche avanzate del calcio reale "
        "(**xG, xA, tiri/90, passaggi chiave, xG Chain**) direttamente da **Understat Serie A**. "
        "Individua le anomalie statistiche per anticipare il mercato: acquista chi crea tanto e raccoglie poco (*Buy-Low*), "
        "e scambia chi sta sovraperformando la fortuna (*Sell-High*)."
    )
    
    # Summary KPIs
    n_understat_total = int(df_master['Understat_Matched'].sum()) if 'Understat_Matched' in df_master.columns else 0
    top_bomber = df_master[df_master['Minuti_Reali'] >= 180].sort_values('xG_90', ascending=False).iloc[0] if not df_master.empty else None
    top_creator = df_master[df_master['Minuti_Reali'] >= 180].sort_values('xA_90', ascending=False).iloc[0] if not df_master.empty else None
    top_buylow = df_master.sort_values('Delta_xG', ascending=True).iloc[0] if not df_master.empty else None
    
    kp_c1, kp_c2, kp_c3, kp_c4 = st.columns(4)
    kp_c1.metric("Serie A su Understat", f"{n_understat_total} giocatori", help="Calciatori con dati reali xG/xA mappati.")
    if top_bomber is not None:
        kp_c2.metric("Top xG/90", f"{top_bomber['Giocatore']}", f"{top_bomber['xG_90']} xG/90 ({top_bomber['Squadra']})")
    if top_creator is not None:
        kp_c3.metric("Top xA/90", f"{top_creator['Giocatore']}", f"{top_creator['xA_90']} xA/90 ({top_creator['Squadra']})")
    if top_buylow is not None:
        kp_c4.metric("Top Buy-Low Assoluto", f"{top_buylow['Giocatore']}", f"{top_buylow['Delta_xG']} ΔxG ({top_buylow['GF']}G / {top_buylow['xG_Tot']}xG)")

    st.markdown("---")

    sub_t1, sub_t2, sub_t3, sub_t4, sub_t5 = st.tabs([
        "🎯 Leaderboard Metriche Avanzate",
        "📉 Buy-Low & Sell-High (Grafici)",
        "🤝 Opportunità Buy-Low nelle Rose Avversarie",
        "🛡️ Performance Squadre Serie A (xG & xGA)",
        "🧤 Portieri: Goals Prevented (PSxG-GA) & Blunders"
    ])
    
    # SUB-TAB 1: LEADERBOARD METRICHE AVANZATE
    with sub_t1:
        st.subheader("Leaderboard Statistiche Avanzate")
        st.caption("Filtra e ordina l'intera Serie A in base alle metriche di prestazione reali.")
        
        f_c1, f_c2, f_c3, f_c4 = st.columns(4)
        with f_c1:
            role_classic_filter = st.selectbox("Ruolo Classic:", options=["TUTTI", "P", "D", "C", "A"], key="sb_rc_filter")
        with f_c2:
            sort_metric = st.selectbox(
                "Ordina per metrica:",
                options=[
                    ("Pct_Sufficienza", "Sufficienza Difensiva (% Voti >= 6)"),
                    ("Goals_Prevented", "Goals Prevented / PSxG-GA (Gol Evitati dai Portieri)"),
                    ("Goals_Prevented_90", "Goals Prevented per 90 min"),
                    ("Pct_Parate", "Parate Portieri (% Efficacia)"),
                    ("Clean_Sheets_Tot", "Clean Sheets Portieri (Totali)"),
                    ("Errors_Leading_To_Goal", "Errori Decisivi / Blunders Concessi"),
                    ("MV_Stagione", "Media Voto Pura (MV)"),
                    ("xG_Tot", "xG Totali"),
                    ("xG_90", "xG per 90 min"),
                    ("xA_Tot", "xA Totali"),
                    ("xA_90", "xA per 90 min"),
                    ("npxG_90", "Non-Penalty xG / 90"),
                    ("Tiri_90", "Tiri per 90 min"),
                    ("Key_Passes_90", "Key Passes per 90 min"),
                    ("xGChain", "xG Chain (Coinvolgimento Manovra)"),
                    ("xGBuildup", "xG Buildup (Costruzione dal Basso)"),
                    ("Delta_xG", "Delta xG (Sfortuna/Regressione)")
                ],
                format_func=lambda x: x[1],
                key="sb_sort_metric"
            )
        with f_c3:
            min_minuti = st.slider("Minuti Minimi Giocati:", min_value=0, max_value=600, value=90, step=45, key="sb_min_mins")
        with f_c4:
            search_name = st.text_input("Cerca Calciatore:", placeholder="es. Lautaro, Thuram, Pulisic...", key="sb_srch")
            
        df_lb = df_master.copy()
        if role_classic_filter != "TUTTI":
            df_lb = df_lb[df_lb['RuoloClassic'] == role_classic_filter]
        if 'Minuti_Reali' in df_lb.columns:
            df_lb = df_lb[df_lb['Minuti_Reali'] >= min_minuti]
        if search_name:
            df_lb = df_lb[df_lb['Giocatore'].str.contains(search_name, case=False, na=False)]
            
        sort_col = sort_metric[0]
        sort_asc = True if sort_col == "Delta_xG" else False
        df_lb = df_lb.sort_values(sort_col, ascending=sort_asc)
        
        display_cols = [
            'Giocatore', 'Squadra', 'RuoloMantra', 'MV_Stagione', 'Pct_Sufficienza', 'Goals_Prevented', 'Goals_Prevented_90', 'Errors_Leading_To_Goal', 'Pct_Parate', 'Clean_Sheets_Tot', 'Minuti_Reali', 'GF', 'xG_Tot', 'xG_90', 'npxG_90',
            'ASS', 'xA_Tot', 'xA_90', 'Tiri_90', 'Key_Passes_90', 'xGChain', 'xGBuildup', 'Signal'
        ]
        display_cols = [c for c in display_cols if c in df_lb.columns]
        
        st.dataframe(
            df_lb[display_cols],
            use_container_width=True,
            hide_index=True
        )

    # SUB-TAB 2: BUY-LOW & SELL-HIGH GRAFICI
    with sub_t2:
        st.subheader("Scatter Plot: Relazione tra Produzione Reale e Bonus")
        
        # Filter options
        f_col1, f_col2 = st.columns([2, 1])
        with f_col1:
            st.caption(
                "💡 **Passa il cursore sui pallini** per visualizzare il nome del calciatore, la squadra, "
                "le presenze e il dettaglio di produzione reale vs bonus realizzati. "
                "La linea tratteggiata rappresenta la perfetta parità (Bonus Reali = Produzione Attesa)."
            )
        with f_col2:
            role_options = ["Tutti i Ruoli", "Attaccanti (A)", "Centrocampisti (C)", "Difensori (D)", "Portieri (P)"]
            sel_scatter_role = st.selectbox("Filtra per Ruolo Classic:", options=role_options, index=0, key="sel_scat_role")
            
        df_plot_base = df_master[df_master['Presenze'] > 0].copy()
        if sel_scatter_role == "Attaccanti (A)":
            df_plot_base = df_plot_base[df_plot_base['RuoloClassic'] == 'A']
        elif sel_scatter_role == "Centrocampisti (C)":
            df_plot_base = df_plot_base[df_plot_base['RuoloClassic'] == 'C']
        elif sel_scatter_role == "Difensori (D)":
            df_plot_base = df_plot_base[df_plot_base['RuoloClassic'] == 'D']
        elif sel_scatter_role == "Portieri (P)":
            df_plot_base = df_plot_base[df_plot_base['RuoloClassic'] == 'P']

        role_scale = alt.Scale(
            domain=['P', 'D', 'C', 'A'],
            range=['#f59e0b', '#10b981', '#3b82f6', '#ef4444']
        )

        sc_c1, sc_c2 = st.columns(2)
        with sc_c1:
            st.markdown("##### ⚽ xG Totali vs Gol Fatti (GF)")
            st.caption("*I calciatori sotto la diagonale hanno segnato meno di quanto prodotto (Candidati BUY-LOW).*")
            
            max_xg = float(max(df_plot_base['xG_Tot'].max() if not df_plot_base.empty else 1.0, 
                               df_plot_base['GF'].max() if not df_plot_base.empty else 1.0) + 1.0)
            diag_df1 = pd.DataFrame({'x': [0, max_xg], 'y': [0, max_xg]})
            
            ref_line1 = alt.Chart(diag_df1).mark_line(
                strokeDash=[4, 4],
                color='#94a3b8',
                opacity=0.6,
                strokeWidth=1.5
            ).encode(x='x:Q', y='y:Q')
            
            points1 = alt.Chart(df_plot_base).mark_circle(
                opacity=0.75,
                stroke='#ffffff',
                strokeWidth=0.6
            ).encode(
                x=alt.X('xG_Tot:Q', title='xG Totali (Gol Attesi)'),
                y=alt.Y('GF:Q', title='Gol Fatti (GF Reali)'),
                color=alt.Color('RuoloClassic:N', title='Ruolo', scale=role_scale),
                size=alt.Size('Presenze:Q', title='Presenze', scale=alt.Scale(range=[40, 260])),
                tooltip=[
                    alt.Tooltip('Giocatore:N', title='⚽ Calciatore'),
                    alt.Tooltip('Squadra:N', title='🛡️ Squadra'),
                    alt.Tooltip('RuoloMantra:N', title='Ruoli Mantra'),
                    alt.Tooltip('RuoloClassic:N', title='Ruolo Classic'),
                    alt.Tooltip('Presenze:Q', title='Presenze'),
                    alt.Tooltip('xG_Tot:Q', title='xG Totali', format='.2f'),
                    alt.Tooltip('GF:Q', title='Gol Segnati (GF)'),
                    alt.Tooltip('Delta_xG:Q', title='Delta xG (GF - xG)', format='+.2f'),
                    alt.Tooltip('FM_Stagione:Q', title='FantaMedia', format='.2f')
                ]
            )
            chart1 = (ref_line1 + points1).properties(height=420).interactive()
            st.altair_chart(chart1, use_container_width=True, theme="streamlit")
            
        with sc_c2:
            st.markdown("##### 🎯 xA Totali vs Assist Fatti (ASS)")
            st.caption("*Chi produce alti xA ma ha zero assist è penalizzato dalla scarsa mira dei compagni (Candidati BUY-LOW).*")
            
            max_xa = float(max(df_plot_base['xA_Tot'].max() if not df_plot_base.empty else 1.0, 
                               df_plot_base['ASS'].max() if not df_plot_base.empty else 1.0) + 1.0)
            diag_df2 = pd.DataFrame({'x': [0, max_xa], 'y': [0, max_xa]})
            
            ref_line2 = alt.Chart(diag_df2).mark_line(
                strokeDash=[4, 4],
                color='#94a3b8',
                opacity=0.6,
                strokeWidth=1.5
            ).encode(x='x:Q', y='y:Q')
            
            points2 = alt.Chart(df_plot_base).mark_circle(
                opacity=0.75,
                stroke='#ffffff',
                strokeWidth=0.6
            ).encode(
                x=alt.X('xA_Tot:Q', title='xA Totali (Assist Attesi)'),
                y=alt.Y('ASS:Q', title='Assist Fatti (ASS Reali)'),
                color=alt.Color('RuoloClassic:N', title='Ruolo', scale=role_scale),
                size=alt.Size('Presenze:Q', title='Presenze', scale=alt.Scale(range=[40, 260])),
                tooltip=[
                    alt.Tooltip('Giocatore:N', title='🎯 Calciatore'),
                    alt.Tooltip('Squadra:N', title='🛡️ Squadra'),
                    alt.Tooltip('RuoloMantra:N', title='Ruoli Mantra'),
                    alt.Tooltip('RuoloClassic:N', title='Ruolo Classic'),
                    alt.Tooltip('Presenze:Q', title='Presenze'),
                    alt.Tooltip('xA_Tot:Q', title='xA Totali', format='.2f'),
                    alt.Tooltip('ASS:Q', title='Assist Serviti (ASS)'),
                    alt.Tooltip('Delta_xA:Q', title='Delta xA (ASS - xA)', format='+.2f'),
                    alt.Tooltip('FM_Stagione:Q', title='FantaMedia', format='.2f')
                ]
            )
            chart2 = (ref_line2 + points2).properties(height=420).interactive()
            st.altair_chart(chart2, use_container_width=True, theme="streamlit")

        st.subheader("Radar Segnali di Mercato")
        signal_filter = st.radio(
            "Filtra per Segnale di Mercato:",
            options=["TUTTI", "BUY-LOW (Sottoperforma xG)", "SELL-HIGH (Sovraperforma xG)", "CREATORE ELITE (High xA)", "BOMBER PURO (High xG)"],
            horizontal=True,
            key="sb_sig_filter"
        )
        
        df_signals = df_master.copy()
        if signal_filter != "TUTTI":
            df_signals = df_signals[df_signals['Signal'] == signal_filter]
            
        sig_cols = [
            'Giocatore', 'Squadra', 'RuoloMantra', 'Presenze', 'FM_Stagione',
            'GF', 'xG_Tot', 'Delta_xG', 'ASS', 'xA_Tot', 'Delta_xA',
            'Tiri_90', 'Pass_Acc_Pct', 'Duelli_Vinti_Pct', 'Signal'
        ]
        sig_cols = [c for c in sig_cols if c in df_signals.columns]
        
        st.dataframe(
            df_signals[sig_cols].sort_values(by='Delta_xG', ascending=True),
            use_container_width=True,
            hide_index=True
        )

    # SUB-TAB 3: BERSAGLI BUY-LOW NELLE ROSE AVVERSARIE
    with sub_t3:
        st.subheader("Bersagli di Scambio Buy-Low nelle Rose Avversarie della Tua Lega")
        st.markdown(
            "Questo algoritmo analizza le rose di tutti i tuoi rivali di lega e scova i calciatori "
            "che hanno una produzione reale di xG o xA molto superiore ai bonus registrati finora. "
            "**Proponi uno scambio ai loro proprietari adesso**, sfruttando il momento di apparente appannamento prima che si sblocchino!"
        )
        
        my_team = get_active_my_team()
        league_rosters_dict = load_league_rosters()
        
        if not league_rosters_dict:
            st.info("Nessuna rosa di lega caricata. Carica il file della lega nel wizard o nella sidebar.")
        else:
            opp_buylow = []
            for t_name, p_list in league_rosters_dict.items():
                if t_name == my_team:
                    continue
                df_t = get_team_roster_df(t_name, df_master)
                for _, r in df_t.iterrows():
                    # Only evaluate players owned by the team (exclude temporary loans belonging to other clubs)
                    if r.get('InPrestito', False) or r.get('Costo', 1) == 0:
                        continue
                    d_xg = float(r.get('Delta_xG', 0.0))
                    sig = str(r.get('Signal', ''))
                    xg_tot = float(r.get('xG_Tot', 0.0))
                    if d_xg <= -0.6 or 'BUY-LOW' in sig or (xg_tot >= 1.5 and r.get('GF', 0) == 0):
                        opp_buylow.append({
                            'Squadra Lega': t_name,
                            'Giocatore': r['Giocatore'],
                            'RuoloMantra': r['RuoloMantra'],
                            'Club Serie A': r['Squadra'],
                            'Costo Asta': int(r.get('Costo', 0)),
                            'Presenze': int(r.get('Presenze', 0)),
                            'GF': int(r.get('GF', 0)),
                            'Tiri / 90': r.get('Tiri_90', 0.0),
                            'xG Totali': r.get('xG_Tot', 0.0),
                            'xG / 90': r.get('xG_90', 0.0),
                            'Delta xG (Sfortuna)': d_xg,
                            'KP / 90': r.get('Key_Passes_90', 0.0),
                            'Segnale': r.get('Signal', ''),
                            'Suggerimento': '🔥 Proponi scambio: gol attesi in forte arrivo!' if d_xg < -1.5 else '⚡ Bersaglio interessante'
                        })
            
            if opp_buylow:
                df_opp_bl = pd.DataFrame(opp_buylow).sort_values('Delta xG (Sfortuna)', ascending=True)
                
                # Filters
                bl_col1, bl_col2 = st.columns(2)
                with bl_col1:
                    filter_rival = st.selectbox(
                        "Filtra per Squadra Rivale:",
                        options=["TUTTE LE SQUADRE"] + sorted(list(set(df_opp_bl['Squadra Lega']))),
                        key="bl_rival_sel"
                    )
                with bl_col2:
                    filter_role = st.selectbox(
                        "Filtra per Ruolo Reparto:",
                        options=["TUTTI", "Attaccanti (Pc / A)", "Centrocampisti (C / T / W / M / E)", "Difensori (Dc / Dd / Ds)"],
                        key="bl_role_sel"
                    )
                    
                if filter_rival != "TUTTE LE SQUADRE":
                    df_opp_bl = df_opp_bl[df_opp_bl['Squadra Lega'] == filter_rival]
                if filter_role == "Attaccanti (Pc / A)":
                    df_opp_bl = df_opp_bl[df_opp_bl['RuoloMantra'].str.contains('Pc|A', na=False)]
                elif filter_role == "Centrocampisti (C / T / W / M / E)":
                    df_opp_bl = df_opp_bl[df_opp_bl['RuoloMantra'].str.contains('C|T|W|M|E', na=False)]
                elif filter_role == "Difensori (Dc / Dd / Ds)":
                    df_opp_bl = df_opp_bl[df_opp_bl['RuoloMantra'].str.contains('Dc|Dd|Ds', na=False)]
                    
                st.dataframe(
                    df_opp_bl,
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Nessun calciatore con marcata sotto-performance rilevato nelle altre squadre.")

    # SUB-TAB 4: UNDERSTAT TEAM PERFORMANCE
    with sub_t4:
        st.subheader("Performance Offensive e Difensive Squadre Serie A (Understat)")
        st.markdown(
            "Visualizza la produzione offensiva (xG generati a partita) e la tenuta difensiva (xGA concessi a partita) "
            "calcolata su tutte le partite giocate finora. Questo permette di stimare scientificamente la difficoltà degli incontri."
        )
        
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
                st.dataframe(
                    df_tu,
                    use_container_width=True,
                    hide_index=True
                )
            with c_tu2:
                st.markdown("**Differenziale xG Squadre**")
                st.bar_chart(
                    df_tu.set_index('Squadra')['Differenziale xG']
                )
        else:
            st.info("Dati di squadra Understat al momento non disponibili.")

    # SUB-TAB 5: PORTIERI GOALS PREVENTED & BLUNDERS
    with sub_t5:
        st.subheader("🧤 Analisi Avanzata Portieri Serie A: Goals Prevented (PSxG-GA) & Blunders")
        st.markdown(
            """
            Il modello integra le metriche moderne per la valutazione oggettiva delle performance dei portieri:
            - **PSxG (Post-Shot Expected Goals)**: La qualità e pericolosità effettiva dei tiri indirizzati verso lo specchio della porta (probabilità che ogni tiro diventi gol in base a traiettoria, velocità e angolazione).
            - **Goals Prevented (GSAx = PSxG - Gol Subiti)**: Quanti gol il portiere ha effettivamente evitato rispetto alle aspettative dei tiri subiti. Un valore positivo indica parate miracolose e prestazione decisiva sopra la media; un valore negativo indica gol evitabili concessi.
            - **Goals Prevented / 90**: Resa di parata parametrata sui 90 minuti di gioco.
            - **Errors Leading to Goal (Blunders / Paperoni)**: Errori tecnici o uscite a vuoto non forzate che hanno causato direttamente un gol avversario (rilevati dai voti di dettaglio e cronache ufficiali).
            """
        )
        
        df_gk_all = df_master[(df_master['RuoloClassic'] == 'P') & (df_master['Presenze'] > 0)].copy()
        if not df_gk_all.empty:
            df_gk_all = df_gk_all.sort_values(by='Goals_Prevented', ascending=False)
            
            top_gp = df_gk_all.iloc[0]
            top_gp90 = df_gk_all.sort_values(by='Goals_Prevented_90', ascending=False).iloc[0]
            blunder_gks = df_gk_all[df_gk_all['Errors_Leading_To_Goal'] > 0].sort_values(by='Errors_Leading_To_Goal', ascending=False)
            
            g_c1, g_c2, g_c3, g_c4 = st.columns(4)
            with g_c1:
                g_c1.metric(
                    "Miglior Shot-Stopper (Totale)",
                    f"{top_gp['Giocatore']} ({top_gp['Squadra']})",
                    f"{top_gp['Goals_Prevented']:+.2f} gol evitati"
                )
            with g_c2:
                g_c2.metric(
                    "Miglior Resa / 90 min",
                    f"{top_gp90['Giocatore']} ({top_gp90['Squadra']})",
                    f"{top_gp90['Goals_Prevented_90']:+.2f} GP/90"
                )
            with g_c3:
                most_blunder = blunder_gks.iloc[0] if not blunder_gks.empty else None
                if most_blunder is not None:
                    g_c3.metric(
                        "Più Errori Decisivi (Blunders)",
                        f"{most_blunder['Giocatore']} ({most_blunder['Squadra']})",
                        f"{int(most_blunder['Errors_Leading_To_Goal'])} concessi",
                        delta_color="inverse"
                    )
                else:
                    g_c3.metric("Più Errori Decisivi", "Nessuno", "0 blunder")
            with g_c4:
                top_save = df_gk_all.sort_values(by='Pct_Parate', ascending=False).iloc[0]
                g_c4.metric(
                    "Top % Parate",
                    f"{top_save['Giocatore']} ({top_save['Squadra']})",
                    f"{top_save['Pct_Parate']:.1f}% parate"
                )
                
            st.markdown("---")
            
            # Comparison chart
            st.markdown("### 📊 Differenziale Goals Prevented (PSxG - Gol Subiti)")
            st.caption("Barre positive: parate salva-risultato. Barre negative: gol concessi sopra le aspettative dei tiri subiti.")
            
            chart_df = df_gk_all[['Giocatore', 'Goals_Prevented']].set_index('Giocatore')
            st.bar_chart(chart_df['Goals_Prevented'])
            
            # Detailed Dataframe
            st.markdown("### 📋 Classifica Completa Portieri Serie A (Understat & Statistiche Reali)")
            cols_gk_view = [
                'Giocatore', 'Squadra', 'Presenze', 'Minuti_Reali', 'MV_Stagione', 'Pct_Sufficienza',
                'GS', 'PSxG', 'Goals_Prevented', 'Goals_Prevented_90', 'Pct_Parate',
                'Errors_Leading_To_Goal', 'Blunder_Rate_90', 'Clean_Sheets_Tot'
            ]
            cols_gk_view = [c for c in cols_gk_view if c in df_gk_all.columns]
            
            st.dataframe(
                df_gk_all[cols_gk_view],
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Nessun dato portieri con presenze disponibile.")

# =============================================================
# TAB 5: CALENDARIO & FDR
# =============================================================
with tab_calendario:
    st.header("📅 Calendario & FDR Dinamico")
    st.markdown(
        "Il **Fixture Difficulty Rating (FDR)** è **dinamico**: deriva per una quota dalla **classifica attuale di Serie A** "
        "(punti e differenza reti delle giornate giocate) e per l'altra dalla **classifica del triennio precedente** "
        "(pedigree storico 2023-2026), combinati all'effetto **Casa/Trasferta**."
    )
    
    cal_tab1, cal_tab2 = st.tabs([
        "📅 Matrice Calendario & FDR Dinamico",
        "📊 Classifica Reale Serie A & Power Rating Dinamico"
    ])
    
    with cal_tab1:
        col_cal1, col_cal2 = st.columns(2)
        with col_cal1:
            cal_start = st.number_input("Da Giornata:", min_value=1, max_value=35, value=selected_giornata, key="cal_st")
        with col_cal2:
            cal_end = st.number_input("A Giornata:", min_value=cal_start + 1, max_value=38, value=min(38, cal_start + 6), key="cal_en")
            
        matrix_df = get_schedule_matrix(start_giornata=cal_start, end_giornata=cal_end, calendar=calendar)
        
        st.subheader("Matrice Fixture Difficulty Rating (FDR 1 = Molto Facile, 5 = Difficilissimo)")
        st.dataframe(
            matrix_df,
            use_container_width=True,
            hide_index=True
        )
        
        c_fav1, c_fav2 = st.columns(2)
        with c_fav1:
            st.subheader("🟢 Top 5 Calendari Più Agevoli")
            st.dataframe(
                matrix_df.head(5)[['Squadra', 'Power_Dinamico', 'Posizione_Attuale', 'FDR_Medio']],
                use_container_width=True,
                hide_index=True
            )
        with c_fav2:
            st.subheader("🔴 Top 5 Calendari Più Ostici")
            st.dataframe(
                matrix_df.tail(5)[['Squadra', 'Power_Dinamico', 'Posizione_Attuale', 'FDR_Medio']],
                use_container_width=True,
                hide_index=True
            )

    with cal_tab2:
        st.subheader("Classifica Reale Serie A (2026/27) & Power Rating Dinamico")
        ratings_dict, df_ratings = compute_dynamic_team_ratings(selected_giornata)
        
        st.markdown(f"""
        Alla **Giornata {selected_giornata}**, la formula pondera:
        - 📈 **Peso Classifica Attuale**: `{df_ratings['w_current'].iloc[0]}%`
        - 🏛️ **Peso Storico Triennale**: `{df_ratings['w_historical'].iloc[0]}%`
        """)
        
        cols_ratings = [
            'Posizione_Attuale', 'Squadra', 'Punti_Attuali', 'DR_Attuale',
            'Power_Attuale', 'Power_Triennio', 'Power_Dinamico'
        ]
        st.dataframe(
            df_ratings[cols_ratings].sort_values(by='Posizione_Attuale', ascending=True),
            use_container_width=True,
            hide_index=True
        )
