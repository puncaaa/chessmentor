import os
from typing import Optional, Dict, Any, List
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
    plies: Optional[List[Dict[str, Any]]] = None,
    initial_ply: int = 0,
    key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Интерактивная шахматная доска с поддержкой Drag-and-Drop и быстрым клиентским предпросмотром ходов.
    
    В режиме 'plies' позволяет мгновенно перемещаться по ходам партии без сетевых раундтрипов и мерцания.
    """
    return _interactive_chessboard(
        fen=fen,
        orientation=orientation,
        allow_moves=allow_moves,
        highlight_move=highlight_move,
        animate_best_move=animate_best_move,
        best_move_uci=best_move_uci,
        plies=plies,
        initial_ply=initial_ply,
        key=key,
        default=None,
    )
