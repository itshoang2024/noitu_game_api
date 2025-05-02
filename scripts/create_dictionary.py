import os
import asyncio
import aiofiles
import aiohttp
import logging

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
    "mặt trăng", "trăng sao", "sao chổi", "chổi quét", "quét dọn"
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

async def main():
    """Main function to generate dictionary files"""
    logger.info("Starting dictionary generation...")
    
    # First generate basic dictionary
    stats = await generate_dictionary_files()
    
    logger.info(f"Dictionary generation complete. Stats: {stats}")
    
    # Optionally attempt to fetch additional words
    # additional_words = await fetch_additional_vietnamese_words()
    # if additional_words:
    #     # Update dictionary with additional words
    #     pass

if __name__ == "__main__":
    asyncio.run(main())