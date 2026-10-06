"""Настройки приложения. Секреты читаются из файла окружения, в коде их нет."""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

# Ниша: финансовое сопровождение деятельности, финансовый аудит, экспертиза и формирование тарифов.
# Конкуренты — открытые страницы услуг компаний; список правится здесь же.
COMPETITORS = [
    {
        "name": "Энерго-тариф",
        "focus": "подготовка тарифных заявок (теплоснабжение, ГВС)",
        "url": "https://energo-tarif.ru/servis/podgotovka-tarifnyh-zayavok-v-sfere-teplosnabzheniya-i-gvs/",
    },
    {
        "name": "ИнжСтройКапитал",
        "focus": "экономическое обоснование тарифов",
        "url": "https://injstroykapital.ru/ekonomicheskoe-obosnovanie-tarifov/",
    },
    {
        "name": "ПрофИнАльянс",
        "focus": "тарифное регулирование",
        "url": "https://profinals.ru/tarifnoe-regulirovanie.html",
    },
    {
        "name": "MEF Legal",
        "focus": "обоснование и оспаривание тарифов естественных монополий",
        "url": "https://mef.legal/services/tarifnoe-regulirovanie",
    },
    {
        "name": "AP-Group",
        "focus": "обязательный финансовый аудит",
        "url": "https://www.ap-group.ru/services/audit/auditorskie-uslugi/fin-audit/",
    },
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    # OpenAI или совместимый прокси (ProxyAPI): ключ в файле окружения, адрес по необходимости
    openai_api_key: str = Field(default="", repr=False)
    openai_base_url: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_vision_model: str = "gpt-4o-mini"
    openai_timeout: float = 90.0

    # История запросов
    history_file: Path = BASE_DIR / "history.json"
    max_history_items: int = 10

    # Парсинг через Selenium (Chrome)
    parser_page_timeout: int = 30
    parser_window: str = "1366,900"

    # Ограничения на вход
    max_image_bytes: int = 8 * 1024 * 1024
    max_text_chars: int = 20000


settings = Settings()
