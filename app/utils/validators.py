import re
from typing import Tuple, List

def validate_vietnamese_syllable(syllable: str) -> bool:
    """
    Verify if a string is likely a valid Vietnamese syllable
    This is a simplified check and not 100% accurate for all Vietnamese syllables
    """
    # Chuẩn hóa đầu vào về dạng NFC
    from unicodedata import normalize
    normalized = normalize('NFC', syllable.lower().strip())
    
    # Mẫu đơn giản hơn, chỉ loại bỏ các ký tự đặc biệt
    return all(ord(c) < 128 or c in 'àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ' for c in normalized)

def extract_syllables(text: str) -> List[str]:
    """Extract syllables from a text string"""
    # In Vietnamese, syllables are separated by spaces
    return [s.strip() for s in text.split() if s.strip()]

def validate_word_structure(word: str) -> Tuple[bool, str]:
    """
    Validate if a word appears to have valid Vietnamese structure
    Returns: (is_valid, reason)
    """
    syllables = extract_syllables(word)
    
    # Check if word has at least 2 syllables
    if len(syllables) < 2:
        return False, "Từ phải có ít nhất 2 âm tiết"
    
    # Check each syllable
    for syllable in syllables:
        if not validate_vietnamese_syllable(syllable):
            return False, f"Âm tiết '{syllable}' không có vẻ hợp lệ trong tiếng Việt"
    
    return True, "Từ có cấu trúc hợp lệ"

def validate_word_chain(word1: str, word2: str) -> Tuple[bool, str]:
    """
    Validate if word2 properly follows word1 according to the game rules
    Returns: (is_valid, reason)
    """
    syllables1 = extract_syllables(word1)
    syllables2 = extract_syllables(word2)
    
    if not syllables1 or not syllables2:
        return False, "Cần cung cấp cả hai từ với đầy đủ âm tiết"
    
    # Check if last syllable of word1 matches first syllable of word2
    last_syllable = syllables1[-1].lower()
    first_syllable = syllables2[0].lower()
    
    if last_syllable != first_syllable:
        return False, f"Âm tiết cuối '{last_syllable}' không khớp với âm tiết đầu '{first_syllable}'"
    
    return True, "Chuỗi từ hợp lệ"