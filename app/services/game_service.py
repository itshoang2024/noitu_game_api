import logging
import time
import uuid
from collections import Counter
from typing import Dict, List, Optional

from app.config import settings
from app.database import crud
from app.database.base import get_async_db
from app.services.ai_service import AIService

logger = logging.getLogger(__name__)


class GameService:
    """Service for game-related functionality."""

    _instance = None

    @classmethod
    def get_instance(cls):
        """Singleton pattern to ensure one instance across app."""
        if cls._instance is None:
            cls._instance = GameService()
        return cls._instance

    def __init__(self):
        """Initialize the game service."""
        self.ai_service = AIService.get_instance()
        self.used_words: Dict[str, List[str]] = {}
        self.game_stats: Dict[str, Dict] = {}

    def _initialize_session_cache(
        self,
        session_id: str,
        used_words: Optional[List[str]] = None,
        start_time: Optional[float] = None,
    ) -> None:
        """Initialize memory state for the provided session id."""
        now = time.time()
        if session_id not in self.used_words:
            self.used_words[session_id] = list(used_words or [])

        if session_id not in self.game_stats:
            self.game_stats[session_id] = {
                "start_time": start_time or now,
                "words_count": len(self.used_words[session_id]),
                "last_activity": now,
            }

    async def _load_session_from_database(self, session_id: str) -> bool:
        """Hydrate memory cache for an existing database-backed session."""
        if not settings.USE_DATABASE:
            return False

        try:
            async for db in get_async_db():
                game = await crud.get_game(db, session_id)
                if not game:
                    return False

                moves = await crud.get_game_moves(db, session_id)
                used_words = [move.word_text.lower().strip() for move in moves]
                start_time = game.start_time.timestamp() if game.start_time else None
                self._initialize_session_cache(session_id, used_words, start_time)
                return True
        except Exception as exc:
            logger.error(f"Error loading game session from database: {str(exc)}")

        return False

    async def _ensure_session_state(self, session_id: str) -> None:
        """Ensure memory and database state exist for the provided session id."""
        if session_id in self.used_words:
            self._initialize_session_cache(session_id)
            return

        if await self._load_session_from_database(session_id):
            return

        if settings.USE_DATABASE:
            try:
                async for db in get_async_db():
                    existing_game = await crud.get_game(db, session_id)
                    if not existing_game:
                        await crud.create_game(db, session_id)
            except Exception as exc:
                logger.error(f"Error creating game session in database: {str(exc)}")

        self._initialize_session_cache(session_id)

    async def create_session(self) -> str:
        """Create a new game session with database support."""
        session_id = str(uuid.uuid4())

        if settings.USE_DATABASE:
            try:
                async for db in get_async_db():
                    await crud.create_game(db, session_id)
            except Exception as exc:
                logger.error(f"Error creating game session in database: {str(exc)}")

        self._initialize_session_cache(session_id)

        logger.info(f"New game session created: {session_id}")
        return session_id

    async def register_word(self, session_id: str, word: str) -> bool:
        """Register a word as used in a session."""
        word = word.lower().strip()
        await self._ensure_session_state(session_id)

        if word in self.used_words[session_id]:
            return False

        if settings.USE_DATABASE:
            try:
                async for db in get_async_db():
                    if await crud.is_word_used_in_game(db, session_id, word):
                        return False

                    is_player = len(self.used_words[session_id]) % 2 == 0
                    await crud.add_game_move(db, session_id, word, is_player)
            except Exception as exc:
                logger.error(f"Error registering word in database: {str(exc)}")

        self.used_words[session_id].append(word)

        if session_id in self.game_stats:
            self.game_stats[session_id]["words_count"] += 1
            self.game_stats[session_id]["last_activity"] = time.time()

        return True

    async def is_word_used(self, session_id: str, word: str) -> bool:
        """Check if a word has been used in the session."""
        word = word.lower().strip()

        if session_id in self.used_words and word in self.used_words[session_id]:
            return True

        if session_id not in self.used_words and await self._load_session_from_database(session_id):
            return word in self.used_words[session_id]

        if settings.USE_DATABASE:
            try:
                async for db in get_async_db():
                    is_used = await crud.is_word_used_in_game(db, session_id, word)
                    if is_used:
                        await self._load_session_from_database(session_id)
                    return is_used
            except Exception as exc:
                logger.error(f"Error checking used word in database: {str(exc)}")

        return False

    def validate_word_pair(self, input_word: str, response_word: str) -> bool:
        """Validate if the response word follows the game rules."""
        input_syllables = input_word.strip().split()
        response_syllables = response_word.strip().split()

        if not input_syllables or not response_syllables:
            return False

        return input_syllables[-1].lower() == response_syllables[0].lower()

    def get_session_stats(self, session_id: str) -> Optional[Dict]:
        """Get statistics for a game session."""
        if session_id not in self.game_stats:
            return None

        stats = self.game_stats[session_id].copy()
        stats["total_words"] = len(self.used_words.get(session_id, []))

        current_time = time.time()
        stats["duration"] = current_time - stats["start_time"]
        stats["idle_time"] = current_time - stats["last_activity"]

        return stats

    def cleanup_old_sessions(self, max_age_hours: float = 24.0) -> int:
        """Clean up sessions that are older than the specified time."""
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600

        sessions_to_remove = []
        for session_id, stats in self.game_stats.items():
            if current_time - stats["last_activity"] > max_age_seconds:
                sessions_to_remove.append(session_id)

        for session_id in sessions_to_remove:
            if session_id in self.used_words:
                del self.used_words[session_id]
            if session_id in self.game_stats:
                del self.game_stats[session_id]

        count = len(sessions_to_remove)
        if count > 0:
            logger.info(f"Cleaned up {count} old game sessions")
        return count

    def analyze_player_words(self, session_id: str = None) -> Dict:
        """Analyze words used by players to improve dictionary."""
        all_words: List[str] = []

        if session_id:
            if session_id in self.used_words:
                all_words = self.used_words[session_id]
        else:
            for words in self.used_words.values():
                all_words.extend(words)

        word_counts = Counter(all_words)
        syllable_stats = Counter(
            syllable
            for word in all_words
            for syllable in word.split()
        )

        return {
            "total_words": len(all_words),
            "unique_words": len(word_counts),
            "top_words": word_counts.most_common(20),
            "top_syllables": syllable_stats.most_common(20),
        }
