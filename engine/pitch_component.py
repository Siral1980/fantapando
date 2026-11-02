import os
import streamlit.components.v1 as components

_COMPONENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pitch_component")
_pitch_component = components.declare_component("tactical_pitch", path=_COMPONENT_DIR)

def render_tactical_pitch(html_markup: str, key: str = None):
    """
    Renders the tactical pitch using a lightweight Streamlit component.
    Captures box clicks and passes the selected player name to Python via WebSocket,
    without triggering full page reloads or losing authentication session state.
    """
    return _pitch_component(html=html_markup, key=key)
