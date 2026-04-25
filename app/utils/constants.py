import os

# Calculate base directory once
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Data directory
DATA_DIR = os.path.join(BASE_DIR, "data")

# Dictionary file paths
DICTIONARY_PATH = os.path.join(DATA_DIR, "vietnamese_dictionary.txt")
COMMON_WORDS_PATH = os.path.join(DATA_DIR, "common_words.txt")
QUALITY_METRICS_PATH = os.path.join(DATA_DIR, "quality_metrics.json")

# Default themes exposed by game endpoints
DEFAULT_GAME_THEMES = [
	{"id": "random", "name": "Ngẫu nhiên", "description": "Chọn từ ngẫu nhiên từ mọi chủ đề"},
	{"id": "food", "name": "Ẩm thực", "description": "Các từ liên quan đến thức ăn, đồ uống"},
	{"id": "animals", "name": "Động vật", "description": "Các từ về thú vật, côn trùng"},
	{"id": "nature", "name": "Thiên nhiên", "description": "Từ về phong cảnh, thiên nhiên"},
	{"id": "education", "name": "Giáo dục", "description": "Từ liên quan đến học tập, trường lớp"},
	{"id": "technology", "name": "Công nghệ", "description": "Từ về công nghệ, thiết bị"},
	{"id": "sports", "name": "Thể thao", "description": "Từ về các môn thể thao, vận động"},
	{"id": "family", "name": "Gia đình", "description": "Từ về gia đình, quan hệ thân thuộc"},
]

DEFAULT_GAME_THEME_IDS = {theme["id"] for theme in DEFAULT_GAME_THEMES}