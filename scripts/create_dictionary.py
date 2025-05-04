import os
import asyncio
import aiofiles
import aiohttp
import logging

from app.database.base import engine, Base, SessionLocal
from app.database import crud, models
from sqlalchemy.orm import Session

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Basic set of common Vietnamese words for the game
COMMON_WORD_PAIRS = [
    # Học tập
    "trường học", "học sinh", "sinh viên", "viên chức", "chức vụ", "vụ việc",
    "lớp học", "học bài", "bài tập", "tập trung", "trung tâm", "tâm trí",
    "giáo viên", "viên phấn", "phấn trắng", "trắng tinh", "tinh khiết",
    
    # Gia đình
    "gia đình", "đình làng", "làng quê", "quê hương", "hương thơm", "thơm ngát",
    "nhà cửa", "cửa sổ", "sổ sách", "sách vở", "vở kịch", "kịch bản",
    "cha mẹ", "mẹ hiền", "hiền lành", "lành mạnh", "mạnh khỏe", "khỏe mạnh",
    
    # Đồ vật
    "bàn ghế", "ghế đẩu", "đẩu xe", "xe đạp", "đạp xe", "xe đò",
    "tủ lạnh", "lạnh lẽo", "lẽo đẽo", "đẽo gọt", "gọt rửa", "rửa mặt",
    "đèn pin", "pin điện", "điện thoại", "thoại đàm", "đàm thoại", "thoại kịch",
    
    # Thiên nhiên
    "thiên nhiên", "nhiên liệu", "liệu pháp", "pháp luật", "luật pháp", "pháp lệnh",
    "mặt trời", "trời đất", "đất nước", "nước biển", "biển cả", "cả quyết",
    "cây cối", "cối xay", "xay xát", "xát muối", "muối mặn", "mặn nồng",
    
    # Thức ăn
    "thức ăn", "ăn uống", "uống nước", "nước chấm", "chấm điểm", "điểm số",
    "bánh mì", "mì gói", "gói ghém", "ghém gó", "gó bó", "bó buộc",
    "cơm gạo", "gạo nếp", "nếp sống", "sống chết", "chết đói", "đói khát",
    
    # Động vật
    "con mèo", "mèo hoang", "hoang dã", "dã chiến", "chiến đấu", "đấu tranh",
    "con chó", "chó mèo", "mèo lười", "lười biếng", "biếng ăn", "ăn ngủ",
    "cá vàng", "vàng óng", "óng ánh", "ánh sáng", "sáng láng", "láng giềng"
]

# Additional common Vietnamese words
COMMON_WORDS = [
    "hạnh phúc", "mưa gió", "đường phố", "thành phố", "phố xá",
    "cà phê", "phê bình", "bình minh", "minh bạch", "bạch tuộc",
    "máy tính", "tính toán", "toán học", "học hành", "hành động",
    "đồng hồ", "hồ nước", "nước ngọt", "ngọt ngào", "ngào dữ",
    "áo quần", "quần áo", "áo khoác", "khoác lác", "lác đác",
    "bệnh viện", "viện trợ", "trợ lý", "lý do", "do dự",
    "mặt trăng", "trăng sao", "sao chổi", "chổi quét", "quét dọn",
    "ghế đá", "đá quý", "quý báu", "báu vật", "vật chất",
    "cây cảnh", "cảnh quan", "quan trọng", "trọng lượng", "lượng giá",
    "hoa quả", "quả thực", "thực phẩm", "phẩm chất", "chất lượng",
    "áo ấm", "ấm áp", "áp lực", "lực sĩ", "sĩ quan",
    "bút bi", "bi kịch", "kịch tính", "tính toán", "toán học",
    "trà đá", "đá banh", "banh hỏng", "hỏng hóc", "hóc búa",
    "xe buýt", "buýt đỏ", "đỏ tươi", "tươi cười", "cười vui"
]

# Vietnamese syllables to check against
VIETNAMESE_SYLLABLES = [
    # Commonly used syllables for prefix
    "anh", "ba", "bài", "bàn", "bạn", "bảo", "biển", "bóng", "buổi", "bút",
    "cá", "cái", "căn", "cây", "cha", "chất", "chiếc", "chiến", "chính", "chủ",
    "con", "công", "cơ", "cửa", "của", "cuộc", "dân", "dòng", "dự", "đá",
    "đất", "đèn", "đêm", "điện", "điểm", "đời", "đồng", "đường", "em", "gia",
    "giá", "giờ", "hàng", "hiện", "hình", "hoa", "hoạt", "học", "hồ", "hướng",
    "kế", "khách", "khai", "khoa", "khóa", "không", "kiến", "kiểm", "kim", "kính",
    "kỳ", "lá", "lãnh", "lập", "lẽ", "lịch", "liên", "loại", "lớp", "lực",
    "lưới", "lượng", "mã", "mặt", "máy", "mẹ", "miền", "miệng", "mình", "mô",
    "môi", "một", "mối", "mục", "nam", "năm", "ngày", "nghiên", "nghệ", "ngôi",
    "người", "nhà", "nhân", "nhiệm", "nhóm", "những", "niên", "nội", "nông", "nước",
    "ông", "phần", "pháp", "phòng", "phương", "quá", "quản", "quốc", "rừng", "sách",
    "sân", "số", "sở", "sức", "sự", "tài", "tâm", "tập", "tất", "tên",
    "thành", "thể", "thiết", "thời", "thực", "tiến", "tiếng", "tiêu", "tin", "toàn",
    "tổ", "tổng", "trình", "trung", "trường", "từ", "tư", "tự", "văn", "vấn",
    "vật", "viện", "việc", "vùng", "xa", "xã", "xuất", "ý"
]

async def generate_dictionary_files():
    """Generate basic dictionary files for Vietnamese words"""
    os.makedirs("./data", exist_ok=True)
    
    # Generate main dictionary file
    dictionary_path = "./data/vietnamese_dictionary.txt"
    common_words_path = "./data/common_words.txt"
    
    # Combine all words and remove duplicates
    all_words = set(COMMON_WORD_PAIRS + COMMON_WORDS)
    logger.info(f"Combined word list contains {len(all_words)} unique words")
    
    # Write to dictionary file
    async with aiofiles.open(dictionary_path, mode='w', encoding='utf-8') as f:
        await f.write('\n'.join(sorted(all_words)))
    logger.info(f"Dictionary file created at {dictionary_path}")
    
    # Write to common words file (subset of most common words)
    common_subset = sorted(set(COMMON_WORD_PAIRS))
    async with aiofiles.open(common_words_path, mode='w', encoding='utf-8') as f:
        await f.write('\n'.join(common_subset))
    logger.info(f"Common words file created at {common_words_path}")
    
    return {
        "dictionary_size": len(all_words),
        "common_words_count": len(common_subset)
    }

async def fetch_additional_vietnamese_words():
    """Optional: Fetch additional Vietnamese words from online sources"""
    logger.info("Attempting to fetch additional Vietnamese words...")
    
    try:
        # This is a placeholder - in practice you would need to find a legitimate API
        # or data source for Vietnamese words
        async with aiohttp.ClientSession() as session:
            async with session.get("https://example.com/api/vietnamese-words") as response:
                if response.status == 200:
                    data = await response.json()
                    additional_words = data.get("words", [])
                    logger.info(f"Fetched {len(additional_words)} additional words")
                    return additional_words
                else:
                    logger.warning(f"Failed to fetch additional words: {response.status}")
                    return []
    except Exception as e:
        logger.error(f"Error fetching additional words: {str(e)}")
        return []

async def generate_dictionary_in_database():
    """Tạo từ điển trong database"""
    # Đảm bảo các bảng đã được tạo
    Base.metadata.create_all(bind=engine)
    
    # Tạo session
    db = SessionLocal()
    
    try:
        # Kiểm tra nếu database đã có dữ liệu
        word_count = db.query(models.Word).count()
        if word_count > 0:
            logger.info(f"Database already contains {word_count} words, skipping initialization")
            return {"existing_words": word_count}
        
        # Tạo các chủ đề mặc định
        themes = {
            "random": "Ngẫu nhiên",
            "food": "Ẩm thực",
            "animals": "Động vật",
            "nature": "Thiên nhiên",
            "education": "Giáo dục",
            "technology": "Công nghệ",
            "sports": "Thể thao",
            "family": "Gia đình"
        }
        
        theme_objects = {}
        for theme_id, theme_name in themes.items():
            theme = models.Theme(
                name=theme_id,
                description=theme_name,
                is_default=(theme_id == "random")
            )
            db.add(theme)
            db.flush()
            theme_objects[theme_id] = theme
            
        logger.info(f"Created {len(themes)} default themes")
        
        # Thêm các từ theo mảng
        words_added = 0
        common_words_added = 0
        
        # Thêm các từ phổ biến
        for word in COMMON_WORD_PAIRS:
            syllables = word.split()
            word_obj = models.Word(
                word=word,
                quality_score=0.7,  # Điểm chất lượng cao cho từ mặc định
                is_common=True,
                syllable_count=len(syllables),
                first_syllable=syllables[0] if syllables else "",
                last_syllable=syllables[-1] if syllables else ""
            )
            db.add(word_obj)
            words_added += 1
            common_words_added += 1
            
            # Thêm vào chủ đề phù hợp
            if any(food_word in word for food_word in ["ăn", "uống", "bánh", "cơm", "gạo", "mì"]):
                db.add(models.ThemeWord(theme_id=theme_objects["food"].id, word_id=word_obj.id))
            
            if any(animal_word in word for animal_word in ["con", "mèo", "chó", "cá", "vàng"]):
                db.add(models.ThemeWord(theme_id=theme_objects["animals"].id, word_id=word_obj.id))
            
            if any(nature_word in word for nature_word in ["trời", "đất", "nước", "biển", "cây", "cối"]):
                db.add(models.ThemeWord(theme_id=theme_objects["nature"].id, word_id=word_obj.id))
            
            if any(edu_word in word for edu_word in ["học", "trường", "sinh", "viên", "giáo", "sách"]):
                db.add(models.ThemeWord(theme_id=theme_objects["education"].id, word_id=word_obj.id))
        
        # Thêm các từ phổ biến khác
        for word in COMMON_WORDS:
            syllables = word.split()
            word_obj = models.Word(
                word=word,
                quality_score=0.6,
                is_common=False,  # Không đánh dấu là common để giảm số lượng
                syllable_count=len(syllables),
                first_syllable=syllables[0] if syllables else "",
                last_syllable=syllables[-1] if syllables else ""
            )
            db.add(word_obj)
            words_added += 1
            
        # Commit các thay đổi
        db.commit()
        logger.info(f"Added {words_added} words to database, including {common_words_added} common words")
        
        return {
            "words_added": words_added,
            "common_words_added": common_words_added,
            "themes_created": len(themes)
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error generating dictionary in database: {str(e)}")
        raise
    finally:
        db.close()

async def main():
    """Main function to generate dictionary"""
    logger.info("Starting dictionary generation...")
    
    # Tạo từ điển trong database
    stats_db = await generate_dictionary_in_database()
    logger.info(f"Database dictionary generation complete. Stats: {stats_db}")
    
    # Vẫn giữ lại code tạo file để tương thích ngược
    stats_file = await generate_dictionary_files()
    logger.info(f"File dictionary generation complete. Stats: {stats_file}")

if __name__ == "__main__":
    asyncio.run(main())