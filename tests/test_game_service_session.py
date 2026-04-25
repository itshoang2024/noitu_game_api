import os
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEBUG", "true")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.routes import game as game_routes
from app.config import settings
import app.services.game_service as game_service_module


class _FakeDB:
    def __init__(self):
        self.games = {}
        self.moves = {}


def _build_db_stubs(fake_db):
    async def fake_get_game(db, session_id):
        return db.games.get(session_id)

    async def fake_create_game(db, session_id, theme_id=None):
        game = SimpleNamespace(
            id=session_id,
            start_time=datetime.utcnow(),
            theme_id=theme_id,
        )
        db.games[session_id] = game
        db.moves.setdefault(session_id, [])
        return game

    async def fake_get_game_moves(db, session_id):
        words = db.moves.get(session_id, [])
        return [SimpleNamespace(word_text=word, move_number=index + 1) for index, word in enumerate(words)]

    async def fake_is_word_used_in_game(db, game_id, word):
        return word.lower().strip() in {w.lower().strip() for w in db.moves.get(game_id, [])}

    async def fake_add_game_move(db, game_id, word, is_player):
        db.moves.setdefault(game_id, []).append(word.lower().strip())
        return SimpleNamespace(game_id=game_id, word_text=word.lower().strip(), is_player=is_player)

    return {
        "get_game": fake_get_game,
        "create_game": fake_create_game,
        "get_game_moves": fake_get_game_moves,
        "is_word_used_in_game": fake_is_word_used_in_game,
        "add_game_move": fake_add_game_move,
    }


def _build_fake_ai_service():
    class _FakeEvaluator:
        def __init__(self):
            self.common_words = {"học sinh"}
            self.dictionary = {"học sinh"}

        async def ensure_initialized(self):
            return True

        async def evaluate_word(self, word):
            return 0.9, "ok"

    class _FakeAIService:
        def __init__(self):
            self.word_evaluator = _FakeEvaluator()
            self.quality_scores = {}
            self.quality_tracker = SimpleNamespace(theme_words_cache={})

        async def get_theme_words(self, theme):
            return []

    return _FakeAIService()


@pytest.fixture
def isolated_game_service(monkeypatch):
    monkeypatch.setattr(
        game_service_module.AIService,
        "get_instance",
        classmethod(lambda cls: object()),
    )
    return game_service_module.GameService()


def _patch_db_layer(monkeypatch, fake_db):
    async def fake_get_async_db():
        yield fake_db

    monkeypatch.setattr(game_service_module, "get_async_db", fake_get_async_db)
    stubs = _build_db_stubs(fake_db)
    for name, func in stubs.items():
        monkeypatch.setattr(game_service_module.crud, name, func)


@pytest.mark.asyncio
async def test_register_word_preserves_supplied_session_on_memory_miss(monkeypatch, isolated_game_service):
    monkeypatch.setattr(settings, "USE_DATABASE", False)

    session_id = "client-session-id"
    assert session_id not in isolated_game_service.used_words

    registered = await isolated_game_service.register_word(session_id, "học sinh")

    assert registered is True
    assert set(isolated_game_service.used_words.keys()) == {session_id}
    assert isolated_game_service.used_words[session_id] == ["học sinh"]


@pytest.mark.asyncio
async def test_is_word_used_and_register_word_hydrate_state_from_db(monkeypatch, isolated_game_service):
    monkeypatch.setattr(settings, "USE_DATABASE", True)
    fake_db = _FakeDB()
    session_id = "restart-session"
    fake_db.games[session_id] = SimpleNamespace(id=session_id, start_time=datetime.utcnow())
    fake_db.moves[session_id] = ["học sinh"]
    _patch_db_layer(monkeypatch, fake_db)

    assert session_id not in isolated_game_service.used_words

    is_used = await isolated_game_service.is_word_used(session_id, "học sinh")
    assert is_used is True
    assert isolated_game_service.used_words[session_id] == ["học sinh"]

    duplicated = await isolated_game_service.register_word(session_id, "học sinh")
    assert duplicated is False

    registered = await isolated_game_service.register_word(session_id, "sinh viên")
    assert registered is True
    assert fake_db.moves[session_id] == ["học sinh", "sinh viên"]


@pytest.mark.asyncio
async def test_new_word_works_for_db_session_missing_from_memory(monkeypatch, isolated_game_service):
    monkeypatch.setattr(settings, "USE_DATABASE", True)
    fake_db = _FakeDB()
    session_id = "cross-worker-session"
    fake_db.games[session_id] = SimpleNamespace(id=session_id, start_time=datetime.utcnow())
    fake_db.moves[session_id] = []
    _patch_db_layer(monkeypatch, fake_db)

    ai_service = _build_fake_ai_service()
    response = await game_routes.get_starting_word(
        data={"session_id": session_id, "theme": "random"},
        ai_service=ai_service,
        game_service=isolated_game_service,
    )

    assert response.status == "success"
    assert response.answer == "học sinh"
    assert fake_db.moves[session_id] == ["học sinh"]
    assert isolated_game_service.used_words[session_id] == ["học sinh"]
