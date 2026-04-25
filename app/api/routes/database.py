from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.dependencies import get_db
from app.database import crud
from app.database.models import Game, GameMove, Theme, Word

router = APIRouter(prefix="/database", tags=["database"])


async def _count_rows(db: AsyncSession, table_model, condition=None) -> int:
    query = select(func.count()).select_from(table_model)
    if condition is not None:
        query = query.filter(condition)
    result = await db.execute(query)
    return result.scalar() or 0


@router.get("/stats")
async def get_database_stats(db: AsyncSession = Depends(get_db)):
    """Get high-level database statistics."""
    return {
        "words_count": await _count_rows(db, Word),
        "common_words_count": await _count_rows(db, Word, Word.is_common.is_(True)),
        "theme_count": await _count_rows(db, Theme),
        "game_count": await _count_rows(db, Game),
        "move_count": await _count_rows(db, GameMove),
    }


@router.get("/words")
async def get_words(
    limit: int = 100,
    offset: int = 0,
    min_quality: float = 0.0,
    is_common: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get words from the database with optional filtering and pagination."""
    query = select(Word)
    if min_quality > 0:
        query = query.filter(Word.quality_score >= min_quality)
    if is_common is not None:
        query = query.filter(Word.is_common == is_common)

    result = await db.execute(query.offset(offset).limit(limit))
    words = result.scalars().all()
    return [
        {
            "id": word.id,
            "word": word.word,
            "quality_score": word.quality_score,
            "is_common": word.is_common,
            "syllable_count": word.syllable_count,
            "first_syllable": word.first_syllable,
            "last_syllable": word.last_syllable,
        }
        for word in words
    ]


@router.get("/game/{game_id}/moves")
async def get_game_moves(game_id: str, db: AsyncSession = Depends(get_db)):
    """Get move history for a game session."""
    moves = await crud.get_game_moves(db, game_id)
    if not moves:
        raise HTTPException(status_code=404, detail="Game not found or no moves")

    return [
        {
            "move_number": move.move_number,
            "word": move.word_text,
            "is_player": move.is_player,
            "quality_score": move.quality_score,
            "created_at": move.created_at,
        }
        for move in moves
    ]


@router.get("/ai/performance")
async def get_ai_performance(db: AsyncSession = Depends(get_db)):
    """Get AI performance stats from persistence."""
    return await crud.get_ai_performance_stats(db)
