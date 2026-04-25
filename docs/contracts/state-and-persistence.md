# State & Persistence Contract

## Purpose
Defines the ownership, lifecycle, and limits of data stored via in-memory caches and SQLite. Describes the syncing responsibilities between `GameService`, `AIService`, and the SQLAlchemy ORM tier.

## Upstream Inputs & Responsibilities
- **`GameService`** (`app/services/game_service.py`): Primary orchestrator for Session interactions (`create_session`, `register_word`).
- **Memory Maps**:
  - `self.used_words[session_id] -> List[str]`
  - `self.game_stats[session_id] -> Dict`
- **Database Tables (`app/database/models.py`)**: `Game`, `GameMove`, `Word`, `Theme`, `ThemeWord`, `AIMetric`.

## Processing & Sync Protocol
1. **Session Injection**: All DB-connected routers rely on `app/api/dependencies.py` -> `get_db()` yielding a SQLAlchemy `AsyncSession` bounding transaction lifecycle to the HTTP request.
2. **Creation**: When a game starts, a UUID is created and written synchronously to the database via `crud.create_game()`, and memory maps are initialized.
3. **Move Registration**: When a word is played:
   - Validated against memory `used_words` first (fast-path).
   - Double-checked against database via `crud.is_word_used_in_game`.
   - Written to the `game_moves` table.
   - Pushed into the memory `used_words` cache.
4. **Dictionary Growth**: When `AIService` generates or validates a novel word not in memory, it is pushed to `WordEvaluator` which writes it to the `words` table and appends to the memory `set()`. AI stats are logged via background tasks to `ai_metrics`.

## Failure Modes & Compatibility Risks
- **Split-Brain Gunicorn Workers (Critical Risk)**:
  - The production runbook defines Gunicorn with `4` workers.
  - Because `GameService` is implemented as an application-level singleton mapping `session_id` to memory arrays, Worker 1's `used_words` array is decoupled from Worker 2.
  - **Risk**: Player submits a word to Worker 1, it passes. Play submits duplicate word to Worker 2. Worker 2's memory cache misses. It queries the DB and catches the duplicate. While technically safe due to DB fallback, the memory cache hit-rates become completely unstable across multi-process deployments.
- **SQLite Concurrency Limits**:
  - Utilizing `aiosqlite` with SQLAlchemy `AsyncSession` means long-running transactions or simultaneous multi-worker writes to `game_moves` or `words` tables could issue `database is locked` exceptions if WAL mode isn't aggressively optimized.
- **OOM (Out Of Memory)**:
  - Cache size is unbounded. `WordEvaluator` loads the entire dictionary into RAM. `GameService` holds all active sessions. 
  - Sessions must rely on `cleanup_old_sessions` background tasks to prune RAM.

## Naming and Schema Conventions
- Game sessions use `UUID4` strings (`id`).
- Word texts are stored entirely in lowercase and stripped of peripheral whitespace (`word.lower().strip()`).
- Time data is always stored in `datetime.utcnow()`.

## Validation Checklist
After modifying `GameService`, `AIService`, or ORM models:
- [ ] Did you generate a new alembic migration? (`alembic revision --autogenerate -m "..."`)
- [ ] If altering state validation, did you test across a multi-worker pool?
- [ ] Are memory arrays manually cleaned up, or do they leak memory?
- [ ] Are background tasks handled cleanly to prevent blocking the HTTP event loop?