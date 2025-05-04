from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Dict, Any
from sqlalchemy.future import select

from app.database import crud
from app.api.dependencies import get_db
from app.database.models import Word, Game, GameMove, Theme
from sqlalchemy import func

router = APIRouter(prefix="/database", tags=["database"])

@router.get("/stats")
async def get_database_stats(db: AsyncSession = Depends(get_db)):
    """Lấy thống kê về database"""
    # Đếm tổng số từ
    result = await db.execute(select(func.count()).select_from(Word))
    word_count = result.scalar()
    
    # Đếm số từ phổ biến
    result = await db.execute(select(func.count()).select_from(Word).filter(Word.is_common == True))
    common_words_count = result.scalar()
    
    # Đếm số chủ đề
    result = await db.execute(select(func.count()).select_from(Theme))
    theme_count = result.scalar()
    
    # Đếm số game
    result = await db.execute(select(func.count()).select_from(Game))
    game_count = result.scalar()
    
    # Đếm số lượt chơi
    result = await db.execute(select(func.count()).select_from(GameMove))
    move_count = result.scalar()
    
    return {
        "words_count": word_count,
        "common_words_count": common_words_count,
        "theme_count": theme_count,
        "game_count": game_count,
        "move_count": move_count
    }

@router.get("/words")
async def get_words(
    limit: int = 100, 
    offset: int = 0,
    min_quality: float = 0.0,
    is_common: bool = None,
    db: AsyncSession = Depends(get_db)
):
    """Lấy danh sách từ từ database"""
    query = select(Word)
    
    # Apply filters
    if min_quality > 0:
        query = query.filter(Word.quality_score >= min_quality)
    
    if is_common is not None:
        query = query.filter(Word.is_common == is_common)
    
    # Apply pagination
    query = query.offset(offset).limit(limit)
    
    result = await db.execute(query)
    words = result.scalars().all()
    
    return [
        {
            "id": word.id,
            "word": word.word,
            "quality_score": word.quality_score,
            "is_common": word.is_common,
            "syllable_count": word.syllable_count,
            "first_syllable": word.first_syllable,
            "last_syllable": word.last_syllable
        }
        for word in words
    ]

@router.get("/game/{game_id}/moves")
async def get_game_moves(game_id: str, db: AsyncSession = Depends(get_db)):
    """Lấy danh sách các lượt đi trong một phiên chơi"""
    moves = await crud.get_game_moves(db, game_id)
    if not moves:
        raise HTTPException(status_code=404, detail="Game not found or no moves")
    
    return [
        {
            "move_number": move.move_number,
            "word": move.word_text,
            "is_player": move.is_player,
            "quality_score": move.quality_score,
            "created_at": move.created_at
        }
        for move in moves
    ]

@router.get("/ai/performance")
async def get_ai_performance(db: AsyncSession = Depends(get_db)):
    """Lấy thống kê về hiệu suất của AI"""
    stats = await crud.get_ai_performance_stats(db)
    return stats