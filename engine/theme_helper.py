"""
Theme Helper: Cyber Neon Blue "Bluelock" Football Analytics Cockpit Theme.
A radical, high-contrast, luminous cyber-stadium aesthetic:
- Background: Deep midnight obsidian pitch (#070e18 / #0b1a2e) with electric cyan neon pitch chalk lines.
- Primary Accents: Electric Cyan Neon (#00f0ff / #38bdf8) with glowing bloom effects.
- Typography: Ultra-crisp snow & ice-white (#ffffff / #f8fafc) for maximum legibility and contrast (WCAG AAA).
- Cards & Containers: Midnight glassmorphism panels (rgba(12, 26, 46, 0.92)) with glowing laser-blue borders (#00f0ff / #0284c7).
- Tables & DataFrames: Midnight navy alternating rows with luminous neon headers.
- Buttons: High-impact Electric Neon Cyan & Deep Navy with razor-sharp contrast.
"""

import os
import base64

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_pitch_bg_base64():
    """
    Returns the Base64 data URI of the soccer pitch background image.
    """
    candidates = [
        os.path.join(APP_DIR, "assets", "pitch_bg_neon.jpg"),
        os.path.join(APP_DIR, "assets", "pitch_bg.jpg"),
        os.path.join(APP_DIR, "assets", "soccer_pitch_bg.jpg"),
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    data = base64.b64encode(f.read()).decode("utf-8")
                    return f"data:image/jpeg;base64,{data}"
            except Exception:
                continue
    return None


def get_global_theme_css():
    """
    Generates Cyber Neon Blue high-contrast CSS.
    """
    bg_uri = get_pitch_bg_base64()
    bg_css = f'url("{bg_uri}")' if bg_uri else 'none'

    return f"""
    <style>
    /* ════════════════════════════════════════════════════════════════
       1. GLOBAL CYBER NEON BLUE PITCH COCKPIT ATMOSPHERE
       ════════════════════════════════════════════════════════════════ */
    .stApp {{
        background: linear-gradient(rgba(7, 14, 24, 0.88), rgba(9, 20, 36, 0.92)), {bg_css} no-repeat center center fixed !important;
        background-size: cover !important;
        color: #f8fafc !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
        font-size: 1.05rem !important;
    }}

    .main .block-container {{
        padding-top: 1.5rem !important;
        padding-bottom: 3.5rem !important;
        max-width: 98% !important;
    }}

    /* Global Headings: Pure White with Electric Cyan Glow */
    h1, h2, h3, h4, h5, h6 {{
        color: #ffffff !important;
        font-weight: 900 !important;
        letter-spacing: -0.01em !important;
        text-shadow: 0 0 14px rgba(0, 240, 255, 0.45) !important;
    }}

    /* Body Text & Paragraphs */
    p, span, label {{
        color: #f1f5f9 !important;
    }}

    /* Captions & Subtitles */
    div[data-testid="stCaptionContainer"] p,
    .stCaption,
    small {{
        color: #94a3b8 !important;
        font-size: 0.96rem !important;
        font-weight: 600 !important;
    }}

    /* Sidebar Cyber Stadium Styling */
    [data-testid="stSidebar"] {{
        background: linear-gradient(rgba(6, 12, 22, 0.95), rgba(10, 22, 38, 0.97)), {bg_css} no-repeat center center fixed !important;
        background-size: cover !important;
        border-right: 2px solid #00f0ff !important;
        box-shadow: 4px 0 25px rgba(0, 240, 255, 0.18) !important;
    }}
    [data-testid="stSidebar"] h1, 
    [data-testid="stSidebar"] h2, 
    [data-testid="stSidebar"] h3 {{
        color: #ffffff !important;
        font-weight: 900 !important;
        text-shadow: 0 0 12px rgba(0, 240, 255, 0.5) !important;
    }}
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] span {{
        color: #f1f5f9 !important;
        font-weight: 700 !important;
    }}

    /* ════════════════════════════════════════════════════════════════
       2. WIDGET LABELS (ELECTRIC CYAN NEON)
       ════════════════════════════════════════════════════════════════ */
    label[data-testid="stWidgetLabel"],
    div[data-testid="stWidgetLabel"] p,
    label p,
    .stSelectbox label p,
    .stMultiSelect label p,
    .stNumberInput label p,
    .stTextInput label p {{
        color: #00f0ff !important;
        font-size: 1.05rem !important;
        font-weight: 800 !important;
        margin-bottom: 6px !important;
        text-shadow: 0 0 8px rgba(0, 240, 255, 0.3) !important;
    }}

    /* ════════════════════════════════════════════════════════════════
       3. METRIC CARDS & KPIS (Midnight Glass with Electric Cyan Border)
       ════════════════════════════════════════════════════════════════ */
    .metric-card {{
        background: linear-gradient(135deg, rgba(12, 26, 46, 0.92) 0%, rgba(8, 18, 33, 0.95) 100%) !important;
        border: 1.5px solid #00f0ff !important;
        border-radius: 12px !important;
        padding: 18px 20px !important;
        color: #ffffff !important;
        margin-bottom: 14px !important;
        box-shadow: 0 0 18px rgba(0, 240, 255, 0.16) !important;
        transition: all 0.2s ease-in-out !important;
    }}
    .metric-card:hover {{
        border-color: #38bdf8 !important;
        box-shadow: 0 0 25px rgba(0, 240, 255, 0.35) !important;
        transform: translateY(-2px) !important;
    }}
    .metric-title {{
        font-size: 1.02rem !important;
        color: #7dd3fc !important;
        font-weight: 800 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.04em !important;
    }}
    .metric-val {{
        font-size: 2.3rem !important;
        font-weight: 900 !important;
        color: #00f0ff !important;
        text-shadow: 0 0 16px rgba(0, 240, 255, 0.5) !important;
    }}

    div[data-testid="stMetric"] {{
        background: linear-gradient(135deg, rgba(12, 26, 46, 0.92) 0%, rgba(8, 18, 33, 0.95) 100%) !important;
        border: 1.5px solid #00f0ff !important;
        border-radius: 12px !important;
        padding: 14px 18px !important;
        box-shadow: 0 0 18px rgba(0, 240, 255, 0.16) !important;
    }}
    div[data-testid="stMetricLabel"] p {{
        font-size: 1.05rem !important;
        font-weight: 800 !important;
        color: #7dd3fc !important;
    }}
    div[data-testid="stMetricValue"] {{
        font-size: 2.3rem !important;
        font-weight: 900 !important;
        color: #00f0ff !important;
        text-shadow: 0 0 16px rgba(0, 240, 255, 0.5) !important;
    }}

    /* ════════════════════════════════════════════════════════════════
       4. TABS
       ════════════════════════════════════════════════════════════════ */
    button[data-baseweb="tab"] {{
        font-size: 1.15rem !important;
        font-weight: 800 !important;
        color: #94a3b8 !important;
        padding: 10px 22px !important;
        transition: all 0.2s ease !important;
    }}
    button[data-baseweb="tab"] p {{
        color: inherit !important;
        font-size: inherit !important;
        font-weight: inherit !important;
    }}
    button[data-baseweb="tab"][aria-selected="true"] {{
        color: #00f0ff !important;
        background: rgba(0, 240, 255, 0.12) !important;
        border-bottom: 4px solid #00f0ff !important;
        border-radius: 8px 8px 0 0 !important;
        font-size: 1.18rem !important;
        text-shadow: 0 0 12px rgba(0, 240, 255, 0.7) !important;
        box-shadow: inset 0 -2px 10px rgba(0, 240, 255, 0.25) !important;
    }}
    button[data-baseweb="tab"][aria-selected="true"] p {{
        color: #00f0ff !important;
    }}

    /* ════════════════════════════════════════════════════════════════
       5. EXPANDERS & ACCORDIONS (Midnight Blue Container)
       ════════════════════════════════════════════════════════════════ */
    div[data-testid="stExpander"] {{
        background: linear-gradient(135deg, rgba(12, 26, 46, 0.92) 0%, rgba(8, 18, 33, 0.95) 100%) !important;
        border: 1.5px solid #0284c7 !important;
        border-radius: 10px !important;
        margin-bottom: 12px !important;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.35) !important;
    }}
    div[data-testid="stExpander"]:hover {{
        border-color: #00f0ff !important;
        box-shadow: 0 0 16px rgba(0, 240, 255, 0.25) !important;
    }}
    div[data-testid="stExpander"] summary {{
        color: #ffffff !important;
    }}
    div[data-testid="stExpander"] summary p,
    div[data-testid="stExpander"] summary span {{
        color: #ffffff !important;
        font-size: 1.08rem !important;
        font-weight: 800 !important;
    }}
    div[data-testid="stExpander"] svg {{
        color: #00f0ff !important;
        fill: #00f0ff !important;
    }}

    /* ════════════════════════════════════════════════════════════════
       6. CHECKBOXES
       ════════════════════════════════════════════════════════════════ */
    div[data-testid="stCheckbox"] {{
        background: #0d223a !important;
        border: 1.5px solid #0284c7 !important;
        border-radius: 8px !important;
        padding: 8px 16px !important;
        margin: 4px 0 !important;
        display: inline-flex !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3) !important;
    }}
    div[data-testid="stCheckbox"]:hover {{
        border-color: #00f0ff !important;
        background: #112d4e !important;
        box-shadow: 0 0 14px rgba(0, 240, 255, 0.3) !important;
    }}
    div[data-testid="stCheckbox"] label p,
    div[data-testid="stCheckbox"] label span,
    label[data-baseweb="checkbox"] p,
    label[data-baseweb="checkbox"] span {{
        color: #f8fafc !important;
        font-size: 1.05rem !important;
        font-weight: 800 !important;
    }}
    div[data-testid="stCheckbox"] span[data-baseweb="checkbox"] > span:first-child,
    label[data-baseweb="checkbox"] > span:first-child {{
        background-color: #071526 !important;
        border: 2px solid #00f0ff !important;
        border-radius: 4px !important;
    }}
    div[data-testid="stCheckbox"] svg,
    label[data-baseweb="checkbox"] svg {{
        color: #00f0ff !important;
        fill: #00f0ff !important;
        stroke: #00f0ff !important;
        stroke-width: 3.5px !important;
    }}

    /* ════════════════════════════════════════════════════════════════
       7. SELECTBOXES, MULTISELECTS & INPUTS
       ════════════════════════════════════════════════════════════════ */
    div[data-baseweb="select"] > div,
    div[data-baseweb="select"] > div:focus-within {{
        background-color: #0b1d33 !important;
        border: 1.5px solid #0284c7 !important;
        border-radius: 8px !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35) !important;
    }}
    div[data-baseweb="select"] > div:focus-within {{
        border-color: #00f0ff !important;
        box-shadow: 0 0 16px rgba(0, 240, 255, 0.45) !important;
    }}
    div[data-baseweb="select"] *,
    div[data-baseweb="select"] span,
    div[data-baseweb="select"] div[aria-selected],
    div[data-baseweb="select"] div {{
        color: #ffffff !important;
        font-weight: 800 !important;
        font-size: 1.05rem !important;
    }}
    div[data-baseweb="select"] input::placeholder {{
        color: #64748b !important;
        font-weight: 600 !important;
    }}
    div[data-baseweb="select"] svg {{
        fill: #00f0ff !important;
        color: #00f0ff !important;
    }}

    /* Multiselect Tags (Cyan Badges) */
    span[data-baseweb="tag"] {{
        background-color: #0284c7 !important;
        border: 1px solid #00f0ff !important;
        border-radius: 6px !important;
        padding: 3px 10px !important;
        box-shadow: 0 0 10px rgba(0, 240, 255, 0.35) !important;
    }}
    span[data-baseweb="tag"] *,
    span[data-baseweb="tag"] span {{
        color: #ffffff !important;
        font-weight: 800 !important;
        font-size: 0.98rem !important;
    }}
    span[data-baseweb="tag"] svg {{
        fill: #ffffff !important;
        color: #ffffff !important;
    }}

    /* Dropdown Menus / Popovers */
    div[data-baseweb="popover"],
    div[data-baseweb="popover"] > div,
    ul[data-baseweb="menu"],
    ul[role="listbox"] {{
        background-color: #081729 !important;
        border: 2px solid #00f0ff !important;
        border-radius: 8px !important;
        box-shadow: 0 10px 30px rgba(0, 240, 255, 0.25) !important;
    }}
    li[data-baseweb="menu-item"],
    li[role="option"] {{
        background-color: #081729 !important;
        color: #f8fafc !important;
        font-size: 1.05rem !important;
        font-weight: 700 !important;
        padding: 10px 16px !important;
        border-bottom: 1px solid #132d4e !important;
    }}
    li[data-baseweb="menu-item"] *,
    li[role="option"] * {{
        color: #f8fafc !important;
        font-weight: 700 !important;
    }}
    li[data-baseweb="menu-item"]:hover,
    li[role="option"]:hover,
    li[data-baseweb="menu-item"][aria-selected="true"],
    li[role="option"][aria-selected="true"] {{
        background-color: #0284c7 !important;
        color: #ffffff !important;
    }}
    li[data-baseweb="menu-item"]:hover *,
    li[role="option"]:hover *,
    li[data-baseweb="menu-item"][aria-selected="true"] *,
    li[role="option"][aria-selected="true"] * {{
        color: #ffffff !important;
    }}

    /* Number & Text Inputs */
    div[data-testid="stNumberInput"] input,
    div[data-testid="stTextInput"] input {{
        background-color: #0b1d33 !important;
        color: #ffffff !important;
        border: 1.5px solid #0284c7 !important;
        border-radius: 8px !important;
        font-weight: 800 !important;
        font-size: 1.05rem !important;
        padding: 8px 12px !important;
    }}
    div[data-testid="stNumberInput"] input:focus,
    div[data-testid="stTextInput"] input:focus {{
        border-color: #00f0ff !important;
        box-shadow: 0 0 16px rgba(0, 240, 255, 0.45) !important;
    }}
    div[data-testid="stNumberInput"] button {{
        background-color: #132d4e !important;
        border: 1px solid #0284c7 !important;
        color: #00f0ff !important;
    }}
    div[data-testid="stNumberInput"] button svg {{
        fill: #00f0ff !important;
        color: #00f0ff !important;
    }}

    /* ════════════════════════════════════════════════════════════════
       8. TABLES & DATAFRAMES (Midnight Cyber Rows with Neon Headers)
       ════════════════════════════════════════════════════════════════ */
    div[data-testid="stDataFrame"],
    div[data-testid="stDataFrame"] > div,
    div[data-testid="stTable"] {{
        background-color: #081627 !important;
        border: 2px solid #00f0ff !important;
        border-radius: 12px !important;
        box-shadow: 0 6px 25px rgba(0, 240, 255, 0.15) !important;
        overflow: hidden !important;
    }}
    table {{
        background-color: #081627 !important;
        border-collapse: separate !important;
        border-spacing: 0 !important;
        border: 2px solid #00f0ff !important;
        border-radius: 12px !important;
        overflow: hidden !important;
        width: 100% !important;
        color: #f1f5f9 !important;
    }}
    th {{
        background: linear-gradient(135deg, #0b2545 0%, #133a68 100%) !important;
        color: #00f0ff !important;
        font-size: 1.05rem !important;
        font-weight: 900 !important;
        padding: 12px 14px !important;
        text-transform: uppercase !important;
        letter-spacing: 0.04em !important;
        border-bottom: 2px solid #00f0ff !important;
        text-shadow: 0 0 8px rgba(0, 240, 255, 0.4) !important;
    }}
    td {{
        background-color: #081627 !important;
        color: #f1f5f9 !important;
        font-size: 1.02rem !important;
        font-weight: 700 !important;
        padding: 10px 14px !important;
        border-bottom: 1px solid #132d4e !important;
    }}
    tr:nth-child(even) td {{
        background-color: #0d2038 !important;
        color: #f1f5f9 !important;
    }}
    tr:hover td {{
        background-color: #173d6b !important;
        color: #ffffff !important;
    }}

    /* ════════════════════════════════════════════════════════════════
       9. BUTTONS (High-Impact Neon Cyan & Deep Navy)
       ════════════════════════════════════════════════════════════════ */
    /* Primary Action Buttons */
    button[kind="primary"],
    div.stButton > button[data-testid="baseButton-primary"],
    div.stButton > button[kind="primary"] {{
        background: linear-gradient(135deg, #0284c7 0%, #00f0ff 100%) !important;
        border: none !important;
        border-radius: 8px !important;
        box-shadow: 0 0 20px rgba(0, 240, 255, 0.5) !important;
        padding: 9px 20px !important;
        transition: all 0.2s ease-in-out !important;
    }}
    button[kind="primary"] *,
    button[kind="primary"] p,
    button[kind="primary"] span,
    div.stButton > button[data-testid="baseButton-primary"] *,
    div.stButton > button[data-testid="baseButton-primary"] p,
    div.stButton > button[data-testid="baseButton-primary"] span {{
        color: #031326 !important;
        font-size: 1.08rem !important;
        font-weight: 900 !important;
    }}
    button[kind="primary"]:hover,
    div.stButton > button[data-testid="baseButton-primary"]:hover {{
        background: linear-gradient(135deg, #38bdf8 0%, #ffffff 100%) !important;
        box-shadow: 0 0 30px rgba(0, 240, 255, 0.85) !important;
        transform: translateY(-2px) !important;
    }}

    /* Secondary / Default Buttons */
    button[kind="secondary"],
    div.stButton > button[data-testid="baseButton-secondary"],
    div.stButton > button {{
        background: #0d223a !important;
        border: 1.5px solid #0284c7 !important;
        border-radius: 8px !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3) !important;
        padding: 9px 18px !important;
        transition: all 0.2s ease-in-out !important;
    }}
    button[kind="secondary"] *,
    button[kind="secondary"] p,
    button[kind="secondary"] span,
    div.stButton > button *,
    div.stButton > button p,
    div.stButton > button span {{
        color: #38bdf8 !important;
        font-size: 1.05rem !important;
        font-weight: 800 !important;
    }}
    button[kind="secondary"]:hover,
    div.stButton > button[data-testid="baseButton-secondary"]:hover,
    div.stButton > button:hover {{
        background: #0284c7 !important;
        border-color: #00f0ff !important;
        box-shadow: 0 0 18px rgba(0, 240, 255, 0.5) !important;
        transform: translateY(-1px) !important;
    }}
    button[kind="secondary"]:hover *,
    div.stButton > button:hover * {{
        color: #ffffff !important;
    }}

    /* Download Buttons */
    div.stDownloadButton > button {{
        background: linear-gradient(135deg, #0369a1 0%, #0284c7 100%) !important;
        border: 1.5px solid #00f0ff !important;
        border-radius: 8px !important;
        box-shadow: 0 0 16px rgba(0, 240, 255, 0.3) !important;
        padding: 9px 18px !important;
    }}
    div.stDownloadButton > button * {{
        color: #ffffff !important;
        font-weight: 800 !important;
    }}
    div.stDownloadButton > button:hover {{
        background: #00f0ff !important;
        box-shadow: 0 0 25px rgba(0, 240, 255, 0.7) !important;
    }}
    div.stDownloadButton > button:hover * {{
        color: #031326 !important;
    }}

    /* ════════════════════════════════════════════════════════════════
       10. PLAYER CARDS & MODAL DIALOG FULLSCREEN (CYBER COCKPIT)
       ════════════════════════════════════════════════════════════════ */
    .player-card {{
        background: linear-gradient(135deg, rgba(12, 26, 46, 0.94) 0%, rgba(8, 18, 33, 0.97) 100%) !important;
        border: 1.5px solid #0284c7 !important;
        border-radius: 10px !important;
        padding: 14px 16px !important;
        color: #f8fafc !important;
        box-shadow: 0 4px 18px rgba(0, 0, 0, 0.4) !important;
        transition: all 0.2s ease !important;
    }}
    .player-card:hover {{
        border-color: #00f0ff !important;
        box-shadow: 0 0 22px rgba(0, 240, 255, 0.35) !important;
        transform: translateY(-2px) !important;
    }}

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
        background: linear-gradient(rgba(7, 15, 27, 0.96), rgba(9, 21, 38, 0.98)), {bg_css} no-repeat center center !important;
        background-size: cover !important;
        border: 2px solid #00f0ff !important;
        box-shadow: 0 0 50px rgba(0, 240, 255, 0.35) !important;
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

    /* Dialog Close Button "X" */
    div[data-testid="stDialog"] button[aria-label="Close"],
    .stDialog button[aria-label="Close"] {{
        background: #0d223a !important;
        border: 2px solid #00f0ff !important;
        border-radius: 50% !important;
        color: #00f0ff !important;
        padding: 6px !important;
        opacity: 1 !important;
        box-shadow: 0 0 12px rgba(0, 240, 255, 0.4) !important;
    }}
    div[data-testid="stDialog"] button[aria-label="Close"] svg,
    .stDialog button[aria-label="Close"] svg {{
        color: #00f0ff !important;
        fill: #00f0ff !important;
        stroke: #00f0ff !important;
    }}
    div[data-testid="stDialog"] button[aria-label="Close"]:hover,
    .stDialog button[aria-label="Close"]:hover {{
        background: #ef4444 !important;
        border-color: #ffffff !important;
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

    /* ════════════════════════════════════════════════════════════════
       11. HIGH-CONTRAST LOAN & STATUS BADGES
       ════════════════════════════════════════════════════════════════ */
    .badge-prestito-in {{
        background: #00f0ff !important;
        color: #031326 !important;
        padding: 4px 10px !important;
        border-radius: 6px !important;
        font-weight: 900 !important;
        font-size: 0.95rem !important;
        display: inline-block !important;
        box-shadow: 0 0 12px rgba(0, 240, 255, 0.6) !important;
    }}
    .badge-prestito-out {{
        background: #f59e0b !important;
        color: #031326 !important;
        padding: 4px 10px !important;
        border-radius: 6px !important;
        font-weight: 900 !important;
        font-size: 0.95rem !important;
        display: inline-block !important;
        box-shadow: 0 0 12px rgba(245, 158, 11, 0.5) !important;
    }}
    .badge-svincolo {{
        background: #ef4444 !important;
        color: #ffffff !important;
        padding: 4px 10px !important;
        border-radius: 6px !important;
        font-weight: 900 !important;
        font-size: 0.95rem !important;
        box-shadow: 0 0 12px rgba(239, 68, 68, 0.5) !important;
    }}
    </style>
    """
