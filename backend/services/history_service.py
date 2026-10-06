"""История запросов: последние N записей в history.json."""
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

from backend.config import settings
from backend.models.schemas import HistoryItem

logger = logging.getLogger("history_service")
_lock = threading.Lock()


def _read() -> list[dict]:
    path = settings.history_file
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("history.json повреждён, начинаем заново: %s", exc)
        return []


def _write(items: list[dict]) -> None:
    path = settings.history_file
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # запись целиком или никак: обрыв не оставит половину файла


def add(kind: str, input_preview: str, result: dict) -> HistoryItem:
    item = HistoryItem(
        id=uuid.uuid4().hex[:12],
        timestamp=datetime.now(timezone.utc),
        kind=kind,
        input_preview=input_preview[:200],
        result=result,
    )
    with _lock:
        items = _read()
        items.append(json.loads(item.model_dump_json()))
        _write(items[-settings.max_history_items :])
    logger.info("В историю добавлено: %s (%s)", item.id, kind)
    return item


def get_all() -> list[dict]:
    with _lock:
        return list(reversed(_read()))  # новые сверху


def clear() -> None:
    with _lock:
        _write([])
