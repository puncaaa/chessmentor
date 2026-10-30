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
from app.schemas.school import StudentCreate
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
    page_title="ChessCoach AI — Teacher Cockpit (B2B SaaS)",
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
    """Генерация дизайн-системы Linear / Tailwind Slate."""
    if is_dark:
        vars_css = """
        --bg-page: #0B0F17;
        --bg-sidebar: #0D131F;
        --bg-card: #161F30;
        --bg-card-subtle: rgba(255, 255, 255, 0.03);
        --border-card: rgba(255, 255, 255, 0.08);
        --border-card-hover: rgba(255, 255, 255, 0.16);
        --border-subtle: rgba(255, 255, 255, 0.06);
        --border-divider: rgba(255, 255, 255, 0.08);
        --text-main: #F3F4F6;
        --text-muted: #9CA3AF;
        --text-subtle: #6B7280;
        --code-bg: #0F172A;
        --shadow-card: 0 4px 20px rgba(0, 0, 0, 0.3);
        --shadow-card-hover: 0 8px 30px rgba(0, 0, 0, 0.4);
        --alert-danger-bg: rgba(239, 68, 68, 0.06);
        --alert-danger-border: rgba(239, 68, 68, 0.25);
        --alert-danger-text: #F3F4F6;
        --alert-danger-title: #F87171;
        --alert-info-bg: rgba(59, 130, 246, 0.06);
        --alert-info-border: rgba(59, 130, 246, 0.25);
        --alert-info-text: #F3F4F6;
        --alert-info-title: #60A5FA;
        --alert-success-bg: rgba(16, 185, 129, 0.06);
        --alert-success-border: rgba(16, 185, 129, 0.25);
        --alert-success-text: #F3F4F6;
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
        --shadow-card: 0 2px 10px rgba(0, 0, 0, 0.05);
        --shadow-card-hover: 0 6px 20px rgba(0, 0, 0, 0.08);
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
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    :root {{
        {vars_css}
    }}

    .stApp {{
        background-color: var(--bg-page) !important;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        color: var(--text-main) !important;
    }}

    section[data-testid="stSidebar"] {{
        background-color: var(--bg-sidebar) !important;
        border-right: 1px solid var(--border-divider) !important;
    }}

    /* Карточки KPI и дашборда */
    .saas-card {{
        background: var(--bg-card);
        border: 1px solid var(--border-card);
        border-radius: 12px;
        padding: 16px;
        box-shadow: var(--shadow-card);
        transition: all 0.2s ease;
    }}
    .saas-card:hover {{
        border-color: var(--border-card-hover);
        box-shadow: var(--shadow-card-hover);
    }}

    .kpi-card {{
        background: var(--bg-card);
        border: 1px solid var(--border-card);
        border-radius: 10px;
        padding: 14px 18px;
        box-shadow: var(--shadow-card);
    }}
    .kpi-label {{
        color: var(--text-muted);
        font-size: 0.78rem;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }}
    .kpi-value {{
        color: var(--text-main);
        font-size: 1.55rem;
        font-weight: 700;
        margin-top: 4px;
        letter-spacing: -0.02em;
    }}
    .kpi-subtext {{
        color: var(--text-subtle);
        font-size: 0.78rem;
        margin-top: 3px;
    }}

    /* Ученик в списке (CRM Card) */
    .student-row-card {{
        background: var(--bg-card);
        border: 1px solid var(--border-card);
        border-radius: 12px;
        padding: 14px 18px;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        transition: border-color 0.15s ease;
    }}
    .student-row-card:hover {{
        border-color: var(--border-card-hover);
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
    .badge-plan {{ background: rgba(59, 130, 246, 0.15); color: #60A5FA; border: 1px solid rgba(59, 130, 246, 0.3); }}

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

    /* Кнопки WhatsApp */
    .btn-whatsapp {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: #10B981;
        color: white !important;
        text-decoration: none !important;
        font-size: 0.82rem;
        font-weight: 600;
        padding: 6px 12px;
        border-radius: 6px;
        transition: background 0.15s ease;
    }}
    .btn-whatsapp:hover {{
        background: #059669;
    }}

    /* Компактный контейнер шахматной доски 420px */
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

st.markdown(get_theme_css(is_dark), unsafe_allow_html=True)
init_db()

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ ДАННЫХ ШКОЛЫ И ТРЕНЕРА
# ============================================================================
with get_db_session() as session:
    school = SchoolService.get_or_create_default_school(session)
    teachers = SchoolService.list_teachers(session, school.id)
    if not teachers:
        # Автоматическое наполнение, если база пустая
        from scripts.seed_school import seed_database
        seed_database()
        school = SchoolService.get_or_create_default_school(session)
        teachers = SchoolService.list_teachers(session, school.id)

# Селектор тренера
coach_options = {f"{t.full_name} ({t.fide_title or 'Тренер'})": t.id for t in teachers}
default_coach_name = list(coach_options.keys())[0] if coach_options else "Тренер"

# ============================================================================
# БОКОВАЯ ПАНЕЛЬ (SIDEBAR): О ШКОЛЕ И НАСТРОЙКИ
# ============================================================================
with st.sidebar:
    render_html(f"""
    <div style="display:flex; align-items:center; gap:12px; margin-bottom:14px; padding-bottom:12px; border-bottom:1px solid var(--border-divider);">
        <img src="{school.logo_url or 'https://img.icons8.com/color/96/chess-knight.png'}" style="width:40px; height:40px; object-fit:contain;" />
        <div>
            <div style="font-size:1.05rem; font-weight:700; color:var(--text-main); line-height:1.2;">{school.name}</div>
            <div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">B2B Academy Cockpit</div>
        </div>
    </div>
    """)

    selected_coach_label = st.selectbox(
        "👔 Текущий тренер:",
        options=list(coach_options.keys()),
        index=0,
        key="active_coach_select"
    )
    current_teacher_id = coach_options.get(selected_coach_label)

    st.divider()

    st.radio(
        "Тема оформления:",
        options=["🌙 Темная", "☀️ Светлая"],
        index=0 if is_dark else 1,
        horizontal=True,
        key="app_theme_choice"
    )

    st.divider()
    render_html(f"""
    <div class="saas-card" style="padding:12px; font-size:0.8rem;">
        <div style="font-weight:600; color:var(--text-main); margin-bottom:6px;">🏫 Параметры школы</div>
        <div style="color:var(--text-muted);">Тариф: <span class="badge-chip badge-plan">{school.subscription_tier.upper()}</span></div>
        <div style="color:var(--text-muted); margin-top:4px;">Лимит мест: <b>{school.max_students} учеников</b></div>
        <div style="color:var(--text-muted); margin-top:4px;">Движок: <span style="color:#10B981; font-weight:600;">Stockfish 19 AI</span></div>
        <div style="color:var(--text-muted); margin-top:4px;">Синхронизация: <span style="color:#3B82F6; font-weight:600;">Lichess & Chess.com</span></div>
    </div>
    """)

# ============================================================================
# ВЕРХНЯЯ ШАПКА ДАШБОРДА
# ============================================================================
render_html(f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; padding-bottom:10px; border-bottom:1px solid var(--border-divider);">
    <div style="display:flex; align-items:center; gap:12px;">
        <span style="font-size:2.0rem;">♟️</span>
        <div>
            <div style="font-size:1.45rem; font-weight:800; color:var(--text-main); letter-spacing:-0.02em;">
                {school.name}
            </div>
            <div style="font-size:0.85rem; color:var(--text-muted); margin-top:2px;">
                Кабинет тренера: <span style="color:#3B82F6; font-weight:600;">{selected_coach_label}</span> • Лицензия активна
            </div>
        </div>
    </div>
    <div style="display:flex; gap:8px;">
        <span class="badge-chip badge-win">🟢 Движок Stockfish 19 активен</span>
        <span class="badge-chip badge-plan">⚡ Pro Plan ({school.max_students} мест)</span>
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

# Загрузка групп школы
with get_db_session() as session:
    school_groups = SchoolService.list_groups(session, school.id)

if not school_groups:
    st.warning("В школе пока нет групп. Нажмите сидирование базы данных!")
    st.stop()

# Групповой селектор
group_dict = {f"{g.name} ({g.level})": g.id for g in school_groups}
selected_group_label = st.selectbox(
    "Учебная группа:",
    options=list(group_dict.keys()),
    index=0,
    key="active_group_select"
)
selected_group_id = group_dict[selected_group_label]

with get_db_session() as session:
    group_stats = SchoolService.get_group_with_stats(session, selected_group_id)
    group_students = SchoolService.list_students(session, school_id=school.id, group_id=selected_group_id)

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
        st.caption(f"Расписание занятий: **{group_stats.schedule or 'По договоренности'}** • Куратор: **{group_stats.teacher_name or selected_coach_label}**")

    st.divider()

    # 3. Список учеников группы (Ростер)
    st.markdown(f"### 📋 Ученики группы ({len(group_students)})")

    if not group_students:
        st.info("В этой группе пока нет учеников. Добавьте первого ученика через форму ниже!")
    else:
        for student in group_students:
            with get_db_session() as session:
                card = SchoolService.get_student_cockpit_card(session, student.id)

            col_stud_info, col_stud_metrics, col_stud_actions = st.columns([4, 4, 3])

            with col_stud_info:
                online_handle = f"Lichess: @{card.lichess_username}" if card.lichess_username else (f"Chess.com: @{card.chesscom_username}" if card.chesscom_username else "Без аккаунта")
                render_html(f"""
                <div style="display:flex; align-items:center; gap:12px;">
                    <div style="background:#3B82F6; color:white; width:40px; height:40px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:1.1rem; flex-shrink:0;">
                        {card.full_name[0]}
                    </div>
                    <div>
                        <div style="font-weight:700; font-size:1.05rem; color:var(--text-main);">{card.full_name}</div>
                        <div style="font-size:0.8rem; color:var(--text-muted);">{online_handle} • Рейтинг: <b style="color:var(--text-main);">{card.rating}</b></div>
                    </div>
                </div>
                """)

            with col_stud_metrics:
                tag_label = "Зевки фигур"
                if card.top_weakness_tag == "time_trouble_panic":
                    tag_label = "Цейтнот"
                elif card.top_weakness_tag == "missed_fork":
                    tag_label = "Вилки конем"
                elif card.top_weakness_tag == "missed_pin":
                    tag_label = "Связки"
                elif card.top_weakness_tag == "endgame_king_activity":
                    tag_label = "Эндшпиль"

                render_html(f"""
                <div style="display:flex; gap:14px; align-items:center;">
                    <div>
                        <div style="font-size:0.75rem; color:var(--text-muted);">Игр за неделю</div>
                        <div style="font-weight:700; font-size:0.95rem; color:var(--text-main);">♟️ {card.games_this_week} партий</div>
                    </div>
                    <div>
                        <div style="font-size:0.75rem; color:var(--text-muted);">Точность (CAPS)</div>
                        <div style="font-weight:700; font-size:0.95rem; color:#3B82F6;">{card.avg_caps_accuracy}%</div>
                    </div>
                    <div>
                        <div style="font-size:0.75rem; color:var(--text-muted);">Слабость</div>
                        <span class="badge-chip badge-blunder">{tag_label}</span>
                    </div>
                </div>
                """)

            with col_stud_actions:
                col_btn_wa, col_btn_go = st.columns([1, 1])
                with col_btn_wa:
                    if card.whatsapp_link:
                        st.link_button("💬 WhatsApp", card.whatsapp_link, use_container_width=True)
                    else:
                        st.button("💬 Нет тел.", disabled=True, use_container_width=True, key=f"no_tel_{card.id}")
                with col_btn_go:
                    if st.button("🔍 Разбор", key=f"goto_deep_{card.id}", use_container_width=True):
                        st.session_state["selected_student_id"] = card.id
                        st.session_state["main_nav_tab"] = "🔍 Разбор ученика"
                        st.rerun()

            st.markdown("<div style='height:4px; border-bottom:1px solid var(--border-divider); margin:8px 0 12px 0;'></div>", unsafe_allow_html=True)

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
                render_interactive_chessboard(
                    fen=selected_error.fen_before,
                    eval_score=selected_error.eval_before / 100.0,
                    best_move=selected_error.best_move_uci,
                    student_move=selected_error.played_move_uci,
                    orientation=board_orientation,
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
