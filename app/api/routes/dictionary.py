from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from typing import List

from app.services.ai_service import AIService
from app.api.dependencies import get_ai_service
from app.utils.validators import validate_word_structure

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dictionary", tags=["dictionary"])

@router.get("/stats")
async def get_dictionary_stats(ai_service: AIService = Depends(get_ai_service)):
    """Get statistics about the word dictionary"""
    word_evaluator = ai_service.word_evaluator
    
    await word_evaluator.ensure_initialized()
    
    return {
        "dictionary_size": len(word_evaluator.dictionary),
        "common_words_count": len(word_evaluator.common_words),
        "evaluated_words_count": len(word_evaluator.word_scores)
    }

@router.post("/add")
async def add_word_to_dictionary(
    req: Request,
    ai_service: AIService = Depends(get_ai_service)
):
    """Add a word to the dictionary"""
    try:
        data = await req.json()
        word = data.get("word", "").strip().lower()
        
        if not word:
            raise HTTPException(status_code=400, detail="Từ không được để trống")
        
        word_evaluator = ai_service.word_evaluator
        
        # Validate basic structure
        is_valid, reason = validate_word_structure(word)
        
        if not is_valid:
            return {"status": "error", "message": f"Từ có cấu trúc không hợp lệ: {reason}"}
        
        # Add to dictionary
        result = await word_evaluator.add_to_dictionary(word)
        
        if result:
            # Invalidate cache
            ai_service.quality_scores = {}
            return {"status": "success", "message": f"Đã thêm từ '{word}' vào từ điển"}
        else:
            return {"status": "error", "message": f"Không thể thêm từ '{word}' vào từ điển"}
    
    except Exception as e:
        logger.error(f"Error adding word to dictionary: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Lỗi: {str(e)}")

@router.post("/update_theme_words")
async def update_theme_words(
    req: Request,
    ai_service: AIService = Depends(get_ai_service)
):
    """Cập nhật danh sách từ theo chủ đề từ nguồn bên ngoài"""
    try:
        data = await req.json()
        theme = data.get("theme")
        words = data.get("words", [])
        
        if not theme:
            raise HTTPException(status_code=400, detail="Thiếu thông tin về chủ đề")
        
        if not words or not isinstance(words, list):
            raise HTTPException(status_code=400, detail="Danh sách từ không hợp lệ")
        
        # Lọc các từ hợp lệ (ít nhất 2 âm tiết)
        valid_words = []
        for word in words:
            if not isinstance(word, str):
                continue
                
            word = word.strip().lower()
            if len(word.split()) >= 2:
                valid_words.append(word)
        
        if not valid_words:
            return {"status": "error", "message": "Không có từ hợp lệ nào để cập nhật"}
        
        # Thực hiện cập nhật vào bộ nhớ đệm
        ai_service.quality_tracker.theme_words_cache[theme] = valid_words
        
        # Thực hiện đánh giá chất lượng trong nền
        background_tasks = BackgroundTasks()
        background_tasks.add_task(evaluate_theme_words_quality, ai_service, theme, valid_words)
        
        return {
            "status": "success", 
            "message": f"Đã cập nhật {len(valid_words)} từ cho chủ đề '{theme}'",
            "words": valid_words
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Lỗi khi cập nhật từ theo chủ đề: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {str(e)}")

async def evaluate_theme_words_quality(ai_service: AIService, theme: str, words: List[str]):
    """Đánh giá chất lượng từ theo chủ đề trong nền"""
    logger.info(f"Bắt đầu đánh giá chất lượng {len(words)} từ cho chủ đề '{theme}'")
    
    for word in words:
        if word not in ai_service.quality_scores:
            try:
                quality, reason = await ai_service.word_evaluator.evaluate_word(word)
                ai_service.quality_scores[word] = quality
                logger.debug(f"Đánh giá từ '{word}': {quality:.2f} - {reason}")
            except Exception as e:
                logger.error(f"Lỗi đánh giá từ '{word}': {str(e)}")
    
    logger.info(f"Hoàn thành đánh giá từ cho chủ đề '{theme}'")

