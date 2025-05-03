import os

# Calculate base directory once
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Data directory
DATA_DIR = os.path.join(BASE_DIR, "data")

# Dictionary file paths
DICTIONARY_PATH = os.path.join(DATA_DIR, "vietnamese_dictionary.txt")
COMMON_WORDS_PATH = os.path.join(DATA_DIR, "common_words.txt")
QUALITY_METRICS_PATH = os.path.join(DATA_DIR, "quality_metrics.json")

# System settings
MAX_CONCURRENT_REQUESTS = 10
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 3