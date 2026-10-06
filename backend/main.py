"""FastAPI: мультимодальный анализатор конкурентов."""
import logging
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from backend.config import COMPETITORS, settings
from backend.models.schemas import (
    CompetitorAnalysis,
    ImageAnalysis,
    PageAnalysis,
    ParseRequest,
    TextAnalysisRequest,
)
from backend.services import history_service
from backend.services.openai_service import AnalysisError, OpenAIService, prepare_image
from backend.services.parsing_service import ParsingError, parse_page

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("api")

app = FastAPI(title="Мониторинг конкурентов", version="1.0.0")
openai_service = OpenAIService()

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "api_key_set": bool(settings.openai_api_key), "model": settings.openai_model}


@app.get("/competitors")
def competitors() -> list[dict]:
    """Конкуренты из config.py: их страницы можно разобрать через /parse_demo."""
    return COMPETITORS


@app.post("/analyze_text", response_model=CompetitorAnalysis)
def analyze_text(request: TextAnalysisRequest) -> CompetitorAnalysis:
    try:
        result = openai_service.analyze_text(request.text)
    except AnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    history_service.add("text", request.text, result.model_dump())
    return result


@app.post("/analyze_image", response_model=ImageAnalysis)
def analyze_image(file: UploadFile = File(...)) -> ImageAnalysis:
    data = file.file.read(settings.max_image_bytes + 1)
    if len(data) > settings.max_image_bytes:
        raise HTTPException(status_code=413, detail="Файл больше 8 МБ")
    try:
        mime, image_b64 = prepare_image(data)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    try:
        result = openai_service.analyze_image(mime, image_b64)
    except AnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    history_service.add("image", file.filename or "изображение", result.model_dump())
    return result


@app.post("/parse_demo", response_model=PageAnalysis)
def parse_demo(request: ParseRequest) -> PageAnalysis:
    try:
        parsed, screenshot = parse_page(request.url)
    except ParsingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        analysis = openai_service.analyze_page(parsed)
    except AnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    visual = None
    if screenshot:
        try:
            visual = openai_service.analyze_image("image/jpeg", screenshot, "Скриншот первого экрана страницы конкурента.")
        except AnalysisError as exc:  # без скриншота разбор текста всё равно полезен
            logger.warning("Анализ скриншота не удался: %s", exc)

    result = PageAnalysis(parsed=parsed, analysis=analysis, visual=visual)
    history_service.add("parse", parsed.url, result.model_dump())
    return result


@app.get("/history")
def history() -> list[dict]:
    return history_service.get_all()


@app.delete("/history")
def clear_history() -> dict:
    history_service.clear()
    return {"status": "cleared"}


# Веб-интерфейс отдаётся с корня; монтируется последним, чтобы не перекрыть маршруты API
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
