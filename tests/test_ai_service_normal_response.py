import os
import sys

import httpx
import pytest

os.environ.setdefault("DEBUG", "true")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app.services.ai_service as ai_service_module
from app.config import settings
from app.services.ai_service import AIService


class _FakeHTTPClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def post(self, url, json):
        self.requests.append((url, json))
        index = min(len(self.requests) - 1, len(self.responses) - 1)
        return self.responses[index]


def _gemini_response(status_code, payload):
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/test")
    return httpx.Response(status_code=status_code, json=payload, request=request)


def _high_demand_response():
    return _gemini_response(
        503,
        {
            "error": {
                "code": 503,
                "message": "This model is currently experiencing high demand.",
                "status": "UNAVAILABLE",
            }
        },
    )


def _request_models(fake_client):
    models = []
    for url, _ in fake_client.requests:
        models.append(url.split("/models/", 1)[1].split(":generateContent", 1)[0])
    return models


@pytest.mark.asyncio
async def test_generate_normal_response_uses_fallback_model_after_503(monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ID", "primary-model")
    monkeypatch.setattr(settings, "MODEL_POOL", ["primary-model", "fallback-model"])

    service = AIService()
    await service.http_client.aclose()

    success_response = _gemini_response(
        200,
        {
            "candidates": [
                {"content": {"parts": [{"text": "NPC reply after retry"}]}}
            ]
        },
    )
    fake_client = _FakeHTTPClient([_high_demand_response(), success_response])
    service.http_client = fake_client

    sleep_delays = []

    async def fake_sleep(delay):
        sleep_delays.append(delay)

    monkeypatch.setattr(ai_service_module.asyncio, "sleep", fake_sleep)

    reply = await service.generate_normal_response("npc prompt", max_retries=0)

    assert reply == "NPC reply after retry"
    assert _request_models(fake_client) == ["primary-model", "fallback-model"]
    assert len(fake_client.requests) == 2
    assert sleep_delays == []
    assert service.successful_requests == 1
    assert service.failed_requests == 0


@pytest.mark.asyncio
async def test_generate_normal_response_falls_back_after_http_retries(monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ID", "primary-model")
    monkeypatch.setattr(settings, "MODEL_POOL", ["primary-model"])

    service = AIService()
    await service.http_client.aclose()

    fake_client = _FakeHTTPClient([_high_demand_response(), _high_demand_response()])
    service.http_client = fake_client

    async def fake_sleep(delay):
        return None

    monkeypatch.setattr(ai_service_module.asyncio, "sleep", fake_sleep)

    reply = await service.generate_normal_response("npc prompt", max_retries=1)

    assert reply == service.NORMAL_RESPONSE_FALLBACK
    assert "Gemini" not in reply
    assert "HTTPStatusError" not in reply
    assert len(fake_client.requests) == 2
    assert _request_models(fake_client) == ["primary-model", "primary-model"]
    assert service.successful_requests == 0
    assert service.failed_requests == 1


@pytest.mark.asyncio
async def test_generate_response_uses_fallback_model_after_503(monkeypatch):
    monkeypatch.setattr(settings, "MODEL_ID", "primary-model")
    monkeypatch.setattr(settings, "MODEL_POOL", ["primary-model", "fallback-model"])

    service = AIService()
    await service.http_client.aclose()

    success_response = _gemini_response(
        200,
        {
            "candidates": [
                {"content": {"parts": [{"text": "fallback word"}]}}
            ]
        },
    )
    fake_client = _FakeHTTPClient([_high_demand_response(), success_response])
    service.http_client = fake_client

    reply = await service.generate_response(
        "seed word",
        use_cache=False,
        max_retries=0,
        skip_quality_check=True,
    )

    assert reply == "fallback word"
    assert _request_models(fake_client) == ["primary-model", "fallback-model"]
    assert service.successful_requests == 1
    assert service.failed_requests == 0


def main() -> int:
    return pytest.main([__file__])


if __name__ == "__main__":
    raise SystemExit(main())
