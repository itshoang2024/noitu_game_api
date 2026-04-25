import logging
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.dependencies import get_ai_service
from app.models.schemas import DictionaryWordRequest, ThemeWordsUpdateRequest
from app.services.ai_service import AIService
from app.utils.validators import validate_word_structure

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dictionary", tags=["dictionary"])


def _normalize_words(words: List[str]) -> List[str]:
    normalized_words: List[str] = []
    for word in words:
        if not isinstance(word, str):
            continue

        normalized_word = word.strip().lower()
        if len(normalized_word.split()) >= 2:
            normalized_words.append(normalized_word)

    return normalized_words


@router.get("/stats")
async def get_dictionary_stats(ai_service: AIService = Depends(get_ai_service)):
    """Get statistics about the word dictionary."""
    word_evaluator = ai_service.word_evaluator
    await word_evaluator.ensure_initialized()
    return {
        "dictionary_size": len(word_evaluator.dictionary),
        "common_words_count": len(word_evaluator.common_words),
        "evaluated_words_count": len(word_evaluator.word_scores),
    }


@router.post("/add")
async def add_word_to_dictionary(
    data: DictionaryWordRequest,
    ai_service: AIService = Depends(get_ai_service),
):
    """Add a word to the dictionary."""
    try:
        word = data.word.strip().lower()
        if not word:
            raise HTTPException(status_code=400, detail="Từ không được để trống")

        is_valid, reason = validate_word_structure(word)
        if not is_valid:
            return {"status": "error", "message": f"Từ có cấu trúc không hợp lệ: {reason}"}

        if not await ai_service.word_evaluator.add_to_dictionary(word):
            return {"status": "error", "message": f"Không thể thêm từ '{word}' vào từ điển"}

        ai_service.quality_scores = {}
        return {"status": "success", "message": f"Đã thêm từ '{word}' vào từ điển"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error adding word to dictionary: {str(exc)}")
        raise HTTPException(status_code=500, detail=f"Lỗi: {str(exc)}")


@router.post("/update_theme_words")
async def update_theme_words(
    data: ThemeWordsUpdateRequest,
    background_tasks: BackgroundTasks,
    ai_service: AIService = Depends(get_ai_service),
):
    """Update theme words from an external source."""
    try:
        theme = data.theme.strip().lower()
        if not theme:
            raise HTTPException(status_code=400, detail="Thiếu thông tin về chủ đề")

        valid_words = _normalize_words(data.words)
        if not valid_words:
            return {"status": "error", "message": "Không có từ hợp lệ nào để cập nhật"}

        ai_service.quality_tracker.theme_words_cache[theme] = valid_words
        background_tasks.add_task(evaluate_theme_words_quality, ai_service, theme, valid_words)
        return {
            "status": "success",
            "message": f"Đã cập nhật {len(valid_words)} từ cho chủ đề '{theme}'",
            "words": valid_words,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Lỗi khi cập nhật từ theo chủ đề: {str(exc)}")
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {str(exc)}")


async def evaluate_theme_words_quality(ai_service: AIService, theme: str, words: List[str]):
    """Evaluate theme word quality in the background."""
    logger.info(f"Bắt đầu đánh giá chất lượng {len(words)} từ cho chủ đề '{theme}'")

    for word in words:
        if word in ai_service.quality_scores:
            continue

        try:
            quality, reason = await ai_service.word_evaluator.evaluate_word(word)
            ai_service.quality_scores[word] = quality
            logger.debug(f"Đánh giá từ '{word}': {quality:.2f} - {reason}")
        except Exception as exc:
            logger.error(f"Lỗi đánh giá từ '{word}': {str(exc)}")

    logger.info(f"Hoàn thành đánh giá từ cho chủ đề '{theme}'")
