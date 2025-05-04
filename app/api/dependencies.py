from typing import Tuple, AsyncGenerator
from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_service import AIService
from app.services.game_service import GameService
from app.database.base import get_async_db

async def get_services() -> Tuple[AIService, GameService]:
    """Dependency để lấy các instance của services"""
    ai_service = AIService.get_instance()
    game_service = GameService.get_instance()
    return ai_service, game_service

async def get_ai_service() -> AIService:
    """Dependency để lấy instance của AI service"""
    return AIService.get_instance()

async def get_game_service() -> GameService:
    """Dependency để lấy instance của game service"""
    return GameService.get_instance()

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency để lấy database session"""
    async for session in get_async_db():
        yield session

async def validate_service_ready(ai_service: AIService = Depends(get_ai_service)):
    """Dependency để đảm bảo AI service đã sẵn sàng"""
    if not ai_service.is_ready:
        raise HTTPException(
            status_code=503, 
            detail="Model đang khởi tạo, vui lòng thử lại sau."
        )
    return ai_service