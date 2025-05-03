import asyncio
import time
import logging
from typing import Dict, List, Optional, Tuple
import httpx
from asyncio import Semaphore

from app.config import settings
from app.utils.word_evaluator import WordEvaluator

logger = logging.getLogger(__name__)

from datetime import datetime
import json
import os

from app.utils.constants import QUALITY_METRICS_PATH

class QualityTracker:
    """Tracks word quality metrics over time"""
    
    def __init__(self):
        """Initialize quality tracker with proper path"""
        self.file_path = QUALITY_METRICS_PATH
        self.metrics = []
        self.theme_words_cache: Dict[str, List[str]] = {}  # Lưu trữ từ theo chủ đề
        self.load_metrics()
        self.load_theme_words()  # Tải chủ đề khi khởi tạo

    def load_metrics(self):
        """Load existing metrics from file"""
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    self.metrics = json.load(f)
                logger.info(f"Loaded {len(self.metrics)} quality metric records")
        except Exception as e:
            logger.error(f"Error loading quality metrics: {str(e)}")
            self.metrics = []
    
    async def save_metrics(self):
        """Save metrics to file"""
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.metrics, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {len(self.metrics)} quality metric records")
            return True
        except Exception as e:
            logger.error(f"Error saving quality metrics: {str(e)}")
            return False
    
    def add_metric(self, word, score, user_input=None, session_id=None):
        """Add a new quality metric"""
        metric = {
            "timestamp": datetime.now().isoformat(),
            "word": word,
            "score": score,
            "user_input": user_input,
            "session_id": session_id
        }
        self.metrics.append(metric)
        
        # Periodically save metrics (e.g., every 10 records)
        if len(self.metrics) % 10 == 0:
            asyncio.create_task(self.save_metrics())
    
    def get_average_score(self, period=None):
        """Get average quality score, optionally filtered by period"""
        if not self.metrics:
            return 0.0
            
        if period:
            # Filter by time period (e.g. 'day', 'week', 'month')
            now = datetime.now()
            filtered_metrics = []
            
            for metric in self.metrics:
                try:
                    metric_time = datetime.fromisoformat(metric["timestamp"])
                    if period == 'day' and (now - metric_time).days <= 1:
                        filtered_metrics.append(metric)
                    elif period == 'week' and (now - metric_time).days <= 7:
                        filtered_metrics.append(metric)
                    elif period == 'month' and (now - metric_time).days <= 30:
                        filtered_metrics.append(metric)
                except Exception:
                    continue
            
            if not filtered_metrics:
                return 0.0
                
            total = sum(m["score"] for m in filtered_metrics)
            return total / len(filtered_metrics)
        else:
            # All time average
            total = sum(m["score"] for m in self.metrics)
            return total / len(self.metrics)
    
    def get_summary_stats(self):
        """Get summary statistics about word quality"""
        if not self.metrics:
            return {
                "count": 0,
                "avg_score": 0.0,
                "avg_score_day": 0.0,
                "avg_score_week": 0.0,
                "avg_score_month": 0.0
            }
            
        return {
            "count": len(self.metrics),
            "avg_score": self.get_average_score(),
            "avg_score_day": self.get_average_score('day'),
            "avg_score_week": self.get_average_score('week'),
            "avg_score_month": self.get_average_score('month')
        }
    
    async def save_theme_words(self):
        """Lưu danh sách từ theo chủ đề vào file"""
        try:
            theme_file_path = os.path.join(os.path.dirname(self.file_path), "theme_words.json")
            with open(theme_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.theme_words_cache, f, ensure_ascii=False, indent=2)
            logger.info(f"Đã lưu {len(self.theme_words_cache)} chủ đề vào {theme_file_path}")
            return True
        except Exception as e:
            logger.error(f"Lỗi khi lưu từ theo chủ đề: {str(e)}")
            return False
    
    def load_theme_words(self):
        """Tải danh sách từ theo chủ đề từ file"""
        try:
            theme_file_path = os.path.join(os.path.dirname(self.file_path), "theme_words.json")
            if os.path.exists(theme_file_path):
                with open(theme_file_path, 'r', encoding='utf-8') as f:
                    self.theme_words_cache = json.load(f)
                logger.info(f"Đã tải {len(self.theme_words_cache)} chủ đề từ {theme_file_path}")
        except Exception as e:
            logger.error(f"Lỗi khi tải từ theo chủ đề: {str(e)}")
            self.theme_words_cache = {}

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
        logger.info("AIService and WordEvaluator initialized")

    async def close(self):
        """Close resources"""
        if self.http_client:
            await self.http_client.aclose()
            logger.info("HTTP client closed")

    async def warm_up_model(self):
        """Warm up the model with predefined words"""
        logger.info("Starting model warm-up...")
        await self.initialize()  # Ensure word evaluator is initialized
        start_time = time.time()
        
        # Limit concurrent requests during warm-up 
        batch_size = 6  # Chỉ xử lý 4 từ một lúc
        semaphore = asyncio.Semaphore(3)  # Giới hạn đồng thời tối đa 3 yêu cầu
        
        async def warm_up_word(word):
            async with semaphore:
                try:
                    start = time.time()
                    result = await self.generate_response(word, use_cache=False)
                    end = time.time()
                    
                    # Evaluate word quality
                    if not result.startswith("Lỗi:"):
                        quality_score, reason = await self.word_evaluator.evaluate_word(result)
                        logger.info(f"Warm-up: '{word}' → '{result}' (Score: {quality_score:.2f}, Reason: {reason})")
                        self.quality_scores[result] = quality_score
                    else:
                        logger.warning(f"Warm-up error: '{word}' → '{result}'")
                    
                    return word, result, end - start
                except Exception as e:
                    logger.error(f"Error warming up word '{word}': {str(e)}")
                    return word, f"Lỗi: {str(e)}", 0
        
        success_count = 0
        total_time = 0.0
        
        # Xử lý từng lô từ
        for i in range(0, len(settings.WARM_UP_WORDS), batch_size):
            batch = settings.WARM_UP_WORDS[i:i+batch_size]
            logger.info(f"Đang xử lý lô {i//batch_size + 1}/{(len(settings.WARM_UP_WORDS) + batch_size - 1) // batch_size}")
            
            # Xử lý lô hiện tại
            tasks = [warm_up_word(word) for word in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Xử lý kết quả
            for result in batch_results:
                if isinstance(result, tuple) and len(result) == 3:
                    word, response, response_time = result
                    if not response.startswith("Lỗi:"):
                        self.word_cache[word] = response
                        success_count += 1
                        total_time += response_time
            
            # Chờ trước khi xử lý lô tiếp theo để tránh rate limiting
            if i + batch_size < len(settings.WARM_UP_WORDS):
                wait_time = 5  # Đợi 5 giây giữa các lô
                logger.info(f"Hoàn thành lô {i//batch_size + 1}, đợi {wait_time}s trước lô tiếp theo...")
                await asyncio.sleep(wait_time)
        
        # Calculate average response time
        if success_count > 0:
            self.average_response_time = total_time / success_count
        
        duration = time.time() - start_time
        logger.info(f"Warm-up hoàn thành trong {duration:.2f}s. {success_count}/{len(settings.WARM_UP_WORDS)} thành công. Thời gian phản hồi TB: {self.average_response_time:.3f}s")
        
        # Lưu các chủ đề nếu có
        if hasattr(self.quality_tracker, 'theme_words_cache') and self.quality_tracker.theme_words_cache:
            await self.quality_tracker.save_theme_words()
        
        self.is_ready = True

    async def generate_response(self, user_input: str, use_cache: bool = True, max_retries: int = None, quality_threshold: float = 0.4, skip_quality_check: bool = False) -> str:
        """Generate a response from Gemini API with retry logic and quality check"""
        if max_retries is None:
            max_retries = settings.MAX_RETRIES
            
        # Check cache first
        if use_cache and user_input in self.word_cache:
            logger.debug(f"Cache hit for: '{user_input}'")
            return self.word_cache[user_input]
        
        logger.debug(f"Cache miss for: '{user_input}'. Calling Gemini API...")
        self.total_requests += 1
        
        # Prepare prompt for Gemini
        prompt_text = f"{settings.SYSTEM_INSTRUCTION}\nNgười dùng: {user_input}\n→"
        
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
    
    async def generate_high_quality_response(self, user_input: str, max_attempts: int = 3, quality_threshold: float = 0.7, session_id: str = None) -> Tuple[str, float]:
        """Generate a high-quality response with multiple attempts if needed"""
        best_response = None
        best_score = 0.0
        
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
        
        # If all attempts failed, return best response or error
        if best_response is None:
            return "Lỗi: Không thể tạo từ chất lượng cao.", 0.0
        
        # Track quality metrics
        self.quality_tracker.add_metric(best_response, best_score, user_input, session_id)
                
        return best_response, best_score
    
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
        
        # 3. Sử dụng Gemini để kiểm tra nghĩa (chính xác nhất nhưng chậm hơn)
        has_meaning, meaning_reason = await self.check_word_meaning(word)
        if has_meaning:
            await self.word_evaluator.add_to_dictionary(word)
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
