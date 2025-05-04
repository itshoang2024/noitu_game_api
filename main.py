import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging

from app.config import settings
from app.api import router
from app.services.ai_service import AIService
from app.utils.logging import setup_logging

# Set up logging
logger = setup_logging()

# Create FastAPI application
app = FastAPI(
    title="Nối Từ Game API",
    description="API cho game nối từ sử dụng Google Gemini",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to your game domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(router)

# Cập nhật trong main.py

# Initialize AI service during startup
@app.on_event("startup")
async def startup_event():
    """Initialize services when the server starts"""
    logger.info(f"Khởi động API nối từ với model {settings.MODEL_ID}")
    
    ai_service = AIService.get_instance()
    
    # Create the data directory if it doesn't exist
    import os
    os.makedirs("./data", exist_ok=True)
    
    # Initialize the word evaluator
    from app.utils.word_evaluator import WordEvaluator
    word_evaluator = WordEvaluator.get_instance()
    await word_evaluator.initialize()
    
    # Chỉ chạy warm-up nếu được bật trong cấu hình
    # if settings.ENABLE_WARM_UP:
    logger.info("Bắt đầu warm-up model...")
    asyncio.create_task(ai_service.warm_up_model())
    # else:
    #     logger.info("Warm-up đã bị tắt trong cấu hình")
        
@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources when the server shuts down"""
    logger.info("Shutting down server")
    ai_service = AIService.get_instance()
    await ai_service.close()

if __name__ == "__main__":
    # Check API key before starting
    if not settings.GEMINI_API_KEY:
        logger.error("ERROR: GEMINI_API_KEY is not set. Exiting.")
    else:
        # Run with reload=True for development, False in production
        uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=settings.DEBUG)
        # uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=False)