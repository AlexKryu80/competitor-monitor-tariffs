"""Анализ конкурентов моделью: текст, изображение, страница сайта.

Модель просим вернуть JSON строго заданной формы, ответ проверяется схемами pydantic:
оценки 0–10 приводятся к диапазону, отсутствующие поля получают значения по умолчанию.
"""
import base64
import io
import json
import logging
import time

from openai import OpenAI, OpenAIError
from PIL import Image, UnidentifiedImageError

from backend.config import settings
from backend.models.schemas import CompetitorAnalysis, ImageAnalysis, ParsedContent

logger = logging.getLogger("openai_service")

ALLOWED_IMAGE_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}
MAX_IMAGE_SIDE = 1600  # больше не нужно: дороже, а читаемость не растёт

NICHE = (
    "рынок услуг по финансовому сопровождению деятельности организаций, финансовому аудиту "
    "и экспертизе/формированию тарифов (тарифное регулирование, обоснование тарифов)"
)

TEXT_PROMPT = f"""Ты аналитик конкурентной разведки. Ниша клиента: {NICHE}.
Тебе дают текст конкурента (страница услуг, предложение, отчёт). Анализируй только то, что есть в тексте,
не выдумывай факты, цены и реквизиты. Если данных не хватает, так и пиши.
Верни ТОЛЬКО JSON такой формы:
{{
  "strengths": ["сильные стороны"],
  "weaknesses": ["слабые стороны"],
  "unique_offers": ["уникальные предложения"],
  "recommendations": ["что клиенту сделать в ответ"],
  "service_coverage": {{"financial_support": true/false, "audit": true/false, "tariff_expertise": true/false}},
  "pricing_transparency": 0-10,
  "tariff_expertise_depth": 0-10,
  "summary": "вывод в 2-3 предложения"
}}
pricing_transparency: насколько понятны цены, сроки и состав работ (0 — нет ничего, 10 — всё прозрачно).
tariff_expertise_depth: насколько глубоко показана экспертиза по тарифам: методы расчёта, регуляторы,
кейсы, судебная практика (0 — не упомянута, 10 — подтверждена конкретикой).
Ответ на русском языке."""

IMAGE_PROMPT = f"""Ты аналитик конкурентной разведки и веб-дизайна. Ниша клиента: {NICHE}.
Тебе дают скриншот лендинга, баннера или документа конкурента. Описывай только видимое.
Верни ТОЛЬКО JSON такой формы:
{{
  "description": "что изображено",
  "marketing_insights": ["маркетинговые инсайты: обещание, УТП, призыв к действию"],
  "design_score": 0-10,
  "trust_score": 0-10,
  "design_analysis": "оценка визуального стиля: типографика, цвет, композиция, читаемость",
  "recommendations": ["что взять на заметку и чем отстроиться"]
}}
design_score: визуальное качество и аккуратность (0 — небрежно, 10 — сильный современный стиль).
trust_score: сколько элементов доверия видно: реквизиты, лицензии и членство, кейсы, клиенты, отзывы, контакты.
Ответ на русском языке."""

PAGE_PROMPT = TEXT_PROMPT.replace(
    "Тебе дают текст конкурента (страница услуг, предложение, отчёт).",
    "Тебе дают данные страницы сайта конкурента: заголовок, H1, первый абзац и заголовки разделов.",
)


class AnalysisError(Exception):
    """Ошибка обращения к модели или разбора её ответа."""


def _extract_json(raw: str) -> dict:
    """Модель может обернуть JSON в блок кода — достаём сам объект."""
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise AnalysisError("Модель вернула ответ без JSON")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"Не удалось разобрать JSON модели: {exc}") from exc


def prepare_image(data: bytes) -> tuple[str, str]:
    """Проверяет, что это картинка допустимого формата, уменьшает до разумного размера.

    Возвращает (mime, base64). Бросает ValueError, если файл не картинка.
    """
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Файл не распознан как изображение") from exc
    fmt = (image.format or "").upper()
    if fmt not in ALLOWED_IMAGE_FORMATS:
        raise ValueError("Допустимы форматы PNG, JPEG, WEBP, GIF")
    if max(image.size) > MAX_IMAGE_SIDE:
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buffer = io.BytesIO()
        image = image.convert("RGB")
        image.save(buffer, format="JPEG", quality=85)
        return "image/jpeg", base64.b64encode(buffer.getvalue()).decode()
    return ALLOWED_IMAGE_FORMATS[fmt], base64.b64encode(data).decode()


class OpenAIService:
    def __init__(self, client: OpenAI | None = None):
        self._client = client

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            if not settings.openai_api_key:
                raise AnalysisError("Не задан ключ API: впишите его в файл окружения (см. .env.example)")
            self._client = OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                timeout=settings.openai_timeout,
            )
        return self._client

    def _ask(self, model: str, system: str, user_content, label: str) -> dict:
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=model,
                temperature=0.2,  # аналитика: нужна повторяемость, а не креатив
                max_tokens=1500,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )
        except OpenAIError as exc:
            logger.error("%s: ошибка API (%s): %s", label, type(exc).__name__, exc)
            raise AnalysisError(f"Ошибка обращения к модели: {type(exc).__name__}") from exc
        elapsed = time.perf_counter() - started
        usage = getattr(response, "usage", None)
        logger.info(
            "%s: модель %s, %.1f с, токены вход/выход: %s/%s",
            label, model, elapsed,
            getattr(usage, "prompt_tokens", "?"), getattr(usage, "completion_tokens", "?"),
        )
        return _extract_json(response.choices[0].message.content)

    def analyze_text(self, text: str) -> CompetitorAnalysis:
        data = self._ask(settings.openai_model, TEXT_PROMPT, text[: settings.max_text_chars], "analyze_text")
        return CompetitorAnalysis.model_validate(data)

    def analyze_image(self, mime: str, image_b64: str, note: str = "") -> ImageAnalysis:
        content = [
            {"type": "text", "text": note or "Проанализируй этот материал конкурента."},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
        ]
        data = self._ask(settings.openai_vision_model, IMAGE_PROMPT, content, "analyze_image")
        return ImageAnalysis.model_validate(data)

    def analyze_page(self, parsed: ParsedContent) -> CompetitorAnalysis:
        lines = [
            f"Адрес: {parsed.url}",
            f"Заголовок страницы: {parsed.title or '—'}",
            f"H1: {parsed.h1 or '—'}",
            f"Первый абзац: {parsed.first_paragraph or '—'}",
            "Заголовки разделов: " + ("; ".join(parsed.headings) if parsed.headings else "—"),
        ]
        data = self._ask(settings.openai_model, PAGE_PROMPT, "\n".join(lines), "analyze_page")
        return CompetitorAnalysis.model_validate(data)
