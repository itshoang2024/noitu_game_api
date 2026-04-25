import logging

from fastapi import APIRouter, Depends

from app.api.dependencies import get_ai_service
from app.config import settings
from app.models.schemas import CacheResponse, ResetResponse, StatusResponse
from app.services.ai_service import AIService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])


def _build_quality_distribution(quality_scores: dict[str, float]) -> dict[str, object]:
    ranges = {
        "excellent": 0,
        "good": 0,
        "average": 0,
        "poor": 0,
        "very_poor": 0,
    }

    for score in quality_scores.values():
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

    return {"total_evaluated": len(quality_scores), "distribution": ranges}


@router.get("/status", response_model=StatusResponse)
async def check_status(ai_service: AIService = Depends(get_ai_service)):
    """Check AI service readiness and cache size."""
    return StatusResponse(
        status="ready" if ai_service.is_ready else "initializing",
        cached_words=ai_service.get_cached_words(),
        model=settings.MODEL_ID,
        api_provider="Google Gemini",
    )


@router.get("/cache", response_model=CacheResponse)
async def view_cache(ai_service: AIService = Depends(get_ai_service)):
    """View the current word cache."""
    return CacheResponse(cache=ai_service.get_cache())


@router.post("/reset", response_model=ResetResponse)
async def reset_cache(ai_service: AIService = Depends(get_ai_service)):
    """Reset the word cache."""
    removed_count = ai_service.reset_cache()
    return ResetResponse(status=f"Cache đã được xóa ({removed_count} items removed)")


@router.get("/performance")
async def get_ai_performance(ai_service: AIService = Depends(get_ai_service)):
    """Get in-memory AI performance metrics and quality distribution."""
    performance = ai_service.get_performance_metrics()
    quality = _build_quality_distribution(ai_service.get_quality_scores())
    return {"performance": performance, "quality": quality}


@router.get("/quality_stats")
async def get_quality_stats(ai_service: AIService = Depends(get_ai_service)):
    """Get quality trend summary and recent data points."""
    stats = ai_service.quality_tracker.get_summary_stats()
    recent_metrics = ai_service.quality_tracker.metrics[-50:]
    recent_data = [
        {
            "word": metric["word"],
            "score": metric["score"],
            "timestamp": metric["timestamp"],
        }
        for metric in recent_metrics
    ]
    return {"summary": stats, "recent_data": recent_data}
