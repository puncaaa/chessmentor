import os
import sys
import io
import time
import zipfile
import urllib.parse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import streamlit as st
import chess
import chess.svg
import chess.pgn
import plotly.graph_objects as go
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

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
from app.models.chess import (
    School,
    Teacher,
    Group,
    StudentProfile,
    StudentChessAccount,
    Game,
    ChessErrorEvent,
    StudentReport,
)
from app.schemas.school import (
    StudentCreate,
    StudentUpdate,
    TeacherCreate,
    TeacherUpdate,
    GroupCreate,
    GroupUpdate,
    StudentCockpitCard,
)
from app.services.school_service import SchoolService
from app.services.chess_sync import ChessSyncService
from app.services.chess_analyzer import ChessEngineAnalyzer
from app.services.llm_reporter import GameMetricsAggregator, LLMReporterService
from app.services.puzzle_service import PuzzleGeneratorService
from app.services.pdf_generator import PDFReportGenerator
from app.services.opening_analyzer import OpeningAnalyzerService
from app.services.worksheet_generator import WorksheetPDFGenerator
from app.ui.components.chessboard_component import render_interactive_chessboard

# ============================================================================
# КОНФИГУРАЦИЯ СТРАНИЦЫ
# ============================================================================
st.set_page_config(
    page_title="ChessCoach AI — Экосистема развития учеников",
    page_icon="♟️",
    layout="wide",
    initial_sidebar_state="expanded"
)

def render_html(html_str: str):
    """Безопасный нативный рендеринг HTML в Streamlit."""
    st.html(html_str)

# Определение темы оформления (Dark / Light)
theme_choice = st.session_state.get("app_theme_choice", "🌙 Темная")
is_dark = "Светлая" not in theme_choice

def get_theme_css(is_dark: bool) -> str:
    """Генерация дизайн-системы Linear / Tailwind Slate с безупречной контрастностью."""
    if is_dark:
        vars_css = """
        --bg-page: #0B0F17;
        --bg-sidebar: #0D131F;
        --bg-card: #161F30;
        --bg-card-subtle: rgba(255, 255, 255, 0.04);
        --border-card: rgba(255, 255, 255, 0.08);
        --border-card-hover: rgba(255, 255, 255, 0.18);
        --border-subtle: rgba(255, 255, 255, 0.06);
        --border-divider: rgba(255, 255, 255, 0.08);
        --text-main: #F8FAFC;
        --text-muted: #94A3B8;
        --text-subtle: #64748B;
        --code-bg: #0F172A;
        --shadow-card: 0 4px 20px rgba(0, 0, 0, 0.35);
        --shadow-card-hover: 0 8px 30px rgba(0, 0, 0, 0.5);
        --alert-danger-bg: rgba(239, 68, 68, 0.08);
        --alert-danger-border: rgba(239, 68, 68, 0.3);
        --alert-danger-text: #F8FAFC;
        --alert-danger-title: #F87171;
        --alert-info-bg: rgba(59, 130, 246, 0.08);
        --alert-info-border: rgba(59, 130, 246, 0.3);
        --alert-info-text: #F8FAFC;
        --alert-info-title: #60A5FA;
        --alert-success-bg: rgba(16, 185, 129, 0.08);
        --alert-success-border: rgba(16, 185, 129, 0.3);
        --alert-success-text: #F8FAFC;
        --alert-success-title: #34D399;
        --badge-blunder-bg: rgba(239, 68, 68, 0.15);
        --badge-blunder-text: #FCA5A5;
        --badge-mistake-bg: rgba(245, 158, 11, 0.15);
        --badge-mistake-text: #FCD34D;
        --badge-inacc-bg: rgba(59, 130, 246, 0.15);
        --badge-inacc-text: #93C5FD;
        --badge-win-bg: rgba(16, 185, 129, 0.15);
        --badge-win-text: #6EE7B7;
        """
    else:
        vars_css = """
        --bg-page: #F8FAFC;
        --bg-sidebar: #FFFFFF;
        --bg-card: #FFFFFF;
        --bg-card-subtle: #F1F5F9;
        --border-card: #E2E8F0;
        --border-card-hover: #CBD5E1;
        --border-subtle: #E2E8F0;
        --border-divider: #E2E8F0;
        --text-main: #0F172A;
        --text-muted: #475569;
        --text-subtle: #64748B;
        --code-bg: #F1F5F9;
        --shadow-card: 0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.04);
        --shadow-card-hover: 0 4px 12px rgba(0, 0, 0, 0.1);
        --alert-danger-bg: #FEF2F2;
        --alert-danger-border: #FECACA;
        --alert-danger-text: #991B1B;
        --alert-danger-title: #DC2626;
        --alert-info-bg: #EFF6FF;
        --alert-info-border: #BFDBFE;
        --alert-info-text: #1E40AF;
        --alert-info-title: #2563EB;
        --alert-success-bg: #ECFDF5;
        --alert-success-border: #A7F3D0;
        --alert-success-text: #065F46;
        --alert-success-title: #059669;
        --badge-blunder-bg: #FEE2E2;
        --badge-blunder-text: #991B1B;
        --badge-mistake-bg: #FEF3C7;
        --badge-mistake-text: #92400E;
        --badge-inacc-bg: #DBEAFE;
        --badge-inacc-text: #1E40AF;
        --badge-win-bg: #D1FAE5;
        --badge-win-text: #065F46;
        """

    return f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    
    :root {{
        {vars_css}
    }}

    .stApp {{
        background-color: var(--bg-page) !important;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        color: var(--text-main) !important;
    }}

    h1, h2, h3, h4, h5, h6 {{
        color: var(--text-main) !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 700 !important;
    }}

    p, span, label, [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] span {{
        color: var(--text-main);
    }}

    .stCaption, [data-testid="stCaptionContainer"] {{
        color: var(--text-muted) !important;
    }}

    section[data-testid="stSidebar"] {{
        background-color: var(--bg-sidebar) !important;
        border-right: 1px solid var(--border-divider) !important;
    }}

    section[data-testid="stSidebar"] * {{
        color: var(--text-main);
    }}

    /* Карточки B2B SaaS */
    .saas-card {{
        background: var(--bg-card) !important;
        border: 1px solid var(--border-card) !important;
        border-radius: 12px !important;
        padding: 16px !important;
        box-shadow: var(--shadow-card) !important;
        transition: all 0.2s ease !important;
        color: var(--text-main) !important;
    }}
    .saas-card:hover {{
        border-color: var(--border-card-hover) !important;
        box-shadow: var(--shadow-card-hover) !important;
    }}

    .kpi-card {{
        background: var(--bg-card) !important;
        border: 1px solid var(--border-card) !important;
        border-radius: 10px !important;
        padding: 14px 18px !important;
        box-shadow: var(--shadow-card) !important;
    }}
    .kpi-label {{
        color: var(--text-muted) !important;
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }}
    .kpi-value {{
        color: var(--text-main) !important;
        font-size: 1.55rem;
        font-weight: 800;
        margin-top: 4px;
        letter-spacing: -0.02em;
    }}
    .kpi-subtext {{
        color: var(--text-subtle) !important;
        font-size: 0.78rem;
        margin-top: 3px;
    }}

    /* Бейджи */
    .badge-chip {{
        display: inline-flex;
        align-items: center;
        padding: 3px 9px;
        border-radius: 6px;
        font-size: 0.76rem;
        font-weight: 600;
    }}
    .badge-blunder {{ background: var(--badge-blunder-bg); color: var(--badge-blunder-text); }}
    .badge-mistake {{ background: var(--badge-mistake-bg); color: var(--badge-mistake-text); }}
    .badge-win {{ background: var(--badge-win-bg); color: var(--badge-win-text); }}
    .badge-inaccuracy {{ background: var(--badge-inacc-bg); color: var(--badge-inacc-text); }}
    .badge-plan {{ background: rgba(59, 130, 246, 0.12); color: #2563EB; border: 1px solid rgba(59, 130, 246, 0.25); }}

    /* Кнопки WhatsApp */
    .stLinkButton a {{
        background: #10B981 !important;
        color: #FFFFFF !important;
        border: none !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
        border-radius: 8px !important;
        box-shadow: 0 2px 6px rgba(16, 185, 129, 0.25) !important;
        transition: all 0.15s ease !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }}
    .stLinkButton a:hover {{
        background: #059669 !important;
        color: #FFFFFF !important;
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.35) !important;
    }}

    /* Primary buttons */
    button[kind="primary"] {{
        background: #2563EB !important;
        color: #FFFFFF !important;
        border: none !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        box-shadow: 0 2px 6px rgba(37, 99, 235, 0.25) !important;
    }}
    button[kind="primary"]:hover {{
        background: #1D4ED8 !important;
    }}

    /* Secondary buttons */
    button[kind="secondary"] {{
        background: var(--bg-card-subtle) !important;
        color: var(--text-main) !important;
        border: 1px solid var(--border-card) !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        transition: all 0.15s ease !important;
    }}
    button[kind="secondary"]:hover {{
        background: var(--border-card) !important;
        color: var(--text-main) !important;
        border-color: var(--border-card-hover) !important;
    }}

    /* Inputs, Selects and Popovers */
    div[data-baseweb="input"] {{
        background-color: var(--bg-card) !important;
        border-color: var(--border-card) !important;
    }}
    input, textarea {{
        color: var(--text-main) !important;
        background-color: transparent !important;
    }}
    div[data-baseweb="select"] > div {{
        background-color: var(--bg-card) !important;
        border-color: var(--border-card) !important;
        color: var(--text-main) !important;
    }}

    /* Карточки учеников в сетке 2x2 */
    .student-card {{
        background: var(--bg-card) !important;
        border: 1px solid var(--border-card) !important;
        border-radius: 14px !important;
        padding: 16px 18px !important;
        box-shadow: var(--shadow-card) !important;
        transition: all 0.2s ease !important;
        margin-bottom: 12px !important;
    }}
    .student-card:hover {{
        border-color: var(--border-card-hover) !important;
        box-shadow: var(--shadow-card-hover) !important;
    }}

    /* Expander styling */
    div[data-testid="stExpander"] {{
        background: var(--bg-card) !important;
        border: 1px solid var(--border-card) !important;
        border-radius: 10px !important;
    }}
    div[data-testid="stExpander"] summary {{
        color: var(--text-main) !important;
        font-weight: 600 !important;
    }}

    /* Alert cards */
    .alert-card-danger {{
        background: var(--alert-danger-bg);
        border: 1px solid var(--alert-danger-border);
        border-radius: 8px;
        padding: 12px 14px;
        margin-bottom: 8px;
    }}
    .alert-card-success {{
        background: var(--alert-success-bg);
        border: 1px solid var(--alert-success-border);
        border-radius: 8px;
        padding: 12px 14px;
        margin-bottom: 8px;
    }}
    .alert-card-info {{
        background: var(--alert-info-bg);
        border: 1px solid var(--alert-info-border);
        border-radius: 8px;
        padding: 12px 14px;
        margin-bottom: 8px;
    }}

    /* Шахматная доска */
    .chessboard-wrapper,
    div[data-testid="stCustomComponentV1"],
    iframe[title*="interactive_chessboard"] {{
        max-width: 420px !important;
        min-width: 420px !important;
        width: 420px !important;
        margin: 0 auto !important;
        display: block !important;
    }}

    /* Навигационные табы в стиле Linear */
    div[data-testid="stRadio"] > div[role="radiogroup"] {{
        background: var(--bg-card);
        padding: 4px;
        border-radius: 10px;
        border: 1px solid var(--border-card);
        gap: 4px;
    }}
    </style>
    """


def get_student_gamification(card: StudentCockpitCard, session: Session) -> dict:
    """Расчет мягкой шахматной геймификации: звания, ранги, форма, стрик активности."""
    rating = card.rating or 1200

    # 1. Шахматные звания / Уровни ученика
    if rating < 1100:
        rank = {
            "title": "Пешечный страж",
            "icon": "🛡️",
            "tier": "Новичок",
            "color": "#10B981",
            "bg": "rgba(16, 185, 129, 0.12)",
            "min_xp": 900,
            "next_xp": 1100,
        }
    elif rating < 1300:
        rank = {
            "title": "Тактический всадник",
            "icon": "♞",
            "tier": "Любитель",
            "color": "#3B82F6",
            "bg": "rgba(59, 130, 246, 0.12)",
            "min_xp": 1100,
            "next_xp": 1300,
        }
    elif rating < 1600:
        rank = {
            "title": "Мастер комбинаций",
            "icon": "🎯",
            "tier": "Разрядник",
            "color": "#8B5CF6",
            "bg": "rgba(139, 92, 246, 0.12)",
            "min_xp": 1300,
            "next_xp": 1600,
        }
    else:
        rank = {
            "title": "Гроссмейстер клуба",
            "icon": "👑",
            "tier": "Сборник",
            "color": "#F59E0B",
            "bg": "rgba(245, 158, 11, 0.12)",
            "min_xp": 1600,
            "next_xp": 2000,
        }

    # 2. Прогресс-бар XP до следующего звания (до преодоления круглой отметки)
    next_xp = ((rating // 100) + 1) * 100
    prev_xp = (rating // 100) * 100
    current_offset = max(0, rating - prev_xp)
    progress_pct = max(10, min(100, int((current_offset / 100) * 100)))

    # 3. Индикатор формы за 5 последних партий
    last_games = session.execute(
        select(Game.result, Game.student_color)
        .where(Game.student_profile_id == card.id)
        .order_by(Game.played_at.desc())
        .limit(5)
    ).all()

    form_emojis = []
    for g_res, s_col in reversed(last_games):
        if (g_res == "1-0" and s_col == "white") or (g_res == "0-1" and s_col == "black"):
            form_emojis.append("🟢")
        elif g_res in ("1/2-1/2", "0.5-0.5", "1/2"):
            form_emojis.append("⚪")
        else:
            form_emojis.append("🔴")

    while len(form_emojis) < 5:
        form_emojis.insert(0, "⚪")

    form_display = " ".join(form_emojis)

    # 4. Стрик активности (Practice Streak)
    if card.games_this_week >= 5:
        streak_text = f"🔥 {card.games_this_week} партий на неделе"
    elif card.games_this_week >= 2:
        streak_text = f"🔥 {card.games_this_week} дня в игре"
    elif card.games_this_week == 1:
        streak_text = "🔥 1 партия на неделе"
    else:
        streak_text = "💤 Ждет новой игры"

    # 5. Главная суперсила
    if card.avg_caps_accuracy >= 80:
        superpower = "Высокая точность"
    elif rating >= 1500:
        superpower = "Сильный эндшпиль"
    elif card.avg_acpl > 0 and card.avg_acpl <= 35:
        superpower = "Точный расчет"
    else:
        superpower = "Стабильный дебют"

    # 6. Зона фокуса
    weakness_map = {
        "time_trouble_panic": "Цейтнот",
        "hanging_piece": "Висячие фигуры",
        "missed_fork": "Вилки конем",
        "missed_pin": "Связки",
        "endgame_king_activity": "Король в эндшпиле",
    }
    focus_area = weakness_map.get(card.top_weakness_tag, "Висячие фигуры")

    return {
        "rank": rank,
        "next_xp": next_xp,
        "progress_pct": progress_pct,
        "form_display": form_display,
        "streak_text": streak_text,
        "superpower": superpower,
        "focus_area": focus_area,
    }

st.markdown(get_theme_css(is_dark), unsafe_allow_html=True)
init_db()

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ ДАННЫХ ШКОЛЫ И ТРЕНЕРА
# ============================================================================
with get_db_session() as session:
    school = SchoolService.get_or_create_default_school(session)
    teachers = SchoolService.list_teachers(session, school.id)
    if not teachers:
        from scripts.seed_school import seed_database
        seed_database()
        school = SchoolService.get_or_create_default_school(session)
        teachers = SchoolService.list_teachers(session, school.id)

# Селектор тренера: Александр Морозевич всегда первый по умолчанию
teachers_sorted = sorted(teachers, key=lambda t: 0 if "Морозевич" in t.last_name else 1)
coach_options = {f"{t.full_name} ({t.fide_title or 'Тренер'})": t.id for t in teachers_sorted}
if not coach_options:
    coach_options = {"(Тренеры не назначены)": None}

if "active_coach_select" in st.session_state and st.session_state["active_coach_select"] not in coach_options:
    del st.session_state["active_coach_select"]
default_coach_name = list(coach_options.keys())[0]

# ============================================================================
# БОКОВАЯ ПАНЕЛЬ (SIDEBAR): О ШКОЛЕ И НАСТРОЙКИ
# ============================================================================
with st.sidebar:
    render_html(f"""
    <div style="display:flex; align-items:center; gap:12px; margin-bottom:16px; padding-bottom:14px; border-bottom:1px solid var(--border-divider);">
        <div style="width:40px; height:40px; border-radius:10px; background:linear-gradient(135deg, #3B82F6 0%, #1D4ED8 100%); display:flex; align-items:center; justify-content:center; box-shadow:0 4px 12px rgba(59, 130, 246, 0.35); flex-shrink:0;">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="#FFFFFF">
                <path d="M19 22H5v-2h14v2M18.8 9.2c-.3-.8-.9-1.5-1.7-1.9-.3-.2-.7-.3-1.1-.3h-.1c-.4-1.2-1.3-2.1-2.4-2.6-.7-.3-1.5-.4-2.2-.2-.2-.6-.6-1.1-1.1-1.5-.7-.5-1.6-.7-2.5-.5-.8.2-1.5.7-1.9 1.4-.4.7-.4 1.5-.2 2.3l.5 1.8c-.8.4-1.4 1-1.8 1.8-.4.8-.4 1.7-.1 2.5l1.6 4.3H19l-.2-7.1z"/>
            </svg>
        </div>
        <div>
            <div style="font-size:1.05rem; font-weight:700; color:var(--text-main); line-height:1.2;">{school.name}</div>
            <div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">Экосистема развития учеников</div>
        </div>
    </div>
    """)

    selected_coach_label = st.selectbox(
        "👔 Тренер:",
        options=list(coach_options.keys()),
        index=0,
        key="active_coach_select"
    )
    current_teacher_id = coach_options.get(selected_coach_label)

    with st.expander("⚙️ Управление тренерами", expanded=False):
        coach_subaction = st.radio("Действие:", ["✏️ Изменить", "➕ Добавить", "🗑️ Удалить"], horizontal=True, key="coach_mgm_radio")
        with get_db_session() as session:
            active_teacher_obj = session.get(Teacher, current_teacher_id) if current_teacher_id else None

        if coach_subaction == "✏️ Изменить":
            if not active_teacher_obj:
                st.info("Нет тренеров для редактирования. Выберите вкладку '➕ Добавить', чтобы создать первого тренера.")
            else:
                with st.form("form_edit_teacher"):
                    e_fname = st.text_input("Имя", value=active_teacher_obj.first_name)
                    e_lname = st.text_input("Фамилия", value=active_teacher_obj.last_name)
                    titles = ["GM", "IM", "FM", "WGM", "WFM", "КМС", "Тренер высшей категории", "Инструктор"]
                    t_idx = titles.index(active_teacher_obj.fide_title) if active_teacher_obj.fide_title in titles else 0
                    e_title = st.selectbox("Титул / Звание", titles, index=t_idx)
                    e_email = st.text_input("Email", value=active_teacher_obj.email or "")
                    e_phone = st.text_input("Телефон", value=active_teacher_obj.phone or "")
                    e_bio = st.text_area("Биография / Описание", value=active_teacher_obj.bio or "")
                    
                    if st.form_submit_button("💾 Сохранить изменения", use_container_width=True):
                        with get_db_session() as session:
                            SchoolService.update_teacher(session, active_teacher_obj.id, TeacherUpdate(
                                first_name=e_fname.strip(),
                                last_name=e_lname.strip(),
                                fide_title=e_title,
                                email=e_email.strip() if e_email else None,
                                phone=e_phone.strip() if e_phone else None,
                                bio=e_bio.strip() if e_bio else None
                            ))
                        st.success("Данные тренера обновлены!")
                        time.sleep(1)
                        st.rerun()

        elif coach_subaction == "➕ Добавить":
            with st.form("form_add_teacher"):
                a_fname = st.text_input("Имя *", placeholder="Сергей")
                a_lname = st.text_input("Фамилия *", placeholder="Карякин")
                titles = ["GM", "IM", "FM", "WGM", "WFM", "КМС", "Тренер высшей категории", "Инструктор"]
                a_title = st.selectbox("Титул / Звание", titles, index=0)
                a_email = st.text_input("Email", placeholder="sergey@gambit.ru")
                a_phone = st.text_input("Телефон", placeholder="+7 (999) 000-00-00")
                a_bio = st.text_area("Биография", placeholder="Опыт преподавания...")
                
                if st.form_submit_button("➕ Добавить тренера", type="primary", use_container_width=True):
                    if not a_fname.strip() or not a_lname.strip():
                        st.error("Укажите имя и фамилию тренера!")
                    else:
                        with get_db_session() as session:
                            SchoolService.create_teacher(session, TeacherCreate(
                                school_id=school.id,
                                first_name=a_fname.strip(),
                                last_name=a_lname.strip(),
                                fide_title=a_title,
                                email=a_email.strip() if a_email else None,
                                phone=a_phone.strip() if a_phone else None,
                                bio=a_bio.strip() if a_bio else None
                            ))
                        st.success(f"Тренер {a_fname} {a_lname} добавлен!")
                        time.sleep(1)
                        st.rerun()

        elif coach_subaction == "🗑️ Удалить":
            if not active_teacher_obj:
                st.info("В школе нет добавленных тренеров для удаления.")
            else:
                st.warning(f"Удалить тренера **{active_teacher_obj.full_name}**?")
                confirm_del_t = st.checkbox("Подтверждаю удаление тренера", key="chk_del_t")
                if st.button("🗑️ Удалить тренера", disabled=not confirm_del_t, type="primary", use_container_width=True, key="btn_del_t"):
                    with get_db_session() as session:
                        SchoolService.delete_teacher(session, active_teacher_obj.id)
                    st.success(f"Тренер {active_teacher_obj.full_name} удален.")
                    time.sleep(1)
                    st.rerun()

    st.divider()

    st.radio(
        "Тема оформления:",
        options=["🌙 Темная", "☀️ Светлая"],
        index=0 if is_dark else 1,
        horizontal=True,
        key="app_theme_choice"
    )

    st.divider()

    with st.expander("⚙️ Настройки школы", expanded=False):
        render_html(f"""
        <div style="font-size:0.8rem; color:var(--text-muted); line-height:1.7;">
            <div>Тариф: <b style="color:var(--text-main);">{school.subscription_tier.upper()}</b></div>
            <div>Лимит мест: <b style="color:var(--text-main);">{school.max_students} учеников</b></div>
            <div>Интеграция: <span style="color:#3B82F6; font-weight:600;">Lichess & Chess.com</span></div>
        </div>
        """)
        st.divider()
        st.caption("Если потребуется заново наполнить базу демо-учениками:")
        confirm_seed = st.checkbox("Подтверждаю сброс демо-данных", key="chk_reset_demo")
        if st.button("🔄 Восстановить демо-данные", disabled=not confirm_seed, use_container_width=True, key="btn_reset_demo"):
            from scripts.seed_school import seed_database
            seed_database()
            st.success("Демо-данные успешно восстановлены!")
            time.sleep(1)
            st.rerun()

# ============================================================================
# ВЕРХНЯЯ ШАПКА ДАШБОРДА
# ============================================================================
coach_display_name = selected_coach_label if current_teacher_id else "Не назначен"
render_html(f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--border-divider);">
    <div style="display:flex; align-items:center; gap:12px;">
        <span style="font-size:1.8rem;">♟️</span>
        <div>
            <div style="font-size:1.4rem; font-weight:800; color:var(--text-main); letter-spacing:-0.02em;">
                {school.name}
            </div>
            <div style="font-size:0.85rem; color:var(--text-muted); margin-top:2px;">
                Кабинет тренера: <span style="color:#3B82F6; font-weight:600;">{coach_display_name}</span>
            </div>
        </div>
    </div>
    <div style="display:flex; align-items:center; gap:8px;">
        <span style="display:inline-flex; align-items:center; gap:6px; font-size:0.8rem; font-weight:600; color:#10B981; background:rgba(16, 185, 129, 0.1); border:1px solid rgba(16, 185, 129, 0.25); padding:5px 12px; border-radius:20px;">
            <span style="width:7px; height:7px; border-radius:50%; background:#10B981; display:inline-block; box-shadow:0 0 8px #10B981;"></span>
            Система активна
        </span>
    </div>
</div>
""")

# Главная трехуровневая навигация
nav_tabs = ["👥 Группы и ученики", "🔍 Разбор ученика", "📦 Пакетная раздача (PDF & ДЗ)"]
if "main_nav_tab" not in st.session_state:
    st.session_state["main_nav_tab"] = nav_tabs[0]

selected_tab = st.radio(
    label="Навигация:",
    options=nav_tabs,
    index=nav_tabs.index(st.session_state["main_nav_tab"]) if st.session_state["main_nav_tab"] in nav_tabs else 0,
    horizontal=True,
    label_visibility="collapsed",
    key="nav_radio_control"
)
st.session_state["main_nav_tab"] = selected_tab

# ============================================================================
# ЗАГРУЗКА ГРУПП ТЕКУЩЕГО ТРЕНЕРА И УПРАВЛЕНИЕ ГРУППАМИ
# ============================================================================
if not current_teacher_id:
    st.info("👈 **Тренер не выбран.** Пожалуйста, выберите или добавьте тренера в левом боковом меню, чтобы просмотреть его учебные группы и учеников.")
    st.stop()

with get_db_session() as session:
    coach_groups = SchoolService.list_groups(session, school.id, teacher_id=current_teacher_id)
    unassigned_groups = session.execute(
        select(Group).where(and_(Group.school_id == school.id, Group.teacher_id == None, Group.is_active == True))
    ).scalars().all()
    all_teachers_in_school = SchoolService.list_teachers(session, school.id)

if not coach_groups:
    st.warning(f"У тренера **{coach_display_name}** пока нет закрепленных учебных групп.")

    if unassigned_groups:
        st.markdown("#### 📌 Свободные группы школы (без назначенного куратора):")
        for ug in unassigned_groups:
            col_ug1, col_ug2 = st.columns([8, 2])
            with col_ug1:
                st.markdown(f"**{ug.name}** ({ug.level}) • {ug.schedule or 'Без расписания'}")
            with col_ug2:
                if st.button("Прикрепить к себе", key=f"btn_adopt_empty_{ug.id}", use_container_width=True):
                    with get_db_session() as session:
                        SchoolService.update_group(session, ug.id, GroupUpdate(teacher_id=current_teacher_id))
                    st.success(f"Группа '{ug.name}' закреплена за вами!")
                    time.sleep(1)
                    st.rerun()

    with st.expander("➕ Создать учебную группу для этого тренера", expanded=True):
        with st.form("form_create_first_group"):
            g_name = st.text_input("Название группы *", placeholder="Например: Разрядники 1400–1600 (Тактика)")
            levels = [
                "Начинающие (0–1000)",
                "3-й юношеский разряд (1000–1200)",
                "2-й / 1-й юношеский (1200–1500)",
                "Взрослые разряды (1500–1800)",
                "КМС / Мастера (1800+)",
            ]
            g_level = st.selectbox("Уровень группы", levels, index=0)
            g_sched = st.text_input("Расписание", placeholder="Например: Вт, Чт 17:00 - 18:30")
            g_notes = st.text_area("Заметки тренера", placeholder="Фокус обучения, цели...")
            if st.form_submit_button("➕ Создать группу", type="primary", use_container_width=True):
                if not g_name.strip():
                    st.error("Укажите название группы!")
                else:
                    with get_db_session() as session:
                        SchoolService.create_group(session, GroupCreate(
                            school_id=school.id,
                            teacher_id=current_teacher_id,
                            name=g_name.strip(),
                            level=g_level,
                            schedule=g_sched.strip() if g_sched else None,
                            notes=g_notes.strip() if g_notes else None,
                        ))
                    st.success(f"Группа '{g_name}' успешно создана!")
                    time.sleep(1)
                    st.rerun()
    st.stop()

# Групповой селектор для текущего тренера
group_dict = {f"{g.name} ({g.level})": g.id for g in coach_groups}
if "active_group_select" in st.session_state and st.session_state["active_group_select"] not in group_dict:
    del st.session_state["active_group_select"]
selected_group_label = st.selectbox(
    f"Учебная группа тренера ({len(coach_groups)}):",
    options=list(group_dict.keys()),
    index=0,
    key="active_group_select"
)
selected_group_id = group_dict[selected_group_label]

with get_db_session() as session:
    group_stats = SchoolService.get_group_with_stats(session, selected_group_id)
    group_students = SchoolService.list_students(session, school_id=school.id, group_id=selected_group_id)
    current_grp_obj = session.get(Group, selected_group_id)

with st.expander(f"⚙️ Управление группами тренера ({selected_group_label})", expanded=False):
    tab_titles = ["✏️ Редактировать группу", "➕ Создать новую группу", "🗑️ Удалить группу"]
    if unassigned_groups:
        tab_titles.insert(2, "📌 Прикрепить свободную")

    tabs = st.tabs(tab_titles)

    with tabs[0]:  # ✏️ Редактировать
        if current_grp_obj:
            with st.form("form_edit_group"):
                eg_name = st.text_input("Название группы *", value=current_grp_obj.name)
                levels = [
                    "Начинающие (0–1000)",
                    "3-й юношеский разряд (1000–1200)",
                    "2-й / 1-й юношеский (1200–1500)",
                    "Взрослые разряды (1500–1800)",
                    "КМС / Мастера (1800+)",
                ]
                l_idx = levels.index(current_grp_obj.level) if current_grp_obj.level in levels else 0
                eg_level = st.selectbox("Уровень группы", levels, index=l_idx)
                eg_sched = st.text_input("Расписание", value=current_grp_obj.schedule or "")

                teacher_map = {f"{t.full_name} ({t.fide_title or 'Тренер'})": t.id for t in all_teachers_in_school}
                curr_t_label = next((k for k, v in teacher_map.items() if v == current_grp_obj.teacher_id), list(teacher_map.keys())[0] if teacher_map else "")
                t_labels = list(teacher_map.keys())
                curr_t_idx = t_labels.index(curr_t_label) if curr_t_label in t_labels else 0
                eg_teacher_label = st.selectbox("Ответственный тренер", t_labels, index=curr_t_idx)

                eg_notes = st.text_area("Заметки тренера", value=current_grp_obj.notes or "")

                if st.form_submit_button("💾 Сохранить изменения группы", type="primary", use_container_width=True):
                    if not eg_name.strip():
                        st.error("Название группы не может быть пустым!")
                    else:
                        with get_db_session() as session:
                            SchoolService.update_group(session, current_grp_obj.id, GroupUpdate(
                                name=eg_name.strip(),
                                level=eg_level,
                                teacher_id=teacher_map.get(eg_teacher_label),
                                schedule=eg_sched.strip() if eg_sched else None,
                                notes=eg_notes.strip() if eg_notes else None,
                            ))
                        st.success("Данные группы успешно обновлены!")
                        time.sleep(1)
                        st.rerun()

    with tabs[1]:  # ➕ Создать новую
        with st.form("form_add_new_group"):
            ag_name = st.text_input("Название новой группы *", placeholder="Например: Продвинутая тактика и расчет")
            levels = [
                "Начинающие (0–1000)",
                "3-й юношеский разряд (1000–1200)",
                "2-й / 1-й юношеский (1200–1500)",
                "Взрослые разряды (1500–1800)",
                "КМС / Мастера (1800+)",
            ]
            ag_level = st.selectbox("Уровень подготовки", levels, index=0, key="new_grp_lvl_key")
            ag_sched = st.text_input("Расписание", placeholder="Например: Ср, Сб 17:30 - 19:00", key="new_grp_sch_key")
            ag_notes = st.text_area("Заметки", placeholder="Цели и программа...", key="new_grp_nt_key")

            if st.form_submit_button("➕ Создать группу для текущего тренера", type="primary", use_container_width=True):
                if not ag_name.strip():
                    st.error("Укажите название группы!")
                else:
                    with get_db_session() as session:
                        SchoolService.create_group(session, GroupCreate(
                            school_id=school.id,
                            teacher_id=current_teacher_id,
                            name=ag_name.strip(),
                            level=ag_level,
                            schedule=ag_sched.strip() if ag_sched else None,
                            notes=ag_notes.strip() if ag_notes else None,
                        ))
                    st.success(f"Группа '{ag_name}' успешно создана!")
                    time.sleep(1)
                    st.rerun()

    if unassigned_groups:
        with tabs[2]:  # 📌 Прикрепить свободную
            st.info("В школе есть группы без назначенного куратора:")
            for ug in unassigned_groups:
                col_u1, col_u2 = st.columns([8, 2])
                with col_u1:
                    st.markdown(f"**{ug.name}** ({ug.level}) • {ug.schedule or 'Без расписания'}")
                with col_u2:
                    if st.button("Прикрепить", key=f"btn_adopt_in_tab_{ug.id}", use_container_width=True):
                        with get_db_session() as session:
                            SchoolService.update_group(session, ug.id, GroupUpdate(teacher_id=current_teacher_id))
                        st.success(f"Группа '{ug.name}' закреплена за вами!")
                        time.sleep(1)
                        st.rerun()

    del_tab_index = 3 if unassigned_groups else 2
    with tabs[del_tab_index]:  # 🗑️ Удалить
        if current_grp_obj:
            st.warning(f"Удалить группу **{current_grp_obj.name}**?")
            st.caption("Ученики группы не удалятся, но будут откреплены от этой группы.")
            confirm_del_grp = st.checkbox(f"Подтверждаю удаление группы '{current_grp_obj.name}'", key=f"del_chk_{current_grp_obj.id}")
            if st.button("🗑️ Удалить группу", disabled=not confirm_del_grp, type="primary", use_container_width=True, key=f"btn_del_grp_{current_grp_obj.id}"):
                with get_db_session() as session:
                    SchoolService.delete_group(session, current_grp_obj.id)
                st.success(f"Группа '{current_grp_obj.name}' удалена.")
                time.sleep(1)
                st.rerun()

st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

# ============================================================================
# РАЗДЕЛ 1: 👥 ГРУППЫ И УЧЕНИКИ (CRM И ОБЗОР ШКОЛЫ)
# ============================================================================
if selected_tab == "👥 Группы и ученики":
    # 1. Метрики группы (KPI)
    col_kpi1, col_kpi2, col_kpi3, col_kpi4, col_kpi5 = st.columns(5)
    with col_kpi1:
        render_html(f"""
        <div class="kpi-card">
            <div class="kpi-label">Учеников в группе</div>
            <div class="kpi-value">{group_stats.students_count if group_stats else 0}</div>
            <div class="kpi-subtext">Активный состав</div>
        </div>
        """)
    with col_kpi2:
        render_html(f"""
        <div class="kpi-card">
            <div class="kpi-label">Средний рейтинг</div>
            <div class="kpi-value">⭐ {group_stats.avg_rating if group_stats else 1200}</div>
            <div class="kpi-subtext">FIDE / Online</div>
        </div>
        """)
    with col_kpi3:
        render_html(f"""
        <div class="kpi-card">
            <div class="kpi-label">Игр за 7 дней</div>
            <div class="kpi-value">♟️ {group_stats.games_played_this_week if group_stats else 0}</div>
            <div class="kpi-subtext">Партий сыграно</div>
        </div>
        """)
    with col_kpi4:
        render_html(f"""
        <div class="kpi-card">
            <div class="kpi-label">Точность (CAPS)</div>
            <div class="kpi-value" style="color:#3B82F6;">{group_stats.avg_caps_accuracy if group_stats else 0}%</div>
            <div class="kpi-subtext">По всем партиям</div>
        </div>
        """)
    with col_kpi5:
        render_html(f"""
        <div class="kpi-card">
            <div class="kpi-label">Выполнение ДЗ</div>
            <div class="kpi-value" style="color:#10B981;">{int(group_stats.homework_completion_rate) if group_stats else 0}%</div>
            <div class="kpi-subtext">Успеваемость</div>
        </div>
        """)

    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

    # 2. Кнопка групповой синхронизации
    col_sync_btn, col_sync_info = st.columns([4, 6])
    with col_sync_btn:
        if st.button("⚡ Синхронизировать партии всей группы", type="primary", use_container_width=True, key="btn_sync_group"):
            with st.spinner(f"Синхронизация партий Lichess / Chess.com для группы '{selected_group_label}'..."):
                with get_db_session() as session:
                    sync_res = SchoolService.sync_group_games(session, selected_group_id, max_games_per_student=3)
                st.success(f"✅ Успешно! Обработано учеников: {sync_res['students_processed']}, добавлено новых партий: {sync_res['total_new_games']}.")
                time.sleep(1)
                st.rerun()

    with col_sync_info:
        st.caption(f"Расписание занятий: **{group_stats.schedule or 'По договоренности'}** • Куратор: **{group_stats.teacher_name or coach_display_name}**")

    st.divider()

    # 3. Карточки учеников группы (Cards Grid 2x2 с геймификацией)
    st.markdown(f"### 📋 Карточки учеников группы ({len(group_students)})")

    if not group_students:
        st.info("В этой группе пока нет учеников. Добавьте первого ученика через форму ниже!")
    else:
        # Сетка 2x2
        for i in range(0, len(group_students), 2):
            row_students = group_students[i:i+2]
            cols = st.columns(2)
            for col_idx, student in enumerate(row_students):
                with cols[col_idx]:
                    with get_db_session() as session:
                        card = SchoolService.get_student_cockpit_card(session, student.id)
                        gamify = get_student_gamification(card, session)

                    rank = gamify["rank"]
                    online_handle = (
                        f"Lichess: @{card.lichess_username}"
                        if card.lichess_username
                        else (f"Chess.com: @{card.chesscom_username}" if card.chesscom_username else "Оффлайн")
                    )

                    # Рендер карточки с геймификацией
                    render_html(f"""
                    <div class="student-card">
                        <!-- Верхняя плашка: Аватар с оверлеем ранга, ФИО, Рейтинг и Титул -->
                        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">
                            <div style="display:flex; align-items:center; gap:12px;">
                                <div style="position:relative; width:48px; height:48px; flex-shrink:0;">
                                    <div style="width:48px; height:48px; border-radius:50%; background:linear-gradient(135deg, #3B82F6 0%, #1D4ED8 100%); display:flex; align-items:center; justify-content:center; color:#FFFFFF; font-weight:700; font-size:1.2rem; box-shadow:0 2px 8px rgba(59, 130, 246, 0.3);">
                                        {card.full_name[0]}
                                    </div>
                                    <div style="position:absolute; bottom:-3px; right:-3px; background:var(--bg-card); border-radius:50%; width:20px; height:20px; display:flex; align-items:center; justify-content:center; font-size:0.75rem; box-shadow:0 1px 4px rgba(0,0,0,0.2); border:1px solid var(--border-card);" title="{rank['title']} ({rank['tier']})">
                                        {rank['icon']}
                                    </div>
                                </div>
                                <div>
                                    <div style="font-weight:700; font-size:1.02rem; color:var(--text-main); line-height:1.25;">{card.full_name}</div>
                                    <div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">{online_handle}</div>
                                </div>
                            </div>
                            <div style="text-align:right;">
                                <div style="font-size:1.15rem; font-weight:800; color:var(--text-main); letter-spacing:-0.02em;">
                                    ⭐ {card.rating}
                                </div>
                                <div style="font-size:0.7rem; font-weight:600; color:{rank['color']}; background:{rank['bg']}; padding:2px 7px; border-radius:10px; display:inline-block; margin-top:2px;">
                                    {rank['icon']} {rank['title']}
                                </div>
                            </div>
                        </div>

                        <!-- Прогресс-бар XP до следующего звания -->
                        <div style="margin-bottom:12px; background:var(--bg-card-subtle); padding:8px 10px; border-radius:8px; border:1px solid var(--border-subtle);">
                            <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.73rem; margin-bottom:5px;">
                                <span style="color:var(--text-muted); font-weight:500;">Уровень: <b style="color:var(--text-main);">{rank['tier']}</b></span>
                                <span style="color:var(--text-main); font-weight:700;">{card.rating} / {gamify['next_xp']} XP</span>
                            </div>
                            <div style="width:100%; height:6px; background:var(--border-card); border-radius:3px; overflow:hidden;">
                                <div style="width:{gamify['progress_pct']}%; height:100%; background:linear-gradient(90deg, #3B82F6 0%, #8B5CF6 100%); border-radius:3px;"></div>
                            </div>
                        </div>

                        <!-- Форма (последние 5) и Стрик активности -->
                        <div style="display:flex; justify-content:space-between; align-items:center; padding:7px 0; margin-bottom:10px; border-top:1px solid var(--border-divider); border-bottom:1px solid var(--border-divider); font-size:0.78rem;">
                            <div>
                                <span style="color:var(--text-muted); font-size:0.7rem; display:block; margin-bottom:2px;">Форма (5 партий):</span>
                                <span style="letter-spacing:2px; font-size:0.85rem;">{gamify['form_display']}</span>
                            </div>
                            <div style="text-align:right;">
                                <span style="color:var(--text-muted); font-size:0.7rem; display:block; margin-bottom:2px;">Активность:</span>
                                <span style="font-weight:600; color:var(--text-main);">{gamify['streak_text']}</span>
                            </div>
                        </div>

                        <!-- Суперсила и Зона фокуса -->
                        <div style="display:flex; gap:6px; align-items:center; flex-wrap:wrap;">
                            <span class="badge-chip badge-win" title="Главная сильная сторона">⚡ {gamify['superpower']}</span>
                            <span class="badge-chip badge-blunder" title="Зона фокуса">🎯 {gamify['focus_area']}</span>
                            <span style="margin-left:auto; font-size:0.75rem; color:var(--text-muted);">CAPS: <b style="color:#3B82F6;">{card.avg_caps_accuracy}%</b></span>
                        </div>
                    </div>
                    """)

                    # Две аккуратные кнопки внизу карточки: "Разбор" (Primary) и "WhatsApp родителю" (Soft Green)
                    col_b1, col_b2 = st.columns([1, 1])
                    with col_b1:
                        if st.button("🔍 Разбор", key=f"btn_deep_card_{card.id}", type="primary", use_container_width=True):
                            st.session_state["selected_student_id"] = card.id
                            st.session_state["main_nav_tab"] = "🔍 Разбор ученика"
                            st.rerun()
                    with col_b2:
                        if card.whatsapp_link:
                            st.link_button("💬 WhatsApp родителю", card.whatsapp_link, use_container_width=True)
                        else:
                            st.button("💬 WhatsApp", disabled=True, use_container_width=True, key=f"no_tel_card_{card.id}")

                    # Expander для редактирования/удаления
                    with st.expander(f"⚙️ Профиль: {card.full_name}", expanded=False):
                        with get_db_session() as session:
                            st_obj = session.get(StudentProfile, student.id)
                            all_school_groups = SchoolService.list_groups(session, school.id)

                        if st_obj:
                            tab_edit_st, tab_del_st = st.tabs(["✏️ Редактировать", "🗑️ Удалить"])
                            with tab_edit_st:
                                with st.form(f"form_edit_stud_{student.id}"):
                                    col_es1, col_es2 = st.columns(2)
                                    with col_es1:
                                        ef_name = st.text_input("Имя", value=st_obj.first_name)
                                        el_name = st.text_input("Фамилия", value=st_obj.last_name)
                                        erating = st.number_input("Рейтинг", min_value=500, max_value=2900, value=st_obj.current_rating or 1200, step=25)
                                        group_names = [g.name for g in all_school_groups]
                                        current_g_idx = 0
                                        for idx, g in enumerate(all_school_groups):
                                            if g.id == st_obj.group_id:
                                                current_g_idx = idx
                                                break
                                        eg_name = st.selectbox("Учебная группа (перевод)", group_names, index=current_g_idx, key=f"sel_grp_{student.id}")
                                    with col_es2:
                                        ep_name = st.text_input("ФИО родителя", value=st_obj.parent_name or "")
                                        ep_phone = st.text_input("Телефон родителя", value=st_obj.parent_phone or "")
                                        ep_tg = st.text_input("Telegram родителя", value=st_obj.parent_telegram or "")
                                        elic = st.text_input("Lichess никнейм", value=card.lichess_username or "")
                                        ecom = st.text_input("Chess.com никнейм", value=card.chesscom_username or "")

                                    if st.form_submit_button("💾 Сохранить изменения", type="primary", use_container_width=True):
                                        target_gid = next((g.id for g in all_school_groups if g.name == eg_name), st_obj.group_id)
                                        with get_db_session() as session:
                                            SchoolService.update_student(session, st_obj.id, StudentUpdate(
                                                first_name=ef_name.strip(),
                                                last_name=el_name.strip(),
                                                current_rating=int(erating),
                                                group_id=target_gid,
                                                parent_name=ep_name.strip() if ep_name else None,
                                                parent_phone=ep_phone.strip() if ep_phone else None,
                                                parent_telegram=ep_tg.strip() if ep_tg else None
                                            ))
                                            if elic.strip():
                                                SchoolService.add_or_update_chess_account(session, st_obj.id, "lichess", elic.strip())
                                            if ecom.strip():
                                                SchoolService.add_or_update_chess_account(session, st_obj.id, "chesscom", ecom.strip())
                                        st.success("Данные ученика сохранены!")
                                        time.sleep(1)
                                        st.rerun()

                            with tab_del_st:
                                st.warning(f"Вы действительно хотите удалить ученика **{card.full_name}** и все связанные партии?")
                                confirm_del_s = st.checkbox(f"Подтверждаю удаление {card.full_name}", key=f"chk_del_s_{student.id}")
                                if st.button("🗑️ Удалить ученика", disabled=not confirm_del_s, type="primary", use_container_width=True, key=f"btn_del_s_{student.id}"):
                                    with get_db_session() as session:
                                        SchoolService.delete_student(session, student.id)
                                    st.success(f"Ученик {card.full_name} удален.")
                                    time.sleep(1)
                                    st.rerun()

                    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

    # 4. Форма добавления нового ученика в группу
    with st.expander("➕ Добавить нового ученика в эту группу", expanded=False):
        with st.form("form_add_student"):
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                st_first_name = st.text_input("Имя ученика *", placeholder="Например: Иван")
                st_last_name = st.text_input("Фамилия ученика *", placeholder="Например: Иванов")
                st_rating = st.number_input("Текущий рейтинг", min_value=500, max_value=2800, value=1200, step=25)
                st_lichess = st.text_input("Lichess никнейм", placeholder="Например: IvanChess2026")
            with col_f2:
                st_parent_name = st.text_input("ФИО родителя", placeholder="Например: Елена Иванова")
                st_parent_phone = st.text_input("Телефон родителя (WhatsApp)", placeholder="+7 (999) 123-45-67")
                st_chesscom = st.text_input("Chess.com никнейм", placeholder="Например: Ivan_Ivanov")
                st_notes = st.text_area("Заметки тренера", placeholder="Особенности характера, цели...")

            submit_student = st.form_submit_button("✅ Сохранить ученика в группу", type="primary", use_container_width=True)

            if submit_student:
                if not st_first_name.strip() or not st_last_name.strip():
                    st.error("Пожалуйста, заполните имя и фамилию ученика!")
                else:
                    with get_db_session() as session:
                        new_student = SchoolService.create_student(
                            session,
                            StudentCreate(
                                school_id=school.id,
                                group_id=selected_group_id,
                                first_name=st_first_name,
                                last_name=st_last_name,
                                current_rating=int(st_rating),
                                parent_name=st_parent_name,
                                parent_phone=st_parent_phone,
                                lichess_username=st_lichess,
                                chesscom_username=st_chesscom,
                                notes=st_notes,
                            )
                        )
                    st.success(f"Ученик {st_first_name} {st_last_name} успешно добавлен в группу!")
                    time.sleep(1)
                    st.rerun()

# ============================================================================
# РАЗДЕЛ 2: 🔍 РАЗБОР УЧЕНИКА (DEEP DIVE, ДОСКА, ДЕБЮТЫ)
# ============================================================================
elif selected_tab == "🔍 Разбор ученика":
    if not group_students:
        st.info("В выбранной группе нет учеников.")
        st.stop()

    student_options = {s.full_name: s.id for s in group_students}
    current_sel_id = st.session_state.get("selected_student_id")
    
    # Индекс по умолчанию
    default_idx = 0
    if current_sel_id:
        for idx, s in enumerate(group_students):
            if s.id == current_sel_id:
                default_idx = idx
                break

    selected_student_name = st.selectbox(
        "Выбор ученика для персонального анализа:",
        options=list(student_options.keys()),
        index=default_idx,
        key="deep_dive_student_select"
    )
    active_student_id = student_options[selected_student_name]
    st.session_state["selected_student_id"] = active_student_id

    # Загружаем профиль, партии и ошибки ученика
    with get_db_session() as session:
        active_student = session.get(StudentProfile, active_student_id)
        student_games = list(session.execute(
            select(Game)
            .where(Game.student_profile_id == active_student_id)
            .order_by(Game.played_at.desc())
        ).scalars().all())

        student_errors = list(session.execute(
            select(ChessErrorEvent)
            .where(ChessErrorEvent.student_profile_id == active_student_id)
            .order_by(ChessErrorEvent.move_number.asc())
        ).scalars().all())

    # Быстрые действия: Скачать отчет родителям / Листок задач
    col_act1, col_act2, col_act3 = st.columns([4, 4, 3])
    with col_act1:
        if student_errors and student_games:
            worksheet_pdf = WorksheetPDFGenerator.generate_worksheet(
                student_name=active_student.full_name,
                error_events=student_errors,
                games=student_games,
                max_puzzles=4
            )
            st.download_button(
                label="🧩 Листок задач А4 из ошибок (PDF)",
                data=worksheet_pdf,
                file_name=f"Worksheet_{active_student.full_name.replace(' ', '_')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="btn_download_worksheet_deep"
            )
    with col_act2:
        if student_games:
            # Генерация отчета для родителей
            agg_stats = GameMetricsAggregator.aggregate(student_games, student_errors, active_student.full_name)
            parent_rep_data = LLMReporterService.generate_parent_report(agg_stats)
            pdf_bytes = PDFReportGenerator.generate_parent_report_pdf(
                student_name=active_student.full_name,
                report=parent_rep_data,
                stats=agg_stats
            )
            st.download_button(
                label="📄 Недельный отчёт родителю (PDF)",
                data=pdf_bytes,
                file_name=f"Report_{active_student.full_name.replace(' ', '_')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="btn_download_parent_report_deep"
            )
    with col_act3:
        if active_student.parent_phone:
            clean_p = "".join(c for c in active_student.parent_phone if c.isdigit())
            if clean_p.startswith("8") and len(clean_p) == 11:
                clean_p = "7" + clean_p[1:]
            msg = urllib.parse.quote(f"Здравствуйте, {active_student.parent_name or 'уважаемый родитель'}! Направляю отчет об успехах {active_student.first_name} в шахматах.")
            st.link_button("💬 Написать родителю", f"https://wa.me/{clean_p}?text={msg}", use_container_width=True)

    with st.expander(f"⚙️ Редактировать профиль или перевести ученика {active_student.full_name}", expanded=False):
        with get_db_session() as session:
            all_groups_tab2 = SchoolService.list_groups(session, school.id)

        tab2_e_tab, tab2_d_tab = st.tabs(["✏️ Редактировать данные", "🗑️ Удалить ученика"])
        with tab2_e_tab:
            with st.form(f"form_deep_edit_{active_student.id}"):
                c_d1, c_d2 = st.columns(2)
                with c_d1:
                    d_first = st.text_input("Имя", value=active_student.first_name)
                    d_last = st.text_input("Фамилия", value=active_student.last_name)
                    d_rating = st.number_input("Рейтинг", min_value=500, max_value=2900, value=active_student.current_rating or 1200, step=25)
                    g_names = [g.name for g in all_groups_tab2]
                    curr_g_idx = 0
                    for idx, g in enumerate(all_groups_tab2):
                        if g.id == active_student.group_id:
                            curr_g_idx = idx
                            break
                    d_group = st.selectbox("Группа (перевод)", g_names, index=curr_g_idx, key=f"sel_d_grp_{active_student.id}")
                with c_d2:
                    d_pname = st.text_input("ФИО родителя", value=active_student.parent_name or "")
                    d_pphone = st.text_input("Телефон родителя", value=active_student.parent_phone or "")
                    d_ptg = st.text_input("Telegram родителя", value=active_student.parent_telegram or "")
                    d_notes = st.text_area("Заметки", value=active_student.notes or "")

                if st.form_submit_button("💾 Сохранить изменения", type="primary", use_container_width=True):
                    new_gid = next((g.id for g in all_groups_tab2 if g.name == d_group), active_student.group_id)
                    with get_db_session() as session:
                        SchoolService.update_student(session, active_student.id, StudentUpdate(
                            first_name=d_first.strip(),
                            last_name=d_last.strip(),
                            current_rating=int(d_rating),
                            group_id=new_gid,
                            parent_name=d_pname.strip() if d_pname else None,
                            parent_phone=d_pphone.strip() if d_pphone else None,
                            parent_telegram=d_ptg.strip() if d_ptg else None,
                            notes=d_notes.strip() if d_notes else None
                        ))
                    st.success("Профиль ученика обновлен!")
                    time.sleep(1)
                    st.rerun()

        with tab2_d_tab:
            st.warning(f"Удалить профиль **{active_student.full_name}** и все связанные данные?")
            confirm_del_deep = st.checkbox(f"Подтверждаю удаление {active_student.full_name}", key=f"chk_del_deep_{active_student.id}")
            if st.button("🗑️ Удалить ученика", disabled=not confirm_del_deep, type="primary", use_container_width=True, key=f"btn_del_deep_{active_student.id}"):
                with get_db_session() as session:
                    SchoolService.delete_student(session, active_student.id)
                st.session_state.pop("selected_student_id", None)
                st.session_state["main_nav_tab"] = "👥 Группы и ученики"
                st.success(f"Ученик {active_student.full_name} удален.")
                time.sleep(1)
                st.rerun()

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # Сетка интерактивной доски и партий
    if not student_games:
        st.info("У данного ученика пока нет сыгранных партий. Нажмите 'Синхронизировать партии всей группы' на Вкладке 1.")
    else:
        col_list, col_board = st.columns([5, 5], gap="large")

        with col_list:
            st.markdown("#### ♟️ Сыгранные партии")
            game_selector_options = {
                f"{g.played_at.strftime('%d.%m %H:%M')} vs {g.opponent_username} ({g.result}) • {g.eco_code or 'C50'}": g.id
                for g in student_games
            }
            chosen_game_label = st.selectbox("Выберите партию:", options=list(game_selector_options.keys()), key="game_select_deep")
            selected_game_id = game_selector_options[chosen_game_label]
            chosen_game = next(g for g in student_games if g.id == selected_game_id)

            errors_this_game = [e for e in student_errors if e.game_id == selected_game_id]

            render_html(f"""
            <div class="saas-card" style="padding:12px; margin-bottom:12px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span style="font-weight:700; color:var(--text-main); font-size:1.0rem;">{chosen_game.opening_name or 'Открытый дебют'}</span>
                        <div style="font-size:0.8rem; color:var(--text-muted); margin-top:2px;">ECO: {chosen_game.eco_code or 'C50'} • Контроль: {chosen_game.time_control}</div>
                    </div>
                    <div>
                        <span class="badge-chip {'badge-win' if chosen_game.result == '1-0' else 'badge-blunder'}">{chosen_game.result}</span>
                    </div>
                </div>
                <div style="display:flex; gap:12px; margin-top:10px; font-size:0.85rem;">
                    <div>Точность: <b style="color:#3B82F6;">{chosen_game.accuracy_score or 85}%</b></div>
                    <div>ACPL: <b>{chosen_game.acpl or 25}</b></div>
                    <div>Зевков: <b style="color:#EF4444;">{chosen_game.blunders_count or 0}</b></div>
                </div>
            </div>
            """)

            st.markdown("#### 🚨 Критические ошибки в партии:")
            if not errors_this_game:
                st.success("В этой партии ученик не допустил грубых ошибок! Очень чистая игра.")
                selected_error = None
            else:
                for idx, err in enumerate(errors_this_game, 1):
                    is_active_err = st.button(
                        f"Ход {err.move_number}: {err.played_move_san} (-{err.centipawn_loss} CPL) • {err.tactical_tag or 'тактика'}",
                        key=f"err_btn_{err.id}",
                        use_container_width=True
                    )
                    if is_active_err:
                        st.session_state["chosen_error_id"] = err.id

                active_err_id = st.session_state.get("chosen_error_id", errors_this_game[0].id)
                selected_error = next((e for e in errors_this_game if e.id == active_err_id), errors_this_game[0])

        with col_board:
            st.markdown("#### 🎯 Интерактивная доска разбора")
            if selected_error:
                board_orientation = "white" if chosen_game.student_color == "white" else "black"
                show_best = st.checkbox("💡 Показать правильный ход Stockfish на доске", key=f"show_best_{selected_error.id}")

                render_interactive_chessboard(
                    fen=selected_error.fen_before,
                    eval_score=(selected_error.eval_before / 100.0) if selected_error.eval_before is not None else 0.0,
                    best_move=selected_error.best_move_uci,
                    student_move=selected_error.played_move_uci,
                    best_move_uci=selected_error.best_move_uci,
                    animate_best_move=show_best,
                    orientation=board_orientation,
                    theme="dark" if is_dark else "light",
                    key=f"board_deep_{selected_error.id}"
                )

                render_html(f"""
                <div class="alert-card-danger" style="margin-top:10px;">
                    <div style="font-weight:700; color:var(--alert-danger-title); margin-bottom:4px;">
                        [{selected_error.severity.upper()}] Ход {selected_error.move_number}: {selected_error.played_move_san}
                    </div>
                    <div style="font-size:0.88rem; color:var(--alert-danger-text);">
                        Лучший ход Stockfish: <b>{selected_error.best_move_san}</b> ({selected_error.best_move_uci}). 
                        Потеря: <b>-{selected_error.centipawn_loss} CPL</b>. Паттерн: <b>{selected_error.tactical_tag or 'тактический просчет'}</b>.
                    </div>
                </div>
                """)
            else:
                board_orientation = "white" if chosen_game.student_color == "white" else "black"
                render_interactive_chessboard(
                    fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                    orientation=board_orientation,
                    theme="dark" if is_dark else "light",
                    key=f"board_clean_{chosen_game.id}"
                )

        st.divider()

        # Анализ дебютных дыр ученика
        st.markdown("### 📖 Дебютное дерево и дыры в репертуаре")
        repertoire = OpeningAnalyzerService.analyze_repertoire(student_games, active_student.full_name)

        col_white, col_black = st.columns(2)
        with col_white:
            st.markdown("#### ⚪ За белых:")
            for op in repertoire.white_openings[:4]:
                badge_class = "badge-win" if op.win_rate >= 50 else ("badge-mistake" if op.win_rate >= 40 else "badge-blunder")
                status_icon = "🛡️ Надежно" if not op.is_hole else "🚨 Уязвимость"
                render_html(f"""
                <div class="saas-card" style="padding:10px; margin-bottom:8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-weight:600; color:var(--text-main); font-size:0.92rem;">{op.opening_name}</span>
                        <span class="badge-chip {badge_class}">{op.win_rate}% побед</span>
                    </div>
                    <div style="font-size:0.78rem; color:var(--text-muted); margin-top:4px;">
                        Партий: {op.games_count} • Дебютный ACPL: {op.avg_cpl} • <b>{status_icon}</b>
                    </div>
                </div>
                """)

        with col_black:
            st.markdown("#### ⚫ За черных:")
            for op in repertoire.black_openings[:4]:
                badge_class = "badge-win" if op.win_rate >= 50 else ("badge-mistake" if op.win_rate >= 40 else "badge-blunder")
                status_icon = "🛡️ Надежно" if not op.is_hole else "🚨 Уязвимость"
                render_html(f"""
                <div class="saas-card" style="padding:10px; margin-bottom:8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-weight:600; color:var(--text-main); font-size:0.92rem;">{op.opening_name}</span>
                        <span class="badge-chip {badge_class}">{op.win_rate}% побед</span>
                    </div>
                    <div style="font-size:0.78rem; color:var(--text-muted); margin-top:4px;">
                        Партий: {op.games_count} • Дебютный ACPL: {op.avg_cpl} • <b>{status_icon}</b>
                    </div>
                </div>
                """)

# ============================================================================
# РАЗДЕЛ 3: 📦 ПАКЕТНАЯ РАЗДАЧА (PDF & ДЗ)
# ============================================================================
elif selected_tab == "📦 Пакетная раздача (PDF & ДЗ)":
    st.markdown(f"### 📦 Пакетные действия для группы: {selected_group_label}")
    st.caption("Массовая генерация отчетов родителям, печать раздаточных материалов А4 и рассылка в WhatsApp в 1 клик.")

    col_batch1, col_batch2 = st.columns(2)

    with col_batch1:
        render_html("""
        <div class="saas-card">
            <div style="font-size:1.1rem; font-weight:700; color:var(--text-main); margin-bottom:4px;">
                📥 Пакетный архив отчетов родителей (.zip)
            </div>
            <div style="font-size:0.85rem; color:var(--text-muted); line-height:1.4; margin-bottom:12px;">
                Сформировать недельные брендированные PDF-отчеты с логотипом Академии для всех учеников группы одним файлом.
            </div>
        </div>
        """)
        # Генерация ZIP-архива
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for s in group_students:
                with get_db_session() as session:
                    s_games = list(session.execute(select(Game).where(Game.student_profile_id == s.id)).scalars().all())
                    s_errs = list(session.execute(select(ChessErrorEvent).where(ChessErrorEvent.student_profile_id == s.id)).scalars().all())
                    if s_games:
                        agg = GameMetricsAggregator.aggregate(s_games, s_errs, s.full_name)
                        p_rep = LLMReporterService.generate_parent_report(agg)
                        pdf_data = PDFReportGenerator.generate_parent_report_pdf(s.full_name, p_rep, agg)
                        safe_name = s.full_name.replace(" ", "_")
                        zip_file.writestr(f"Отчет_{safe_name}.pdf", pdf_data)

        zip_buffer.seek(0)
        st.download_button(
            label="📥 Скачать все PDF-отчеты родителей (.zip)",
            data=zip_buffer.getvalue(),
            file_name=f"Отчеты_Родителям_{selected_group_label[:15].replace(' ', '_')}.zip",
            mime="application/zip",
            use_container_width=True,
            type="primary",
            key="btn_download_zip"
        )

    with col_batch2:
        render_html("""
        <div class="saas-card">
            <div style="font-size:1.1rem; font-weight:700; color:var(--text-main); margin-bottom:4px;">
                📑 Единый листок задач А4 к сегодняшнему уроку
            </div>
            <div style="font-size:0.85rem; color:var(--text-muted); line-height:1.4; margin-bottom:12px;">
                Собрать 4 ключевые тактические ошибки из недавних партий учеников группы для совместного решения на занятии.
            </div>
        </div>
        """)

        # Собираем все ошибки группы
        all_group_errors = []
        all_group_games = []
        with get_db_session() as session:
            g_stud_ids = [s.id for s in group_students]
            if g_stud_ids:
                all_group_errors = list(session.execute(select(ChessErrorEvent).where(ChessErrorEvent.student_profile_id.in_(g_stud_ids))).scalars().all())
                all_group_games = list(session.execute(select(Game).where(Game.student_profile_id.in_(g_stud_ids))).scalars().all())

        if all_group_errors:
            group_worksheet_pdf = WorksheetPDFGenerator.generate_worksheet(
                student_name=f"Группа: {selected_group_label.split('(')[0].strip()}",
                error_events=all_group_errors,
                games=all_group_games,
                max_puzzles=4
            )
            st.download_button(
                label="📑 Скачать листок задач А4 на урок (PDF)",
                data=group_worksheet_pdf,
                file_name=f"Worksheet_Lesson_{selected_group_label[:15].replace(' ', '_')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                type="primary",
                key="btn_download_group_worksheet"
            )
        else:
            st.button("📑 Нет данных для раздаточного материала", disabled=True, use_container_width=True)

    st.divider()

    # Таблица быстрой отправки в WhatsApp
    st.markdown("#### 📱 Быстрая отправка отчетов родителям в WhatsApp")
    st.caption("Нажмите на кнопку, чтобы открыть чат с родителем с уже предзаполненным персональным текстом успехов:")

    for s in group_students:
        with get_db_session() as session:
            card = SchoolService.get_student_cockpit_card(session, s.id)

        col_w1, col_w2, col_w3, col_w4 = st.columns([3, 2, 3, 2])
        with col_w1:
            st.write(f"**{card.full_name}** (Рейтинг: {card.rating})")
        with col_w2:
            st.write(f"{card.parent_name or 'Родитель'}")
        with col_w3:
            st.write(f"📞 `{card.parent_phone or 'нет номера'}`")
        with col_w4:
            if card.whatsapp_link:
                st.link_button("💬 В WhatsApp", card.whatsapp_link, use_container_width=True)
            else:
                st.button("Нет номера", disabled=True, use_container_width=True, key=f"no_tel_batch_{card.id}")

        st.markdown("<div style='height:2px; border-bottom:1px solid var(--border-divider); margin:4px 0 8px 0;'></div>", unsafe_allow_html=True)
