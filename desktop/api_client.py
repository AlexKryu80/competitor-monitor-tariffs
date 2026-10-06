"""HTTP-клиент к backend (FastAPI). Адрес берётся из переменной COMPETITOR_API или по умолчанию локальный."""
import os
from pathlib import Path
from urllib.parse import urlparse

import requests

BASE_URL = os.environ.get("COMPETITOR_API", "http://127.0.0.1:8000")

_session = requests.Session()
if urlparse(BASE_URL).hostname in ("127.0.0.1", "localhost", "::1"):
    # Системный прокси (VPN, v2ray и т.п.) не должен перехватывать запросы к своему же компьютеру:
    # иначе вместо ответа сервера приходит «502 Bad Gateway» от прокси.
    _session.trust_env = False


class ApiError(Exception):
    pass


def _json(response: requests.Response):
    if response.ok:
        return response.json()
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    raise ApiError(detail if isinstance(detail, str) else f"Ошибка сервера {response.status_code}")


def _request(method: str, path: str, timeout: int, **kwargs):
    try:
        return _json(_session.request(method, BASE_URL + path, timeout=timeout, **kwargs))
    except requests.ConnectionError as exc:
        raise ApiError(f"Сервер не отвечает ({BASE_URL}). Запустите: python run.py") from exc
    except requests.Timeout as exc:
        raise ApiError("Сервер слишком долго отвечал") from exc


def health() -> dict:
    return _request("GET", "/health", 5)


def competitors() -> list[dict]:
    return _request("GET", "/competitors", 5)


def analyze_text(text: str) -> dict:
    return _request("POST", "/analyze_text", 120, json={"text": text})


def analyze_image(path: str) -> dict:
    file = Path(path)
    with file.open("rb") as handle:
        return _request("POST", "/analyze_image", 120, files={"file": (file.name, handle)})


def parse_url(url: str) -> dict:
    return _request("POST", "/parse_demo", 240, json={"url": url})


def history() -> list[dict]:
    return _request("GET", "/history", 10)


def clear_history() -> dict:
    return _request("DELETE", "/history", 10)
