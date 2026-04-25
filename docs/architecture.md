# Architecture: Noitu Game API

## System Purpose
A backend service defining core game loops for a Vietnamese word-chain (Nối Từ) experience. It processes player input, validates Vietnamese syllable structure and semantic definitions, queries Google Gemini for valid chain responses, scores result quality, and manages active game sessions.

## Module Boundaries
- **API Runtime (`app/api/`)**: Translates HTTP JSON payloads into typed Pydantic objects, enforces rate limits, handles CORS, and exposes grouped route modules (`core`, `game`, `system`, `dictionary`, `word`, `database`, `npc`).
- **Game Engine & Orchestration (`app/services/`)**: 
  - `GameService` acts as a session manager linking player IDs to used-word registries.
  - `AIService` orchestrates the Gemini prompt chain, applies adaptive rate limiting, tracks response timing, and evaluates response semantic validity.
- **Rules evaluation (`app/utils/`)**: Pure stateless functions for Vietnamese character parsing and word composition logic. `WordEvaluator` provides heavy in-memory caching of the dictionary to allow zero-latency structural checks.
- **Persistence (`app/database/`)**: Maps domain objects (Word, Game, Session, Move, AIMetric) through SQLAlchemy into SQLite.

## Runtime Boundaries
1. **Startup Phase**:
   - `main.py` binds the `engine` to create tables.
   - `WordEvaluator` hydrates its internal sets (`dictionary`, `common_words`, `word_chains`) entirely into memory via `crud.get_all_common_words()`.
   - `AIService` performs an adaptive "warmup" prompting Gemini with seeded common Vietnamese words to build prompt context.
2. **Execution Phase**:
   - Web requests enter FastAPI endpoints.
   - Core state relies on Python singleton classes holding `Dict` properties.
   - **ASSUMPTION**: Current production deployment (`Dockerfile.prod`) defines `gunicorn --workers 4`. In-memory state tracking (`used_words`) across 4 processes will fracture game sessions uniquely per-worker unless the database acts as the single source of truth synchronously.

## Artifact Flow
1. Scripts → `scripts/create_dictionary.py` seeds initial Vietnamese pairs.
2. Migrations → `alembic upgrade head` asserts SQL schema.
3. Database → `data/noitu_game.db` persists session/word history.
4. AI Backend → Outbound HTTPS calls to `generativelanguage.googleapis.com` requesting `maxOutputTokens=50`.

```text
[HTTP Clients] ---> FastAPI ---> GameService (Memory/SQLite)
                          \
                           \---> AIService ---> Gemini API
                                        \
                                         \---> WordEvaluator (Memory Dictionary)
```

## Current Limitations
- **Multi-process In-memory State**: Singletons in `app.services` cannot share state (like `used_words` or `word_cache`) safely across multiple Gunicorn workers.
- **SQLite Concurrency**: High-throughput AI metric recording and session word-insertion can lock `aiosqlite` under load without WAL mode or a transition to PostgreSQL/Redis.
- **Dictionary Rigidity**: Checking word validity relies on pre-seeded records. Gemini fallback acts as the decider but increases request latency significantly.

## Change Impact Notes
- Modifying `app/config.py` thresholds (e.g. `WORD_QUALITY_THRESHOLD`) instantly changes the AI's aggressiveness in retrying requests and filtering common words.
- Modifying the prompt template in `SYSTEM_INSTRUCTION` directly shifts downstream schema reliability (the AI might start explaining words instead of returning single strings, breaking `extract_syllables()`).