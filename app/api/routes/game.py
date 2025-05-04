from fastapi import APIRouter, Depends, Body, HTTPException, Request
from app.models.schemas import SessionResponse
from app.services.game_service import GameService
from app.services.ai_service import AIService
from app.api.dependencies import get_game_service, get_ai_service
from app.models.schemas import WordResponse
from app.config import settings
from typing import List, Dict

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/game", tags=["game"])

@router.get("/start", response_model=SessionResponse)
async def start_game(game_service: GameService = Depends(get_game_service)):
    """Bắt đầu một phiên chơi mới"""
    session_id = await game_service.create_session()
    return SessionResponse(session_id=session_id, status="success")

@router.get("/stats/{session_id}")
async def get_game_stats(
    session_id: str,
    game_service: GameService = Depends(get_game_service)
):
    """Get statistics for a game session"""
    stats = game_service.get_session_stats(session_id)
    
    if not stats:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên game")
    
    return stats

@router.post("/check_pair")
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

@router.post("/new_word", response_model=WordResponse)
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

@router.get("/themes", response_model=Dict[str, List[str]])
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

@router.get("/theme/{theme_id}/words")
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

@router.delete("/theme/{theme_id}")
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

@router.get("/preview_words")
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