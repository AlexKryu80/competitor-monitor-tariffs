"""Сбор материалов конкурентов и массовый прогон анализа.

  python collect.py collect   # Selenium: скриншот и текст каждой страницы из config.py -> data/
  python collect.py analyze   # (сервер запущен) прогон /analyze_text, /analyze_image, /parse_demo -> results/
"""
import base64
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

from backend.config import BASE_DIR, COMPETITORS
from backend.services.parsing_service import ParsingError, parse_page

DATA = BASE_DIR / "data"
RESULTS = BASE_DIR / "results"
API = "http://127.0.0.1:8000"


def slug(competitor: dict) -> str:
    return urlparse(competitor["url"]).hostname.replace("www.", "").replace(".", "-")


def collect() -> None:
    DATA.mkdir(exist_ok=True)
    for competitor in COMPETITORS:
        name = slug(competitor)
        try:
            parsed, screenshot = parse_page(competitor["url"])
        except ParsingError as exc:
            print(f"[пропуск] {competitor['name']}: {exc}")
            continue
        if screenshot:
            (DATA / f"{name}.jpg").write_bytes(base64.b64decode(screenshot))
        text = "\n".join([
            f"Компания: {competitor['name']} ({competitor['focus']})",
            f"Адрес: {parsed.url}",
            f"Заголовок: {parsed.title or '—'}",
            f"H1: {parsed.h1 or '—'}",
            f"Первый абзац: {parsed.first_paragraph or '—'}",
            "Разделы: " + ("; ".join(parsed.headings) or "—"),
        ])
        (DATA / f"{name}.txt").write_text(text, encoding="utf-8")
        print(f"[ок] {competitor['name']}: data/{name}.jpg, data/{name}.txt")


def analyze() -> None:
    RESULTS.mkdir(exist_ok=True)
    rows = []
    with httpx.Client(base_url=API, timeout=240) as client:
        for competitor in COMPETITORS:
            name = slug(competitor)
            row = {"name": competitor["name"], "text": None, "image": None, "page": None}
            txt, jpg = DATA / f"{name}.txt", DATA / f"{name}.jpg"
            if txt.exists():
                row["text"] = _call(client.post("/analyze_text", json={"text": txt.read_text(encoding="utf-8")}))
            if jpg.exists():
                row["image"] = _call(client.post("/analyze_image", files={"file": (jpg.name, jpg.read_bytes(), "image/jpeg")}))
            row["page"] = _call(client.post("/parse_demo", json={"url": competitor["url"]}))
            (RESULTS / f"{name}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
            rows.append(row)
            print(f"[ок] {competitor['name']}")
    (RESULTS / "summary.md").write_text(_summary(rows), encoding="utf-8")
    print("Сводка: results/summary.md")


def _call(response: httpx.Response):
    return response.json() if response.status_code == 200 else {"error": response.status_code, "detail": response.text[:200]}


def _summary(rows: list[dict]) -> str:
    lines = ["| Конкурент | Дизайн | Доверие | Прозрачность цен | Глубина по тарифам | Аудит | Тарифы |",
             "|---|---|---|---|---|---|---|"]
    for row in rows:
        page = row["page"] or {}
        analysis = page.get("analysis") or {}
        visual = page.get("visual") or row["image"] or {}
        coverage = analysis.get("service_coverage") or {}
        lines.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            row["name"], visual.get("design_score", "—"), visual.get("trust_score", "—"),
            analysis.get("pricing_transparency", "—"), analysis.get("tariff_expertise_depth", "—"),
            "да" if coverage.get("audit") else "нет", "да" if coverage.get("tariff_expertise") else "нет"))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "collect":
        collect()
    elif command == "analyze":
        analyze()
    else:
        print(__doc__)
