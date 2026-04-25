import logging
import random
from typing import Dict, List, Tuple, Union

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_ai_service, get_game_service
from app.config import settings
from app.models.schemas import SessionResponse, StartingWordRequest, WordPairRequest, WordResponse
from app.services.ai_service import AIService
from app.services.game_service import GameService
from app.utils.constants import DEFAULT_GAME_THEME_IDS, DEFAULT_GAME_THEMES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/game", tags=["game"])


def _get_random_candidate_words(word_evaluator) -> List[str]:
    candidate_words = list(word_evaluator.common_words)
    if len(candidate_words) >= 20:
        return candidate_words

    remaining_words = list(word_evaluator.dictionary - word_evaluator.common_words)
    if not remaining_words:
        return candidate_words

    candidate_words.extend(random.sample(remaining_words, min(50, len(remaining_words))))
    return candidate_words


async def _get_candidate_words_by_theme(
    theme: str,
    ai_service: AIService,
    use_common_words_fallback: bool,
) -> List[str]:
    if theme == "random":
        return _get_random_candidate_words(ai_service.word_evaluator)

    theme_words = await ai_service.get_theme_words(theme)
    if theme_words:
        return theme_words

    if use_common_words_fallback:
        return list(ai_service.word_evaluator.common_words)
    return []


async def _get_quality_score(word: str, ai_service: AIService) -> float:
    quality_score = ai_service.quality_scores.get(word)
    if quality_score is not None:
        return quality_score

    quality_score, _ = await ai_service.word_evaluator.evaluate_word(word)
    ai_service.quality_scores[word] = quality_score
    return quality_score


async def _build_scored_words(
    candidate_words: List[str],
    ai_service: AIService,
    game_service: GameService = None,
    session_id: str = None,
) -> List[Tuple[str, float]]:
    scored_words: List[Tuple[str, float]] = []
    for candidate_word in candidate_words:
        if len(candidate_word.split()) < 2:
            continue

        if session_id and game_service and await game_service.is_word_used(session_id, candidate_word):
            continue

        quality_score = await _get_quality_score(candidate_word, ai_service)
        scored_words.append((candidate_word, quality_score))

    scored_words.sort(key=lambda item: item[1], reverse=True)
    return scored_words


def _choose_starting_word(scored_words: List[Tuple[str, float]]) -> Tuple[str, float]:
    if not scored_words:
        return random.choice(settings.WARM_UP_WORDS), 0.5

    return random.choice(scored_words[:20])


def _build_theme_payload(ai_service: AIService) -> List[Dict[str, object]]:
    theme_words_cache = ai_service.quality_tracker.theme_words_cache
    default_themes = [theme.copy() for theme in DEFAULT_GAME_THEMES]
    custom_themes = []

    for theme_id, words in theme_words_cache.items():
        if theme_id in DEFAULT_GAME_THEME_IDS or not words:
            continue

        custom_themes.append({
            "id": theme_id,
            "name": theme_id.capitalize(),
            "description": f"Chủ đề tùy chỉnh với {len(words)} từ",
            "custom": True,
        })

    for theme in default_themes:
        theme_id = theme["id"]
        if theme_id != "random" and theme_id in theme_words_cache:
            theme["word_count"] = len(theme_words_cache[theme_id])

    return default_themes + custom_themes


def _extract_starting_word_request(data: Union[StartingWordRequest, dict]) -> Tuple[str, str]:
    if isinstance(data, dict):
        session_id = data.get("session_id")
        theme = data.get("theme", "random")
    else:
        session_id = data.session_id
        theme = data.theme or "random"

    return session_id, str(theme or "random").strip().lower()


@router.get("/start", response_model=SessionResponse)
async def start_game(game_service: GameService = Depends(get_game_service)):
    """Bắt đầu một phiên chơi mới"""
    session_id = await game_service.create_session()
    return SessionResponse(session_id=session_id, status="success")


@router.get("/stats/{session_id}")
async def get_game_stats(
    session_id: str,
    game_service: GameService = Depends(get_game_service),
):
    """Get statistics for a game session"""
    stats = game_service.get_session_stats(session_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên game")
    return stats


@router.post("/check_pair")
async def check_word_pair(
    data: WordPairRequest,
    game_service: GameService = Depends(get_game_service),
):
    """Check if a word pair follows the game rules"""
    try:
        input_word = data.input_word.strip().lower()
        response_word = data.response_word.strip().lower()

        if not input_word or not response_word:
            raise HTTPException(status_code=400, detail="Vui lòng cung cấp cả hai từ")

        is_valid_pair = game_service.validate_word_pair(input_word, response_word)
        return {
            "valid": is_valid_pair,
            "reason": "Hợp lệ" if is_valid_pair else "Từ phản hồi không bắt đầu bằng âm tiết cuối của từ nhập vào",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Lỗi khi kiểm tra cặp từ: {str(exc)}")
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {str(exc)}")


@router.post("/new_word", response_model=WordResponse)
async def get_starting_word(
    data: StartingWordRequest,
    ai_service: AIService = Depends(get_ai_service),
    game_service: GameService = Depends(get_game_service),
):
    """Trả về một từ bắt đầu cho phiên chơi với khả năng tùy chọn chủ đề"""
    session_id, theme = _extract_starting_word_request(data)
    if not session_id:
        raise HTTPException(status_code=400, detail="Thiếu session_id")

    await ai_service.word_evaluator.ensure_initialized()

    candidate_words = await _get_candidate_words_by_theme(
        theme=theme,
        ai_service=ai_service,
        use_common_words_fallback=True,
    )
    if not candidate_words:
        candidate_words = settings.WARM_UP_WORDS

    scored_words = await _build_scored_words(candidate_words, ai_service, game_service, session_id)
    selected_word, quality_score = _choose_starting_word(scored_words)

    is_registered = await game_service.register_word(session_id, selected_word)
    if not is_registered:
        return WordResponse(
            answer="Không thể đăng ký từ khởi đầu cho phiên hiện tại. Vui lòng thử lại.",
            status="unfound",
            model=settings.MODEL_ID,
            metadata={"theme": theme},
        )

    logger.info(
        f"Bắt đầu game mới với từ '{selected_word}' "
        f"(chủ đề: {theme}, điểm: {quality_score:.2f}) cho session {session_id}"
    )

    return WordResponse(
        answer=selected_word,
        status="success",
        model=settings.MODEL_ID,
        metadata={
            "theme": theme,
            "quality_score": f"{quality_score:.2f}",
        },
    )


@router.get("/themes", response_model=Dict[str, List[Dict[str, object]]])
async def get_available_themes(ai_service: AIService = Depends(get_ai_service)):
    """Lấy danh sách các chủ đề có sẵn cho từ khởi đầu"""
    return {"themes": _build_theme_payload(ai_service)}


@router.get("/theme/{theme_id}/words")
async def get_theme_words_list(
    theme_id: str,
    ai_service: AIService = Depends(get_ai_service),
):
    """Lấy danh sách các từ theo chủ đề cụ thể"""
    if theme_id == "random":
        raise HTTPException(status_code=400, detail="Không thể liệt kê từ cho chủ đề ngẫu nhiên")

    words = await ai_service.get_theme_words(theme_id)
    if not words:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy từ nào cho chủ đề '{theme_id}'")

    word_info = []
    for word in words:
        quality_score = await _get_quality_score(word, ai_service)
        word_info.append({"word": word, "quality": quality_score})

    word_info.sort(key=lambda item: item["quality"], reverse=True)
    return {"theme": theme_id, "word_count": len(words), "words": word_info}


@router.delete("/theme/{theme_id}")
async def delete_theme(
    theme_id: str,
    ai_service: AIService = Depends(get_ai_service),
):
    """Xóa một chủ đề khỏi hệ thống"""
    if theme_id in DEFAULT_GAME_THEME_IDS:
        raise HTTPException(status_code=400, detail=f"Không thể xóa chủ đề mặc định '{theme_id}'")

    theme_words_cache = ai_service.quality_tracker.theme_words_cache
    if theme_id not in theme_words_cache:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy chủ đề '{theme_id}'")

    del theme_words_cache[theme_id]
    await ai_service.quality_tracker.save_theme_words()
    return {"status": "success", "message": f"Đã xóa chủ đề '{theme_id}'"}


@router.get("/preview_words")
async def preview_starting_words(
    theme: str = "random",
    count: int = 5,
    ai_service: AIService = Depends(get_ai_service),
):
    """Xem trước các từ khởi đầu theo chủ đề"""
    if count <= 0 or count > 20:
        count = 5

    await ai_service.word_evaluator.ensure_initialized()

    requested_theme = theme.strip().lower()
    candidate_words = await _get_candidate_words_by_theme(
        theme=requested_theme,
        ai_service=ai_service,
        use_common_words_fallback=False,
    )
    if requested_theme != "random" and not candidate_words:
        return {"status": "error", "message": f"Không tìm thấy từ nào cho chủ đề '{requested_theme}'"}

    scored_words = await _build_scored_words(candidate_words, ai_service)
    top_words = [{"word": word, "quality": quality} for word, quality in scored_words[:count]]

    return {
        "theme": requested_theme,
        "words": top_words,
        "total_available": len(scored_words),
    }
