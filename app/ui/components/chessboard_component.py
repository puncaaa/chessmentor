import os
from typing import Optional, Dict, Any
import streamlit.components.v1 as components

# Путь к HTML/JS коду компонента
_COMPONENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "chessboard"))
_interactive_chessboard = components.declare_component("interactive_chessboard", path=_COMPONENT_DIR)


def render_interactive_chessboard(
    fen: str,
    orientation: str = "white",
    allow_moves: bool = True,
    highlight_move: Optional[Dict[str, str]] = None,
    animate_best_move: bool = False,
    best_move_uci: Optional[str] = None,
    key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Интерактивная шахматная доска с поддержкой Drag-and-Drop на базе chessboard.js и chess.js.
    
    Возвращает dict при совершении хода пользователем:
    {
        'event': 'move_played',
        'from': 'e2',
        'to': 'e4',
        'san': 'e4',
        'uci': 'e2e4',
        'fen_after': '...',
        'in_check': bool,
        'is_game_over': bool,
        'turn': 'b' | 'w',
        'timestamp': int
    }
    """
    return _interactive_chessboard(
        fen=fen,
        orientation=orientation,
        allow_moves=allow_moves,
        highlight_move=highlight_move,
        animate_best_move=animate_best_move,
        best_move_uci=best_move_uci,
        key=key,
        default=None,
    )
