import asyncio
import time
import logging
from typing import Dict, List, Optional, Tuple
import httpx
from asyncio import Semaphore

from app.config import settings

logger = logging.getLogger(__name__)

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
        self.is_ready = False
        self.request_semaphore = Semaphore(settings.MAX_CONCURRENT_REQUESTS)

    async def close(self):
        """Close resources"""
        if self.http_client:
            await self.http_client.aclose()
            logger.info("HTTP client closed")
    
    async def warm_up_model(self):
        """Warm up the model with predefined words"""
        logger.info("Starting model warm-up...")
        start_time = time.time()
        
        # Limit concurrent requests during warm-up
        semaphore = asyncio.Semaphore(5)
        
        async def warm_up_word(word):
            async with semaphore:
                result = await self.generate_response(word, use_cache=False)
                logger.info(f"Warm-up: '{word}' → '{result}'")
                return word, result
        
        tasks = [warm_up_word(word) for word in settings.WARM_UP_WORDS]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = 0
        for i, result in enumerate(results):
            if isinstance(result, Tuple) and len(result) == 2:
                word, response = result
                if not response.startswith("Lỗi:"):
                    self.word_cache[word] = response
                    success_count += 1
            elif isinstance(result, Exception):
                logger.error(f"Error during warm-up: {str(result)}")
        
        duration = time.time() - start_time
        logger.info(f"Warm-up completed in {duration:.2f}s. {success_count}/{len(settings.WARM_UP_WORDS)} successful.")
        self.is_ready = True

    async def generate_response(self, user_input: str, use_cache: bool = True, max_retries: int = None) -> str:
        """Generate a response from Gemini API with retry logic"""
        if max_retries is None:
            max_retries = settings.MAX_RETRIES
            
        # Check cache first
        if use_cache and user_input in self.word_cache:
            logger.debug(f"Cache hit for: '{user_input}'")
            return self.word_cache[user_input]
        
        logger.debug(f"Cache miss for: '{user_input}'. Calling Gemini API...")
        
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
            while retries <= max_retries:
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
                        feedback = result.get("promptFeedback")
                        block_reason = feedback.get("blockReason", "Unknown") if feedback else "No candidates found"
                        logger.error(f"Gemini API Error: No candidates. Reason: {block_reason}")
                        
                        if feedback and feedback.get("safetyRatings"):
                            logger.error(f"Safety Ratings: {feedback.get('safetyRatings')}")
                        
                        return f"Lỗi: Gemini không thể tạo phản hồi (Reason: {block_reason})."
                    
                    # Extract text from response
                    first_candidate = result["candidates"][0]
                    if "content" not in first_candidate or "parts" not in first_candidate["content"]:
                        logger.error(f"Gemini API Error: Unexpected response structure")
                        finish_reason = first_candidate.get("finishReason", "Unknown")
                        if finish_reason != "STOP":
                            return f"Lỗi: Gemini dừng tạo phản hồi vì lý do '{finish_reason}'."
                        return "Lỗi: Không thể trích xuất nội dung từ Gemini."
                    
                    reply_parts = first_candidate["content"]["parts"]
                    if not reply_parts or "text" not in reply_parts[0]:
                        logger.error(f"Gemini API Error: Missing text in parts")
                        return "Lỗi: Không thể trích xuất văn bản từ Gemini."
                    
                    reply = reply_parts[0]["text"].strip()
                    
                    # Validate response
                    if not reply or len(reply.split()) > 5:
                        logger.warning(f"Warning: Potentially invalid response: '{reply}'")
                    
                    # Cache successful responses
                    if reply and not reply.startswith("Lỗi:"):
                        self.word_cache[user_input] = reply
                    
                    return reply
                    
                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    retries += 1
                    if retries > max_retries:
                        logger.error(f"Failed after {max_retries} retries: {str(e)}")
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
                    return f"Lỗi: Lỗi máy chủ nội bộ khi xử lý yêu cầu ({type(e).__name__})."
    
    def get_cached_words(self) -> int:
        """Get the number of cached words"""
        return len(self.word_cache)
    
    def get_cache(self) -> Dict[str, str]:
        """Get the current cache"""
        return self.word_cache
    
    def reset_cache(self) -> int:
        """Reset the cache and return count of removed items"""
        count = len(self.word_cache)
        self.word_cache = {}
        logger.info(f"Cache cleared. Removed {count} entries.")
        return count

    async def explain_word(self, word: str) -> str:
        """Get explanation for a word"""
        prompt = f"Vui lòng giải thích ngắn gọn nghĩa của từ '{word}' trong tiếng Việt. Chỉ trả lời nghĩa, không thêm giải thích."
        return await self.generate_response(prompt, use_cache=True)
    
    async def validate_vietnamese_word(self, word: str) -> Tuple[bool, str]:
        """Check if a word is valid Vietnamese"""
        prompt = f"Từ '{word}' có phải là một từ có nghĩa trong tiếng Việt không? Chỉ trả lời 'có' hoặc 'không'."
        result = await self.generate_response(prompt, use_cache=True)
        
        is_valid = result.lower().startswith("có")
        reason = "Từ hợp lệ" if is_valid else "Từ không tồn tại hoặc không có nghĩa"
        
        return is_valid, reason
    
    async def suggest_words(self, starting_syllable: str) -> List[str]:
        """Suggest words starting with the given syllable"""
        if not starting_syllable:
            return []
            
        # First check cache for matching words
        suggestions = []
        for _, response in self.word_cache.items():
            if response.lower().startswith(starting_syllable.lower()):
                suggestions.append(response)
        
        # If not enough suggestions, ask the model
        if len(suggestions) < 5:
            prompt = f"Vui lòng liệt kê 5 từ tiếng Việt bắt đầu bằng '{starting_syllable}', mỗi từ nên có 2 âm tiết trở lên."
            result = await self.generate_response(prompt, use_cache=False)
            
            if not result.startswith("Lỗi:"):
                new_suggestions = [word.strip() for word in result.split('\n') if word.strip()]
                suggestions.extend(new_suggestions)
        
        # Remove duplicates and limit to 5
        unique_suggestions = list(dict.fromkeys(suggestions))
        return unique_suggestions[:5]