import re
import webbrowser

from urllib.parse import urljoin, urlparse, urlunparse
from time import sleep
from random import uniform
from typing import Literal, TypeAlias

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from bs4 import BeautifulSoup
from bs4.element import Tag

from interfaces.parser_interfaces import IParcer
from model.parser_config import ParserConfig
from model.site_parse_data_model import SiteParseData, geoLabelDict

PAGE_WAIT_TIME = 10

ObjectType: TypeAlias = Literal[
    "flat",
    "room",
    "studio",
    "house",
    "land_plot",
    "garage",
    "other",
]

class AvitoParser(IParcer):
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
        
        self.options = Options()
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
        self.options.page_load_strategy = "eager"
        
        # self.options.add_argument("--headless=new")

        self.object_types: dict[str, ObjectType] = {
            "flat/studio": "flat",
            "room": "room",
            "house": "house",
            "land_plot": "land_plot",
            "garage": "garage",
            "other": "other",
        }

    def parse(self, parserConfig: ParserConfig) -> tuple[bool, list[SiteParseData] | None]:
        driver = webdriver.Chrome(options=self.options)
        driver.set_page_load_timeout(PAGE_WAIT_TIME)

        offers: list[SiteParseData] = []
        
        offers: list[SiteParseData] = []

        try:
            for category, category_url in self.refs.items():
                object_type = self.object_types[category]

                for page in range( 1, parserConfig.max_page_iteration + 1,): 
                    page_url = category_url.format(page=page)

                    success, page_offers = self._parsePage(
                        driver,
                        page_url,
                        object_type,
                    )

                    if not success:
                        print(
                            f"[-] Avito: не удалось загрузить страницу "
                            f"категории={category}, страница={page}"
                        )

                        answer = input(
                            "Откройте страницу в браузере и устраните "
                            "проблему, затем нажмите Enter для повтора. "
                            "Введите 'n' для пропуска: "
                        ).strip().lower()

                        if answer == "n":
                            break

                        page-=1
                        continue

                    print(
                        f"[+] Avito: добавлено {len(page_offers)} объявлений; "
                        f"категория={category}, страница={page}"
                    )

                    if not page_offers:
                        break

                    offers.extend(page_offers)

                    sleep(
                        uniform(
                            parserConfig.min_iteration_time_span,
                            parserConfig.max_iteration_time_span,
                        )
                    )

        finally:
            driver.quit()

        return True, offers

    def _parsePage(self, driver: webdriver.Chrome, page_url: str, category: ObjectType) -> tuple[bool, list[SiteParseData]]:
        try:
            driver.get(page_url)

            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, '[data-marker="item"]')
                )
            )

        except TimeoutException:
            return False, []

        # TODO: можно добавить сюда скролл

        soup = BeautifulSoup(driver.page_source, "html.parser")
        cards = self._find_cards(soup)

        results: list[SiteParseData] = []
        seen_urls: set[str] = set()

        for card in cards:
            item = self._extract_card_data(
                card,
                page_url,
                category,
            )

            if item is None or not item.url:
                continue

            parsed_url = urlparse(item.url)

            if parsed_url.netloc and not parsed_url.netloc.endswith(
                "avito.ru"
            ):
                continue

            if not parsed_url.path.startswith("/vladivostok/"):
                continue

            if not re.search(r"\d{8,}/?$", parsed_url.path):
                continue

            canonical_url = urlunparse(
                (
                    parsed_url.scheme or "https",
                    parsed_url.netloc or "www.avito.ru",
                    parsed_url.path,
                    "",
                    "",
                    "",
                )
            )

            if canonical_url in seen_urls:
                continue

            seen_urls.add(canonical_url)

            item.url = canonical_url
            item.site = "Avito"

            results.append(item)

        # Описание и фотографии получаем со страницы каждого объявления.
        for index, item in enumerate(results, start=1):
            print(
                f"[Avito] Объявление {index}/{len(results)}: "
                f"{item.url}"
            )

            description, images, complex_name = self._extract_detail_data(
                driver,
                item.url,
            )

            item.description = description
            item.imgs = images

            # Если название комплекса найдено на странице объявления,
            # используем его. Иначе оставляем значение из карточки.
            if complex_name:
                item.residential_complex = complex_name

            # Небольшая пауза между объявлениями.
            sleep(uniform(1, 7))

        return True, results

    def _find_cards(self, soup: BeautifulSoup) -> list[Tag]:
        return soup.select('[data-marker="item"]')

    def _extract_card_data(
        self,
        card: Tag,
        page_url: str,
        category: ObjectType,
    ) -> SiteParseData | None:
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
        parsed_url = urlparse(url)

        url = urlunparse(
            (
                parsed_url.scheme or "https",
                parsed_url.netloc or "www.avito.ru",
                parsed_url.path,
                "",
                "",
                "",
            )
        )

        name = title_element.get_text(" ", strip=True)

        price_element = card.select_one(
            '[data-marker="item-price"]'
        )

        price = self._extract_price(price_element)

        subtitles_element = (
            card.select_one('[data-marker="item-specific-params"]')
            or card.select_one('[data-marker="item-subtitle"]')
            or card.select_one('[data-marker="item-description"]')
        )

        subtitles = (
            subtitles_element.get_text(" ", strip=True)
            if subtitles_element
            else ""
        )

        location_element = (
            card.select_one('[data-marker="item-address"]')
            or card.select_one('[data-marker="item-location"]')
            or card.select_one('[data-marker="item-address-line"]')
        )

        location = (
            location_element.get_text(" ", strip=True)
            if location_element
            else ""
        )

        residential_complex = self._extract_residential_complex(card)

        property_details = self._extract_property_details(
            f"{name} {subtitles}"
        )

        object_type: ObjectType = category

        if category == "flat" and "студи" in name.lower():
            object_type = "studio"

        geo_label = self._extract_geo_labels(location)

        return SiteParseData(
            site="Avito",
            url=url,
            name=name,
            subtitles=subtitles,
            description="",
            price=price,
            object_type=object_type,
            imgs=[],
            residential_complex=residential_complex,
            floor=property_details["floor"],
            area=property_details["area"],
            rooms_count=property_details["rooms_count"],
            geo_label=geo_label,
        )

    #
    def _extract_detail_data(
        self,
        driver: webdriver.Chrome,
        url: str,
    ) -> tuple[str, list[str], str]:
        """
        Извлекает со страницы объявления:
        - описание;
        - фотографии только из bx_item-gallery;
        - название из подходящего элемента h4.

        Не ждёт загрузки всех изображений страницы.
        """
        if not url:
            return "", [], ""

        description = ""
        residential_complex = ""
        images: list[str] = []
        seen_image_keys: set[str] = set()

        try:
            try:
                driver.get(url)
            except TimeoutException:
                # Если загрузка затянулась, останавливаем её
                # и пробуем использовать уже полученный HTML.
                try:
                    driver.execute_script("window.stop();")
                except Exception:
                    pass

            # Ждём появления галереи не дольше 5 секунд.
            # Это ожидание нужно только для появления DOM-элемента,
            # а не для загрузки самих фотографий.
            try:
                WebDriverWait(driver, PAGE_WAIT_TIME).until(
                    EC.presence_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            (
                                "div#bx_item-gallery, "
                                'div[data-marker="item-view/main-gallery"]'
                            ),
                        )
                    )
                )
            except TimeoutException:
                pass

            soup = BeautifulSoup(driver.page_source, "html.parser")

            # --------------------------------------------------
            # 1. Описание объявления
            # --------------------------------------------------
            description_element = soup.select_one(
                '[data-marker="item-view/item-description"]'
            )

            if description_element:
                description = description_element.get_text(
                    " ",
                    strip=True,
                )

            # Резервный вариант, если data-marker изменился.
            if not description:
                description_element = soup.select_one(
                    '[data-marker*="item-description"]'
                )

                if description_element:
                    description = description_element.get_text(
                        " ",
                        strip=True,
                    )

            # --------------------------------------------------
            # 2. Название жилого комплекса или другого объекта
            # --------------------------------------------------
            gallery = soup.select_one("div#bx_item-gallery")

            if gallery is None:
                gallery = soup.select_one(
                    'div[data-marker="item-view/main-gallery"]'
                )

            # Ищем h4 с указанным стилем.
            # Классы Avito часто меняются, поэтому не привязываемся
            # к длинному набору случайных CSS-классов.
            for heading in soup.select(
                'h4[style*="--module-max-lines-size"]'
            ):
                # Не берём заголовки из самой галереи.
                if gallery is not None and (
                    heading is gallery or gallery in heading.parents
                ):
                    continue

                text = heading.get_text(" ", strip=True)

                if text:
                    residential_complex = text
                    break

            # --------------------------------------------------
            # 3. Фотографии — исключительно из галереи объявления
            # --------------------------------------------------
            if gallery is None:
                return description, [], residential_complex

            for image in gallery.select("img"):
                # Исключаем рекламные блоки ипотеки.
                if image.find_parent(
                    attrs={
                        "data-marker": re.compile(
                            r"mortgage",
                            re.IGNORECASE,
                        )
                    }
                ):
                    continue

                # Пропускаем SVG и логотипы.
                if image.find_parent("svg"):
                    continue

                candidates: list[str] = []

                # Обычные URL и атрибуты отложенной загрузки.
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

                # Извлекаем варианты из srcset.
                for attribute in ("srcset", "data-srcset"):
                    srcset = image.get(attribute)

                    if not isinstance(srcset, str):
                        continue

                    # Обычно srcset содержит URL, затем размер:
                    # https://... 640w, https://... 1280w
                    for entry in srcset.split(","):
                        entry = entry.strip()

                        if entry:
                            candidates.append(entry.split()[0])

                # Выбираем первую корректную ссылку.
                for candidate in candidates:
                    if not candidate or candidate.startswith("data:"):
                        continue

                    candidate = urljoin(url, candidate)
                    parsed = urlparse(candidate)

                    host = (parsed.hostname or "").lower()
                    path = parsed.path or ""

                    if parsed.scheme not in ("http", "https"):
                        continue

                    # Только хосты изображений Avito.
                    if not (
                        host == "img.avito.st"
                        or host.endswith(".img.avito.st")
                    ):
                        continue

                    # Полный путь изображения должен содержать
                    # идентификатор и второй сегмент после точки.
                    if not re.fullmatch(
                        r"/image/\d+/\d+\.[^/]+\.[^/]+",
                        path,
                    ):
                        continue

                    if path.lower().endswith(".svg"):
                        continue

                    if "placeholder" in path.lower():
                        continue

                    # Убираем дубли с разными query-параметрами.
                    image_key = f"{host}{path}"

                    if image_key in seen_image_keys:
                        continue

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

                    seen_image_keys.add(image_key)
                    images.append(image_url)

                    # Переходим к следующему img.
                    break

        except Exception as error:
            print(
                f"[-] Avito: ошибка обработки {url}: {error}"
            )

        return description, images, residential_complex
    #

    def _extract_price(self, price_element: Tag | None) -> int:
        if price_element is None:
            return 0

        price_text = price_element.get_text(" ", strip=True)
        digits = re.sub(r"\D", "", price_text)

        return int(digits) if digits else 0

    def _extract_property_details(self, text: str) -> dict:
        area = 0.0
        floor = 0
        rooms_count = 0

        area_match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*(?:м²|м2|кв\.?\s*м)",
            text,
            re.IGNORECASE,
        )

        if area_match:
            area = float(area_match.group(1).replace(",", "."))

        floor_match = re.search(
            r"(\d+)\s*/\s*(\d+)\s*(?:эт\.?|этаж)",
            text,
            re.IGNORECASE,
        )

        if floor_match:
            floor = int(floor_match.group(1))
        else:
            floor_match = re.search(
                r"(\d+)\s*(?:эт\.?|этаж)",
                text,
                re.IGNORECASE,
            )

            if floor_match:
                floor = int(floor_match.group(1))

        rooms_match = re.search(
            r"(\d+)\s*[-–]?\s*(?:комн\.?|комнат)",
            text,
            re.IGNORECASE,
        )

        if rooms_match:
            rooms_count = int(rooms_match.group(1))
        elif re.search(r"\bстуди", text, re.IGNORECASE):
            rooms_count = 1

        return {
            "area": area,
            "floor": floor,
            "rooms_count": rooms_count,
        }

    def _extract_residential_complex(self, card: Tag) -> str:
        element = (
            card.select_one('[data-marker="item-residential-complex"]')
            or card.select_one('[data-marker="item-complex-name"]')
        )

        return (
            element.get_text(" ", strip=True)
            if element
            else ""
        )

    def _extract_geo_labels(self, location: str) -> geoLabelDict:
        geo_label: geoLabelDict = {
            "region": "Приморский край",
            "city": "Владивосток",
            "district": "",
            "micro_district": "",
            "street": "",
            "house": "",
        }

        if not location:
            return geo_label

        parts = [
            part.strip()
            for part in re.split(r"[,;]", location)
            if part.strip()
        ]

        house_pattern = re.compile(
            r"^(?:д\.?|дом|стр\.?|строение|корп\.?|корпус)\s*"
            r"([\w/-]+)",
            re.IGNORECASE,
        )

        street_pattern = re.compile(
            r"^(?:ул\.?|улица|пр-т|проспект|пер\.?|переулок|"
            r"ш\.?|шоссе|наб\.?|набережная)\s*.+",
            re.IGNORECASE,
        )

        for part in parts:
            if re.search(
                r"владивосток",
                part,
                re.IGNORECASE,
            ):
                geo_label["city"] = "Владивосток"
                continue

            if re.search(
                r"приморский край",
                part,
                re.IGNORECASE,
            ):
                geo_label["region"] = "Приморский край"
                continue

            house_match = house_pattern.match(part)

            if house_match:
                geo_label["house"] = house_match.group(1)
                continue

            if street_pattern.match(part):
                street_match = re.search(
                    r"^(?:ул\.?|улица|пр-т|проспект|пер\.?|переулок|"
                    r"ш\.?|шоссе|наб\.?|набережная)\s*(.+)$",
                    part,
                    re.IGNORECASE,
                )

                if street_match:
                    street_value = street_match.group(1).strip()
                    number_match = re.search(
                        r",?\s*(?:д\.?|дом)?\s*(\d+[\w/-]*)$",
                        street_value,
                        re.IGNORECASE,
                    )

                    if number_match:
                        geo_label["house"] = number_match.group(1)
                        street_value = street_value[
                            :number_match.start()
                        ].strip(" ,")

                    geo_label["street"] = street_value

                continue

            if re.search(
                r"район|р-н",
                part,
                re.IGNORECASE,
            ):
                geo_label["district"] = part
                continue

            if re.search(
                r"микрорайон|мкр\.?",
                part,
                re.IGNORECASE,
            ):
                geo_label["micro_district"] = part
                continue

            if not geo_label["street"]:
                number_match = re.search(
                    r",?\s*(?:д\.?|дом)?\s*(\d+[\w/-]*)$",
                    part,
                    re.IGNORECASE,
                )

                if number_match and re.search(
                    r"[а-яё]",
                    part,
                    re.IGNORECASE,
                ):
                    geo_label["house"] = number_match.group(1)
                    geo_label["street"] = part[
                        :number_match.start()
                    ].strip(" ,")

        return geo_label
