from fastapi import APIRouter, Depends

from app.models.schemas import StatusResponse, CacheResponse, ResetResponse
from app.services.ai_service import AIService
from app.api.dependencies import get_ai_service
from app.config import settings

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])

@router.get("/status", response_model=StatusResponse)
async def check_status(ai_service: AIService = Depends(get_ai_service)):
    """Check the status of the AI service"""
    return StatusResponse(
        status="ready" if ai_service.is_ready else "initializing",
        cached_words=ai_service.get_cached_words(),
        model=settings.MODEL_ID,
        api_provider="Google Gemini"
    )

@router.get("/cache", response_model=CacheResponse)
async def view_cache(ai_service: AIService = Depends(get_ai_service)):
    """View the current word cache (for debugging)"""
    return CacheResponse(cache=ai_service.get_cache())

@router.post("/reset", response_model=ResetResponse)
async def reset_cache(ai_service: AIService = Depends(get_ai_service)):
    """Reset the word cache (for debugging)"""
    count = ai_service.reset_cache()
    return ResetResponse(status=f"Cache đã được xóa ({count} items removed)")

@router.get("/performance")
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

@router.get("/quality_stats")
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