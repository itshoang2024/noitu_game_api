from fastapi import APIRouter, Request, Depends, BackgroundTasks, HTTPException
from app.models.schemas import WordResponse
from app.services.ai_service import AIService
from app.services.game_service import GameService
from app.api.dependencies import validate_service_ready, get_game_service
from app.models.schemas import WordResponse
from app.config import settings
from app.utils.validators import validate_word_structure

import logging
logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

async def _validate_input_word(word: str, session_id: str, game_service: GameService) -> None:
    """Validate user input word and raise appropriate exceptions"""
    if not word:
        raise HTTPException(status_code=400, detail="Vui lòng nhập một từ để nối.")
    
    # Check if word has been used before in this session
    if game_service.is_word_used(session_id, word):
        raise HTTPException(
            status_code=400, 
            detail="Từ này đã được sử dụng, vui lòng chọn một từ khác"
        )

async def _add_word_to_dictionary_background(
    word: str, 
    word_evaluator, 
    background_tasks: BackgroundTasks
):
    """Add valid words to dictionary in background"""
    is_valid_structure, _ = validate_word_structure(word)
    if is_valid_structure and not word_evaluator.is_in_dictionary(word):
        logger.info(f"Adding new word from player: '{word}'")
        background_tasks.add_task(word_evaluator.add_to_dictionary, word)

async def _generate_quality_response(
    user_input: str,
    session_id: str,
    ai_service: AIService,
    game_service: GameService,
    background_tasks: BackgroundTasks,
    max_retry: int = 3,
    quality_threshold: float = 0.4
) -> WordResponse:
    """Generate high-quality response with retry logic"""
    attempts = 0
    reply = None
    best_score = 0.0
    best_reply = None

    while attempts < max_retry:
        try:
            # Generate high-quality response
            reply, score = await ai_service.generate_high_quality_response(
                user_input, 
                max_attempts=2,
                quality_threshold=quality_threshold,
                session_id=session_id
            )
            
            logger.info(f"Attempt {attempts+1}/{max_retry}: Generated '{reply}' with quality score {score:.2f}")

            # Check for errors
            if not reply or reply.startswith("Lỗi:"):
                logger.error(f"AI error on attempt {attempts+1}: {reply}")
                attempts += 1
                continue

            # Validate word follows game rules
            if not game_service.validate_word_pair(user_input, reply):
                logger.error(f"Invalid word pair on attempt {attempts+1}: {user_input} -> {reply}")
                attempts += 1
                continue

            # Check if word was used in this session
            if game_service.is_word_used(session_id, reply):
                logger.info(f"Từ '{reply}' đã được dùng, thử lại...")
                attempts += 1
                continue

            # Validate word has meaning
            is_valid, reason = await ai_service.validate_vietnamese_word(reply)
            if not is_valid:
                logger.info(f"Từ '{reply}' không hợp lệ: {reason}, thử lại...")
                attempts += 1
                continue

            # Check quality score
            if score < quality_threshold:
                # Keep track of best response so far
                if score > best_score:
                    best_score = score
                    best_reply = reply
                
                # Only retry if we haven't reached the maximum attempts
                if attempts < max_retry - 1:
                    logger.info(f"Từ '{reply}' có chất lượng thấp (score: {score:.2f}), thử lại...")
                    attempts += 1
                    continue
            
            # If word passes all checks, use it
            break
        except Exception as e:
            logger.error(f"Error during generation attempt {attempts+1}: {str(e)}")
            return WordResponse(
                answer=f"Đã xảy ra lỗi khi tìm từ: {str(e)}",
                status="error",
                model=settings.MODEL_ID
            )
        
        finally:
            attempts += 1

    # If we still don't have a valid response after all attempts
    if not reply or game_service.is_word_used(session_id, reply):
        # Use best reply if we have one with at least some quality
        if best_reply and best_score > 0.2:
            reply = best_reply
            score = best_score
        else:
            return WordResponse(
                answer="Không thể tìm được từ phù hợp, vui lòng thử lại.",
                status="unfound",
                model=settings.MODEL_ID
            )
        
    # CRITICAL: Add this check to make sure the final word follows game rules
    if not game_service.validate_word_pair(user_input, reply):
        return WordResponse(
            answer="Không thể tìm được từ phù hợp theo luật nối từ. Vui lòng thử lại.",
            status="unfound",  # Thay đổi từ invalid_chain sang unfound
            model=settings.MODEL_ID
        )

    # Register the AI's word in the used words
    game_service.register_word(session_id, reply)
    
    # Add to word evaluator dictionary in background
    word_evaluator = ai_service.word_evaluator
    background_tasks.add_task(word_evaluator.add_to_dictionary, reply)
    
    return WordResponse(
        answer=reply,
        status="success",
        model=settings.MODEL_ID,
        metadata={
            "quality_score": f"{score:.2f}" if score > 0 else f"{quality_threshold:.2f}"
        }
    )

@router.post("/ask", response_model=WordResponse)
async def ask_ai(
    req: Request, 
    background_tasks: BackgroundTasks,
    ai_service: AIService = Depends(validate_service_ready),
    game_service: GameService = Depends(get_game_service)
):
    """Main endpoint to get word responses"""
    try:
        # Parse request
        data = await req.json()
        user_input = data.get("prompt", "").strip().lower()
        session_id = data.get("session_id", "default")
        
        # Validate input
        await _validate_input_word(user_input, session_id, game_service)
        
        # Add valid words to dictionary
        await _add_word_to_dictionary_background(
            user_input, 
            ai_service.word_evaluator, 
            background_tasks
        )
        
        # Generate response
        response = await _generate_quality_response(
            user_input, 
            session_id, 
            ai_service, 
            game_service, 
            background_tasks
        )
        
        # Run cleanup in background occasionally
        if session_id != "default":
            background_tasks.add_task(game_service.cleanup_old_sessions)
            
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
    
