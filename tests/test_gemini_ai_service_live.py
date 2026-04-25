"""Live smoke test for the Gemini-backed AIService.

Run this script manually when you want to verify the real Gemini integration:

    python scripts/test_gemini_ai_service_live.py

It requires GEMINI_API_KEY to be set in the environment or in .env.
The script disables database metric writes so the check stays focused on AIService
and does not mutate the canonical SQLite artifact.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

from app.config import settings
from app.services.ai_service import AIService


DEFAULT_CONNECTION_WORD = "tr\u01b0\u1eddng h\u1ecdc"
DEFAULT_GAME_WORD = "b\u00e0n gh\u1ebf"
ERROR_PREFIXES = ("l\u1ed7i:", "l\u00e1\u00bb", "loi:")


class LiveSmokeTestError(AssertionError):
    """Raised when a required live smoke check fails."""


def is_error_response(text: str | None) -> bool:
    if not text:
        return True
    normalized = text.strip().lower()
    return normalized.startswith(ERROR_PREFIXES)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise LiveSmokeTestError(message)


def print_ok(name: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    print(f"[PASS] {name}{suffix}")


async def run_check(name: str, check: Callable[[], Awaitable[str] | str]) -> None:
    result = check()
    detail = await result if hasattr(result, "__await__") else result
    print_ok(name, detail)


def validate_api_key() -> None:
    api_key = settings.GEMINI_API_KEY.strip()
    require(api_key, "GEMINI_API_KEY is not set. Add it to .env or the environment.")
    require(
        api_key != "your_gemini_api_key_here",
        "GEMINI_API_KEY is still the placeholder value.",
    )


def patch_metric_writer(service: AIService) -> None:
    async def add_metric_in_memory(
        word: str,
        score: float,
        user_input: str | None = None,
        session_id: str | None = None,
    ) -> None:
        service.quality_tracker.metrics.append(
            {
                "timestamp": datetime.now().isoformat(),
                "word": word,
                "score": score,
                "user_input": user_input,
                "session_id": session_id,
            }
        )

    service.quality_tracker.add_metric = add_metric_in_memory


def first_syllable(text: str) -> str:
    return text.strip().lower().split()[0]


def last_syllable(text: str) -> str:
    return text.strip().lower().split()[-1]


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the real Gemini connection and core AIService behavior."
    )
    parser.add_argument(
        "--connection-word",
        default=DEFAULT_CONNECTION_WORD,
        help="Seed word used for the direct Gemini call.",
    )
    parser.add_argument(
        "--game-word",
        default=DEFAULT_GAME_WORD,
        help="Seed word used for generate_high_quality_response.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum attempts for high-quality generation.",
    )
    parser.add_argument(
        "--quality-threshold",
        type=float,
        default=0.4,
        help="Minimum acceptable quality score for the high-quality response.",
    )
    args = parser.parse_args()

    try:
        validate_api_key()

        settings.USE_DATABASE = False
        service = AIService.get_instance()

        await run_check(
            "Initialize AIService",
            lambda: _initialize_service(service),
        )

        patch_metric_writer(service)
        service.reset_cache()

        direct_response = await _check_direct_generation(service, args.connection_word)
        cached_response = await _check_cache(service, args.connection_word)
        require(
            cached_response == direct_response,
            "Cache check failed: cached response does not match the direct response.",
        )
        print_ok("Cache hit", f"{args.connection_word!r} -> {cached_response!r}")

        await run_check(
            "Evaluate generated word",
            lambda: _check_word_evaluation(service, direct_response),
        )

        await run_check(
            "Generate high-quality response",
            lambda: _check_high_quality_generation(
                service=service,
                seed_word=args.game_word,
                max_attempts=args.max_attempts,
                quality_threshold=args.quality_threshold,
            ),
        )

        await run_check(
            "Performance metrics",
            lambda: _check_performance_metrics(service),
        )

    except LiveSmokeTestError as exc:
        print(f"[FAIL] {exc}")
        return 1
    finally:
        instance = AIService.get_instance()
        await instance.close()

    print("[DONE] Gemini live smoke test completed successfully.")
    return 0


async def _initialize_service(service: AIService) -> str:
    await service.initialize()
    require(service.word_evaluator.is_initialized, "WordEvaluator was not initialized.")
    return f"model={settings.MODEL_ID}"


async def _check_direct_generation(service: AIService, seed_word: str) -> str:
    response = await service.generate_response(
        seed_word,
        use_cache=False,
        max_retries=1,
        quality_threshold=0.0,
        skip_quality_check=True,
    )
    require(not is_error_response(response), f"Gemini returned an error: {response}")
    require(response.strip(), "Gemini returned an empty response.")
    print_ok("Direct Gemini generation", f"{seed_word!r} -> {response!r}")
    return response


async def _check_cache(service: AIService, seed_word: str) -> str:
    response = await service.generate_response(
        seed_word,
        use_cache=True,
        max_retries=0,
        skip_quality_check=True,
    )
    require(not is_error_response(response), f"Cache returned an error: {response}")
    return response


async def _check_word_evaluation(service: AIService, word: str) -> str:
    score, reason = await service.word_evaluator.evaluate_word(word)
    require(score >= 0.1, f"Generated word scored too low: {score:.2f} ({reason})")
    return f"{word!r} score={score:.2f}"


async def _check_high_quality_generation(
    service: AIService,
    seed_word: str,
    max_attempts: int,
    quality_threshold: float,
) -> str:
    response, score = await service.generate_high_quality_response(
        seed_word,
        max_attempts=max_attempts,
        quality_threshold=quality_threshold,
    )

    require(not is_error_response(response), f"High-quality generation failed: {response}")
    require(
        score >= quality_threshold,
        f"Quality score {score:.2f} is below threshold {quality_threshold:.2f}. Response: {response}",
    )
    require(
        first_syllable(response) == last_syllable(seed_word),
        (
            "Word-chain rule failed: "
            f"input={seed_word!r}, response={response!r}, score={score:.2f}"
        ),
    )

    return f"{seed_word!r} -> {response!r}, score={score:.2f}"


async def _check_performance_metrics(service: AIService) -> str:
    metrics = service.get_performance_metrics()
    require(metrics["total_requests"] > 0, "AIService did not record any requests.")
    require(
        service.get_cached_words() > 0,
        "AIService cache is empty after generation checks.",
    )
    return (
        f"requests={metrics['total_requests']}, "
        f"success={metrics['successful_requests']}, "
        f"failed={metrics['failed_requests']}, "
        f"cache={metrics['cache_size']}"
    )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
