"""
Mantra Player Profile View (Scheda Dettagliata Calciatore).
Displays complete player dossier integrating:
1. Fantacalcio official statistics, vote sufficiency, and bonus trends.
2. Real-world advanced stats from Understat & Opta (xG, xA, Shots, Key Passes, xGChain, Duels, Tackles, Blunders).
3. Visual skill radar chart and attribute indicators (0-100 rating scale).
4. Medical status, Serie A starting status, and next 5 fixtures calendar projections.

Responsive Layout:
- On Desktop/PC: 2-column horizontal cockpit layout designed to fit viewport without vertical scrolling.
- On Mobile/Narrow: Automatically stacks vertically for clean touch navigation.
"""

import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.fanta_calendar import get_or_create_calendar
from engine.models import predict_player_xfv
from engine.injuries_manager import classify_injury_status
from engine.trade_finder import compute_real_starter_status
from engine.theme_helper import get_pitch_bg_base64


def clean_html(raw_html):
    """Strips leading/trailing whitespace from each line to prevent Markdown code-block interpretation."""
    return "\n".join(line.strip() for line in raw_html.strip().splitlines() if line.strip())


def compute_player_skill_ratings(p):
    """
    Computes 5 normalized attribute ratings (0 to 100) for visual radar and progress bars.
    Distinguishes outfield players from goalkeepers.
    """
    roles = str(p.get('RuoloMantra', ''))
    is_gk = 'Por' in roles

    if is_gk:
        gp90 = float(p.get('Goals_Prevented_90', 0.0) or 0.0)
        save_pct = float(p.get('Pct_Parate', 70.0) or 70.0)
        blunders = int(p.get('Errors_Leading_To_Goal', 0) or 0)
        cs = int(p.get('Clean_Sheets_Tot', 0) or 0)
        pres = int(p.get('Presenze', 0) or 0)
        pass_acc = float(p.get('Pass_Acc_Pct', 70.0) or 70.0)

        r_shot = min(99, max(15, int(50 + (gp90 / 0.40 * 40))))
        r_save = min(99, max(15, int(35 + ((save_pct - 60.0) / 20.0 * 55))))
        r_rel = 95 if blunders == 0 else (50 if blunders == 1 else 20)
        cs_rate = cs / max(1, pres)
        r_cs = min(99, max(20, int(20 + cs_rate * 180)))
        r_dist = min(99, max(20, int(pass_acc)))

        return {
            'is_gk': True,
            'categories': ['Shot-Stop', '% Parate', 'Sicurezza', 'CleanSheet', 'Rinvio'],
            'values': [r_shot, r_save, r_rel, r_cs, r_dist],
            'tooltips': [
                f"{gp90:+.2f} Goals Prev./90",
                f"{save_pct:.1f}% parate",
                f"{blunders} paperoni",
                f"{cs} clean sheets",
                f"{pass_acc:.0f}% precisione piedi"
            ]
        }
    else:
        tiri = float(p.get('Tiri_90', 0.0) or 0.0)
        xg = float(p.get('xG_90', 0.0) or 0.0)
        kp = float(p.get('Key_Passes_90', 0.0) or 0.0)
        xa = float(p.get('xA_90', 0.0) or 0.0)
        suff = float(p.get('Pct_Sufficienza', 60.0) or 60.0)
        mv = float(p.get('MV_Stagione', 6.0) or 6.0)
        xg_chain = float(p.get('xGChain', 0.0) or 0.0)
        pass_acc = float(p.get('Pass_Acc_Pct', 75.0) or 75.0)
        duels = float(p.get('Duelli_Vinti_Pct', 50.0) or 50.0)
        rec = float(p.get('Recuperi_90', 0.0) or 0.0)
        tackles = float(p.get('Tackles_90', 0.0) or 0.0)

        r_shoot = min(99, max(10, int((min(4.5, tiri) / 4.0 * 50) + (min(0.70, xg) / 0.55 * 50))))
        r_create = min(99, max(10, int((min(2.5, kp) / 2.0 * 50) + (min(0.35, xa) / 0.25 * 50))))
        r_suff = min(99, max(10, int((suff * 0.55) + (max(0.0, mv - 5.5) / 1.1 * 45))))
        r_build = min(99, max(15, int((min(5.0, xg_chain) / 4.5 * 50) + ((pass_acc - 50.0) / 45.0 * 50))))
        r_def = min(99, max(15, int(((duels - 30.0) / 40.0 * 45) + (min(6.0, rec + tackles) / 5.5 * 55))))

        return {
            'is_gk': False,
            'categories': ['Tiro/xG', 'Assist/KP', 'Voto/D-Factor', 'Costruzione', 'Duelli/Rec'],
            'values': [r_shoot, r_create, r_suff, r_build, r_def],
            'tooltips': [
                f"{tiri:.1f} tiri/90 | {xg:.2f} xG/90",
                f"{kp:.1f} kp/90 | {xa:.2f} xA/90",
                f"{suff:.1f}% >= 6.0 | MV: {mv:.2f}",
                f"{xg_chain:.2f} xGChain | {pass_acc:.0f}% pass",
                f"{duels:.0f}% duelli | {rec+tackles:.1f} rec/tack"
            ]
        }


def create_radar_figure(skill_data):
    """
    Renders an ultra-high contrast dark-theme polar radar plot styled for soccer stadium cockpits.
    """
    categories = skill_data['categories']
    values = skill_data['values']
    n_cats = len(categories)

    angles = [n / float(n_cats) * 2 * np.pi for n in range(n_cats)]
    plot_values = values + values[:1]
    plot_angles = angles + angles[:1]

    fig, ax = plt.subplots(figsize=(4.0, 4.0), subplot_kw=dict(polar=True), dpi=125)
    fig.patch.set_facecolor('#081627')
    ax.set_facecolor('#0d223a')

    accent_color = '#00f0ff' if not skill_data.get('is_gk') else '#38bdf8'

    ax.plot(plot_angles, plot_values, color=accent_color, linewidth=2.8, linestyle='solid')
    ax.fill(plot_angles, plot_values, color=accent_color, alpha=0.30)
    ax.scatter(angles, values, color=accent_color, s=55, edgecolors='#ffffff', linewidth=1.5, zorder=6)

    ax.set_xticks(angles)
    ax.set_xticklabels(categories, color='#f8fafc', size=10.5, weight='bold')

    ax.set_ylim(0, 100)
    ax.set_yticks([30, 60, 90])
    ax.set_yticklabels(['30', '60', '90'], color='#38bdf8', size=8.5, weight='bold')

    ax.spines['polar'].set_color('#00f0ff')
    ax.spines['polar'].set_linewidth(1.4)
    ax.grid(color='#38bdf8', alpha=0.35, linestyle='--', linewidth=0.9)

    plt.tight_layout(pad=0.3)
    return fig


def render_player_profile_content(player_name_or_row, df_master, calendar=None, matchday=8, df_roster=None):
    """
    Renders the full interactive Player Profile Card into Streamlit.
    Optimized to fit on PC desktop screens without scrolling, and automatically
    stacks vertically on mobile.
    """
    if calendar is None:
        calendar = get_or_create_calendar()

    # Locate player row
    if isinstance(player_name_or_row, str):
        match = df_master[df_master['Giocatore'] == player_name_or_row]
        if match.empty:
            st.error(f"Calciatore '{player_name_or_row}' non trovato nel database.")
            return
        p_row = dict(match.iloc[0])
    else:
        p_row = dict(player_name_or_row)

    player_name = p_row.get('Giocatore', 'N/D')
    team = p_row.get('Squadra', 'N/D')
    ruolo_m = p_row.get('RuoloMantra', 'N/D')
    ruolo_c = p_row.get('RuoloClassic', 'N/D')

    # Merge roster info if available
    costo = p_row.get('Costo', 0)
    stato_prestito = p_row.get('Stato_Prestito', 'Proprietà')
    prestito_det = p_row.get('Dettaglio_Prestito', '')
    if df_roster is not None and not df_roster.empty:
        r_match = df_roster[df_roster['Giocatore'] == player_name]
        if not r_match.empty:
            r_info = r_match.iloc[0]
            costo = r_info.get('Costo', costo)
            stato_prestito = r_info.get('Stato_Prestito', stato_prestito)
            prestito_det = r_info.get('Dettaglio_Prestito', prestito_det)

    # 1. Injuries & Medical Status
    inj_info = classify_injury_status(player_name)
    is_injured = inj_info.get('Is_Injured', False)
    inj_badge = inj_info.get('Stato', 'Disponibile')
    inj_detail = inj_info.get('Dettaglio', '')

    # 2. Real Starter Status in Serie A
    st_info = compute_real_starter_status(p_row)

    # 3. Next match prediction
    p_series = pd.Series(p_row)
    proj_next = predict_player_xfv(p_series, matchday=matchday, calendar=calendar)

    # 4. Signal (Buy-Low / Sell-High)
    signal = str(p_row.get('Signal', 'NEUTRO'))

    # CSS Injection with Soccer Pitch Theme & High-Contrast Palette
    bg_uri = get_pitch_bg_base64()
    bg_css = f'url("{bg_uri}")' if bg_uri else 'none'

    st.markdown(clean_html(f"""
    <style>
    /* Modal Dialog Cockpit Fullscreen Expansion on Pitch */
    .react-aria-Modal,
    .ep9mgll1,
    div.stDialog .react-aria-Modal,
    div.stDialog .ep9mgll1,
    div[data-testid="stDialog"] .react-aria-Modal,
    div[data-testid="stDialog"] .ep9mgll1,
    div[data-testid="stDialog"] div[class*="ep9mgll1"],
    div[data-testid="stDialog"] div[class*="react-aria-Modal"],
    div[data-testid="stDialog"] > div,
    div[data-testid="stDialog"] > div > div {{
        width: 96vw !important;
        max-width: 96vw !important;
        min-width: 92vw !important;
        height: 94vh !important;
        max-height: 94vh !important;
        margin: 2vh auto !important;
        border-radius: 14px !important;
        background: linear-gradient(rgba(7, 14, 24, 0.70), rgba(11, 26, 46, 0.85)), {bg_css} no-repeat center center !important;
        background-size: cover !important;
        border: 2px solid #00f0ff !important;
        box-shadow: 0 25px 70px -10px rgba(0, 0, 0, 0.95), 0 0 35px rgba(0, 240, 255, 0.40) !important;
        outline: none !important;
    }}

    .react-aria-Dialog,
    .ep9mgll2,
    div.stDialog .react-aria-Dialog,
    div.stDialog .ep9mgll2,
    div[data-testid="stDialog"] .react-aria-Dialog,
    div[data-testid="stDialog"] .ep9mgll2,
    div[data-testid="stDialog"] section[role="dialog"],
    div[data-testid="stDialog"] [role="dialog"] {{
        width: 100% !important;
        max-width: 100% !important;
        height: 100% !important;
        max-height: 100% !important;
        overflow-y: auto !important;
        display: flex !important;
        flex-direction: column !important;
        padding: 1.25rem 2rem !important;
        background: transparent !important;
    }}

    div[data-testid="stDialog"] [data-testid="stDialogContent"] {{
        width: 100% !important;
        max-width: 100% !important;
        flex: 1 1 auto !important;
        background: transparent !important;
    }}

    @media (max-width: 900px) {{
        .react-aria-Modal,
        .ep9mgll1,
        div.stDialog .react-aria-Modal,
        div.stDialog .ep9mgll1,
        div[data-testid="stDialog"] .react-aria-Modal,
        div[data-testid="stDialog"] .ep9mgll1,
        div[data-testid="stDialog"] > div {{
            width: 98vw !important;
            max-width: 98vw !important;
            min-width: 95vw !important;
            height: 96vh !important;
            max-height: 96vh !important;
            margin: 1.5vh auto !important;
            border-radius: 10px !important;
        }}
        .react-aria-Dialog,
        .ep9mgll2,
        div[data-testid="stDialog"] section[role="dialog"] {{
            padding: 0.8rem 1rem !important;
        }}
    }}

    .profile-hero-bar {{
        background: linear-gradient(135deg, #0d223a 0%, #081627 100%) !important;
        border: 2px solid #00f0ff !important;
        border-radius: 12px !important;
        padding: 14px 22px !important;
        margin-bottom: 14px !important;
        box-shadow: 0 6px 24px rgba(0, 240, 255, 0.25) !important;
    }}
    .profile-skill-bar {{
        margin-bottom: 9px !important;
    }}
    .profile-card-subtab {{
        background: rgba(13, 34, 58, 0.90) !important;
        border: 1.5px solid rgba(0, 240, 255, 0.40) !important;
        border-radius: 10px !important;
        padding: 14px 18px !important;
        font-size: 1.05rem !important;
        line-height: 1.85 !important;
        color: #f8fafc !important;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.40) !important;
    }}
    .profile-metric-pill {{
        background: rgba(13, 34, 58, 0.90);
        border: 1.5px solid #00f0ff;
        border-radius: 10px;
        padding: 8px 12px;
        text-align: center;
        color: #f8fafc;
    }}
    </style>
    """), unsafe_allow_html=True)

    # HEADER HERO BAR (Compact Horizontal Flex with Large Fonts)
    inj_color = "#ef4444" if inj_badge == 'Infortunato' else ("#f59e0b" if inj_badge in ['In dubbio', 'Squalificato'] else "#10b981")
    starter_color = "#10b981" if st_info['Status'] == 'TITOLARE' else ("#f59e0b" if st_info['Status'] == 'CO_TITOLARE' else "#94a3b8")

    if stato_prestito == 'Prestito IN':
        prestito_badge = f'<span style="background: #0284c7; color: white; padding: 4px 14px; border-radius: 8px; font-size: 1.05rem; font-weight: 800; border: 1.5px solid #38bdf8; box-shadow: 0 2px 6px rgba(2,132,199,0.4);">🔄 IN PRESTITO (da {prestito_det})</span>'
    elif stato_prestito == 'Prestito OUT':
        prestito_badge = f'<span style="background: #d97706; color: white; padding: 4px 14px; border-radius: 8px; font-size: 1.05rem; font-weight: 800; border: 1.5px solid #fbbf24; box-shadow: 0 2px 6px rgba(217,119,6,0.4);">📤 PRESTITO CEDUTO (a {prestito_det})</span>'
    else:
        prestito_badge = ''

    signal_badge = f'<span style="background: rgba(245, 158, 11, 0.25); border: 2px solid #fbbf24; color: #fde047; padding: 6px 16px; border-radius: 18px; font-size: 1.05rem; font-weight: 800;">⚡ {signal}</span>' if ('BUY-LOW' in signal or 'SELL-HIGH' in signal) else ''
    inj_box = f'<div style="margin-top: 8px; font-size: 0.95rem; color: #fca5a5; font-weight: 600;"><b>Dettaglio Medico:</b> {inj_detail}</div>' if (is_injured and inj_detail) else ''
    prest_box = f'<div style="margin-top: 6px; font-size: 0.95rem; color: #bae6fd; font-weight: 700;"><b>Accordo di Prestito:</b> {prestito_det}</div>' if (prestito_det and stato_prestito != 'Proprietà') else ''

    hero_html = clean_html(f"""
    <div class="profile-hero-bar">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
            <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
                <span style="font-size: 2.1rem; font-weight: 900; color: #ffffff; letter-spacing: -0.02em; text-shadow: 0 0 16px rgba(0,240,255,0.7);">{player_name}</span>
                <span style="font-size: 1.15rem; color: #00f0ff; font-weight: 800; background: #081627; padding: 4px 14px; border-radius: 8px; border: 1.5px solid #00f0ff;">{team}</span>
                <span style="background: #0284c7; color: #ffffff; padding: 4px 14px; border-radius: 8px; font-weight: 800; font-size: 1.05rem; border: 1.5px solid #38bdf8;">Mantra: {ruolo_m}</span>
                <span style="background: #0f172a; color: #94a3b8; padding: 4px 12px; border-radius: 8px; font-weight: 700; font-size: 1.05rem; border: 1.5px solid #334155;">Classic: {ruolo_c}</span>
                <span style="background: #78350f; border: 1.5px solid #fbbf24; color: #fef08a; padding: 4px 14px; border-radius: 8px; font-size: 1.05rem; font-weight: 800;">💰 {costo} cr</span>
                {prestito_badge}
            </div>
            <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                <span style="background: {inj_color}25; border: 2px solid {inj_color}; color: {inj_color}; padding: 6px 16px; border-radius: 18px; font-weight: 800; font-size: 1.05rem;">{'🚑' if is_injured else '✅'} {inj_badge.upper()}</span>
                <span style="background: {starter_color}25; border: 2px solid {starter_color}; color: {starter_color}; padding: 6px 16px; border-radius: 18px; font-weight: 800; font-size: 1.05rem;">{st_info['Badge']}</span>
                {signal_badge}
            </div>
        </div>
        {inj_box}
        {prest_box}
    </div>
    """)
    st.markdown(hero_html, unsafe_allow_html=True)

    # 2 RESPONSIVE COLUMNS (Horizontal Cockpit on PC, Vertical on Mobile)
    col_left, col_right = st.columns([1.0, 1.25], gap="large")

    # LEFT COLUMN: RADAR + ATTRIBUTE PROGRESS BARS
    with col_left:
        st.markdown("<div style='font-size: 1.25rem; font-weight: 800; color: #ffffff; margin-bottom: 8px; text-shadow: 0 2px 4px rgba(0,0,0,0.8);'>🎯 Profilo Tecnico & Radar Skill</div>", unsafe_allow_html=True)
        skill_data = compute_player_skill_ratings(p_row)

        c_rad, c_att = st.columns([1.15, 1.0], gap="medium")
        with c_rad:
            radar_fig = create_radar_figure(skill_data)
            st.pyplot(radar_fig, width='stretch')
            plt.close(radar_fig)
        with c_att:
            for cat, val, tip in zip(skill_data['categories'], skill_data['values'], skill_data['tooltips']):
                bar_color = "#38bdf8" if val >= 75 else ("#34d399" if val >= 55 else ("#fbbf24" if val >= 40 else "#f87171"))
                st.markdown(clean_html(f"""
                <div class="profile-skill-bar">
                    <div style="display: flex; justify-content: space-between; font-size: 1.05rem; margin-bottom: 3px;">
                        <span style="font-weight: 800; color: #ffffff;">{cat}</span>
                        <span style="color: {bar_color}; font-weight: 900; font-size: 1.15rem;">{val}/100</span>
                    </div>
                    <div style="background: rgba(255, 255, 255, 0.15); border-radius: 5px; height: 10px; overflow: hidden; width: 100%;">
                        <div style="background: {bar_color}; width: {val}%; height: 100%; border-radius: 5px; box-shadow: 0 0 8px {bar_color}88;"></div>
                    </div>
                    <div style="font-size: 0.88rem; color: #cbd5e1; font-weight: 600; line-height: 1.2; margin-top: 3px;">{tip}</div>
                </div>
                """), unsafe_allow_html=True)

    # RIGHT COLUMN: KPIS + SUBTABS
    with col_right:
        # TOP KPIS (Compact 4-column row)
        k1, k2, k3, k4 = st.columns(4)
        fm = float(p_row.get('FM_Stagione', 0.0) or 0.0)
        mv = float(p_row.get('MV_Stagione', 0.0) or 0.0)
        pres = int(p_row.get('Presenze', 0) or 0)
        gf = int(p_row.get('GF', 0) or 0)
        ass = int(p_row.get('ASS', 0) or 0)
        gs = int(p_row.get('GS', 0) or 0)
        is_gk = 'Por' in ruolo_m

        with k1:
            st.metric("Fantamedia (FM)", f"{fm:.2f}", delta=f"{fm - mv:+.2f} bonus" if fm > 0 and mv > 0 else None)
        with k2:
            st.metric("Media Voto (MV)", f"{mv:.2f}", delta=f"{pres} pres.")
        with k3:
            st.metric(f"xFV (G{matchday})", f"{proj_next['xFV']:.2f} pt", delta=f"{proj_next['Match']}")
        with k4:
            if is_gk:
                gp = float(p_row.get('Goals_Prevented', 0.0) or 0.0)
                st.metric("Goals Prevented", f"{gp:+.2f}", delta=f"{gs} gol sub.", delta_color="inverse")
            else:
                st.metric("Gol / Assist", f"{gf} G / {ass} A", delta=f"{p_row.get('Tiri_90', 0.0)} tiri/90")

        # 3 IN-DEPTH SUBTABS (Compact Layout with Large Legible Fonts)
        tab_fanta, tab_real, tab_next = st.tabs([
            "📈 Fantacalcio",
            "🔬 Dati Reali & Understat",
            "📅 Calendario 5G"
        ])

        # SUBTAB 1: FANTACALCIO STATS
        with tab_fanta:
            f_r1, f_r2 = st.columns(2)
            with f_r1:
                st.markdown(clean_html(f"""
                <div class="profile-card-subtab">
                    <div>🛡️ <b>Sufficienza (&ge;6):</b> <span style="color: #00f0ff; font-weight:800; font-size: 1.15rem;">{float(p_row.get('Pct_Sufficienza', 0.0)):.1f}%</span> ({p_row.get('Voti_Ge_6', 0)}/{p_row.get('Voti_Tot_Valutati', pres)} gare)</div>
                    <div>⏱️ <b>Minuti Giocati:</b> <span style="color: #38bdf8; font-weight:800; font-size: 1.15rem;">{int(p_row.get('Minuti_Reali', 0) or 0)}'</span> (~{st_info['Min_Per_Pres']}'/pres)</div>
                    <div>⚽ <b>Gol &amp; Assist:</b> <span style="color: #4ade80; font-weight:800; font-size: 1.15rem;">{gf} GF</span> / <span style="color: #c084fc; font-weight:800; font-size: 1.15rem;">{ass} ASS</span></div>
                </div>
                """), unsafe_allow_html=True)
            with f_r2:
                mv_u3 = float(p_row.get('MV_Ultime3', 0.0) or 0.0)
                fm_u3 = float(p_row.get('FM_Ultime3', 0.0) or 0.0)
                mv_3y = float(p_row.get('MV_Triennio', 0.0) or 0.0)
                fm_3y = float(p_row.get('FM_Triennio', 0.0) or 0.0)
                st.markdown(clean_html(f"""
                <div class="profile-card-subtab">
                    <div>🟨 <b>Cartellini:</b> <span style="color: #fde047; font-weight:800; font-size: 1.15rem;">{p_row.get('AMM', 0)} Amm.</span> / <span style="color: #f87171; font-weight:800; font-size: 1.15rem;">{p_row.get('ESP', 0)} Esp.</span></div>
                    <div>🔥 <b>Forma Ultime 3 (U3):</b> MV <b style="color:#ffffff; font-size: 1.15rem;">{mv_u3:.2f}</b> | FM <b style="color:#00f0ff; font-size: 1.15rem;">{fm_u3:.2f}</b></div>
                    <div>📚 <b>Storico Triennio:</b> MV <b style="color:#ffffff; font-size: 1.15rem;">{mv_3y:.2f}</b> | FM <b style="color:#00f0ff; font-size: 1.15rem;">{fm_3y:.2f}</b></div>
                </div>
                """), unsafe_allow_html=True)

        # SUBTAB 2: UNDERSTAT REAL MATCH STATS
        with tab_real:
            xg_tot = float(p_row.get('xG_Tot', 0.0) or 0.0)
            xg_90 = float(p_row.get('xG_90', 0.0) or 0.0)
            delta_xg = float(p_row.get('Delta_xG', 0.0) or 0.0)
            tiri_90 = float(p_row.get('Tiri_90', 0.0) or 0.0)
            xa_90 = float(p_row.get('xA_90', 0.0) or 0.0)
            kp_90 = float(p_row.get('Key_Passes_90', 0.0) or 0.0)
            xg_chain = float(p_row.get('xGChain', 0.0) or 0.0)
            pass_acc = float(p_row.get('Pass_Acc_Pct', 75.0) or 75.0)
            duels = float(p_row.get('Duelli_Vinti_Pct', 50.0) or 50.0)
            rec_90 = float(p_row.get('Recuperi_90', 0.0) or 0.0)

            u_r1, u_r2 = st.columns(2)
            with u_r1:
                st.markdown(clean_html(f"""
                <div class="profile-card-subtab">
                    <div>⚽ <b>xG/90:</b> <span style="color:#00f0ff; font-weight:800; font-size:1.15rem;">{xg_90:.2f}</span> (Tot: {xg_tot:.2f})</div>
                    <div>🎯 <b>Tiri/90:</b> <span style="color:#f8fafc; font-weight:800; font-size:1.15rem;">{tiri_90:.1f}</span> ({p_row.get('Tiri_Porta_90', 0.0)} porta)</div>
                    <div>🍀 <b>Delta xG:</b> <b style="color:{'#4ade80' if delta_xg>0 else '#fde047'}; font-size:1.15rem;">{delta_xg:+.2f}</b></div>
                    <div>👟 <b>xA/90:</b> <span style="color:#c084fc; font-weight:800; font-size:1.15rem;">{xa_90:.2f}</span> | <b>KP/90:</b> <span style="color:#38bdf8; font-weight:800; font-size:1.15rem;">{kp_90:.1f}</span></div>
                </div>
                """), unsafe_allow_html=True)
            with u_r2:
                if is_gk:
                    psxg = float(p_row.get('PSxG', 0.0) or 0.0)
                    gp = float(p_row.get('Goals_Prevented', 0.0) or 0.0)
                    gp90 = float(p_row.get('Goals_Prevented_90', 0.0) or 0.0)
                    blunders = int(p_row.get('Errors_Leading_To_Goal', 0) or 0)
                    st.markdown(clean_html(f"""
                    <div class="profile-card-subtab">
                        <div>🧤 <b>PSxG:</b> <span style="color:#00f0ff; font-weight:800; font-size:1.15rem;">{psxg:.2f}</span> | <b>GP/90:</b> {gp90:+.2f}</div>
                        <div>🧱 <b>Goals Prevented:</b> <b style="color:{'#4ade80' if gp>0 else '#fde047'}; font-size:1.15rem;">{gp:+.2f}</b></div>
                        <div>⚠️ <b>Blunders / Papere:</b> <span style="color:{'#f87171' if blunders>0 else '#4ade80'}; font-weight:800; font-size:1.15rem;">{blunders}</span></div>
                    </div>
                    """), unsafe_allow_html=True)
                else:
                    st.markdown(clean_html(f"""
                    <div class="profile-card-subtab">
                        <div>⛓️ <b>xGChain:</b> <span style="color:#00f0ff; font-weight:800; font-size:1.15rem;">{xg_chain:.2f}</span></div>
                        <div>🎯 <b>Precisione Passaggi:</b> <span style="color:#38bdf8; font-weight:800; font-size:1.15rem;">{pass_acc:.0f}%</span></div>
                        <div>🥊 <b>Duelli Vinti:</b> <span style="color:#4ade80; font-weight:800; font-size:1.15rem;">{duels:.0f}%</span></div>
                        <div>🛡️ <b>Recuperi/90:</b> <span style="color:#cbd5e1; font-weight:800; font-size:1.15rem;">{rec_90:.1f}</span></div>
                    </div>
                    """), unsafe_allow_html=True)

        # SUBTAB 3: NEXT FIXTURES
        with tab_next:
            future_giornate = list(range(matchday, min(39, matchday + 5)))
            fixtures_data = []
            p_series = pd.Series(p_row)
            for g in future_giornate:
                proj = predict_player_xfv(p_series, matchday=g, calendar=calendar)
                fixtures_data.append({
                    'G': f"G{g}",
                    'Match': proj.get('Match', 'N/D'),
                    'FDR': int(proj.get('FDR', 3)),
                    'xFV': float(proj.get('xFV', 0.0))
                })
            df_fix = pd.DataFrame(fixtures_data)

            fix_col1, fix_col2 = st.columns([1, 1.2])
            with fix_col1:
                chart_df = df_fix[['G', 'xFV']].set_index('G')
                st.markdown("<div style='font-weight: 700; color: #ffffff; font-size: 1.05rem; margin-bottom: 4px;'>📊 Punteggio Atteso xFV:</div>", unsafe_allow_html=True)
                st.bar_chart(chart_df, height=185)
            with fix_col2:
                st.markdown("<div style='font-weight: 700; color: #ffffff; font-size: 1.05rem; margin-bottom: 4px;'>🗓️ Calendario & Difficoltà (FDR 1-5):</div>", unsafe_allow_html=True)
                st.dataframe(
                    df_fix[['G', 'Match', 'FDR', 'xFV']],
                    width='stretch',
                    hide_index=True,
                    height=185
                )


@st.dialog("📋 Scheda Profilo Calciatore", width="large")
def show_player_profile_dialog(player_name, df_master, calendar=None, matchday=8, df_roster=None):
    """
    Displays the player profile as an interactive modal dialog overlay.
    """
    render_player_profile_content(player_name, df_master, calendar=calendar, matchday=matchday, df_roster=df_roster)
