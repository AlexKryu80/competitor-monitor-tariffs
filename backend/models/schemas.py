"""Схемы запросов и ответов API."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field


def _score(value) -> int:
    """Оценка 0–10: модель иногда отдаёт 11, -1 или строку — приводим к допустимому диапазону."""
    try:
        number = round(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, min(10, number))


Score = Annotated[int, BeforeValidator(_score)]


def _str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


StrList = Annotated[list[str], BeforeValidator(_str_list)]


# === Запросы ===

class TextAnalysisRequest(BaseModel):
    text: str = Field(..., min_length=10, description="Текст конкурента: описание услуг, предложение, отчёт")


class ParseRequest(BaseModel):
    url: str = Field(..., description="Адрес страницы конкурента (http/https)")


# === Ответы модели ===

class ServiceCoverage(BaseModel):
    """Какие направления ниши конкурент реально предлагает."""
    financial_support: bool = False   # финансовое сопровождение деятельности
    audit: bool = False               # финансовый аудит
    tariff_expertise: bool = False    # экспертиза, расчёт и обоснование тарифов


class CompetitorAnalysis(BaseModel):
    strengths: StrList = []
    weaknesses: StrList = []
    unique_offers: StrList = []
    recommendations: StrList = []
    service_coverage: ServiceCoverage = ServiceCoverage()
    pricing_transparency: Score = 0       # 0–10: насколько понятны цены и состав работ
    tariff_expertise_depth: Score = 0     # 0–10: глубина экспертизы по тарифам (вместо animation_potential)
    summary: str = ""


class ImageAnalysis(BaseModel):
    description: str = ""
    marketing_insights: StrList = []
    design_score: Score = 0               # 0–10: визуальный стиль
    trust_score: Score = 0                # 0–10: доверие (реквизиты, кейсы, лицензии, отзывы)
    design_analysis: str = ""
    recommendations: StrList = []


class ParsedContent(BaseModel):
    url: str
    title: str | None = None
    h1: str | None = None
    first_paragraph: str | None = None
    headings: list[str] = []              # заголовки h2: структура услуг на странице


class PageAnalysis(BaseModel):
    parsed: ParsedContent
    analysis: CompetitorAnalysis
    visual: ImageAnalysis | None = None   # анализ скриншота, если он получен


# === История ===

class HistoryItem(BaseModel):
    id: str
    timestamp: datetime
    kind: Literal["text", "image", "parse"]
    input_preview: str
    result: dict
