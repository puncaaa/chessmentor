import io
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

import chess
import chess.svg
from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas

from app.models.chess import Game, ChessErrorEvent
from app.services.pdf_generator import FONT_REGULAR, FONT_BOLD, draw_pawn_logo, draw_pill_badge, wrap_text
from app.services.puzzle_service import PuzzleGeneratorService


class WorksheetPDFGenerator:
    """
    Генератор персональных PDF-листков шахматных задач (Worksheet A4)
    на основе реальных ошибок ученика в недавних партиях.
    """

    @classmethod
    def select_worksheet_puzzles(
        cls,
        error_events: List[ChessErrorEvent],
        games: List[Game],
        max_puzzles: int = 4
    ) -> List[Dict[str, Any]]:
        """
        Отбор 4-6 самых показательных критических ошибок (зевки и тактические удары)
        с FEN строго ДО совершенной ошибки.
        """
        games_by_id = {g.id: g for g in games}
        candidates = []

        for e in error_events:
            # Пропускаем ошибки без FEN до хода или без лучшего хода
            if not e.fen_before or not e.best_move_san:
                continue

            game = games_by_id.get(e.game_id)
            if not game:
                continue

            # Приоритет: сначала грубые зевки (blunder), затем ошибки (mistake)
            priority = 0
            if e.severity == "blunder":
                priority += 100
            elif e.severity == "mistake":
                priority += 50
            else:
                priority += 10

            priority += min(50, e.centipawn_loss // 10)

            candidates.append({
                "error": e,
                "game": game,
                "priority": priority
            })

        # Сортировка по приоритету (наиболее яркие зевки и тактические моменты)
        candidates.sort(key=lambda x: x["priority"], reverse=True)

        selected = candidates[:max_puzzles]

        # Если ошибок меньше требуемого — возвращаем сколько есть
        return selected

    @classmethod
    def generate_worksheet(
        cls,
        student_name: str,
        error_events: List[ChessErrorEvent],
        games: List[Game],
        max_puzzles: int = 4,
        date_str: Optional[str] = None
    ) -> bytes:
        """
        Генерация двустраничного PDF-документа:
        - Стр 1: Задачник для ученика с векторными диаграммами и местом для ответа.
        - Стр 2: Лист ответов для тренера с оценками движка и тактическими идеями.
        """
        if not date_str:
            now = datetime.now()
            months = [
                "", "января", "февраля", "марта", "апреля", "мая", "июня",
                "июля", "августа", "сентября", "октября", "ноября", "декабря"
            ]
            date_str = f"{now.day} {months[now.month]} {now.year} г."

        selected_items = cls.select_worksheet_puzzles(error_events, games, max_puzzles=max_puzzles)

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        page_w, page_h = A4

        # ====================================================================
        # СТРАНИЦА 1: ПЕРСОНАЛЬНЫЙ ЗАДАЧНИК ДЛЯ УЧЕНИКА
        # ====================================================================
        cls._draw_student_page(
            c=c,
            page_w=page_w,
            page_h=page_h,
            student_name=student_name,
            date_str=date_str,
            selected_items=selected_items
        )

        c.showPage()

        # ====================================================================
        # СТРАНИЦА 2: ЛИСТ РЕШЕНИЙ И ПОЯСНЕНИЙ ДЛЯ ТРЕНЕРА
        # ====================================================================
        cls._draw_solutions_page(
            c=c,
            page_w=page_w,
            page_h=page_h,
            student_name=student_name,
            date_str=date_str,
            selected_items=selected_items
        )

        c.save()
        buffer.seek(0)
        return buffer.getvalue()

    @classmethod
    def _draw_student_page(
        cls,
        c: canvas.Canvas,
        page_w: float,
        page_h: float,
        student_name: str,
        date_str: str,
        selected_items: List[Dict[str, Any]]
    ):
        """Отрисовка страницы с задачами для ученика."""
        # Фоновая шапка
        c.setFillColor(colors.HexColor("#0B0F17"))
        c.rect(0, page_h - 90, page_w, 90, fill=True, stroke=False)

        # Логотип
        draw_pawn_logo(c, 40, page_h - 68, size=38)

        # Заголовок и метаданные
        c.setFillColor(colors.white)
        c.setFont(FONT_BOLD, 17)
        c.drawString(90, page_h - 45, f"Персональный задачник: {student_name}")

        c.setFillColor(colors.HexColor("#94A3B8"))
        c.setFont(FONT_REGULAR, 9)
        c.drawString(90, page_h - 60, "ChessCoach AI • Анализ недавних партий ученика")
        c.drawRightString(page_w - 40, page_h - 45, date_str)

        # Разделительная полоска
        c.setStrokeColor(colors.HexColor("#3B82F6"))
        c.setLineWidth(2)
        c.line(0, page_h - 90, page_w, page_h - 90)

        # Инструкция для ученика
        c.setFillColor(colors.HexColor("#1E293B"))
        c.roundRect(40, page_h - 130, page_w - 80, 32, 6, fill=True, stroke=False)
        c.setFillColor(colors.HexColor("#38BDF8"))
        c.setFont(FONT_BOLD, 9.5)
        c.drawString(52, page_h - 113, "ЦЕЛЬ ЗАДАЧНИКА:")
        c.setFillColor(colors.HexColor("#F8FAFC"))
        c.setFont(FONT_REGULAR, 9)
        c.drawString(160, page_h - 113, "Найди сильнейший ход движка, который ты упустил в реальной партии!")

        # Если задач нет
        if not selected_items:
            c.setFillColor(colors.HexColor("#334155"))
            c.setFont(FONT_REGULAR, 12)
            c.drawString(40, page_h - 180, "Поздравляем! В недавних партиях ученика нет критических зевков.")
            return

        # Сетка 2x2 для 4 задач (или 2x3)
        # Координаты колонок
        col_w = (page_w - 80 - 20) / 2  # 247.6 pt
        row_h = 310  # высота ячейки задачи

        col_x = [40, 40 + col_w + 20]
        row_y = [page_h - 145 - row_h, page_h - 145 - row_h * 2]

        for idx, item in enumerate(selected_items[:4]):
            ci = idx % 2
            ri = idx // 2
            x = col_x[ci]
            y = row_y[ri]

            cls._draw_puzzle_card(
                c=c,
                x=x,
                y=y,
                w=col_w,
                h=row_h - 15,
                puzzle_num=idx + 1,
                item=item
            )

        # Подвал страницы
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.setLineWidth(0.8)
        c.line(40, 35, page_w - 40, 35)

        c.setFillColor(colors.HexColor("#64748B"))
        c.setFont(FONT_REGULAR, 8)
        c.drawString(40, 22, "ChessCoach AI — Персональные тренировочные материалы")
        c.drawRightString(page_w - 40, 22, "Страница 1 из 2")

    @classmethod
    def _draw_puzzle_card(
        cls,
        c: canvas.Canvas,
        x: float,
        y: float,
        w: float,
        h: float,
        puzzle_num: int,
        item: Dict[str, Any]
    ):
        """Отрисовка карточки отдельной задачи с векторной доской."""
        err: ChessErrorEvent = item["error"]
        game: Game = item["game"]

        # Фон карточки
        c.setFillColor(colors.HexColor("#F8FAFC"))
        c.roundRect(x, y, w, h, 8, fill=True, stroke=False)
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.setLineWidth(1)
        c.roundRect(x, y, w, h, 8, fill=False, stroke=True)

        # Номер задачи
        draw_pill_badge(c, x + 12, y + h - 22, f"Задача {puzzle_num}", "#2563EB", "#FFFFFF", font_size=8)

        # Индикатор чей ход
        board = chess.Board(err.fen_before)
        is_white_turn = board.turn == chess.WHITE
        turn_text = "Ход белых" if is_white_turn else "Ход черных"
        turn_bg = "#E2E8F0" if is_white_turn else "#334155"
        turn_fg = "#0F172A" if is_white_turn else "#F8FAFC"
        draw_pill_badge(c, x + w - 75, y + h - 22, turn_text, turn_bg, turn_fg, font_size=7.5)

        # Отрисовка шахматной диаграммы через chess.svg + svglib
        board_size = 148
        student_color = chess.WHITE if game.student_color == "white" else chess.BLACK
        
        try:
            svg_data = chess.svg.board(
                board=board,
                orientation=student_color,
                size=board_size,
                coordinates=True
            )
            drawing = svg2rlg(io.StringIO(svg_data))
            if drawing:
                scale = board_size / drawing.width
                drawing.scale(scale, scale)
                drawing.width = board_size
                drawing.height = board_size
                
                # Центрирование доски по горизонтали
                bx = x + (w - board_size) / 2
                by = y + h - 35 - board_size
                renderPDF.draw(drawing, c, bx, by)
        except Exception:
            # Fallback если парсер svg выдал сбой
            c.setFillColor(colors.HexColor("#E2E8F0"))
            c.rect(x + 20, y + h - 35 - board_size, board_size, board_size, fill=True, stroke=True)
            c.setFillColor(colors.HexColor("#475569"))
            c.setFont(FONT_REGULAR, 8)
            c.drawCentredString(x + w / 2, y + h - 35 - board_size / 2, "Диаграмма позиции")

        # Информация о партии под доской
        text_y = y + h - 45 - board_size
        c.setFillColor(colors.HexColor("#0F172A"))
        c.setFont(FONT_BOLD, 8.5)
        c.drawString(x + 12, text_y, f"vs {game.opponent_username} ({game.opponent_rating or 'unrated'})")

        c.setFillColor(colors.HexColor("#475569"))
        c.setFont(FONT_REGULAR, 8)
        text_y -= 13
        c.drawString(x + 12, text_y, f"Ход {err.move_number} • Фаза: {err.phase.capitalize()}")

        text_y -= 13
        c.setFillColor(colors.HexColor("#DC2626"))
        c.setFont(FONT_REGULAR, 8)
        c.drawString(x + 12, text_y, f"Твой ход в партии: {err.played_move_san} ({err.severity.upper()})")

        # Линия для ответа ученика
        text_y -= 20
        c.setFillColor(colors.HexColor("#1E293B"))
        c.setFont(FONT_BOLD, 8.5)
        c.drawString(x + 12, text_y, "Твой ответ:")

        c.setStrokeColor(colors.HexColor("#94A3B8"))
        c.setLineWidth(0.8)
        c.line(x + 70, text_y - 1, x + w - 12, text_y - 1)

    @classmethod
    def _draw_solutions_page(
        cls,
        c: canvas.Canvas,
        page_w: float,
        page_h: float,
        student_name: str,
        date_str: str,
        selected_items: List[Dict[str, Any]]
    ):
        """Отрисовка страницы с ответами и пояснениями для тренера."""
        # Фоновая шапка
        c.setFillColor(colors.HexColor("#0B0F17"))
        c.rect(0, page_h - 90, page_w, 90, fill=True, stroke=False)

        draw_pawn_logo(c, 40, page_h - 68, size=38)

        c.setFillColor(colors.white)
        c.setFont(FONT_BOLD, 17)
        c.drawString(90, page_h - 45, "Ответы и решения (Для тренера)")

        c.setFillColor(colors.HexColor("#94A3B8"))
        c.setFont(FONT_REGULAR, 9)
        c.drawString(90, page_h - 60, f"Ключ проверки решений • Ученик: {student_name}")
        c.drawRightString(page_w - 40, page_h - 45, date_str)

        # Красная разделительная линия (секретно для тренера)
        c.setStrokeColor(colors.HexColor("#EF4444"))
        c.setLineWidth(2)
        c.line(0, page_h - 90, page_w, page_h - 90)

        # Заметка для тренера
        c.setFillColor(colors.HexColor("#FEF2F2"))
        c.roundRect(40, page_h - 130, page_w - 80, 30, 6, fill=True, stroke=False)
        c.setFillColor(colors.HexColor("#DC2626"))
        c.setFont(FONT_BOLD, 9)
        c.drawString(52, page_h - 113, "СЛУЖЕБНЫЙ МАТЕРИАЛ:")
        c.setFillColor(colors.HexColor("#7F1D1D"))
        c.setFont(FONT_REGULAR, 8.5)
        c.drawString(185, page_h - 113, "Используйте для быстрой проверки выполненного домашнего задания.")

        if not selected_items:
            c.setFillColor(colors.HexColor("#334155"))
            c.setFont(FONT_REGULAR, 12)
            c.drawString(40, page_h - 180, "Нет задач для отображения.")
            return

        # Список карточек решений (по одной на строку, высота 135 pt)
        card_w = page_w - 80
        card_h = 140
        start_y = page_h - 150

        for idx, item in enumerate(selected_items[:4]):
            err: ChessErrorEvent = item["error"]
            game: Game = item["game"]
            y = start_y - (idx + 1) * card_h + 10

            theme_info = PuzzleGeneratorService.get_theme_info(err.tactical_tag or "tactical_blunder")

            # Карточка решения
            c.setFillColor(colors.HexColor("#F8FAFC"))
            c.roundRect(40, y, card_w, card_h - 15, 8, fill=True, stroke=False)
            c.setStrokeColor(colors.HexColor("#E2E8F0"))
            c.setLineWidth(1)
            c.roundRect(40, y, card_w, card_h - 15, 8, fill=False, stroke=True)

            # Левая цветная полоса
            c.setFillColor(colors.HexColor("#10B981"))
            c.roundRect(40, y, 5, card_h - 15, 2, fill=True, stroke=False)

            # Шапка карточки
            draw_pill_badge(c, 55, y + card_h - 35, f"Решение задачи {idx+1}", "#10B981", "#FFFFFF", font_size=8)

            c.setFillColor(colors.HexColor("#64748B"))
            c.setFont(FONT_REGULAR, 8.5)
            c.drawString(165, y + card_h - 32, f"Партия vs {game.opponent_username} (Ход {err.move_number})")

            # Сильнейший ход Stockfish
            c.setFillColor(colors.HexColor("#065F46"))
            c.setFont(FONT_BOLD, 12)
            c.drawString(55, y + card_h - 55, f"Сильнейший ход: {err.best_move_san} ({err.best_move_uci})")

            # Зевок ученика
            c.setFillColor(colors.HexColor("#DC2626"))
            c.setFont(FONT_REGULAR, 8.5)
            c.drawString(55, y + card_h - 70, f"Ошибка в партии: {err.played_move_san} (-{err.centipawn_loss} CPL, падение шансов -{round((err.win_rate_drop or 0)*100, 1)}%)")

            # Тактический паттерн
            c.setFillColor(colors.HexColor("#1E293B"))
            c.setFont(FONT_BOLD, 8.5)
            c.drawString(55, y + card_h - 86, f"Тактическая тема: {theme_info['title']} (паттерн: {err.tactical_tag or 'тактический удар'})")

            # Описание и подсказка тренеру
            c.setFillColor(colors.HexColor("#475569"))
            c.setFont(FONT_REGULAR, 8)
            desc_lines = wrap_text(c, f"Идея решения: {theme_info['description']}", FONT_REGULAR, 8, card_w - 30)
            for li, line in enumerate(desc_lines[:2]):
                c.drawString(55, y + card_h - 100 - li * 11, line)

        # Подвал
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.setLineWidth(0.8)
        c.line(40, 35, page_w - 40, 35)

        c.setFillColor(colors.HexColor("#64748B"))
        c.setFont(FONT_REGULAR, 8)
        c.drawString(40, 22, "ChessCoach AI — Конфиденциально для тренерского штаба")
        c.drawRightString(page_w - 40, 22, "Страница 2 из 2")
