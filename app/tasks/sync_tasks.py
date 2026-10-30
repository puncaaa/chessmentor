import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
import httpx
from celery import shared_task

from app.tasks.celery_app import celery_app
from app.tasks.analysis_tasks import analyze_game_task
from app.db.session import get_db_session
from app.services.chess_sync import ChessSyncService, UserNotFoundError
from app.services.game_service import GameService

logger = logging.getLogger(__name__)

def run_async(coro):
    """Синхронный запуск асинхронных корутин внутри Celery воркера."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(
    bind=True,
    name="app.tasks.sync_tasks.sync_student_games",
    queue="sync",
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def sync_student_games(self, student_id: str, max_games: int = 10) -> dict:
    """
    Синхронизация партий конкретного ученика со сторонних платформ.
    Задачи выполняются в легкой I/O очереди 'sync'.
    """
    logger.info(f"Запуск синхронизации партий для ученика {student_id}")
    sync_service = ChessSyncService()
    new_games_saved = 0
    skipped_duplicates = 0
    queued_for_analysis: List[str] = []

    with get_db_session() as session:
        accounts = GameService.get_active_student_accounts(session, student_id=student_id)

    if not accounts:
        logger.warning(f"У ученика {student_id} нет активных шахматных аккаунтов.")
        return {"status": "no_accounts", "new_games": 0}

    for account in accounts:
        raw_games: List[Dict[str, Any]] = []

        try:
            if account.platform == "lichess":
                since_ms = None
                if account.last_game_played_at:
                    since_ms = int(account.last_game_played_at.timestamp() * 1000)
                raw_games = run_async(
                    sync_service.fetch_lichess_games(
                        username=account.username,
                        since_timestamp_ms=since_ms,
                        max_games=max_games,
                    )
                )

            elif account.platform == "chesscom":
                raw_games = run_async(
                    sync_service.fetch_chesscom_recent_games(
                        username=account.username,
                        max_games=max_games,
                    )
                )

        except UserNotFoundError as exc:
            logger.warning(f"Шахматный пользователь не найден: {exc}")
            return {
                "status": "user_not_found",
                "message": "User not found",
                "error": str(exc),
                "new_games": 0,
                "skipped_duplicates": 0
            }

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning(f"Шахматный пользователь {account.username} не найден (404).")
                return {
                    "status": "user_not_found",
                    "message": "User not found",
                    "error": f"User '{account.username}' not found",
                    "new_games": 0,
                    "skipped_duplicates": 0
                }
            if exc.response.status_code == 429:
                logger.warning(f"Rate limit 429 при синхронизации {account.platform}:{account.username}. Рестарт через backoff...")
                raise self.retry(exc=exc, countdown=60)
            raise self.retry(exc=exc)

        # Сохранение с дедупликацией
        latest_played_at: Optional[datetime] = account.last_game_played_at

        with get_db_session() as session:
            for g_data in raw_games:
                if GameService.is_game_exists(session, g_data["platform"], g_data["external_game_id"]):
                    skipped_duplicates += 1
                    continue

                new_game = GameService.create_pending_game(
                    session=session,
                    student_profile_id=student_id,
                    chess_account_id=account.id,
                    platform=g_data["platform"],
                    external_game_id=g_data["external_game_id"],
                    url=g_data.get("url"),
                    played_at=g_data["played_at"],
                    student_color=g_data["student_color"],
                    student_rating=g_data.get("student_rating"),
                    opponent_username=g_data["opponent_username"],
                    opponent_rating=g_data.get("opponent_rating"),
                    result=g_data["result"],
                    time_control=g_data.get("time_control"),
                    speed_category=g_data.get("speed_category"),
                    eco_code=g_data.get("eco_code"),
                    opening_name=g_data.get("opening_name"),
                    pgn=g_data["pgn"],
                )

                if new_game:
                    new_games_saved += 1
                    queued_for_analysis.append(new_game.id)
                    if not latest_played_at or new_game.played_at > latest_played_at:
                        latest_played_at = new_game.played_at

            # Обновление времени синка аккаунта
            GameService.update_account_sync(
                session=session,
                account_id=account.id,
                last_synced_at=datetime.utcnow(),
                last_game_played_at=latest_played_at,
            )

        # Отправляем в тяжелую очередь Stockfish ПОСЛЕ успешного коммита транзакции
        for game_id in queued_for_analysis:
            analyze_game_task.apply_async(args=[game_id], queue="engine")

    logger.info(
        f"Синхронизация завершена для {student_id}: новых партий={new_games_saved}, "
        f"дубликатов пропущено={skipped_duplicates}"
    )

    return {
        "status": "success",
        "student_id": student_id,
        "new_games": new_games_saved,
        "skipped_duplicates": skipped_duplicates,
        "queued_games": queued_for_analysis,
    }


@celery_app.task(
    name="app.tasks.sync_tasks.sync_all_active_students_task",
    queue="sync",
)
def sync_all_active_students_task() -> dict:
    """
    Периодическая задача Celery Beat: опрашивает всех учеников школы.
    """
    logger.info("Запуск периодической синхронизации всех активных учеников")
    with get_db_session() as session:
        accounts = GameService.get_active_student_accounts(session)
        distinct_student_ids = list({acc.student_profile_id for acc in accounts})

    for student_id in distinct_student_ids:
        sync_student_games.apply_async(args=[student_id], queue="sync")

    return {
        "status": "triggered",
        "students_count": len(distinct_student_ids),
        "student_ids": distinct_student_ids,
    }
