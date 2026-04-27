import asyncio
import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.config import settings
from app.database.base import Base, engine
from app.services.ai_service import AIService
from app.utils.logging import setup_logging
from app.utils.word_evaluator import WordEvaluator

logger = setup_logging()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Nối Từ Game API",
        description="API cho game nối từ sử dụng Google Gemini",
        version="3.10",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()


@app.on_event("startup")
async def startup_event():
    """Initialize services when the server starts."""
    logger.info(f"Khởi động API nối từ với model {settings.MODEL_ID}")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created or verified")

    os.makedirs("./data", exist_ok=True)
    word_evaluator = WordEvaluator.get_instance()
    await word_evaluator.initialize()

    ai_service = AIService.get_instance()
    if settings.ENABLE_WARM_UP:
        logger.info("Bắt đầu warm-up model...")
        asyncio.create_task(ai_service.warm_up_model())
    else:
        logger.info("Warm-up disabled by ENABLE_WARM_UP=False")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources when the server shuts down."""
    logger.info("Shutting down server")
    ai_service = AIService.get_instance()
    await ai_service.close()


if __name__ == "__main__":
    if not settings.GEMINI_API_KEY:
        logger.error("ERROR: GEMINI_API_KEY is not set. Exiting.")
    else:
        uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=settings.DEBUG)
