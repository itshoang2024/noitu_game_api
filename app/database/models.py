from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, UniqueConstraint, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
from .base import Base

class Word(Base):
    __tablename__ = "words"
    
    id = Column(Integer, primary_key=True, index=True)
    word = Column(String(100), unique=True, index=True, nullable=False)
    quality_score = Column(Float, default=0.5)
    is_common = Column(Boolean, default=False)
    syllable_count = Column(Integer)
    first_syllable = Column(String(50))
    last_syllable = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    theme_words = relationship("ThemeWord", back_populates="word")
    game_moves = relationship("GameMove", back_populates="word")

class Game(Base):
    __tablename__ = "games"
    
    id = Column(String(36), primary_key=True)  # UUID làm session_id
    theme_id = Column(Integer, ForeignKey("themes.id"), nullable=True)
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    status = Column(String(20), default="active")  # active, completed, abandoned
    duration_seconds = Column(Integer, nullable=True)
    word_count = Column(Integer, default=0)
    max_chain = Column(Integer, default=0)
    score = Column(Integer, default=0)
    
    # Relationships
    theme = relationship("Theme", back_populates="games")
    moves = relationship("GameMove", back_populates="game", cascade="all, delete-orphan")

class GameMove(Base):
    __tablename__ = "game_moves"
    
    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(String(36), ForeignKey("games.id"), nullable=False)
    word_id = Column(Integer, ForeignKey("words.id"), nullable=False)
    word_text = Column(String(100), nullable=False)  # Redundant data for performance
    move_number = Column(Integer, nullable=False)
    is_player = Column(Boolean, default=True)  # True if player, False if AI
    quality_score = Column(Float)
    response_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    game = relationship("Game", back_populates="moves")
    word = relationship("Word", back_populates="game_moves")
    
    __table_args__ = (
        UniqueConstraint('game_id', 'move_number', name='uix_game_move'),
    )

class Theme(Base):
    __tablename__ = "themes"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    theme_words = relationship("ThemeWord", back_populates="theme", cascade="all, delete-orphan")
    games = relationship("Game", back_populates="theme")

class ThemeWord(Base):
    __tablename__ = "theme_words"
    
    id = Column(Integer, primary_key=True, index=True)
    theme_id = Column(Integer, ForeignKey("themes.id"), nullable=False)
    word_id = Column(Integer, ForeignKey("words.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    theme = relationship("Theme", back_populates="theme_words")
    word = relationship("Word", back_populates="theme_words")
    
    __table_args__ = (
        UniqueConstraint('theme_id', 'word_id', name='uix_theme_word'),
    )

class AIMetric(Base):
    __tablename__ = "ai_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    request_word = Column(String(100), nullable=False)
    response_word = Column(String(100), nullable=False)
    response_time_ms = Column(Integer)
    quality_score = Column(Float)
    game_id = Column(String(36), ForeignKey("games.id"), nullable=True)
    success = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    game = relationship("Game")