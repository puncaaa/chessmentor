import os
import sys
import base64
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

import streamlit as st
import chess
import chess.svg
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
from app.services.llm_reporter import GameMetricsAggregator, LLMReporterService
from app.services.puzzle_service import PuzzleGeneratorService
from app.services.pdf_generator import PDFReportGenerator
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
            if active_error:
                board_html = render_chessboard_svg(
                    fen=active_error.fen_before,
                    played_uci=active_error.played_move_uci,
                    best_uci=active_error.best_move_uci,
                    student_color=selected_game.student_color,
                    size=440
                )
                st.markdown(board_html, unsafe_allow_html=True)
                
                st.markdown(f"""
                <div style="display:flex; justify-content:space-around; background:#f1f5f9; padding:8px; border-radius:8px; font-size:0.95rem;">
                    <div>🔴 <b>Сыграно учеником:</b> <code>{active_error.played_move_san}</code> ({active_error.played_move_uci})</div>
                    <div>🟢 <b>Лучший ход Stockfish:</b> <code>{active_error.best_move_san}</code> ({active_error.best_move_uci})</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                final_fen = chess.STARTING_FEN
                board_html = render_chessboard_svg(fen=final_fen, student_color=selected_game.student_color, size=440)
                st.markdown(board_html, unsafe_allow_html=True)
                st.caption("Позиция на доске")

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
