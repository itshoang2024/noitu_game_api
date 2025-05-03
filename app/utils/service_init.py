from app.services.ai_service import AIService
from app.services.game_service import GameService
from app.utils.word_evaluator import WordEvaluator
import logging

logger = logging.getLogger(__name__)

async def initialize_services():
    """Initialize all services in the correct order"""
    logger.info("Initializing services...")
    
    # Initialize word evaluator first
    word_evaluator = WordEvaluator.get_instance()
    await word_evaluator.initialize()
    
    # Initialize AI service
    ai_service = AIService.get_instance()
    await ai_service.initialize()
    
    # Initialize game service
    game_service = GameService.get_instance()
    
    logger.info("All services initialized successfully")
    return word_evaluator, ai_service, game_service