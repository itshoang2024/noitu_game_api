import asyncio
import time
import logging
from typing import Dict, List, Tuple
import httpx
from asyncio import Semaphore

from datetime import datetime
import json
import os

from app.config import settings
from app.utils.word_evaluator import WordEvaluator
from app.utils.constants import QUALITY_METRICS_PATH
from app.database.base import get_db, get_async_db
from app.database import crud
from sqlalchemy.future import select
from app.database.models import AIMetric

logger = logging.getLogger(__name__)

class QualityTracker:
    """Tracks word quality metrics over time"""
    
    def __init__(self):
        """Initialize quality tracker"""
        self.metrics = []
        self.theme_words_cache: Dict[str, List[str]] = {}  # Lưu trữ từ theo chủ đề

    async def initialize(self):
        """Async initialization"""
        await self.load_metrics()
        await self.load_theme_words()
        return self


    async def load_metrics(self):
        """Load existing metrics from database"""
        try:
            async for db in get_async_db():
                # Get metrics from AI_metrics table
                result = await db.execute(select(AIMetric).order_by(AIMetric.created_at.desc()).limit(100))
                metrics = result.scalars().all()
                
                # Convert to memory format
                self.metrics = [
                    {
                        "timestamp": metric.created_at.isoformat(),
                        "word": metric.response_word,
                        "score": metric.quality_score,
                        "user_input": metric.request_word,
                        "session_id": metric.game_id
                    }
                    for metric in metrics
                ]
                logger.info(f"Loaded {len(self.metrics)} quality metric records from database")
        except Exception as e:
            logger.error(f"Error loading quality metrics: {str(e)}")
            self.metrics = []
    
    async def add_metric(self, word, score, user_input=None, session_id=None):
        """Add a new quality metric"""
        metric = {
            "timestamp": datetime.now().isoformat(),
            "word": word,
            "score": score,
            "user_input": user_input,
            "session_id": session_id
        }
        self.metrics.append(metric)
        
        # Add to database
        try:
            async for db in get_async_db():
                await crud.add_ai_metric(
                    db,
                    request_word=user_input or "",
                    response_word=word,
                    quality_score=score,
                    response_time_ms=0,  # Add response time if available
                    game_id=session_id,
                    success=True
                )
        except Exception as e:
            logger.error(f"Error adding metric to database: {str(e)}")

    async def load_theme_words(self):
        """Tải danh sách từ theo chủ đề từ database"""
        try:
            async for db in get_async_db():
                # Get all themes
                themes = await crud.get_all_themes(db)
                
                # Load words for each theme
                for theme in themes:
                    theme_words = await crud.get_theme_words(db, theme.id)
                    self.theme_words_cache[theme.name] = [word.word for word in theme_words]
                    
                logger.info(f"Loaded theme words for {len(themes)} themes from database")
        except Exception as e:
            logger.error(f"Error loading theme words from database: {str(e)}")
            self.theme_words_cache = {}

    async def save_theme_words(self):
        """Lưu danh sách từ theo chủ đề vào database"""
        try:
            async for db in get_async_db():
                for theme_name, words in self.theme_words_cache.items():
                    # Get or create theme
                    theme = await crud.get_theme_by_name(db, theme_name)
                    if not theme:
                        theme = await crud.create_theme(db, theme_name)
                    
                    # Clear existing theme words (optional, depends on your use case)
                    # Add new theme words
                    for word in words:
                        await crud.add_word_to_theme(db, theme.id, word)
                        
                logger.info(f"Saved {len(self.theme_words_cache)} themes to database")
                return True
        except Exception as e:
            logger.error(f"Error saving theme words to database: {str(e)}")
            return False

class AIService:
    """Service for interacting with Gemini AI API"""
    _instance = None
    
    @classmethod
    def get_instance(cls):
        """Singleton pattern to ensure one instance across app"""
        if cls._instance is None:
            cls._instance = AIService()
        return cls._instance
    
    def __init__(self):
        """Initialize the AI service"""
        self.http_client = httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT)
        self.word_cache: Dict[str, str] = {}
        self.quality_scores: Dict[str, float] = {}  # Cache for word quality scores
        self.is_ready = False
        self.request_semaphore = Semaphore(settings.MAX_CONCURRENT_REQUESTS)
        self.word_evaluator = WordEvaluator.get_instance()
        self.quality_tracker = QualityTracker()
        # Performance metrics
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.average_response_time = 0.0

    async def initialize(self):
        """Initialize the service and word evaluator"""
        await self.word_evaluator.initialize()
        await self.quality_tracker.initialize()
        logger.info("AIService, WordEvaluator and QualityTracker initialized")

    async def close(self):
        """Close resources"""
        if self.http_client:
            await self.http_client.aclose()
            logger.info("HTTP client closed")

    async def warm_up_model(self):
        """Warm up the model with an adaptive, efficient strategy"""
        logger.info("Starting model warm-up with adaptive strategy...")

        # Ensure word evaluator is initialized
        await self.initialize()
        
        if not self.word_evaluator.is_initialized:
            logger.error("WordEvaluator initialization failed, forcing initialization")
            self.word_evaluator.is_initialized = True
            await self.word_evaluator.build_word_chains()

        start_time = time.time()
        
        # Adaptive rate limiting parameters
        initial_concurrency = 3
        max_concurrency = 8
        min_concurrency = 1
        current_concurrency = initial_concurrency
        
        # Success tracking
        success_count = 0
        total_time = 0.0
        
        # Work queue for better management
        queue = asyncio.Queue()
        for word in settings.WARM_UP_WORDS:
            await queue.put(word)
        
        # Track recent response times for adaptive behavior
        recent_times = []
        
        # Process word function with adaptive rate limiting
        async def process_word():
            nonlocal success_count, total_time, current_concurrency
            
            try:
                # Get word from queue with timeout
                word = await asyncio.wait_for(queue.get(), 0.1)
            except asyncio.TimeoutError:
                return False  # No more words
                
            try:
                # Process the word
                start = time.time()
                result = await self.generate_response(word, use_cache=False)
                process_time = time.time() - start
                
                # Update recent times list (keep last 5)
                recent_times.append(process_time)
                if len(recent_times) > 5:
                    recent_times.pop(0)
                
                # Adjust concurrency based on recent response times
                avg_time = sum(recent_times) / len(recent_times)
                if avg_time > 2.5 and current_concurrency > min_concurrency:
                    # Responses too slow, reduce concurrency
                    current_concurrency = max(min_concurrency, current_concurrency - 1)
                    logger.info(f"Reducing concurrency to {current_concurrency} (avg response: {avg_time:.2f}s)")
                elif avg_time < 1.0 and current_concurrency < max_concurrency:
                    # Responses fast, increase concurrency
                    current_concurrency = min(max_concurrency, current_concurrency + 1)
                    logger.info(f"Increasing concurrency to {current_concurrency} (avg response: {avg_time:.2f}s)")
                
                # Evaluate word quality
                if not result.startswith("Lỗi:"):
                    quality_score, reason = await self.word_evaluator.evaluate_word(result)
                    logger.info(f"Warm-up: '{word}' → '{result}' (Score: {quality_score:.2f}, Time: {process_time:.2f}s)")
                    self.quality_scores[result] = quality_score
                    self.word_cache[word] = result
                    success_count += 1
                    total_time += process_time
                else:
                    logger.warning(f"Warm-up error: '{word}' → '{result}'")
                    # Put back in queue for retry (with limit)
                    if queue.qsize() < len(settings.WARM_UP_WORDS) * 2:  # Prevent infinite retries
                        await queue.put(word)
                        
                # Adaptive delay based on response time
                await asyncio.sleep(min(0.2, process_time * 0.1))  # Proportional delay
                
                return True
            except Exception as e:
                logger.error(f"Error processing '{word}': {str(e)}")
                # Put back in queue for retry (with limit)
                if queue.qsize() < len(settings.WARM_UP_WORDS) * 2:
                    await queue.put(word)
                return True
            finally:
                queue.task_done()
        
        # Main processing loop with dynamic workers
        while not queue.empty():
            # Create batch of workers based on current concurrency
            workers = [process_word() for _ in range(current_concurrency)]
            await asyncio.gather(*workers)
            
            # Log progress
            remaining = queue.qsize()
            progress = (len(settings.WARM_UP_WORDS) - remaining) / len(settings.WARM_UP_WORDS) * 100
            logger.info(f"Warm-up progress: {progress:.1f}% ({remaining} words remaining)")
            
            # Small pause to prevent CPU spinning if queue gets empty
            if queue.empty() and success_count < len(settings.WARM_UP_WORDS):
                await asyncio.sleep(0.5)
        
        # Calculate final statistics
        if success_count > 0:
            self.average_response_time = total_time / success_count
        
        duration = time.time() - start_time
        logger.info(f"Warm-up completed in {duration:.2f}s. {success_count}/{len(settings.WARM_UP_WORDS)} successful. "
                f"Average response time: {self.average_response_time:.3f}s")
        
        # Save any themes
        if hasattr(self.quality_tracker, 'theme_words_cache') and self.quality_tracker.theme_words_cache:
            await self.quality_tracker.save_theme_words()
        
        self.is_ready = True    
    
    async def generate_response(self, user_input: str, used_words: List[str] = None, 
                            session_id: str = None, game_service = None,
                            use_cache: bool = True, max_retries: int = settings.MAX_RETRIES, 
                            quality_threshold: float = 0.4, 
                            skip_quality_check: bool = False) -> str:
        """Generate a response from Gemini API with retry logic and quality check"""
        # Check cache first
        if use_cache and user_input in self.word_cache:
            logger.debug(f"Cache hit for: '{user_input}'")
            return self.word_cache[user_input]
        
        logger.debug(f"Cache miss for: '{user_input}'. Calling Gemini API...")
        self.total_requests += 1
        
        base_prompt = settings.SYSTEM_INSTRUCTION
        
        if session_id and game_service and user_input:
            # Lấy âm tiết cuối của từ người dùng nhập
            user_syllables = user_input.strip().lower().split()
            if len(user_syllables) > 0:
                last_syllable = user_syllables[-1]
                
                # Lọc các từ đã dùng bắt đầu bằng âm tiết cuối
                conflicting_words = []
                all_used_words = game_service.used_words.get(session_id, [])
                
                for word in all_used_words:
                    word_syllables = word.strip().lower().split()
                    if word_syllables and word_syllables[0] == last_syllable:
                        conflicting_words.append(word)
                
                # Thêm vào prompt nếu có từ xung đột
                if conflicting_words:
                    conflicting_words_text = ", ".join(conflicting_words)
                    base_prompt += f"\n\nCác từ đã sử dụng bắt đầu bằng '{last_syllable}' (không được dùng lại): {conflicting_words_text}."
                    logger.debug(f"Added {len(conflicting_words)} conflicting words to prompt for syllable '{last_syllable}'")
        
        prompt_text = f"{base_prompt}\nNgười dùng: {user_input}\n→"
        
        # Prepare API payload
        payload = {
            "contents": [{
                "parts": [{"text": prompt_text}]
            }],
            "generationConfig": settings.GENERATION_CONFIG,
            "safetySettings": settings.SAFETY_SETTINGS
        }
        
        # Use semaphore to limit concurrent requests
        async with self.request_semaphore:
            retries = 0
            quality_retries = 0
            max_quality_retries = 2  # Maximum attempts to get a high-quality word
            
            while retries <= max_retries:
                try:
                    start_time = time.time()
                    
                    # Get the URL with actual model ID and API key
                    api_url = settings.GEMINI_API_URL.format(
                        model_id=settings.MODEL_ID,
                        api_key=settings.GEMINI_API_KEY
                    )
                    
                    # Send request to Gemini API
                    response = await self.http_client.post(api_url, json=payload)
                    response.raise_for_status()
                    result = response.json()
                    
                    # Track response time
                    response_time = time.time() - start_time
                    self.average_response_time = (self.average_response_time * self.successful_requests + response_time) / (self.successful_requests + 1)
                    
                    # Parse response
                    if not result.get("candidates"):
                        feedback = result.get("promptFeedback")
                        block_reason = feedback.get("blockReason", "Unknown") if feedback else "No candidates found"
                        logger.error(f"Gemini API Error: No candidates. Reason: {block_reason}")
                        
                        if feedback and feedback.get("safetyRatings"):
                            logger.error(f"Safety Ratings: {feedback.get('safetyRatings')}")
                        
                        self.failed_requests += 1
                        return f"Lỗi: Gemini không thể tạo phản hồi (Reason: {block_reason})."
                    
                    # Extract text from response
                    first_candidate = result["candidates"][0]
                    if "content" not in first_candidate or "parts" not in first_candidate["content"]:
                        logger.error(f"Gemini API Error: Unexpected response structure")
                        finish_reason = first_candidate.get("finishReason", "Unknown")
                        if finish_reason != "STOP":
                            self.failed_requests += 1
                            return f"Lỗi: Gemini dừng tạo phản hồi vì lý do '{finish_reason}'."
                        self.failed_requests += 1
                        return "Lỗi: Không thể trích xuất nội dung từ Gemini."
                    
                    reply_parts = first_candidate["content"]["parts"]
                    if not reply_parts or "text" not in reply_parts[0]:
                        logger.error(f"Gemini API Error: Missing text in parts")
                        self.failed_requests += 1
                        return "Lỗi: Không thể trích xuất văn bản từ Gemini."
                    
                    reply = reply_parts[0]["text"].strip()
                    
                    # Validate response format
                    if not reply or len(reply.split()) > 5:
                        logger.warning(f"Warning: Potentially invalid response format: '{reply}'")
                        if quality_retries < max_quality_retries:
                            quality_retries += 1
                            logger.info(f"Trying again to get a better formatted word (attempt {quality_retries}/{max_quality_retries})")
                            continue
                    
                    if skip_quality_check:
                        if reply and not reply.startswith("Lỗi:"):
                            self.word_cache[user_input] = reply
                            self.successful_requests += 1
                        else:
                            self.failed_requests += 1
                        return reply
                    
                    # Evaluate word quality
                    quality_score, reason = await self.word_evaluator.evaluate_word(reply)
                    logger.info(f"Word quality for '{reply}': {quality_score:.2f} - {reason}")
                    
                    # Retry if quality is below threshold and we haven't exceeded retry limit
                    if quality_score < quality_threshold and quality_retries < max_quality_retries:
                        quality_retries += 1
                        logger.info(f"Word quality below threshold ({quality_score:.2f} < {quality_threshold}). Retrying ({quality_retries}/{max_quality_retries})")
                        continue
                    
                    # Cache successful responses
                    if reply and not reply.startswith("Lỗi:"):
                        self.word_cache[user_input] = reply
                        self.quality_scores[reply] = quality_score
                        self.successful_requests += 1
                    else:
                        self.failed_requests += 1
                    
                    return reply
                    
                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    retries += 1
                    if retries > max_retries:
                        logger.error(f"Failed after {max_retries} retries: {str(e)}")
                        self.failed_requests += 1
                        if isinstance(e, httpx.HTTPStatusError):
                            error_details = "Unknown error"
                            try:
                                error_data = e.response.json()
                                error_details = error_data.get("error", {}).get("message", e.response.text)
                            except Exception:
                                error_details = e.response.text
                            return f"Lỗi: Gemini API trả về lỗi {e.response.status_code}. Chi tiết: {error_details}"
                        return f"Lỗi: Không thể kết nối đến Gemini ({type(e).__name__})."
                    
                    # Exponential backoff
                    wait_time = 0.5 * (2 ** retries)
                    logger.warning(f"Retry {retries}/{max_retries} sau {wait_time}s cho '{user_input}'")
                    await asyncio.sleep(wait_time)
                
                except Exception as e:
                    logger.error(f"Unexpected error: {str(e)}", exc_info=True)
                    self.failed_requests += 1
                    return f"Lỗi: Lỗi máy chủ nội bộ khi xử lý yêu cầu ({type(e).__name__})."

    async def generate_high_quality_response(
        self, user_input: str, session_id: str = None, 
        game_service = None, max_attempts: int = settings.MAX_RETRIES, 
        quality_threshold: float = 0.7
    ) -> Tuple[str, float]:
        """Generate a high-quality response with multiple attempts if needed"""
        best_response = None
        best_score = 0.0
        start_time = time.time()
        
        for attempt in range(max_attempts):
            response = await self.generate_response(user_input, use_cache=(attempt == 0))
            
            # Skip error responses
            if response.startswith("Lỗi:"):
                logger.warning(f"Error response on attempt {attempt+1}: {response}")
                continue
                    
            # Evaluate response quality
            quality_score, reason = await self.word_evaluator.evaluate_word(response)
            logger.info(f"Attempt {attempt+1}: '{response}' with score {quality_score:.2f} - {reason}")
            
            # Keep the highest scoring response
            if quality_score > best_score:
                best_response = response
                best_score = quality_score
                    
                # If we found a response above threshold, return immediately
                if quality_score >= quality_threshold:
                    logger.info(f"Found high-quality response on attempt {attempt+1}")
                    break
        
        # Tính toán thời gian phản hồi
        response_time_ms = int((time.time() - start_time) * 1000)
        
        # Lưu metrics vào database
        if settings.USE_DATABASE and best_response:
            try:
                async for db in get_async_db():
                    await crud.add_ai_metric(
                        db, 
                        request_word=user_input,
                        response_word=best_response,
                        quality_score=best_score,
                        response_time_ms=response_time_ms,
                        game_id=session_id,
                        success=(best_response is not None and not best_response.startswith("Lỗi:"))
                    )
            except Exception as e:
                logger.error(f"Error logging AI metrics to database: {str(e)}")
        
        # Vẫn duy trì việc track quality metrics trong memory
        if best_response is not None:
            self.quality_tracker.add_metric(best_response, best_score, user_input, session_id)
                
        return best_response or "Lỗi: Không thể tạo từ chất lượng cao.", best_score
    
    async def generate_normal_response(self, user_input: str) -> str:
        prompt_text = f"{user_input}"

        # Prepare API payload
        payload = {
            "contents": [{
                "parts": [{"text": prompt_text}]
            }],
            "generationConfig": {
            "temperature": 0.9,
            "topP": 0.1,
            "topK": 1,
            "maxOutputTokens": 100,
            },
            "safetySettings": settings.SAFETY_SETTINGS
        }

        try:
            # Get the URL with actual model ID and API key
            api_url = settings.GEMINI_API_URL.format(
                model_id=settings.MODEL_ID,
                api_key=settings.GEMINI_API_KEY
            )
        
            # Send request to Gemini API
            response = await self.http_client.post(api_url, json=payload)
            response.raise_for_status()
            result = response.json()
        
            # Parse response
            if not result.get("candidates"):
                return "Chúc bạn ngày vui vẻ!"
        
            # Extract text from response
            first_candidate = result["candidates"][0]
            if "content" not in first_candidate or "parts" not in first_candidate["content"]:
                return "Chúc bạn ngày vui vẻ!"
        
            reply_parts = first_candidate["content"]["parts"]
            if not reply_parts or "text" not in reply_parts[0]:
                return "Chúc bạn ngày vui vẻ!"
        
            reply = reply_parts[0]["text"].strip()
        
            # Return the generated reply
            return reply

        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            return f"Lỗi: Không thể kết nối đến Gemini ({type(e).__name__})."

        except Exception as e:
            return f"Lỗi: Lỗi máy chủ nội bộ khi xử lý yêu cầu ({type(e).__name__})."

    def get_cached_words(self) -> int:
        """Get the number of cached words"""
        return len(self.word_cache)
    
    def get_cache(self) -> Dict[str, str]:
        """Get the current cache"""
        return self.word_cache
    
    def get_quality_scores(self) -> Dict[str, float]:
        """Get the word quality scores"""
        return self.quality_scores
    
    def reset_cache(self) -> int:
        """Reset the cache and return count of removed items"""
        count = len(self.word_cache)
        self.word_cache = {}
        self.quality_scores = {}
        logger.info(f"Cache cleared. Removed {count} entries.")
        return count
    
    def get_performance_metrics(self) -> Dict:
        """Get performance metrics for the service"""
        success_rate = 0.0
        if self.total_requests > 0:
            success_rate = (self.successful_requests / self.total_requests) * 100
            
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": f"{success_rate:.2f}%",
            "average_response_time": f"{self.average_response_time:.3f}s",
            "cache_size": len(self.word_cache)
        }

    async def explain_word(self, word: str) -> str:
        """Get explanation for a word"""
        prompt = f"Vui lòng giải thích ngắn gọn nghĩa của từ '{word}' trong tiếng Việt. Chỉ trả lời nghĩa, không thêm giải thích."
        return await self.generate_response(prompt, use_cache=True)
    
    async def validate_vietnamese_word(self, word: str) -> Tuple[bool, str]:
        """Check if a word is valid Vietnamese using multiple methods"""
        # 1. Kiểm tra trong từ điển trước (nhanh nhất)
        if self.word_evaluator.is_in_dictionary(word):
            return True, "Từ có trong từ điển"
        
        # 2. Kiểm tra cấu trúc cơ bản
        from app.utils.validators import validate_word_structure
        structure_valid, structure_reason = validate_word_structure(word)
        
        if not structure_valid:
            return False, structure_reason
        
        # Bổ sung: Kiểm tra xem từ đã được lưu quality score chưa
        if word in self.quality_scores and self.quality_scores[word] >= 0.5:
            # Thêm vào từ điển luôn
            await self.word_evaluator.add_to_dictionary(word)
            return True, "Từ có chất lượng cao được đánh giá trước đó"
        
        # 3. Sử dụng Gemini để kiểm tra nghĩa
        has_meaning, meaning_reason = await self.check_word_meaning(word)
        if has_meaning:
            # Try-except để tránh lỗi duplicate
            try:
                await self.word_evaluator.add_to_dictionary(word)
            except Exception as e:
                logger.warning(f"Không thể thêm từ '{word}' vào từ điển: {str(e)}")
            return True, "Từ có nghĩa và đã được thêm vào từ điển"
        else:
            return False, meaning_reason             
               
    async def suggest_words(self, starting_syllable: str) -> List[str]:
        """Suggest words starting with the given syllable"""
        if not starting_syllable:
            return []
            
        # First check cache for matching words
        suggestions = []
        for _, response in self.word_cache.items():
            if response.lower().startswith(starting_syllable.lower()):
                # Get quality score if available
                quality_score = self.quality_scores.get(response, 0.5)
                if quality_score >= 0.5:  # Only suggest reasonably good words
                    suggestions.append(response)
        
        # Sort suggestions by quality score (if available)
        suggestions.sort(key=lambda word: self.quality_scores.get(word, 0.5), reverse=True)
        
        # If not enough suggestions, ask the model
        if len(suggestions) < 5:
            prompt = f"Vui lòng liệt kê 5 từ tiếng Việt phổ biến bắt đầu bằng '{starting_syllable}', mỗi từ nên có 2-3 âm tiết và có nghĩa cụ thể."
            result = await self.generate_response(prompt, use_cache=False)
            
            if not result.startswith("Lỗi:"):
                new_suggestions = [word.strip() for word in result.split('\n') if word.strip()]
                
                # Filter and evaluate new suggestions
                for word in new_suggestions:
                    if word not in suggestions:
                        quality_score, _ = await self.word_evaluator.evaluate_word(word)
                        if quality_score >= 0.5:  # Only add reasonably good words
                            suggestions.append(word)
                            self.quality_scores[word] = quality_score
        
        # Remove duplicates and limit to 5
        unique_suggestions = list(dict.fromkeys(suggestions))
        return unique_suggestions[:5]
    
    async def initialize_system(self):
        """Initialize the entire AI system including dictionaries and warm-up"""
        logger.info("Starting AI system initialization...")
        
        # Initialize word evaluator
        await self.word_evaluator.initialize()
        
        # Perform warm-up
        await self.warm_up_model()
        
        # Log system status
        metrics = self.get_performance_metrics()
        dictionary_stats = {
            "dictionary_size": len(self.word_evaluator.dictionary),
            "common_words": len(self.word_evaluator.common_words),
            "score_cache": len(self.word_evaluator.word_scores)
        }
        
        logger.info(f"AI system initialized successfully. Metrics: {metrics}")
        logger.info(f"Dictionary stats: {dictionary_stats}")
        
        return True
    
    async def check_word_meaning(self, word: str) -> Tuple[bool, str]:
        """Check if a word has actual meaning in Vietnamese using Gemini"""
        prompt = f"Từ '{word}' có phải là một từ có nghĩa trong tiếng Việt không? Chỉ trả lời 'có' hoặc 'không'."
        
        try:
            result = await self.generate_response(prompt, use_cache=True, skip_quality_check=True)
            is_valid = result.lower().startswith("có")
            
            reason = "Từ có nghĩa" if is_valid else "Từ không tồn tại hoặc không có nghĩa"
            return is_valid, reason
        except Exception as e:
            logger.error(f"Error checking word meaning: {str(e)}")
            return False, f"Lỗi kiểm tra nghĩa: {str(e)}"    
        
    async def get_theme_words(self, theme: str) -> List[str]:
        """Lấy từ theo chủ đề từ bộ nhớ đệm hoặc tạo mới"""
        if theme in self.quality_tracker.theme_words_cache:
            # Lấy từ bộ nhớ đệm nếu có
            logger.info(f"Sử dụng từ đã cache cho chủ đề '{theme}'")
            return self.quality_tracker.theme_words_cache[theme]
        
        # Định nghĩa từ theo chủ đề
        theme_mapping = {
            "food": ["thức ăn", "món ăn", "bánh mì", "cơm gạo", "rau củ", "trái cây", 
                    "hoa quả", "thịt cá", "nước uống", "đồ ngọt", "bữa tiệc", 
                    "nhà hàng", "quán ăn", "bếp núc", "gia vị", "mì gói"],
            "animals": ["con vật", "động vật", "con chó", "con mèo", "con cá", "con chim",
                    "thú rừng", "thú cưng", "loài vật", "côn trùng", "gia súc",
                    "chim muông", "thú hoang", "rắn rết", "cá tôm", "gấu bẹo"],
            "nature": ["thiên nhiên", "núi non", "sông ngòi", "biển cả", "bầu trời",
                    "mây mưa", "nắng gió", "rừng rậm", "cây cối", "hoa lá",
                    "đồng cỏ", "bãi biển", "thác nước", "hang động", "sa mạc"],
            "education": ["học tập", "trường học", "lớp học", "sinh viên", "học sinh",
                        "giáo viên", "bài tập", "sách vở", "kiến thức", "trí tuệ",
                        "đại học", "giảng đường", "thư viện", "khóa học", "môn học"],
            "technology": ["công nghệ", "máy tính", "điện thoại", "mạng lưới", "thiết bị",
                        "phần mềm", "thông tin", "dữ liệu", "kỹ thuật", "ứng dụng",
                        "trí tuệ", "robot", "mạng xã", "máy móc", "khoa học"],
            "sports": ["thể thao", "bóng đá", "bóng rổ", "cầu lông", "bơi lội",
                    "võ thuật", "chạy bộ", "đạp xe", "thể dục", "sân vận",
                    "vận động", "sức khỏe", "huấn luyện", "cầu thủ", "vận động"],
            "family": ["gia đình", "cha mẹ", "con cái", "anh em", "chị em",
                    "ông bà", "họ hàng", "tổ tiên", "tình thương", "hạnh phúc",
                    "kỷ niệm", "tương lai", "mái ấm", "tình yêu", "thân thuộc"]
        }
        
        words = []
        
        # Nếu có sẵn từ theo chủ đề
        if theme in theme_mapping:
            words = theme_mapping[theme]
            logger.info(f"Sử dụng {len(words)} từ có sẵn cho chủ đề '{theme}'")
        
        # Nếu là chủ đề tùy chỉnh, sử dụng Gemini để gợi ý
        elif theme != "random":
            prompt = f"Hãy liệt kê 10 từ tiếng Việt gồm 2-3 âm tiết thuộc chủ đề '{theme}'. Mỗi từ phải có nghĩa cụ thể và thường gặp trong đời sống. Chỉ trả lời bằng các từ, mỗi từ một dòng."
            
            try:
                result = await self.generate_response(prompt, use_cache=False)
                
                if not result.startswith("Lỗi:"):
                    words = [word.strip() for word in result.split('\n') if word.strip()]
                    logger.info(f"Tạo {len(words)} từ mới cho chủ đề '{theme}' từ Gemini")
                    
                    # Đánh giá chất lượng các từ nhận được
                    validated_words = []
                    for word in words:
                        # Kiểm tra nếu từ có ít nhất 2 âm tiết
                        if len(word.split()) >= 2:
                            quality, _ = await self.word_evaluator.evaluate_word(word)
                            if quality >= 0.4:  # Chỉ giữ lại từ có chất lượng tốt
                                validated_words.append(word)
                                # Lưu điểm chất lượng
                                self.quality_scores[word] = quality
                    
                    words = validated_words
            except Exception as e:
                logger.error(f"Lỗi khi tạo từ cho chủ đề '{theme}': {str(e)}")
                words = []
        
        # Nếu vẫn không có từ nào, trả về danh sách trống
        if not words:
            logger.warning(f"Không tìm thấy từ nào cho chủ đề '{theme}'")
            return []
        
        # Lưu vào bộ nhớ đệm
        self.quality_tracker.theme_words_cache[theme] = words
        return words
