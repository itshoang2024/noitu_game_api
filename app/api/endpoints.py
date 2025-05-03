import time
import logging
from typing import Tuple, Dict, Any, Optional, List

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Body, Depends
from fastapi.responses import JSONResponse

from app.models.schemas import (
    WordRequest, WordResponse, StatusResponse, CacheResponse,
    ResetResponse, SessionResponse, ValidationResponse, 
    SuggestionResponse, ExplanationResponse
)
from app.services.ai_service import AIService
from app.services.game_service import GameService
from app.config import settings
from app.utils.validators import validate_word_structure, validate_word_chain

logger = logging.getLogger(__name__)

# Create main router
router = APIRouter()

# Create sub-routers by functionality
game_router = APIRouter(prefix="/game", tags=["game"])
word_router = APIRouter(prefix="/word", tags=["word"])
dictionary_router = APIRouter(prefix="/dictionary", tags=["dictionary"])
system_router = APIRouter(prefix="/system", tags=["system"])

# ---------------------------------------------------------------------------
# Dependency Injection
# ---------------------------------------------------------------------------

def get_services() -> Tuple[AIService, GameService]:
    """Dependency to get service instances"""
    ai_service = AIService.get_instance()
    game_service = GameService.get_instance()
    return ai_service, game_service

def get_ai_service() -> AIService:
    """Dependency to get AI service instance"""
    return AIService.get_instance()

def get_game_service() -> GameService:
    """Dependency to get game service instance"""
    return GameService.get_instance()

async def validate_service_ready(ai_service: AIService = Depends(get_ai_service)):
    """Dependency to ensure AI service is ready"""
    if not ai_service.is_ready:
        raise HTTPException(
            status_code=503, 
            detail="Model is initializing, please try again shortly."
        )
    return ai_service

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

# ---------------------------------------------------------------------------
# Core Functionality Endpoints
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Game Management Endpoints
# ---------------------------------------------------------------------------

@game_router.get("/start", response_model=SessionResponse)
async def start_game(game_service: GameService = Depends(get_game_service)):
    """Start a new game session"""
    session_id = game_service.create_session()
    return SessionResponse(session_id=session_id, status="success")

@game_router.get("/stats/{session_id}")
async def get_game_stats(
    session_id: str,
    game_service: GameService = Depends(get_game_service)
):
    """Get statistics for a game session"""
    stats = game_service.get_session_stats(session_id)
    
    if not stats:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên game")
    
    return stats

@game_router.post("/check_pair")
async def check_word_pair(
    req: Request,
    game_service: GameService = Depends(get_game_service)
):
    """Check if a word pair follows the game rules"""
    try:
        data = await req.json()
        input_word = data.get("input_word", "").strip().lower()
        response_word = data.get("response_word", "").strip().lower()
        
        if not input_word or not response_word:
            raise HTTPException(status_code=400, detail="Vui lòng cung cấp cả hai từ")
        
        valid = game_service.validate_word_pair(input_word, response_word)
        
        return {
            "valid": valid,
            "reason": "Hợp lệ" if valid else "Từ phản hồi không bắt đầu bằng âm tiết cuối của từ nhập vào"
        }
    except Exception as e:
        logger.error(f"Lỗi khi kiểm tra cặp từ: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {str(e)}")

@game_router.post("/new_word", response_model=WordResponse)
async def get_starting_word(
    data: dict = Body(...),
    ai_service: AIService = Depends(get_ai_service),
    game_service: GameService = Depends(get_game_service)
):
    """Trả về một từ bắt đầu cho phiên chơi với khả năng tùy chọn chủ đề"""
    session_id = data.get("session_id")
    theme = data.get("theme", "random")  # Chủ đề, mặc định là ngẫu nhiên
    
    if not session_id:
        raise HTTPException(status_code=400, detail="Thiếu session_id")
    
    # Lấy evaluator từ ai_service
    word_evaluator = ai_service.word_evaluator
    
    # Đảm bảo evaluator đã được khởi tạo
    await word_evaluator.ensure_initialized()
    
    # Danh sách từ để chọn
    candidate_words = []
    
    # 1. Tùy theo chủ đề, chọn các từ phù hợp
    if theme == "random":
        # Lấy từ danh sách từ phổ biến trước tiên
        candidate_words = list(word_evaluator.common_words)
        
        # Nếu có ít hơn 20 từ phổ biến, bổ sung thêm từ từ điển
        if len(candidate_words) < 20:
            # Lấy ngẫu nhiên thêm từ từ từ điển chính
            import random
            additional_words = random.sample(
                list(word_evaluator.dictionary - word_evaluator.common_words),
                min(50, len(word_evaluator.dictionary) - len(word_evaluator.common_words))
            )
            candidate_words.extend(additional_words)
    else:
        # Tạo từ theo chủ đề cụ thể sử dụng phương thức của ai_service
        theme_words = await ai_service.get_theme_words(theme)
        if theme_words:
            candidate_words = theme_words
        else:
            # Nếu không có từ theo chủ đề, quay lại danh sách mặc định
            candidate_words = list(word_evaluator.common_words)
    
    # 2. Nếu vẫn không có từ, sử dụng danh sách từ cấu hình
    if not candidate_words:
        candidate_words = settings.WARM_UP_WORDS
    
    # 3. Đánh giá và sắp xếp các từ theo chất lượng
    scored_words = []
    score = 0.0
    
    for word in candidate_words:
        # Bỏ qua từ một âm tiết
        if len(word.split()) < 2:
            continue
            
        # Kiểm tra xem từ đã được sử dụng chưa
        if game_service.is_word_used(session_id, word):
            continue
            
        # Lấy điểm chất lượng
        score = ai_service.quality_scores.get(word, None)
        if score is None:
            # Nếu chưa có điểm, tính toán nhanh
            score_tuple = await word_evaluator.evaluate_word(word)
            score = score_tuple[0]
            ai_service.quality_scores[word] = score
            
        # Thêm vào danh sách có điểm
        scored_words.append((word, score))
    
    # 4. Sắp xếp theo điểm chất lượng
    scored_words.sort(key=lambda x: x[1], reverse=True)
    
    # 5. Chọn ngẫu nhiên từ top 20 từ để tránh lặp lại
    import random
    top_words = scored_words[:20] if len(scored_words) > 20 else scored_words
    
    if not top_words:
        # Failsafe nếu không có từ nào thỏa mãn
        word = random.choice(settings.WARM_UP_WORDS)
        score = 0.5  # Giá trị mặc định
    else:
        # Chọn ngẫu nhiên từ những từ có điểm cao
        word, score = random.choice(top_words)
    
    # Đăng ký từ đó vào session
    game_service.register_word(session_id, word)
    
    # Ghi log
    logger.info(f"Bắt đầu game mới với từ '{word}' (chủ đề: {theme}, điểm: {score:.2f}) cho session {session_id}")

    return WordResponse(
        answer=word,
        status="success",
        model=settings.MODEL_ID,
        metadata={
            "theme": theme,
            "quality_score": f"{score:.2f}"
        }
    )

@game_router.get("/themes", response_model=Dict[str, List[str]])
async def get_available_themes(ai_service: AIService = Depends(get_ai_service)):
    """Lấy danh sách các chủ đề có sẵn cho từ khởi đầu"""
    # Danh sách chủ đề mặc định
    default_themes = [
        {"id": "random", "name": "Ngẫu nhiên", "description": "Chọn từ ngẫu nhiên từ mọi chủ đề"},
        {"id": "food", "name": "Ẩm thực", "description": "Các từ liên quan đến thức ăn, đồ uống"},
        {"id": "animals", "name": "Động vật", "description": "Các từ về thú vật, côn trùng"},
        {"id": "nature", "name": "Thiên nhiên", "description": "Từ về phong cảnh, thiên nhiên"},
        {"id": "education", "name": "Giáo dục", "description": "Từ liên quan đến học tập, trường lớp"},
        {"id": "technology", "name": "Công nghệ", "description": "Từ về công nghệ, thiết bị"},
        {"id": "sports", "name": "Thể thao", "description": "Từ về các môn thể thao, vận động"},
        {"id": "family", "name": "Gia đình", "description": "Từ về gia đình, quan hệ thân thuộc"}
    ]
    
    # Thêm các chủ đề đã được cập nhật từ nguồn bên ngoài
    custom_themes = []
    for theme in ai_service.quality_tracker.theme_words_cache:
        # Bỏ qua các chủ đề mặc định đã có
        if any(t["id"] == theme for t in default_themes):
            continue
            
        words = ai_service.quality_tracker.theme_words_cache[theme]
        if words:  # Chỉ thêm chủ đề có từ
            custom_themes.append({
                "id": theme,
                "name": theme.capitalize(),
                "description": f"Chủ đề tùy chỉnh với {len(words)} từ",
                "custom": True
            })
    
    # Thêm số lượng từ cho mỗi chủ đề
    for theme in default_themes:
        theme_id = theme["id"]
        if theme_id != "random" and theme_id in ai_service.quality_tracker.theme_words_cache:
            theme["word_count"] = len(ai_service.quality_tracker.theme_words_cache[theme_id])
    
    # Kết hợp danh sách
    all_themes = default_themes + custom_themes
    
    return {"themes": all_themes}

@game_router.get("/theme/{theme_id}/words")
async def get_theme_words_list(
    theme_id: str,
    ai_service: AIService = Depends(get_ai_service)
):
    """Lấy danh sách các từ theo chủ đề cụ thể"""
    # Kiểm tra chủ đề
    if theme_id == "random":
        raise HTTPException(status_code=400, detail="Không thể liệt kê từ cho chủ đề ngẫu nhiên")
    
    # Lấy danh sách từ
    words = await ai_service.get_theme_words(theme_id)
    
    if not words:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy từ nào cho chủ đề '{theme_id}'")
    
    # Thêm thông tin điểm chất lượng
    word_info = []
    for word in words:
        quality = ai_service.quality_scores.get(word, None)
        if quality is None:
            # Nếu chưa có điểm, tính toán nhanh
            quality_tuple = await ai_service.word_evaluator.evaluate_word(word)
            quality = quality_tuple[0]
            ai_service.quality_scores[word] = quality
        
        word_info.append({
            "word": word,
            "quality": quality
        })
    
    # Sắp xếp theo điểm chất lượng
    word_info.sort(key=lambda x: x["quality"], reverse=True)
    
    return {
        "theme": theme_id,
        "word_count": len(words),
        "words": word_info
    }

@game_router.delete("/theme/{theme_id}")
async def delete_theme(
    theme_id: str,
    ai_service: AIService = Depends(get_ai_service)
):
    """Xóa một chủ đề khỏi hệ thống"""
    # Không cho phép xóa chủ đề mặc định
    default_themes = ["random", "food", "animals", "nature", "education", "technology", "sports", "family"]
    if theme_id in default_themes:
        raise HTTPException(status_code=400, detail=f"Không thể xóa chủ đề mặc định '{theme_id}'")
    
    # Kiểm tra xem chủ đề có tồn tại không
    if theme_id not in ai_service.quality_tracker.theme_words_cache:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy chủ đề '{theme_id}'")
    
    # Xóa chủ đề
    del ai_service.quality_tracker.theme_words_cache[theme_id]
    
    # Lưu thay đổi
    await ai_service.quality_tracker.save_theme_words()
    
    return {"status": "success", "message": f"Đã xóa chủ đề '{theme_id}'"}

@game_router.get("/preview_words")
async def preview_starting_words(
    theme: str = "random",
    count: int = 5,
    ai_service: AIService = Depends(get_ai_service)
):
    """Xem trước các từ khởi đầu theo chủ đề"""
    if count <= 0 or count > 20:
        count = 5  # Giới hạn số lượng từ
    
    # Lấy evaluator từ ai_service
    word_evaluator = ai_service.word_evaluator
    
    # Đảm bảo evaluator đã được khởi tạo
    await word_evaluator.ensure_initialized()
    
    # Danh sách từ để chọn
    candidate_words = []
    
    # Lấy từ theo chủ đề
    if theme == "random":
        # Lấy từ danh sách từ phổ biến 
        candidate_words = list(word_evaluator.common_words)
        if len(candidate_words) < 20:
            # Bổ sung thêm từ từ điển chính
            import random
            additional_words = random.sample(
                list(word_evaluator.dictionary - word_evaluator.common_words),
                min(50, len(word_evaluator.dictionary) - len(word_evaluator.common_words))
            )
            candidate_words.extend(additional_words)
    else:
        # Lấy từ theo chủ đề cụ thể
        theme_words = await ai_service.get_theme_words(theme)
        if theme_words:
            candidate_words = theme_words
        else:
            return {"status": "error", "message": f"Không tìm thấy từ nào cho chủ đề '{theme}'"}
    
    # Lọc và đánh giá từ
    scored_words = []
    for word in candidate_words:
        # Chỉ lấy từ có ít nhất 2 âm tiết
        if len(word.split()) < 2:
            continue
        
        # Lấy điểm chất lượng
        score = ai_service.quality_scores.get(word, None)
        if score is None:
            # Tính toán điểm nếu chưa có
            score_tuple = await word_evaluator.evaluate_word(word)
            score = score_tuple[0]
            ai_service.quality_scores[word] = score
        
        # Thêm vào danh sách có điểm
        scored_words.append({"word": word, "quality": score})
    
    # Sắp xếp theo điểm chất lượng
    scored_words.sort(key=lambda x: x["quality"], reverse=True)
    
    # Lấy top từ
    top_words = scored_words[:count]
    
    return {
        "theme": theme,
        "words": top_words,
        "total_available": len(scored_words)
    }

# ---------------------------------------------------------------------------
# Word Operations Endpoints
# ---------------------------------------------------------------------------

@word_router.post("/validate", response_model=ValidationResponse)
async def validate_word(
    req: Request,
    ai_service: AIService = Depends(get_ai_service)
):
    """Validate if a word is valid Vietnamese"""
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

@word_router.get("/suggest", response_model=SuggestionResponse)
async def suggest_words(
    starting_syllable: str = "",
    ai_service: AIService = Depends(get_ai_service)
):
    """Suggest words starting with a specific syllable"""
    suggestions = await ai_service.suggest_words(starting_syllable)
    return SuggestionResponse(suggestions=suggestions)

@word_router.get("/explain", response_model=ExplanationResponse)
async def explain_word(
    word: str,
    ai_service: AIService = Depends(get_ai_service)
):
    """Get explanation for a word"""
    if not word:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp từ cần giải thích")
    
    try:
        explanation = await ai_service.explain_word(word)
        if explanation.startswith("Lỗi:"):
            raise HTTPException(status_code=500, detail=explanation)
        return ExplanationResponse(word=word, explanation=explanation)
    except Exception as e:
        logger.error(f"Lỗi khi giải thích từ '{word}': {str(e)}")
        raise HTTPException(status_code=500, detail=f"Không thể giải thích từ: {str(e)}")

@word_router.post("/check_meaning")
async def check_word_meaning(
    req: Request,
    ai_service: AIService = Depends(get_ai_service)
):
    """Check if a word is valid Vietnamese and has meaning"""
    try:
        data = await req.json()
        word = data.get("word", "").strip().lower()
        
        if not word:
            raise HTTPException(status_code=400, detail="Từ không được để trống")
        
        # Kiểm tra cấu trúc
        structure_valid, structure_reason = validate_word_structure(word)
        
        # Kiểm tra trong từ điển
        word_evaluator = ai_service.word_evaluator
        in_dictionary = word_evaluator.is_in_dictionary(word)
        
        # Kiểm tra nghĩa với Gemini
        has_meaning, meaning_reason = await ai_service.check_word_meaning(word)
        
        # Chất lượng từ
        quality_score, quality_reason = await word_evaluator.evaluate_word(word)
        
        # Thêm vào từ điển nếu có nghĩa và chưa có trong từ điển
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
            "final_reason": meaning_reason if has_meaning else structure_reason
        }
        
    except Exception as e:
        logger.error(f"Error checking word: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Lỗi: {str(e)}")

@word_router.get("/quality/{word}")
async def get_word_quality(
    word: str,
    ai_service: AIService = Depends(get_ai_service)
):
    """Get the quality score for a specific word"""
    if not word:
        raise HTTPException(status_code=400, detail="Từ không được để trống")
    
    word_evaluator = ai_service.word_evaluator
    
    score, reason = await word_evaluator.evaluate_word(word)
    
    return {
        "word": word,
        "quality_score": score,
        "reason": reason,
        "is_in_dictionary": word_evaluator.is_in_dictionary(word),
        "is_common_word": word_evaluator.is_common_word(word)
    }

# ---------------------------------------------------------------------------
# Dictionary Management Endpoints
# ---------------------------------------------------------------------------

@dictionary_router.get("/stats")
async def get_dictionary_stats(ai_service: AIService = Depends(get_ai_service)):
    """Get statistics about the word dictionary"""
    word_evaluator = ai_service.word_evaluator
    
    await word_evaluator.ensure_initialized()
    
    return {
        "dictionary_size": len(word_evaluator.dictionary),
        "common_words_count": len(word_evaluator.common_words),
        "evaluated_words_count": len(word_evaluator.word_scores)
    }

@dictionary_router.post("/add")
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

@dictionary_router.post("/update_theme_words")
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

# ---------------------------------------------------------------------------
# System Management Endpoints
# ---------------------------------------------------------------------------

@system_router.get("/status", response_model=StatusResponse)
async def check_status(ai_service: AIService = Depends(get_ai_service)):
    """Check the status of the AI service"""
    return StatusResponse(
        status="ready" if ai_service.is_ready else "initializing",
        cached_words=ai_service.get_cached_words(),
        model=settings.MODEL_ID,
        api_provider="Google Gemini"
    )

@system_router.get("/cache", response_model=CacheResponse)
async def view_cache(ai_service: AIService = Depends(get_ai_service)):
    """View the current word cache (for debugging)"""
    return CacheResponse(cache=ai_service.get_cache())

@system_router.post("/reset", response_model=ResetResponse)
async def reset_cache(ai_service: AIService = Depends(get_ai_service)):
    """Reset the word cache (for debugging)"""
    count = ai_service.reset_cache()
    return ResetResponse(status=f"Cache đã được xóa ({count} items removed)")

@system_router.get("/performance")
async def get_ai_performance(ai_service: AIService = Depends(get_ai_service)):
    """Get performance metrics for the AI service"""
    # Get basic performance metrics
    metrics = ai_service.get_performance_metrics()
    
    # Get word quality distribution
    quality_scores = ai_service.get_quality_scores()
    
    ranges = {
        "excellent": 0,  # 0.8-1.0
        "good": 0,       # 0.6-0.8
        "average": 0,    # 0.4-0.6
        "poor": 0,       # 0.2-0.4
        "very_poor": 0   # 0.0-0.2
    }
    
    for word, score in quality_scores.items():
        if score >= 0.8:
            ranges["excellent"] += 1
        elif score >= 0.6:
            ranges["good"] += 1
        elif score >= 0.4:
            ranges["average"] += 1
        elif score >= 0.2:
            ranges["poor"] += 1
        else:
            ranges["very_poor"] += 1
    
    quality_distribution = {
        "total_evaluated": len(quality_scores),
        "distribution": ranges
    }
    
    return {
        "performance": metrics,
        "quality": quality_distribution
    }

@system_router.get("/quality_stats")
async def get_quality_stats(ai_service: AIService = Depends(get_ai_service)):
    """Get quality statistics over time"""
    # Get quality tracker stats
    stats = ai_service.quality_tracker.get_summary_stats()
    
    # Get recent quality data for plotting
    recent_metrics = ai_service.quality_tracker.metrics[-50:] if len(ai_service.quality_tracker.metrics) > 0 else []
    
    # Format for plotting
    plot_data = [
        {
            "word": m["word"],
            "score": m["score"],
            "timestamp": m["timestamp"]
        } for m in recent_metrics
    ]
    
    return {
        "summary": stats,
        "recent_data": plot_data
    }

# Include all sub-routers
router.include_router(game_router)
router.include_router(word_router)
router.include_router(dictionary_router)
router.include_router(system_router)