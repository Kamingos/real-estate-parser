import re
import webbrowser

from time import sleep
from random import uniform
from typing import Literal, TypeAlias
from urllib.parse import urljoin, urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from bs4 import BeautifulSoup
from bs4.element import Tag

from interfaces.parser_interfaces import IParcer
from model.parser_config import ParserConfig
from model.site_parse_data_model import SiteParseData, geoLabelDict


refs = {
    "flat/studio": "https://www.avito.ru/vladivostok/kvartiry/prodam-ASgBAgICAUSSA8YQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6Ik1Hbms0NVdCYU1SeElremciO33Do1akJgAAAA&localPriority=0&p={page}",
    "room": "https://www.avito.ru/vladivostok/komnaty/prodam-ASgBAgICAUSQA7wQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6Ims5ZkhvUUFwTGJicWR1cGEiO33Idg0EJgAAAA&localPriority=0&p={page}",
    "house": "https://www.avito.ru/vladivostok/doma_dachi_kottedzhi/prodam-ASgBAgICAUSUA9AQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6ImdBbjNKTGlKeGxEWDVKbngiO3367d43JgAAAA&localPriority=0&p={page}",
    "land_plot": "https://www.avito.ru/vladivostok/zemelnye_uchastki/prodam-ASgBAgICAUSWA9oQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6InNhQTVsSjhmV1pTZEo1aE8iO300GHrYJgAAAA&localPriority=0&p={page}",
    "garage": "https://www.avito.ru/vladivostok/garazhi_i_mashinomesta/prodam-ASgBAgICAUSYA~QQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6ImgyMXNNQ2VWQkxaNlQ0YkciO33mvNP-JgAAAA&localPriority=0&p={page}",
    "other": "https://www.avito.ru/vladivostok/kommercheskaya_nedvizhimost/prodam-ASgBAgICAUSwCNJW?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6Imo2SnJ2d0hOZElKdnNOMlkiO31-kt2FJgAAAA&f=ASgBAgICAkSwCNJW8hKg2gE&localPriority=0&p={page}",
}


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

    def __init__(self) -> None:
        super().__init__()

        self.options = Options()
        self.options.add_experimental_option(
            "excludeSwitches", ["enable-automation"]
        )
        self.options.add_experimental_option(
            "useAutomationExtension", False
        )
        self.options.add_argument(
            "--disable-blink-features=AutomationControlled"
        )

        # Для фонового режима раскомментируй следующую строку.
        # self.options.add_argument("--headless=new")

        self.object_types: dict[str, ObjectType] = {
            "flat/studio": "flat",
            "room": "room",
            "house": "house",
            "land_plot": "land_plot",
            "garage": "garage",
            "other": "other",
        }

    def parse(
        self,
        parserConfig: ParserConfig,
    ) -> tuple[bool, list[SiteParseData] | None]:

        offers_list: list[SiteParseData] = []
        seen_urls: set[str] = set()

        try:
            driver = webdriver.Chrome(options=self.options)
        except WebDriverException as error:
            print(f"[-] Avito: не удалось запустить Chrome: {error}")
            return False, None

        try:
            for category, url_template in refs.items():
                for page in range(1, parserConfig.max_page_iteration + 1):
                    page_url = url_template.format(page=page)

                    success, result = self._parsePage(
                        driver,
                        page_url,
                        category,
                    )

                    if not success or result is None:
                        print(
                            f"[-] Avito: не удалось получить страницу "
                            f"{page}, категория={category}"
                        )

                        answer = input(
                            "Проверить страницу и повторить? [y/n]: "
                        ).strip().lower()

                        if answer == "y":
                            webbrowser.open_new_tab(page_url)
                            input("После проверки нажмите Enter...")

                            success, result = self._parsePage(
                                driver,
                                page_url,
                                category,
                            )

                        if not success or result is None:
                            break

                    added_count = 0

                    for item in result:
                        if not item.url or item.url in seen_urls:
                            continue

                        seen_urls.add(item.url)
                        offers_list.append(item)
                        added_count += 1

                    print(
                        f"[+] Avito: добавлено {added_count} объявлений; "
                        f"категория={category}, страница={page}"
                    )

                    if not result:
                        break

                    if page < parserConfig.max_page_iteration:
                        sleep(
                            uniform(
                                parserConfig.min_iteration_time_span,
                                parserConfig.max_iteration_time_span,
                            )
                        )

            print(
                f"[+] Avito: всего собрано {len(offers_list)} объявлений"
            )
            return True, offers_list

        except Exception as error:
            print(f"[-] Avito: ошибка парсинга: {error}")
            return False, offers_list if offers_list else None

        finally:
            driver.quit()

    def _parsePage(
        self,
        driver: webdriver.Chrome,
        page_url: str,
        category: str,
    ) -> tuple[bool, list[SiteParseData] | None]:

        try:
            driver.get(page_url)

            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, '[data-marker="item"]')
                )
            )

        except TimeoutException:
            print(
                "[-] Avito: карточки не загрузились. "
                "Возможны CAPTCHA, пустая выдача или изменение разметки."
            )
            return False, None

        except WebDriverException as error:
            print(f"[-] Avito: ошибка загрузки страницы: {error}")
            return False, None

        soup = BeautifulSoup(driver.page_source, "html.parser")
        cards = self._find_cards(soup)

        if not cards:
            print("[-] Avito: карточки не найдены")
            return False, None

        results: list[SiteParseData] = []

        for card in cards:
            item = self._extract_card_data(card, page_url, category)

            if not item.url:
                continue

            location = self._get_location_text(card)

            if self._is_other_city(location):
                continue

            results.append(item)

        return True, results

    def _find_cards(self, soup: BeautifulSoup) -> list[Tag]:
        return list(soup.select('[data-marker="item"]'))

    def _extract_card_data(
        self,
        card: Tag,
        page_url: str,
        category: str,
    ) -> SiteParseData:

        title = card.select_one('[data-marker="item-title"]')
        name = title.get_text(" ", strip=True) if title else ""

        # Получаем ссылку непосредственно из карточки.
        url = self._extract_url(card, page_url)

        price_element = card.select_one('[data-marker="item-price"]')
        price = self._extract_price(price_element)

        description = self._extract_description(card)
        subtitles = self._extract_subtitles(card, title)
        location_text = self._get_location_text(card)
        images = self._extract_card_images(card)

        floor, area, rooms_count = self._extract_property_details(name)

        object_type = self.object_types[category]

        # Студия определяется по заголовку.
        if re.search(r"\bстуди[яиюи]\b", name, re.IGNORECASE):
            object_type = "studio"

        return SiteParseData(
            site="Avito",
            url=url,
            name=name,
            subtitles=subtitles,
            description=description,
            price=price,
            object_type=object_type,
            imgs=images,
            residential_complex=self._extract_residential_complex(card),
            floor=floor,
            area=area,
            rooms_count=rooms_count,
            geo_label=self._extract_geo_labels(location_text),
        )

    def _extract_url(self, card: Tag, page_url: str) -> str:
        """
        Avito использует ссылки вида:
        /vladivostok/kvartiry/kvartira-studiya_..._8374551255
        Поэтому нельзя проверять только наличие /obyavlenie/.
        """

        title = card.select_one('[data-marker="item-title"]')

        link: Tag | None = None

        if isinstance(title, Tag):
            if title.name == "a" and title.get("href"):
                link = title
            else:
                parent_link = title.find_parent("a", href=True)
                if isinstance(parent_link, Tag):
                    link = parent_link

        if link is None:
            link = card.select_one('a[data-marker="item-title"]')

        if link is None:
            return ""

        href = link.get("href")

        if not isinstance(href, str) or not href.strip():
            return ""

        url = urljoin(page_url, href.strip())
        parsed_url = urlparse(url)

        if parsed_url.netloc.lower() not in {
            "avito.ru",
            "www.avito.ru",
        }:
            return ""

        path = parsed_url.path.rstrip("/")
        last_segment = path.split("/")[-1]

        # У объявления Avito в конце URL обычно находится числовой ID.
        if not re.search(r"_\d{7,}$", last_segment):
            return ""

        # Удаляем параметры запроса, чтобы одна ссылка не считалась
        # разными объявлениями из-за context и других параметров.
        return f"https://www.avito.ru{path}"

    def _get_location_text(self, card: Tag) -> str:
        selectors = (
            '[data-marker="item-address"]',
            '[data-marker="item-location"]',
        )

        for selector in selectors:
            element = card.select_one(selector)

            if element:
                text = element.get_text(" ", strip=True)

                if text:
                    return text

        return ""

    def _is_other_city(self, location: str) -> bool:
        if not location:
            return False

        text = location.lower()

        if "владивосток" in text:
            return False

        first_part = text.split(",")[0].strip()

        return bool(
            re.match(
                r"^(?:г\.?\s+|город\s+)",
                first_part,
                re.IGNORECASE,
            )
        )

    def _extract_description(self, card: Tag) -> str:
        element = card.select_one('[data-marker="item-description"]')

        if element:
            return element.get_text(" ", strip=True)

        return ""

    def _extract_subtitles(
        self,
        card: Tag,
        title: Tag | None,
    ) -> str:

        element = card.select_one(
            '[data-marker="item-specific-params"]'
        )

        if not element:
            return ""

        text = element.get_text(" ", strip=True)

        if title:
            title_text = title.get_text(" ", strip=True)

            if text == title_text:
                return ""

        return text

    def _extract_residential_complex(self, card: Tag) -> str:
        for link in card.select("a[href]"):
            text = link.get_text(" ", strip=True)

            if not text:
                continue

            if re.search(
                r"^(?:жк\s*[«\"']?|жилой комплекс\s*[«\"']?)",
                text,
                re.IGNORECASE,
            ):
                text = re.split(
                    r"\s*[·•]\s*(?:\d+[,.]?\d*|отзыв)",
                    text,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0].strip()

                return text

        return ""

    def _extract_card_images(self, card: Tag) -> list[str]:
        result: list[str] = []

        for image in card.select("img"):
            candidates = [
                image.get("src"),
                image.get("data-src"),
                image.get("data-original"),
            ]

            srcset = image.get("srcset") or image.get("data-srcset")

            if isinstance(srcset, str):
                candidates.extend(
                    part.strip().split(" ")[0]
                    for part in srcset.split(",")
                    if part.strip()
                )

            for src in candidates:
                if not isinstance(src, str):
                    continue

                src = src.strip()

                if src.startswith("//"):
                    src = f"https:{src}"

                if not src.startswith("https://"):
                    continue

                if any(
                    marker in src.lower()
                    for marker in (
                        "stub_avatars",
                        "avatar",
                        "logo",
                    )
                ):
                    continue

                if src not in result:
                    result.append(src)

        return result

    def _extract_price(self, price_element: Tag | None) -> int:
        if price_element is None:
            return 0

        text = price_element.get_text(" ", strip=True)

        match = re.search(
            r"(\d[\d\s\u00a0]*)\s*(?:₽|руб\.?|р\.)",
            text,
            re.IGNORECASE,
        )

        if match:
            digits = re.sub(r"\D", "", match.group(1))
            return int(digits) if digits else 0

        digits = re.sub(r"\D", "", text)
        return int(digits) if digits else 0

    def _extract_property_details(
        self,
        name: str,
    ) -> tuple[int, float, int]:

        floor = 0
        area = 0.0
        rooms_count = 0

        area_match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*(?:м²|м2|кв\.?\s*м)",
            name,
            re.IGNORECASE,
        )

        if area_match:
            area = float(area_match.group(1).replace(",", "."))

        floor_match = re.search(
            r"(\d+)\s*/\s*\d+\s*(?:эт\.?|этаж)",
            name,
            re.IGNORECASE,
        )

        if floor_match:
            floor = int(floor_match.group(1))

        rooms_match = re.search(
            r"\b(\d+)\s*[-‑–]?\s*"
            r"(?:к(?:\.|\b)|комн\.?|комнатн\w*)",
            name,
            re.IGNORECASE,
        )

        if rooms_match:
            rooms_count = int(rooms_match.group(1))

        # У студии не указываем количество комнат.
        if re.search(r"\bстуди[яиюи]\b", name, re.IGNORECASE):
            rooms_count = 0

        return floor, area, rooms_count

    def _extract_geo_labels(self, location: str) -> geoLabelDict:
        geo_data: geoLabelDict = {
            "region": "Приморский край",
            "city": "Владивосток",
            "district": "",
            "micro_district": "",
            "street": "",
            "house": "",
        }

        if not location:
            return geo_data

        text = re.sub(r"\s+", " ", location).strip()
        parts = [
            part.strip(" .")
            for part in re.split(r"[,;]", text)
            if part.strip(" .")
        ]

        for part in parts:
            district_match = re.search(
                r"(?:^|\b)(?:р-н|район)\s*[:.]?\s*(.+)$",
                part,
                re.IGNORECASE,
            )

            if district_match and not geo_data["district"]:
                geo_data["district"] = district_match.group(1).strip(" .")

            micro_match = re.search(
                r"(?:^|\b)(?:мкр\.?|микрорайон)\s*[:.]?\s*(.+)$",
                part,
                re.IGNORECASE,
            )

            if micro_match and not geo_data["micro_district"]:
                geo_data["micro_district"] = (
                    micro_match.group(1).strip(" .")
                )

            # Улица.
            street_match = re.match(
                r"^(?:ул\.?|улица|пр-т|проспект|пер\.?|переулок|"
                r"ш\.?|шоссе|наб\.?|набережная|б-р|бульвар|"
                r"пл\.?|площадь)\s*(.+)$",
                part,
                re.IGNORECASE,
            )

            if street_match and not geo_data["street"]:
                street = street_match.group(1).strip(" .")

                # Убираем номер дома в конце сегмента.
                street = re.sub(
                    r"\s*,?\s*(?:(?:д(?:ом)?|стр(?:оение)?|"
                    r"корп(?:ус)?)\.?\s*)?\d+[а-яА-Яa-zA-Z]?"
                    r"(?:\s*/\s*\d+[а-яА-Яa-zA-Z]?)?\s*$",
                    "",
                    street,
                    flags=re.IGNORECASE,
                ).strip(" ,.")

                if street:
                    geo_data["street"] = street

            # Дом, строение или корпус — только по явному маркеру.
            house_match = re.search(
                r"\b(стр(?:оение)?|д(?:ом)?|корп(?:ус)?)"
                r"\.?\s*(\d+[а-яА-Яa-zA-Z]?"
                r"(?:\s*/\s*\d+[а-яА-Яa-zA-Z]?)?)",
                part,
                re.IGNORECASE,
            )

            if house_match and not geo_data["house"]:
                marker = house_match.group(1).lower()
                number = house_match.group(2).strip()

                if marker.startswith("стр"):
                    geo_data["house"] = f"стр. {number}"
                elif marker.startswith("корп"):
                    geo_data["house"] = f"корп. {number}"
                else:
                    geo_data["house"] = number

            # Формат «ул. Нейбута, 137».
            if (
                not geo_data["house"]
                and re.fullmatch(
                    r"\d+[а-яА-Яa-zA-Z]?"
                    r"(?:\s*/\s*\d+[а-яА-Яa-zA-Z]?)?",
                    part,
                )
            ):
                geo_data["house"] = part

        return geo_data