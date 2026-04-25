from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

class WordRequest(BaseModel):
    prompt: str = Field(..., description="The word provided by the user")
    session_id: Optional[str] = Field(None, description="Game session identifier")
    theme: Optional[str] = Field(None, description="Theme for starting word (optional)")

class WordResponse(BaseModel):
    answer: str = Field(..., description="The AI's response word")
    status: str = Field(..., description="Status of the response (success or error)")
    model: Optional[str] = Field(None, description="Model ID used for generating response")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata about the response")

class StatusResponse(BaseModel):
    status: str = Field(..., description="Current status of the API (ready or initializing)")
    cached_words: int = Field(..., description="Number of words in cache")
    model: str = Field(..., description="Model ID being used")
    api_provider: str = Field(..., description="AI API provider")

class CacheResponse(BaseModel):
    cache: Dict[str, str] = Field(..., description="Current word cache content")

class ResetResponse(BaseModel):
    status: str = Field(..., description="Status message of cache reset operation")

class SessionResponse(BaseModel):
    session_id: str = Field(..., description="New session identifier")
    status: str = Field(..., description="Status of session creation")

class ValidationResponse(BaseModel):
    valid: bool = Field(..., description="Whether the word is valid")
    reason: str = Field(..., description="Reason for validation result")

class SuggestionResponse(BaseModel):
    suggestions: List[str] = Field(..., description="List of suggested words")

class ExplanationResponse(BaseModel):
    word: str = Field(..., description="The word that was explained")
    explanation: str = Field(..., description="Explanation of the word")

class NPCIntroRequest(BaseModel):
    npc_background: str

class NPCIntroResponse(BaseModel):
    reply: str
    status: str


class WordValidationRequest(BaseModel):
    word: str = Field(default="", description="Word to validate")


class WordMeaningRequest(BaseModel):
    word: str = Field(default="", description="Word to check for meaning")


class DictionaryWordRequest(BaseModel):
    word: str = Field(default="", description="Word to add into dictionary")


class ThemeWordsUpdateRequest(BaseModel):
    theme: str = Field(default="", description="Theme identifier")
    words: List[str] = Field(default_factory=list, description="Words for this theme")


class WordPairRequest(BaseModel):
    input_word: str = Field(default="", description="Input word from player")
    response_word: str = Field(default="", description="Response word to validate")


class StartingWordRequest(BaseModel):
    session_id: str = Field(default="", description="Game session identifier")
    theme: Optional[str] = Field(default="random", description="Requested theme")
