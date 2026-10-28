import io
import math
import re
from typing import Optional, List
import chess
import chess.pgn
import chess.engine

from app.schemas.chess import (
    GamePhase,
    ErrorSeverity,
    TacticalTag,
    AnalyzedMove,
    GameAnalysisResult,
)

PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}

class ChessEngineAnalyzer:
    """
    Production-grade chess analysis service using python-chess & Stockfish.
    Uses Win Rate Drop model (Lichess standard) for classifying inaccuracies, mistakes, and blunders.
    """
    def __init__(
        self,
        stockfish_path: str = "/opt/homebrew/bin/stockfish",
        depth: int = 12,
        time_limit: float = 0.08,
        threads: int = 2,
        hash_size_mb: int = 128,
        max_plies: int = 80,
    ):
        self.stockfish_path = stockfish_path
        self.depth = depth
        self.time_limit = time_limit
        self.threads = threads
        self.hash_size_mb = hash_size_mb
        self.max_plies = max_plies
        self.engine: Optional[chess.engine.SimpleEngine] = None

    def start(self):
        """Starts the UCI engine with optimized CPU/RAM limits."""
        self.engine = chess.engine.SimpleEngine.popen_uci(self.stockfish_path)
        self.engine.configure({
            "Threads": self.threads,
            "Hash": self.hash_size_mb,
        })

    def stop(self):
        if self.engine:
            self.engine.quit()
            self.engine = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    @staticmethod
    def cp_to_win_rate(cp: int) -> float:
        """
        Lichess Winning Percentage formula.
        Returns win probability from 0.0 to 1.0.
        """
        clamped_cp = max(-2000, min(2000, cp))
        return 1.0 / (1.0 + math.exp(-0.00368208 * clamped_cp))

    @staticmethod
    def score_to_cp(score: chess.engine.Score, pov_color: chess.Color) -> int:
        """Converts PovScore (including mate) to centipawns relative to pov_color."""
        pov_score = score.pov(pov_color)
        if pov_score.is_mate():
            mate_moves = pov_score.mate()
            return 2000 if (mate_moves and mate_moves > 0) else -2000
        return pov_score.score(mate_score=2000) or 0

    @staticmethod
    def determine_game_phase(board: chess.Board, ply: int) -> GamePhase:
        """
        Determines the phase of the game:
        1. Opening: ply <= 20 and total non-pawn material >= 50.
        2. Endgame: queens off board OR total non-pawn material per side <= 13 points.
        3. Middlegame: all other positions.
        """
        white_non_pawn = sum(
            len(board.pieces(pt, chess.WHITE)) * val
            for pt, val in PIECE_VALUES.items()
            if pt != chess.PAWN
        )
        black_non_pawn = sum(
            len(board.pieces(pt, chess.BLACK)) * val
            for pt, val in PIECE_VALUES.items()
            if pt != chess.PAWN
        )

        white_has_queen = bool(board.pieces(chess.QUEEN, chess.WHITE))
        black_has_queen = bool(board.pieces(chess.QUEEN, chess.BLACK))

        if (not white_has_queen and not black_has_queen) or (white_non_pawn <= 13 and black_non_pawn <= 13):
            return GamePhase.ENDGAME

        if ply <= 20 and (white_non_pawn + black_non_pawn) >= 50:
            return GamePhase.OPENING

        return GamePhase.MIDDLEGAME

    @staticmethod
    def check_hanging_piece(board_after_move: chess.Board, played_move: chess.Move) -> bool:
        """Checks if the move placed a piece on an attacked square without defender or into lower-piece attack."""
        dest_sq = played_move.to_square
        piece = board_after_move.piece_at(dest_sq)
        if not piece:
            return False

        opp_color = not piece.color
        attackers = list(board_after_move.attackers(opp_color, dest_sq))
        if not attackers:
            return False

        defenders = list(board_after_move.attackers(piece.color, dest_sq))
        piece_val = PIECE_VALUES[piece.piece_type]

        if not defenders:
            return True

        min_attacker_val = min(
            PIECE_VALUES[board_after_move.piece_at(sq).piece_type]
            for sq in attackers
            if board_after_move.piece_at(sq)
        )
        if min_attacker_val < piece_val:
            return True

        return False

    @staticmethod
    def parse_clock(comment: str) -> Optional[float]:
        """Extracts remaining clock from PGN comments like [%clk 0:03:45.2]"""
        match = re.search(r"\[%clk\s+(\d+):(\d+):([\d\.]+)\]", comment)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = float(match.group(3))
            return hours * 3600 + minutes * 60 + seconds
        return None

    def analyze_game(self, pgn_text: str, student_color: chess.Color) -> GameAnalysisResult:
        """
        Analyzes full PGN text, extracting move-by-move metrics, error classifications, and tactical tags.
        Optimized with fast engine limits (depth 12, time 0.08s) and position evaluation reuse.
        """
        if not self.engine:
            raise RuntimeError("Stockfish engine is not started. Call start() or use context manager.")

        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if not game:
            raise ValueError("Invalid PGN text provided.")

        board = game.board()
        engine_limit = chess.engine.Limit(time=self.time_limit, depth=self.depth)

        total_plies_in_game = sum(1 for _ in game.mainline())
        capped_plies = min(total_plies_in_game, self.max_plies)
        total_moves = (capped_plies + 1) // 2

        moves_tree: List[AnalyzedMove] = []
        errors: List[AnalyzedMove] = []
        cpl_list: List[int] = []

        blunders = 0
        mistakes = 0
        inaccuracies = 0
        time_blunders = 0

        # Начальная оценка стартовой позиции
        curr_info = self.engine.analyse(board, engine_limit)
        prev_score_cp = self.score_to_cp(curr_info["score"], chess.WHITE)
        prev_clock: Optional[float] = None

        node = game
        ply = 0

        while node.variations and ply < self.max_plies:
            next_node = node.variation(0)
            move = next_node.move
            ply += 1
            move_number = (ply + 1) // 2
            is_student_turn = (board.turn == student_color)

            fen_before = board.fen()
            # Берем лучший ход из уже рассчитанной оценки текущей позиции
            best_move = curr_info.get("pv", [move])[0]
            best_move_san = board.san(best_move)
            best_move_uci = best_move.uci()

            current_clock = self.parse_clock(next_node.comment)
            time_spent = None
            is_time_trouble = False
            if current_clock is not None:
                if prev_clock is not None:
                    time_spent = max(0.0, prev_clock - current_clock)
                is_time_trouble = current_clock < 15.0
                prev_clock = current_clock

            san = board.san(move)
            uci = move.uci()
            board.push(move)
            fen_after = board.fen()

            # Оценка позиции ПОСЛЕ сделанного хода (всего 1 вызов движка на полуход!)
            curr_info = self.engine.analyse(board, engine_limit)
            curr_score_cp = self.score_to_cp(curr_info["score"], chess.WHITE)

            # Логирование прогресса каждые 8 полуходов или в конце
            if ply % 8 == 0 or ply == capped_plies:
                print(f"      [Ход {move_number}/{total_moves}] полуход {ply}: {san} (оценка {curr_score_cp/100:+.2f})...", flush=True)

            phase = self.determine_game_phase(board, ply)

            turn_color = not board.turn
            score_before = prev_score_cp if turn_color == chess.WHITE else -prev_score_cp
            score_after = curr_score_cp if turn_color == chess.WHITE else -curr_score_cp

            cpl = max(0, score_before - score_after)
            win_before = self.cp_to_win_rate(score_before)
            win_after = self.cp_to_win_rate(score_after)
            win_rate_drop = max(0.0, win_before - win_after)

            severity = None
            if win_rate_drop >= 0.20 or cpl >= 200:
                severity = ErrorSeverity.BLUNDER
            elif win_rate_drop >= 0.10 or cpl >= 100:
                severity = ErrorSeverity.MISTAKE
            elif win_rate_drop >= 0.05 or cpl >= 50:
                severity = ErrorSeverity.INACCURACY

            tactical_tag = None
            if severity:
                if score_before >= 1800 and score_after < 1500:
                    tactical_tag = TacticalTag.MISSED_MATE
                elif self.check_hanging_piece(board, move):
                    tactical_tag = TacticalTag.HANGING_PIECE
                elif is_time_trouble and (time_spent is not None and time_spent < 5.0):
                    tactical_tag = TacticalTag.TIME_TROUBLE_PANIC
                else:
                    tactical_tag = TacticalTag.TACTICAL_BLUNDER

            analyzed_move = AnalyzedMove(
                ply=ply,
                move_number=move_number,
                is_student_move=is_student_turn,
                san=san,
                uci=uci,
                best_move_san=best_move_san,
                best_move_uci=best_move_uci,
                fen_before=fen_before,
                fen_after=fen_after,
                eval_before_cp=prev_score_cp,
                eval_after_cp=curr_score_cp,
                centipawn_loss=cpl if is_student_turn else 0,
                win_rate_drop=round(win_rate_drop, 4) if is_student_turn else 0.0,
                phase=phase,
                severity=severity if is_student_turn else None,
                tactical_tag=tactical_tag if is_student_turn else None,
                time_spent_seconds=time_spent,
                clock_remaining_seconds=current_clock,
                is_time_trouble=is_time_trouble,
            )

            moves_tree.append(analyzed_move)

            if is_student_turn:
                cpl_list.append(cpl)
                if severity == ErrorSeverity.BLUNDER:
                    blunders += 1
                    if is_time_trouble:
                        time_blunders += 1
                elif severity == ErrorSeverity.MISTAKE:
                    mistakes += 1
                elif severity == ErrorSeverity.INACCURACY:
                    inaccuracies += 1

                if severity is not None:
                    errors.append(analyzed_move)

            prev_score_cp = curr_score_cp
            node = next_node

        avg_cpl = int(sum(cpl_list) / len(cpl_list)) if cpl_list else 0
        accuracy = round(max(0.0, min(100.0, 100.0 * math.exp(-0.004 * avg_cpl))), 2)

        return GameAnalysisResult(
            accuracy_score=accuracy,
            acpl=avg_cpl,
            blunders_count=blunders,
            mistakes_count=mistakes,
            inaccuracies_count=inaccuracies,
            time_blunders_count=time_blunders,
            errors=errors,
            moves_tree=moves_tree,
        )
