
import os
import re
import webbrowser

import requests

from dadata import Dadata

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
        with open("dadadata_token.txt", "r", encoding="utf-8") as key_file:
            self.dadata_api_key = str(key_file.read)
            
        self.dadata = Dadata(self.dadata_api_key)

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
        
        # self.refs = {
        #             "flat/studio": (
        #                 "https://www.avito.ru/vladivostok/kvartiry/prodam-ASgBAgICAUSSA8YQ"
        #                 "?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6Ik1Hbms0NVdCYU1SeElremciO33Do1akJgAAAA"
        #                 "&localPriority=0&p={page}"
        #             ),
        # }

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

        self.object_types: dict[str, ObjectType] = {
            "flat/studio": "flat",
            "room": "room",
            "house": "house",
            "land_plot": "land_plot",
            "garage": "garage",
            "other": "other",
        }

    def parse(self,parserConfig: ParserConfig,) -> tuple[bool, list[SiteParseData] | None]:
        driver = webdriver.Chrome(options=self.options)
        driver.set_page_load_timeout(PAGE_WAIT_TIME)

        offers: list[SiteParseData] = []

        try:
            for category, category_url in self.refs.items():
                object_type = self.object_types[category]

                for page in range(
                    1,
                    parserConfig.max_page_iteration + 1,
                ):
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
                            "Исправьте проблему в браузере и нажмите Enter "
                            "для повтора. Введите 'n' для пропуска: "
                        ).strip().lower()

                        if answer == "n":
                            break

                        # Повторяем ту же страницу.
                        continue

                    print(
                        f"[+] Avito: добавлено {len(page_offers)} объявлений; "
                        f"категория={category}, страница={page}"
                    )

                    if not page_offers:
                        break

                    offers.extend(page_offers)

                    # Пауза между страницами категории.
                    sleep(
                        uniform(
                            parserConfig.min_iteration_time_span,
                            parserConfig.max_iteration_time_span,
                        )
                    )

        finally:
            driver.quit()

        print(f"[=] Avito: добавлено {len(offers)} объявлений")

        return True, offers

    def _parsePage(
        self,
        driver: webdriver.Chrome,
        page_url: str,
        category: ObjectType,
    ) -> tuple[bool, list[SiteParseData]]:

        try:
            driver.get(page_url)

            WebDriverWait(driver, PAGE_WAIT_TIME).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, '[data-marker="item"]')
                )
            )

        except (TimeoutException, WebDriverException) as error:
            print(f"[-] Avito: ошибка загрузки списка: {error}")
            return False, []

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

            if (
                parsed_url.netloc
                and not parsed_url.netloc.endswith("avito.ru")
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

        # Подробные характеристики берём со страницы объявления.
        for index, item in enumerate(results, start=1):
            print(
                f"[Avito] Объявление {index}/{len(results)}: "
                f"{item.url}"
            )

            detail = self._extract_detail_data(driver, item.url)

            item.description = detail["description"]
            item.imgs = detail["images"]
            item.residential_complex = detail["residential_complex"]

            property_details = detail["property_details"]

            item.rooms_count = property_details["rooms_count"]
            item.area = property_details["area"]
            item.floor = property_details["floor"]

            # Адрес со страницы товара имеет приоритет над карточкой.
            if detail["location"]:
                item.geo_label = detail["location"]

            # Небольшая пауза, чтобы не создавать лишнюю нагрузку.
            sleep(uniform(1.5, 5))

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

        price = self._extract_price(
            card.select_one('[data-marker="item-price"]')
        )

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

        object_type: ObjectType = category

        if category == "flat" and re.search(
            r"\bстуди",
            name,
            re.IGNORECASE,
        ):
            object_type = "studio"

        geo_label = self._extract_geo_labels(location)

        # Значения с карточки — только предварительные.
        # После открытия объявления они будут заменены данными страницы.
        property_details = self._extract_property_details(
            f"{name} {subtitles}"
        )

        return SiteParseData(
            site="Avito",
            url=url,
            name=name,
            subtitles=subtitles,
            description="",
            price=price,
            object_type=object_type,
            imgs=[],
            residential_complex="",
            floor=property_details["floor"],
            area=property_details["area"],
            rooms_count=property_details["rooms_count"],
            geo_label=geo_label,
        )

    def _extract_detail_data(
        self,
        driver: webdriver.Chrome,
        url: str,
    ) -> dict:

        result = {
            "description": "",
            "images": [],
            "residential_complex": "",
            "location": "",
            "parameters": {},
            "property_details": {
                "area": 0.0,
                "floor": 0,
                "rooms_count": "",
            },
        }

        if not url:
            return result

        try:
            try:
                driver.get(url)
            except TimeoutException:
                # Продолжаем работу с уже полученным DOM.
                try:
                    driver.execute_script("window.stop();")
                except WebDriverException:
                    pass

            # Ждём появления галереи, но не полной загрузки всех фото.
            try:
                WebDriverWait(driver, PAGE_WAIT_TIME).until(
                    EC.presence_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            "div#bx_item-gallery, "
                            'div[data-marker="item-view/main-gallery"]',
                        )
                    )
                )
            except TimeoutException:
                pass

            soup = BeautifulSoup(driver.page_source, "html.parser")

            # --------------------------------------------------
            # 1. Описание
            # --------------------------------------------------
            description_element = soup.select_one(
                '[data-marker="item-view/item-description"]'
            )

            if description_element is None:
                description_element = soup.select_one(
                    '[data-marker*="item-description"]'
                )

            if description_element:
                result["description"] = description_element.get_text(
                    " ",
                    strip=True,
                )

            # --------------------------------------------------
            # 2. Характеристики объявления
            # --------------------------------------------------
            parameters = self._extract_detail_parameters(soup)
            result["parameters"] = parameters

            result["property_details"] = self._extract_property_details(
                soup.get_text(" ", strip=True),
                parameters,
            )

            # --------------------------------------------------
            # 3. Название жилого комплекса
            # --------------------------------------------------
            result["residential_complex"] = (
                self._extract_residential_complex_from_page(soup)
            )

            # --------------------------------------------------
            # 4. Адрес объявления
            # --------------------------------------------------
            result["location"] = self._extract_location_from_page(soup)

            # --------------------------------------------------
            # 5. Фотографии только из галереи
            # --------------------------------------------------
            gallery = (
                soup.select_one("div#bx_item-gallery")
                or soup.select_one(
                    'div[data-marker="item-view/main-gallery"]'
                )
                or soup.select_one('[data-marker="item-view/gallery"]')
            )

            if gallery is None:
                return result

            images: list[str] = []
            seen_image_keys: set[str] = set()

            for image in gallery.select("img"):
                if image.find_parent("svg"):
                    continue

                # Не берём изображения из рекламных/ипотечных блоков.
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

                    # Дедупликация без учёта query-параметров.
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

            result["images"] = images

        except Exception as error:
            print(f"[-] Avito: ошибка обработки {url}: {error}")

        return result

    def _extract_detail_parameters(
        self,
        soup: BeautifulSoup,
    ) -> dict[str, str]:
        """
        Извлекает параметры вида:
        «Количество комнат: 1», «Общая площадь: 32.5 м²» и т. д.
        """

        parameters: dict[str, str] = {}

        for li in soup.select("li"):
            label_element = li.find("span")

            if label_element is None:
                continue

            label = label_element.get_text(
                " ",
                strip=True,
            ).rstrip(":").strip()

            if not label:
                continue

            # Работаем с копией текста: не изменяем исходную страницу.
            value_parts = []

            for child in li.find_all(
                recursive=False
            ):
                if child is label_element:
                    continue

                value_parts.append(
                    child.get_text(" ", strip=True)
                    if isinstance(child, Tag)
                    else str(child).strip()
                )

            # Удаляем из полного текста li название характеристики.
            full_text = li.get_text(" ", strip=True)
            label_text = label_element.get_text(" ", strip=True)

            value = full_text.replace(label_text, "", 1)
            value = re.sub(r"\s+", " ", value).strip(" :\u00a0")

            if value:
                parameters[label] = value

        return parameters

    def _get_parameter(
        self,
        parameters: dict[str, str],
        *names: str,
    ) -> str:

        normalized = {
            re.sub(r"\s+", " ", key).strip().casefold(): value.strip()
            for key, value in parameters.items()
        }

        for name in names:
            key = re.sub(
                r"\s+",
                " ",
                name,
            ).strip().casefold()

            value = normalized.get(key, "")

            if value:
                return value

        return ""

    def _extract_property_details(
        self,
        text: str,
        parameters: dict[str, str] | None = None,
    ) -> dict:

        parameters = parameters or {}

        # --------------------------------------------------
        # Количество комнат — строка или пустое значение
        # --------------------------------------------------
        rooms_count = self._get_parameter(
            parameters,
            "Количество комнат",
            "Комнаты",
        )

        if rooms_count:
            match = re.search(
                r"^\s*(студия|студи[яию]|комната|\d+)",
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
            match = re.search(
                r"количество комнат\s*:\s*(студия|\d+)",
                text,
                re.IGNORECASE,
            )

            if match:
                rooms_count = match.group(1).strip().lower()
            else:
                match = re.search(
                    r"(\d+)\s*[-–]?\s*комн(?:ат(?:а|ы)?)?\.?",
                    text,
                    re.IGNORECASE,
                )

                if match:
                    rooms_count = match.group(1)
                elif re.search(
                    r"\bстуди[яию]\b",
                    text,
                    re.IGNORECASE,
                ):
                    rooms_count = "студия"
                else:
                    rooms_count = ""

        # --------------------------------------------------
        # Площадь — в первую очередь из «Общая площадь»
        # --------------------------------------------------
        area_text = self._get_parameter(
            parameters,
            "Общая площадь",
            "Площадь",
        )

        area_match = re.search(
            r"(\d+(?:[.,]\d+)?)",
            area_text,
        )

        if area_match:
            area = float(
                area_match.group(1).replace(",", ".")
            )
        else:
            area_match = re.search(
                r"(\d+(?:[.,]\d+)?)\s*(?:м²|м2|кв\.?\s*м)",
                text,
                re.IGNORECASE,
            )

            area = (
                float(area_match.group(1).replace(",", "."))
                if area_match
                else 0.0
            )

        # --------------------------------------------------
        # Этаж — значение вида «2 из 9»
        # --------------------------------------------------
        floor_text = self._get_parameter(
            parameters,
            "Этаж",
        )

        floor_match = re.search(
            r"^\s*(\d+)\s*(?:из\s+\d+)?",
            floor_text,
            re.IGNORECASE,
        )

        if not floor_match:
            floor_match = re.search(
                r"(\d+)\s*/\s*\d+\s*(?:эт\.?|этаж)",
                text,
                re.IGNORECASE,
            )

        if not floor_match:
            floor_match = re.search(
                r"(\d+)\s*(?:эт\.?|этаж)",
                text,
                re.IGNORECASE,
            )

        floor = (
            int(floor_match.group(1))
            if floor_match
            else 0
        )

        return {
            "area": area,
            "floor": floor,
            "rooms_count": rooms_count,
        }

    def _extract_residential_complex_from_page(
        self,
        soup: BeautifulSoup,
    ) -> str:

        selectors = [
            '[data-marker="item-view/residential-complex"]',
            '[data-marker="item-residential-complex"]',
            '[data-marker="item-complex-name"]',
        ]

        for selector in selectors:
            element = soup.select_one(selector)

            if element:
                value = element.get_text(" ", strip=True)

                if value and self._looks_like_complex_name(value):
                    return value

        # Резервный вариант: только заголовки, явно похожие на название ЖК.
        for heading in soup.select(
            'h4[style*="--module-max-lines-size"]'
        ):
            value = heading.get_text(" ", strip=True)

            if self._looks_like_complex_name(value):
                return value

        return ""

    def _looks_like_complex_name(self, value: str) -> bool:
        if not value:
            return False

        # Название должно явно обозначать жилой комплекс.
        if not re.match(
            r"^(?:ЖК\b|жилой комплекс\b)",
            value,
            re.IGNORECASE,
        ):
            return False

        # Исключаем рекламные фразы и заголовки других блоков.
        excluded = (
            "скидка",
            "трейд-ин",
            "ипотека",
            "выгода",
            "лёгкий старт",
            "легкий старт",
            "о доме",
            "условия продажи",
        )

        return not any(
            phrase in value.casefold()
            for phrase in excluded
        )

    def _extract_price(self, price_element: Tag | None) -> int:
        """Извлекает числовую цену из элемента карточки объявления."""
        if price_element is None:
            return 0
        price_text = price_element.get_text(" ", strip=True)
        digits = re.sub(r"\D", "", price_text)
        return int(digits) if digits else 0

    def _extract_geo_labels(self, location: str = "") -> geoLabelDict:
        """Возвращает пустые поля географии до получения адреса через DaData.

        Текстовый адрес Avito намеренно не разбирается: адресные поля
        заполняются только по координатам с карты объявления.
        """
        return {
            "region": "",
            "city": "",
            "district": "",
            "micro_district": "",
            "street": "",
            "house": "",
        }

#
    def _extract_location_from_page(self,  soup: BeautifulSoup,) -> geoLabelDict | None:
        """
        Получает координаты из data-map-lat/data-map-lon
        и определяет адрес через библиотеку DaData.
        """
        map_element = soup.select_one(
            '[data-marker="item-map-wrapper"][data-map-lat][data-map-lon]'
        )

        if map_element is None:
            return None

        
        lat_value = map_element.get("data-map-lat")
        lon_value = map_element.get("data-map-lon")

        if not isinstance(lat_value, str) or not isinstance(lon_value, str):
            print("[-] Avito: не удалось прочитать координаты объявления")
            return None

        try:
            lat = float(lat_value)
            lon = float(lon_value)
        except ValueError:
            print("[-] Avito: некорректный формат координат")
            return None
        

        try:
            result = self.dadata.geolocate(
                name="address",
                lat=lat,
                lon=lon,
            )
        except Exception as error:
            print(f"[-] DaData: ошибка получения адреса: {error}")
            return None

        if not result:
            print(
                f"[-] DaData: адрес не найден "
                f"для координат {lat}, {lon}"
            )
            return None

        # Библиотека возвращает список подсказок с полем data.
        address = result[0].get("data", {})

        return {
            "region": address.get("region", "") or "",
            "city": address.get("city", "") or "",
            "district": address.get("city_district", "") or "",
            "micro_district": address.get("settlement", "") or "",
            "street": address.get("street", "") or "",
            "house": address.get("house", "") or "",
        }
#
