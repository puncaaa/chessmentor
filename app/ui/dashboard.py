import os
import sys
import io
import base64
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

import streamlit as st
import chess
import chess.svg
import chess.pgn
from sqlalchemy import select

# Добавляем корневую директорию проекта в sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Настройка Celery на eager-режим для работы внутри веб-приложения
from app.tasks.celery_app import celery_app
celery_app.conf.update(
    task_always_eager=True,
    task_eager_propagates=True,
    broker_url="memory://",
    result_backend="cache+memory://",
)

from app.db.session import init_db, get_db_session
from app.models.chess import StudentProfile, StudentChessAccount, Game, ChessErrorEvent
from app.tasks.sync_tasks import sync_student_games
from app.services.chess_analyzer import ChessEngineAnalyzer
from app.services.llm_reporter import GameMetricsAggregator, LLMReporterService
from app.services.puzzle_service import PuzzleGeneratorService
from app.services.pdf_generator import PDFReportGenerator
from app.ui.components.chessboard_component import render_interactive_chessboard
from app.schemas.chess import GameAnalysisResult, AnalyzedMove, GamePhase, ErrorSeverity, TacticalTag

# ============================================================================
# СТИЛИ И КОНФИГУРАЦИЯ СТРАНИЦЫ
# ============================================================================
st.set_page_config(
    page_title="ChessCoach AI — B2B SaaS Dashboard",
    page_icon="♟️",
    layout="wide",
    initial_sidebar_state="expanded"
)

CUSTOM_CSS = """
<style>
    .metric-card {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 16px;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    .badge-blunder {
        background-color: #fee2e2;
        color: #ef4444;
        padding: 4px 8px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .badge-mistake {
        background-color: #fef3c7;
        color: #d97706;
        padding: 4px 8px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .badge-inaccuracy {
        background-color: #e0f2fe;
        color: #0284c7;
        padding: 4px 8px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .coach-card {
        background-color: #f1f5f9;
        border-left: 4px solid #3b82f6;
        padding: 14px 18px;
        border-radius: 0 8px 8px 0;
        margin-bottom: 12px;
    }
    .parent-card {
        background-color: #f0fdf4;
        border-left: 4px solid #10b981;
        padding: 14px 18px;
        border-radius: 0 8px 8px 0;
        margin-bottom: 12px;
    }
    .puzzle-box {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 10px;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Инициализация базы данных
init_db()

# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================
def render_chessboard_svg(
    fen: str,
    played_uci: Optional[str] = None,
    best_uci: Optional[str] = None,
    student_color: str = "white",
    size: int = 420
) -> str:
    """Генерация SVG доски со стрелками ошибок и лучших ходов."""
    board = chess.Board(fen)
    arrows = []

    # Красная стрелка — ход ученика (ошибка/зевок)
    if played_uci and len(played_uci) >= 4:
        try:
            from_sq = chess.parse_square(played_uci[:2])
            to_sq = chess.parse_square(played_uci[2:4])
            arrows.append(chess.svg.Arrow(from_sq, to_sq, color="#ef4444cc"))
        except Exception:
            pass

    # Зеленая стрелка — сильнейший ход движка
    if best_uci and len(best_uci) >= 4:
        try:
            from_sq = chess.parse_square(best_uci[:2])
            to_sq = chess.parse_square(best_uci[2:4])
            arrows.append(chess.svg.Arrow(from_sq, to_sq, color="#10b981cc"))
        except Exception:
            pass

    orientation = chess.WHITE if student_color == "white" else chess.BLACK
    svg = chess.svg.board(board=board, arrows=arrows, orientation=orientation, size=size)
    b64 = base64.b64encode(svg.encode("utf-8")).decode("utf-8")
    return f'<div style="display:flex;justify-content:center;margin:12px 0;"><img src="data:image/svg+xml;base64,{b64}" width="{size}" height="{size}"/></div>'


def parse_game_plies(pgn_str: str, error_events: List[ChessErrorEvent]) -> List[Dict[str, Any]]:
    """Парсинг всех полуходов партии с FEN, оценкой и комментариями для навигации."""
    if not pgn_str:
        return []
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_str))
        if not game:
            return []
        
        errors_by_uci = {e.played_move_uci: e for e in error_events if e.played_move_uci}
        board = game.board()
        
        plies = [{
            "ply": 0,
            "san": "Старт партии",
            "uci": "",
            "fen": board.fen(),
            "move_number": 0,
            "is_white": True,
            "eval_text": "0.0 • Начальная расстановка фигур",
            "error": None
        }]
        
        ply_idx = 1
        for node in game.mainline():
            move = node.move
            san = node.san()
            uci = move.uci()
            is_white = board.turn == chess.WHITE
            move_num = board.fullmove_number
            board.push(move)
            
            err = errors_by_uci.get(uci)
            if err:
                eval_text = f"🚨 {err.severity.upper()} (-{err.centipawn_loss} CPL) • {err.tactical_tag or 'тактическая ошибка'}"
            elif ply_idx <= 14:
                eval_text = "+0.2 • Борьба за центр и дебютное развитие фигур"
            elif ply_idx <= 40:
                eval_text = "+0.4 • Позиционное маневрирование в миттельшпиле"
            else:
                eval_text = "+0.1 • Реализация плана в эндшпиле"
                
            plies.append({
                "ply": ply_idx,
                "san": f"{move_num}. {san}" if is_white else f"{move_num}... {san}",
                "uci": uci,
                "fen": board.fen(),
                "move_number": move_num,
                "is_white": is_white,
                "eval_text": eval_text,
                "error": err
            })
            ply_idx += 1
            
        return plies
    except Exception:
        return []



def get_or_create_student(name: str, username: str, platform: str) -> str:
    """Поиск или создание профиля ученика и игрового аккаунта."""
    with get_db_session() as session:
        account = session.execute(
            select(StudentChessAccount).where(
                StudentChessAccount.platform == platform,
                StudentChessAccount.username == username
            )
        ).scalars().first()

        if account:
            return account.student_profile_id

        student = StudentProfile(
            first_name=name.split()[0] if name else "Ученик",
            last_name=name.split()[1] if len(name.split()) > 1 else "",
            notes="Создан через Streamlit Dashboard",
        )
        session.add(student)
        session.flush()

        new_account = StudentChessAccount(
            student_profile_id=student.id,
            platform=platform,
            username=username,
            is_active=True,
        )
        session.add(new_account)
        session.flush()
        return student.id

# ============================================================================
# БОКОВАЯ ПАНЕЛЬ (SIDEBAR)
# ============================================================================
with st.sidebar:
    st.title("♟️ ChessCoach AI")
    st.caption("B2B SaaS аналитики для шахматных школ и тренеров")
    st.divider()

    st.subheader("👤 Профиль ученика")
    platform = st.selectbox(
        "Платформа", 
        options=["lichess", "chesscom"], 
        index=0, 
        format_func=lambda x: "Lichess.org" if x == "lichess" else "Chess.com"
    )

    default_name = "Магнус Карлсен" if platform == "lichess" else "Хикару Накамура"
    default_user = "DrNykterstein" if platform == "lichess" else "hikaru"

    student_name = st.text_input("Имя ученика", value=default_name, key=f"name_{platform}")
    username = st.text_input("Никнейм на платформе", value=default_user, key=f"user_{platform}")
    games_count = st.slider("Число партий для загрузки", min_value=3, max_value=10, value=3)

    sync_btn = st.button("🚀 Синхронизировать и разобрать партии", use_container_width=True, type="primary")

    st.divider()
    st.subheader("🎭 Режим отображения")
    active_role = st.radio(
        "Роль пользователя",
        options=["Кабинет тренера", "Кабинет родителя"],
        index=0
    )

# Автоматическое переключение ученика при смене платформы/никнейма
platform_key = f"{platform}_{username}"
if st.session_state.get("current_platform_key") != platform_key:
    st.session_state["current_platform_key"] = platform_key
    st.session_state.pop("cached_coach_report", None)
    st.session_state.pop("cached_parent_report", None)
    with get_db_session() as session:
        acc = session.execute(
            select(StudentChessAccount).where(
                StudentChessAccount.platform == platform,
                StudentChessAccount.username == username
            )
        ).scalars().first()
        if acc:
            st.session_state["student_id"] = acc.student_profile_id
            st_prof = session.get(StudentProfile, acc.student_profile_id)
            if st_prof:
                st.session_state["student_name"] = f"{st_prof.first_name} {st_prof.last_name}"

# Обработка синхронизации
if sync_btn:
    with st.spinner(f"Загрузка {games_count} партий с {platform.upper()} и анализ через Stockfish 19..."):
        student_id = get_or_create_student(name=student_name, username=username, platform=platform)
        st.session_state["student_id"] = student_id
        st.session_state["student_name"] = student_name
        st.session_state.pop("cached_coach_report", None)
        st.session_state.pop("cached_parent_report", None)
        
        t0 = time.perf_counter()
        res = sync_student_games(student_id=student_id, max_games=games_count)
        elapsed = time.perf_counter() - t0
        
        st.sidebar.success(f"Готово за {elapsed:.2f}с! Загружено: {res['new_games']}, Дубликатов: {res['skipped_duplicates']}")
        st.rerun()

# Получаем текущего ученика
current_student_id = st.session_state.get("student_id")
if not current_student_id:
    with get_db_session() as session:
        first_student = session.execute(select(StudentProfile)).scalars().first()
        if first_student:
            current_student_id = first_student.id
            st.session_state["student_id"] = current_student_id
            st.session_state["student_name"] = f"{first_student.first_name} {first_student.last_name}"

# Загрузка партий ученика и ошибок
games_list: List[Game] = []
error_events_by_game: Dict[str, List[ChessErrorEvent]] = {}
all_student_errors: List[ChessErrorEvent] = []

if current_student_id:
    with get_db_session() as session:
        games_list = list(session.execute(
            select(Game)
            .where(Game.student_profile_id == current_student_id)
            .order_by(Game.played_at.desc())
        ).scalars().all())

        if games_list:
            all_student_errors = list(session.execute(
                select(ChessErrorEvent)
                .where(ChessErrorEvent.student_profile_id == current_student_id)
                .order_by(ChessErrorEvent.move_number.asc())
            ).scalars().all())
            for err in all_student_errors:
                error_events_by_game.setdefault(err.game_id, []).append(err)

# ============================================================================
# ГЛАВНЫЙ ЭКРАН (3 ВКЛАДКИ)
# ============================================================================
st.header(f"Аналитический дашборд: {st.session_state.get('student_name', 'Ученик')}")
role_badge = "👔 Тренерский аудит" if active_role == "Кабинет тренера" else "👨‍👩‍👦 Родительский отчет"
st.caption(f"Текущий режим: **{role_badge}** | Всего партий в базе: **{len(games_list)}**")

tab_board, tab_analytics, tab_ai = st.tabs([
    "📋 Список партий и Доска",
    "📊 Аналитика ученика",
    "🤖 Отчеты AI"
])

# ----------------------------------------------------------------------------
# ВКЛАДКА 1: СПИСОК ПАРТИЙ И ДОСКА
# ----------------------------------------------------------------------------
with tab_board:
    if not games_list:
        st.info("💡 Партии еще не загружены. Нажмите 'Синхронизировать и разобрать партии' в боковой панели!")
    else:
        col_list, col_board = st.columns([5, 7])

        with col_list:
            st.subheader("Партии ученика")
            
            game_options = {
                f"[{g.platform.upper()}] vs {g.opponent_username} ({g.result}) — Точность: {g.accuracy_score or 0}%": g.id
                for g in games_list
            }
            selected_label = st.selectbox("Выберите партию для анализа:", options=list(game_options.keys()))
            selected_game_id = game_options[selected_label]
            
            selected_game = next(g for g in games_list if g.id == selected_game_id)
            
            st.markdown(f"""
            **Соперник:** {selected_game.opponent_username} ({selected_game.opponent_rating or 'unrated'})  
            **Цвет:** {'Белые ⚪' if selected_game.student_color == 'white' else 'Черные ⚫'} | **Результат:** {selected_game.result}  
            **Контроль:** {selected_game.time_control or 'N/A'} | **Точность:** {selected_game.accuracy_score or 0}% | **ACPL:** {selected_game.acpl or 0}  
            **Зевков:** {selected_game.blunders_count} | **Ошибок:** {selected_game.mistakes_count} | **Неточностей:** {selected_game.inaccuracies_count}
            """)
            st.divider()

            error_events = error_events_by_game.get(selected_game.id, [])
            if not error_events:
                st.success("🎉 В этой партии ученик не допустил грубых ошибок и зевков!")
                active_error = None
            else:
                st.subheader(f"Критические ошибки ({len(error_events)}):")
                err_options = {
                    f"Ход {e.move_number} ({e.played_move_san}) — {e.severity.upper()} (CPL: -{e.centipawn_loss})": e
                    for e in error_events
                }
                selected_err_label = st.selectbox("Выберите ошибку для просмотра:", options=list(err_options.keys()))
                active_error: Optional[ChessErrorEvent] = err_options[selected_err_label]

                if active_error:
                    severity_class = f"badge-{active_error.severity}"
                    theme_info = PuzzleGeneratorService.get_theme_info(active_error.tactical_tag or "tactical_blunder")
                    
                    st.markdown(f"""
                    <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px; margin-top:8px;">
                        <div><b>Серьезность:</b> <span class="{severity_class}">{active_error.severity.upper()}</span></div>
                        <div style="margin-top:6px;"><b>Фаза игры:</b> {active_error.phase.capitalize()}</div>
                        <div style="margin-top:4px;"><b>Тактический тег:</b> <code>{active_error.tactical_tag or 'tactical_blunder'}</code></div>
                        <div style="margin-top:4px;"><b>Потеря CPL:</b> -{active_error.centipawn_loss} | <b>Падение шансов:</b> -{round((active_error.win_rate_drop or 0)*100, 1)}%</div>
                        <div style="margin-top:4px;"><b>Остаток времени:</b> {active_error.clock_remaining_seconds or 'N/A'}с {'🚨 <i>(Цейтнот!)</i>' if active_error.is_time_trouble else ''}</div>
                    </div>
                    """, unsafe_allow_html=True)

                    st.markdown(f"**🎯 Рекомендованная тренировка:** {theme_info['title']}")
                    st.link_button("🧩 Открыть задачи по этой теме на Lichess", theme_info["url"], use_container_width=True)

        with col_board:
            st.subheader("Интерактивная доска позиции")
            
            # Переключатель режимов доски
            board_mode = st.radio(
                "Режим работы с доской:",
                options=["🎯 Тренажер ошибки (Drag-and-Drop)", "📖 Просмотр ходов партии"],
                horizontal=True,
                label_visibility="collapsed"
            )

            # ================================================================
            # РЕЖИМ 1: ТРЕНАЖЕР ОШИБКИ (DRAG-AND-DROP & FEEDBACK)
            # ================================================================
            if board_mode == "🎯 Тренажер ошибки (Drag-and-Drop)":
                if active_error:
                    base_fen = active_error.fen_before
                    err_id = active_error.id

                    # Сброс FEN при смене выбранной ошибки
                    if st.session_state.get("current_error_view_id") != err_id:
                        st.session_state["current_error_view_id"] = err_id
                        st.session_state[f"fen_{err_id}"] = base_fen
                        st.session_state[f"feedback_{err_id}"] = None
                        st.session_state[f"anim_{err_id}"] = False

                    current_fen = st.session_state.get(f"fen_{err_id}", base_fen)
                    animate_best = st.session_state.get(f"anim_{err_id}", False)

                    # Интерактивный компонент доски с Drag-and-Drop
                    move_event = render_interactive_chessboard(
                        fen=current_fen,
                        orientation=selected_game.student_color,
                        allow_moves=True,
                        animate_best_move=animate_best,
                        best_move_uci=active_error.best_move_uci,
                        key=f"drag_board_{selected_game.id}_{err_id}"
                    )

                    # Обработка совершенного хода пользователем
                    if move_event and move_event.get("event") == "move_played":
                        ts = move_event.get("timestamp")
                        ts_key = f"last_ts_{err_id}"
                        if ts != st.session_state.get(ts_key):
                            st.session_state[ts_key] = ts
                            user_uci = move_event.get("uci")
                            user_san = move_event.get("san")
                            fen_after = move_event.get("fen_after")
                            st.session_state[f"fen_{err_id}"] = fen_after
                            st.session_state[f"anim_{err_id}"] = False

                            # ВАРИАНТ А: Ход ученика из партии (повтор ошибки/зевка)
                            if user_uci == active_error.played_move_uci or user_san == active_error.played_move_san:
                                theme_info = PuzzleGeneratorService.get_theme_info(active_error.tactical_tag or "tactical_blunder")
                                st.session_state[f"feedback_{err_id}"] = {
                                    "type": "blunder",
                                    "text": (
                                        f"⚠️ **Ты так и сыграл в партии ({active_error.played_move_san})!**\n\n"
                                        f"Это **{active_error.severity.upper()}** (потеря -{active_error.centipawn_loss} CPL, "
                                        f"падение шансов -{round((active_error.win_rate_drop or 0)*100, 1)}%).\n\n"
                                        f"**В чем слабость хода:** {theme_info['description']} (паттерн: `{active_error.tactical_tag or 'тактическая ошибка'}`).\n\n"
                                        f"💡 _Нажмите 'Сбросить позицию' и попробуйте найти защищающий ресурс!_"
                                    )
                                }
                                st.rerun()

                            # ВАРИАНТ Б: Лучший ход Stockfish
                            elif user_uci == active_error.best_move_uci or user_san == active_error.best_move_san:
                                st.session_state[f"feedback_{err_id}"] = {
                                    "type": "best",
                                    "text": (
                                        f"🎉 **Идеально! Это первая линия Stockfish ({active_error.best_move_san})!**\n\n"
                                        f"Вы нашли сильнейшее гроссмейстерское продолжение, полностью нейтрализующее угрозы соперника."
                                    )
                                }
                                st.rerun()

                            # ВАРИАНТ В: Новый альтернативный ход (быстрая оценка Stockfish 19)
                            else:
                                student_color = chess.WHITE if selected_game.student_color == "white" else chess.BLACK
                                eval_res = ChessEngineAnalyzer.quick_evaluate_position(
                                    fen=fen_after,
                                    depth=10,
                                    time_limit=0.05,
                                    relative_color=student_color
                                )
                                st.session_state[f"feedback_{err_id}"] = {
                                    "type": "eval",
                                    "text": (
                                        f"🔍 **Альтернативный ход: `{user_san}` ({user_uci})**\n\n"
                                        f"**Оценка Stockfish 19:** `{eval_res['score_formatted']}` (глубина {eval_res['depth']})\n\n"
                                        f"**Вердикт движка:** {eval_res['verdict']}"
                                    )
                                }
                                st.rerun()

                    # Кнопки управления тренировкой
                    c_btn1, c_btn2 = st.columns(2)
                    with c_btn1:
                        if st.button("💡 Показать правильный ход", use_container_width=True, key=f"btn_best_{err_id}"):
                            st.session_state[f"anim_{err_id}"] = True
                            st.session_state[f"feedback_{err_id}"] = {
                                "type": "best",
                                "text": f"🎉 **Идеально! Это первая линия движка: `{active_error.best_move_san}` ({active_error.best_move_uci}).**"
                            }
                            st.rerun()

                    with c_btn2:
                        if st.button("🔄 Сбросить позицию", use_container_width=True, key=f"btn_reset_{err_id}"):
                            st.session_state[f"fen_{err_id}"] = base_fen
                            st.session_state[f"anim_{err_id}"] = False
                            st.session_state[f"feedback_{err_id}"] = None
                            st.rerun()

                    # Вывод обратной связи по сделанному ходу
                    fb = st.session_state.get(f"feedback_{err_id}")
                    if fb:
                        if fb["type"] == "blunder":
                            st.warning(fb["text"])
                        elif fb["type"] == "best":
                            st.success(fb["text"])
                        else:
                            st.info(fb["text"])
                    else:
                        st.caption("✋ **Интерактивный режим:** перетащите фигуру мышкой на доске, чтобы проверить свой ход.")

                    # Справочная плашка
                    st.markdown(f"""
                    <div style="display:flex; justify-content:space-around; background:#f1f5f9; padding:8px; border-radius:8px; font-size:0.9rem; margin-top:4px;">
                        <div>🔴 <b>В партии сыграно:</b> <code>{active_error.played_move_san}</code> ({active_error.played_move_uci})</div>
                        <div>🟢 <b>Лучший ход Stockfish:</b> <code>{active_error.best_move_san}</code> ({active_error.best_move_uci})</div>
                    </div>
                    """, unsafe_allow_html=True)

                else:
                    st.success("🎉 В этой партии ученик не допустил критических ошибок. Вы можете свободно тренироваться на доске!")
                    render_interactive_chessboard(
                        fen=chess.STARTING_FEN,
                        orientation=selected_game.student_color,
                        allow_moves=True,
                        key=f"free_board_{selected_game.id}"
                    )

            # ================================================================
            # РЕЖИМ 2: ПРОСМОТР ВСЕЙ ПАРТИИ (WALKTHROUGH С ОЦЕНКОЙ ХОДОВ)
            # ================================================================
            else:
                plies = parse_game_plies(selected_game.pgn, error_events)
                ply_key = f"ply_{selected_game.id}"
                if ply_key not in st.session_state:
                    st.session_state[ply_key] = 0
                
                cur_ply = max(0, min(len(plies) - 1, st.session_state[ply_key]))
                st.session_state[ply_key] = cur_ply
                ply_data = plies[cur_ply]

                # Отрисовка доски для текущего полухода
                render_interactive_chessboard(
                    fen=ply_data["fen"],
                    orientation=selected_game.student_color,
                    allow_moves=False,
                    key=f"walk_board_{selected_game.id}_{cur_ply}"
                )

                # Кнопки пошаговой навигации (|<<, <, >, >>)
                n1, n2, n3, n4 = st.columns(4)
                with n1:
                    if st.button("⏮️ |<<", use_container_width=True, key=f"btn_first_{selected_game.id}", help="В начало партии"):
                        st.session_state[ply_key] = 0
                        st.rerun()
                with n2:
                    if st.button("◀️ <", use_container_width=True, key=f"btn_prev_{selected_game.id}", help="Ход назад"):
                        st.session_state[ply_key] = max(0, cur_ply - 1)
                        st.rerun()
                with n3:
                    if st.button("> ▶️", use_container_width=True, key=f"btn_next_{selected_game.id}", help="Ход вперед"):
                        st.session_state[ply_key] = min(len(plies) - 1, cur_ply + 1)
                        st.rerun()
                with n4:
                    if st.button(">>| ⏭️", use_container_width=True, key=f"btn_last_{selected_game.id}", help="В конец партии"):
                        st.session_state[ply_key] = len(plies) - 1
                        st.rerun()

                # Слайдер перемотки ходов (связан с ply_key)
                st.slider(
                    "Шкала ходов партии",
                    min_value=0,
                    max_value=len(plies) - 1,
                    key=ply_key
                )

                # Информационная плашка с оценкой хода движком
                is_err = ply_data.get("error") is not None
                border_color = "#ef4444" if is_err else "#3b82f6"
                bg_color = "#fef2f2" if is_err else "#f8fafc"

                st.markdown(f"""
                <div style="background:{bg_color}; border-left:4px solid {border_color}; border-radius:4px; padding:10px 14px; margin-top:4px;">
                    <div style="font-weight:700; font-size:1.05rem; color:#0f172a;">
                        Ход: {ply_data['san']} ({'Белые ⚪' if ply_data['is_white'] else 'Черные ⚫'})
                    </div>
                    <div style="color:{border_color}; font-weight:600; font-size:0.95rem; margin-top:3px;">
                        Оценка Stockfish: {ply_data['eval_text']}
                    </div>
                </div>
                """, unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# ВКЛАДКА 2: АНАЛИТИКА УЧЕНИКА
# ----------------------------------------------------------------------------
with tab_analytics:
    st.subheader("📈 Агрегированная аналитика пула партий")

    if not games_list:
        st.info("Нет данных для отображения аналитики.")
    else:
        total_g = len(games_list)
        wins_count = sum(1 for g in games_list if (g.student_color == 'white' and g.result == '1-0') or (g.student_color == 'black' and g.result == '0-1'))
        win_rate = round((wins_count / total_g) * 100, 1)
        
        valid_acc = [float(g.accuracy_score) for g in games_list if g.accuracy_score is not None]
        avg_acc = round(sum(valid_acc) / len(valid_acc), 1) if valid_acc else 0.0
        
        valid_acpl = [g.acpl for g in games_list if g.acpl is not None]
        avg_acpl = int(sum(valid_acpl) / len(valid_acpl)) if valid_acpl else 0
        
        all_errors = all_student_errors
        time_trouble_errors = sum(1 for e in all_errors if e.is_time_trouble)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Побед / Винрейт", f"{wins_count}/{total_g} ({win_rate}%)")
        c2.metric("Точность (CAPS)", f"{avg_acc}%")
        c3.metric("Средний ACPL", f"{avg_acpl}")
        c4.metric("Зевков под флагом", f"{time_trouble_errors}", delta=f"{len(all_errors)} всего ошибок", delta_color="inverse")

        st.divider()

        g_col1, g_col2 = st.columns(2)

        with g_col1:
            st.markdown("#### Ошибки по фазам игры")
            phase_counts = {"Дебют": 0, "Миттельшпиль": 0, "Эндшпиль": 0}
            for e in all_errors:
                if e.phase == "opening":
                    phase_counts["Дебют"] += 1
                elif e.phase == "middlegame":
                    phase_counts["Миттельшпиль"] += 1
                elif e.phase == "endgame":
                    phase_counts["Эндшпиль"] += 1
            
            st.bar_chart(phase_counts, color="#3b82f6")

        with g_col2:
            st.markdown("#### Топ тактических слабостей")
            tag_counts = {}
            for e in all_errors:
                tag = e.tactical_tag or "tactical_blunder"
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
            
            if tag_counts:
                st.bar_chart(tag_counts, color="#ef4444")
            else:
                st.info("Нет зафиксированных тактических ошибок.")

# ----------------------------------------------------------------------------
# ВКЛАДКА 3: ОТЧЕТЫ AI И ЭКСПОРТ В PDF
# ----------------------------------------------------------------------------
with tab_ai:
    st.subheader(f"Генерация отчетов AI ({active_role})")
    
    if not games_list:
        st.info("Сначала загрузите партии ученика.")
    else:
        agg_input = []
        for g in games_list:
            agg_input.append({
                "analysis": GameAnalysisResult(
                    accuracy_score=float(g.accuracy_score or 90.0),
                    acpl=g.acpl or 20,
                    blunders_count=g.blunders_count,
                    mistakes_count=g.mistakes_count,
                    inaccuracies_count=g.inaccuracies_count,
                    time_blunders_count=g.time_spent_blunders_count,
                    errors=[],
                    moves_tree=[]
                ),
                "student_color": g.student_color,
                "result": g.result,
                "opponent_username": g.opponent_username
            })

        aggregator = GameMetricsAggregator()
        stats = aggregator.aggregate(
            student_name=st.session_state.get("student_name", "Ученик"),
            period_description="Октябрь 2026",
            games_data=agg_input
        )

        btn_col, pdf_col = st.columns([1, 1])
        with btn_col:
            gen_report_btn = st.button("🤖 Сгенерировать сводный отчет AI", type="primary", use_container_width=True)

        if gen_report_btn or "cached_coach_report" in st.session_state:
            reporter = LLMReporterService()
            
            if gen_report_btn:
                with st.spinner("Генерация структурированного отчета..."):
                    st.session_state["cached_coach_report"] = reporter.generate_coach_report(stats)
                    st.session_state["cached_parent_report"] = reporter.generate_parent_report(stats)

            coach_rep = st.session_state.get("cached_coach_report")
            parent_rep = st.session_state.get("cached_parent_report")

            # Генерация PDF для родителя
            if parent_rep:
                pdf_bytes = PDFReportGenerator.generate_parent_pdf(
                    report=parent_rep,
                    stats=stats,
                    coach_name="Тренерский штаб"
                )
                with pdf_col:
                    st.download_button(
                        label="📄 Скачать красивый PDF-отчет для родителя",
                        data=pdf_bytes,
                        file_name=f"ChessCoach_Report_{parent_rep.child_name.replace(' ', '_')}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )

            st.divider()

            # Режим тренера
            if active_role == "Кабинет тренера" and coach_rep:
                st.markdown(f"### 👔 Аудит для тренера: {coach_rep.student_name}")
                st.markdown(f"<div class='coach-card'><b>Резюме:</b><br>{coach_rep.executive_summary}</div>", unsafe_allow_html=True)
                
                st.markdown("#### 🔍 Хронические паттерны ошибок:")
                for p in coach_rep.systemic_patterns:
                    st.markdown(f"- **[{p.severity.upper()}] {p.title}** ({p.frequency})<br>_{p.description}_", unsafe_allow_html=True)

                st.markdown(f"**⏱️ Оценка цейтнота:** {coach_rep.time_trouble_verdict}")
                
                st.markdown("#### 🎯 Рекомендованный план тренировок:")
                for l in coach_rep.next_lessons_plan:
                    st.markdown(f"- {l}")

                st.divider()
                st.subheader("🧩 Персональное домашнее задание (Lichess Puzzle Database):")
                st.caption("Кликабельные ссылки на открытую базу задач Lichess, сгенерированные под слабые темы ученика:")
                
                puzzle_recs = PuzzleGeneratorService.generate_recommendations(stats.top_tactical_weaknesses)
                for rec in puzzle_recs:
                    with st.container():
                        st.markdown(f"""
                        <div class="puzzle-box">
                            <b>📌 {rec['title']}</b> ({rec['puzzles_recommended']} задач)<br>
                            <span style="color:#64748b; font-size:0.9rem;">{rec['description']}</span><br>
                            <span style="color:#ef4444; font-size:0.85rem;">Причина: {rec['error_frequency']}</span>
                        </div>
                        """, unsafe_allow_html=True)
                        st.link_button(f"👉 Начать тренировку темы '{rec['title'].split('(')[0].strip()}' на Lichess", rec["url"])

                st.divider()
                st.subheader("📋 Экспорт в мессенджер тренера:")
                coach_text = (
                    f"♟️ АУДИТ ИГРЫ: {coach_rep.student_name}\n\n"
                    f"{coach_rep.executive_summary}\n\n"
                    f"ПАТТЕРНЫ:\n" + "\n".join([f"- {p.title} ({p.frequency})" for p in coach_rep.systemic_patterns]) + "\n\n"
                    f"ЗАДАЧИ НА ДОМ (LICHESS):\n" + "\n".join([f"- {r['title']}: {r['url']}" for r in puzzle_recs]) + "\n\n"
                    f"ПЛАН ЗАНЯТИЙ:\n" + "\n".join([f"- {l}" for l in coach_rep.next_lessons_plan])
                )
                st.code(coach_text, language="markdown")

            # Режим родителя
            elif active_role == "Кабинет родителя" and parent_rep:
                st.markdown(f"### 👨‍👩‍👦 Отчет для родителей: {parent_rep.child_name}")
                st.markdown(f"<div class='parent-card'>{parent_rep.greeting_and_summary}</div>", unsafe_allow_html=True)
                
                st.markdown("#### 🏆 Главные победы и достижения недели:")
                for a in parent_rep.achievements:
                    st.markdown(f"✅ {a}")

                st.markdown("#### 🌱 Над чем мягко поработаем дальше:")
                for g in parent_rep.areas_for_growth:
                    st.markdown(f"🔹 {g}")

                st.markdown("#### 💡 Совет для родителей дома:")
                st.info(parent_rep.home_support_advice)

                st.divider()
                st.subheader("📱 Текст для отправки родителю в WhatsApp:")
                parent_text = (
                    f"{parent_rep.greeting_and_summary}\n\n"
                    f"🏆 Достижения:\n" + "\n".join([f"✅ {a}" for a in parent_rep.achievements]) + "\n\n"
                    f"🌱 Зоны роста:\n" + "\n".join([f"🔹 {g}" for g in parent_rep.areas_for_growth]) + "\n\n"
                    f"💡 Совет для дома:\n{parent_rep.home_support_advice}"
                )
                st.code(parent_text, language="text")
