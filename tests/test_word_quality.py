import pytest
import pytest_asyncio
import sys
import os
import uuid

# Thêm thư mục gốc vào path để import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.utils.word_evaluator import WordEvaluator
from app.services.ai_service import AIService
from app.config import settings

@pytest_asyncio.fixture
async def word_evaluator():
    evaluator = WordEvaluator.get_instance()
    await evaluator.initialize()
    return evaluator

@pytest_asyncio.fixture
async def ai_service():
    service = AIService.get_instance()
    await service.initialize()
    return service

@pytest.mark.asyncio
async def test_word_evaluation(word_evaluator):
    """Test word evaluation functionality"""
    # Test known good words
    good_words = ["học sinh", "nhà cửa", "bàn ghế", "trường học"]
    for word in good_words:
        score, reason = await word_evaluator.evaluate_word(word)
        assert score >= 0.6, f"Expected high score for '{word}', got {score}"
    
    # Test known bad words
    bad_words = ["abcxyz", "hfdshjkfd", "qwertyuiop"]
    for word in bad_words:
        score, reason = await word_evaluator.evaluate_word(word)
        assert score <= 0.5, f"Expected low score for '{word}', got {score}"

@pytest.mark.asyncio
async def test_high_quality_generation(ai_service, monkeypatch):
    """Test high-quality word generation"""
    test_words = ["trường học", "bàn ghế", "nhà cửa"]

    mocked_replies = {
        "trường học": "học sinh",
        "bàn ghế": "ghế đẩu",
        "nhà cửa": "cửa sổ",
    }

    async def mock_generate_response(user_input: str, **kwargs):
        return mocked_replies.get(user_input, "Lỗi: Không có dữ liệu test")

    async def mock_add_metric(*args, **kwargs):
        return None

    monkeypatch.setattr(ai_service, "generate_response", mock_generate_response)
    monkeypatch.setattr(ai_service.quality_tracker, "add_metric", mock_add_metric)
    monkeypatch.setattr(settings, "USE_DATABASE", False)
    
    for word in test_words:
        response, score = await ai_service.generate_high_quality_response(word, max_attempts=3)
        
        # Verify response is not an error
        assert not response.startswith("Lỗi:"), f"Error response: {response}"
        
        # Verify quality score is acceptable
        assert score >= 0.5, f"Quality score too low: {score} for '{response}'"
        
        # Verify the word follows game rules
        last_syllable = word.split()[-1]
        first_response_syllable = response.split()[0]
        assert last_syllable == first_response_syllable, f"Word '{response}' doesn't follow game rules for input '{word}'"

@pytest.mark.asyncio
async def test_dictionary_functions(word_evaluator):
    """Test dictionary operations"""
    # Test adding a new word
    new_word = f"tu moi test {uuid.uuid4().hex[:8]}"
    result = await word_evaluator.add_to_dictionary(new_word)
    assert result, f"Failed to add '{new_word}' to dictionary"
    
    # Verify word was added
    assert word_evaluator.is_in_dictionary(new_word), f"Word '{new_word}' not found in dictionary"

if __name__ == "__main__":
    pytest.main(["-xvs", __file__])