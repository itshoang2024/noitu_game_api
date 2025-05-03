import time
import logging
from typing import Dict, List, Tuple, Optional
import uuid

from app.services.ai_service import AIService

logger = logging.getLogger(__name__)

class GameService:
    """Service for game-related functionality"""
    _instance = None
    
    @classmethod
    def get_instance(cls):
        """Singleton pattern to ensure one instance across app"""
        if cls._instance is None:
            cls._instance = GameService()
        return cls._instance
    
    def __init__(self):
        """Initialize the game service"""
        self.ai_service = AIService.get_instance()
        self.used_words: Dict[str, List[str]] = {}  # Map session_id to list of used words
        self.game_stats: Dict[str, Dict] = {}  # Store game statistics
    
    def create_session(self) -> str:
        """Create a new game session"""
        session_id = str(uuid.uuid4())
        self.used_words[session_id] = []
        self.game_stats[session_id] = {
            "start_time": time.time(),
            "words_count": 0,
            "last_activity": time.time()
        }
        logger.info(f"New game session created: {session_id}")
        return session_id
    
    def register_word(self, session_id: str, word: str) -> bool:
        """Register a word as used in a session"""
        # Create session if it doesn't exist
        if session_id not in self.used_words:
            self.create_session()
            
        # Check if word is already used
        if word in self.used_words[session_id]:
            return False
            
        # Add word to used list
        self.used_words[session_id].append(word)
        
        # Update stats
        if session_id in self.game_stats:
            self.game_stats[session_id]["words_count"] += 1
            self.game_stats[session_id]["last_activity"] = time.time()
            
        return True
    
    def is_word_used(self, session_id: str, word: str) -> bool:
        """Check if a word has been used in the session"""
        if session_id not in self.used_words:
            return False
        return word in self.used_words[session_id]
    
    def validate_word_pair(self, input_word: str, response_word: str) -> bool:
        """Validate if the response word follows the game rules"""
        # Split words into syllables
        input_syllables = input_word.strip().split()
        response_syllables = response_word.strip().split()
        
        # Basic validation
        if not input_syllables or not response_syllables:
            return False
        
        # Last syllable of input must match first syllable of response
        return input_syllables[-1].lower() == response_syllables[0].lower()
    
    def get_session_stats(self, session_id: str) -> Optional[Dict]:
        """Get statistics for a game session"""
        if session_id not in self.game_stats:
            return None
            
        stats = self.game_stats[session_id].copy()
        
        # Calculate additional metrics
        if session_id in self.used_words:
            stats["total_words"] = len(self.used_words[session_id])
        else:
            stats["total_words"] = 0
            
        current_time = time.time()
        stats["duration"] = current_time - stats["start_time"]
        stats["idle_time"] = current_time - stats["last_activity"]
        
        return stats
    
    def cleanup_old_sessions(self, max_age_hours: float = 24.0) -> int:
        """Clean up sessions that are older than the specified time"""
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        sessions_to_remove = []
        for session_id, stats in self.game_stats.items():
            if current_time - stats["last_activity"] > max_age_seconds:
                sessions_to_remove.append(session_id)
        
        # Remove old sessions
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
        """Analyze words used by players to improve dictionary"""
        all_words = []
        
        if session_id:
            # Analyze specific session
            if session_id in self.used_words:
                all_words = self.used_words[session_id]
        else:
            # Analyze all sessions
            for words in self.used_words.values():
                all_words.extend(words)
        
        # Count word frequencies
        word_counts = {}
        for word in all_words:
            if word in word_counts:
                word_counts[word] += 1
            else:
                word_counts[word] = 1
        
        # Sort by frequency
        sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        
        # Get syllable statistics
        syllable_stats = {}
        for word in all_words:
            syllables = word.split()
            for syllable in syllables:
                if syllable in syllable_stats:
                    syllable_stats[syllable] += 1
                else:
                    syllable_stats[syllable] = 1
        
        # Sort syllables by frequency
        sorted_syllables = sorted(syllable_stats.items(), key=lambda x: x[1], reverse=True)
        
        return {
            "total_words": len(all_words),
            "unique_words": len(word_counts),
            "top_words": sorted_words[:20],
            "top_syllables": sorted_syllables[:20]
        }

