"""Точка входа. Запуск: `uvicorn run:app --reload` или `python run.py`."""
from backend.main import app  # noqa: F401  (uvicorn run:app берёт приложение отсюда)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("run:app", host="127.0.0.1", port=8000, reload=False)
