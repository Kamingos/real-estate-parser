"""
Парсер объявлений CIAN (на Selenium, в стиле Avito-парсера).

Схема работы (после обновления модели данных сайта):
1. Парсер постранично обходит список объявлений и собирает ТОЛЬКО ссылки
   на страницы объявлений (данные из карточек больше не используются).
2. Затем для каждой ссылки открывается страница объявления в браузере
   и из неё извлекаются все поля модели CianSiteParseData.

Приоритет источников данных на странице объявления:
- JSON состояния объявления, встраиваемый CIAN в страницу:
  текущий формат — блок ``"offerData"`` в конфиге микрофронтенда
  ``frontend-offer-card``; резервный формат — ``window._offerJson``;
- HTML-разметка страницы — резервный вариант, если JSON недоступен.

Ошибки сети, отсутствующие поля и некорректный HTML не останавливают
процесс: проблемное объявление пропускается с записью в лог.
"""

import json
import logging
import re
from random import uniform
from time import sleep
from typing import Any
from urllib.parse import urljoin, urlunparse, urlparse

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
from model.site_parse_data_model import CianSiteParseData, geoLabelDict

# ------------------------------------------------------------------------------
# Настройки логирования
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("cian_parser")

# Время ожидания загрузки страницы (секунды)
PAGE_WAIT_TIME = 10

# Задержки между запросами по умолчанию (используются, если в ParserConfig
# интервалы заданы нулевыми). Нужны, чтобы не попасть под блокировку.
DEFAULT_MIN_DELAY = 1.0
DEFAULT_MAX_DELAY = 3.0

# Маркер JSON-состояния объявления в старой версии страницы CIAN
OFFER_JSON_MARKER = "window._offerJson"

# Маркер JSON-состояния объявления в текущей версии страницы: конфиг
# микрофронтенда frontend-offer-card содержит блок
# ``"offerData": {"offer": {...}, "agent": {...}, "stats": {...}, ...}``
OFFER_DATA_MARKER_RE = re.compile(r'"offerData"\s*:\s*')

# Шаблон URL объявления: https://<город>.cian.ru/sale/flat/<id>/
OFFER_ID_RE = re.compile(r"/sale/flat/(\d{6,})/?$")
OFFER_URL_RE = re.compile(r"/sale/flat/\d{6,}/?$")

# Подписи для кодов типа санузла (offer.bathroomUnit)
BATHROOM_LABELS = {
    "separate": "раздельный",
    "combined": "совмещённый",
    "two": "два и более",
}

# Подписи для кодов вида из окон (offer.viewFromWindows)
WINDOW_VIEW_LABELS = {
    "yard": "во двор",
    "street": "на улицу",
    "yardandstreet": "во двор и на улицу",
    "park": "на парк",
    "water": "на воду",
    "unknown": "",
}

# Подписи для кодов типов лифтов (building.elevators)
ELEVATOR_TYPE_LABELS = {
    "pass": "пассажирский",
    "passenger": "пассажирский",
    "cargo": "грузовой",
    "cargoandpass": "грузопассажирский",
    "service": "служебный",
}


# ==============================================================================
# Вспомогательные функции
# ==============================================================================

def _clean(value: Any) -> str:
    """Приводит значение к чистой строке (без лишних пробелов/переносов)."""
    if value is None:
        return ""
    if isinstance(value, dict):
        # Словарь CIAN (например {"id": 10934687, "name": "Корпус 14"})
        # разворачиваем в осмысленную строку, а не в repr(dict)
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

    digits = re.sub(r"[\s\u00a0]", "", str(value))
    match = re.search(r"-?\d+", digits)

    return int(match.group()) if match else 0


def _to_float(value: Any) -> float:
    """Безопасное преобразование значения в float (0.0 при неудаче)."""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)

    match = re.search(r"(\d+(?:[.,]\d+)?)", str(value).replace(" ", ""))

    return float(match.group(1).replace(",", ".")) if match else 0.0


def _deep_find(data: Any, keys: tuple[str, ...]) -> Any:
    """
    Ищет по всем вложенным словарям/спискам первое непустое значение,
    ключ которого совпадает (без учёта регистра) с одним из ``keys``.
    Позволяет не зависеть от точной структуры JSON CIAN.
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
    Как _deep_find, но предназначена для булевых полей: возвращает False,
    если ключ найден со значением False (в т.ч. строкой "false").
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
    Определяет страницу капчи/блокировки.

    ВАЖНО: нельзя проверять голую подстроку "captcha" по всему HTML —
    на обычных страницах CIAN слово "captcha" встречается в служебных
    скриптах (подключение SmartCaptcha и т.п.), что даёт ложные
    срабатывания. Проверяем только однозначные признаки.
    """
    # 1. Браузер редиректнуло на страницу капчи
    lowered_url = current_url.casefold()
    if "captcha" in urlparse(lowered_url).netloc or "/captcha" in lowered_url:
        return True

    lowered = html.casefold()

    # 2. Точные тексты заглушки CIAN
    text_markers = (
        "подтвердите, что запросы отправляли вы",
        "доступ ограничен: проблема с ip",
        "доступ ограничен: проблема с браузером",
        "проверка браузера перед открытием сайта",
    )
    if any(marker in lowered for marker in text_markers):
        return True

    # 3. Реальный iframe/виджет капчи в DOM (не упоминание в скриптах)
    if re.search(
        r"<iframe[^>]*(?:smartcaptcha\.yandexcloud\.net|captcha)",
        lowered,
    ):
        return True
    if re.search(
        r'<div[^>]*data-name="[^"]*captcha[^"]*"', lowered
    ):
        return True

    return False


# ==============================================================================
# Парсер
# ==============================================================================

class CianParser(IParcer):
    """Парсер CIAN: список объявлений -> страницы объявлений -> модель данных."""

    def __init__(self) -> None:
        # Шаблон URL поисковой выдачи (список объявлений)
        self.url = (
            "https://cian.ru/cat.php?deal_type=sale&engine_version=2"
            "&location%5B0%5D={city_id}&offer_type=flat"
            "&region={city_id}&p={page}&source=search_string"
        )

        # Настройки браузера (как в Avito-парсере)
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

        # Для запуска без окна браузера можно раскомментировать:
        # self.options.add_argument("--headless=new")

    # --------------------------------------------------------------------------
    # Публичный интерфейс
    # --------------------------------------------------------------------------

    def parse(
        self,
        parserConfig: ParserConfig,
    ) -> tuple[bool, list[CianSiteParseData] | None]:

        driver = webdriver.Chrome(options=self.options)
        driver.set_page_load_timeout(PAGE_WAIT_TIME)

        # Скрываем признак автоматизации (navigator.webdriver) на каждой странице
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

        offers: list[CianSiteParseData] = []
        seen_urls: set[str] = set()

        # Задержки из конфигурации; нулевые заменяем на безопасные значения
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

        try:
            # ------------------------------------------------------------------
            # Этап 1: обходим списки объявлений и собираем ссылки
            # ------------------------------------------------------------------
            pending_urls: list[str] = []

            for city_key, city_id in parserConfig.cities.items():
                city_urls = self._collect_offer_urls(
                    driver=driver,
                    city_key=city_key,
                    city_id=city_id,
                    max_pages=parserConfig.max_page_iteration,
                    min_delay=min_delay,
                    max_delay=max_delay,
                )

                for url in city_urls:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        pending_urls.append(url)

            logger.info("Собрано уникальных ссылок на объявления: %d", len(pending_urls))

            # ------------------------------------------------------------------
            # Этап 2: открываем страницу каждого объявления и парсим данные
            # ------------------------------------------------------------------
            for index, offer_url in enumerate(pending_urls, start=1):
                logger.info("Объявление %d/%d: %s", index, len(pending_urls), offer_url)

                item = self._parse_offer_page(driver, offer_url)

                if item is None:
                    # Проблемное объявление пропускаем, процесс не останавливаем
                    logger.warning("Пропущено объявление: %s", offer_url)
                else:
                    offers.append(item)

                # Задержка между запросами, чтобы не попасть под блокировку
                sleep(uniform(min_delay, max_delay))

        finally:
            driver.quit()

        logger.info("Итого собрано объявлений: %d", len(offers))

        return True, offers

    # --------------------------------------------------------------------------
    # Этап 1: сбор ссылок из списка объявлений
    # --------------------------------------------------------------------------

    def _collect_offer_urls(
        self,
        driver: webdriver.Chrome,
        city_key: str,
        city_id: int,
        max_pages: int,
        min_delay: float,
        max_delay: float,
    ) -> list[str]:
        """Обходит постранично выдачу и возвращает список URL объявлений."""
        urls: list[str] = []

        page = 1

        while page <= max_pages:
            page_url = self.url.format(city_id=city_id, page=page)

            success, page_urls = self._parse_listing_page(
                driver,
                page_url,
                city_key=city_key,
                page=page,
            )

            if not success:
                print(
                    f"[-] Cian: не удалось загрузить страницу списка "
                    f"город={city_key}, страница={page}"
                )

                # Интерактивный повтор, как в Avito-парсере:
                # пользователь решает капчу в открывшемся браузере
                answer = input(
                    "Исправьте проблему в браузере и нажмите Enter "
                    "для повтора. Введите 'n' для пропуска: "
                ).strip().lower()

                if answer == "n":
                    break

                # Повторяем ту же страницу
                continue

            logger.info(
                "Список %s, стр. %d: найдено %d объявлений",
                city_key,
                page,
                len(page_urls),
            )

            # Пустая страница означает конец выдачи
            if not page_urls:
                break

            urls.extend(page_urls)
            page += 1

            # Пауза между страницами списка
            sleep(uniform(min_delay, max_delay))

        return urls

    def _parse_listing_page(
        self,
        driver: webdriver.Chrome,
        page_url: str,
        city_key: str,
        page: int,
    ) -> tuple[bool, list[str]]:
        """Открывает страницу списка и извлекает ссылки на объявления."""
        try:
            driver.get(page_url)

            WebDriverWait(driver, PAGE_WAIT_TIME).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'article[data-name="CardComponent"]')
                )
            )

        except (TimeoutException, WebDriverException) as error:
            logger.warning(
                "Ошибка загрузки списка (город=%s, стр. %d): %s",
                city_key,
                page,
                error,
            )
            return False, []

        try:
            soup = BeautifulSoup(driver.page_source, "lxml")
            return True, self._extract_offer_urls(soup, page_url)

        except Exception as error:  # некорректный HTML
            logger.error(
                "Ошибка разбора HTML списка (город=%s, стр. %d): %s",
                city_key,
                page,
                error,
            )
            return False, []

    def _extract_offer_urls(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        """Извлекает ссылки на объявления из HTML страницы списка."""
        urls: list[str] = []
        seen: set[str] = set()

        # Ссылки ищем только внутри карточек объявлений
        cards = soup.find_all("article", attrs={"data-name": "CardComponent"})

        for card in cards:
            if not isinstance(card, Tag):
                continue

            # Приоритет: заголовок карточки, затем любая ссылка в карточке
            link = card.find("a", attrs={"data-name": "TitleComponent"})
            if not isinstance(link, Tag):
                link = card.find("a", href=True)

            if not isinstance(link, Tag):
                continue

            href = link.get("href")
            if not isinstance(href, str) or not href.strip():
                continue

            url = self._canonical_offer_url(href)

            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        return urls

    def _canonical_offer_url(self, href: str) -> str | None:
        """Нормализует ссылку на объявление (только схема/домен/путь)."""
        url = urljoin("https://cian.ru", href.strip())
        parsed = urlparse(url)

        # Отбираем только ссылки на страницы продажи квартир
        if not OFFER_URL_RE.search(parsed.path):
            return None

        return urlunparse(
            (parsed.scheme or "https", parsed.netloc, parsed.path, "", "", "")
        )

    # --------------------------------------------------------------------------
    # Этап 2: парсинг страницы объявления
    # --------------------------------------------------------------------------

    def _parse_offer_page(
        self,
        driver: webdriver.Chrome,
        url: str,
    ) -> CianSiteParseData | None:
        """Открывает страницу объявления и собирает все поля модели."""
        try:
            driver.get(url)
        except TimeoutException:
            # Продолжаем работу с уже полученным DOM
            try:
                driver.execute_script("window.stop();")
            except WebDriverException:
                pass
        except WebDriverException as error:
            logger.warning("Ошибка загрузки объявления %s: %s", url, error)
            return None

        # Ждём появления содержимого объявления (описание или заголовок),
        # но не полной загрузки всех ресурсов
        try:
            WebDriverWait(driver, PAGE_WAIT_TIME).until(
                EC.presence_of_element_located(
                    (
                        By.CSS_SELECTOR,
                        'div[data-name="Description"], h1[data-mark="OfferTitle"], h1',
                    )
                )
            )
        except TimeoutException:
            pass

        html = driver.page_source

        if _looks_like_captcha(html, driver.current_url):
            html = self._handle_captcha(driver, url)

            if html is None:
                return None

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception as error:  # некорректный HTML
            logger.error("Ошибка разбора HTML %s: %s", url, error)
            return None

        # ------------------------------------------------------------------
        # 1. Основной источник — встроенный JSON объявления
        # ------------------------------------------------------------------
        raw_json = self._extract_offer_json(html)

        if raw_json is not None:
            try:
                item = self._build_item_from_json(raw_json, url)
            except Exception as error:
                logger.error("Ошибка разбора JSON объявления %s: %s", url, error)
                item = None
        else:
            item = None

        # ------------------------------------------------------------------
        # 2. Резервный источник — HTML-разметка страницы
        # ------------------------------------------------------------------
        try:
            html_data = self._extract_html_data(soup, url)
        except Exception as error:
            logger.error("Ошибка разбора HTML объявления %s: %s", url, error)
            html_data = None

        if item is None:
            if html_data is None:
                return None

            # Собираем объект только из HTML-данных
            item = CianSiteParseData(site="Cian", url=url)
            item.name = html_data["name"]
            item.subtitles = html_data["subtitles"]
            item.description = html_data["description"]
            item.price = html_data["price"]
            item.imgs = html_data["imgs"]
            item.geo_label = html_data["geo_label"]
            item.address = html_data["address"]

        elif html_data is not None:
            # Заполняем HTML-данными поля, отсутствующие в JSON
            self._fill_missing_from_html(item, html_data)

        return item

    # --------------------------- Обработка капчи ---------------------------

    def _handle_captcha(
        self,
        driver: webdriver.Chrome,
        url: str,
        max_attempts: int = 3,
    ) -> str | None:
        """
        Обрабатывает настоящую капчу на странице объявления.

        Программа останавливается и ждёт, пока пользователь решит капчу
        в открытом браузере, после чего нужно нажать Enter в консоли.
        Делается до ``max_attempts`` таких попыток. Один раз сохраняет
        HTML страницы в captcha_debug.html для последующего анализа.
        Возвращает актуальный HTML или None (если все попытки исчерпаны).
        """
        debug_saved = False

        for attempt in range(1, max_attempts + 1):
            logger.warning(
                "Капча на странице объявления (попытка %d/%d): %s",
                attempt,
                max_attempts,
                url,
            )

            if not debug_saved:
                try:
                    with open("captcha_debug.html", "w", encoding="utf-8") as file:
                        file.write(driver.page_source)
                    debug_saved = True
                    logger.info("HTML с капчей сохранён в captcha_debug.html")
                except OSError as error:
                    logger.error("Не удалось сохранить отладочный HTML: %s", error)
                    debug_saved = True  # больше не пытаемся

            # Останавливаемся и ждём, пока пользователь решит капчу вручную
            try:
                answer = input(
                    f"\n[CAPTCHA] Решите капчу в открывшемся браузере "
                    f"(попытка {attempt}/{max_attempts}),\n"
                    "затем нажмите Enter здесь в консоли для продолжения "
                    "(введите 'n' — пропустить объявление): "
                ).strip().lower()
            except EOFError:
                # Неинтерактивный режим консоли: просто пробуем перезагрузку
                answer = ""

            if answer == "n":
                logger.warning("Капча пропущена пользователем: %s", url)
                return None

            # Если пользователь не закрыл вкладку — пробуем перезагрузить страницу.
            # Если он уже решил капчу и страница сама загрузилась,
            # перезагрузка не помешает: просто откроем объявление заново.
            try:
                driver.get(url)
            except TimeoutException:
                try:
                    driver.execute_script("window.stop();")
                except WebDriverException:
                    pass
            except WebDriverException as error:
                logger.warning("Ошибка загрузки объявления %s: %s", url, error)
                return None

            try:
                WebDriverWait(driver, PAGE_WAIT_TIME).until(
                    EC.presence_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            'div[data-name="Description"], h1[data-mark="OfferTitle"], h1',
                        )
                    )
                )
            except TimeoutException:
                pass

            html = driver.page_source

            if not _looks_like_captcha(html, driver.current_url):
                logger.info("Капча пройдена, продолжаем: %s", url)
                return html

            logger.warning("Капча всё ещё отображается после попытки %d", attempt)

        logger.warning("Капча не пройдена за %d попыток: %s", max_attempts, url)
        return None

    # --------------------------- Источник: JSON ---------------------------

    def _extract_offer_json(self, html: str) -> dict | None:
        """
        Извлекает состояние объявления из HTML страницы.

        Текущий формат (микрофронтенд frontend-offer-card): в конфиге
        ``window._cianConfig['frontend-offer-card']`` лежит блок
        ``"offerData": {"offer": {...}, "agent": {...}, "stats": {...}, ...}``.

        Резервный формат (старая версия страницы):
        ``window._offerJson = {...};``.
        """
        # 1. Текущий формат: блок "offerData"
        for marker_match in OFFER_DATA_MARKER_RE.finditer(html):
            start = marker_match.end()

            if start >= len(html) or html[start] != "{":
                continue

            try:
                # raw_decode читает ровно один JSON-объект и игнорирует хвост
                decoded, _ = json.JSONDecoder().raw_decode(html[start:])
            except ValueError:
                continue

            if isinstance(decoded, dict) and isinstance(decoded.get("offer"), dict):
                return decoded

        # 2. Резервный формат: window._offerJson
        marker_pos = html.find(OFFER_JSON_MARKER)

        if marker_pos == -1:
            logger.info("JSON объявления не найден (offerData/_offerJson)")
            return None

        start = html.find("{", marker_pos)

        if start == -1:
            return None

        try:
            decoded, _ = json.JSONDecoder().raw_decode(html[start:])
        except ValueError as error:
            logger.error("Некорректный JSON объявления: %s", error)
            return None

        if not isinstance(decoded, dict):
            return None

        if isinstance(decoded.get("offer"), dict):
            return decoded

        return {"offer": decoded}

    def _build_item_from_json(self, state: dict, url: str) -> CianSiteParseData:
        """Заполняет модель CianSiteParseData данными из JSON объявления."""
        offer = state.get("offer")
        if not isinstance(offer, dict):
            offer = state
        bargain = offer.get("bargainTerms") or {}
        building = offer.get("building") or {}
        newbuilding = offer.get("newbuilding") or {}
        new_object = state.get("newObject")
        if not isinstance(new_object, dict):
            new_object = {}
        geo = offer.get("geo") or {}

        # --- Основная информация -------------------------------------------
        external_id_match = OFFER_ID_RE.search(url)
        external_id = external_id_match.group(1) if external_id_match else ""

        name = _clean(_deep_find(offer, ("fullTitle", "offerTitle", "title")))
        subtitles = _clean(
            _deep_find(offer, ("shortLocationName", "annotation", "subtitle"))
        )
        description = _clean(offer.get("description"))

        # Тип объекта: студия или обычная квартира
        flat_type = _clean(
            _deep_find(offer, ("flatType", "objectType", "propertyType"))
        ).casefold()
        object_type = (
            "studio"
            if "studio" in flat_type or "студи" in name.casefold()
            else "flat"
        )

        # Тип жилья: новостройка / вторичка
        is_primary = _deep_find_flag(offer, ("isPrimary", "isNewFlat", "newFlat"))
        if is_primary is None:
            # В новом формате признак новостройки берём из категории объявления
            # (например, "newBuildingFlatSale")
            category = _clean(offer.get("category")).casefold()
            if "newbuilding" in category or "new" in category:
                is_primary = True
            elif category:
                is_primary = False

        if is_primary is True:
            housing_type = "новостройка"
        elif is_primary is False:
            housing_type = "вторичка"
        else:
            housing_type = ""

        # --- Цена и условия сделки ------------------------------------------
        price = _to_int(bargain.get("price"))
        currency_raw = _clean(bargain.get("currency")).casefold()
        currency = "RUB" if currency_raw in ("", "rur", "rub") else currency_raw.upper()

        area = _to_float(_deep_find(offer, ("totalArea",)))
        price_per_meter_raw = _to_int(_deep_find(offer, ("pricePerMeter",)))
        if price_per_meter_raw == 0 and price and area:
            price_per_meter_raw = round(price / area)

        deal_conditions = _clean(
            [
                bargain.get("saleType"),
                bargain.get("paymentPeriod"),
            ]
        )
        mortgage_possible = _deep_find_flag(
            offer, ("mortgageAllowed", "mortgagePossible", "isMortgageAllowed")
        )
        if mortgage_possible is None:
            # В новом формате признак ипотеки лежит в блоке bargainTerms
            mortgage_possible = _deep_find_flag(
                bargain, ("mortgageAllowed", "mortgagePossible")
            )

        # --- Основные характеристики -----------------------------------------
        rooms_count_raw = offer.get("roomsCount")
        rooms_count: int | None = (
            _to_int(rooms_count_raw) if rooms_count_raw is not None else None
        )
        if object_type == "studio":
            rooms_count = None  # у студии комнат нет

        # Резерв: если roomsCount в JSON отсутствует (или пуст), пробуем
        # вытащить количество комнат из заголовка («1-комн. квартира»)
        if rooms_count is None and object_type != "studio":
            rooms_match = re.search(r"(\d)\s*-?\s*комн", name, re.IGNORECASE)
            if rooms_match:
                rooms_count = int(rooms_match.group(1))

        living_area = _to_float(_deep_find(offer, ("livingArea", "roomArea")))
        kitchen_area = _to_float(_deep_find(offer, ("kitchenArea",)))
        floor = _to_int(_deep_find(offer, ("floorNumber", "floor")))
        floors_count = _to_int(
            _deep_find(offer, ("floorsCount",))
            or building.get("floorsCount")
        )
        ceiling_height = _to_float(_deep_find(offer, ("ceilingHeight",)))

        # Санузел: в новом формате — код offer.bathroomUnit
        bathroom_raw = _deep_find(offer, ("bathroomUnit", "bathroomType", "bathroom"))
        bathroom_code = _clean(bathroom_raw).casefold()
        bathroom = BATHROOM_LABELS.get(bathroom_code, _clean(bathroom_raw))

        # Балкон/лоджия: в новом формате — счётчики balconiesCount/loggiasCount,
        # в старом — строковое значение
        balconies_count = _to_int(offer.get("balconiesCount"))
        loggias_count = _to_int(offer.get("loggiasCount"))
        if balconies_count or loggias_count:
            balcony = " + ".join(
                part
                for part, count in (
                    ("балкон", balconies_count),
                    ("лоджия", loggias_count),
                )
                if count
            )
        else:
            balcony = _clean(
                _deep_find(offer, ("balconiesType", "balconyType", "balcony"))
            )

        # Вид из окон: в новом формате — список кодов offer.viewFromWindows
        view_raw = offer.get("viewFromWindows")
        if view_raw is None:
            view_raw = _deep_find(offer, ("windowsViewType", "windowView"))
        if isinstance(view_raw, list):
            view_labels = [
                WINDOW_VIEW_LABELS.get(_clean(item).casefold(), _clean(item))
                for item in view_raw
            ]
            window_view = ", ".join(label for label in view_labels if label)
        else:
            view_code = _clean(view_raw).casefold()
            window_view = WINDOW_VIEW_LABELS.get(view_code, _clean(view_raw))

        # --- Состояние и отделка ---------------------------------------------
        # В новом формате отделка приходит кодом в поле decoration
        # (without / preFine / fine / design)
        decoration_labels = {
            "without": "без ремонта",
            "prefine": "предчистовая",
            "fine": "чистовая",
            "design": "дизайнерский",
        }
        decoration_raw = _clean(
            _deep_find(offer, ("decoration", "finishingType", "finishing"))
        ).casefold()
        decoration = decoration_labels.get(decoration_raw, decoration_raw)

        repairs = _clean(_deep_find(offer, ("repairs", "renovation"))) or decoration
        finishing = decoration
        furniture = _clean(_deep_find(offer, ("furniture",)))
        sell_with_furniture = (
            ("without" not in furniture.casefold())
            if furniture
            else None
        )

        # --- Информация о доме -------------------------------------------------
        year_building = _to_int(_deep_find(offer, ("buildYear", "builtYear")))
        building_material = _clean(
            _deep_find(building, ("materialType", "wallMaterial", "buildingMaterial"))
        )
        entrances_count = _to_int(
            _deep_find(building, ("entrancesCount", "porchesCount"))
        )
        elevators = self._format_elevators(
            _deep_find(building, ("elevator", "elevators"))
        )
        parking_raw = _deep_find(building, ("parkingType", "parking", "parkingInfo"))
        if isinstance(parking_raw, dict):
            # Новый формат: {"type": "underground"}
            parking_raw = parking_raw.get("type")
        parking = _clean(parking_raw)
        heating = _clean(_deep_find(building, ("heatingType", "heating")))
        ramp = _deep_find_flag(building, ("ramp",))
        concierge = _deep_find_flag(building, ("concierge",))
        barrier = _deep_find_flag(building, ("barrier",))
        emergency = _deep_find_flag(offer, ("emergency", "isEmergency"))

        # --- Информация о жилом комплексе --------------------------------------
        residential_complex = _clean(
            newbuilding.get("name")
            or new_object.get("name")
            or _deep_find(offer, ("residentialComplex",))
        )

        developer_raw = new_object.get("developer")
        developer = _clean(
            developer_raw.get("name")
            if isinstance(developer_raw, dict)
            else developer_raw
        ) or _clean(newbuilding.get("developerName")) or _clean(
            _deep_find(newbuilding, ("developerName", "builderName"))
        ) or _clean(_deep_find(offer, ("developerName", "builderName")))

        # Класс ЖК: "comfort" / {"label": "..."} и т.п.
        class_raw = new_object.get("newbuildingClass")
        residential_complex_class = _clean(
            (class_raw.get("label") or class_raw.get("name"))
            if isinstance(class_raw, dict)
            else class_raw
        ) or _clean(_deep_find(building, ("classType", "buildingClass", "objectClass")))

        # Срок сдачи: finishDate из newbuilding.house либо deadline из building
        residential_complex_completion = ""
        house_info = newbuilding.get("house")
        if isinstance(house_info, dict):
            finish_date = house_info.get("finishDate")
            if isinstance(finish_date, dict):
                quarter = finish_date.get("quarter")
                year = finish_date.get("year")
                if quarter and year:
                    residential_complex_completion = f"{quarter} квартал {year} г."
                elif year:
                    residential_complex_completion = f"{year} г."
        if not residential_complex_completion:
            deadline_raw = building.get("deadline")
            if isinstance(deadline_raw, dict):
                quarter_names = {"first": 1, "second": 2, "third": 3, "fourth": 4}
                quarter = quarter_names.get(_clean(deadline_raw.get("quarter")).lower())
                year = deadline_raw.get("year")
                if year:
                    prefix = f"{quarter} квартал " if quarter else ""
                    residential_complex_completion = f"{prefix}{year} г."
            else:
                residential_complex_completion = _clean(deadline_raw)

        residential_complex_parking = self._as_str_list(
            _deep_find(newbuilding, ("parkingType", "parking"))
        )
        residential_complex_finishing = self._as_str_list(
            _deep_find(newbuilding, ("finishingType", "finishing"))
        )

        # --- География -----------------------------------------------------------
        geo_label = self._extract_geo_from_json(geo)
        address = _clean(geo.get("userNote")) or self._join_geo_label(geo_label)

        # --- Инфраструктура --------------------------------------------------------
        nearby_infrastructure = self._as_str_list(
            _deep_find(offer, ("nearbyInfrastructure", "infrastructure"))
        )

        # --- Юридическая информация ---------------------------------------------
        cadastral_number = _clean(_deep_find(offer, ("cadastralNumber",)))
        encumbrances = _clean(_deep_find(offer, ("encumbrance", "encumbrances")))
        minors_owners = _deep_find_flag(offer, ("minorsOwners", "hasMinorsOwners"))
        maternity_capital_used = _deep_find_flag(
            offer, ("maternityCapital", "maternityCapitalUsed")
        )

        # --- Продавец ---------------------------------------------------------------
        # В новом формате продавец лежит рядом с offer (state.agent / state.user)
        agent = (
            state.get("agent")
            or state.get("user")
            or offer.get("agentInfo")
            or offer.get("user")
            or {}
        )
        if not isinstance(agent, dict):
            agent = {}

        rieltor = _clean(agent.get("name") or agent.get("userName"))
        seller_ads_count = _to_int(
            _deep_find(agent, ("adsCount", "offersCount", "offersAmount"))
        )
        is_by_homeowner = _deep_find_flag(agent, ("isByHomeowner",))
        if is_by_homeowner is True:
            seller_type = "собственник"
        elif is_by_homeowner is False:
            seller_type = "агентство"
        else:
            seller_type = _clean(_deep_find(agent, ("userType", "type")))

        # --- Фотографии -----------------------------------------------------------
        photos_raw = offer.get("photos") or []
        imgs: list[str] = []
        for photo in photos_raw:
            if isinstance(photo, dict):
                src = _clean(
                    photo.get("fullUrl") or photo.get("minUrl") or photo.get("miniUrl")
                )
                if src:
                    imgs.append(src)

        # --- Статистика ---------------------------------------------------------------
        update_date = _clean(
            _deep_find(offer, ("updateDate", "editDate", "updatedAt", "publicationDate"))
        )
        views_count = _to_int(_deep_find(offer, ("viewsCount", "views")))
        views_today = 0
        stats = state.get("stats")
        if isinstance(stats, dict):
            # Новый формат: "135 просмотров, 5 за сегодня"
            if not views_count:
                views_count = _to_int(stats.get("totalViewsFormattedString"))
            # Просмотры за сегодня: отдельное поле либо хвост строки
            views_today = _to_int(stats.get("viewsTodayFormattedString"))
            if not views_today:
                today_match = re.search(
                    r"(\d+)\s*за сегодня",
                    _clean(stats.get("totalViewsFormattedString")),
                )
                if today_match:
                    views_today = int(today_match.group(1))

        return CianSiteParseData(
            site="Cian",
            url=url,
            external_id=external_id,
            name=name,
            subtitles=subtitles,
            description=description,
            object_type=object_type,
            housing_type=housing_type,
            price=price,
            price_per_meter=price_per_meter_raw,
            currency=currency,
            deal_type="sale",
            deal_conditions=deal_conditions,
            mortgage_possible=mortgage_possible,
            area=area,
            living_area=living_area,
            kitchen_area=kitchen_area,
            rooms_count=rooms_count,
            floor=floor,
            floors_count=floors_count,
            ceiling_height=ceiling_height,
            bathroom=bathroom,
            balcony=balcony,
            window_view=window_view,
            repairs=repairs,
            finishing=finishing,
            sell_with_furniture=sell_with_furniture,
            furniture=furniture,
            year_building=year_building,
            building_status=housing_type,
            building_material=building_material,
            entrances_count=entrances_count,
            elevators=elevators,
            parking=parking,
            heating=heating,
            concierge=concierge,
            barrier=barrier,
            emergency=emergency,
            ramp=ramp,
            residential_complex=residential_complex,
            developer=developer,
            residential_complex_class=residential_complex_class,
            residential_complex_completion=residential_complex_completion,
            residential_complex_parking=residential_complex_parking,
            residential_complex_finishing=residential_complex_finishing,
            geo_label=dict(geo_label),
            address=address,
            nearby_infrastructure=nearby_infrastructure,
            cadastral_number=cadastral_number,
            encumbrances=encumbrances,
            minors_owners=minors_owners,
            maternity_capital_used=maternity_capital_used,
            rieltor=rieltor,
            seller_type=seller_type,
            seller_ads_count=seller_ads_count,
            imgs=imgs,
            update_date=update_date,
            views_count=views_count,
            views_today=views_today,
            photos_count=len(imgs),
        )

    def _extract_geo_from_json(self, geo: Any) -> geoLabelDict:
        """Извлекает географию из блока geo JSON объявления."""
        geo_label: geoLabelDict = {
            "region": "",
            "city": "",
            "district": "",
            "micro_district": "",
            "street": "",
            "house": "",
        }

        if not isinstance(geo, dict):
            return geo_label

        address_block = geo.get("address")

        if isinstance(address_block, list):
            for element in address_block:
                if not isinstance(element, dict):
                    continue

                name = _clean(element.get("name"))
                if not name:
                    continue

                geo_type = _clean(
                    element.get("geoType") or element.get("type")
                ).casefold()

                # В новом формате типы: location / raion / mikroraion / house;
                # обобщённый тип "location" уточняем по locationTypeId
                # (138 — регион/край, 1 — город, прочие — улица)
                if geo_type == "location":
                    type_id = _to_int(element.get("locationTypeId"))
                    if type_id in (138, 30):
                        geo_type = "region"
                    elif type_id == 1:
                        geo_type = "city"
                    else:
                        geo_type = "street"

                # Важно: "raion" входит в "mikroraion", поэтому сначала
                # проверяем микрорайон
                if "mikroraion" in geo_type and not geo_label["micro_district"]:
                    geo_label["micro_district"] = name
                elif ("raion" in geo_type or "district" in geo_type) and not geo_label["district"]:
                    geo_label["district"] = name
                elif "region" in geo_type and not geo_label["region"]:
                    geo_label["region"] = name
                elif "street" in geo_type and not geo_label["street"]:
                    geo_label["street"] = name
                elif "house" in geo_type and not geo_label["house"]:
                    geo_label["house"] = name
                elif "city" in geo_type and not geo_label["city"]:
                    geo_label["city"] = name

        # Резервный вариант: прямые ключи в блоке geo
        if not geo_label["region"]:
            geo_label["region"] = _clean(_deep_find(geo, ("region",)))
        if not geo_label["city"]:
            geo_label["city"] = _clean(_deep_find(geo, ("city",)))
        if not geo_label["district"]:
            geo_label["district"] = _clean(_deep_find(geo, ("district",)))
        if not geo_label["street"]:
            geo_label["street"] = _clean(_deep_find(geo, ("street",)))
        if not geo_label["house"]:
            geo_label["house"] = _clean(_deep_find(geo, ("house",)))

        return geo_label

    # --------------------------- Источник: HTML ---------------------------

    def _extract_html_data(self, soup: BeautifulSoup, url: str) -> dict | None:
        """
        Резервное извлечение данных из HTML страницы объявления.
        Возвращает словарь с базовыми полями и словарём параметров.
        """
        has_title = soup.find("h1") is not None
        has_any_text = bool(soup.get_text(strip=True))

        if not has_any_text:
            return None

        data: dict[str, Any] = {
            "name": "",
            "subtitles": "",
            "description": "",
            "price": 0,
            "imgs": [],
            "geo_label": None,
            "address": "",
            "parameters": {},
        }

        if not has_title:
            # Пустая или ошибка-страница
            logger.warning("HTML объявления %s без заголовка — возможна ошибка страницы", url)

        # Заголовок
        title = soup.select_one('h1[data-mark="OfferTitle"]') or soup.find("h1")
        if isinstance(title, Tag):
            data["name"] = _clean(title.get_text(" ", strip=True))

        # Подзаголовок (если присутствует)
        subtitle = soup.select_one('[data-mark="OfferSubtitle"]') or soup.select_one(
            '[data-name="OfferSubtitle"]'
        )
        if isinstance(subtitle, Tag):
            data["subtitles"] = _clean(subtitle.get_text(" ", strip=True))

        # Описание
        description = soup.select_one('div[data-name="Description"]')
        if isinstance(description, Tag):
            data["description"] = _clean(description.get_text(" ", strip=True))

        # Цена
        price_el = soup.select_one('[data-mark="MainPrice"]')
        if isinstance(price_el, Tag):
            digits = re.sub(r"\D", "", price_el.get_text("", strip=True))
            data["price"] = int(digits) if digits else 0

        # География (метки GeoLabel, как в старом парсере карточек)
        geo_labels = [
            _clean(item.get_text(" ", strip=True))
            for item in soup.select('[data-name="GeoLabel"]')
            if isinstance(item, Tag)
        ]
        if geo_labels:
            data["geo_label"] = self._geo_labels_from_list(geo_labels)
            data["address"] = ", ".join(geo_labels)

        # Фотографии из галереи
        gallery = soup.select_one('div[data-name="Gallery"]')
        if isinstance(gallery, Tag):
            imgs: list[str] = []
            for img in gallery.find_all("img"):
                src = img.get("src")
                if isinstance(src, str) and src.startswith("http"):
                    imgs.append(src)
            data["imgs"] = list(dict.fromkeys(imgs))

        # Параметры объявления (список «название: значение»)
        data["parameters"] = self._extract_li_parameters(soup)

        return data

    def _extract_li_parameters(self, soup: BeautifulSoup) -> dict[str, str]:
        """
        Извлекает пары «название: значение» из списков характеристик
        (элементы <li>, где название — первый <span>).
        """
        parameters: dict[str, str] = {}

        for li in soup.select("li"):
            if not isinstance(li, Tag):
                continue

            label_element = li.find("span")

            if not isinstance(label_element, Tag):
                continue

            label_text = _clean(label_element.get_text(" ", strip=True)).rstrip(":")
            full_text = _clean(li.get_text(" ", strip=True))

            if not label_text or label_text not in full_text:
                continue

            value = full_text.replace(label_text, "", 1).strip(" :\u00a0")

            if value:
                parameters[label_text] = value

        return parameters

    def _fill_missing_from_html(self, item: CianSiteParseData, html_data: dict) -> None:
        """Дозаполняет пустые поля модели данными, извлечёнными из HTML."""
        if not item.name:
            item.name = html_data["name"]
        if not item.subtitles:
            item.subtitles = html_data["subtitles"]
        if not item.description:
            item.description = html_data["description"]
        if not item.price:
            item.price = html_data["price"]
        if not item.imgs:
            item.imgs = html_data["imgs"]
        if not item.address:
            item.address = html_data["address"]

        if not item.geo_label.get("city") and html_data["geo_label"]:
            item.geo_label = html_data["geo_label"]

        if not item.photos_count:
            item.photos_count = len(item.imgs)

        # Характеристики из HTML-списка параметров
        parameters: dict[str, str] = html_data["parameters"]

        def param(*names: str) -> str:
            for name in names:
                for label, value in parameters.items():
                    if label.casefold() == name.casefold():
                        return value
            return ""

        if not item.area:
            item.area = _to_float(param("Общая площадь", "Площадь"))
        if not item.floor:
            item.floor = _to_int(param("Этаж"))
        if not item.floors_count:
            item.floors_count = _to_int(param("Этажей в доме"))
        if item.rooms_count is None:
            rooms_text = param("Количество комнат", "Комнат в квартире")
            item.rooms_count = _to_int(rooms_text) if rooms_text else None
        if not item.year_building:
            item.year_building = _to_int(param("Год постройки", "Год сдачи"))
        if not item.housing_type:
            item.housing_type = param("Тип жилья")
        if not item.bathroom:
            item.bathroom = param("Санузел")
        if not item.balcony:
            item.balcony = param("Балкон", "Лоджия", "Балкон/Лоджия")
        if not item.repairs:
            item.repairs = param("Ремонт", "Тип ремонта")
        if not item.ceiling_height:
            item.ceiling_height = _to_float(param("Высота потолков"))
        if not item.parking:
            item.parking = param("Парковка", "Тип парковки")
        if not item.building_material:
            item.building_material = param("Тип дома", "Материал стен")

    # --------------------------- Вспомогательные методы ---------------------------

    @staticmethod
    def _as_str_list(value: Any) -> list[str]:
        """Преобразует произвольное значение в список непустых строк."""
        if value is None:
            return []
        if isinstance(value, list):
            items = value
        else:
            items = [value]

        result = [_clean(item) for item in items]
        return [item for item in result if item]

    @staticmethod
    def _format_elevators(value: Any) -> list[str]:
        """
        Преобразует блок лифтов в список читаемых строк.

        Новый формат CIAN: [{"type": "pass", "count": 2}, ...]
        Старый формат: список строк либо одиночная строка.
        """
        if value is None:
            return []
        items = value if isinstance(value, list) else [value]

        result: list[str] = []
        for item in items:
            if isinstance(item, dict):
                label = ELEVATOR_TYPE_LABELS.get(
                    _clean(item.get("type")).casefold(),
                    _clean(item.get("type")),
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
    def _geo_labels_from_list(labels: list[str]) -> geoLabelDict:
        """Преобразует текстовые GeoLabel в словарь географии (по порядку)."""
        geo_data: geoLabelDict = {
            "region": "",
            "city": "",
            "district": "",
            "micro_district": "",
            "street": "",
            "house": "",
        }

        order = ("region", "city", "district", "micro_district", "street", "house")

        for position, label in enumerate(labels):
            if position >= len(order):
                break
            geo_data[order[position]] = label

        return geo_data

    @staticmethod
    def _join_geo_label(geo_label: geoLabelDict) -> str:
        """Собирает адрес одной строкой из заполненных полей географии."""
        parts = [
            geo_label.get(key, "")
            for key in ("region", "city", "district", "street", "house")
        ]
        return ", ".join(part for part in parts if part)
