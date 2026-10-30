import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import httpx

logger = logging.getLogger(__name__)


class UserNotFoundError(Exception):
    """Исключение: шахматный пользователь не найден на указанной платформе (404 Not Found)."""
    pass


class ChessSyncService:
    """
    Асинхронный сервис для инкрементальной синхронизации партий 
    с Lichess и Chess.com с нормализацией и защитой от rate-limiting.
    """
    
    LICHESS_BASE_URL = "https://lichess.org/api"
    CHESSCOM_BASE_URL = "https://api.chess.com/pub/player"

    def __init__(
        self,
        lichess_token: Optional[str] = None,
        user_agent: str = "ChessCoachAI/1.0 (contact: support@chesscoach.ai)"
    ):
        self.lichess_token = lichess_token
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "application/json",
        }

    async def fetch_lichess_games(
        self,
        username: str,
        since_timestamp_ms: Optional[int] = None,
        max_games: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Загрузка партий с Lichess через NDJSON.
        """
        req_headers = dict(self.headers)
        req_headers["Accept"] = "application/x-ndjson"
        if self.lichess_token:
            req_headers["Authorization"] = f"Bearer {self.lichess_token}"

        params = {
            "max": max_games,
            "pgnInJson": "true",
            "clocks": "true",
            "opening": "true",
        }
        if since_timestamp_ms:
            params["since"] = since_timestamp_ms

        url = f"{self.LICHESS_BASE_URL}/games/user/{username}"
        raw_games: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params, headers=req_headers)
            if response.status_code == 429:
                logger.warning("Lichess rate limit hit (429). Backing off...")
                raise httpx.HTTPStatusError("Lichess 429 Rate Limit", request=response.request, response=response)
            if response.status_code == 404:
                logger.warning(f"Игрок Lichess '{username}' не найден (404).")
                raise UserNotFoundError(f"User '{username}' not found on Lichess")
            response.raise_for_status()

            for line in response.text.strip().split("\n"):
                if line.strip():
                    import json
                    raw_games.append(json.loads(line))

        normalized = []
        for g in raw_games:
            norm = self.normalize_lichess_game(g, username)
            if norm:
                normalized.append(norm)
        return normalized

    async def fetch_chesscom_recent_games(
        self,
        username: str,
        max_games: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Загрузка последних партий с Chess.com через список архивов.
        Просматривает последние месячные архивы в обратном порядке,
        гарантируя получение свежих партий, даже если в текущем месяце сыграно 0 партий.
        """
        clean_username = username.strip().lower()
        archives_url = f"{self.CHESSCOM_BASE_URL}/{clean_username}/games/archives"
        raw_games: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                # Сначала проверяем существование профиля игрока на Chess.com
                profile_res = await client.get(f"{self.CHESSCOM_BASE_URL}/{clean_username}", headers=self.headers)
                if profile_res.status_code == 404:
                    logger.warning(f"Игрок Chess.com '{username}' не найден (404).")
                    raise UserNotFoundError(f"User '{username}' not found on Chess.com")
                if profile_res.status_code == 429:
                    raise httpx.HTTPStatusError("Chess.com 429 Rate Limit", request=profile_res.request, response=profile_res)
                profile_res.raise_for_status()

                res = await client.get(archives_url, headers=self.headers)
                if res.status_code == 429:
                    raise httpx.HTTPStatusError("Chess.com 429 Rate Limit", request=res.request, response=res)
                if res.status_code == 404:
                    logger.warning(f"Архивы Chess.com для '{username}' не найдены.")
                    return []
                res.raise_for_status()
                archives = res.json().get("archives", [])
            except UserNotFoundError:
                raise
            except httpx.HTTPError as exc:
                logger.error(f"Ошибка при запросе архивов Chess.com для {username}: {exc}")
                raise

            # Проходим архивы с конца (самые свежие)
            for archive_url in reversed(archives):
                try:
                    arch_res = await client.get(archive_url, headers=self.headers)
                    if arch_res.status_code == 200:
                        month_games = arch_res.json().get("games", [])
                        # Добавляем партии с конца месяца (самые свежие)
                        for g in reversed(month_games):
                            raw_games.append(g)
                            if len(raw_games) >= max_games:
                                break
                    if len(raw_games) >= max_games:
                        break
                except Exception as exc:
                    logger.warning(f"Ошибка чтения архива {archive_url}: {exc}")
                    continue

        normalized = []
        for g in raw_games:
            norm = self.normalize_chesscom_game(g, username)
            if norm:
                normalized.append(norm)
        return normalized

    async def fetch_chesscom_monthly_archive(
        self,
        username: str,
        year: int,
        month: int,
        max_games: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Загрузка архива партий за конкретный месяц с Chess.com.
        """
        url = f"{self.CHESSCOM_BASE_URL}/{username.lower()}/games/{year}/{month:02d}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=self.headers)
            if response.status_code == 429:
                logger.warning("Chess.com rate limit hit (429).")
                raise httpx.HTTPStatusError("Chess.com 429 Rate Limit", request=response.request, response=response)
            if response.status_code == 404:
                return []
            response.raise_for_status()
            data = response.json()
            raw_games = data.get("games", [])

        raw_games = raw_games[-max_games:] if len(raw_games) > max_games else raw_games

        normalized = []
        for g in raw_games:
            norm = self.normalize_chesscom_game(g, username)
            if norm:
                normalized.append(norm)
        return normalized

    @staticmethod
    def normalize_lichess_game(raw: Dict[str, Any], student_username: str) -> Optional[Dict[str, Any]]:
        """Нормализация формата партии Lichess к схеме сервиса."""
        ext_id = raw.get("id")
        if not ext_id:
            return None

        players = raw.get("players", {})
        white_player = players.get("white", {})
        black_player = players.get("black", {})

        white_user = white_player.get("user", {}).get("name", white_player.get("userId", ""))
        black_user = black_player.get("user", {}).get("name", black_player.get("userId", ""))

        is_student_white = white_user.lower() == student_username.lower()
        student_color = "white" if is_student_white else "black"

        opponent_user = black_user if is_student_white else white_user
        student_rating = white_player.get("rating") if is_student_white else black_player.get("rating")
        opponent_rating = black_player.get("rating") if is_student_white else white_player.get("rating")

        winner = raw.get("winner")
        if winner == "white":
            result = "1-0"
        elif winner == "black":
            result = "0-1"
        else:
            result = "1/2-1/2"

        played_at_ms = raw.get("createdAt")
        played_at = datetime.fromtimestamp(played_at_ms / 1000.0) if played_at_ms else datetime.utcnow()

        pgn = raw.get("pgn", "")
        # Если PGN не вложен прямо в json, сформируем минимальный заголовок с ходами
        if not pgn and "moves" in raw:
            pgn = f'[Event "Lichess game"]\n[White "{white_user}"]\n[Black "{black_user}"]\n[Result "{result}"]\n\n{raw["moves"]}'

        return {
            "platform": "lichess",
            "external_game_id": ext_id,
            "url": f"https://lichess.org/{ext_id}",
            "played_at": played_at,
            "student_color": student_color,
            "student_rating": student_rating,
            "opponent_username": opponent_user or "Unknown",
            "opponent_rating": opponent_rating,
            "result": result,
            "time_control": raw.get("speed", ""),
            "speed_category": raw.get("speed", "blitz"),
            "eco_code": raw.get("opening", {}).get("eco"),
            "opening_name": raw.get("opening", {}).get("name"),
            "pgn": pgn,
        }

    @staticmethod
    def normalize_chesscom_game(raw: Dict[str, Any], student_username: str) -> Optional[Dict[str, Any]]:
        """Нормализация формата партии Chess.com к схеме сервиса."""
        url = raw.get("url", "")
        ext_id = raw.get("uuid") or url.split("/")[-1]
        if not ext_id:
            return None

        white = raw.get("white", {})
        black = raw.get("black", {})

        white_user = white.get("username", "")
        black_user = black.get("username", "")

        is_student_white = white_user.lower() == student_username.lower()
        student_color = "white" if is_student_white else "black"

        opponent_user = black_user if is_student_white else white_user
        student_rating = white.get("rating") if is_student_white else black.get("rating")
        opponent_rating = black.get("rating") if is_student_white else white.get("rating")

        white_result = white.get("result", "")
        black_result = black.get("result", "")

        if white_result == "win":
            result = "1-0"
        elif black_result == "win":
            result = "0-1"
        else:
            result = "1/2-1/2"

        end_time = raw.get("end_time")
        played_at = datetime.fromtimestamp(end_time) if end_time else datetime.utcnow()

        return {
            "platform": "chesscom",
            "external_game_id": ext_id,
            "url": url,
            "played_at": played_at,
            "student_color": student_color,
            "student_rating": student_rating,
            "opponent_username": opponent_user or "Unknown",
            "opponent_rating": opponent_rating,
            "result": result,
            "time_control": raw.get("time_control", ""),
            "speed_category": raw.get("time_class", "blitz"),
            "eco_code": None,
            "opening_name": None,
            "pgn": raw.get("pgn", ""),
        }
