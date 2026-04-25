import logging
import os
from typing import Dict, List, Tuple, Set
from app.utils.constants import DICTIONARY_PATH, COMMON_WORDS_PATH
from app.database.base import get_async_db
from app.database import crud
from app.database.models import Word
from sqlalchemy.future import select

logger = logging.getLogger(__name__)

class WordEvaluator:
    """Evaluator for Vietnamese word quality"""
    _instance = None
    
    @classmethod
    def get_instance(cls):
        """Singleton pattern to ensure one instance across app"""
        if cls._instance is None:
            cls._instance = WordEvaluator()
        return cls._instance
    
    def __init__(self):
        """Initialize the word evaluator with dictionaries"""
        self.dictionary_path = DICTIONARY_PATH
        self.common_words_path = COMMON_WORDS_PATH
        self.dictionary: Set[str] = set()
        self.common_words: Set[str] = set()
        self.word_scores: Dict[str, float] = {}
        self.is_initialized = False
        self.word_chains: Dict[str, List[str]] = {}  # syllable -> list of words that start with it

    async def _load_common_words_from_db(self, db):
        common_words = await crud.get_all_common_words(db)
        self.common_words = {word.word for word in common_words}
        if self.common_words:
            logger.info(f"Loaded {len(self.common_words)} common words from database")
            return

        await self._create_minimal_dictionary_in_db(db)
        common_words = await crud.get_all_common_words(db)
        self.common_words = {word.word for word in common_words}
        logger.info(f"Loaded {len(self.common_words)} common words from database")

    async def _load_dictionary_from_db(self, db):
        result = await db.execute(select(Word))
        all_words = result.scalars().all()
        self.dictionary = {word.word for word in all_words}
        if not self.dictionary:
            self.dictionary = set(self.common_words)
        logger.info(f"Loaded {len(self.dictionary)} words from database")

    async def _initialize_from_database(self):
        async for db in get_async_db():
            await self._load_common_words_from_db(db)
            await self._load_dictionary_from_db(db)

    async def initialize(self):
        """Load dictionaries from database"""
        if self.is_initialized:
            return

        try:
            await self._initialize_from_database()
        except Exception as exc:
            logger.error(f"Error initializing WordEvaluator: {str(exc)}")
            self._create_minimal_dictionary_in_memory()
            if not self.common_words:
                self._create_minimal_common_words()

        self.is_initialized = True
        await self.build_word_chains()

    def _create_minimal_dictionary_in_memory(self):
        """Create a minimal dictionary with common Vietnamese words"""
        base_words = [
            "học sinh", "sinh viên", "viên chức", "chức vụ", "vụ việc", "việc làm",
            "làm việc", "việc nhà", "nhà cửa", "cửa sổ", "sổ sách", "sách vở",
            "vở kịch", "kịch bản", "bàn ghế", "ghế đẩu", "đầu óc", "óc chó",
            "chó mèo", "mèo hoang", "hoang dã", "dã chiến", "chiến đấu", "đấu tranh",
            "tranh ảnh", "ảnh đẹp", "đẹp đẽ", "đẽo gọt", "gọt rửa", "rửa mặt",
            "mặt trời", "trời đất", "đất nước", "nước mắm", "mắm tôm", "tôm cá",
            "cá chép", "chép bài", "bài tập", "tập trung", "trung tâm", "tâm hồn"
        ]
        self.dictionary = set(base_words)
        
        # Save to file for future use
        try:
            os.makedirs(os.path.dirname(self.dictionary_path), exist_ok=True)
            with open(self.dictionary_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(base_words))
            logger.info(f"Created minimal dictionary with {len(base_words)} words")
        except Exception as e:
            logger.error(f"Error creating minimal dictionary file: {str(e)}")

    async def _create_minimal_dictionary_in_db(self, db):
        """Tạo từ điển tối thiểu trong database"""
        base_words = [
            "học sinh", "sinh viên", "viên chức", "chức vụ", "vụ việc", "việc làm",
            "làm việc", "việc nhà", "nhà cửa", "cửa sổ", "sổ sách", "sách vở",
            "vở kịch", "kịch bản", "bàn ghế", "ghế đẩu", "đầu óc", "óc chó",
            "chó mèo", "mèo hoang", "hoang dã", "dã chiến", "chiến đấu", "đấu tranh",
            "tranh ảnh", "ảnh đẹp", "đẹp đẽ", "đẽo gọt", "gọt rửa", "rửa mặt",
            "mặt trời", "trời đất", "đất nước", "nước mắm", "mắm tôm", "tôm cá",
            "cá chép", "chép bài", "bài tập", "tập trung", "trung tâm", "tâm hồn"
        ]
        
        for word in base_words:
            await crud.create_word(db, word, quality_score=0.7, is_common=True)
        
        logger.info(f"Created minimal dictionary with {len(base_words)} words in database")
    
    def _create_minimal_common_words(self):
        """Create a minimal list of common Vietnamese words"""
        common_words = [
            "học sinh", "nhà cửa", "bàn ghế", "cửa sổ", "mặt trời",
            "đất nước", "gia đình", "trường học", "bệnh viện", "công việc"
        ]
        self.common_words = set(common_words)
        
        # Save to file for future use
        try:
            os.makedirs(os.path.dirname(self.common_words_path), exist_ok=True)
            with open(self.common_words_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(common_words))
            logger.info(f"Created minimal common words list with {len(common_words)} words")
        except Exception as e:
            logger.error(f"Error creating minimal common words file: {str(e)}")
    
    async def add_to_dictionary(self, word: str) -> bool:
        """Add a new word to dictionary"""
        word = word.strip().lower()
        if not word or word in self.dictionary:
            return False

        try:
            async for db in get_async_db():
                # Kiểm tra tồn tại trước khi thêm
                existing_word = await crud.get_word(db, word)
                if existing_word:
                    self.dictionary.add(word)  # Đảm bảo từ có trong bộ nhớ cache
                    return True  # Trả về thành công vì từ đã tồn tại
                else:
                    await crud.create_word(db, word)
            # Update in-memory cache
            self.dictionary.add(word)
            return True
        except Exception as e:
            logger.error(f"Error adding word to database: {str(e)}")
            # Still add to memory cache to prevent repeated errors
            self.dictionary.add(word)
            return True
        
    def is_in_dictionary(self, word: str) -> bool:
        """Check if word exists in the dictionary"""
        return word.strip().lower() in self.dictionary
    
    def is_common_word(self, word: str) -> bool:
        """Check if word is a common word"""
        return word.strip().lower() in self.common_words
    
    async def evaluate_word(self, word: str) -> Tuple[float, str]:
        """Evaluate the quality of a word on a scale of 0-1"""
        if not await self.ensure_initialized():
            return 0.3, "Từ điển chưa được khởi tạo"
            
        word = word.strip().lower()
        
        # Return cached score if available
        if word in self.word_scores:
            return self.word_scores[word], self._get_score_reason(self.word_scores[word])
        
        score = 0.0
        reasons = []
        
        # Check if word exists in dictionary - make this a bonus, not a requirement
        if self.is_in_dictionary(word):
            score += 0.4
            reasons.append("Từ tồn tại trong từ điển")
        else:
            # Check basic Vietnamese word structure
            from app.utils.validators import validate_word_structure
            is_valid, _ = validate_word_structure(word)
            if is_valid:
                score += 0.3
                reasons.append("Từ có cấu trúc tiếng Việt hợp lệ")
            else:
                score += 0.1
                reasons.append("Từ không có trong từ điển")
        
        # Check if it's a common word
        if self.is_common_word(word):
            score += 0.3
            reasons.append("Từ phổ biến")
        
        # Check length (2-3 syllables preferred)
        syllable_count = len(word.split())
        if syllable_count == 2:
            score += 0.3  # Increased weight for 2-syllable words
            reasons.append("Độ dài từ thích hợp (2 âm tiết)")
        elif syllable_count == 3:
            score += 0.2
            reasons.append("Độ dài từ thích hợp (3 âm tiết)")
        elif syllable_count > 3:
            score += 0.1
            reasons.append(f"Từ dài ({syllable_count} âm tiết)")
        else:
            # Single syllable words are okay too
            score += 0.2
            reasons.append("Từ ngắn (1 âm tiết)")
        
        # Cap score at 1.0
        final_score = min(score, 1.0)
        
        # Cache the score
        self.word_scores[word] = final_score
        
        return final_score, "; ".join(reasons)    
    
    def _get_score_reason(self, score: float) -> str:
        """Get a reason description based on score"""
        if score >= 0.8:
            return "Từ chất lượng cao"
        elif score >= 0.6:
            return "Từ chất lượng khá tốt"
        elif score >= 0.4:
            return "Từ chất lượng trung bình"
        elif score >= 0.2:
            return "Từ chất lượng thấp"
        else:
            return "Từ chất lượng rất thấp hoặc không hợp lệ"
    
    async def ensure_initialized(self) -> bool:
        """Ensure the evaluator is initialized"""
        if not self.is_initialized:
            await self.initialize()
        return self.is_initialized
    
    async def build_word_chains(self):
        """Build word chains for faster suggestion and validation"""
        self.word_chains = {}
        
        # Process all words in dictionary
        for word in self.dictionary:
            syllables = word.split()
            if len(syllables) >= 2:
                first_syllable = syllables[0]
                
                # Add to chains
                if first_syllable not in self.word_chains:
                    self.word_chains[first_syllable] = []
                    
                self.word_chains[first_syllable].append(word)
        
        logger.info(f"Built word chains for {len(self.word_chains)} syllables")
        
        # Log some statistics
        total_chain_words = sum(len(words) for words in self.word_chains.values())
        avg_words_per_syllable = total_chain_words / len(self.word_chains) if self.word_chains else 0
        
        logger.info(f"Average words per syllable: {avg_words_per_syllable:.2f}")
        
        return len(self.word_chains)

    def get_words_starting_with(self, syllable: str) -> List[str]:
        """Get words that start with the given syllable"""
        return self.word_chains.get(syllable.lower(), [])