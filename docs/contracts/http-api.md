# HTTP API Contract

## Purpose
Specifies the interface guarantees, input shapes, output shapes, and failure modes for clients integrating with the Noitu Game API.
*(For system boundaries and artifact flow, see the [Architecture Overview](../architecture.md)).*

## Core Workflows
Most endpoints expect `application/json` bodies. 

### Game Loop Workflow
1. Client starts session: `GET /game/start` -> returns `session_id`
2. Client requests starting word (optional): `POST /game/new_word` 
3. Client plays word: `POST /ask`

## Interface Definitions

### `POST /ask`
**Purpose**: Submit a player's choice and receive the AI's counter-word.
**Upstream Inputs**:
```json
{
  "prompt": "trường học",
  "session_id": "uuid-v4-string"
}
```
**Downstream Outputs**:
```json
{
  "answer": "học sinh",
  "status": "success",  // Enum: success, error, unfound
  "model": "gemini-3.1-flash-lite-preview",
  "metadata": {
    "quality_score": "0.95"
  }
}
```
**Failure modes**:
- HTTP 400: `detail: "Vui lòng nhập một từ để nối."` (Empty string)
- HTTP 400: `detail: "Từ này đã được sử dụng..."` (Duplicate submission)
- Output `status: "unfound"`: AI could not find a valid linking word after `MAX_RETRIES`.

### `POST /game/new_word`
**Purpose**: Acquire a game starting word optionally constrained by a theme.
**Upstream Inputs**:
```json
{
  "session_id": "uuid-v4",
  "theme": "random" // "food", "animals", "nature", etc.
}
```
**Downstream Outputs**: `WordResponse` (schema matches `/ask`)

### `POST /word/check_meaning`
**Purpose**: Validate a word's physical structure, Vietnamese semantics, and existence in dictionary. Has side effects: forces evaluation against Gemini and saves to `dictionary` if valid.
**Upstream Inputs**: `{"word": "bàn ghế"}`
**Downstream Outputs**:
```json
{
  "word": "bàn ghế",
  "structure_valid": true,
  "structure_reason": "...",
  "in_dictionary": true,
  "has_meaning": true,
  "meaning_reason": "...",
  "quality_score": 0.8,
  "quality_reason": "...",
  "final_result": true,
  "final_reason": "..."
}
```

### `POST /npc/npc_intro`
**Purpose**: Generate a dynamic 1-2 sentence immersive text line for an NPC participating in a festival, based on a provided background. AI-generated, no game-mechanic rules enforced.
**Upstream Inputs**:
```json
{
  "npc_background": "Một ông lão bán bánh mì ở góc phố"
}
```
**Downstream Outputs**:
```json
{
  "reply": "Trời hôm nay đông người quá, bánh mì bán chạy dã man. Mấy đứa nhỏ cứ nhao náo cả lên.",
  "status": "success"
}
```

### `GET /database/stats`
**Purpose**: Retrieve high-level system telemetry (total games, total words, theme counts, move counts).
**Downstream Outputs**:
```json
{
  "words_count": 1500,
  "common_words_count": 500,
  "theme_count": 5,
  "game_count": 25,
  "move_count": 150
}
```

### `GET /database/game/{game_id}/moves`
**Purpose**: Retrieve chronological move history for a specific game session.
**Downstream Outputs**: Array of move objects including `move_number`, `word`, `is_player`, `quality_score`, and `created_at`.

## Failure Modes & HTTP Status Codes
- **400 Bad Request**: Malformed JSON, missing fields, violating game constraints (using utilized words or invalid chain structures).
- **429 Too Many Requests**: Triggered by `RateLimitingMiddleware` (>60 req/min/IP).
- **500 Internal Server Error**: Gemini API timeout, invalid model responses, or unhandled SQLite threading violations.
- **503 Service Unavailable**: Fired if `/ask` is called while the `AIService` warmup is incomplete (`is_ready == False`).

## Backward Compatibility Risks
- Schema shapes occasionally nest data into `.metadata` instead of root-level nodes. Clients must not hard-fail if new keys appear.
- Relying on `status: "success"` is critical; an HTTP 200 may still return a failed game state (`status: "unfound"`).

## Validation Checklist
When adding or modifying API routes:
- [ ] Must map input request to a Pydantic schema in `app/models/schemas.py`.
- [ ] Must return a Pydantic schema.
- [ ] Do not expose raw exception tracebacks in 500 errors to avoid leaking internal file paths.
- [ ] Update `tests/test_word_quality.py` if word parsing behavior is affected.