# Документация API

Базовый адрес: `http://127.0.0.1:8000`. Все ответы: JSON. Ошибки: `{"detail": "текст"}`.

| Код | Когда |
|---|---|
| 413 | изображение больше 8 МБ |
| 415 | файл не изображение или неподдерживаемый формат |
| 422 | неверный запрос или страница не открылась (`/parse_demo`) |
| 502 | ошибка модели: нет ключа, сбой сети, ответ без JSON |

## GET /health

```json
{"status": "ok", "api_key_set": true, "model": "gpt-4o-mini"}
```

Значение ключа никогда не возвращается, только факт, что он задан.

## GET /competitors

Список из `backend/config.py`: `[{"name", "focus", "url"}]`.

## POST /analyze_text

```bash
curl -X POST http://127.0.0.1:8000/analyze_text \
  -H "Content-Type: application/json" \
  -d '{"text": "Готовим тарифные заявки для теплоснабжающих организаций, сопровождаем до утверждения тарифа."}'
```

Ответ:

```json
{
  "strengths": ["..."], "weaknesses": ["..."], "unique_offers": ["..."], "recommendations": ["..."],
  "service_coverage": {"financial_support": false, "audit": false, "tariff_expertise": true},
  "pricing_transparency": 3,
  "tariff_expertise_depth": 8,
  "summary": "..."
}
```

## POST /analyze_image

`multipart/form-data`, поле `file` (PNG, JPEG, WEBP, GIF, до 8 МБ).

```bash
curl -X POST http://127.0.0.1:8000/analyze_image -F "file=@data/energo-tarif-ru.jpg"
```

Ответ:

```json
{
  "description": "...", "marketing_insights": ["..."],
  "design_score": 7, "trust_score": 4,
  "design_analysis": "...", "recommendations": ["..."]
}
```

## POST /parse_demo

```bash
curl -X POST http://127.0.0.1:8000/parse_demo \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/uslugi"}'
```

Открывает страницу в Chrome (Selenium), собирает данные, анализирует текст и скриншот. Занимает 20–60 секунд. Результат сохраняется в историю.

```json
{
  "parsed": {"url": "...", "title": "...", "h1": "...", "first_paragraph": "...", "headings": ["..."]},
  "analysis": { "...поля как в /analyze_text..." },
  "visual": { "...поля как в /analyze_image...; null, если скриншот проанализировать не удалось" }
}
```

## GET /history, DELETE /history

`GET` возвращает последние 10 записей, новые сверху:

```json
[{"id": "a1b2c3d4e5f6", "timestamp": "2026-10-06T11:20:00Z", "kind": "parse",
  "input_preview": "https://example.com/uslugi", "result": { "...": "..." }}]
```

`kind`: `text`, `image` или `parse`. `DELETE` очищает историю: `{"status": "cleared"}`.

## Мультимодальность

Один и тот же анализ работает с текстом и с картинкой. Для сайтов оба канала объединены: текст страницы идёт в текстовый анализ, скриншот первого экрана в анализ изображения (модель с поддержкой изображений). Если скриншот проанализировать не удалось, ответ всё равно содержит разбор текста, а поле `visual` равно `null`.

## Как устроены промпты

Модель получает роль аналитика ниши, строго заданную форму JSON и правило не выдумывать факты. Температура 0.2: нужна повторяемость, а не креатив. Ответ проверяется схемами `pydantic` (`backend/models/schemas.py`).
