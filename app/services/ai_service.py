import asyncio
import time
import logging
from typing import Dict, List, Tuple, Union
import httpx
from asyncio import Semaphore

from datetime import datetime

from app.config import settings
from app.utils.word_evaluator import WordEvaluator
from app.database.base import get_async_db
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

    def get_summary_stats(self) -> Dict[str, Union[int, float]]:
        """Return aggregate quality statistics for recent metrics."""
        if not self.metrics:
            return {
                "total_metrics": 0,
                "average_score": 0.0,
                "max_score": 0.0,
                "min_score": 0.0,
                "high_quality_count": 0,
            }

        scores = [
            metric["score"]
            for metric in self.metrics
            if isinstance(metric.get("score"), (int, float))
        ]
        if not scores:
            return {
                "total_metrics": len(self.metrics),
                "average_score": 0.0,
                "max_score": 0.0,
                "min_score": 0.0,
                "high_quality_count": 0,
            }

        return {
            "total_metrics": len(self.metrics),
            "average_score": round(sum(scores) / len(scores), 4),
            "max_score": round(max(scores), 4),
            "min_score": round(min(scores), 4),
            "high_quality_count": sum(score >= 0.7 for score in scores),
        }

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
    NORMAL_RESPONSE_FALLBACK = "Lễ hội hôm nay đông vui thật, mình thấy vui khi được ở đây."
    
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

    def _extract_http_error_details(self, exc: httpx.HTTPStatusError) -> str:
        try:
            error_data = exc.response.json()
            return error_data.get("error", {}).get("message", exc.response.text)
        except Exception:
            return exc.response.text or str(exc)

    def _get_model_pool(self) -> List[str]:
        configured_pool = settings.MODEL_POOL or []
        if isinstance(configured_pool, str):
            configured_pool = [item.strip() for item in configured_pool.split(",") if item.strip()]

        model_pool = []
        for model_id in [settings.MODEL_ID, *configured_pool]:
            normalized_model_id = str(model_id).strip()
            if normalized_model_id and normalized_model_id not in model_pool:
                model_pool.append(normalized_model_id)

        return model_pool or [settings.MODEL_ID]

    def _build_gemini_api_url(self, model_id: str) -> str:
        return settings.GEMINI_API_URL.format(
            model_id=model_id,
            api_key=settings.GEMINI_API_KEY
        )

    def _should_fallback_model(self, exc: httpx.HTTPStatusError) -> bool:
        return exc.response.status_code == 503

    async def _post_gemini_with_model_pool(self, payload: dict, request_label: str) -> Tuple[httpx.Response, str]:
        model_pool = self._get_model_pool()
        last_error = None

        for index, model_id in enumerate(model_pool):
            try:
                response = await self.http_client.post(
                    self._build_gemini_api_url(model_id),
                    json=payload,
                )
                response.raise_for_status()
                return response, model_id
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if not self._should_fallback_model(exc):
                    raise

                if index >= len(model_pool) - 1:
                    raise

                next_model_id = model_pool[index + 1]
                error_details = self._extract_http_error_details(exc)
                logger.warning(
                    "Gemini model %s returned HTTP 503 for %s: %s. Trying fallback model %s.",
                    model_id,
                    request_label,
                    error_details,
                    next_model_id,
                )

        if last_error:
            raise last_error

        raise RuntimeError("No Gemini model configured")

    async def _ensure_warm_up_dependencies(self):
        await self.initialize()
        if self.word_evaluator.is_initialized:
            return

        logger.error("WordEvaluator initialization failed, forcing initialization")
        self.word_evaluator.is_initialized = True
        await self.word_evaluator.build_word_chains()

    def _update_recent_times(self, recent_times: List[float], process_time: float):
        recent_times.append(process_time)
        if len(recent_times) > 5:
            recent_times.pop(0)

    def _adjust_warm_up_concurrency(
        self,
        current_concurrency: int,
        recent_times: List[float],
        min_concurrency: int,
        max_concurrency: int,
    ) -> int:
        if not recent_times:
            return current_concurrency

        average_time = sum(recent_times) / len(recent_times)
        if average_time > 2.5 and current_concurrency > min_concurrency:
            new_concurrency = max(min_concurrency, current_concurrency - 1)
            logger.info(f"Reducing concurrency to {new_concurrency} (avg response: {average_time:.2f}s)")
            return new_concurrency

        if average_time < 1.0 and current_concurrency < max_concurrency:
            new_concurrency = min(max_concurrency, current_concurrency + 1)
            logger.info(f"Increasing concurrency to {new_concurrency} (avg response: {average_time:.2f}s)")
            return new_concurrency

        return current_concurrency

    async def _warm_up_single_word(self, seed_word: str) -> Tuple[bool, float]:
        try:
            start_time = time.time()
            generated_word = await self.generate_response(seed_word, use_cache=False)
            process_time = time.time() - start_time

            if generated_word.startswith("Lỗi:"):
                logger.warning(f"Warm-up error: '{seed_word}' → '{generated_word}'")
                return False, process_time

            quality_score, _ = await self.word_evaluator.evaluate_word(generated_word)
            logger.info(
                f"Warm-up: '{seed_word}' → '{generated_word}' "
                f"(Score: {quality_score:.2f}, Time: {process_time:.2f}s)"
            )
            self.quality_scores[generated_word] = quality_score
            self.word_cache[seed_word] = generated_word
            return True, process_time
        except Exception as exc:
            logger.error(f"Error processing '{seed_word}': {str(exc)}")
            return False, 0.0

    async def warm_up_model(self):
        """Warm up the model with an adaptive, efficient strategy"""
        if not settings.ENABLE_WARM_UP:
            logger.info("Skipping model warm-up because ENABLE_WARM_UP=False")
            return

        logger.info("Starting model warm-up with adaptive strategy...")

        await self._ensure_warm_up_dependencies()

        start_time = time.time()
        min_concurrency = 1
        max_concurrency = 8
        current_concurrency = 3
        max_retries_per_word = 2

        pending_items = list(enumerate(settings.WARM_UP_WORDS))
        retry_counts: Dict[int, int] = {}
        completed_item_ids = set()
        recent_times: List[float] = []
        success_count = 0
        total_time = 0.0
        total_words = len(pending_items)

        while pending_items:
            batch_items = pending_items[:current_concurrency]
            pending_items = pending_items[current_concurrency:]
            batch_tasks = [self._warm_up_single_word(seed_word) for _, seed_word in batch_items]
            batch_results = await asyncio.gather(*batch_tasks)

            for (item_id, seed_word), (is_success, process_time) in zip(batch_items, batch_results):
                if process_time > 0:
                    self._update_recent_times(recent_times, process_time)

                if is_success:
                    success_count += 1
                    total_time += process_time
                    completed_item_ids.add(item_id)
                    continue

                retry_counts[item_id] = retry_counts.get(item_id, 0) + 1
                if retry_counts[item_id] <= max_retries_per_word:
                    pending_items.append((item_id, seed_word))
                else:
                    completed_item_ids.add(item_id)

            current_concurrency = self._adjust_warm_up_concurrency(
                current_concurrency=current_concurrency,
                recent_times=recent_times,
                min_concurrency=min_concurrency,
                max_concurrency=max_concurrency,
            )

            if total_words:
                progress = len(completed_item_ids) / total_words * 100
                logger.info(f"Warm-up progress: {progress:.1f}% ({len(pending_items)} words remaining)")

        if success_count > 0:
            self.average_response_time = total_time / success_count

        duration = time.time() - start_time
        logger.info(
            f"Warm-up completed in {duration:.2f}s. "
            f"{success_count}/{len(settings.WARM_UP_WORDS)} successful. "
            f"Average response time: {self.average_response_time:.3f}s"
        )

        if hasattr(self.quality_tracker, "theme_words_cache") and self.quality_tracker.theme_words_cache:
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
                    
                    response, model_id = await self._post_gemini_with_model_pool(
                        payload,
                        request_label="word generation",
                    )
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
                            logger.debug("Gemini model %s generated word response", model_id)
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
                        logger.debug("Gemini model %s generated word response", model_id)
                    else:
                        self.failed_requests += 1
                    
                    return reply
                    
                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    retries += 1
                    if retries > max_retries:
                        logger.error(f"Failed after {max_retries} retries: {str(e)}")
                        self.failed_requests += 1
                        if isinstance(e, httpx.HTTPStatusError):
                            error_details = self._extract_http_error_details(e)
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
            response = await self.generate_response(
                user_input,
                session_id=session_id,
                game_service=game_service,
                use_cache=(attempt == 0),
            )
            
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
            await self.quality_tracker.add_metric(best_response, best_score, user_input, session_id)
                
        return best_response or "Lỗi: Không thể tạo từ chất lượng cao.", best_score
    
    async def generate_normal_response(self, user_input: str, max_retries: int = settings.MAX_RETRIES) -> str:
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

        self.total_requests += 1

        async with self.request_semaphore:
            retries = 0
            while retries <= max_retries:
                try:
                    start_time = time.time()

                    response, model_id = await self._post_gemini_with_model_pool(
                        payload,
                        request_label="normal response",
                    )
                    result = response.json()

                    response_time = time.time() - start_time
                    self.average_response_time = (
                        self.average_response_time * self.successful_requests + response_time
                    ) / (self.successful_requests + 1)

                    if not result.get("candidates"):
                        feedback = result.get("promptFeedback")
                        block_reason = feedback.get("blockReason", "No candidates found") if feedback else "No candidates found"
                        logger.warning(f"Gemini normal response returned no candidates: {block_reason}")
                        self.failed_requests += 1
                        return self.NORMAL_RESPONSE_FALLBACK

                    first_candidate = result["candidates"][0]
                    if "content" not in first_candidate or "parts" not in first_candidate["content"]:
                        logger.warning("Gemini normal response had unexpected response structure")
                        self.failed_requests += 1
                        return self.NORMAL_RESPONSE_FALLBACK

                    reply_parts = first_candidate["content"]["parts"]
                    if not reply_parts or "text" not in reply_parts[0]:
                        logger.warning("Gemini normal response was missing text content")
                        self.failed_requests += 1
                        return self.NORMAL_RESPONSE_FALLBACK

                    reply = reply_parts[0]["text"].strip()
                    if not reply:
                        logger.warning("Gemini normal response was empty")
                        self.failed_requests += 1
                        return self.NORMAL_RESPONSE_FALLBACK

                    logger.debug("Gemini model %s generated normal response", model_id)
                    self.successful_requests += 1
                    return reply

                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    retries += 1
                    if retries > max_retries:
                        self.failed_requests += 1
                        if isinstance(e, httpx.HTTPStatusError):
                            error_details = self._extract_http_error_details(e)
                            logger.error(
                                "Gemini normal response failed after %s retries with HTTP %s: %s",
                                max_retries,
                                e.response.status_code,
                                error_details,
                            )
                        else:
                            logger.error(
                                "Gemini normal response failed after %s retries: %s",
                                max_retries,
                                str(e),
                            )
                        return self.NORMAL_RESPONSE_FALLBACK

                    wait_time = 0.5 * (2 ** retries)
                    if isinstance(e, httpx.HTTPStatusError):
                        error_details = self._extract_http_error_details(e)
                        logger.warning(
                            "Retry %s/%s for normal Gemini response after HTTP %s: %s",
                            retries,
                            max_retries,
                            e.response.status_code,
                            error_details,
                        )
                    else:
                        logger.warning(
                            "Retry %s/%s for normal Gemini response after request error: %s",
                            retries,
                            max_retries,
                            str(e),
                        )
                    await asyncio.sleep(wait_time)

                except Exception as e:
                    logger.error(
                        "Unexpected error while generating normal Gemini response: %s",
                        str(e),
                        exc_info=True,
                    )
                    self.failed_requests += 1
                    return self.NORMAL_RESPONSE_FALLBACK

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
