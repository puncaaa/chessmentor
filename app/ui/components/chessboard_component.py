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
    theme: str = "dark",
    key: Optional[str] = None,
    best_move: Optional[str] = None,
    student_move: Optional[str] = None,
    eval_score: Optional[float] = None,
    **kwargs: Any,
) -> Optional[Dict[str, Any]]:
    """
    Интерактивная шахматная доска с поддержкой Drag-and-Drop и быстрым клиентским предпросмотром ходов.
    
    В режиме 'plies' позволяет мгновенно перемещаться по ходам партии без сетевых раундтрипов и мерцания.
    Поддерживает темы оформления ('dark' / 'light').
    Принимает альтернативные алиасы: best_move -> best_move_uci, student_move -> highlight_move.
    """
    # Совместимость с альтернативными параметрами вызова
    if best_move and not best_move_uci:
        best_move_uci = best_move

    if student_move and not highlight_move and isinstance(student_move, str) and len(student_move) >= 4:
        highlight_move = {
            "from": student_move[:2],
            "to": student_move[2:4],
            "type": "error",
        }

    return _interactive_chessboard(
        fen=fen,
        orientation=orientation,
        allow_moves=allow_moves,
        highlight_move=highlight_move,
        animate_best_move=animate_best_move,
        best_move_uci=best_move_uci,
        plies=plies,
        initial_ply=initial_ply,
        theme=theme,
        key=key,
        default=None,
    )
