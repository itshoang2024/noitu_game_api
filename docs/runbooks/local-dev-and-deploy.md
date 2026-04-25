# Deployment Runbook: Local, Docker, and Production

## Purpose
Operational steps for setting up, running, monitoring, and deploying the Noitu Game API. Includes expected outputs and troubleshooting cues.

## Prerequisites
- **Git**
- **Docker** and **Docker Compose**
- **Python 3.10+** (if running locally without Docker)
- Valid **Gemini API Key** from Google Generative AI.

---

## 1. Local Development (No Docker)

### Setup Steps
1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Prepare environment variables:
   ```bash
   cp .env.example .env
   # Edit .env and set GEMINI_API_KEY=...
   ```
3. Initialize the database and dictionary data:
   ```bash
   alembic upgrade head
   python -m scripts.create_dictionary
   ```

### Execution
```bash
python main.py
```
**Expected Output**:
- Log stating `Uvicorn running on http://0.0.0.0:8800`
- Logs displaying the AI warmup progress (e.g. `Warm-up progress: 10.0%`).
- Note: The API routes that depend on AI will return 503 until warmup completes.

---

## 2. Docker Compose (Development)

Runs Uvicorn natively wrapping the code via host-volumes for live-reloading.

### Execution
```bash
docker-compose up --build
```
**What happens under the hood**:
- Reads from `docker-compose.yml` and `Dockerfile`.
- The `Dockerfile` injects `scripts/init_database.sh` which automatically runs Alembic migrations and dictionary seeding if `data/noitu_game.db` is empty.
- Maps your local `./data` folder to persist game sessions.

### Rollback/Reset
```bash
docker-compose down -v  # Destroys containers and custom volumes
rm -rf data/noitu_game.db
```

---

## 3. Production Deployment

Runs optimized `gunicorn` with Uvicorn workers underneath. Disables hot-reloading.

### Execution
1. Create a specific production `.env`:
   ```bash
   cp .env.example .env.prod
   # Edit .env.prod -> Set DEBUG=False, GEMINI_API_KEY=...
   ```
2. Start production daemon:
   ```bash
   docker-compose -f docker-compose.prod.yml up --build -d
   ```

**Important considerations for production**:
- **Multiproc Warning**: `Dockerfile.prod` spins up 4 workers (`--workers 4`). Game state tracking in memory will fragment. SQLite acts as the actual source of truth.
- **Port mapping**: Ensure the host server proxies port 8800 appropriately through Nginx/Caddy if serving over HTTPS.
- **Healthcheck**: Docker compose continuously polls `http://localhost:8800/system/status`.

---

## Troubleshooting

### "Error: GEMINI_API_KEY is not set"
- You forgot to copy `.env.example` to `.env` or didn't supply it to docker.
- Fix: Add the key and force-recreate the container.

### "database is locked" (SQLite)
- A known limitation. Under heavy load, multiple workers attempting to insert new dictionary words or AI metrics simultaneously into SQLite may block.
- Remediation: No immediate fix without tuning the SQLite engine to WAL mode (Write-Ahead Logging) or switching to PostgreSQL. 

### API Returns 503 "Model đang khởi tạo"
- `ENABLE_WARM_UP=True` is on, and the asynchronous model initialization hasn't finished hitting the Gemini endpoint yet.
- Fix: Wait ~30-60 seconds for the initial dictionary words to process, or set `ENABLE_WARM_UP=False` in your `.env`.

### Alembic Migration Integrity Errors
- If `scripts.create_dictionary` runs before Alembic structures are ready, or if DB states desync:
  - Delete `data/noitu_game.db` completely.
  - Restart the application. Custom script `init_database.sh` performs initialization cleanly.