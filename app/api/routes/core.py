import logging
from typing import Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.api.dependencies import get_game_service, validate_service_ready
from app.config import settings
from app.models.schemas import WordResponse
from app.services.ai_service import AIService
from app.services.game_service import GameService
from app.utils.validators import validate_word_structure

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

async def _validate_input_word(word: str, session_id: str, game_service: GameService) -> None:
    """Validate user input word and raise appropriate exceptions"""
    if not word:
        raise HTTPException(status_code=400, detail="Vui lòng nhập một từ để nối.")

    if await game_service.is_word_used(session_id, word):
        raise HTTPException(
            status_code=400,
            detail="Từ này đã được sử dụng, vui lòng chọn một từ khác",
        )

async def _add_word_to_dictionary_background(
    word: str,
    word_evaluator, 
    background_tasks: BackgroundTasks,
):
    """Add valid words to dictionary in background"""
    is_valid_structure, _ = validate_word_structure(word)
    if is_valid_structure and not word_evaluator.is_in_dictionary(word):
        logger.info(f"Adding new word from player: '{word}'")
        background_tasks.add_task(word_evaluator.add_to_dictionary, word)


def _error_response(message: str) -> WordResponse:
    return WordResponse(answer=message, status="error", model=settings.MODEL_ID)


def _unfound_response(message: str) -> WordResponse:
    return WordResponse(answer=message, status="unfound", model=settings.MODEL_ID)


async def _validate_generated_reply(
    user_input: str,
    reply: str,
    session_id: str,
    ai_service: AIService,
    game_service: GameService,
) -> Tuple[bool, str]:
    if not reply or reply.startswith("Lỗi:"):
        return False, "ai_error"

    if not game_service.validate_word_pair(user_input, reply):
        return False, "invalid_pair"

    if await game_service.is_word_used(session_id, reply):
        return False, "used_word"

    is_valid_word, reason = await ai_service.validate_vietnamese_word(reply)
    if not is_valid_word:
        return False, f"invalid_word:{reason}"

    return True, ""


def _log_retry_reason(reason: str, attempt: int, max_retry: int, user_input: str, reply: str) -> None:
    if reason == "ai_error":
        logger.error(f"AI error on attempt {attempt}/{max_retry}: {reply}")
        return

    if reason == "invalid_pair":
        logger.error(f"Invalid word pair on attempt {attempt}/{max_retry}: {user_input} -> {reply}")
        return

    if reason == "used_word":
        logger.info(f"Từ '{reply}' đã được dùng, thử lại...")
        return

    if reason.startswith("invalid_word:"):
        logger.info(f"Từ '{reply}' không hợp lệ: {reason.split(':', 1)[1]}, thử lại...")

async def _generate_quality_response(
    user_input: str,
    session_id: str,
    ai_service: AIService,
    game_service: GameService,
    background_tasks: BackgroundTasks,
    max_retry: int = settings.MAX_RETRIES,
    quality_threshold: float = 0.4,
) -> WordResponse:
    """Generate high-quality response with retry logic"""
    selected_reply: Optional[str] = None
    selected_score = quality_threshold
    best_score = 0.0
    best_reply: Optional[str] = None

    for attempt in range(1, max_retry + 1):
        try:
            reply, score = await ai_service.generate_high_quality_response(
                user_input,
                session_id=session_id,
                game_service=game_service,
                max_attempts=2,
                quality_threshold=quality_threshold,
            )

            logger.info(f"Attempt {attempt}/{max_retry}: Generated '{reply}' with quality score {score:.2f}")

            is_valid_reply, reason = await _validate_generated_reply(
                user_input=user_input,
                reply=reply,
                session_id=session_id,
                ai_service=ai_service,
                game_service=game_service,
            )
            if not is_valid_reply:
                _log_retry_reason(reason, attempt, max_retry, user_input, reply)
                continue

            if score < quality_threshold and attempt < max_retry:
                if score > best_score:
                    best_score = score
                    best_reply = reply

                logger.info(f"Từ '{reply}' có chất lượng thấp (score: {score:.2f}), thử lại...")
                continue

            selected_reply = reply
            selected_score = score
            break
        except Exception as exc:
            logger.error(f"Error during generation attempt {attempt}: {str(exc)}")
            return _error_response(f"Đã xảy ra lỗi khi tìm từ: {str(exc)}")

    if not selected_reply:
        if best_reply and best_score > 0.2:
            selected_reply = best_reply
            selected_score = best_score
        else:
            return _unfound_response("Không thể tìm được từ phù hợp, vui lòng thử lại.")

    if await game_service.is_word_used(session_id, selected_reply):
        return _unfound_response("Không thể tìm được từ phù hợp, vui lòng thử lại.")

    if not game_service.validate_word_pair(user_input, selected_reply):
        return _unfound_response("Không thể tìm được từ phù hợp theo luật nối từ. Vui lòng thử lại.")

    await game_service.register_word(session_id, selected_reply)
    background_tasks.add_task(ai_service.word_evaluator.add_to_dictionary, selected_reply)

    return WordResponse(
        answer=selected_reply,
        status="success",
        model=settings.MODEL_ID,
        metadata={
            "quality_score": (
                f"{selected_score:.2f}" if selected_score > 0 else f"{quality_threshold:.2f}"
            )
        },
    )

@router.post("/ask", response_model=WordResponse)
async def ask_ai(
    req: Request,
    background_tasks: BackgroundTasks,
    ai_service: AIService = Depends(validate_service_ready),
    game_service: GameService = Depends(get_game_service),
):
    """Main endpoint to get word responses"""
    try:
        data = await req.json()
        user_input = data.get("prompt", "").strip().lower()
        session_id = data.get("session_id", "default")

        await _validate_input_word(user_input, session_id, game_service)

        await _add_word_to_dictionary_background(
            user_input,
            ai_service.word_evaluator,
            background_tasks,
        )

        response = await _generate_quality_response(
            user_input,
            session_id,
            ai_service,
            game_service,
            background_tasks,
        )

        if session_id != "default":
            background_tasks.add_task(game_service.cleanup_old_sessions)

        return response

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error processing request: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")
    
