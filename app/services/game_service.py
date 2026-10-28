import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select, and_

from app.models.chess import Game, ChessErrorEvent, StudentChessAccount, StudentProfile
from app.schemas.chess import GameAnalysisResult, AnalyzedMove

logger = logging.getLogger(__name__)

class GameService:
    """
    Сервис доступа к данным партий, дедупликации и сохранения результатов анализа.
    """

    @staticmethod
    def is_game_exists(session: Session, platform: str, external_game_id: str) -> bool:
        """
        Проверка дедупликации по составному уникальному ключу (platform, external_game_id).
        """
        stmt = select(Game.id).where(
            and_(Game.platform == platform, Game.external_game_id == str(external_game_id))
        )
        return session.execute(stmt).first() is not None

    @staticmethod
    def create_pending_game(
        session: Session,
        student_profile_id: str,
        chess_account_id: Optional[str],
        platform: str,
        external_game_id: str,
        url: Optional[str],
        played_at: datetime,
        student_color: str,
        student_rating: Optional[int],
        opponent_username: str,
        opponent_rating: Optional[int],
        result: str,
        time_control: Optional[str],
        speed_category: Optional[str],
        pgn: str,
        eco_code: Optional[str] = None,
        opening_name: Optional[str] = None,
    ) -> Optional[Game]:
        """
        Сохранение новой партии со статусом 'pending' с гарантией дедупликации.
        """
        if GameService.is_game_exists(session, platform, external_game_id):
            logger.debug(f"Партия {platform}:{external_game_id} уже есть в БД. Пропуск.")
            return None

        # Определяем победителя
        winner = None
        if result == "1-0":
            winner = "white"
        elif result == "0-1":
            winner = "black"
        elif result in ("1/2-1/2", "0.5-0.5", "draw"):
            winner = "draw"

        game = Game(
            student_profile_id=student_profile_id,
            chess_account_id=chess_account_id,
            platform=platform,
            external_game_id=str(external_game_id),
            url=url,
            played_at=played_at,
            student_color=student_color.lower(),
            student_rating=student_rating,
            opponent_username=opponent_username,
            opponent_rating=opponent_rating,
            result=result,
            winner=winner,
            time_control=time_control,
            speed_category=speed_category,
            eco_code=eco_code,
            opening_name=opening_name,
            pgn=pgn,
            analysis_status="pending",
        )
        session.add(game)
        session.flush() # Получаем game.id
        return game

    @staticmethod
    def get_game_by_id(session: Session, game_id: str) -> Optional[Game]:
        return session.get(Game, game_id)

    @staticmethod
    def update_analysis_status(session: Session, game_id: str, status: str):
        game = session.get(Game, game_id)
        if game:
            game.analysis_status = status
            session.flush()

    @staticmethod
    def save_analysis_results(
        session: Session,
        game_id: str,
        result: GameAnalysisResult,
    ):
        """
        Сохранение рассчитанных метрик движка в запись партии 
        и детализированных ошибок в таблицу chess_error_events.
        """
        game = session.get(Game, game_id)
        if not game:
            raise ValueError(f"Game with id {game_id} not found")

        game.accuracy_score = result.accuracy_score
        game.acpl = result.acpl
        game.blunders_count = result.blunders_count
        game.mistakes_count = result.mistakes_count
        game.inaccuracies_count = result.inaccuracies_count
        game.time_spent_blunders_count = result.time_blunders_count
        game.analysis_status = "completed"
        game.analyzed_at = datetime.utcnow()
        game.analysis_json = [m.model_dump() for m in result.moves_tree]

        # Сохранение ошибок в оптимизированную таблицу
        for err in result.errors:
            error_event = ChessErrorEvent(
                game_id=game.id,
                student_profile_id=game.student_profile_id,
                ply_number=err.ply,
                move_number=err.move_number,
                played_move_san=err.san,
                played_move_uci=err.uci,
                best_move_san=err.best_move_san,
                best_move_uci=err.best_move_uci,
                fen_before=err.fen_before,
                fen_after=err.fen_after,
                eval_before=err.eval_before_cp,
                eval_after=err.eval_after_cp,
                centipawn_loss=err.centipawn_loss,
                win_rate_drop=err.win_rate_drop,
                severity=err.severity.value if err.severity else "blunder",
                tactical_tag=err.tactical_tag.value if err.tactical_tag else None,
                phase=err.phase.value if err.phase else "middlegame",
                time_spent_seconds=err.time_spent_seconds,
                clock_remaining_seconds=err.clock_remaining_seconds,
                is_time_trouble=err.is_time_trouble,
            )
            session.add(error_event)

        session.flush()

    @staticmethod
    def update_account_sync(
        session: Session,
        account_id: str,
        last_synced_at: datetime,
        last_game_played_at: Optional[datetime] = None,
    ):
        account = session.get(StudentChessAccount, account_id)
        if account:
            account.last_synced_at = last_synced_at
            if last_game_played_at:
                account.last_game_played_at = last_game_played_at
            session.flush()

    @staticmethod
    def get_active_student_accounts(session: Session, student_id: Optional[str] = None) -> List[StudentChessAccount]:
        stmt = select(StudentChessAccount).where(StudentChessAccount.is_active == True)
        if student_id:
            stmt = stmt.where(StudentChessAccount.student_profile_id == student_id)
        return list(session.execute(stmt).scalars().all())
