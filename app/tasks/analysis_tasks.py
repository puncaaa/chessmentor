import logging
import chess
from datetime import datetime
from app.tasks.celery_app import celery_app
from app.db.session import get_db_session
from app.services.game_service import GameService
from app.services.chess_analyzer import ChessEngineAnalyzer
from app.core.config import settings

logger = logging.getLogger(__name__)

@celery_app.task(
    bind=True,
    name="app.tasks.analysis_tasks.analyze_game_task",
    queue="engine",
    max_retries=2,
    default_retry_delay=30,
)
def analyze_game_task(self, game_id: str) -> dict:
    """
    Тяжелая фоновая задача движкового анализа партии через Stockfish.
    Исполняется в выделенной очереди 'engine' с лимитом параллелизма.
    """
    logger.info(f"Начало анализа партии {game_id}")
    
    with get_db_session() as session:
        game = GameService.get_game_by_id(session, game_id)
        if not game:
            logger.error(f"Партия {game_id} не найдена в базе данных.")
            return {"status": "error", "message": "Game not found"}

        if game.analysis_status == "completed":
            logger.info(f"Партия {game_id} уже была проанализирована.")
            return {"status": "skipped", "game_id": game_id}

        # Обновляем статус на processing
        GameService.update_analysis_status(session, game_id, "processing")
        pgn = game.pgn
        student_color = chess.WHITE if game.student_color == "white" else chess.BLACK
        platform = game.platform
        ext_id = game.external_game_id

    import time
    start_time = time.perf_counter()
    print(f"\n   ⏳ Начинаем анализ партии [{platform}] ID: {ext_id}...", flush=True)

    try:
        # Анализ через Stockfish
        with ChessEngineAnalyzer(
            stockfish_path=settings.STOCKFISH_PATH,
            depth=settings.STOCKFISH_DEPTH,
            time_limit=getattr(settings, "STOCKFISH_TIME_LIMIT", 0.08),
            threads=settings.STOCKFISH_THREADS,
            hash_size_mb=settings.STOCKFISH_HASH_MB,
        ) as analyzer:
            analysis_result = analyzer.analyze_game(pgn, student_color=student_color)

        # Сохранение результатов и ошибок
        with get_db_session() as session:
            GameService.save_analysis_results(session, game_id, analysis_result)

        elapsed = time.perf_counter() - start_time
        print(
            f"   ✅ Партия [{platform}] ID={ext_id} проанализирована за {elapsed:.2f}с: "
            f"Точность={analysis_result.accuracy_score}%, ACPL={analysis_result.acpl}, "
            f"Зевков={analysis_result.blunders_count}",
            flush=True
        )
        return {
            "status": "completed",
            "game_id": game_id,
            "accuracy": analysis_result.accuracy_score,
            "acpl": analysis_result.acpl,
            "blunders": analysis_result.blunders_count,
            "errors_extracted": len(analysis_result.errors),
            "elapsed_seconds": round(elapsed, 2),
        }

    except Exception as exc:
        logger.exception(f"Ошибка при анализе партии {game_id}: {exc}")
        with get_db_session() as session:
            GameService.update_analysis_status(session, game_id, "failed")
        raise self.retry(exc=exc)
