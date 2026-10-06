"""Проверки API без сети и без ключа: модель и браузер подменены, логика бэкенда настоящая."""
import io
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import main
from backend.config import settings
from backend.models.schemas import ParsedContent
from backend.services import openai_service as svc
from backend.services.parsing_service import ParsingError, validate_url

TEXT_REPLY = {
    "strengths": ["Опыт в тарифных кампаниях"],
    "weaknesses": ["Нет цен на сайте"],
    "unique_offers": ["Сопровождение до утверждения тарифа"],
    "recommendations": ["Показать кейсы с суммами"],
    "service_coverage": {"financial_support": False, "audit": False, "tariff_expertise": True},
    "pricing_transparency": 3,
    "tariff_expertise_depth": 8,
    "summary": "Узкий специалист по тарифам.",
}
IMAGE_REPLY = {
    "description": "Лендинг с синей шапкой",
    "marketing_insights": ["Обещание: тариф без отказов"],
    "design_score": 7,
    "trust_score": 4,
    "design_analysis": "Аккуратно, но шаблонно",
    "recommendations": ["Добавить кейсы"],
}


class FakeClient:
    """Подмена OpenAI: отдаёт заготовленные ответы по очереди и запоминает запросы."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        content = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
        )


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "history_file", tmp_path / "history.json")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    def install(replies):
        client = FakeClient(replies)
        monkeypatch.setattr(main, "openai_service", svc.OpenAIService(client=client))
        return client

    return TestClient(main.app), install


def png_bytes(size=(40, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_health_does_not_expose_key(api):
    client, _ = api
    body = client.get("/health").json()
    assert body["api_key_set"] is True
    assert "test-key" not in json.dumps(body)


def test_analyze_text_ok_and_json_mode(api):
    client, install = api
    fake = install([TEXT_REPLY])
    response = client.post("/analyze_text", json={"text": "Мы готовим тарифные заявки для РСО."})
    assert response.status_code == 200
    body = response.json()
    assert body["tariff_expertise_depth"] == 8
    assert body["service_coverage"]["tariff_expertise"] is True
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


def test_scores_are_clamped_and_missing_fields_default(api):
    client, install = api
    install([{"pricing_transparency": 15, "tariff_expertise_depth": "7.6", "strengths": "одна строка"}])
    body = client.post("/analyze_text", json={"text": "Достаточно длинный текст конкурента"}).json()
    assert body["pricing_transparency"] == 10
    assert body["tariff_expertise_depth"] == 8
    assert body["strengths"] == ["одна строка"]
    assert body["weaknesses"] == []


def test_json_inside_code_fence_is_accepted(api):
    client, install = api
    install(["```json\n" + json.dumps(TEXT_REPLY) + "\n```"])
    assert client.post("/analyze_text", json={"text": "Достаточно длинный текст конкурента"}).status_code == 200


def test_reply_without_json_gives_502(api):
    client, install = api
    install(["Извините, не могу"])
    response = client.post("/analyze_text", json={"text": "Достаточно длинный текст конкурента"})
    assert response.status_code == 502


def test_short_text_rejected(api):
    client, _ = api
    assert client.post("/analyze_text", json={"text": "коротко"}).status_code == 422


def test_missing_api_key_gives_clear_502(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(main, "openai_service", svc.OpenAIService())
    response = client.post("/analyze_text", json={"text": "Достаточно длинный текст конкурента"})
    assert response.status_code == 502
    assert "ключ" in response.json()["detail"]


def test_analyze_image_ok(api):
    client, install = api
    fake = install([IMAGE_REPLY])
    response = client.post("/analyze_image", files={"file": ("banner.png", png_bytes(), "image/png")})
    assert response.status_code == 200
    assert response.json()["design_score"] == 7
    image_part = fake.calls[0]["messages"][1]["content"][1]
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_analyze_image_rejects_non_image_and_oversize(api, monkeypatch):
    client, install = api
    install([IMAGE_REPLY])
    assert client.post("/analyze_image", files={"file": ("a.txt", b"hello", "text/plain")}).status_code == 415
    monkeypatch.setattr(settings, "max_image_bytes", 100)
    assert client.post("/analyze_image", files={"file": ("big.png", png_bytes((300, 300)), "image/png")}).status_code == 413


def test_large_image_is_downscaled():
    mime, b64 = svc.prepare_image(png_bytes((3200, 2000)))
    image = Image.open(io.BytesIO(__import__("base64").b64decode(b64)))
    assert mime == "image/jpeg" and max(image.size) <= svc.MAX_IMAGE_SIDE


def test_parse_demo_with_screenshot(api, monkeypatch):
    client, install = api
    parsed = ParsedContent(url="https://example.com/", title="Тарифы", h1="Расчёт тарифов",
                           first_paragraph="Готовим тарифные заявки", headings=["Услуги", "Цены"])
    monkeypatch.setattr(main, "parse_page", lambda url: (parsed, "AAAA"))
    fake = install([TEXT_REPLY, IMAGE_REPLY])
    body = client.post("/parse_demo", json={"url": "https://example.com/"}).json()
    assert body["parsed"]["h1"] == "Расчёт тарифов"
    assert body["analysis"]["pricing_transparency"] == 3
    assert body["visual"]["design_score"] == 7
    assert "Услуги; Цены" in fake.calls[0]["messages"][1]["content"]
    assert client.get("/history").json()[0]["kind"] == "parse"


def test_parse_demo_survives_failed_screenshot_analysis(api, monkeypatch):
    client, install = api
    parsed = ParsedContent(url="https://example.com/", title="T")
    monkeypatch.setattr(main, "parse_page", lambda url: (parsed, "AAAA"))
    install([TEXT_REPLY, "не json"])
    body = client.post("/parse_demo", json={"url": "https://example.com/"}).json()
    assert body["visual"] is None and body["analysis"]["tariff_expertise_depth"] == 8


def test_parse_demo_unreachable_page_gives_422(api, monkeypatch):
    client, _ = api

    def fail(url):
        raise ParsingError("Страница не открылась")

    monkeypatch.setattr(main, "parse_page", fail)
    assert client.post("/parse_demo", json={"url": "https://example.com/"}).status_code == 422


@pytest.mark.parametrize("url", [
    "ftp://example.com/", "file:///c:/windows/win.ini", "http://127.0.0.1:8000/", "http://localhost/", "не адрес",
])
def test_validate_url_blocks_unsafe_addresses(url):
    with pytest.raises(ParsingError):
        validate_url(url)


def test_history_keeps_last_ten_newest_first(api):
    client, install = api
    install([TEXT_REPLY] * 12)
    for number in range(12):
        client.post("/analyze_text", json={"text": f"Текст конкурента номер {number:02d}"})
    items = client.get("/history").json()
    assert len(items) == 10
    assert items[0]["input_preview"].endswith("11") and items[-1]["input_preview"].endswith("02")
    assert client.delete("/history").json() == {"status": "cleared"}
    assert client.get("/history").json() == []


def test_competitors_listed_from_config(api):
    client, _ = api
    items = client.get("/competitors").json()
    assert 3 <= len(items) <= 5 and all(item["url"].startswith("https://") for item in items)


@pytest.mark.parametrize("address, internal", [
    ("31.31.201.73", False),
    ("64:ff9b::1f1f:c949", False),       # NAT64 от провайдера: внутри публичный 31.31.201.73
    ("64:ff9b::7f00:1", True),           # NAT64 с вложенным 127.0.0.1
    ("64:ff9b::c0a8:101", True),         # NAT64 с вложенным 192.168.1.1
    ("::ffff:10.0.0.5", True),
    ("10.0.0.5", True),
    ("169.254.169.254", True),
    ("::1", True),
])
def test_is_internal_handles_nat64(address, internal):
    from backend.services.parsing_service import _is_internal
    assert _is_internal(address) is internal
