from typing import List, Tuple
from unicodedata import normalize


def validate_vietnamese_syllable(syllable: str) -> bool:
    """
    Verify if a string is likely a valid Vietnamese syllable.
    This is intentionally simple and permissive.
    """
    normalized = normalize("NFC", syllable.strip().lower())
    return bool(normalized) and normalized.isalpha()


def extract_syllables(text: str) -> List[str]:
    """Extract syllables from a text string."""
    return [syllable.strip() for syllable in text.split() if syllable.strip()]


def validate_word_structure(word: str) -> Tuple[bool, str]:
    """
    Validate if a word appears to have valid Vietnamese structure.
    Returns: (is_valid, reason)
    """
    syllables = extract_syllables(word)
    if len(syllables) < 2:
        return False, "Từ phải có ít nhất 2 âm tiết"

    for syllable in syllables:
        if not validate_vietnamese_syllable(syllable):
            return False, f"Âm tiết '{syllable}' không có vẻ hợp lệ trong tiếng Việt"

    return True, "Từ có cấu trúc hợp lệ"


def validate_word_chain(word1: str, word2: str) -> Tuple[bool, str]:
    """
    Validate if word2 properly follows word1 according to the game rules.
    Returns: (is_valid, reason)
    """
    syllables1 = extract_syllables(word1)
    syllables2 = extract_syllables(word2)
    if not syllables1 or not syllables2:
        return False, "Cần cung cấp cả hai từ với đầy đủ âm tiết"

    last_syllable = syllables1[-1].lower()
    first_syllable = syllables2[0].lower()
    if last_syllable != first_syllable:
        return False, f"Âm tiết cuối '{last_syllable}' không khớp với âm tiết đầu '{first_syllable}'"

    return True, "Chuỗi từ hợp lệ"
