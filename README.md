<div align="center">

  # Noitu Game API (Nối Từ)
  ### Backend API for the Nối Từ mini-game in Folk Games Collection

  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Google%20Gemini-8E75B2?style=for-the-badge&logo=google-gemini&logoColor=white" />
  <img src="https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white" />
  <img src="https://img.shields.io/badge/SQLAlchemy-D71F00?style=for-the-badge&logo=sqlalchemy&logoColor=white" />
  <img src="https://img.shields.io/badge/Alembic-6BA539?style=for-the-badge&logo=alembic&logoColor=white" />
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" />
</div>

---

A FastAPI-based Vietnamese word-chain game engine backed by Google Gemini. This service manages game sessions, validates Vietnamese word structure, evaluates word quality, and tracks game telemetry in a SQLite database.

## Features
- **Google Gemini Integration**: Generates valid, semantic Vietnamese word-chain responses using Gemini models.
- **Game Collection Backend**: Serves the `NOI_CHU` mini-game in [Folk Games Collection](https://github.com/ntntran09/Tung-Bung-Ngay-Thong-Nhat) through HTTP endpoints.
- **Session Management**: Tracks active games and previously played words to enforce rules (e.g., no duplicates).
- **Word Validation**: Includes structural syllable checks and a pre-seeded SQLite/memory dictionary for immediate validation.
- **Telemetry & Scoring**: Evaluates the quality of player and AI inputs, storing metrics for analytics.

## Repository Structure
- `app/api/routes/`: HTTP endpoint definitions (`/ask`, `/game`, `/word`, etc.).
- `app/services/`: Core logic containing `AIService` (Gemini wrapper) and `GameService` (Session tracking).
- `app/utils/`: Word evaluation rules and text normalization.
- `app/database/`: SQLAlchemy ORM models, migration configuration, and CRUD operations.
- `scripts/`: Utilities for seeding the database (`create_dictionary.py`, `init_database.sh`).
- `docs/`: Detailed system architecture, interface contracts, and runbooks.

## Quick Start

### 1. Prerequisites
- Python 3.10+
- Google Gemini API Key
- Docker and Docker Compose (optional, for containerized run)

### 2. Environment Setup
```bash
cp .env.example .env
# Edit .env and set your GEMINI_API_KEY="..."
```

### 3. Run Locally (Native) & Docker Compose
For complete setup, deployment, and troubleshooting instructions, **refer to the canonical [Deployment Runbook](docs/runbooks/local-dev-and-deploy.md)**.

**Quick Start (Docker):**
```bash
docker-compose up --build
```
*Docker automatically orchestrates the Alembic migrations and dictionary seeding on startup. The server will start at `http://0.0.0.0:8800`. API documentation is available at `http://0.0.0.0:8800/docs`.*

## Documentation Directory
For deeper architectural details and operational workflows, refer to the following documents:
- [Architecture Overview](docs/architecture.md): Module boundaries, runtime constraints, and artifact flows.
- [Deployment Runbook](docs/runbooks/local-dev-and-deploy.md): Detailed operational steps for Docker, Production, and troubleshooting.
- [HTTP API Contract](docs/contracts/http-api.md): Endpoint definitions, input/output JSON schemas, and failure modes.
- [State & Persistence Contract](docs/contracts/state-and-persistence.md): Data lifecycle, caching risks, and database design.
