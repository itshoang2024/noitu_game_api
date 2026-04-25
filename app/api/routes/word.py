import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_ai_service
from app.models.schemas import (
    ExplanationResponse,
    SuggestionResponse,
    ValidationResponse,
    WordMeaningRequest,
    WordValidationRequest,
)
from app.services.ai_service import AIService
from app.utils.validators import validate_word_structure

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/word", tags=["word"])


@router.post("/validate", response_model=ValidationResponse)
async def validate_word(
    data: WordValidationRequest,
    ai_service: AIService = Depends(get_ai_service),
):
    """Validate if a word is valid Vietnamese."""
    try:
        word = data.word.strip().lower()
        if not word:
            return ValidationResponse(valid=False, reason="Từ trống")

        if len(word.split()) < 2:
            return ValidationResponse(valid=False, reason="Từ phải có ít nhất 2 âm tiết")

        is_valid, reason = await ai_service.validate_vietnamese_word(word)
        return ValidationResponse(valid=is_valid, reason=reason)
    except Exception as exc:
        logger.error(f"Error validating word: {str(exc)}")
        return ValidationResponse(valid=False, reason=f"Lỗi hệ thống: {str(exc)}")


@router.get("/suggest", response_model=SuggestionResponse)
async def suggest_words(
    starting_syllable: str = "",
    ai_service: AIService = Depends(get_ai_service),
):
    """Suggest words starting with a specific syllable."""
    suggestions = await ai_service.suggest_words(starting_syllable)
    return SuggestionResponse(suggestions=suggestions)


@router.get("/explain", response_model=ExplanationResponse)
async def explain_word(
    word: str,
    ai_service: AIService = Depends(get_ai_service),
):
    """Get explanation for a word."""
    if not word:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp từ cần giải thích")

    try:
        explanation = await ai_service.explain_word(word)
        if explanation.startswith("Lá»—i:") or explanation.startswith("Lỗi:"):
            raise HTTPException(status_code=500, detail=explanation)
        return ExplanationResponse(word=word, explanation=explanation)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Lỗi khi giải thích từ '{word}': {str(exc)}")
        raise HTTPException(status_code=500, detail=f"Không thể giải thích từ: {str(exc)}")


@router.post("/check_meaning")
async def check_word_meaning(
    data: WordMeaningRequest,
    ai_service: AIService = Depends(get_ai_service),
):
    """Check if a word is valid Vietnamese and has meaning."""
    try:
        word = data.word.strip().lower()
        if not word:
            raise HTTPException(status_code=400, detail="Từ không được để trống")

        structure_valid, structure_reason = validate_word_structure(word)
        word_evaluator = ai_service.word_evaluator
        in_dictionary = word_evaluator.is_in_dictionary(word)
        has_meaning, meaning_reason = await ai_service.check_word_meaning(word)
        quality_score, quality_reason = await word_evaluator.evaluate_word(word)

        if has_meaning and not in_dictionary:
            await word_evaluator.add_to_dictionary(word)
            in_dictionary = True

        return {
            "word": word,
            "structure_valid": structure_valid,
            "structure_reason": structure_reason,
            "in_dictionary": in_dictionary,
            "has_meaning": has_meaning,
            "meaning_reason": meaning_reason,
            "quality_score": quality_score,
            "quality_reason": quality_reason,
            "final_result": structure_valid and has_meaning,
            "final_reason": meaning_reason if has_meaning else structure_reason,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error checking word: {str(exc)}")
        raise HTTPException(status_code=500, detail=f"Lỗi: {str(exc)}")


@router.get("/quality/{word}")
async def get_word_quality(
    word: str,
    ai_service: AIService = Depends(get_ai_service),
):
    """Get the quality score for a specific word."""
    if not word:
        raise HTTPException(status_code=400, detail="Từ không được để trống")

    word_evaluator = ai_service.word_evaluator
    score, reason = await word_evaluator.evaluate_word(word)
    return {
        "word": word,
        "quality_score": score,
        "reason": reason,
        "is_in_dictionary": word_evaluator.is_in_dictionary(word),
        "is_common_word": word_evaluator.is_common_word(word),
    }
