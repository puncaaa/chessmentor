import os
import sys
import io
import base64
import time
import textwrap
from datetime import datetime
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

import httpx
from app.db.session import init_db, get_db_session
from app.models.chess import StudentProfile, StudentChessAccount, Game, ChessErrorEvent
from app.tasks.sync_tasks import sync_student_games
from app.services.chess_sync import UserNotFoundError
from app.services.chess_analyzer import ChessEngineAnalyzer
from app.services.llm_reporter import GameMetricsAggregator, LLMReporterService
from app.services.puzzle_service import PuzzleGeneratorService
from app.services.pdf_generator import PDFReportGenerator
from app.services.opening_analyzer import OpeningAnalyzerService, RepertoireAnalysisResult, OpeningGapInfo
from app.services.worksheet_generator import WorksheetPDFGenerator
from app.ui.components.chessboard_component import render_interactive_chessboard
from app.schemas.chess import GameAnalysisResult, AnalyzedMove, GamePhase, ErrorSeverity, TacticalTag

# ============================================================================
# СТИЛИ И КОНФИГУРАЦИЯ СТРАНИЦЫ (B2B SaaS Linear / Tailwind Slate Design System)
# ============================================================================
st.set_page_config(
    page_title="ChessCoach AI — B2B SaaS Dashboard",
    page_icon="♟️",
    layout="wide",
    initial_sidebar_state="expanded"
)

def render_html(html_str: str):
    """Безопасный нативный рендеринг HTML в Streamlit без искажения Markdown-парсером."""
    st.html(html_str)


# Определение темы оформления (Dark / Light)
theme_choice = st.session_state.get("app_theme_choice", "🌙 Темная")
is_dark = "Светлая" not in theme_choice
active_theme_str = "dark" if is_dark else "light"


def get_theme_css(is_dark: bool) -> str:
    """Генерация дизайн-системы Linear / Tailwind Slate для темной и светлой тем."""
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
        --tab-bg-active: rgba(59, 130, 246, 0.12);
        --tab-border-active: rgba(59, 130, 246, 0.3);
        --btn-sec-bg: #161F30;
        --btn-sec-border: rgba(255, 255, 255, 0.1);
        --btn-sec-text: #E5E7EB;
        --btn-sec-hover-bg: #1E293B;
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
        --badge-blunder-text: #F87171;
        --badge-blunder-border: rgba(239, 68, 68, 0.35);
        --badge-mistake-bg: rgba(245, 158, 11, 0.15);
        --badge-mistake-text: #FBBF24;
        --badge-mistake-border: rgba(245, 158, 11, 0.35);
        --badge-inaccuracy-bg: rgba(56, 189, 248, 0.15);
        --badge-inaccuracy-text: #38BDF8;
        --badge-inaccuracy-border: rgba(56, 189, 248, 0.35);
        --badge-win-bg: rgba(16, 185, 129, 0.15);
        --badge-win-text: #34D399;
        --badge-win-border: rgba(16, 185, 129, 0.3);
        --badge-loss-bg: rgba(239, 68, 68, 0.15);
        --badge-loss-text: #F87171;
        --badge-loss-border: rgba(239, 68, 68, 0.3);
        --badge-draw-bg: rgba(156, 163, 175, 0.15);
        --badge-draw-text: #9CA3AF;
        --badge-draw-border: rgba(156, 163, 175, 0.3);
        --kpi-blue-bg: rgba(59, 130, 246, 0.15);
        --kpi-blue-text: #60A5FA;
        --kpi-blue-border: rgba(59, 130, 246, 0.3);
        --kpi-green-bg: rgba(16, 185, 129, 0.15);
        --kpi-green-text: #34D399;
        --kpi-green-border: rgba(16, 185, 129, 0.3);
        --kpi-amber-bg: rgba(245, 158, 11, 0.15);
        --kpi-amber-text: #FBBF24;
        --kpi-amber-border: rgba(245, 158, 11, 0.3);
        --kpi-red-bg: rgba(239, 68, 68, 0.15);
        --kpi-red-text: #F87171;
        --kpi-red-border: rgba(239, 68, 68, 0.3);
        --tab-text-inactive: #9CA3AF;
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
        --text-subtle: #94A3B8;
        --code-bg: #F1F5F9;
        --shadow-card: 0 1px 3px rgba(0, 0, 0, 0.05), 0 1px 2px rgba(0, 0, 0, 0.03);
        --shadow-card-hover: 0 4px 12px rgba(0, 0, 0, 0.08);
        --tab-bg-active: rgba(59, 130, 246, 0.08);
        --tab-border-active: rgba(59, 130, 246, 0.3);
        --tab-text-inactive: #475569;
        --btn-sec-bg: #FFFFFF;
        --btn-sec-border: #CBD5E1;
        --btn-sec-text: #1E293B;
        --btn-sec-hover-bg: #F8FAFC;
        --alert-danger-bg: #FEF2F2;
        --alert-danger-border: #FECACA;
        --alert-danger-text: #7F1D1D;
        --alert-danger-title: #DC2626;
        --alert-info-bg: #EFF6FF;
        --alert-info-border: #BFDBFE;
        --alert-info-text: #1E3A8A;
        --alert-info-title: #2563EB;
        --alert-success-bg: #F0FDF4;
        --alert-success-border: #BBF7D0;
        --alert-success-text: #14532D;
        --alert-success-title: #16A34A;
        --badge-blunder-bg: #FEE2E2;
        --badge-blunder-text: #DC2626;
        --badge-blunder-border: #FCA5A5;
        --badge-mistake-bg: #FEF3C7;
        --badge-mistake-text: #D97706;
        --badge-mistake-border: #FCD34D;
        --badge-inaccuracy-bg: #E0F2FE;
        --badge-inaccuracy-text: #0284C7;
        --badge-inaccuracy-border: #BAE6FD;
        --badge-win-bg: #DCFCE7;
        --badge-win-text: #16A34A;
        --badge-win-border: #86EFAC;
        --badge-loss-bg: #FEE2E2;
        --badge-loss-text: #DC2626;
        --badge-loss-border: #FCA5A5;
        --badge-draw-bg: #F1F5F9;
        --badge-draw-text: #475569;
        --badge-draw-border: #CBD5E1;
        --kpi-blue-bg: #EFF6FF;
        --kpi-blue-text: #2563EB;
        --kpi-blue-border: #BFDBFE;
        --kpi-green-bg: #F0FDF4;
        --kpi-green-text: #16A34A;
        --kpi-green-border: #BBF7D0;
        --kpi-amber-bg: #FFFBEB;
        --kpi-amber-text: #D97706;
        --kpi-amber-border: #FDE68A;
        --kpi-red-bg: #FEF2F2;
        --kpi-red-text: #DC2626;
        --kpi-red-border: #FECACA;
        """

    return f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    :root {{
        {vars_css}
    }}

    /* Бесшовный заголовок Streamlit */
    header[data-testid="stHeader"] {{
        background: transparent !important;
    }}

    /* Базовая типографика и тема */
    html, body, [class*="css"], .stApp {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        background-color: var(--bg-page) !important;
        color: var(--text-main) !important;
    }}

    /* Стилизация заголовков Linear SaaS */
    h1 {{
        font-size: 1.5rem !important;
        font-weight: 700 !important;
        color: var(--text-main) !important;
        letter-spacing: -0.02em !important;
        margin-bottom: 0.5rem !important;
    }}
    h2 {{
        font-size: 1.25rem !important;
        font-weight: 600 !important;
        color: var(--text-main) !important;
        letter-spacing: -0.01em !important;
        margin-top: 0.75rem !important;
        margin-bottom: 0.5rem !important;
    }}
    h3 {{
        font-size: 1.1rem !important;
        font-weight: 600 !important;
        color: var(--text-main) !important;
        margin-bottom: 0.4rem !important;
    }}
    h4 {{
        font-size: 0.95rem !important;
        font-weight: 600 !important;
        color: var(--text-muted) !important;
        text-transform: uppercase !important;
        letter-spacing: 0.05em !important;
    }}

    /* Карточки и контейнеры */
    .saas-card {{
        background-color: var(--bg-card) !important;
        border: 1px solid var(--border-card) !important;
        border-radius: 12px;
        padding: 18px 20px;
        box-shadow: var(--shadow-card);
        margin-bottom: 14px;
        color: var(--text-main);
    }}

    .saas-card-subtle {{
        background-color: var(--bg-card-subtle) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: 10px;
        padding: 14px 16px;
        margin-bottom: 12px;
        color: var(--text-main);
    }}

    /* KPI блоки */
    .kpi-card {{
        background-color: var(--bg-card) !important;
        border: 1px solid var(--border-card) !important;
        border-radius: 12px;
        padding: 20px;
        box-shadow: var(--shadow-card);
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        min-height: 130px;
        transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
    }}
    .kpi-card:hover {{
        transform: translateY(-2px);
        border-color: var(--border-card-hover) !important;
        box-shadow: var(--shadow-card-hover);
    }}
    .kpi-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 8px;
    }}
    .kpi-title {{
        font-size: 0.8rem;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }}
    .kpi-icon {{
        font-size: 1.25rem;
        background: var(--bg-card-subtle);
        border: 1px solid var(--border-subtle);
        padding: 6px;
        border-radius: 8px;
    }}
    .kpi-value {{
        font-size: 1.85rem;
        font-weight: 700;
        color: var(--text-main);
        letter-spacing: -0.02em;
        line-height: 1.1;
        margin-bottom: 8px;
    }}
    .kpi-badge {{
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 600;
        width: fit-content;
    }}
    .kpi-badge-blue {{ background: var(--kpi-blue-bg); color: var(--kpi-blue-text); border: 1px solid var(--kpi-blue-border); }}
    .kpi-badge-green {{ background: var(--kpi-green-bg); color: var(--kpi-green-text); border: 1px solid var(--kpi-green-border); }}
    .kpi-badge-amber {{ background: var(--kpi-amber-bg); color: var(--kpi-amber-text); border: 1px solid var(--kpi-amber-border); }}
    .kpi-badge-red {{ background: var(--kpi-red-bg); color: var(--kpi-red-text); border: 1px solid var(--kpi-red-border); }}

    /* Бейджи ошибок и статусов */
    .badge-blunder {{
        background-color: var(--badge-blunder-bg);
        color: var(--badge-blunder-text);
        border: 1px solid var(--badge-blunder-border);
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.75rem;
        letter-spacing: 0.05em;
    }}
    .badge-mistake {{
        background-color: var(--badge-mistake-bg);
        color: var(--badge-mistake-text);
        border: 1px solid var(--badge-mistake-border);
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.75rem;
        letter-spacing: 0.05em;
    }}
    .badge-inaccuracy {{
        background-color: var(--badge-inaccuracy-bg);
        color: var(--badge-inaccuracy-text);
        border: 1px solid var(--badge-inaccuracy-border);
        padding: 3px 8px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.75rem;
        letter-spacing: 0.05em;
    }}

    /* Бейджи исхода партии */
    .badge-win {{
        background: var(--badge-win-bg);
        color: var(--badge-win-text);
        border: 1px solid var(--badge-win-border);
        padding: 3px 9px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.8rem;
    }}
    .badge-loss {{
        background: var(--badge-loss-bg);
        color: var(--badge-loss-text);
        border: 1px solid var(--badge-loss-border);
        padding: 3px 9px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.8rem;
    }}
    .badge-draw {{
        background: var(--badge-draw-bg);
        color: var(--badge-draw-text);
        border: 1px solid var(--badge-draw-border);
        padding: 3px 9px;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.8rem;
    }}

    /* Карточки алертов (Отчеты AI, хронические паттерны) */
    .alert-card-danger {{
        background: var(--alert-danger-bg) !important;
        border: 1px solid var(--alert-danger-border) !important;
        border-left: 4px solid #EF4444 !important;
        border-radius: 8px;
        padding: 14px 18px;
        margin-bottom: 12px;
        color: var(--alert-danger-text) !important;
        box-shadow: var(--shadow-card);
    }}
    .alert-card-info {{
        background: var(--alert-info-bg) !important;
        border: 1px solid var(--alert-info-border) !important;
        border-left: 4px solid #3B82F6 !important;
        border-radius: 8px;
        padding: 14px 18px;
        margin-bottom: 12px;
        color: var(--alert-info-text) !important;
        box-shadow: var(--shadow-card);
    }}
    .alert-card-success {{
        background: var(--alert-success-bg) !important;
        border: 1px solid var(--alert-success-border) !important;
        border-left: 4px solid #10B981 !important;
        border-radius: 8px;
        padding: 14px 18px;
        margin-bottom: 12px;
        color: var(--alert-success-text) !important;
        box-shadow: var(--shadow-card);
    }}

    /* Карточка домашнего задания */
    .homework-card {{
        background-color: var(--bg-card) !important;
        border: 1px solid var(--border-card) !important;
        border-radius: 12px;
        padding: 16px 18px;
        margin-bottom: 12px;
        box-shadow: var(--shadow-card);
    }}

    /* Стилизация вкладок Streamlit */
    div[data-baseweb="tab-list"] {{
        gap: 8px !important;
        border-bottom: 1px solid var(--border-divider) !important;
        padding-bottom: 4px !important;
    }}
    button[data-baseweb="tab"] {{
        font-family: 'Inter', sans-serif !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        color: var(--tab-text-inactive) !important;
        background: transparent !important;
        border: 1px solid transparent !important;
        border-radius: 8px !important;
        padding: 8px 16px !important;
        transition: all 0.15s ease !important;
    }}
    button[data-baseweb="tab"]:hover {{
        color: var(--text-main) !important;
        background: var(--bg-card-subtle) !important;
    }}
    button[data-baseweb="tab"][aria-selected="true"] {{
        color: #3B82F6 !important;
        background: var(--tab-bg-active) !important;
        border: 1px solid var(--tab-border-active) !important;
        font-weight: 700 !important;
    }}
    button[data-baseweb="tab"] p,
    button[data-baseweb="tab"] span,
    button[data-baseweb="tab"] div {{
        color: inherit !important;
        font-weight: inherit !important;
    }}

    /* Кнопки Streamlit */
    div.stButton > button[kind="primary"] {{
        background: linear-gradient(135deg, #3B82F6 0%, #2563EB 100%) !important;
        border: 1px solid rgba(96, 165, 250, 0.4) !important;
        color: #FFFFFF !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        box-shadow: 0 2px 10px rgba(37, 99, 235, 0.35) !important;
        transition: all 0.2s ease !important;
    }}
    div.stButton > button[kind="primary"]:hover {{
        background: linear-gradient(135deg, #2563EB 0%, #1D4ED8 100%) !important;
        box-shadow: 0 4px 14px rgba(37, 99, 235, 0.5) !important;
        transform: translateY(-1px) !important;
    }}
    div.stButton > button:not([kind="primary"]) {{
        background: var(--btn-sec-bg) !important;
        border: 1px solid var(--btn-sec-border) !important;
        color: var(--btn-sec-text) !important;
        border-radius: 8px !important;
        font-weight: 500 !important;
        transition: all 0.2s ease !important;
    }}
    div.stButton > button:not([kind="primary"]):hover {{
        border-color: var(--border-card-hover) !important;
        background: var(--btn-sec-hover-bg) !important;
        color: var(--text-main) !important;
    }}

    /* Кнопка скачивания PDF */
    div.stDownloadButton > button {{
        background: linear-gradient(135deg, #10B981 0%, #059669 100%) !important;
        border: 1px solid rgba(52, 211, 153, 0.4) !important;
        color: #FFFFFF !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 14px rgba(16, 185, 129, 0.35) !important;
        transition: all 0.2s ease !important;
    }}
    div.stDownloadButton > button:hover {{
        background: linear-gradient(135deg, #059669 0%, #047857 100%) !important;
        box-shadow: 0 6px 18px rgba(16, 185, 129, 0.5) !important;
        transform: translateY(-1px) !important;
    }}

    /* Кнопки-ссылки */
    a[data-testid="stLinkButton"] {{
        background: var(--btn-sec-bg) !important;
        border: 1px solid rgba(59, 130, 246, 0.3) !important;
        color: #3B82F6 !important;
        border-radius: 8px !important;
        font-weight: 500 !important;
        transition: all 0.15s ease !important;
    }}
    a[data-testid="stLinkButton"]:hover {{
        background: var(--tab-bg-active) !important;
        border-color: #3B82F6 !important;
        color: #2563EB !important;
    }}

    /* Боковая панель */
    section[data-testid="stSidebar"] {{
        background-color: var(--bg-sidebar) !important;
        border-right: 1px solid var(--border-divider) !important;
    }}

    /* Разделители */
    hr {{
        border-color: var(--border-divider) !important;
        margin: 1.2rem 0 !important;
    }}

    /* Код и плашки */
    .stCodeBlock, div[data-testid="stCode"] {{
        background-color: var(--code-bg) !important;
        border: 1px solid var(--border-card) !important;
        border-radius: 8px !important;
        color: var(--text-main) !important;
    }}

    /* Поля ввода и выпадающие списки (BaseWeb & React-Aria Streamlit) */
    div[data-testid="stTextInputRootElement"],
    div[data-testid="stTextInput"] > div > div,
    div[data-testid="stTextInputRootElement"] > div,
    div[data-baseweb="input"],
    div[data-baseweb="base-input"],
    div[data-baseweb="input"] > div,
    div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
    div[data-testid="stSelectbox"] div.react-aria-ComboBox > div,
    div[data-testid="stSelectbox"] div[class*="e1oobldh0"],
    div[data-testid="stSelectbox"] [role="combobox"] {{
        background-color: var(--bg-card) !important;
        border: 1px solid var(--border-card) !important;
        border-radius: 8px !important;
        color: var(--text-main) !important;
    }}
    div[data-testid="stTextInputField"],
    div[data-testid="stTextInput"] input,
    div[data-baseweb="input"] input,
    div[data-testid="stSelectbox"] input {{
        background-color: transparent !important;
        color: var(--text-main) !important;
    }}
    div[data-testid="stSelectbox"] span,
    div[data-testid="stSelectbox"] div,
    div[data-testid="stSelectbox"] p {{
        color: var(--text-main) !important;
    }}
    div[data-testid="stSelectbox"] svg {{
        fill: var(--text-muted) !important;
        color: var(--text-muted) !important;
    }}
    div.react-aria-Popover,
    ul.react-aria-ListBox,
    li.react-aria-ListBoxItem,
    div[data-baseweb="popover"],
    div[data-baseweb="menu"],
    ul[data-baseweb="menu"] {{
        background-color: var(--bg-card) !important;
        border: 1px solid var(--border-card) !important;
        color: var(--text-main) !important;
    }}
    li.react-aria-ListBoxItem,
    div[data-baseweb="popover"] li,
    div[data-baseweb="menu"] li {{
        background-color: var(--bg-card) !important;
        color: var(--text-main) !important;
    }}
    li.react-aria-ListBoxItem:hover,
    li.react-aria-ListBoxItem[data-hovered="true"],
    li.react-aria-ListBoxItem[data-focused="true"],
    div[data-baseweb="popover"] li:hover,
    div[data-baseweb="menu"] li:hover {{
        background-color: var(--bg-card-subtle) !important;
    }}
    div[data-testid="stWidgetLabel"] label, div[data-testid="stWidgetLabel"] p {{
        color: var(--text-main) !important;
        font-weight: 600 !important;
    }}
    div[data-testid="stRadio"] label p, div[data-testid="stRadio"] label span {{
        color: var(--text-main) !important;
    }}
    div[data-testid="stSlider"] [data-testid="stTickBarMin"],
    div[data-testid="stSlider"] [data-testid="stTickBarMax"] {{
        color: var(--text-muted) !important;
    }}
    div[data-testid="stCaptionContainer"], small {{
        color: var(--text-muted) !important;
    }}

    /* Жесткие компактные размеры контейнера доски (Anti-flicker & 13-14" laptop fit) */
    .chessboard-wrapper,
    div[data-testid="stCustomComponentV1"],
    iframe[title*="interactive_chessboard"] {{
        min-height: 420px !important;
        min-width: 420px !important;
        max-width: 420px !important;
        aspect-ratio: 1/1 !important;
        contain: layout !important;
        border: none !important;
        margin: 0 auto !important;
        display: block !important;
    }}
</style>
"""

render_html(get_theme_css(is_dark))


# Инициализация базы данных
init_db()

# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================
@st.cache_data
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
            "is_error": False,
            "error_severity": None,
            "error_cpl": 0,
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
                eval_text = "+0.2 • Дебютное развитие и борьба за центр"
            elif ply_idx <= 40:
                eval_text = "+0.4 • Позиционная борьба в миттельшпиле"
            else:
                eval_text = "+0.1 • Эндшпиль и реализация преимущества"
                
            plies.append({
                "ply": ply_idx,
                "san": f"{move_num}. {san}" if is_white else f"{move_num}... {san}",
                "uci": uci,
                "fen": board.fen(),
                "move_number": move_num,
                "is_white": is_white,
                "eval_text": eval_text,
                "is_error": bool(err),
                "error_severity": err.severity if err else None,
                "error_cpl": err.centipawn_loss if err else 0,
                "error": None
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
    render_html("""
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">
        <span style="font-size:1.8rem;">♟️</span>
        <div>
            <div style="font-size:1.2rem; font-weight:700; color:var(--text-main); letter-spacing:-0.02em;">ChessCoach AI</div>
        </div>
    </div>
    """)
    st.caption("Аналитический стек для профессиональных тренеров и шахматных академий")
    
    st.radio(
        "Тема оформления:",
        options=["🌙 Темная", "☀️ Светлая"],
        index=0 if is_dark else 1,
        horizontal=True,
        key="app_theme_choice"
    )
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

    if st.session_state.get("sync_error"):
        st.error(f"❌ {st.session_state['sync_error']}")

# Динамическая привязка и синхронизация имени ученика из сайдбара
student_display_name = student_name.strip() if student_name.strip() else st.session_state.get('student_name', 'Ученик')
st.session_state['student_name'] = student_display_name

# Сброс кэша отчетов при смене имени
if st.session_state.get("last_synced_student_name") != student_display_name:
    st.session_state["last_synced_student_name"] = student_display_name
    st.session_state.pop("cached_coach_report", None)
    st.session_state.pop("cached_parent_report", None)

# Автоматическое переключение ученика при смене платформы/никнейма
platform_key = f"{platform}_{username}"
if st.session_state.get("current_platform_key") != platform_key:
    st.session_state["current_platform_key"] = platform_key
    st.session_state.pop("cached_coach_report", None)
    st.session_state.pop("cached_parent_report", None)
    st.session_state.pop("sync_error", None)
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
                if student_name.strip():
                    parts = student_name.strip().split(" ", 1)
                    st_prof.first_name = parts[0]
                    st_prof.last_name = parts[1] if len(parts) > 1 else ""
                    session.commit()
                    st.session_state["student_name"] = student_name.strip()
                else:
                    st.session_state["student_name"] = f"{st_prof.first_name} {st_prof.last_name}".strip()

# Обработка синхронизации
if sync_btn:
    with st.spinner(f"Загрузка {games_count} партий с {platform.upper()} и анализ через Stockfish 19..."):
        student_id = get_or_create_student(name=student_name, username=username, platform=platform)
        st.session_state["student_id"] = student_id
        st.session_state["student_name"] = student_name
        st.session_state.pop("cached_coach_report", None)
        st.session_state.pop("cached_parent_report", None)
        
        t0 = time.perf_counter()
        try:
            res = sync_student_games(student_id=student_id, max_games=games_count)
            elapsed = time.perf_counter() - t0

            if isinstance(res, dict) and res.get("status") == "user_not_found":
                st.session_state["sync_error"] = "user not found"
                # Удаляем пустой созданный аккаунт при 404, чтобы база оставалась чистой
                with get_db_session() as session:
                    acc = session.execute(
                        select(StudentChessAccount).where(
                            StudentChessAccount.platform == platform,
                            StudentChessAccount.username == username
                        )
                    ).scalars().first()
                    if acc:
                        has_games = session.execute(select(Game.id).where(Game.student_profile_id == acc.student_profile_id)).first() is not None
                        if not has_games:
                            st_prof = session.get(StudentProfile, acc.student_profile_id)
                            session.delete(acc)
                            if st_prof:
                                session.delete(st_prof)
                st.session_state.pop("student_id", None)
            else:
                st.session_state.pop("sync_error", None)
                st.sidebar.success(f"Готово за {elapsed:.2f}с! Загружено: {res['new_games']}, Дубликатов: {res['skipped_duplicates']}")
        except (UserNotFoundError, httpx.HTTPStatusError) as exc:
            st.session_state["sync_error"] = "user not found"
            with get_db_session() as session:
                acc = session.execute(
                    select(StudentChessAccount).where(
                        StudentChessAccount.platform == platform,
                        StudentChessAccount.username == username
                    )
                ).scalars().first()
                if acc:
                    has_games = session.execute(select(Game.id).where(Game.student_profile_id == acc.student_profile_id)).first() is not None
                    if not has_games:
                        st_prof = session.get(StudentProfile, acc.student_profile_id)
                        session.delete(acc)
                        if st_prof:
                            session.delete(st_prof)
            st.session_state.pop("student_id", None)

        st.rerun()

# Получаем текущего ученика
current_student_id = st.session_state.get("student_id")
if not current_student_id:
    with get_db_session() as session:
        first_student = session.execute(select(StudentProfile)).scalars().first()
        if first_student:
            current_student_id = first_student.id
            st.session_state["student_id"] = current_student_id
            st.session_state["student_name"] = student_name.strip() if student_name.strip() else f"{first_student.first_name} {first_student.last_name}".strip()

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
# ГЛАВНЫЙ ЭКРАН (ШАПКА И 3 ВКЛАДКИ)
# ============================================================================
sync_error = st.session_state.get("sync_error")
if sync_error:
    st.error(f"❌ {sync_error}")

student_display_name = st.session_state.get('student_name', 'Ученик')
render_html(f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:18px; padding-bottom:12px; border-bottom:1px solid var(--border-divider);">
    <div>
        <h1 style="margin:0; font-size:1.6rem; font-weight:700; color:var(--text-main);">{student_display_name}</h1>
        <div style="color:var(--text-muted); font-size:0.85rem; margin-top:2px;">
            Игровой профиль: <span style="color:#3B82F6; font-weight:600;">@{username}</span> ({platform.upper()}) • Всего партий в базе: <span style="color:var(--text-main); font-weight:600;">{len(games_list)}</span>
        </div>
    </div>
    <div style="display:flex; gap:8px;">
        <span class="badge-win">🟢 Движок Stockfish 19 активен</span>
        <span class="badge-inaccuracy">⚡ Eager Sync Engine</span>
    </div>
</div>
""")

tab_board, tab_analytics, tab_ai = st.tabs([
    "📋 Список партий и Доска",
    "📊 Аналитика ученика",
    "🤖 Отчеты AI"
])

# ----------------------------------------------------------------------------
# ВКЛАДКА 1: СПИСОК ПАРТИЙ И ДОСКА (40% / 60% Grid Layout)
# ----------------------------------------------------------------------------
with tab_board:
    if not games_list:
        st.info("💡 Партии еще не загружены. Нажмите 'Синхронизировать и разобрать партии' в боковой панели!")
    else:
        col_list, col_board = st.columns([4, 6], gap="large")

        with col_list:
            if all_student_errors:
                worksheet_pdf = WorksheetPDFGenerator.generate_worksheet(
                    student_name=student_display_name,
                    error_events=all_student_errors,
                    games=games_list,
                    max_puzzles=4
                )
                st.download_button(
                    label="📥 Скачать листок задач А4 (Worksheet PDF)",
                    data=worksheet_pdf,
                    file_name=f"ChessWorksheet_{student_display_name.replace(' ', '_')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="btn_download_worksheet_tab1"
                )
                st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)

            st.markdown("### Партии ученика")
            
            game_options = {
                f"[{g.platform.upper()}] vs {g.opponent_username} ({g.result}) — Точность: {g.accuracy_score or 0}%": g.id
                for g in games_list
            }
            selected_label = st.selectbox(
                "Выберите партию для анализа:", 
                options=list(game_options.keys()),
                label_visibility="collapsed"
            )
            selected_game_id = game_options[selected_label]
            selected_game = next(g for g in games_list if g.id == selected_game_id)
            
            # Определение бейджей для метаданных партии
            res_str = selected_game.result or "*"
            is_win = (selected_game.student_color == 'white' and res_str == '1-0') or (selected_game.student_color == 'black' and res_str == '0-1')
            is_loss = (selected_game.student_color == 'white' and res_str == '0-1') or (selected_game.student_color == 'black' and res_str == '1-0')
            if is_win:
                result_badge = '<span class="badge-win">🏆 ПОБЕДА (1-0)</span>' if res_str == '1-0' else '<span class="badge-win">🏆 ПОБЕДА (0-1)</span>'
            elif is_loss:
                result_badge = '<span class="badge-loss">❌ ПОРАЖЕНИЕ (0-1)</span>' if res_str == '0-1' else '<span class="badge-loss">❌ ПОРАЖЕНИЕ (1-0)</span>'
            else:
                result_badge = '<span class="badge-draw">🤝 НИЧЬЯ (1/2-1/2)</span>'

            color_badge = "⚪ Белые" if selected_game.student_color == "white" else "⚫ Черные"
            acc_val = float(selected_game.accuracy_score or 0.0)
            
            # Аккуратная карточка метаданных партии в левой колонке (без отступов, вызывающих Markdown code blocks)
            render_html(f"""
            <div class="saas-card" style="margin-top:10px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                    <div style="display:flex; gap:8px; align-items:center;">
                        <span style="background:rgba(59,130,246,0.12); color:#3B82F6; border:1px solid rgba(59,130,246,0.25); padding:2px 8px; border-radius:6px; font-size:0.75rem; font-weight:600;">
                            ⚡ {selected_game.time_control or 'Standard'}
                        </span>
                        <span style="color:var(--text-muted); font-size:0.8rem; font-weight:500;">
                            {color_badge}
                        </span>
                    </div>
                    {result_badge}
                </div>

                <div style="margin-bottom:14px;">
                    <div style="color:var(--text-muted); font-size:0.8rem; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:2px;">Соперник</div>
                    <div style="font-size:1.1rem; font-weight:700; color:var(--text-main);">
                        {selected_game.opponent_username} 
                        <span style="color:var(--text-muted); font-size:0.85rem; font-weight:400;">({selected_game.opponent_rating or 'unrated'})</span>
                    </div>
                </div>

                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:12px;">
                    <div style="background:var(--bg-card-subtle); border:1px solid var(--border-subtle); border-radius:8px; padding:10px 12px;">
                        <div style="color:var(--text-muted); font-size:0.75rem; font-weight:600; text-transform:uppercase;">Точность CAPS</div>
                        <div style="font-size:1.35rem; font-weight:700; color:#10B981; margin-top:2px;">{acc_val}%</div>
                        <div style="background:var(--border-divider); border-radius:999px; height:4px; width:100%; margin-top:6px; overflow:hidden;">
                            <div style="background:#10B981; width:{min(100.0, acc_val)}%; height:100%; border-radius:999px;"></div>
                        </div>
                    </div>
                    <div style="background:var(--bg-card-subtle); border:1px solid var(--border-subtle); border-radius:8px; padding:10px 12px;">
                        <div style="color:var(--text-muted); font-size:0.75rem; font-weight:600; text-transform:uppercase;">Средний ACPL</div>
                        <div style="font-size:1.35rem; font-weight:700; color:#0284C7; margin-top:2px;">{selected_game.acpl or 0} <span style="font-size:0.8rem; color:var(--text-muted); font-weight:400;">CPL</span></div>
                        <div style="color:var(--text-muted); font-size:0.75rem; margin-top:6px;">Потеря центипешек</div>
                    </div>
                </div>

                <div style="display:flex; justify-content:space-between; align-items:center; background:var(--bg-card-subtle); border-radius:8px; padding:8px 12px; border:1px solid var(--border-subtle);">
                    <div style="display:flex; align-items:center; gap:6px;">
                        <span class="badge-blunder">BLUNDER: {selected_game.blunders_count}</span>
                    </div>
                    <div style="display:flex; align-items:center; gap:6px;">
                        <span class="badge-mistake">MISTAKE: {selected_game.mistakes_count}</span>
                    </div>
                    <div style="display:flex; align-items:center; gap:6px;">
                        <span class="badge-inaccuracy">INACCURACY: {selected_game.inaccuracies_count}</span>
                    </div>
                </div>
            </div>
            """)

            # Список ошибок в партии
            error_events = error_events_by_game.get(selected_game.id, [])
            if not error_events:
                render_html("""
                <div class="alert-card-success" style="margin-top:14px;">
                    <div style="font-weight:600; font-size:0.95rem;">🎉 Чистая гроссмейстерская игра!</div>
                    <div style="font-size:0.85rem; color:var(--text-muted); margin-top:3px;">В этой партии ученик не допустил критических ошибок и грубых зевков.</div>
                </div>
                """)
                active_error = None
            else:
                st.markdown(f"#### Критические моменты ({len(error_events)})")
                
                err_options = {
                    f"Ход {e.move_number} ({e.played_move_san}) — {e.severity.upper()} (-{e.centipawn_loss} CPL)": e
                    for e in error_events
                }
                selected_err_label = st.selectbox(
                    "Выберите ошибку для детального разбора:", 
                    options=list(err_options.keys()),
                    label_visibility="collapsed"
                )
                active_error: Optional[ChessErrorEvent] = err_options[selected_err_label]

                if active_error:
                    severity_badge = f"badge-{active_error.severity}"
                    theme_info = PuzzleGeneratorService.get_theme_info(active_error.tactical_tag or "tactical_blunder")
                    time_alert = f'<span class="badge-blunder" style="margin-left:6px;">🚨 ЦЕЙТНОТ ({active_error.clock_remaining_seconds}с)</span>' if active_error.is_time_trouble else ''
                    
                    render_html(f"""
                    <div class="saas-card" style="margin-top:10px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                            <span class="{severity_badge}">{active_error.severity.upper()}</span>
                            <span style="color:var(--text-muted); font-size:0.8rem; font-weight:500;">Фаза: {active_error.phase.capitalize()}</span>
                        </div>

                        <div style="font-size:0.9rem; color:var(--text-main); margin-bottom:8px;">
                            <b>Тактический паттерн:</b> 
                            <code style="background:var(--code-bg); color:#3B82F6; padding:2px 6px; border-radius:4px; border:1px solid var(--border-subtle);">{active_error.tactical_tag or 'tactical_blunder'}</code>
                        </div>

                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px;">
                            <div style="background:var(--alert-danger-bg); border:1px solid var(--alert-danger-border); border-radius:6px; padding:6px 10px;">
                                <div style="font-size:0.75rem; color:var(--text-muted);">Потеря оценки</div>
                                <div style="font-size:1.05rem; font-weight:700; color:var(--badge-blunder-text);">-{active_error.centipawn_loss} CPL</div>
                            </div>
                            <div style="background:var(--badge-mistake-bg); border:1px solid var(--badge-mistake-border); border-radius:6px; padding:6px 10px;">
                                <div style="font-size:0.75rem; color:var(--text-muted);">Падение шансов</div>
                                <div style="font-size:1.05rem; font-weight:700; color:var(--badge-mistake-text);">-{round((active_error.win_rate_drop or 0)*100, 1)}%</div>
                            </div>
                        </div>

                        <div style="font-size:0.8rem; color:var(--text-muted); margin-bottom:12px;">
                            Время на ход: {active_error.clock_remaining_seconds or 'N/A'}с {time_alert}
                        </div>

                        <div style="border-top:1px solid var(--border-divider); padding-top:10px;">
                            <div style="font-size:0.8rem; color:var(--text-muted); margin-bottom:4px;">🎯 Рекомендованный тренажер темы:</div>
                            <div style="font-weight:600; color:var(--text-main); font-size:0.88rem; margin-bottom:8px;">{theme_info['title']}</div>
                        </div>
                    </div>
                    """)

                    st.link_button(
                        f"🧩 Тренировать тему на Lichess", 
                        theme_info["url"], 
                        use_container_width=True
                    )

        with col_board:
            # Правая колонка: Центрированная интерактивная доска + контролы
            render_html("""
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                <h3 style="margin:0;">Интерактивная доска позиции</h3>
            </div>
            """)
            
            # Переключатель режимов доски (сегментированный)
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
                        theme=active_theme_str,
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

                    # Панель управления под доской
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

                    # Справочная плашка хода партии vs лучшего хода
                    render_html(f"""
                    <div style="display:flex; justify-content:space-around; background:var(--bg-card); border:1px solid var(--border-divider); border-radius:8px; padding:10px 14px; margin-top:8px;">
                        <div style="display:flex; align-items:center; gap:6px; font-size:0.85rem;">
                            <span style="color:#EF4444;">🔴 В партии:</span> 
                            <code style="background:var(--badge-blunder-bg); color:var(--badge-blunder-text); padding:2px 6px; border-radius:4px; font-weight:600;">{active_error.played_move_san}</code>
                        </div>
                        <div style="display:flex; align-items:center; gap:6px; font-size:0.85rem;">
                            <span style="color:#10B981;">🟢 Stockfish 19:</span> 
                            <code style="background:var(--badge-win-bg); color:var(--badge-win-text); padding:2px 6px; border-radius:4px; font-weight:600;">{active_error.best_move_san}</code>
                        </div>
                    </div>
                    """)

                    # Вывод обратной связи по сделанному ходу
                    fb = st.session_state.get(f"feedback_{err_id}")
                    if fb:
                        if fb["type"] == "blunder":
                            render_html(f"""
                            <div class="alert-card-danger" style="margin-top:10px;">
                                {fb['text']}
                            </div>
                            """)
                        elif fb["type"] == "best":
                            render_html(f"""
                            <div class="alert-card-success" style="margin-top:10px;">
                                {fb['text']}
                            </div>
                            """)
                        else:
                            render_html(f"""
                            <div class="alert-card-info" style="margin-top:10px;">
                                {fb['text']}
                            </div>
                            """)
                    else:
                        st.caption("✋ **Интерактивный тренажер:** перетащите фигуру на доске, чтобы проверить свой вариант защиты.")

                else:
                    render_html("""
                    <div class="alert-card-success">
                        🎉 В этой партии ошибок не обнаружено. Вы можете свободно тренироваться на доске!
                    </div>
                    """)
                    render_interactive_chessboard(
                        fen=chess.STARTING_FEN,
                        orientation=selected_game.student_color,
                        allow_moves=True,
                        theme=active_theme_str,
                        key=f"free_board_{selected_game.id}"
                    )

            # ================================================================
            # РЕЖИМ 2: ПРОСМОТР ВСЕЙ ПАРТИИ (FAST CLIENT-SIDE PREVIEW)
            # ================================================================
            else:
                plies = parse_game_plies(selected_game.pgn, error_events)

                # Клиентский предпросмотр ходов без перезапуска Streamlit (0ms latency, zero flicker)
                render_interactive_chessboard(
                    fen=plies[0]["fen"] if plies else chess.STARTING_FEN,
                    orientation=selected_game.student_color,
                    allow_moves=False,
                    plies=plies,
                    initial_ply=0,
                    theme=active_theme_str,
                    key=f"walk_board_{selected_game.id}"
                )

                # Глобальный слушатель клавиатуры для навигации стрелками с любой части страницы
                render_html("""
                <script>
                (function() {
                    if (!window._chessNavScriptLoaded) {
                        window._chessNavScriptLoaded = true;
                        window.addEventListener('keydown', function(e) {
                            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight' || e.key === 'Home' || e.key === 'End') {
                                const iframes = document.querySelectorAll('iframe[title*="interactive_chessboard"]');
                                iframes.forEach(function(f) {
                                    if (f && f.contentWindow) {
                                        f.contentWindow.postMessage({ type: 'nav_key', key: e.key }, '*');
                                    }
                                });
                            }
                        });
                    }
                })();
                </script>
                """)

                st.caption("⚡ **Мгновенная навигация:** используйте кнопки на доске, слайдер или стрелки на клавиатуре (← / →, Home / End). Фигуры перемещаются мгновенно на клиенте.")


# ----------------------------------------------------------------------------
# ВКЛАДКА 2: АНАЛИТИКА УЧЕНИКА (Dark Plotly & Modern KPI Cards)
# ----------------------------------------------------------------------------
with tab_analytics:
    st.markdown("### 📊 Аналитический срез пула партий")

    if not games_list:
        st.info("Нет данных для отображения аналитики.")
    else:
        total_g = len(games_list)
        wins_count = sum(1 for g in games_list if (g.student_color == 'white' and g.result == '1-0') or (g.student_color == 'black' and g.result == '0-1'))
        win_rate = round((wins_count / total_g) * 100, 1) if total_g > 0 else 0.0
        
        valid_acc = [float(g.accuracy_score) for g in games_list if g.accuracy_score is not None]
        avg_acc = round(sum(valid_acc) / len(valid_acc), 1) if valid_acc else 0.0
        
        valid_acpl = [g.acpl for g in games_list if g.acpl is not None]
        avg_acpl = int(sum(valid_acpl) / len(valid_acpl)) if valid_acpl else 0
        
        all_errors = all_student_errors
        time_trouble_errors = sum(1 for e in all_errors if e.is_time_trouble)

        # 4 Современных KPI Блока в стиле Linear / Tailwind Slate
        k1, k2, k3, k4 = st.columns(4)
        
        with k1:
            render_html(f"""
            <div class="kpi-card">
                <div class="kpi-header">
                    <span class="kpi-title">Винрейт ученика</span>
                    <span class="kpi-icon">🏆</span>
                </div>
                <div class="kpi-value">{win_rate}%</div>
                <div class="kpi-badge kpi-badge-green">
                    <span>Побед: {wins_count} из {total_g}</span>
                </div>
            </div>
            """)

        with k2:
            acc_badge_class = "kpi-badge-green" if avg_acc >= 85 else ("kpi-badge-blue" if avg_acc >= 75 else "kpi-badge-amber")
            acc_status = "Высокий уровень" if avg_acc >= 85 else ("Стабильная игра" if avg_acc >= 75 else "Нужна практика")
            render_html(f"""
            <div class="kpi-card">
                <div class="kpi-header">
                    <span class="kpi-title">Средняя точность</span>
                    <span class="kpi-icon">🎯</span>
                </div>
                <div class="kpi-value">{avg_acc}%</div>
                <div class="kpi-badge {acc_badge_class}">
                    <span>{acc_status}</span>
                </div>
            </div>
            """)

        with k3:
            acpl_status = "Гроссмейстерский" if avg_acpl <= 25 else ("Кандидат в мастера" if avg_acpl <= 45 else "Разрядный уровень")
            render_html(f"""
            <div class="kpi-card">
                <div class="kpi-header">
                    <span class="kpi-title">Средний ACPL</span>
                    <span class="kpi-icon">⚡</span>
                </div>
                <div class="kpi-value">{avg_acpl} <span style="font-size:0.9rem; color:var(--text-muted); font-weight:400;">CPL</span></div>
                <div class="kpi-badge kpi-badge-blue">
                    <span>{acpl_status}</span>
                </div>
            </div>
            """)

        with k4:
            tt_badge_class = "kpi-badge-red" if time_trouble_errors > 0 else "kpi-badge-green"
            render_html(f"""
            <div class="kpi-card">
                <div class="kpi-header">
                    <span class="kpi-title">Зевков под флагом</span>
                    <span class="kpi-icon">⏱️</span>
                </div>
                <div class="kpi-value">{time_trouble_errors}</div>
                <div class="kpi-badge {tt_badge_class}">
                    <span>Всего ошибок: {len(all_errors)}</span>
                </div>
            </div>
            """)

        st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)

        # Интерактивные графики Plotly с глубокой темной темой
        g_col1, g_col2 = st.columns(2, gap="medium")

        chart_text_color = '#F3F4F6' if is_dark else '#0F172A'
        chart_muted_color = '#9CA3AF' if is_dark else '#64748B'
        chart_grid_color = 'rgba(255, 255, 255, 0.06)' if is_dark else 'rgba(0, 0, 0, 0.06)'
        chart_line_color = 'rgba(255, 255, 255, 0.08)' if is_dark else 'rgba(0, 0, 0, 0.1)'

        with g_col1:
            st.markdown("#### ⏳ Ошибки по фазам партии")
            phase_counts = {"Дебют": 0, "Миттельшпиль": 0, "Эндшпиль": 0}
            for e in all_errors:
                if e.phase == "opening":
                    phase_counts["Дебют"] += 1
                elif e.phase == "middlegame":
                    phase_counts["Миттельшпиль"] += 1
                elif e.phase == "endgame":
                    phase_counts["Эндшпиль"] += 1

            # Построение Plotly столбчатого графика с скругленными краями и фиксированной шириной
            fig_phases = go.Figure(go.Bar(
                x=list(phase_counts.keys()),
                y=list(phase_counts.values()),
                width=0.35,
                marker=dict(
                    color='#3B82F6',
                    cornerradius=8,
                    line=dict(color='rgba(59, 130, 246, 0.4)', width=1)
                ),
                text=list(phase_counts.values()),
                textposition='outside',
                textfont=dict(color=chart_text_color, family='Inter', size=13),
                hovertemplate="<b>%{x}</b><br>Ошибок: %{y}<extra></extra>"
            ))
            fig_phases.update_layout(
                bargap=0.5,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(family='Inter', color=chart_muted_color),
                margin=dict(l=10, r=10, t=30, b=20),
                height=240,
                xaxis=dict(
                    showgrid=False,
                    tickfont=dict(color=chart_text_color, size=13, family='Inter'),
                    linecolor=chart_line_color
                ),
                yaxis=dict(
                    showgrid=True,
                    gridcolor=chart_grid_color,
                    tickfont=dict(color=chart_muted_color, size=11, family='Inter'),
                    zeroline=False
                )
            )
            st.plotly_chart(fig_phases, use_container_width=True, config={"displayModeBar": False})

        with g_col2:
            st.markdown("#### 🎯 Тактические слабости (Паттерны)")
            tag_counts = {}
            for e in all_errors:
                tag = e.tactical_tag or "tactical_blunder"
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
            
            if tag_counts:
                # Сортировка по возрастанию для правильного порядка в горизонтальном баре
                sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1])
                labels = [item[0] for item in sorted_tags]
                values = [item[1] for item in sorted_tags]

                # Ограничиваем толщину баров, чтобы 1-2 ошибки не раздувались в огромный блок
                bar_w = [0.25] * len(labels)
                chart_h = 180 if len(labels) <= 2 else 240

                fig_tags = go.Figure(go.Bar(
                    x=values,
                    y=labels,
                    orientation='h',
                    width=bar_w,
                    marker=dict(
                        color='#3B82F6' if len(labels) == 1 else values,
                        colorscale=[[0, '#60A5FA'], [1, '#2563EB']],
                        cornerradius=6,
                        line=dict(color='rgba(59, 130, 246, 0.4)', width=1),
                        showscale=False
                    ),
                    text=values,
                    textposition='outside',
                    textfont=dict(color=chart_text_color, family='Inter', size=12),
                    hovertemplate="Паттерн: <b>%{y}</b><br>Частота: %{x}<extra></extra>"
                ))
                fig_tags.update_layout(
                    bargap=0.6,
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    font=dict(family='Inter', color=chart_muted_color),
                    margin=dict(l=10, r=10, t=30, b=20),
                    height=chart_h,
                    xaxis=dict(
                        showgrid=True,
                        gridcolor=chart_grid_color,
                        tickfont=dict(color=chart_muted_color, size=11, family='Inter'),
                        zeroline=False
                    ),
                    yaxis=dict(
                        showgrid=False,
                        tickfont=dict(color=chart_text_color, size=12, family='Inter'),
                        linecolor=chart_line_color
                    )
                )
                st.plotly_chart(fig_tags, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("Нет зафиксированных тактических ошибок.")

        st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)
        st.divider()

        # ====================================================================
        # ДЕБЮТНОЕ ДЕРЕВО И ДЫРЫ В РЕПЕРТУАРЕ (REPERTOIRE GAP FINDER)
        # ====================================================================
        st.markdown("### ♟️ Дебютный репертуар и Дыры (Repertoire Gap Finder)")
        st.caption("Автоматический аудит дебютного дерева, выявление систематических пробелов и потери темпа в первых 10–12 ходах")

        repertoire_res = OpeningAnalyzerService.analyze_repertoire(
            games=games_list,
            student_name=student_display_name
        )

        # Главный тренерский инсайт
        if repertoire_res.repertoire_holes:
            holes_cnt = len(repertoire_res.repertoire_holes)
            render_html(f"""
            <div class="alert-card-danger" style="margin-top:10px; margin-bottom:16px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <span style="font-weight:700; font-size:1.0rem; color:var(--alert-danger-title);">
                        🚨 Обнаружены уязвимости в репертуаре ({holes_cnt})
                    </span>
                    <span class="badge-blunder">Требует внимания тренера</span>
                </div>
                <div style="font-size:0.92rem; color:var(--alert-danger-text); line-height:1.45;">
                    {repertoire_res.summary_insight}
                </div>
            </div>
            """)
        else:
            render_html(f"""
            <div class="alert-card-success" style="margin-top:10px; margin-bottom:16px;">
                <div style="font-weight:700; font-size:1.0rem; color:var(--alert-success-title); margin-bottom:4px;">
                    ✅ Дебютный репертуар надежен
                </div>
                <div style="font-size:0.92rem; color:var(--alert-success-text);">
                    {repertoire_res.summary_insight}
                </div>
            </div>
            """)

        # Сегментированный фильтр: За белых / За черных / Все дыры
        rep_tab_choice = st.radio(
            "Разрез дебютного репертуара:",
            options=[
                f"⚪ За Белых ({len(repertoire_res.white_openings)})",
                f"⚫ За Черных ({len(repertoire_res.black_openings)})",
                f"🚨 Все Дыры ({len(repertoire_res.repertoire_holes)})"
            ],
            horizontal=True,
            index=0 if repertoire_res.white_openings else (1 if repertoire_res.black_openings else 2)
        )

        if "Белых" in rep_tab_choice:
            current_openings = repertoire_res.white_openings
        elif "Черных" in rep_tab_choice:
            current_openings = repertoire_res.black_openings
        else:
            current_openings = repertoire_res.repertoire_holes

        if not current_openings:
            st.info("В выбранной категории дебютов не зафиксировано.")
        else:
            for op in current_openings:
                # Бейдж статуса
                if op.status == "Критическая дыра":
                    st_badge = '<span class="badge-blunder">🚨 Критическая дыра</span>'
                    card_border = "rgba(239, 68, 68, 0.3)" if is_dark else "#FCA5A5"
                elif op.status == "Требует разбора":
                    st_badge = '<span class="badge-mistake">⚠️ Требует разбора</span>'
                    card_border = "rgba(245, 158, 11, 0.3)" if is_dark else "#FCD34D"
                else:
                    st_badge = '<span class="badge-win">✅ Надежно</span>'
                    card_border = "rgba(16, 185, 129, 0.25)" if is_dark else "#86EFAC"

                color_icon = "⚪ Белые" if op.color == "white" else "⚫ Черные"
                wr_color = '#10B981' if op.win_rate >= 50 else ('#F59E0B' if op.win_rate >= 40 else '#EF4444')
                err_color = '#EF4444' if op.early_blunders_count > 0 else ('#F59E0B' if op.early_errors_count > 0 else '#10B981')
                
                # Рендеринг карточки дебюта
                render_html(f"""
                <div class="saas-card" style="border: 1px solid {card_border}; margin-bottom:12px;">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">
                        <div>
                            <div style="display:flex; align-items:center; gap:8px;">
                                <span style="background:rgba(59,130,246,0.15); color:#3B82F6; border:1px solid rgba(59,130,246,0.3); padding:2px 8px; border-radius:6px; font-size:0.8rem; font-weight:700;">
                                    {op.eco}
                                </span>
                                <span style="font-size:1.08rem; font-weight:700; color:var(--text-main);">
                                    {op.name}
                                </span>
                            </div>
                            <div style="color:var(--text-muted); font-size:0.82rem; margin-top:4px;">
                                Цвет фигур: <span style="color:var(--text-main); font-weight:500;">{color_icon}</span>
                            </div>
                        </div>
                        <div>
                            {st_badge}
                        </div>
                    </div>

                    <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:10px; margin-bottom:12px;">
                        <div style="background:var(--bg-card-subtle); border:1px solid var(--border-subtle); border-radius:8px; padding:8px 12px;">
                            <div style="color:var(--text-muted); font-size:0.75rem; text-transform:uppercase; font-weight:600;">Партий</div>
                            <div style="font-size:1.2rem; font-weight:700; color:var(--text-main); margin-top:2px;">{op.games_count}</div>
                            <div style="color:var(--text-muted); font-size:0.75rem; margin-top:2px;">
                                <span style="color:#10B981;">{op.wins}В</span> • 
                                <span style="color:var(--text-muted);">{op.draws}Н</span> • 
                                <span style="color:#EF4444;">{op.losses}П</span>
                            </div>
                        </div>

                        <div style="background:var(--bg-card-subtle); border:1px solid var(--border-subtle); border-radius:8px; padding:8px 12px;">
                            <div style="color:var(--text-muted); font-size:0.75rem; text-transform:uppercase; font-weight:600;">Винрейт</div>
                            <div style="font-size:1.2rem; font-weight:700; color:{wr_color}; margin-top:2px;">
                                {op.win_rate}%
                            </div>
                            <div style="background:var(--border-divider); border-radius:999px; height:4px; width:100%; margin-top:6px; overflow:hidden;">
                                <div style="background:{wr_color}; width:{min(100.0, op.win_rate)}%; height:100%;"></div>
                            </div>
                        </div>

                        <div style="background:var(--bg-card-subtle); border:1px solid var(--border-subtle); border-radius:8px; padding:8px 12px;">
                            <div style="color:var(--text-muted); font-size:0.75rem; text-transform:uppercase; font-weight:600;">ACPL Дебюта</div>
                            <div style="font-size:1.2rem; font-weight:700; color:#0284C7; margin-top:2px;">
                                {op.opening_acpl} <span style="font-size:0.75rem; color:var(--text-muted); font-weight:400;">CPL</span>
                            </div>
                            <div style="color:var(--text-muted); font-size:0.75rem; margin-top:2px;">Точность: {op.opening_accuracy}%</div>
                        </div>

                        <div style="background:var(--bg-card-subtle); border:1px solid var(--border-subtle); border-radius:8px; padding:8px 12px;">
                            <div style="color:var(--text-muted); font-size:0.75rem; text-transform:uppercase; font-weight:600;">Ранние ошибки (1-15)</div>
                            <div style="font-size:1.2rem; font-weight:700; color:{err_color}; margin-top:2px;">
                                {op.early_errors_count}
                            </div>
                            <div style="color:var(--text-muted); font-size:0.75rem; margin-top:2px;">Грубых зевков: {op.early_blunders_count}</div>
                        </div>
                    </div>

                    <div style="background:var(--bg-card-subtle); border-radius:8px; padding:10px 14px; border:1px solid var(--border-subtle); font-size:0.88rem; line-height:1.45; color:var(--text-main);">
                        <span style="color:#3B82F6; font-weight:600;">💡 Подсказка тренеру:</span> {op.coach_tip}
                    </div>
                </div>
                """)


# ----------------------------------------------------------------------------
# ВКЛАДКА 3: ОТЧЕТЫ AI И ЭКСПОРТ (Сегментированный переключатель ролей)
# ----------------------------------------------------------------------------
with tab_ai:
    # Переключатель ролей прямо над отчетом в виде сегментированного таба
    r_col1, r_col2 = st.columns([6, 4])
    with r_col1:
        st.markdown("### 🤖 Интеллектуальные отчеты AI")
        st.caption("Генерация экспертного анализа партий для тренерского штаба и родителей")
    with r_col2:
        tab_ai_role = st.radio(
            "Аудитория отчета:",
            options=["👔 Кабинет тренера", "👨‍👩‍👦 Отчет для родителей"],
            horizontal=True,
            index=0
        )
    
    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    if not games_list:
        st.info("Сначала загрузите партии ученика в боковой панели.")
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

        c_act1, c_act2, c_act3 = st.columns([1, 1, 1], gap="medium")
        with c_act1:
            gen_report_btn = st.button("✨ Сгенерировать актуальный AI-отчет", type="primary", use_container_width=True)

        if all_student_errors:
            worksheet_pdf_tab3 = WorksheetPDFGenerator.generate_worksheet(
                student_name=student_display_name,
                error_events=all_student_errors,
                games=games_list,
                max_puzzles=4
            )
            with c_act3:
                st.download_button(
                    label="📥 Скачать листок задач А4 (PDF)",
                    data=worksheet_pdf_tab3,
                    file_name=f"ChessWorksheet_{student_display_name.replace(' ', '_')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="btn_download_worksheet_tab3"
                )

        if gen_report_btn or "cached_coach_report" in st.session_state:
            reporter = LLMReporterService()
            
            if gen_report_btn:
                with st.spinner("Анализ партий и компиляция экспертного отчета..."):
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
                with c_act2:
                    st.download_button(
                        label="📄 Скачать PDF-отчет для родителей",
                        data=pdf_bytes,
                        file_name=f"ChessCoach_Report_{parent_rep.child_name.replace(' ', '_')}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )

            st.divider()

            # ============================================================
            # ВАРИАНТ 1: РЕЖИМ ТРЕНЕРА
            # ============================================================
            if tab_ai_role == "👔 Кабинет тренера" and coach_rep:
                st.markdown(f"#### 👔 Глубокий аудит для тренера: {coach_rep.student_name}")
                
                # Executive summary в акцентной карточке
                render_html(f"""
                <div class="alert-card-info">
                    <div style="font-weight:700; font-size:1.0rem; margin-bottom:4px; color:var(--alert-info-title);">📋 Резюме игры:</div>
                    <div style="font-size:0.92rem; line-height:1.5; color:var(--alert-info-text);">{coach_rep.executive_summary}</div>
                </div>
                """)
                
                st.markdown("#### 🚨 Хронические паттерны ошибок:")
                valid_patterns = [
                    p for p in coach_rep.systemic_patterns
                    if not (
                        p.frequency.strip().startswith("0 ")
                        or "0 ошибок" in p.frequency
                        or p.frequency.strip().startswith("0%")
                        or p.frequency.strip() == "0"
                    )
                ]
                if valid_patterns:
                    for p in valid_patterns:
                        render_html(f"""
                        <div class="alert-card-danger">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                                <span style="font-weight:700; font-size:0.98rem; color:var(--alert-danger-title);">
                                    [{p.severity.upper()}] {p.title}
                                </span>
                                <span class="badge-blunder">
                                    {p.frequency}
                                </span>
                            </div>
                            <div style="font-size:0.88rem; color:var(--alert-danger-text); line-height:1.4;">{p.description}</div>
                        </div>
                        """)
                else:
                    render_html("""
                    <div class="alert-card-success" style="margin-bottom:12px;">
                        <div style="font-weight:700; font-size:0.98rem; color:var(--alert-success-title); margin-bottom:4px;">
                            ✅ Хронических уязвимостей не выявлено
                        </div>
                        <div style="font-size:0.88rem; color:var(--alert-success-text);">
                            Критичных паттернов ошибок не выявлено. Ученик провел период очень чисто.
                        </div>
                    </div>
                    """)

                render_html(f"""
                <div class="saas-card" style="margin-top:12px;">
                    <div style="color:var(--text-muted); font-size:0.8rem; text-transform:uppercase; letter-spacing:0.04em;">Оценка игры под флагом</div>
                    <div style="font-size:1.0rem; font-weight:600; color:var(--text-main); margin-top:3px;">⏱️ {coach_rep.time_trouble_verdict}</div>
                </div>
                """)
                
                st.markdown("#### 🎯 Рекомендованный план тренировок:")
                for idx, lesson in enumerate(coach_rep.next_lessons_plan, 1):
                    render_html(f"""
                    <div class="saas-card-subtle" style="display:flex; align-items:flex-start; gap:10px;">
                        <span style="background:rgba(59,130,246,0.15); color:#3B82F6; width:24px; height:24px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:0.8rem; font-weight:700; flex-shrink:0;">
                            {idx}
                        </span>
                        <span style="font-size:0.92rem; color:var(--text-main); padding-top:2px;">{lesson}</span>
                    </div>
                    """)

                st.divider()
                st.markdown("#### 🧩 Домашнее задание (Lichess Puzzle Database)")
                st.caption("Персональные интерактивные задачи под выявленные уязвимости ученика:")
                
                puzzle_recs = PuzzleGeneratorService.generate_recommendations(stats.top_tactical_weaknesses)
                for rec in puzzle_recs:
                    render_html(f"""
                    <div class="homework-card">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                            <div style="font-weight:700; font-size:1.0rem; color:var(--text-main);">📌 {rec['title']}</div>
                            <span class="kpi-badge kpi-badge-blue">{rec['puzzles_recommended']} задач</span>
                        </div>
                        <div style="color:var(--text-muted); font-size:0.88rem; line-height:1.4; margin-bottom:8px;">{rec['description']}</div>
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <span style="color:var(--badge-blunder-text); font-size:0.8rem; font-weight:500;">Причина: {rec['error_frequency']}</span>
                        </div>
                    </div>
                    """)
                    st.link_button(
                        f"👉 Начать тренировку темы '{rec['title'].split('(')[0].strip()}' на Lichess", 
                        rec["url"],
                        use_container_width=True
                    )

                st.divider()
                st.markdown("#### 📋 Экспорт в мессенджер тренера")
                patterns_export = "\n".join([f"- {p.title} ({p.frequency})" for p in valid_patterns]) if valid_patterns else "- Критичных паттернов ошибок не выявлено. Ученик провел период очень чисто."
                coach_text = (
                    f"♟️ АУДИТ ИГРЫ: {coach_rep.student_name}\n\n"
                    f"{coach_rep.executive_summary}\n\n"
                    f"ПАТТЕРНЫ:\n{patterns_export}\n\n"
                    f"ЗАДАЧИ НА ДОМ (LICHESS):\n" + "\n".join([f"- {r['title']}: {r['url']}" for r in puzzle_recs]) + "\n\n"
                    f"ПЛАН ЗАНЯТИЙ:\n" + "\n".join([f"- {l}" for l in coach_rep.next_lessons_plan])
                )
                st.code(coach_text, language="markdown")

            # ============================================================
            # ВАРИАНТ 2: РЕЖИМ РОДИТЕЛЯ
            # ============================================================
            elif tab_ai_role == "👨‍👩‍👦 Отчет для родителей" and parent_rep:
                st.markdown(f"#### 👨‍👩‍👦 Презентабельный отчет для родителей: {parent_rep.child_name}")
                
                render_html(f"""
                <div class="alert-card-success">
                    <div style="font-weight:700; font-size:1.0rem; margin-bottom:4px; color:var(--alert-success-title);">🌟 Успехи недели:</div>
                    <div style="font-size:0.92rem; line-height:1.5; color:var(--alert-success-text);">{parent_rep.greeting_and_summary}</div>
                </div>
                """)
                
                st.markdown("#### 🏆 Главные достижения ребенка:")
                for a in parent_rep.achievements:
                    render_html(f"""
                    <div class="saas-card-subtle" style="display:flex; align-items:center; gap:8px;">
                        <span style="color:#10B981; font-size:1.1rem;">✅</span>
                        <span style="font-size:0.92rem; color:var(--text-main);">{a}</span>
                    </div>
                    """)

                st.markdown("#### 🌱 Зоны мягкого роста:")
                for g in parent_rep.areas_for_growth:
                    render_html(f"""
                    <div class="saas-card-subtle" style="display:flex; align-items:center; gap:8px;">
                        <span style="color:#3B82F6; font-size:1.1rem;">🔹</span>
                        <span style="font-size:0.92rem; color:var(--text-main);">{g}</span>
                    </div>
                    """)

                render_html(f"""
                <div class="alert-card-info" style="margin-top:14px;">
                    <div style="font-weight:700; font-size:0.95rem; margin-bottom:4px; color:var(--alert-info-title);">💡 Совет тренера для родителей дома:</div>
                    <div style="font-size:0.9rem; line-height:1.4; color:var(--alert-info-text);">{parent_rep.home_support_advice}</div>
                </div>
                """)

                st.divider()
                st.markdown("#### 📱 Готовое сообщение для отправки в WhatsApp")
                parent_text = (
                    f"{parent_rep.greeting_and_summary}\n\n"
                    f"🏆 Достижения:\n" + "\n".join([f"✅ {a}" for a in parent_rep.achievements]) + "\n\n"
                    f"🌱 Зоны роста:\n" + "\n".join([f"🔹 {g}" for g in parent_rep.areas_for_growth]) + "\n\n"
                    f"💡 Совет для дома:\n{parent_rep.home_support_advice}"
                )
                st.code(parent_text, language="text")
