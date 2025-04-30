import time
import logging
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Depends, Body
from app.utils.validators import validate_word_chain

from app.models.schemas import (
    WordRequest, WordResponse, StatusResponse, CacheResponse,
    ResetResponse, SessionResponse, ValidationResponse, 
    SuggestionResponse, ExplanationResponse
)
from app.services.ai_service import AIService
from app.services.game_service import GameService
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Helper function to get services
def get_services():
    ai_service = AIService.get_instance()
    game_service = GameService.get_instance()
    return ai_service, game_service

@router.post("/ask", response_model=WordResponse)
async def ask_ai(req: Request, background_tasks: BackgroundTasks):
    """Main endpoint to get word responses"""
    ai_service, game_service = get_services()
    
    # Check if AI is ready
    if not ai_service.is_ready:
        raise HTTPException(status_code=503, detail="Model is initializing, please try again shortly.")
    
    try:
        # Parse request
        data = await req.json()
        user_input = data.get("prompt", "").strip().lower()
        session_id = data.get("session_id", "default")
        
        # Validate input
        if not user_input:
            raise HTTPException(status_code=400, detail="Vui lòng nhập một từ để nối.")
        
        # Check if word has been used before in this session
        if game_service.is_word_used(session_id, user_input):
            return WordResponse(
                answer="Từ này đã được sử dụng, vui lòng chọn một từ khác",
                status="error",
                model=settings.MODEL_ID
            )
        
        MAX_RETRY = 3
        attempts = 0
        reply = None

        while attempts < MAX_RETRY:
            reply = await ai_service.generate_response(user_input)

            if not reply or reply.startswith("Lỗi:"):
                logger.error(f"AI error on attempt {attempts+1}: {reply}")
                raise HTTPException(status_code=500, detail=f"AI failed to generate a response. {reply}")

            if not game_service.validate_word_pair(user_input, reply):
                logger.error(f"AI error on attempt {attempts+1}: {reply}")
                raise HTTPException(status_code=500, detail=f"AI failed to generate a response. {reply}")

            if game_service.is_word_used(session_id, reply):
                logger.info(f"Từ '{reply}' đã được dùng, thử lại...")
                attempts += 1
                continue

            is_valid, reason = await ai_service.validate_vietnamese_word(reply)
            if not is_valid:
                logger.info(f"Từ '{reply}' không hợp lệ: {reason}, thử lại...")
                attempts += 1
                continue

            # Nếu vừa chưa dùng và hợp lệ thì dùng được
            break

        # Nếu vẫn không tìm được từ phù hợp sau MAX_RETRY lần
        if not reply or game_service.is_word_used(session_id, reply):
            return WordResponse(
                answer="Không thể tìm được từ phù hợp, vui lòng thử lại.",
                status="unfound",
                model=settings.MODEL_ID
            )

        # If successful, register the AI's word in the used words
        game_service.register_word(session_id, reply)
        
        # Run cleanup in background occasionally
        if session_id != "default":
            background_tasks.add_task(game_service.cleanup_old_sessions)
        
        return WordResponse(
            answer=reply,
            status="success",
            model=settings.MODEL_ID
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/status", response_model=StatusResponse)
async def check_status():
    """Check the status of the AI service"""
    ai_service, _ = get_services()
    
    return StatusResponse(
        status="ready" if ai_service.is_ready else "initializing",
        cached_words=ai_service.get_cached_words(),
        model=settings.MODEL_ID,
        api_provider="Google Gemini"
    )

@router.get("/cache", response_model=CacheResponse)
async def view_cache():
    """View the current word cache (for debugging)"""
    ai_service, _ = get_services()
    return CacheResponse(cache=ai_service.get_cache())

@router.post("/reset", response_model=ResetResponse)
async def reset_cache():
    """Reset the word cache (for debugging)"""
    ai_service, _ = get_services()
    count = ai_service.reset_cache()
    return ResetResponse(status=f"Cache đã được xóa ({count} items removed)")

@router.get("/start_game", response_model=SessionResponse)
async def start_game():
    """Start a new game session"""
    _, game_service = get_services()
    session_id = game_service.create_session()
    return SessionResponse(session_id=session_id, status="success")

@router.post("/validate", response_model=ValidationResponse)
async def validate_word(req: Request):
    """Validate if a word is valid Vietnamese"""
    ai_service, _ = get_services()
    
    try:
        data = await req.json()
        word = data.get("word", "").strip().lower()
        
        if not word:
            return ValidationResponse(valid=False, reason="Từ trống")
        
        # Basic validation (at least 2 syllables)
        syllables = word.split()
        if len(syllables) < 2:
            return ValidationResponse(valid=False, reason="Từ phải có ít nhất 2 âm tiết")
        
        # Validate using AI service
        is_valid, reason = await ai_service.validate_vietnamese_word(word)
        return ValidationResponse(valid=is_valid, reason=reason)
        
    except Exception as e:
        logger.error(f"Error validating word: {str(e)}")
        return ValidationResponse(valid=False, reason=f"Lỗi hệ thống: {str(e)}")

@router.get("/suggest", response_model=SuggestionResponse)
async def suggest_words(starting_syllable: str = ""):
    """Suggest words starting with a specific syllable"""
    ai_service, _ = get_services()
    suggestions = await ai_service.suggest_words(starting_syllable)
    return SuggestionResponse(suggestions=suggestions)

@router.get("/explain", response_model=ExplanationResponse)
async def explain_word(word: str):
    """Get explanation for a word"""
    if not word:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp từ cần giải thích")
    
    ai_service, _ = get_services()
    try:
        explanation = await ai_service.explain_word(word)
        if explanation.startswith("Lỗi:"):
            raise HTTPException(status_code=500, detail=explanation)
        return ExplanationResponse(word=word, explanation=explanation)
    except Exception as e:
        logger.error(f"Lỗi khi giải thích từ '{word}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Không thể giải thích từ: {str(e)}")

@router.get("/stats/{session_id}")
async def get_game_stats(session_id: str):
    """Get statistics for a game session"""
    _, game_service = get_services()
    stats = game_service.get_session_stats(session_id)
    
    if not stats:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên game")
    
    return stats

@router.post("/check_pair")
async def check_word_pair(req: Request):
    """Check if a word pair follows the game rules"""
    try:
        data = await req.json()
        input_word = data.get("input_word", "").strip().lower()
        response_word = data.get("response_word", "").strip().lower()
        
        if not input_word or not response_word:
            raise HTTPException(status_code=400, detail="Vui lòng cung cấp cả hai từ")
        
        _, game_service = get_services()
        valid = game_service.validate_word_pair(input_word, response_word)
        
        return {
            "valid": valid,
            "reason": "Hợp lệ" if valid else "Từ phản hồi không bắt đầu bằng âm tiết cuối của từ nhập vào"
        }
    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra cặp từ: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {str(e)}")
    
@router.post("/new_word", response_model=WordResponse)
async def get_starting_word(data: dict = Body(...)):
    """Trả về một từ bắt đầu ngẫu nhiên cho phiên chơi"""
    ai_service, game_service = get_services()
    
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Thiếu session_id")

    # Chọn ngẫu nhiên một từ khởi đầu từ danh sách cấu hình
    import random
    word = random.choice(settings.WARM_UP_WORDS)

    # Đăng ký từ đó vào session
    game_service.register_word(session_id, word)

    return WordResponse(
        answer=word,
        status="success",
        model=settings.MODEL_ID
    )


