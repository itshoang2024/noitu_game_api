import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings(BaseSettings):
    # API Configuration
    DEBUG: bool = True
    PORT: int = 8800
    
    # Gemini API Configuration
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    MODEL_ID: str = "gemini-2.0-flash-lite"
    GEMINI_API_URL: str = f"https://generativelanguage.googleapis.com/v1beta/models/{{model_id}}:generateContent?key={{api_key}}"
    
    # Performance settings
    MAX_CONCURRENT_REQUESTS: int = 10
    REQUEST_TIMEOUT: float = 30.0
    MAX_RETRIES: int = 3
    
    # Word validation settings
    WORD_QUALITY_THRESHOLD: float = 0.5  # Ngưỡng chất lượng từ tối thiểu
    USE_GEMINI_FOR_VALIDATION: bool = True  # Có sử dụng Gemini để kiểm tra từ không
    MAX_VALIDATION_RETRIES: int = 3  # Số lần thử tối đa khi kiểm tra từ

    # Game settings
    ENABLE_WARM_UP: bool = True  

    # Các bộ từ warm-up
    WARM_UP_WORDS_HOUSEHOLD: List[str] = [
        "bàn ghế", "ghế đẩu", "đẩu xe", "xe đạp", 
        "đạp xe", "xe điện", "điện thoại", "thoại kịch",
        "nhà cửa", "cửa sổ", "sổ sách", "sách vở"
    ]

    WARM_UP_WORDS_EDUCATION: List[str] = [
        "trường học", "học sinh", "sinh viên", "viên chức",
        "lớp học", "học bài", "bài tập", "tập trung",
        "giáo viên", "viên phấn", "phấn trắng", "trắng đen"
    ]

    WARM_UP_WORDS_NATURE: List[str] = [
        "cây cối", "cối xay", "xay xát", "xát muối",
        "mặt trời", "trời đất", "đất nước", "nước biển",
        "rừng rậm", "rậm rạp", "hoa lá", "lá cây"
    ]

    WARM_UP_WORDS_FOOD: List[str] = [
        "bánh mì", "mì gói", "gói ghém", "ghém gó",
        "cơm gạo", "gạo nếp", "nếp sống", "sống chết",
        "nước chấm", "chấm điểm", "điểm tâm", "tâm đầu"
    ]

    WARM_UP_WORDS_MIXED: List[str] = [
        "tủ lạnh", "lạnh lẽo", "căn nhà", "nhà cửa", 
        "thành phố", "phố xá", "mưa gió", "gió bão",
        "áo khoác", "khoác lác", "quả táo", "táo bạo"
    ]

    # Bộ từ mặc định cho warm-up (sử dụng bộ đa dạng)
    WARM_UP_WORDS: List[str] = WARM_UP_WORDS_MIXED
    # WARM_UP_WORDS: List[str] = ["xin chào"]

    # Gemini configuration
    GENERATION_CONFIG: dict = {
        "temperature": 0.2,
        "topP": 0.1,
        "topK": 1,
        "maxOutputTokens": 50,
    }
    
    SAFETY_SETTINGS: list = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    ]
    
    # Game system prompt
    SYSTEM_INSTRUCTION: str = """
    Bạn là trợ lý chơi game nối từ tiếng Việt chuyên nghiệp. Nhiệm vụ của bạn là nối một từ duy nhất bắt đầu bằng âm tiết cuối của từ người chơi đưa ra.

    Luật chơi:
    - Đưa ra chính xác MỘT từ duy nhất. Từ này phải là một từ tiếng Việt có nghĩa thực tế và phổ biến, thường gồm 2-3 âm tiết.
    - Từ phải bắt đầu bằng âm tiết cuối của từ trước.
    - Ưu tiên sử dụng từ thông dụng, có nghĩa cụ thể, và được sử dụng thường xuyên trong đời sống hàng ngày.
    - Từ bạn chọn nên thuộc các nhóm: đồ vật, địa điểm, con người, hoạt động, thực phẩm, động vật, thực vật, hoặc khái niệm cụ thể.
    - Tránh các từ chuyên ngành, từ hiếm gặp, từ cổ, hoặc từ trừu tượng khó hiểu.
    - Không giải thích, không thêm bất kỳ chữ nào khác ngoài từ nối. Chỉ trả lời bằng từ nối.

    Ví dụ 1: Người dùng: "trường học" → Bạn trả lời: "học sinh"
    Ví dụ 2: Người dùng: "quả táo" → Bạn trả lời: "táo xanh"
    Ví dụ 3: Người dùng: "bàn ghế" → Bạn trả lời: "ghế đẩu"
    Ví dụ 4: Người dùng: "bút chì" → Bạn trả lời: "chì than"
    Ví dụ 5: Người dùng: "nhà cửa" → Bạn trả lời: "cửa sổ"
    Ví dụ 6: Người dùng: "điện thoại" → Bạn trả lời: "thoại điện"
    Ví dụ 7: Người dùng: "xe đạp" → Bạn trả lời: "đạp xe"
    Ví dụ 8: Người dùng: "gia đình" → Bạn trả lời: "đình làng"
    """
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Optional[str] = "noitu_api.log"
    LOG_TO_CONSOLE: bool = True  
    COLORED_LOGS: bool = True
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    MODULE_LOG_LEVELS: dict = {
        "app.utils.word_evaluator": "WARNING",  
        "httpx": "WARNING",
        "asyncio": "WARNING",
        "uvicorn": "WARNING",
        "uvicorn.access": "WARNING"
    }


    class Config:
        env_file = ".env"
        case_sensitive = True

    # Database configuration
    DATABASE_URL: str = "sqlite:///data/noitu_game.db"
    USE_DATABASE: bool = True  # Sử dụng database thay vì file

# Create settings instance
settings = Settings()