"""
Парсер объявлений Avito (на Selenium, в стиле Cian-парсера).

Схема работы:
1. Парсер постранично обходит списки объявлений и собирает карточки
   с предварительными данными (название, цена, ссылка) — из карточек
   списка используется только минимум.
2. Затем для каждой ссылки открывается страница объявления в браузере
   и из неё извлекаются все поля модели AvitoSiteParseData. Если страница
   объявления не распарсилась, объявление остаётся в результатах с
   предварительными данными карточки.

Приоритет источников данных на странице объявления:
- HTML-разметка с data-marker атрибутами (сервер-рендеринг Авито);
  встраиваемого JSON объявления на странице нет.
- data-атрибуты блока карты (data-map-lat / data-map-lon) — координаты.
- DaData (обратное геокодирование по координатам) — адресные поля.

Ошибки сети, отсутствующие поля и некорректный HTML не останавливают
процесс: проблемное объявление пропускается с записью в лог.
"""

import logging
import os
import re

from random import uniform
from time import sleep
from typing import Literal, TypeAlias
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
from model.site_parse_data_model import AvitoSiteParseData as SiteParseData, geoLabelDict

# ------------------------------------------------------------------------------
# Настройки логирования
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("avito_parser")

# Время ожидания загрузки страницы (секунды)
PAGE_WAIT_TIME = 10

# Задержки между запросами по умолчанию (используются, если в ParserConfig
# интервалы заданы нулевыми). Нужны, чтобы не попасть под блокировку.
DEFAULT_MIN_DELAY = 1.5
DEFAULT_MAX_DELAY = 5.0

ObjectType: TypeAlias = Literal[
    "flat",
    "room",
    "studio",
    "house",
    "land_plot",
    "garage",
    "other",
]

# Признаки антибот-заглушки Авито («Доступ ограничен: проверка безопасности»).
# Проверяем только однозначные признаки, чтобы не ловить ложные срабатывания.
BLOCK_TEXT_MARKERS = (
    "доступ ограничен: проверка безопасности",
    "firewall__title",
    "доступ ограничен: проблема с ip",
)

# Селектор содержимого загруженной страницы объявления
CONTENT_SELECTOR = (
    '[data-marker="item-view/title-info"], '
    '[data-marker="item-view/item-id"], '
    '[data-marker="item-view/item-price"]'
)

# Подписи продавцов для нормализации типа
SELLER_TYPE_LABELS = {
    "частное лицо": "Частное лицо",
    "застройщик": "Застройщик",
    "агентство": "Агентство",
    "агент": "Агентство",
}

# Соответствие «поле модели -> подписи в item-params Авито».
# Используется для контроля заполнения: если подпись есть в параметрах
# страницы, но поле модели осталось пустым — парсер логирует предупреждение.
# Поля условные: «Отопление», «Категория земель» и т. п. встречаются только
# у домов, участков и гаражей, поэтому пустое поле само по себе не ошибка.
FIELD_PARAMETER_LABELS: dict[str, tuple[str, ...]] = {
    "elevators": ("Пассажирский лифт", "Грузовой лифт", "Лифт"),
    "parking": ("Парковка",),
    "courtyard": ("Двор",),
    "heating": ("Отопление",),
    "water_supply": ("Водоснабжение",),
    "sewerage": ("Канализация",),
    "gas": ("Газ",),
    "electricity": ("Электричество",),
    "internet_tv": ("Интернет и ТВ",),
    "land_category": ("Категория земель",),
    "land_area": ("Площадь участка",),
    "garage_type": ("Тип гаража",),
    "security": ("Охрана",),
    "recreation": ("Для отдыха",),
    "terrace": ("Терраса или веранда",),
}


# ==============================================================================
# Вспомогательные функции
# ==============================================================================

def _clean(value) -> str:
    """Приводит значение к чистой строке (без лишних пробелов/переносов)."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _to_int(value) -> int:
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


def _to_float(value) -> float:
    """Безопасное преобразование значения в float (0.0 при неудаче)."""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)

    match = re.search(
        r"(\d+(?:[.,]\d+)?)",
        str(value).replace(" ", "").replace("\u00a0", ""),
    )

    return float(match.group(1).replace(",", ".")) if match else 0.0


def _looks_like_block_page(html: str, current_url: str = "") -> bool:
    """
    Определяет страницу антибот-заглушки Авито
    («Доступ ограничен: проверка безопасности»).
    """
    if "firewall" in urlparse(current_url).netloc.casefold():
        return True

    lowered = html[:5000].casefold()

    return any(marker in lowered for marker in BLOCK_TEXT_MARKERS)


# ==============================================================================
# Парсер
# ==============================================================================

class AvitoParser(IParcer):
    """Парсер Avito: список объявлений -> страницы объявлений -> модель данных."""

    def __init__(self):
        self.refs = {
            "flat/studio": (
                "https://www.avito.ru/vladivostok/kvartiry/prodam-ASgBAgICAUSSA8YQ"
                "?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6Ik1Hbms0NVdCYU1SeElremciO33Do1akJgAAAA"
                "&localPriority=0&p={page}"
            ),
            "room": (
                "https://www.avito.ru/vladivostok/komnaty/prodam-ASgBAgICAUSQA7wQ"
                "?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6Ims5ZkhvUUFwTGJicWR1cGEiO33Idg0EJgAAAA"
                "&localPriority=0&p={page}"
            ),
            "house": (
                "https://www.avito.ru/vladivostok/doma_dachi_kottedzhi/prodam-ASgBAgICAUSUA9AQ"
                "?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6ImdBbjNKTGlKeGxEWDVKbngiO3367d43JgAAAA"
                "&localPriority=0&p={page}"
            ),
            "land_plot": (
                "https://www.avito.ru/vladivostok/zemelnye_uchastki/prodam-ASgBAgICAUSWA9oQ"
                "?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6InNhQTVsSjhmV1pTZEo1aE8iO300GHrYJgAAAA"
                "&localPriority=0&p={page}"
            ),
            "garage": (
                "https://www.avito.ru/vladivostok/garazhi_i_mashinomesta/prodam-ASgBAgICAUSYA~QQ"
                "?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6ImgyMXNNQ2VWQkxaNlQ0YkciO33mvNP-JgAAAA"
                "&localPriority=0&p={page}"
            ),
            "other": (
                "https://www.avito.ru/vladivostok/kommercheskaya_nedvizhimost/prodam-ASgBAgICAUSwCNJW"
                "?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6Imo2SnJ2d0hOZElKdnNOMlkiO31-kt2FJgAAAA"
                "&f=ASgBAgICAkSwCNJW8hKg2gE&localPriority=0&p={page}"
            ),
        }

        self.object_types: dict[str, ObjectType] = {
            "flat/studio": "flat",
            "room": "room",
            "house": "house",
            "land_plot": "land_plot",
            "garage": "garage",
            "other": "other",
        }

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

        # DaData для обратного геокодирования адреса по координатам карты.
        # Если токен недоступен, адресные поля просто останутся пустыми.
        self.dadata = None
        self._init_dadata()

    def _init_dadata(self) -> None:
        """Инициализирует DaData, если файл с API-ключом существует.

        Ключ ищется в текущем каталоге и в родительском каталоге проекта.
        """
        api_key = ""

        for token_path in ("dadadata_token.txt", os.path.join("..", "dadadata_token.txt")):
            try:
                with open(token_path, "r", encoding="utf-8") as key_file:
                    api_key = key_file.read().strip()
                break
            except OSError:
                continue

        if not api_key:
            logger.warning(
                "Файл dadadata_token.txt не найден, "
                "адрес по координатам определяться не будет"
            )
            return

        try:
            from dadata import Dadata

            self.dadata = Dadata(api_key)
        except Exception as error:
            logger.warning("Не удалось инициализировать DaData: %s", error)

    # --------------------------------------------------------------------------
    # Публичный интерфейс
    # --------------------------------------------------------------------------

    def parse(
        self,
        parserConfig: ParserConfig,
    ) -> tuple[bool, list[SiteParseData] | None]:

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

        offers: list[SiteParseData] = []
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
            # Этап 1: обходим списки объявлений и собираем карточки
            # ------------------------------------------------------------------
            pending_items: list[SiteParseData] = []

            for category, category_url in self.refs.items():
                object_type = self.object_types[category]

                category_items = self._collect_listing_items(
                    driver=driver,
                    category=category,
                    category_url=category_url,
                    object_type=object_type,
                    max_pages=parserConfig.max_page_iteration,
                    min_delay=min_delay,
                    max_delay=max_delay,
                )

                for item in category_items:
                    if item.url and item.url not in seen_urls:
                        seen_urls.add(item.url)
                        pending_items.append(item)

            logger.info("Собрано уникальных карточек объявлений: %d", len(pending_items))

            # ------------------------------------------------------------------
            # Этап 2: открываем страницу каждого объявления и парсим данные
            # ------------------------------------------------------------------
            for index, item in enumerate(pending_items, start=1):
                logger.info("Объявление %d/%d: %s", index, len(pending_items), item.url)

                parsed = self._parse_offer_page(driver, item)

                if parsed:
                    offers.append(item)
                else:
                    # Страница не распарсилась — оставляем данные карточки
                    logger.warning(
                        "Объявление пропущено, данные карточки: %s", item.url
                    )
                    offers.append(item)

                # Задержка между запросами, чтобы не попасть под блокировку
                sleep(uniform(min_delay, max_delay))

        finally:
            driver.quit()

        logger.info("Итого собрано объявлений: %d", len(offers))

        return True, offers

    # --------------------------------------------------------------------------
    # Этап 1: сбор карточек из списка объявлений
    # --------------------------------------------------------------------------

    def _collect_listing_items(
        self,
        driver: webdriver.Chrome,
        category: str,
        category_url: str,
        object_type: ObjectType,
        max_pages: int,
        min_delay: float,
        max_delay: float,
        max_attempts: int = 3,
    ) -> list[SiteParseData]:
        """Обходит постранично выдачу и возвращает карточки объявлений."""
        items: list[SiteParseData] = []

        page = 1
        attempts = 0

        while page <= max_pages:
            page_url = category_url.format(page=page)

            success, page_items = self._parse_listing_page(
                driver,
                page_url,
                object_type,
            )

            if not success:
                attempts += 1
                logger.warning(
                    "Не удалось загрузить страницу списка "
                    "(категория=%s, стр. %d, попытка %d/%d)",
                    category,
                    page,
                    attempts,
                    max_attempts,
                )

                if attempts >= max_attempts:
                    logger.warning(
                        "Страница пропущена после %d попыток: %s",
                        attempts,
                        page_url,
                    )
                    break

                # Интерактивный повтор, как в Cian-парсере:
                # пользователь решает проблему в открывшемся браузере
                try:
                    answer = input(
                        "Исправьте проблему в браузере и нажмите Enter "
                        "для повтора. Введите 'n' для пропуска: "
                    ).strip().lower()
                except EOFError:
                    # Неинтерактивный режим консоли: продолжаем повторы
                    answer = ""

                if answer == "n":
                    break

                # Повторяем ту же страницу
                continue

            attempts = 0

            logger.info(
                "Список %s, стр. %d: найдено %d объявлений",
                category,
                page,
                len(page_items),
            )

            # Пустая страница означает конец выдачи
            if not page_items:
                break

            items.extend(page_items)
            page += 1

            # Пауза между страницами списка
            sleep(uniform(min_delay, max_delay))

        return items

    def _parse_listing_page(
        self,
        driver: webdriver.Chrome,
        page_url: str,
        category: ObjectType,
    ) -> tuple[bool, list[SiteParseData]]:
        """Открывает страницу списка и извлекает карточки объявлений."""
        try:
            driver.get(page_url)

            WebDriverWait(driver, PAGE_WAIT_TIME).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, '[data-marker="item"]')
                )
            )

        except (TimeoutException, WebDriverException) as error:
            logger.warning("Ошибка загрузки списка: %s", error)
            return False, []

        try:
            soup = BeautifulSoup(driver.page_source, "lxml")
        except Exception as error:
            logger.error("Ошибка разбора HTML списка: %s", error)
            return False, []

        results: list[SiteParseData] = []
        seen_urls: set[str] = set()

        for card in soup.select('[data-marker="item"]'):
            item = self._extract_card_data(card, page_url, category)

            if item is None:
                continue

            canonical_url = self._canonical_offer_url(item.url)

            if canonical_url is None or canonical_url in seen_urls:
                continue

            seen_urls.add(canonical_url)
            item.url = canonical_url

            results.append(item)

        return True, results

    def _canonical_offer_url(self, url: str) -> str | None:
        """Нормализует ссылку на объявление (только схема/домен/путь)."""
        if not url:
            return None

        parsed_url = urlparse(url)

        if (
            parsed_url.netloc
            and not parsed_url.netloc.endswith("avito.ru")
        ):
            return None

        if not parsed_url.path.startswith("/vladivostok/"):
            return None

        if not re.search(r"\d{8,}/?$", parsed_url.path):
            return None

        return urlunparse(
            (
                parsed_url.scheme or "https",
                parsed_url.netloc or "www.avito.ru",
                parsed_url.path,
                "",
                "",
                "",
            )
        )

    def _extract_card_data(
        self,
        card: Tag,
        page_url: str,
        category: ObjectType,
    ) -> SiteParseData | None:
        """Извлекает предварительные данные карточки из списка объявлений."""

        title_element = card.select_one(
            '[data-marker="item-title"]'
        )

        if title_element is None:
            title_element = card.select_one(
                "a[data-marker*='item-title'][href], "
                "a[href*='/vladivostok/']"
            )

        if title_element is None:
            return None

        link_element = (
            title_element
            if title_element.name == "a"
            else title_element.find_parent("a")
        )

        if link_element is None:
            link_element = card.select_one(
                "a[data-marker*='item-title'][href], "
                "a[href*='/vladivostok/']"
            )

        if link_element is None:
            return None

        href = link_element.get("href")

        if not isinstance(href, str) or not href.strip():
            return None

        url = urljoin(page_url, href.strip())

        name = _clean(title_element.get_text(" ", strip=True))

        price = self._extract_price(
            card.select_one('[data-marker="item-price"]')
        )

        subtitles_element = (
            card.select_one('[data-marker="item-specific-params"]')
            or card.select_one('[data-marker="item-subtitle"]')
            or card.select_one('[data-marker="item-description"]')
        )

        subtitles = (
            _clean(subtitles_element.get_text(" ", strip=True))
            if subtitles_element
            else ""
        )

        object_type: ObjectType = category

        if category == "flat" and re.search(
            r"\bстуди",
            name,
            re.IGNORECASE,
        ):
            object_type = "studio"

        # Значения с карточки — только предварительные.
        # После открытия объявления они будут заменены данными страницы.
        property_details = self._parse_property_from_title(f"{name} {subtitles}")

        return SiteParseData(
            site="Avito",
            url=url,
            name=name,
            subtitles=subtitles,
            description="",
            price=price,
            object_type=object_type,
            floor=property_details["floor"],
            area=property_details["area"],
            rooms_count=property_details["rooms_count"],
        )

    def _extract_price(self, price_element: Tag | None) -> int:
        """Извлекает числовую цену из элемента карточки объявления."""
        if price_element is None:
            return 0

        price_text = price_element.get_text(" ", strip=True)
        digits = re.sub(r"\D", "", price_text)

        return int(digits) if digits else 0

    # --------------------------------------------------------------------------
    # Этап 2: парсинг страницы объявления
    # --------------------------------------------------------------------------

    def _parse_offer_page(
        self,
        driver: webdriver.Chrome,
        item: SiteParseData,
    ) -> bool:
        """
        Открывает страницу объявления и заполняет модель данными страницы.

        Возвращает True, если данные страницы успешно извлечены.
        Модель item изменяет in-place: пустые поля карточки дозаполняются,
        непустые (если данные страницы есть) — переопределяются.
        """
        url = item.url

        html = self._load_offer_page(driver, url, max_attempts=3)

        if html is None:
            return False

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception as error:
            logger.error("Ошибка разбора HTML объявления %s: %s", url, error)
            return False

        try:
            page_data = self._extract_page_data(soup, url)
        except Exception as error:
            logger.error("Ошибка извлечения данных %s: %s", url, error)
            return False

        if not page_data["parameters"]:
            logger.warning(
                "Характеристики (item-params) не найдены на странице — "
                "поля дома/участка/гаража останутся пустыми: %s",
                url,
            )

        self._apply_page_data(item, page_data)

        return True

    def _load_offer_page(
        self,
        driver: webdriver.Chrome,
        url: str,
        max_attempts: int = 3,
    ) -> str | None:
        """Загружает страницу объявления, обрабатывая антибот-заглушку."""
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
                logger.warning("Ошибка загрузки объявления %s: %s", url, error)
                return None

            # Ждём появления содержимого объявления, но не полной загрузки
            try:
                WebDriverWait(driver, PAGE_WAIT_TIME).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, CONTENT_SELECTOR)
                    )
                )
            except TimeoutException:
                pass

            html = driver.page_source

            if not _looks_like_block_page(html, driver.current_url):
                return html

            logger.warning(
                "Антибот-заглушка на странице объявления "
                "(попытка %d/%d): %s",
                attempt,
                max_attempts,
                url,
            )

            if attempt < max_attempts:
                sleep(uniform(3, 7))

        logger.warning("Не удалось обойти заглушку: %s", url)
        return None

    # --------------------------- Извлечение данных ---------------------------

    def _extract_page_data(
        self,
        soup: BeautifulSoup,
        url: str,
    ) -> dict:
        """
        Извлекает все доступные данные страницы объявления в словарь.
        Все поля null-safe: отсутствие блока даёт пустое значение.
        """
        data: dict = {
            "external_id": "",
            "name": "",
            "description": "",
            "price": 0,
            "imgs": [],
            "parameters": {},
            "breadcrumbs": [],
            "badges": [],
            "feature_chips": [],
            "publish_date": "",
            "views_count": 0,
            "views_today": 0,
            "residential_complex": "",
            "seller": {},
            "developer": {},
            "coordinates": {},
            "geo_label": None,
        }

        # --------------------------------------------------
        # 1. Идентификатор объявления
        # --------------------------------------------------
        id_element = soup.select_one('[data-marker="item-view/item-id"]')

        if id_element:
            id_match = re.search(r"\d{8,}", id_element.get_text(" ", strip=True))

            if id_match:
                data["external_id"] = id_match.group()

        # Резерв: data-item-id блока карты
        if not data["external_id"]:
            map_element = soup.select_one('[data-marker="item-map-wrapper"]')

            if map_element:
                data["external_id"] = _clean(map_element.get("data-item-id"))

        # --------------------------------------------------
        # 2. Название (заголовок объявления)
        # --------------------------------------------------
        title_element = soup.select_one(
            '[data-marker="item-view/title-info"] h1'
        ) or soup.select_one('[data-marker="item-view/title-info"]')

        if title_element:
            data["name"] = _clean(title_element.get_text(" ", strip=True))

        # --------------------------------------------------
        # 3. Цена
        # --------------------------------------------------
        price_element = soup.select_one('[data-marker="item-view/item-price"]')

        if price_element:
            data["price"] = self._extract_price(price_element)

        # --------------------------------------------------
        # 4. Описание
        # --------------------------------------------------
        description_element = soup.select_one(
            '[data-marker="item-view/item-description"]'
        )

        if description_element is None:
            description_element = soup.select_one(
                '[data-marker*="item-description"]'
            )

        if description_element:
            data["description"] = _clean(
                description_element.get_text(" ", strip=True)
            )

        # --------------------------------------------------
        # 5. Параметры объявления («Количество комнат: 1» и т. д.)
        # --------------------------------------------------
        data["parameters"] = self._extract_li_parameters(soup)

        # --------------------------------------------------
        # 6. Дата публикации
        # --------------------------------------------------
        date_element = soup.select_one('[data-marker="item-view/item-date"]')

        if date_element:
            data["publish_date"] = _clean(
                date_element.get_text(" ", strip=True)
            ).lstrip("·").strip()

        # --------------------------------------------------
        # 7. Просмотры
        # --------------------------------------------------
        total_views_element = soup.select_one(
            '[data-marker="item-view/total-views"]'
        )

        if total_views_element:
            data["views_count"] = _to_int(
                total_views_element.get_text(" ", strip=True)
            )

        today_views_element = soup.select_one(
            '[data-marker="item-view/today-views"]'
        )

        if today_views_element:
            data["views_today"] = _to_int(
                today_views_element.get_text(" ", strip=True)
            )

        # --------------------------------------------------
        # 8. Хлебные крошки (категория, тип жилья)
        # --------------------------------------------------
        data["breadcrumbs"] = self._extract_breadcrumbs(soup)

        # --------------------------------------------------
        # 9. Бейджи («Данные подтверждены» и т. п.)
        # --------------------------------------------------
        data["badges"] = self._extract_badges(soup)

        # --------------------------------------------------
        # 10. Чипы-особенности (кухня м², лифты, окна и т. п.)
        # --------------------------------------------------
        data["feature_chips"] = self._extract_feature_chips(soup)

        # --------------------------------------------------
        # 11. Название ЖК
        # --------------------------------------------------
        data["residential_complex"] = self._extract_residential_complex(soup)

        # --------------------------------------------------
        # 12. Продавец
        # --------------------------------------------------
        data["seller"] = self._extract_seller_info(soup)

        # --------------------------------------------------
        # 13. Застройщик (блок «О застройщике»)
        # --------------------------------------------------
        data["developer"] = self._extract_developer_info(soup)

        # --------------------------------------------------
        # 14. Координаты карты объявления
        # --------------------------------------------------
        data["coordinates"] = self._extract_coordinates(soup)

        # --------------------------------------------------
        # 15. Адрес через DaData (обратное геокодирование)
        # --------------------------------------------------
        if data["coordinates"]:
            data["geo_label"] = self._extract_geo_from_coordinates(
                data["coordinates"]
            )

        # --------------------------------------------------
        # 16. Фотографии из галереи
        # --------------------------------------------------
        data["imgs"] = self._extract_gallery_images(soup, url)

        return data

    def _extract_li_parameters(self, soup: BeautifulSoup) -> dict[str, str]:
        """
        Извлекает пары «название: значение» из списков характеристик
        объявления (элементы <li> внутри item-params).
        """
        parameters: dict[str, str] = {}

        containers = (
            soup.select('[data-marker="item-view/item-params"]')
            or [soup]
        )

        for container in containers:
            for li in container.select("li"):
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

    def _get_parameter(
        self,
        parameters: dict[str, str],
        *names: str,
    ) -> str:
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

    def _extract_breadcrumbs(self, soup: BeautifulSoup) -> list[str]:
        """Извлекает хлебные крошки («Главная | Недвижимость | ...»).

        Каждая крошка может дублироваться в li > a > span, поэтому берём
        только ссылки и текст последнего пункта (без ссылки), затем
        убираем подряд идущие дубликаты.
        """
        crumbs_element = soup.select_one('[data-marker="breadcrumbs"]')

        if crumbs_element is None:
            return []

        links = crumbs_element.select("a")

        if links:
            crumbs = [
                _clean(link.get_text(" ", strip=True))
                for link in links
            ]

            last_item = crumbs_element.select("li")[-1] if crumbs_element.select("li") else None

            if last_item is not None:
                last_link = last_item.find("a")

                if last_link is None:
                    crumbs.append(
                        _clean(last_item.get_text(" ", strip=True))
                    )
        else:
            crumbs = [
                _clean(li.get_text(" ", strip=True))
                for li in crumbs_element.select("li")
            ]

        # Убираем пустые пункты («…») и подряд идущие дубликаты
        result: list[str] = []

        for crumb in crumbs:
            if not crumb or crumb == "…":
                continue

            if result and result[-1] == crumb:
                continue

            result.append(crumb)

        return result

    def _extract_badges(self, soup: BeautifulSoup) -> list[str]:
        """Извлекает бейджи объявления (badgeBar)."""
        badges: list[str] = []

        for badge in soup.select('[data-marker^="badgeBar/option"]'):
            text = _clean(badge.get_text(" ", strip=True))

            if text and text not in badges:
                badges.append(text)

        return badges

    def _extract_feature_chips(self, soup: BeautifulSoup) -> list[str]:
        """Извлекает чипы-особенности (реalty-usp)."""
        chips_element = soup.select_one('[data-marker="realty-usp/desktop-chips"]')

        if chips_element is None:
            return []

        chips = [
            _clean(option.get_text(" ", strip=True))
            for option in chips_element.select('[data-marker*="/option"]')
        ]

        return [chip for chip in chips if chip]

    def _extract_residential_complex(self, soup: BeautifulSoup) -> str:
        """Извлекает название жилого комплекса (nd-house-complex-link)."""
        link_element = soup.select_one('[data-marker="nd-house-complex-link"]')

        if link_element:
            value = _clean(link_element.get_text(" ", strip=True))

            if value:
                return value

        # Резерв: параметр «Название новостройки»
        parameters = self._extract_li_parameters(soup)

        return self._get_parameter(
            parameters,
            "Название новостройки",
            "Название ЖК",
        )

    def _extract_seller_info(self, soup: BeautifulSoup) -> dict:
        """
        Извлекает информацию о продавце:
        имя, тип, рейтинг, отзывы, год регистрации, число объявлений.
        """
        seller: dict = {
            "name": "",
            "type": "",
            "rating": 0.0,
            "reviews_count": 0,
            "registered_year": 0,
            "ads_count": 0,
            "contact_person": "",
            "documents_verified": None,
        }

        seller_element = soup.select_one('[data-marker="item-view/seller-info"]')

        if seller_element is None:
            return seller

        seller_text = _clean(seller_element.get_text(" ", strip=True))

        # Имя продавца
        name_element = seller_element.select_one(
            '[data-marker="seller-info/name"]'
        )

        if name_element:
            seller["name"] = _clean(name_element.get_text(" ", strip=True))

        # Контактное лицо (у застройщиков)
        contact_element = seller_element.select_one(
            '[data-marker="seller-info/contact-person"]'
        )

        if contact_element:
            contact_text = _clean(
                contact_element.get_text(" ", strip=True)
            )

            contact_text = re.sub(
                r"^контактное лицо\s*",
                "",
                contact_text,
                flags=re.IGNORECASE,
            ).strip()

            seller["contact_person"] = contact_text

        # Тип продавца
        label_element = seller_element.select_one(
            '[data-marker="seller-info/label"]'
        )

        if label_element:
            raw_type = _clean(label_element.get_text(" ", strip=True))
            seller["type"] = SELLER_TYPE_LABELS.get(
                raw_type.casefold(),
                raw_type,
            )

        # Рейтинг продавца (itemprop ratingValue в разметке страницы)
        rating_value = soup.find(itemprop="ratingValue")

        if rating_value is not None:
            rating_content = (
                rating_value.get("content")
                if isinstance(rating_value, Tag)
                else None
            )

            if rating_content:
                seller["rating"] = _to_float(rating_content)
            else:
                seller["rating"] = _to_float(
                    rating_value.get_text(" ", strip=True)
                )

        # Количество отзывов («15 отзывов», «1 отзыв»).
        # У застройщиков блок отзывов (rating-row) находится вне seller-info,
        # поэтому ищем в обоих местах.
        reviews_text = seller_text

        for reviews_marker in (
            '[data-marker="rating-row"]',
            '[data-marker="rating-caption/rating"]',
        ):
            reviews_element = soup.select_one(reviews_marker)

            if reviews_element is not None:
                reviews_text += " " + _clean(
                    reviews_element.get_text(" ", strip=True)
                )

                break

        reviews_match = re.search(
            r"(\d+)\s+отзыв\w*",
            reviews_text,
            re.IGNORECASE,
        )

        if reviews_match:
            seller["reviews_count"] = int(reviews_match.group(1))

        # Год регистрации («На Авито c 2022 года»)
        year_match = re.search(
            r"На Авито c (\d{4})",
            seller_text,
            re.IGNORECASE,
        )

        if year_match:
            seller["registered_year"] = int(year_match.group(1))

        # Количество объявлений пользователя
        ads_match = re.search(
            r"(\d+)\s+объявлен\w*\s+пользователя",
            seller_text,
            re.IGNORECASE,
        )

        if ads_match:
            seller["ads_count"] = int(ads_match.group(1))

        return seller

    def _extract_developer_info(self, soup: BeautifulSoup) -> dict:
        """
        Извлекает информацию о застройщике из блока «О застройщике»:
        название, год основания, сдано/строятся домов.
        """
        developer: dict = {
            "name": "",
            "foundation_year": 0,
            "completed_buildings": 0,
            "buildings_under_construction": 0,
        }

        block_element = soup.select_one('[data-marker="developer-trust-block"]')

        if block_element is None:
            return developer

        block_text = _clean(block_element.get_text(" ", strip=True))

        # Название: «Группа компаний «X»» или строка после «О застройщике»
        name_match = re.search(
            r"Группа компаний\s+(.+?)(?:\s+\d+%|\s+С \d{4}|$)",
            block_text,
        )

        if name_match:
            developer["name"] = name_match.group(1).strip()

        # Год основания («С 2016 года» / «С 1994 года»)
        year_match = re.search(r"С (\d{4}) года", block_text)

        if year_match:
            developer["foundation_year"] = int(year_match.group(1))

        # Сдано («Сдано: 10 домов в 6 ЖК»)
        completed_match = re.search(
            r"Сдано:\s*(\d+)\s+дом\w*",
            block_text,
            re.IGNORECASE,
        )

        if completed_match:
            developer["completed_buildings"] = int(completed_match.group(1))

        # Строятся («Строятся: 3 дома в 2 ЖК»)
        building_match = re.search(
            r"Строятся:\s*(\d+)\s+дом\w*",
            block_text,
            re.IGNORECASE,
        )

        if building_match:
            developer["buildings_under_construction"] = int(
                building_match.group(1)
            )

        return developer

    def _extract_coordinates(self, soup: BeautifulSoup) -> dict:
        """Извлекает координаты из data-атрибутов блока карты."""
        coordinates: dict = {"lat": 0.0, "lon": 0.0, "zoom": 0}

        map_element = soup.select_one(
            '[data-marker="item-map-wrapper"][data-map-lat][data-map-lon]'
        )

        if map_element is None:
            map_element = soup.select_one(
                "[data-map-lat][data-map-lon]"
            )

        if map_element is None:
            return coordinates

        lat_value = map_element.get("data-map-lat")
        lon_value = map_element.get("data-map-lon")

        if not isinstance(lat_value, str) or not isinstance(lon_value, str):
            logger.warning("Не удалось прочитать координаты объявления")
            return coordinates

        try:
            coordinates["lat"] = float(lat_value)
            coordinates["lon"] = float(lon_value)
        except ValueError:
            logger.warning("Некорректный формат координат")
            return coordinates

        zoom_value = map_element.get("data-map-zoom")

        if isinstance(zoom_value, str):
            coordinates["zoom"] = _to_int(zoom_value)

        return coordinates

    def _extract_geo_from_coordinates(
        self,
        coordinates: dict,
    ) -> geoLabelDict | None:
        """Определяет адрес через DaData по координатам карты объявления."""
        if self.dadata is None:
            return None

        lat = coordinates.get("lat")
        lon = coordinates.get("lon")

        if not lat or not lon:
            return None

        try:
            result = self.dadata.geolocate(
                name="address",
                lat=lat,
                lon=lon,
            )
        except Exception as error:
            logger.warning("DaData: ошибка получения адреса: %s", error)
            return None

        if not result:
            logger.warning(
                "DaData: адрес не найден для координат %s, %s", lat, lon
            )
            return None

        # Библиотека возвращает список подсказок с полем data
        address = result[0].get("data", {})

        return {
            "region": address.get("region", "") or "",
            "city": address.get("city", "") or "",
            "district": address.get("city_district", "") or "",
            "micro_district": address.get("settlement", "") or "",
            "street": address.get("street", "") or "",
            "house": address.get("house", "") or "",
        }

    def _extract_gallery_images(self, soup: BeautifulSoup, url: str) -> list[str]:
        """Извлекает фотографии из галереи объявления."""
        gallery = (
            soup.select_one("div#bx_item-gallery")
            or soup.select_one(
                'div[data-marker="item-view/main-gallery"]'
            )
            or soup.select_one('[data-marker="item-view/gallery"]')
        )

        if gallery is None:
            return []

        images: list[str] = []
        seen_image_keys: set[str] = set()

        for image in gallery.select("img"):
            if image.find_parent("svg"):
                continue

            # Не берём изображения из рекламных/ипотечных блоков
            if image.find_parent(
                attrs={
                    "data-marker": re.compile(
                        r"mortgage|advert",
                        re.IGNORECASE,
                    )
                }
            ):
                continue

            candidates: list[str] = []

            for attribute in (
                "src",
                "data-src",
                "data-original",
                "data-lazy-src",
                "data-url",
            ):
                value = image.get(attribute)

                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())

            for attribute in ("srcset", "data-srcset"):
                srcset = image.get(attribute)

                if not isinstance(srcset, str):
                    continue

                for entry in srcset.split(","):
                    entry = entry.strip()

                    if entry:
                        candidates.append(entry.split()[0])

            for candidate in candidates:
                if not candidate or candidate.startswith("data:"):
                    continue

                candidate = urljoin(url, candidate)
                parsed = urlparse(candidate)

                host = (parsed.hostname or "").lower()
                path = parsed.path or ""

                if parsed.scheme not in ("http", "https"):
                    continue

                if not (
                    host == "img.avito.st"
                    or host.endswith(".img.avito.st")
                ):
                    continue

                if not re.fullmatch(
                    r"/image/\d+/\d+\.[^/]+\.[^/]+",
                    path,
                ):
                    continue

                if "placeholder" in path.lower():
                    continue

                # Дедупликация без учёта query-параметров
                image_key = f"{host}{path}"

                if image_key in seen_image_keys:
                    continue

                seen_image_keys.add(image_key)

                image_url = urlunparse(
                    (
                        parsed.scheme,
                        parsed.netloc,
                        parsed.path,
                        "",
                        parsed.query,
                        "",
                    )
                )

                images.append(image_url)
                break

        return images

    # --------------------------- Применение данных ---------------------------

    def _apply_page_data(self, item: SiteParseData, data: dict) -> None:
        """Заполняет модель данными страницы объявления (null-safe)."""
        parameters: dict[str, str] = data["parameters"]

        # --- Основная информация -------------------------------------------
        if data["external_id"]:
            item.external_id = data["external_id"]

        if data["name"]:
            item.name = data["name"]

        if data["description"]:
            item.description = data["description"]

        if data["price"]:
            item.price = data["price"]

        if data["imgs"]:
            item.imgs = data["imgs"]

        item.photos_count = len(item.imgs)

        if data["residential_complex"]:
            item.residential_complex = data["residential_complex"]

        # --- Цена и условия сделки ------------------------------------------
        item.currency = "RUB"
        item.deal_type = "sale"

        item.deal_conditions = self._get_parameter(
            parameters,
            "Условия продажи",
        )

        sale_method = self._get_parameter(
            parameters,
            "Способ продажи",
        )
        if sale_method:
            item.sale_method = sale_method

        participation_type = self._get_parameter(
            parameters,
            "Тип участия",
        )
        if participation_type:
            item.participation_type = participation_type

        if "ипотек" in item.deal_conditions.casefold():
            item.mortgage_possible = True

        # --- Характеристики объекта -----------------------------------------
        property_details = self._parse_property_parameters(parameters, data["name"])

        if property_details["area"]:
            item.area = property_details["area"]

        if property_details["floor"]:
            item.floor = property_details["floor"]

        if property_details["rooms_count"]:
            item.rooms_count = property_details["rooms_count"]

        # --- Тип объекта (по данным страницы) --------------------------------
        item.object_type = self._detect_object_type(
            item.object_type,
            data["breadcrumbs"],
            item.rooms_count,
        )

        # --- Цена за квадратный метр (после уточнения площади) ---------------
        if item.price and item.area:
            item.price_per_meter = round(item.price / item.area)

        item.living_area = _to_float(
            self._get_parameter(parameters, "Жилая площадь")
        )
        item.kitchen_area = _to_float(
            self._get_parameter(parameters, "Площадь кухни")
        )
        item.floors_count = _to_int(
            self._get_parameter(parameters, "Этажей в доме")
        )
        item.ceiling_height = _to_float(
            self._get_parameter(parameters, "Высота потолков")
        )
        item.bathroom = self._get_parameter(parameters, "Санузел")
        item.balcony = self._get_parameter(
            parameters,
            "Балкон",
            "Лоджия",
            "Балкон/Лоджия",
        )
        item.window_view = self._get_parameter(parameters, "Окна")
        item.repairs = self._get_parameter(parameters, "Ремонт")
        item.finishing = self._get_parameter(parameters, "Отделка")

        # --- Информация о доме ----------------------------------------------
        breadcrumbs = data["breadcrumbs"]
        crumbs_text = " ".join(breadcrumbs).casefold()

        if "новостройки" in crumbs_text:
            item.housing_type = "новостройка"
        elif "вторичка" in crumbs_text or "квартиры" in crumbs_text:
            item.housing_type = "вторичка"

        item.building_status = item.housing_type
        item.year_building = _to_int(
            self._get_parameter(parameters, "Год постройки")
        )
        item.building_material = self._get_parameter(
            parameters,
            "Материал стен",
            "Тип дома",
        )
        item.building_section = self._get_parameter(
            parameters,
            "Корпус, строение",
        )
        item.completion_date = self._get_parameter(parameters, "Срок сдачи")

        item.elevators = self._extract_elevators(parameters)
        item.parking = self._get_parameter(parameters, "Парковка")

        courtyard = self._get_parameter(parameters, "Двор")
        if courtyard:
            item.courtyard = [
                part.strip()
                for part in courtyard.split(",")
                if part.strip()
            ]

        # --- Инженерия и участок --------------------------------------------
        item.heating = self._get_parameter(parameters, "Отопление")
        item.water_supply = self._get_parameter(parameters, "Водоснабжение")
        item.sewerage = self._get_parameter(parameters, "Канализация")
        item.gas = self._get_parameter(parameters, "Газ")
        item.electricity = self._get_parameter(parameters, "Электричество")
        item.internet_tv = self._get_parameter(parameters, "Интернет и ТВ")
        item.land_category = self._get_parameter(parameters, "Категория земель")

        land_area_text = self._get_parameter(parameters, "Площадь участка")

        if land_area_text:
            item.land_area = _to_float(land_area_text)

            if "га" in land_area_text.casefold():
                item.land_area_unit = "га"
            elif "сот" in land_area_text.casefold():
                item.land_area_unit = "сот."

        item.garage_type = self._get_parameter(parameters, "Тип гаража")
        item.security = self._get_parameter(parameters, "Охрана")
        item.recreation = self._get_parameter(parameters, "Для отдыха")
        item.terrace = self._get_parameter(
            parameters,
            "Терраса или веранда",
        )

        # --- Застройщик ------------------------------------------------------
        seller: dict = data["seller"]
        developer: dict = data["developer"]

        if developer.get("name"):
            item.developer = developer["name"]
        elif seller.get("type") == "Застройщик" and seller.get("name"):
            item.developer = seller["name"]

        if developer.get("foundation_year"):
            item.developer_foundation_year = developer["foundation_year"]

        if developer.get("completed_buildings"):
            item.developer_completed_buildings = developer["completed_buildings"]

        if developer.get("buildings_under_construction"):
            item.developer_buildings_under_construction = developer[
                "buildings_under_construction"
            ]

        # --- Продавец ---------------------------------------------------------
        if seller.get("name"):
            item.seller_name = seller["name"]

        if seller.get("type"):
            item.seller_type = seller["type"]

        if seller.get("rating"):
            item.seller_rating = seller["rating"]

        if seller.get("reviews_count"):
            item.seller_reviews_count = seller["reviews_count"]

        if seller.get("registered_year"):
            item.seller_registered_year = seller["registered_year"]

        if seller.get("ads_count"):
            item.seller_ads_count = seller["ads_count"]

        if seller.get("contact_person"):
            item.contact_person = seller["contact_person"]

        if "данные подтверждены" in " ".join(data["badges"]).casefold():
            item.seller_documents_verified = True
            item.is_verified = True

        # --- Геолокация --------------------------------------------------------
        coordinates: dict = data["coordinates"]

        if coordinates.get("lat") and coordinates.get("lon"):
            item.latitude = coordinates["lat"]
            item.longitude = coordinates["lon"]

        if data["geo_label"]:
            item.geo_label = data["geo_label"]

        # --- Навигация и маркетинг ---------------------------------------------
        if data["breadcrumbs"]:
            item.breadcrumbs = data["breadcrumbs"]

        if data["badges"]:
            item.badges = data["badges"]

        if data["feature_chips"]:
            item.feature_chips = data["feature_chips"]

        # --- Статистика ----------------------------------------------------------
        if data["publish_date"]:
            item.publish_date = data["publish_date"]
            item.update_date = data["publish_date"]

        item.views_count = data["views_count"]
        item.views_today = data["views_today"]

        # --- Сырые параметры -------------------------------------------------------
        if parameters:
            item.parameters = parameters

        self._warn_unfilled_fields(item, parameters)

    def _warn_unfilled_fields(
        self,
        item: SiteParseData,
        parameters: dict[str, str],
    ) -> None:
        """
        Логирует предупреждение, если характеристика присутствует на странице
        объявления, но соответствующее поле модели осталось пустым.

        Пустое поле без соответствующей подписи в параметрах — нормальная
        ситуация (условные поля: отопление есть только у домов, категория
        земель — только у участков и т. д.) и предупреждением не считается.
        """
        for field_name, labels in FIELD_PARAMETER_LABELS.items():
            found_labels = [
                label
                for label in labels
                if self._get_parameter(parameters, label)
            ]

            if not found_labels:
                continue

            value = getattr(item, field_name, None)

            if value in ("", 0, 0.0, [], None):
                logger.warning(
                    "Поле '%s' не заполнено, хотя на странице есть "
                    "параметр '%s' (url=%s)",
                    field_name,
                    found_labels[0],
                    item.url,
                )

    # --------------------------- Разбор характеристик ---------------------------

    @staticmethod
    def _detect_object_type(
        current_type: ObjectType,
        breadcrumbs: list[str],
        rooms_count: str,
    ) -> ObjectType:
        """
        Уточняет тип объекта по данным страницы объявления:
        хлебным крошкам и количеству комнат.
        """
        crumbs_text = " ".join(breadcrumbs).casefold()

        if rooms_count == "студия":
            return "studio"

        if "дом" in crumbs_text or "дач" in crumbs_text:
            return "house"

        if "земельн" in crumbs_text or "участки" in crumbs_text:
            return "land_plot"

        if "гараж" in crumbs_text or "машиноместо" in crumbs_text:
            return "garage"

        if "комнаты" in crumbs_text:
            return "room"

        if "квартиры" in crumbs_text and current_type == "other":
            return "flat"

        return current_type

    def _extract_elevators(self, parameters: dict[str, str]) -> list[str]:
        """Собирает сведения о лифтах («Пассажирский лифт: 1» и т. п.)."""
        elevators: list[str] = []

        for label, value in parameters.items():
            label_casefold = label.casefold()

            if "лифт" not in label_casefold:
                continue

            cleaned_label = label.strip()

            if cleaned_label.casefold().startswith("пассажирский"):
                cleaned_label = "пассажирский лифт"
            elif cleaned_label.casefold().startswith("грузовой"):
                cleaned_label = "грузовой лифт"

            elevators.append(f"{cleaned_label}: {value.strip()}")

        return elevators

    def _parse_property_parameters(
        self,
        parameters: dict[str, str],
        title: str = "",
    ) -> dict:
        """
        Разбирает основные характеристики (площадь, этаж, комнаты)
        из словаря параметров объявления с резерва в заголовке.
        """
        # --------------------------------------------------
        # Количество комнат — строка («1», «студия», «комната»)
        # --------------------------------------------------
        rooms_count = self._get_parameter(
            parameters,
            "Количество комнат",
            "Комнаты",
        )

        if rooms_count:
            match = re.search(
                r"^\s*(студи\w*|комната|\d+)",
                rooms_count,
                re.IGNORECASE,
            )

            if match:
                rooms_count = match.group(1).strip().lower()

                if rooms_count.startswith("студи"):
                    rooms_count = "студия"
            else:
                rooms_count = rooms_count.strip()
        else:
            rooms_count = self._parse_rooms_from_title(title)

        # --------------------------------------------------
        # Площадь — в первую очередь из «Общая площадь»
        # --------------------------------------------------
        area_text = self._get_parameter(
            parameters,
            "Общая площадь",
            "Площадь дома",
            "Площадь",
        )

        area = _to_float(area_text)

        if not area:
            area_match = re.search(
                r"(\d+(?:[.,]\d+)?)\s*(?:м²|м2|кв\.?\s*м)",
                title,
                re.IGNORECASE,
            )

            area = (
                _to_float(area_match.group(1))
                if area_match
                else 0.0
            )

        # --------------------------------------------------
        # Этаж — значение вида «4 из 25»
        # --------------------------------------------------
        floor_text = self._get_parameter(
            parameters,
            "Этаж",
        )

        floor = 0

        if floor_text:
            floor_match = re.search(
                r"^\s*(\d+)\s*(?:из\s+\d+)?",
                floor_text,
                re.IGNORECASE,
            )

            if floor_match:
                floor = int(floor_match.group(1))
        else:
            floor_match = re.search(
                r"(\d+)\s*/\s*\d+\s*(?:эт\.?|этаж)",
                title,
                re.IGNORECASE,
            )

            if not floor_match:
                floor_match = re.search(
                    r"(\d+)\s*(?:эт\.?|этаж)",
                    title,
                    re.IGNORECASE,
                )

            if floor_match:
                floor = int(floor_match.group(1))

        return {
            "area": area,
            "floor": floor,
            "rooms_count": rooms_count,
        }

    def _parse_property_from_title(self, title: str) -> dict:
        """
        Предварительный разбор характеристик (площадь, этаж, комнаты)
        из заголовка объявления. Используется для данных карточки списка;
        после открытия объявления значения заменяются данными страницы.
        """
        area_match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*(?:м²|м2|кв\.?\s*м)",
            title,
            re.IGNORECASE,
        )

        area = _to_float(area_match.group(1)) if area_match else 0.0

        floor_match = re.search(
            r"(\d+)\s*/\s*(\d+)\s*эт",
            title,
            re.IGNORECASE,
        )

        floor = int(floor_match.group(1)) if floor_match else 0

        rooms_count = self._parse_rooms_from_title(title)

        return {
            "area": area,
            "floor": floor,
            "rooms_count": rooms_count,
        }

    def _parse_rooms_from_title(self, title: str) -> str:
        """Резервное извлечение количества комнат из заголовка объявления."""
        match = re.search(
            r"(\d+)\s*[-–]?\s*к(?:\.\s*)?к?(?:омн)?",
            title,
            re.IGNORECASE,
        )

        if match:
            return match.group(1)

        if re.search(r"\bстуди[яию]\b", title, re.IGNORECASE):
            return "студия"

        return ""
