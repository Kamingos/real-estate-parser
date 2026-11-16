"""
Парсер объявлений Яндекс Недвижимости (realty.yandex.ru) на Selenium.

Схема работы (такая же, как в CianParser и AvitoParser):
1. Парсер постранично обходит списки объявлений по категориям и собирает
   только ссылки на страницы объявлений (``https://realty.yandex.ru/offer/<id>/``).
2. Затем для каждой ссылки открывается страница объявления и из неё
   извлекаются все поля модели YandexSiteParseData.

Приоритет источников данных на странице объявления:
- JSON состояния страницы ``window.__INITIAL_STATE__`` (блоки ``offer`` и
  ``offers.entities``) — основной источник;
- JSON-LD (``<script type="application/ld+json">``) — резервный источник;
- HTML-разметка (``data-testid``, ``itemprop``, ссылки ``/offer/``,
  галерея) — последний резерв.

Яндекс закрывает автоматические запросы SmartCaptcha, поэтому:
- браузер запускается с теми же stealth-настройками, что у Cian/Avito;
- при обнаружении капчи парсер останавливается и ждёт решения капчи
  в открытом браузере (как Cian), после чего продолжает работу;
- при сетевых ошибках выполняются повторные попытки с экспоненциальной
  паузой (backoff), между запросами выдерживается случайная задержка.

Ошибки сети, отсутствующие поля и некорректный HTML не останавливают
процесс: проблемное объявление пропускается с записью в лог.
"""

import json
import logging
import re
from random import uniform
from time import sleep
from typing import Any, Literal, cast
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from bs4.element import Tag
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from interfaces.parser_interfaces import IParcer
from model.parser_config import ParserConfig
from model.site_parse_data_model import YandexSiteParseData, geoLabelDict

# ------------------------------------------------------------------------------
# Настройки логирования
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("yandex_parser")

# Время ожидания загрузки страницы по умолчанию (секунды)
PAGE_WAIT_TIME = 10

# Задержки между запросами по умолчанию (используются, если в ParserConfig
# интервалы заданы нулевыми). Яндекс строже остальных источников, поэтому
# паузы больше, чем у Cian/Avito.
DEFAULT_MIN_DELAY = 2.0
DEFAULT_MAX_DELAY = 5.0

# Город по умолчанию, если ParserConfig.cities пуст
DEFAULT_CITY = {"vladivostok": 585430}

# Транслитерация названий городов в slug для URL
CITY_SLUGS = {
    "владивосток": "vladivostok",
    "москва": "moscow",
    "санкт-петербург": "saint-petersburg",
    "новосибирск": "novosibirsk",
    "екатеринбург": "ekaterinburg",
    "казань": "kazan",
}

# Шаблоны URL поисковой выдачи по категориям
CATEGORY_URLS = {
    "flat": "https://realty.yandex.ru/{city}/kupit/kvartira/?page={page}",
    "newbuilding": "https://realty.yandex.ru/{city}/kupit/novostrojka/?page={page}",
    "house": "https://realty.yandex.ru/{city}/kupit/dom/?page={page}",
    "land_plot": "https://realty.yandex.ru/{city}/kupit/uchastok/?page={page}",
    "garage": "https://realty.yandex.ru/{city}/kupit/garazh/?page={page}",
    "commercial": (
        "https://realty.yandex.ru/{city}/kupit/kommercheskaya-nedvizhimost/"
        "?page={page}"
    ),
}

# Комнаты ищутся через общий поиск с идентификатором региона (rgid)
ROOMS_URL = (
    "https://realty.yandex.ru/search/?rgid={rgid}&type=SELL"
    "&category=ROOMS&route=search&page={page}"
)

# Категория выдачи -> тип объекта модели
CATEGORY_OBJECT_TYPES = {
    "flat": "flat",
    "newbuilding": "flat",
    "house": "house",
    "land_plot": "land_plot",
    "garage": "garage",
    "commercial": "other",
    "room": "room",
}

# Категория объявления Яндекса -> тип объекта модели
YANDEX_CATEGORY_OBJECT_TYPES = {
    "apartment": "flat",
    "flat": "flat",
    "newbuilding": "flat",
    "room": "room",
    "rooms": "room",
    "house": "house",
    "lot": "land_plot",
    "land": "land_plot",
    "landplot": "land_plot",
    "garage": "garage",
    "parking": "garage",
    "commercial": "other",
}

ObjectType = Literal[
    "flat",
    "room",
    "studio",
    "house",
    "land_plot",
    "garage",
    "other",
]

# Допустимые значения Literal-поля object_type
OBJECT_TYPES = {"flat", "room", "studio", "house", "land_plot", "garage", "other"}

GEO_KEYS = ("region", "city", "district", "micro_district", "street", "house")

# Подписи для кодов валют
CURRENCY_LABELS = {
    "rur": "RUB",
    "rub": "RUB",
    "₽": "RUB",
    "ruble": "RUB",
    "rubles": "RUB",
    "usd": "USD",
    "$": "USD",
    "eur": "EUR",
    "€": "EUR",
}

# Подписи для типов продавца
SELLER_TYPE_LABELS = {
    "agency": "Агентство",
    "agent": "Агент",
    "developer": "Застройщик",
    "owner": "Частное лицо",
    "private": "Частное лицо",
    "агентство": "Агентство",
    "агент": "Агент",
    "застройщик": "Застройщик",
    "частноелицо": "Частное лицо",
}

# Подписи для единиц площади
AREA_UNIT_LABELS = {
    "sqm": "м²",
    "mtk": "м²",
    "m2": "м²",
    "квм": "м²",
    "м²": "м²",
    "ha": "га",
    "hectare": "га",
    "га": "га",
    "sotka": "сот.",
    "сот": "сот.",
    "сот.": "сот.",
}

# Подписи для материалов стен
BUILDING_MATERIAL_LABELS = {
    "monolith": "монолит",
    "monolithic": "монолит",
    "brick": "кирпич",
    "panel": "панель",
    "block": "блок",
    "wood": "дерево",
    "monolithbrick": "монолитно-кирпичный",
}

# Подписи для санузла
BATHROOM_LABELS = {
    "separate": "раздельный",
    "separated": "раздельный",
    "combined": "совмещённый",
}

# Подписи для балкона/лоджии
BALCONY_LABELS = {
    "balcony": "балкон",
    "loggia": "лоджия",
}

# Подписи для отделки
FINISHING_LABELS = {
    "without": "без отделки",
    "rough": "черновая",
    "prefinishing": "предчистовая",
    "fine": "чистовая",
    "designer": "дизайнерский",
    "design": "дизайнерский",
}

# Подписи для статуса дома
BUILDING_STATUS_LABELS = {
    "built": "сдан",
    "delivered": "сдан",
    "underconstruction": "строится",
    "construction": "строится",
}

# Подписи для типов лифтов
ELEVATOR_TYPE_LABELS = {
    "passenger": "пассажирский",
    "cargo": "грузовой",
    "cargopassenger": "грузопассажирский",
    "service": "служебный",
}

# Признаки страницы SmartCaptcha. Проверяются только однозначные маркеры,
# чтобы не ловить ложные срабатывания на обычных страницах.
CAPTCHA_TEXT_MARKERS = (
    "подтвердите, что вы не робот",
    "are you not a robot",
    "confirm that you are not a robot",
    "подтвердите, что запросы отправляли вы",
    "доступ ограничен",
)

# Маркеры JSON-состояния страницы
INITIAL_STATE_MARKERS = (
    "window.__INITIAL_STATE__",
    "window._initialState",
    "window.__INITIAL_STATE",
)

# JSON-LD блок страницы
JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)

# Ссылка/идентификатор объявления: https://realty.yandex.ru/offer/<id>/
OFFER_URL_RE = re.compile(r"/offer/(\d{6,})/?")
OFFER_ID_RE = re.compile(r"/offer/(\d{6,})/?")

# Содержимое страницы объявления, по которому ждём загрузку
CONTENT_SELECTOR = (
    '[data-testid="offer-price"], [data-testid="offer-description"], '
    '[itemprop="price"], h1'
)

# Содержимое страницы списка объявлений
LISTING_SELECTOR = (
    '[data-testid="serp-item"], a[href*="/offer/"], '
    '[class*="OffersSerpItem"]'
)


# ==============================================================================
# Вспомогательные функции
# ==============================================================================

def _clean(value: Any) -> str:
    """Приводит значение к чистой строке (без лишних пробелов/переносов)."""
    if value is None:
        return ""
    if isinstance(value, dict):
        # Словарь Яндекса ({"name": ...} / {"label": ...}) разворачиваем
        # в осмысленную строку, а не в repr(dict)
        name = (
            value.get("name")
            or value.get("title")
            or value.get("label")
            or value.get("value")
        )
        return _clean(name)
    if isinstance(value, list):
        return ", ".join(_clean(item) for item in value if _clean(item))
    return re.sub(r"\s+", " ", str(value)).strip()


def _to_int(value: Any) -> int:
    """Безопасное преобразование значения в int (0 при неудаче)."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        for key in ("value", "total", "count", "amount"):
            if key in value:
                return _to_int(value[key])
        return 0

    digits = re.sub(r"[\s\u00a0]", "", str(value))
    match = re.search(r"-?\d+", digits)

    return int(match.group()) if match else 0


def _to_int_or_none(value: Any) -> int | None:
    """Преобразование в int, при отсутствии значения возвращает None."""
    if value is None or value == "":
        return None
    return _to_int(value)


def _to_float(value: Any) -> float:
    """Безопасное преобразование значения в float (0.0 при неудаче)."""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("value", "total", "amount"):
            if key in value:
                return _to_float(value[key])
        return 0.0

    match = re.search(
        r"(\d+(?:[.,]\d+)?)",
        str(value).replace(" ", "").replace("\u00a0", ""),
    )

    return float(match.group(1).replace(",", ".")) if match else 0.0


def _label_from_map(value: Any, labels: dict[str, str]) -> str:
    """Переводит код Яндекса в читаемую подпись (или возвращает как есть)."""
    text = _clean(value)
    if not text:
        return ""
    key = re.sub(r"[\s_\-]", "", text).casefold()
    return labels.get(key, text)


def _normalize_currency(value: Any) -> str:
    """Нормализует код валюты (₽/RUR/RUB -> RUB)."""
    text = _clean(value)
    if not text:
        return ""
    return _label_from_map(text, CURRENCY_LABELS)


def _normalize_area_unit(value: Any) -> str:
    """Нормализует единицу площади (SQM -> м²)."""
    return _label_from_map(value, AREA_UNIT_LABELS)


def _normalize_seller_type(value: Any) -> str:
    """Нормализует тип продавца (AGENCY -> Агентство)."""
    return _label_from_map(value, SELLER_TYPE_LABELS)


def _deep_find(data: Any, keys: tuple[str, ...]) -> Any:
    """
    Ищет по всем вложенным словарям/спискам первое непустое значение,
    ключ которого совпадает (без учёта регистра) с одним из ``keys``.
    Позволяет не зависеть от точной структуры JSON Яндекса.
    """
    wanted = {key.casefold() for key in keys}
    queue: list[Any] = [data]

    while queue:
        node = queue.pop(0)

        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    isinstance(key, str)
                    and key.casefold() in wanted
                    and value not in (None, "", [], {})
                ):
                    return value
            queue.extend(node.values())

        elif isinstance(node, list):
            queue.extend(node)

    return None


def _deep_find_flag(data: Any, keys: tuple[str, ...]) -> bool | None:
    """
    Как _deep_find, но для булевых полей: возвращает False, если ключ найден
    со значением False (в том числе строкой "false").
    """
    wanted = {key.casefold() for key in keys}
    queue: list[Any] = [data]

    while queue:
        node = queue.pop(0)

        if isinstance(node, dict):
            for key, value in node.items():
                if not (isinstance(key, str) and key.casefold() in wanted):
                    continue

                if isinstance(value, bool):
                    return value

                if isinstance(value, str):
                    normalized = value.strip().casefold()
                    if normalized in ("true", "yes", "1"):
                        return True
                    if normalized in ("false", "no", "0"):
                        return False

            queue.extend(node.values())

        elif isinstance(node, list):
            queue.extend(node)

    return None


def _looks_like_captcha(html: str, current_url: str = "") -> bool:
    """
    Определяет страницу SmartCaptcha/блокировки Яндекса.

    Нельзя проверять голую подстроку "captcha" по всему HTML: на обычных
    страницах слово встречается в служебных скриптах. Проверяем URL,
    точные тексты заглушки и реальные элементы капчи в DOM.
    """
    lowered_url = current_url.casefold()
    if (
        "showcaptcha" in lowered_url
        or "captcha" in urlparse(lowered_url).netloc
        or "/captcha" in lowered_url
    ):
        return True

    lowered = html[:20000].casefold()

    if any(marker in lowered for marker in CAPTCHA_TEXT_MARKERS):
        return True

    if re.search(
        r"<iframe[^>]*(?:smartcaptcha\.yandexcloud\.net|showcaptcha)",
        lowered,
    ):
        return True

    if re.search(r'<div[^>]*class="[^"]*smart-captcha', lowered):
        return True

    return False


# ==============================================================================
# Парсер
# ==============================================================================

class YandexParser(IParcer):
    """Парсер Яндекс Недвижимости: списки объявлений -> страницы -> модель."""

    def __init__(self) -> None:
        self.categories = dict(CATEGORY_URLS)
        self.categories["room"] = ROOMS_URL

        # Настройки браузера (как в Cian/Avito-парсерах)
        self.options = Options()
        self.options.page_load_strategy = "eager"

        self.options.add_experimental_option(
            "excludeSwitches",
            ["enable-automation"],
        )
        self.options.add_experimental_option(
            "useAutomationExtension",
            False,
        )
        self.options.add_argument(
            "--disable-blink-features=AutomationControlled"
        )

    # --------------------------------------------------------------------------
    # Публичный интерфейс
    # --------------------------------------------------------------------------

    def parse(
        self,
        parserConfig: ParserConfig,
    ) -> tuple[bool, list[YandexSiteParseData] | None]:

        if parserConfig.headless and "--headless=new" not in self.options.arguments:
            self.options.add_argument("--headless=new")

        try:
            driver = webdriver.Chrome(options=self.options)
        except WebDriverException as error:
            logger.error("Не удалось запустить браузер: %s", error)
            return False, None

        page_wait = parserConfig.page_wait_time or PAGE_WAIT_TIME
        max_retries = max(1, parserConfig.max_retries)
        driver.set_page_load_timeout(page_wait)

        # Скрываем признак автоматизации (navigator.webdriver)
        try:
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": (
                        "Object.defineProperty(navigator, 'webdriver', "
                        "{get: () => undefined});"
                    )
                },
            )
        except WebDriverException as error:
            logger.warning("Не удалось применить stealth-скрипт: %s", error)

        offers: list[YandexSiteParseData] = []
        seen_urls: set[str] = set()
        seen_ids: set[str] = set()

        min_delay, max_delay = self._resolve_delays(parserConfig)

        cities = dict(parserConfig.cities)
        if not cities:
            logger.warning(
                "Не заданы города в ParserConfig.cities, используется %s",
                DEFAULT_CITY,
            )
            cities = dict(DEFAULT_CITY)

        try:
            # ------------------------------------------------------------------
            # Этап 1: обходим списки объявлений и собираем ссылки
            # ------------------------------------------------------------------
            pending_urls: list[str] = []

            for city_key, city_id in cities.items():
                city_slug = self._city_slug(city_key)

                for category in self.categories:
                    city_urls = self._collect_offer_urls(
                        driver=driver,
                        city_slug=city_slug,
                        rgid=city_id,
                        category=category,
                        max_pages=parserConfig.max_page_iteration,
                        page_wait=page_wait,
                        min_delay=min_delay,
                        max_delay=max_delay,
                        max_retries=max_retries,
                    )

                    for url in city_urls:
                        if url not in seen_urls:
                            seen_urls.add(url)
                            pending_urls.append(url)

            logger.info(
                "Собрано уникальных ссылок на объявления: %d", len(pending_urls)
            )

            # ------------------------------------------------------------------
            # Этап 2: открываем страницу каждого объявления и парсим данные
            # ------------------------------------------------------------------
            for index, offer_url in enumerate(pending_urls, start=1):
                logger.info(
                    "Объявление %d/%d: %s", index, len(pending_urls), offer_url
                )

                item = self._parse_offer_page(
                    driver,
                    offer_url,
                    page_wait,
                    max_retries,
                )

                if item is None:
                    logger.warning("Пропущено объявление: %s", offer_url)
                elif not self._validate_item(item):
                    logger.warning(
                        "Объявление не прошло валидацию: %s", offer_url
                    )
                elif item.external_id and item.external_id in seen_ids:
                    logger.info(
                        "Дубликат объявления пропущен: %s", item.external_id
                    )
                else:
                    if item.external_id:
                        seen_ids.add(item.external_id)
                    offers.append(item)

                sleep(uniform(min_delay, max_delay))

        finally:
            driver.quit()

        logger.info("Итого собрано объявлений: %d", len(offers))

        return True, offers

    # --------------------------------------------------------------------------
    # Этап 1: сбор ссылок из списков объявлений
    # --------------------------------------------------------------------------

    def _collect_offer_urls(
        self,
        *,
        driver: webdriver.Chrome,
        city_slug: str,
        rgid: int,
        category: str,
        max_pages: int,
        page_wait: int,
        min_delay: float,
        max_delay: float,
        max_retries: int,
    ) -> list[str]:
        """Обходит постранично выдачу категории и возвращает URL объявлений."""
        urls: list[str] = []
        page = 1

        while page <= max_pages:
            page_url = self._category_page_url(category, city_slug, rgid, page)

            success, page_urls = self._parse_listing_page(
                driver,
                page_url,
                page_wait,
                max_retries,
            )

            if not success:
                logger.warning(
                    "Не удалось загрузить список (город=%s, категория=%s, "
                    "стр. %d) — страница пропущена",
                    city_slug,
                    category,
                    page,
                )
                break

            logger.info(
                "Список %s/%s, стр. %d: найдено %d объявлений",
                city_slug,
                category,
                page,
                len(page_urls),
            )

            # Пустая страница означает конец выдачи
            if not page_urls:
                break

            urls.extend(page_urls)
            page += 1

            sleep(uniform(min_delay, max_delay))

        return urls

    def _category_page_url(
        self,
        category: str,
        city_slug: str,
        rgid: int,
        page: int,
    ) -> str:
        """Собирает URL страницы выдачи для категории."""
        template = self.categories[category]

        if category == "room":
            return template.format(rgid=rgid, page=page)

        return template.format(city=city_slug, page=page)

    def _parse_listing_page(
        self,
        driver: webdriver.Chrome,
        page_url: str,
        page_wait: int,
        max_retries: int,
    ) -> tuple[bool, list[str]]:
        """Открывает страницу списка и извлекает ссылки на объявления."""
        html = self._load_page(
            driver,
            page_url,
            page_wait,
            max_retries,
            content_selector=LISTING_SELECTOR,
        )

        if html is None:
            return False, []

        try:
            return True, self._extract_listing_urls(html, page_url)
        except Exception as error:  # некорректный HTML
            logger.error("Ошибка разбора HTML списка %s: %s", page_url, error)
            return False, []

    def _extract_listing_urls(self, html: str, page_url: str) -> list[str]:
        """Извлекает ссылки на объявления из HTML страницы списка."""
        urls: list[str] = []
        seen: set[str] = set()

        # 1. Основной источник — JSON состояния страницы (offers.entities)
        state = self._extract_initial_state(html)
        if isinstance(state, dict):
            for offer in self._iter_state_offers(state):
                offer_id = _clean(offer.get("offerId") or offer.get("id"))
                url = self._canonical_offer_url(
                    f"https://realty.yandex.ru/offer/{offer_id}/"
                )
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)

        if urls:
            return urls

        # 2. Резерв — ссылки и идентификаторы в HTML
        candidates: list[str] = []

        for match in re.finditer(r'href=["\']([^"\']+)["\']', html):
            candidates.append(match.group(1))

        for match in re.finditer(r'"offerId"\s*:\s*"?(\d{6,})"?', html):
            candidates.append(f"/offer/{match.group(1)}/")

        for match in re.finditer(r'data-offer-id=["\'](\d{6,})["\']', html):
            candidates.append(f"/offer/{match.group(1)}/")

        for href in candidates:
            url = self._canonical_offer_url(urljoin(page_url, href))
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        return urls

    def _canonical_offer_url(self, href: str) -> str | None:
        """Нормализует ссылку на объявление (только схема/домен/путь)."""
        if not href or not href.strip():
            return None

        url = urljoin("https://realty.yandex.ru", href.strip())
        parsed = urlparse(url)

        if parsed.netloc and not parsed.netloc.endswith("yandex.ru"):
            return None

        match = OFFER_URL_RE.search(parsed.path)

        if not match:
            return None

        return urlunparse(
            (
                parsed.scheme or "https",
                parsed.netloc or "realty.yandex.ru",
                f"/offer/{match.group(1)}/",
                "",
                "",
                "",
            )
        )

    # --------------------------------------------------------------------------
    # Этап 2: парсинг страницы объявления
    # --------------------------------------------------------------------------

    def _parse_offer_page(
        self,
        driver: webdriver.Chrome,
        url: str,
        page_wait: int,
        max_retries: int,
    ) -> YandexSiteParseData | None:
        """Открывает страницу объявления и собирает все поля модели."""
        html = self._load_page(driver, url, page_wait, max_retries)

        if html is None:
            return None

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception as error:  # некорректный HTML
            logger.error("Ошибка разбора HTML %s: %s", url, error)
            return None

        data = self._empty_data()

        # 1. Основной источник — JSON состояния страницы
        state = self._extract_initial_state(html)
        if isinstance(state, dict):
            try:
                self._apply_state(data, state, url)
            except Exception as error:
                logger.error("Ошибка разбора JSON состояния %s: %s", url, error)

        # 2. Резерв — JSON-LD
        json_ld_nodes = self._extract_json_ld(soup)
        if json_ld_nodes:
            try:
                self._apply_json_ld(data, json_ld_nodes)
            except Exception as error:
                logger.error("Ошибка разбора JSON-LD %s: %s", url, error)

        # 3. Резерв — HTML-разметка
        try:
            html_data = self._extract_html_data(soup, url)
        except Exception as error:
            logger.error("Ошибка разбора HTML объявления %s: %s", url, error)
            html_data = None

        if html_data:
            self._apply_html(data, html_data)

        item = self._build_item(data, url)

        if item is None:
            logger.warning("Не удалось извлечь данные объявления: %s", url)
            return None

        return item

    # --------------------------- Загрузка страниц ---------------------------

    def _load_page(
        self,
        driver: webdriver.Chrome,
        url: str,
        page_wait: int,
        max_attempts: int,
        content_selector: str = CONTENT_SELECTOR,
    ) -> str | None:
        """
        Загружает страницу с повторными попытками и обработкой SmartCaptcha.

        При сетевых ошибках пауза между попытками растёт (экспоненциальный
        backoff с джиттером). При капче управление передаётся в
        _handle_captcha (ожидание решения капчи пользователем).
        """
        max_attempts = max(1, max_attempts)

        for attempt in range(1, max_attempts + 1):
            try:
                driver.get(url)
            except TimeoutException:
                # Продолжаем работу с уже полученным DOM
                try:
                    driver.execute_script("window.stop();")
                except WebDriverException:
                    pass
            except WebDriverException as error:
                logger.warning(
                    "Ошибка загрузки %s (попытка %d/%d): %s",
                    url,
                    attempt,
                    max_attempts,
                    error,
                )

                if attempt >= max_attempts:
                    return None

                sleep(uniform(2, 5) * attempt)
                continue

            self._wait_for_content(driver, content_selector, page_wait)

            html = driver.page_source

            if not _looks_like_captcha(html, driver.current_url):
                return html

            logger.warning(
                "SmartCaptcha на странице (попытка %d/%d): %s",
                attempt,
                max_attempts,
                url,
            )

            return self._handle_captcha(
                driver,
                url,
                page_wait,
                max_attempts=max_attempts - attempt + 1,
            )

        return None

    def _wait_for_content(
        self,
        driver: webdriver.Chrome,
        selector: str,
        page_wait: int,
    ) -> None:
        """Ждёт появления содержимого страницы, не дожидаясь всех ресурсов."""
        try:
            WebDriverWait(driver, page_wait).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
        except TimeoutException:
            pass

    def _handle_captcha(
        self,
        driver: webdriver.Chrome,
        url: str,
        page_wait: int,
        max_attempts: int = 3,
    ) -> str | None:
        """
        Обрабатывает SmartCaptcha: ждёт решения капчи в открытом браузере.

        Делается до ``max_attempts`` попыток. Один раз сохраняет HTML
        страницы в yandex_captcha_debug.html для последующего анализа.
        Возвращает актуальный HTML или None (если попытки исчерпаны).
        """
        debug_saved = False

        for attempt in range(1, max_attempts + 1):
            if not debug_saved:
                try:
                    with open(
                        "yandex_captcha_debug.html", "w", encoding="utf-8"
                    ) as file:
                        file.write(driver.page_source)
                    logger.info(
                        "HTML с капчей сохранён в yandex_captcha_debug.html"
                    )
                except OSError as error:
                    logger.error(
                        "Не удалось сохранить отладочный HTML: %s", error
                    )
                debug_saved = True

            try:
                answer = input(
                    f"\n[CAPTCHA] Решите капчу в открывшемся браузере "
                    f"(попытка {attempt}/{max_attempts}),\n"
                    "затем нажмите Enter здесь в консоли для продолжения "
                    "(введите 'n' — пропустить): "
                ).strip().lower()
            except EOFError:
                # Неинтерактивный режим консоли: пробуем перезагрузку
                answer = ""

            if answer == "n":
                logger.warning("Капча пропущена пользователем: %s", url)
                return None

            try:
                driver.get(url)
            except TimeoutException:
                try:
                    driver.execute_script("window.stop();")
                except WebDriverException:
                    pass
            except WebDriverException as error:
                logger.warning("Ошибка загрузки %s: %s", url, error)
                return None

            self._wait_for_content(driver, CONTENT_SELECTOR, page_wait)

            html = driver.page_source

            if not _looks_like_captcha(html, driver.current_url):
                logger.info("Капча пройдена, продолжаем: %s", url)
                return html

            logger.warning(
                "Капча всё ещё отображается после попытки %d", attempt
            )

            if attempt < max_attempts:
                sleep(uniform(3, 7))

        logger.warning("Капча не пройдена за %d попыток: %s", max_attempts, url)
        return None

    # --------------------------- Источник: JSON ---------------------------

    def _extract_initial_state(self, html: str) -> dict | None:
        """
        Извлекает JSON состояния страницы (``window.__INITIAL_STATE__``).

        Используется raw_decode: он читает ровно один JSON-объект и
        игнорирует хвост скрипта после него.
        """
        for marker in INITIAL_STATE_MARKERS:
            position = html.find(marker)

            while position != -1:
                start = html.find("{", position)

                if start != -1:
                    try:
                        decoded, _ = json.JSONDecoder().raw_decode(html[start:])
                    except ValueError:
                        decoded = None

                    if isinstance(decoded, dict) and decoded:
                        return decoded

                position = html.find(marker, position + 1)

        return None

    def _iter_state_offers(self, state: dict) -> list[dict]:
        """Возвращает все объявления из JSON состояния страницы."""
        offers: list[dict] = []

        offers_block = state.get("offers")

        if isinstance(offers_block, dict):
            entities = offers_block.get("entities")

            if isinstance(entities, dict):
                for key, value in entities.items():
                    if isinstance(value, dict):
                        offer = dict(value)
                        offer.setdefault("offerId", key)
                        offers.append(offer)
            elif isinstance(entities, list):
                offers.extend(
                    value for value in entities if isinstance(value, dict)
                )

        for key in ("offer", "offerData", "currentOffer"):
            node = state.get(key)
            if isinstance(node, dict) and node:
                offers.append(node)

        return offers

    def _pick_offer(self, state: dict, url: str) -> dict:
        """Выбирает объявление страницы (по id из URL либо первое доступное)."""
        target_id = self._offer_id_from_url(url)
        candidates = self._iter_state_offers(state)

        if target_id:
            for candidate in candidates:
                candidate_id = _clean(
                    candidate.get("offerId") or candidate.get("id")
                )
                if candidate_id == target_id:
                    return candidate

        for key in ("offer", "offerData", "currentOffer"):
            node = state.get(key)
            if isinstance(node, dict) and node:
                return node

        if candidates:
            return candidates[0]

        fallback = _deep_find(state, ("offer",))

        return fallback if isinstance(fallback, dict) else state

    def _apply_state(self, data: dict, state: dict, url: str) -> None:
        """Заполняет словарь данных из JSON состояния страницы."""
        offer = self._pick_offer(state, url)

        building = offer.get("building")
        building = building if isinstance(building, dict) else {}

        new_building = offer.get("newBuilding")
        new_building = new_building if isinstance(new_building, dict) else {}

        address_block = offer.get("address")
        address_block = address_block if isinstance(address_block, dict) else {}

        location_block = offer.get("location")
        location_block = (
            location_block if isinstance(location_block, dict) else {}
        )

        seller = self._first_dict(
            offer.get("seller"),
            offer.get("author"),
            offer.get("agent"),
            state.get("seller"),
        )

        # --- Основная информация -------------------------------------------
        self._set(
            data,
            "external_id",
            _clean(offer.get("offerId") or offer.get("id") or offer.get("offerID")),
        )
        self._set(
            data,
            "name",
            _clean(
                offer.get("title")
                or offer.get("name")
                or offer.get("offerTitle")
            ),
        )
        self._set(
            data,
            "subtitles",
            _clean(
                offer.get("subtitle")
                or offer.get("shortDescription")
                or offer.get("annotation")
            ),
        )
        self._set(data, "description", _clean(offer.get("description")))

        category = _clean(offer.get("category")).upper()
        self._set(data, "category", category)

        self._set(
            data,
            "offer_article",
            _clean(
                _deep_find(
                    offer, ("offerArticle", "article", "vendorCode", "articleId")
                )
            )
            or self._article_from_text(data.get("description", "")),
        )

        object_type = self._object_type_from_category(category, url)

        flat_type = _clean(
            offer.get("flatType") or offer.get("apartmentType")
        ).casefold()
        title_casefold = _clean(data.get("name")).casefold()

        if object_type == "flat" and (
            "studio" in flat_type or "студи" in title_casefold
        ):
            object_type = "studio"

        self._set(data, "object_type", object_type)

        self._set(
            data,
            "housing_type",
            self._housing_type_from_state(offer, building, category),
        )

        self._set(
            data,
            "breadcrumbs",
            self._breadcrumbs_to_list(
                _deep_find(offer, ("breadcrumbs",))
            ),
        )

        # --- Цена и условия сделки ------------------------------------------
        price_block = offer.get("price")

        if isinstance(price_block, dict):
            price_value = price_block.get("value")
            currency_raw = price_block.get("currency")
        else:
            price_value = price_block
            currency_raw = offer.get("currency")

        self._set(data, "price", _to_int(price_value))
        self._set(data, "currency", _normalize_currency(currency_raw))

        self._set(
            data,
            "price_per_meter",
            _to_int(
                _deep_find(
                    offer,
                    ("pricePerSquareMeter", "pricePerMeter", "pricePerSqm"),
                )
            ),
        )

        deal_type = _clean(offer.get("type") or offer.get("dealType")).casefold()
        self._set(data, "deal_type", "rent" if "rent" in deal_type else "sale")

        self._set(
            data,
            "deal_conditions",
            _clean(
                _deep_find(
                    offer,
                    (
                        "dealConditions",
                        "saleConditions",
                        "bargainTerms",
                        "terms",
                    ),
                )
            ),
        )
        self._set(
            data,
            "mortgage_possible",
            _deep_find_flag(
                offer,
                ("mortgage", "mortgageAllowed", "isMortgageAvailable"),
            ),
        )
        self._set(
            data,
            "sale_method",
            _clean(
                _deep_find(
                    offer, ("saleType", "saleMethod", "participationType")
                )
            ),
        )

        # --- Основные характеристики -----------------------------------------
        area, area_unit = self._extract_measure(offer, ("area", "totalArea"))
        self._set(data, "area", area)
        self._set(data, "area_unit", _normalize_area_unit(area_unit))

        living_area, _ = self._extract_measure(offer, ("livingArea",))
        kitchen_area, _ = self._extract_measure(offer, ("kitchenArea",))
        self._set(data, "living_area", living_area)
        self._set(data, "kitchen_area", kitchen_area)

        rooms_raw = offer.get("roomsCount")

        if rooms_raw is None:
            rooms_raw = offer.get("rooms")

        if isinstance(rooms_raw, str) and "studio" in rooms_raw.casefold():
            self._set(data, "object_type", "studio")
            rooms_raw = None

        self._set(data, "rooms_count", _to_int_or_none(rooms_raw))
        self._set(
            data,
            "rooms_in_flat",
            _to_int_or_none(_deep_find(offer, ("roomsInFlat",))),
        )

        floor_raw = offer.get("floor")

        if isinstance(floor_raw, dict):
            floor_raw = floor_raw.get("value")

        self._set(data, "floor", _to_int(floor_raw))

        floors_count = _deep_find(
            offer, ("floorsCount", "floorsTotal", "houseFloors")
        )

        if floors_count is None:
            floors_count = building.get("floorsCount") or building.get("floors")

        self._set(data, "floors_count", _to_int(floors_count))
        self._set(
            data,
            "ceiling_height",
            _to_float(_deep_find(offer, ("ceilingHeight",))),
        )

        self._set(
            data,
            "bathroom",
            _label_from_map(
                _deep_find(
                    offer, ("bathroomUnit", "bathroomType", "bathroom")
                ),
                BATHROOM_LABELS,
            ),
        )
        self._set(
            data,
            "balcony",
            self._balcony_to_string(
                _deep_find(
                    offer,
                    ("balcony", "balconies", "loggia", "balconyType"),
                )
            ),
        )
        self._set(
            data,
            "window_view",
            _clean(
                _deep_find(
                    offer, ("windowView", "viewFromWindows", "windowsView")
                )
            ),
        )

        # --- Состояние и отделка ---------------------------------------------
        self._set(
            data,
            "repairs",
            _label_from_map(
                _deep_find(offer, ("repair", "repairs", "renovation")),
                FINISHING_LABELS,
            ),
        )
        self._set(
            data,
            "finishing",
            _label_from_map(
                _deep_find(offer, ("finishing", "decoration")),
                FINISHING_LABELS,
            ),
        )

        # --- Информация о доме -------------------------------------------------
        self._set(
            data,
            "year_building",
            _to_int(
                _deep_find(offer, ("yearBuild", "buildYear", "builtYear"))
                or building.get("year")
            ),
        )
        self._set(
            data,
            "building_status",
            _label_from_map(
                _deep_find(offer, ("buildingStatus", "houseStatus"))
                or building.get("status"),
                BUILDING_STATUS_LABELS,
            ),
        )
        self._set(
            data,
            "building_material",
            _label_from_map(
                _deep_find(
                    offer,
                    ("buildingMaterial", "material", "wallMaterial"),
                )
                or building.get("material"),
                BUILDING_MATERIAL_LABELS,
            ),
        )
        self._set(
            data,
            "building_type",
            _clean(
                _deep_find(offer, ("buildingType", "houseType"))
                or building.get("type")
            ),
        )
        self._set(
            data,
            "completion_date",
            _clean(
                _deep_find(
                    offer, ("completionDate", "deliveryDate", "deadline")
                )
                or new_building.get("completionDate")
            ),
        )
        self._set(
            data,
            "floors_range",
            _clean(
                _deep_find(offer, ("floorsRange",))
                or building.get("floorsRange")
            ),
        )
        self._set(
            data,
            "entrances_count",
            _to_int(
                _deep_find(offer, ("entrancesCount", "porchesCount"))
                or building.get("entrancesCount")
            ),
        )
        self._set(
            data,
            "apartments_count",
            _to_int(
                _deep_find(offer, ("apartmentsCount",))
                or building.get("apartmentsCount")
            ),
        )
        self._set(
            data,
            "elevators",
            self._format_elevators(
                _deep_find(building, ("elevators", "elevator"))
                or _deep_find(offer, ("elevators",))
            ),
        )
        self._set(
            data,
            "parking",
            _clean(
                _deep_find(offer, ("parking", "parkingType"))
                or building.get("parking")
            ),
        )
        self._set(
            data,
            "garbage_chute",
            _deep_find_flag(
                offer, ("garbageChute", "hasGarbageChute", "chute")
            ),
        )

        # --- Инженерия и коммуникации -------------------------------------------
        self._set(
            data,
            "heating",
            _clean(_deep_find(offer, ("heating", "heatingType"))),
        )
        self._set(
            data,
            "water_supply",
            _clean(_deep_find(offer, ("waterSupply", "water"))),
        )
        self._set(
            data,
            "sewerage",
            _clean(_deep_find(offer, ("sewerage", "sewage"))),
        )
        self._set(
            data,
            "electricity",
            _clean(_deep_find(offer, ("electricity", "powerSupply"))),
        )
        self._set(data, "gas", _clean(_deep_find(offer, ("gas", "gasSupply"))))
        self._set(
            data,
            "internet",
            _deep_find_flag(offer, ("internet", "hasInternet")),
        )
        self._set(
            data,
            "telephone",
            _deep_find_flag(offer, ("telephone", "hasTelephone", "phone")),
        )
        self._set(
            data,
            "sauna",
            _deep_find_flag(offer, ("sauna", "hasSauna")),
        )

        # --- Участок, гараж, коммерческое помещение ------------------------------
        self._set(
            data,
            "land_type",
            _clean(
                _deep_find(offer, ("landType", "lotType", "landCategory"))
            ),
        )

        land_area, land_unit = self._extract_measure(
            offer, ("landArea", "lotArea")
        )
        self._set(data, "land_area", land_area)
        self._set(data, "land_area_unit", _normalize_area_unit(land_unit))

        self._set(
            data,
            "garage_type",
            _clean(_deep_find(offer, ("garageType", "garageKind"))),
        )
        self._set(
            data,
            "commercial_purpose",
            _clean(
                _deep_find(offer, ("commercialPurpose", "purpose", "purposeType"))
            ),
        )
        self._set(
            data,
            "entrance_type",
            _clean(_deep_find(offer, ("entranceType", "entrance"))),
        )

        # --- ЖК и застройщик -------------------------------------------------------
        self._set(
            data,
            "residential_complex",
            _clean(
                new_building.get("name")
                or _deep_find(
                    offer, ("residentialComplex", "complexName", "newBuildingName")
                )
            ),
        )
        self._set(
            data,
            "residential_complex_class",
            _clean(
                new_building.get("class")
                or _deep_find(offer, ("residentialComplexClass", "buildingClass"))
            ),
        )
        self._set(
            data,
            "residential_complex_completion",
            _clean(
                new_building.get("completionDate")
                or _deep_find(offer, ("residentialComplexCompletion",))
            ),
        )

        developer_block = _deep_find(offer, ("developer", "builder"))

        if isinstance(developer_block, dict):
            self._set(
                data, "developer", _clean(developer_block.get("name"))
            )
            self._set(
                data,
                "developer_foundation_year",
                _to_int(developer_block.get("foundationYear")),
            )
            self._set(
                data,
                "developer_completed_buildings",
                _to_int(developer_block.get("completedBuildings")),
            )
            self._set(
                data,
                "developer_buildings_under_construction",
                _to_int(developer_block.get("buildingsUnderConstruction")),
            )
        else:
            self._set(data, "developer", _clean(developer_block))

        if not data.get("developer"):
            self._set(
                data, "developer", _clean(new_building.get("developerName"))
            )

        # --- География ---------------------------------------------------------------
        geo_label = data["geo_label"]

        self._fill_geo(
            geo_label,
            region=address_block.get("region")
            or location_block.get("region")
            or _deep_find(offer, ("region",)),
            city=address_block.get("locality")
            or address_block.get("city")
            or location_block.get("locality")
            or _deep_find(offer, ("locality", "city")),
            district=address_block.get("district")
            or location_block.get("district")
            or _deep_find(offer, ("district", "districtName")),
            micro_district=address_block.get("microDistrict")
            or location_block.get("microDistrict")
            or _deep_find(offer, ("microDistrict", "microdistrict")),
            street=address_block.get("street")
            or location_block.get("street")
            or _deep_find(offer, ("street",)),
            house=address_block.get("house")
            or location_block.get("house")
            or _deep_find(offer, ("house",)),
        )

        address_raw = offer.get("address")

        if isinstance(address_raw, str):
            self._set(data, "address", _clean(address_raw))
        else:
            self._set(
                data,
                "address",
                _clean(
                    location_block.get("address")
                    or _deep_find(offer, ("addressText", "fullAddress"))
                ),
            )

        coordinates = _deep_find(offer, ("coordinates",))

        if isinstance(coordinates, dict):
            self._set(
                data,
                "latitude",
                _to_float(
                    coordinates.get("lat") or coordinates.get("latitude")
                ),
            )
            self._set(
                data,
                "longitude",
                _to_float(
                    coordinates.get("lon") or coordinates.get("longitude")
                ),
            )
        else:
            self._set(
                data,
                "latitude",
                _to_float(_deep_find(offer, ("latitude", "lat"))),
            )
            self._set(
                data,
                "longitude",
                _to_float(_deep_find(offer, ("longitude", "lon", "lng"))),
            )

        self._set(
            data,
            "nearby_infrastructure",
            self._as_str_list(
                _deep_find(offer, ("nearbyInfrastructure", "infrastructure"))
            ),
        )

        # --- Продавец ------------------------------------------------------------------
        self._set(
            data,
            "seller_name",
            _clean(seller.get("name") or seller.get("displayName")),
        )
        self._set(
            data,
            "seller_type",
            _normalize_seller_type(
                seller.get("type") or seller.get("sellerType")
            ),
        )
        self._set(
            data,
            "agency",
            _clean(
                seller.get("agency")
                or seller.get("agencyName")
                or seller.get("company")
            ),
        )
        self._set(
            data,
            "seller_experience",
            _clean(
                seller.get("experience")
                or seller.get("experienceText")
                or seller.get("registeredYears")
            ),
        )

        # --- Фотографии ------------------------------------------------------------------
        photos = offer.get("photos") or offer.get("images") or []
        imgs: list[str] = []

        if isinstance(photos, list):
            for photo in photos:
                if isinstance(photo, dict):
                    src = _clean(
                        photo.get("fullUrl")
                        or photo.get("url")
                        or photo.get("originalUrl")
                        or photo.get("src")
                    )
                else:
                    src = _clean(photo)

                if src.startswith("//"):
                    src = f"https:{src}"

                if src.startswith("http"):
                    imgs.append(src)

        self._set(data, "imgs", list(dict.fromkeys(imgs)))

        # --- Статистика и маркеры ----------------------------------------------------------
        self._set(
            data,
            "publish_date",
            _clean(
                _deep_find(
                    offer,
                    ("creationDate", "createdDate", "publishDate", "publishedAt"),
                )
            ),
        )
        self._set(
            data,
            "update_date",
            _clean(
                _deep_find(
                    offer, ("updateDate", "editedDate", "updatedAt")
                )
            ),
        )

        views = _deep_find(offer, ("viewsCount", "views"))

        if isinstance(views, dict):
            self._set(data, "views_count", _to_int(views.get("total")))
        else:
            self._set(data, "views_count", _to_int(views))

        self._set(
            data,
            "badges",
            self._as_str_list(_deep_find(offer, ("badges", "labels"))),
        )

        features = _deep_find(
            offer, ("features", "featureChips", "options", "tags")
        )
        self._set(data, "feature_chips", self._features_to_list(features))
        self._set(data, "parameters", self._features_to_parameters(features))

    # --------------------------- Источник: JSON-LD ---------------------------

    def _extract_json_ld(self, soup: BeautifulSoup) -> list[dict]:
        """Извлекает все JSON-LD объекты страницы."""
        nodes: list[dict] = []

        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            if not isinstance(script, Tag):
                continue

            raw = script.string or script.get_text()
            if not raw or not raw.strip():
                continue

            try:
                decoded = json.loads(raw)
            except ValueError:
                continue

            if isinstance(decoded, dict):
                nodes.append(decoded)
            elif isinstance(decoded, list):
                nodes.extend(item for item in decoded if isinstance(item, dict))

        return nodes

    def _apply_json_ld(self, data: dict, nodes: list[dict]) -> None:
        """Заполняет словарь данных из JSON-LD (резервный источник)."""
        for node in nodes:
            node_type = _clean(node.get("@type")).casefold()

            if node_type not in (
                "",
                "product",
                "offer",
                "apartment",
                "residence",
                "house",
                "realestatelisting",
                "place",
            ):
                continue

            offers_block = node.get("offers")
            offers_block = offers_block if isinstance(offers_block, dict) else {}

            self._set(data, "name", _clean(node.get("name")))
            self._set(data, "description", _clean(node.get("description")))
            self._set(
                data,
                "external_id",
                _clean(node.get("sku") or node.get("productID")),
            )

            self._set(
                data,
                "price",
                _to_int(
                    offers_block.get("price")
                    or offers_block.get("lowPrice")
                    or node.get("price")
                ),
            )
            self._set(
                data,
                "currency",
                _normalize_currency(
                    offers_block.get("priceCurrency")
                    or node.get("priceCurrency")
                ),
            )

            images = node.get("image")
            image_list = (
                images if isinstance(images, list) else [images] if images else []
            )
            self._set(
                data,
                "imgs",
                [
                    image
                    for image in (_clean(item) for item in image_list)
                    if image.startswith("http")
                ],
            )

            address = offers_block.get("availableAtOrFrom")
            address = address.get("address") if isinstance(address, dict) else None
            address = address if isinstance(address, dict) else node.get("address")

            if isinstance(address, dict):
                self._fill_geo(
                    data["geo_label"],
                    region=address.get("addressRegion"),
                    city=address.get("addressLocality"),
                    street=address.get("streetAddress"),
                )

            geo = offers_block.get("availableAtOrFrom")
            geo = geo.get("geo") if isinstance(geo, dict) else None
            geo = geo if isinstance(geo, dict) else node.get("geo")

            if isinstance(geo, dict):
                self._set(data, "latitude", _to_float(geo.get("latitude")))
                self._set(data, "longitude", _to_float(geo.get("longitude")))

            floor_size = node.get("floorSize")

            if isinstance(floor_size, dict):
                self._set(data, "area", _to_float(floor_size.get("value")))
                self._set(
                    data,
                    "area_unit",
                    _normalize_area_unit(
                        floor_size.get("unitCode") or floor_size.get("unitText")
                    ),
                )

            self._set(
                data,
                "rooms_count",
                _to_int_or_none(node.get("numberOfRooms")),
            )

    # --------------------------- Источник: HTML ---------------------------

    def _extract_html_data(
        self,
        soup: BeautifulSoup,
        url: str,
    ) -> dict | None:
        """Резервное извлечение данных из HTML страницы объявления."""
        if not soup.get_text(strip=True):
            return None

        data: dict[str, Any] = {
            "external_id": "",
            "name": "",
            "description": "",
            "price": 0,
            "address": "",
            "imgs": [],
            "breadcrumbs": [],
            "parameters": {},
        }

        title = soup.find("h1")
        if isinstance(title, Tag):
            data["name"] = _clean(title.get_text(" ", strip=True))

        price_element = soup.select_one(
            '[data-testid="offer-price"]'
        ) or soup.select_one('[itemprop="price"]')

        if isinstance(price_element, Tag):
            price_content = price_element.get("content")
            if isinstance(price_content, str) and price_content.strip():
                data["price"] = _to_int(price_content)
            else:
                data["price"] = _to_int(
                    price_element.get_text(" ", strip=True)
                )

        description = soup.select_one(
            '[data-testid="offer-description"]'
        ) or soup.select_one('[itemprop="description"]')

        if isinstance(description, Tag):
            data["description"] = _clean(
                description.get_text(" ", strip=True)
            )

        address = soup.select_one(
            '[data-testid="offer-address"]'
        ) or soup.select_one('[itemprop="address"]')

        if isinstance(address, Tag):
            data["address"] = _clean(address.get_text(" ", strip=True))

        canonical = soup.find("link", attrs={"rel": "canonical"})
        if isinstance(canonical, Tag):
            href = canonical.get("href")
            if isinstance(href, str):
                match = OFFER_ID_RE.search(href)
                if match:
                    data["external_id"] = match.group(1)

        crumbs = soup.select('[data-testid="breadcrumbs"] a')
        data["breadcrumbs"] = [
            _clean(crumb.get_text(" ", strip=True))
            for crumb in crumbs
            if isinstance(crumb, Tag)
        ]

        images: list[str] = []
        for image in soup.find_all("img"):
            if not isinstance(image, Tag):
                continue

            src = image.get("src")
            if not isinstance(src, str) or not src.startswith("http"):
                continue

            host = (urlparse(src).hostname or "").casefold()

            if "yandex" not in host and "realty" not in host and "mds" not in host:
                continue

            images.append(src)

        data["imgs"] = list(dict.fromkeys(images))
        data["parameters"] = self._extract_li_parameters(soup)

        return data

    def _extract_li_parameters(self, soup: BeautifulSoup) -> dict[str, str]:
        """Извлекает пары «название: значение» из списков характеристик."""
        parameters: dict[str, str] = {}

        for li in soup.select("li"):
            if not isinstance(li, Tag):
                continue

            label_element = li.find("span")

            if not isinstance(label_element, Tag):
                continue

            label_text = _clean(
                label_element.get_text(" ", strip=True)
            ).rstrip(":").strip()

            if not label_text:
                continue

            full_text = _clean(li.get_text(" ", strip=True))

            if label_text not in full_text:
                continue

            value = full_text.replace(label_text, "", 1).strip(" :\u00a0")

            if value:
                parameters[label_text] = value

        return parameters

    def _apply_html(self, data: dict, html_data: dict) -> None:
        """Дозаполняет словарь данных значениями из HTML."""
        self._set(data, "external_id", html_data.get("external_id", ""))
        self._set(data, "name", html_data.get("name", ""))
        self._set(data, "description", html_data.get("description", ""))
        self._set(data, "price", html_data.get("price", 0))
        self._set(data, "address", html_data.get("address", ""))
        self._set(data, "imgs", html_data.get("imgs", []))
        self._set(data, "breadcrumbs", html_data.get("breadcrumbs", []))
        self._set(data, "parameters", html_data.get("parameters", {}))

        parameters = html_data.get("parameters", {})

        if not data.get("floor"):
            self._set(
                data,
                "floor",
                _to_int(self._get_parameter(parameters, "Этаж")),
            )

        if not data.get("floors_count"):
            floors_text = self._get_parameter(
                parameters, "Этажей в доме", "Этажность"
            )

            # Значение вида «7 из 12» содержит и этаж, и этажность
            if not floors_text:
                floor_text = self._get_parameter(parameters, "Этаж")
                floors_match = re.search(
                    r"\d+\s*(?:из|/)\s*(\d+)", floor_text
                )
                if floors_match:
                    floors_text = floors_match.group(1)

            self._set(data, "floors_count", _to_int(floors_text))

        if data.get("rooms_count") is None:
            self._set(
                data,
                "rooms_count",
                _to_int_or_none(
                    self._get_parameter(parameters, "Количество комнат", "Комнат")
                ),
            )

        if not data.get("area"):
            self._set(
                data,
                "area",
                _to_float(
                    self._get_parameter(
                        parameters, "Общая площадь", "Площадь"
                    )
                ),
            )

        if not data.get("year_building"):
            self._set(
                data,
                "year_building",
                _to_int(
                    self._get_parameter(parameters, "Год постройки", "Год сдачи")
                ),
            )

    @staticmethod
    def _get_parameter(parameters: dict[str, str], *names: str) -> str:
        """Возвращает значение параметра по одному из названий (null-safe)."""
        normalized = {
            re.sub(r"\s+", " ", key).strip().casefold(): value.strip()
            for key, value in parameters.items()
        }

        for name in names:
            key = re.sub(r"\s+", " ", name).strip().casefold()
            value = normalized.get(key, "")

            if value:
                return value

        return ""

    # --------------------------- Сборка и валидация ---------------------------

    def _build_item(
        self,
        data: dict,
        url: str,
    ) -> YandexSiteParseData | None:
        """Создаёт модель YandexSiteParseData из собранных данных."""
        external_id = _clean(data.get("external_id")) or (
            self._offer_id_from_url(url) or ""
        )

        name = _clean(data.get("name"))
        description = _clean(data.get("description"))
        price = _to_int(data.get("price"))

        # Без названия, описания и цены объявление считать не удалось
        if not name and not description and not price:
            return None

        geo_label = cast(
            geoLabelDict,
            {key: _clean(data["geo_label"].get(key)) for key in GEO_KEYS},
        )

        address = _clean(data.get("address")) or self._join_geo_label(geo_label)

        object_type: ObjectType = "other"
        candidate_type = _clean(data.get("object_type")).casefold()
        if candidate_type in OBJECT_TYPES:
            object_type = cast(ObjectType, candidate_type)

        price = _to_int(data.get("price"))
        area = _to_float(data.get("area"))
        price_per_meter = _to_int(data.get("price_per_meter"))

        if not price_per_meter and price and area:
            price_per_meter = round(price / area)

        imgs = list(data.get("imgs") or [])

        return YandexSiteParseData(
            site="Yandex",
            url=url,
            external_id=external_id,
            name=name,
            subtitles=_clean(data.get("subtitles")),
            description=description,
            offer_article=_clean(data.get("offer_article")),
            category=_clean(data.get("category")),
            object_type=object_type,
            housing_type=_clean(data.get("housing_type")),
            breadcrumbs=list(data.get("breadcrumbs") or []),
            price=price,
            price_per_meter=price_per_meter,
            price_unit=_clean(data.get("price_unit")) or "м²",
            currency=_normalize_currency(data.get("currency")) or "RUB",
            deal_type=_clean(data.get("deal_type")) or "sale",
            deal_conditions=_clean(data.get("deal_conditions")),
            mortgage_possible=data.get("mortgage_possible"),
            sale_method=_clean(data.get("sale_method")),
            area=area,
            area_unit=_clean(data.get("area_unit")) or "м²",
            living_area=_to_float(data.get("living_area")),
            kitchen_area=_to_float(data.get("kitchen_area")),
            rooms_count=data.get("rooms_count"),
            rooms_in_flat=data.get("rooms_in_flat"),
            floor=_to_int(data.get("floor")),
            floors_count=_to_int(data.get("floors_count")),
            ceiling_height=_to_float(data.get("ceiling_height")),
            bathroom=_clean(data.get("bathroom")),
            balcony=_clean(data.get("balcony")),
            window_view=_clean(data.get("window_view")),
            repairs=_clean(data.get("repairs")),
            finishing=_clean(data.get("finishing")),
            year_building=_to_int(data.get("year_building")),
            building_status=_clean(data.get("building_status")),
            building_material=_clean(data.get("building_material")),
            building_type=_clean(data.get("building_type")),
            completion_date=_clean(data.get("completion_date")),
            floors_range=_clean(data.get("floors_range")),
            entrances_count=_to_int(data.get("entrances_count")),
            apartments_count=_to_int(data.get("apartments_count")),
            elevators=list(data.get("elevators") or []),
            parking=_clean(data.get("parking")),
            garbage_chute=data.get("garbage_chute"),
            heating=_clean(data.get("heating")),
            water_supply=_clean(data.get("water_supply")),
            sewerage=_clean(data.get("sewerage")),
            electricity=_clean(data.get("electricity")),
            gas=_clean(data.get("gas")),
            internet=data.get("internet"),
            telephone=data.get("telephone"),
            sauna=data.get("sauna"),
            land_type=_clean(data.get("land_type")),
            land_area=_to_float(data.get("land_area")),
            land_area_unit=_clean(data.get("land_area_unit")),
            garage_type=_clean(data.get("garage_type")),
            commercial_purpose=_clean(data.get("commercial_purpose")),
            entrance_type=_clean(data.get("entrance_type")),
            residential_complex=_clean(data.get("residential_complex")),
            residential_complex_class=_clean(
                data.get("residential_complex_class")
            ),
            residential_complex_completion=_clean(
                data.get("residential_complex_completion")
            ),
            developer=_clean(data.get("developer")),
            developer_foundation_year=_to_int(
                data.get("developer_foundation_year")
            ),
            developer_completed_buildings=_to_int(
                data.get("developer_completed_buildings")
            ),
            developer_buildings_under_construction=_to_int(
                data.get("developer_buildings_under_construction")
            ),
            geo_label=geo_label,
            address=address,
            latitude=_to_float(data.get("latitude")),
            longitude=_to_float(data.get("longitude")),
            nearby_infrastructure=list(
                data.get("nearby_infrastructure") or []
            ),
            seller_name=_clean(data.get("seller_name")),
            seller_type=_clean(data.get("seller_type")),
            agency=_clean(data.get("agency")),
            seller_experience=_clean(data.get("seller_experience")),
            imgs=imgs,
            publish_date=_clean(data.get("publish_date")),
            update_date=_clean(data.get("update_date")),
            views_count=_to_int(data.get("views_count")),
            photos_count=len(imgs),
            badges=list(data.get("badges") or []),
            feature_chips=list(data.get("feature_chips") or []),
            parameters=dict(data.get("parameters") or {}),
        )

    def _validate_item(self, item: YandexSiteParseData) -> bool:
        """
        Проверяет и нормализует значения модели.

        Обязательные поля: url, external_id, name, price > 0. Отрицательные
        значения обрезаются, несоответствия (этаж больше этажности, сумма
        жилой и кухонной площади больше общей) логируются, но объявление
        не отбрасывается.
        """
        problems: list[str] = []

        if not item.url:
            problems.append("url")

        if not item.external_id:
            problems.append("external_id")

        if not item.name:
            problems.append("name")

        if item.price <= 0:
            problems.append("price")

        for field_name in ("area", "living_area", "kitchen_area", "land_area"):
            value = getattr(item, field_name)
            if value < 0:
                logger.warning(
                    "Отрицательное значение %s=%s исправлено (url=%s)",
                    field_name,
                    value,
                    item.url,
                )
                setattr(item, field_name, 0.0)

        if item.rooms_count is not None and item.rooms_count < 0:
            item.rooms_count = None

        if item.floor < 0:
            item.floor = 0

        if item.floors_count < 0:
            item.floors_count = 0

        if item.floors_count and item.floor > item.floors_count:
            logger.warning(
                "Этаж %d больше этажности %d (url=%s)",
                item.floor,
                item.floors_count,
                item.url,
            )

        if item.area and item.living_area + item.kitchen_area > item.area:
            logger.warning(
                "Сумма жилой и кухонной площади больше общей (url=%s)",
                item.url,
            )

        if problems:
            logger.warning(
                "Невалидное объявление %s: отсутствуют/некорректны поля %s",
                item.url,
                ", ".join(problems),
            )
            return False

        return True

    # --------------------------- Вспомогательные методы ---------------------------

    @staticmethod
    def _resolve_delays(parserConfig: ParserConfig) -> tuple[float, float]:
        """Возвращает безопасные задержки между запросами."""
        min_delay = (
            parserConfig.min_iteration_time_span
            if parserConfig.min_iteration_time_span > 0
            else DEFAULT_MIN_DELAY
        )
        max_delay = (
            parserConfig.max_iteration_time_span
            if parserConfig.max_iteration_time_span > 0
            else DEFAULT_MAX_DELAY
        )

        if max_delay < min_delay:
            min_delay, max_delay = max_delay, min_delay

        return min_delay, max_delay

    @staticmethod
    def _city_slug(city_key: str) -> str:
        """Преобразует название города в slug для URL."""
        key = _clean(city_key).casefold()

        if not key:
            return "vladivostok"

        if key in CITY_SLUGS:
            return CITY_SLUGS[key]

        return re.sub(r"\s+", "-", key)

    @staticmethod
    def _offer_id_from_url(url: str) -> str | None:
        """Извлекает идентификатор объявления из URL."""
        match = OFFER_ID_RE.search(urlparse(url).path)

        return match.group(1) if match else None

    @staticmethod
    def _first_dict(*values: Any) -> dict:
        """Возвращает первый непустой словарь из переданных значений."""
        for value in values:
            if isinstance(value, dict) and value:
                return value

        return {}

    @staticmethod
    def _object_type_from_category(category: str, url: str) -> str:
        """Определяет тип объекта по категории объявления и URL."""
        normalized = re.sub(r"[\s_\-]", "", category).casefold()
        object_type = YANDEX_CATEGORY_OBJECT_TYPES.get(normalized)

        if object_type:
            return object_type

        path = urlparse(url).path.casefold()

        if "kommercheskaya" in path:
            return "other"
        if "uchastok" in path:
            return "land_plot"
        if "garazh" in path:
            return "garage"
        if "/dom" in path:
            return "house"
        if "komnat" in path or "room" in path:
            return "room"

        return "flat"

    @staticmethod
    def _housing_type_from_state(
        offer: dict,
        building: dict,
        category: str,
    ) -> str:
        """Определяет тип жилья (новостройка/вторичка) по данным Яндекса."""
        is_new = _deep_find_flag(
            offer, ("isNewBuilding", "isNew", "newBuildingFlag")
        )

        # Явный булев признак в блоке дома имеет приоритет над наличием
        # блока newBuilding (он может присутствовать и у вторички)
        if is_new is None and isinstance(building.get("newBuilding"), bool):
            is_new = building["newBuilding"]

        if is_new is None:
            new_building = offer.get("newBuilding")
            if isinstance(new_building, dict) and new_building:
                is_new = True

        if is_new is None and category in ("NEWBUILDING", "NEW_BUILDING"):
            is_new = True

        if is_new is True:
            return "новостройка"

        if is_new is False:
            return "вторичка"

        if category in ("APARTMENT", "FLAT", "ROOMS", "ROOM"):
            return "вторичка"

        return ""

    @staticmethod
    def _extract_measure(
        node: Any,
        keys: tuple[str, ...],
    ) -> tuple[float, str]:
        """
        Извлекает числовое значение и единицу измерения.

        Яндекс может отдавать как число, так и блок
        ``{"value": 46.7, "unit": "SQM"}``.
        """
        value = _deep_find(node, keys)
        unit = ""

        if isinstance(value, dict):
            unit = _clean(value.get("unit") or value.get("unitCode"))
            value = value.get("value")

        return _to_float(value), unit

    @staticmethod
    def _balcony_to_string(value: Any) -> str:
        """Преобразует блок балконов/лоджий в читаемую строку."""
        if value is None:
            return ""

        items = value if isinstance(value, list) else [value]
        labels: list[str] = []

        for item in items:
            if isinstance(item, dict):
                item = (
                    item.get("type")
                    or item.get("name")
                    or item.get("value")
                )

            label = _label_from_map(item, BALCONY_LABELS)

            if label and label not in labels:
                labels.append(label)

        return ", ".join(labels)

    @staticmethod
    def _format_elevators(value: Any) -> list[str]:
        """Преобразует блок лифтов в список читаемых строк."""
        if value is None:
            return []

        items = value if isinstance(value, list) else [value]
        result: list[str] = []

        for item in items:
            if isinstance(item, dict):
                label = _label_from_map(
                    item.get("type") or item.get("name"),
                    ELEVATOR_TYPE_LABELS,
                )
                count = _to_int(item.get("count"))

                if label and count:
                    result.append(f"{label} ({count})")
                elif label:
                    result.append(label)
            else:
                cleaned = _clean(item)
                if cleaned:
                    result.append(cleaned)

        return result

    @staticmethod
    def _as_str_list(value: Any) -> list[str]:
        """Преобразует произвольное значение в список непустых строк."""
        if value is None:
            return []

        items = value if isinstance(value, list) else [value]
        result = [_clean(item) for item in items]

        return [item for item in result if item]

    @classmethod
    def _features_to_list(cls, value: Any) -> list[str]:
        """Преобразует блок характеристик в список строк."""
        if value is None:
            return []

        if isinstance(value, dict):
            return [
                f"{_clean(key)}: {_clean(item)}" if _clean(item) else _clean(key)
                for key, item in value.items()
                if _clean(key)
            ]

        return cls._as_str_list(value)

    @staticmethod
    def _features_to_parameters(value: Any) -> dict[str, str]:
        """Преобразует блок характеристик в словарь «название -> значение»."""
        if not isinstance(value, dict):
            return {}

        return {
            _clean(key): _clean(item)
            for key, item in value.items()
            if _clean(key) and _clean(item)
        }

    @staticmethod
    def _breadcrumbs_to_list(value: Any) -> list[str]:
        """Преобразует хлебные крошки Яндекса в список строк."""
        if value is None:
            return []

        items = value if isinstance(value, list) else [value]
        result: list[str] = []

        for item in items:
            text = _clean(item)

            if text and text not in result:
                result.append(text)

        return result

    @staticmethod
    def _article_from_text(text: str) -> str:
        """Извлекает артикул объявления из текста описания."""
        match = re.search(
            r"(?:артикул|арт\.)\s*[:№]?\s*([A-Za-zА-Яа-я0-9\-/]+)",
            text,
            re.IGNORECASE,
        )

        return match.group(1) if match else ""

    @staticmethod
    def _fill_geo(geo_label: dict, **values: Any) -> None:
        """Дозаполняет пустые поля географии (первое значение побеждает)."""
        for key in GEO_KEYS:
            if key not in values or geo_label.get(key):
                continue

            value = _clean(values.get(key))

            if value:
                geo_label[key] = value

    @staticmethod
    def _join_geo_label(geo_label: geoLabelDict) -> str:
        """Собирает адрес одной строкой из заполненных полей географии."""
        parts = [geo_label.get(key, "") for key in GEO_KEYS]

        return ", ".join(part for part in parts if part)

    @staticmethod
    def _empty_data() -> dict:
        """Словарь данных объявления с пустыми значениями."""
        return {
            "external_id": "",
            "name": "",
            "subtitles": "",
            "description": "",
            "offer_article": "",
            "category": "",
            "object_type": "",
            "housing_type": "",
            "breadcrumbs": [],
            "price": 0,
            "price_per_meter": 0,
            "price_unit": "м²",
            "currency": "",
            "deal_type": "",
            "deal_conditions": "",
            "mortgage_possible": None,
            "sale_method": "",
            "area": 0.0,
            "area_unit": "",
            "living_area": 0.0,
            "kitchen_area": 0.0,
            "rooms_count": None,
            "rooms_in_flat": None,
            "floor": 0,
            "floors_count": 0,
            "ceiling_height": 0.0,
            "bathroom": "",
            "balcony": "",
            "window_view": "",
            "repairs": "",
            "finishing": "",
            "year_building": 0,
            "building_status": "",
            "building_material": "",
            "building_type": "",
            "completion_date": "",
            "floors_range": "",
            "entrances_count": 0,
            "apartments_count": 0,
            "elevators": [],
            "parking": "",
            "garbage_chute": None,
            "heating": "",
            "water_supply": "",
            "sewerage": "",
            "electricity": "",
            "gas": "",
            "internet": None,
            "telephone": None,
            "sauna": None,
            "land_type": "",
            "land_area": 0.0,
            "land_area_unit": "",
            "garage_type": "",
            "commercial_purpose": "",
            "entrance_type": "",
            "residential_complex": "",
            "residential_complex_class": "",
            "residential_complex_completion": "",
            "developer": "",
            "developer_foundation_year": 0,
            "developer_completed_buildings": 0,
            "developer_buildings_under_construction": 0,
            "geo_label": {key: "" for key in GEO_KEYS},
            "address": "",
            "latitude": 0.0,
            "longitude": 0.0,
            "nearby_infrastructure": [],
            "seller_name": "",
            "seller_type": "",
            "agency": "",
            "seller_experience": "",
            "imgs": [],
            "publish_date": "",
            "update_date": "",
            "views_count": 0,
            "photos_count": 0,
            "badges": [],
            "feature_chips": [],
            "parameters": {},
        }

    @staticmethod
    def _set(data: dict, key: str, value: Any) -> None:
        """
        Заполняет поле, если оно ещё пустое (первый источник побеждает).

        Для булевых полей False считается значимым значением.
        """
        bool_fields = {
            "mortgage_possible",
            "garbage_chute",
            "internet",
            "telephone",
            "sauna",
        }

        if key in bool_fields:
            if data.get(key) is None and value is not None:
                data[key] = bool(value)
            return

        if data.get(key) not in (None, "", 0, 0.0, [], {}):
            return

        if value in (None, "", 0, 0.0, [], {}):
            return

        data[key] = value
