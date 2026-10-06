"""Сбор данных со страницы конкурента через Selenium (настоящий Chrome).

Возвращает title, H1, первый содержательный абзац, заголовки H2 и скриншот первого экрана.
"""
import base64
import io
import ipaddress
import logging
import socket
import time
from urllib.parse import urlparse

from PIL import Image
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

from backend.config import settings
from backend.models.schemas import ParsedContent

logger = logging.getLogger("parsing_service")

# Скрипт выполняется в странице: берём первый абзац с живым текстом (не меню и не подпись) и заголовки H2
_EXTRACT_JS = """
const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
const h1 = document.querySelector('h1');
// Баннеры cookie, меню, шапку и подвал пропускаем; ищем абзац после H1, а не просто первый на странице
const noise = 'footer, nav, header, [class*=cookie i], [id*=cookie i], [class*=consent i], [class*=popup i], [class*=modal i]';
const noiseText = /cookie|куки|персональн\\w+ данн|политик\\w+ конфиденциальн/i;
const isGood = p => {
  const t = clean(p.innerText);
  return t.length >= 60 && !p.closest(noise) && !noiseText.test(t);
};
const all = [...document.querySelectorAll('p')].filter(isGood);
const after = h1 ? all.find(p => h1.compareDocumentPosition(p) & Node.DOCUMENT_POSITION_FOLLOWING) : null;
const chosen = after || all[0];
const paragraph = chosen ? clean(chosen.innerText) : null;
const headings = [...document.querySelectorAll('h2')].map(h => clean(h.innerText)).filter(Boolean).slice(0, 12);
return {title: clean(document.title), h1: h1 ? clean(h1.innerText) : null, paragraph, headings};
"""


class ParsingError(Exception):
    """Страницу не удалось открыть или адрес недопустим."""


def validate_url(url: str) -> str:
    """Допускает только публичные http/https-адреса: не даём ходить в локальную сеть."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ParsingError("Нужен адрес вида https://example.com/page")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except socket.gaierror as exc:
        raise ParsingError("Адрес не найден (проверьте написание)") from exc
    if any(_is_internal(address) for address in addresses):
        raise ParsingError("Адреса локальной сети запрещены")
    return parsed.geturl()


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _is_internal(address: str) -> bool:
    """Адрес не из публичного интернета. NAT64 (64:ff9b::/96, его отдают DNS некоторых провайдеров)
    и IPv4-in-IPv6 проверяются по вложенному IPv4: сам префикс Python считает «непубличным»."""
    ip = ipaddress.ip_address(address)
    if ip.version == 6:
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif ip in _NAT64:
            ip = ipaddress.IPv4Address(ip.packed[-4:])
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified)


def _make_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument(f"--window-size={settings.parser_window}")
    options.add_argument("--disable-gpu")
    options.add_argument("--lang=ru-RU")
    options.page_load_strategy = "eager"  # не ждём тяжёлые картинки и счётчики
    driver = webdriver.Chrome(options=options)  # драйвер подбирает Selenium Manager
    driver.set_page_load_timeout(settings.parser_page_timeout)
    return driver


def _wait_until_rendered(driver) -> None:
    """Страницы с анимацией на старте дают чёрный кадр: ждём полной загрузки и даём секунду на отрисовку."""
    try:
        WebDriverWait(driver, 12).until(lambda d: d.execute_script("return document.readyState") == "complete")
    except TimeoutException:
        logger.warning("Страница не дозагрузилась за 12 с, снимаем как есть")
    time.sleep(1.5)


def _shrink_screenshot(png: bytes) -> str:
    image = Image.open(io.BytesIO(png)).convert("RGB")
    image.thumbnail((1280, 1280))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=80)
    return base64.b64encode(buffer.getvalue()).decode()


def parse_page(url: str) -> tuple[ParsedContent, str | None]:
    """Открывает страницу и возвращает (данные, скриншот JPEG в base64 или None)."""
    url = validate_url(url)
    logger.info("Открываю %s", url)
    driver = None
    try:
        driver = _make_driver()
        driver.get(url)
        _wait_until_rendered(driver)
        data = driver.execute_script(_EXTRACT_JS)
        try:
            screenshot = _shrink_screenshot(driver.get_screenshot_as_png())
        except WebDriverException:
            logger.warning("Скриншот не получен: %s", url)
            screenshot = None
    except WebDriverException as exc:
        logger.error("Не удалось открыть %s: %s", url, exc.msg.splitlines()[0] if exc.msg else exc)
        raise ParsingError("Страница не открылась (недоступна, блокирует автоматический сбор или слишком долго грузится)") from exc
    finally:
        if driver is not None:
            driver.quit()

    parsed = ParsedContent(
        url=url,
        title=data.get("title") or None,
        h1=data.get("h1"),
        first_paragraph=data.get("paragraph"),
        headings=data.get("headings") or [],
    )
    logger.info("Собрано: title=%r, h1=%r, абзац=%s, заголовков=%d", parsed.title, parsed.h1,
                "есть" if parsed.first_paragraph else "нет", len(parsed.headings))
    return parsed, screenshot
