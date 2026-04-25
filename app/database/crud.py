from sqlalchemy.orm import Session
from sqlalchemy.future import select
from sqlalchemy import func, or_
from typing import List, Optional, Dict, Tuple
from datetime import datetime

from .models import Word, Game, GameMove, Theme, ThemeWord, AIMetric

# --- Word operations ---

async def create_word(db: Session, word: str, quality_score: float = 0.5, is_common: bool = False) -> Word:
    """Tạo một từ mới trong database"""
    syllables = word.lower().strip().split()
    word_obj = Word(
        word=word.lower().strip(),
        quality_score=quality_score,
        is_common=is_common,
        syllable_count=len(syllables),
        first_syllable=syllables[0] if syllables else "",
        last_syllable=syllables[-1] if syllables else ""
    )
    db.add(word_obj)
    await db.commit()
    await db.refresh(word_obj)
    return word_obj

async def get_word(db: Session, word: str) -> Optional[Word]:
    """Lấy từ từ database theo text"""
    result = await db.execute(select(Word).filter(Word.word == word.lower().strip()))
    return result.scalars().first()

async def get_or_create_word(db: Session, word: str, quality_score: float = 0.5) -> Word:
    """Lấy từ nếu đã tồn tại, nếu không thì tạo mới"""
    word_obj = await get_word(db, word)
    if not word_obj:
        word_obj = await create_word(db, word, quality_score)
    return word_obj

async def get_words_by_first_syllable(db: Session, syllable: str) -> List[Word]:
    """Lấy các từ bắt đầu bằng âm tiết cho trước"""
    result = await db.execute(select(Word).filter(Word.first_syllable == syllable.lower().strip()))
    return result.scalars().all()

async def get_words_by_last_syllable(db: Session, syllable: str) -> List[Word]:
    """Lấy các từ kết thúc bằng âm tiết cho trước"""
    result = await db.execute(select(Word).filter(Word.last_syllable == syllable.lower().strip()))
    return result.scalars().all()

async def get_all_common_words(db: Session) -> List[Word]:
    """Lấy tất cả các từ phổ biến"""
    result = await db.execute(select(Word).filter(Word.is_common == True))
    return result.scalars().all()

async def update_word_quality(db: Session, word_id: int, quality_score: float) -> Word:
    """Cập nhật điểm chất lượng của từ"""
    word_obj = await db.get(Word, word_id)
    if word_obj:
        word_obj.quality_score = quality_score
        await db.commit()
        await db.refresh(word_obj)
    return word_obj

# --- Game operations ---

async def create_game(db: Session, session_id: str, theme_id: Optional[int] = None) -> Game:
    """Tạo một phiên chơi mới"""
    game = Game(
        id=session_id,
        theme_id=theme_id,
        start_time=datetime.utcnow(),
        status="active"
    )
    db.add(game)
    await db.commit()
    await db.refresh(game)
    return game

async def get_game(db: Session, session_id: str) -> Optional[Game]:
    """Lấy thông tin phiên chơi theo ID"""
    result = await db.execute(select(Game).filter(Game.id == session_id))
    return result.scalars().first()

async def end_game(db: Session, session_id: str) -> Optional[Game]:
    """Kết thúc phiên chơi"""
    game = await get_game(db, session_id)
    if game:
        game.status = "completed"
        game.end_time = datetime.utcnow()
        if game.start_time:
            game.duration_seconds = (game.end_time - game.start_time).seconds
        await db.commit()
        await db.refresh(game)
    return game

async def add_game_move(db: Session, game_id: str, word: str, is_player: bool, 
                      quality_score: float = None, response_time_ms: int = None) -> GameMove:
    """Thêm một lượt đi vào phiên chơi"""
    # Lấy hoặc tạo từ
    word_obj = await get_or_create_word(db, word)
    
    # Lấy số thứ tự lượt đi
    result = await db.execute(
        select(func.count()).select_from(GameMove).filter(GameMove.game_id == game_id)
    )
    move_number = result.scalar() + 1
    
    # Tạo lượt đi
    move = GameMove(
        game_id=game_id,
        word_id=word_obj.id,
        word_text=word,
        move_number=move_number,
        is_player=is_player,
        quality_score=quality_score,
        response_time_ms=response_time_ms
    )
    db.add(move)
    
    # Cập nhật số từ cho game
    game = await get_game(db, game_id)
    if game:
        game.word_count = move_number
    
    await db.commit()
    await db.refresh(move)
    return move

async def get_game_moves(db: Session, game_id: str) -> List[GameMove]:
    """Lấy tất cả các lượt đi của một phiên chơi"""
    result = await db.execute(
        select(GameMove).filter(GameMove.game_id == game_id).order_by(GameMove.move_number)
    )
    return result.scalars().all()

async def is_word_used_in_game(db: Session, game_id: str, word: str) -> bool:
    """Kiểm tra xem từ đã được sử dụng trong phiên chơi chưa"""
    result = await db.execute(
        select(func.count()).select_from(GameMove).filter(
            GameMove.game_id == game_id,
            func.lower(GameMove.word_text) == word.lower().strip()
        )
    )
    return result.scalar() > 0

# --- Theme operations ---

async def create_theme(db: Session, name: str, description: str = None, is_default: bool = False) -> Theme:
    """Tạo một chủ đề mới"""
    theme = Theme(
        name=name,
        description=description,
        is_default=is_default
    )
    db.add(theme)
    await db.commit()
    await db.refresh(theme)
    return theme

async def get_theme(db: Session, theme_id: int) -> Optional[Theme]:
    """Lấy thông tin chủ đề theo ID"""
    result = await db.execute(select(Theme).filter(Theme.id == theme_id))
    return result.scalars().first()

async def get_theme_by_name(db: Session, name: str) -> Optional[Theme]:
    """Lấy thông tin chủ đề theo tên"""
    result = await db.execute(select(Theme).filter(Theme.name == name))
    return result.scalars().first()

async def get_all_themes(db: Session) -> List[Theme]:
    """Lấy tất cả các chủ đề"""
    result = await db.execute(select(Theme))
    return result.scalars().all()

async def add_word_to_theme(db: Session, theme_id: int, word: str) -> ThemeWord:
    """Thêm một từ vào chủ đề"""
    word_obj = await get_or_create_word(db, word)

    # Skip insert if this theme-word mapping already exists
    existing = await db.execute(
        select(ThemeWord).filter(
            ThemeWord.theme_id == theme_id,
            ThemeWord.word_id == word_obj.id
        )
    )
    existing_theme_word = existing.scalars().first()
    if existing_theme_word:
        return existing_theme_word
    
    theme_word = ThemeWord(
        theme_id=theme_id,
        word_id=word_obj.id
    )
    db.add(theme_word)
    await db.commit()
    await db.refresh(theme_word)
    return theme_word

async def get_theme_words(db: Session, theme_id: int) -> List[Word]:
    """Lấy tất cả các từ thuộc một chủ đề"""
    result = await db.execute(
        select(Word).join(ThemeWord).filter(ThemeWord.theme_id == theme_id)
    )
    return result.scalars().all()

# --- AI Metrics operations ---

async def add_ai_metric(db: Session, request_word: str, response_word: str, 
                       quality_score: float, response_time_ms: int,
                       game_id: Optional[str] = None, success: bool = True) -> AIMetric:
    """Thêm thông tin về hiệu suất của AI"""
    metric = AIMetric(
        request_word=request_word,
        response_word=response_word,
        quality_score=quality_score,
        response_time_ms=response_time_ms,
        game_id=game_id,
        success=success
    )
    db.add(metric)
    await db.commit()
    await db.refresh(metric)
    return metric

async def get_ai_performance_stats(db: Session) -> Dict:
    """Lấy thống kê về hiệu suất của AI"""
    # Tổng số lượt
    result = await db.execute(select(func.count()).select_from(AIMetric))
    total = result.scalar()
    
    # Số lượt thành công
    result = await db.execute(select(func.count()).select_from(AIMetric).filter(AIMetric.success == True))
    success_count = result.scalar()
    
    # Thời gian phản hồi trung bình
    result = await db.execute(select(func.avg(AIMetric.response_time_ms)).select_from(AIMetric))
    avg_response_time = result.scalar()
    
    # Điểm chất lượng trung bình
    result = await db.execute(select(func.avg(AIMetric.quality_score)).select_from(AIMetric))
    avg_quality = result.scalar()
    
    return {
        "total_requests": total,
        "success_count": success_count,
        "success_rate": (success_count / total) * 100 if total > 0 else 0,
        "avg_response_time_ms": avg_response_time,
        "avg_quality_score": avg_quality
    }