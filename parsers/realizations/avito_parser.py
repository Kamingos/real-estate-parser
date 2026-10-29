import re
import webbrowser

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


refs = {
    "flat/studio": "https://www.avito.ru/vladivostok/kvartiry/prodam-ASgBAgICAUSSA8YQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6Ik1Hbms0NVdCYU1SeElremciO33Do1akJgAAAA&localPriority=0&p={page}",
    "room": "https://www.avito.ru/vladivostok/komnaty/prodam-ASgBAgICAUSQA7wQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6Ims5ZkhvUUFwTGJicWR1cGEiO33Idg0EJgAAAA&localPriority=0&p={page}",
    "house": "https://www.avito.ru/vladivostok/doma_dachi_kottedzhi/prodam-ASgBAgICAUSUA9AQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6ImdBbjNKTGlKeGxEWDVKbngiO3367d43JgAAAA&localPriority=0&p={page}",
    "land_plot": "https://www.avito.ru/vladivostok/zemelnye_uchastki/prodam-ASgBAgICAUSWA9oQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6InNhQTVsSjhmV1pTZEo1aE8iO300GHrYJgAAAA&localPriority=0&p={page}",
    "garage": "https://www.avito.ru/vladivostok/garazhi_i_mashinomesta/prodam-ASgBAgICAUSYA~QQ?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6ImgyMXNNQ2VWQkxaNlQ0YkciO33mvNP-JgAAAA&localPriority=0&p={page}",
    "other": "https://www.avito.ru/vladivostok/kommercheskaya_nedvizhimost/prodam-ASgBAgICAUSwCNJW?context=H4sIAAAAAAAA_wEmANn_YToxOntzOjE6InkiO3M6MTY6Imo2SnJ2d0hOZElKdnNOMlkiO31-kt2FJgAAAA&f=ASgBAgICAkSwCNJW8hKg2gE&localPriority=0&p={page}"
}

ObjectType: TypeAlias = Literal[
    "flat", "room", "studio", "house",
    "land_plot", "garage", "other"
]

class AvitoParser(IParcer):

    def __init__(self) -> None:
        super().__init__()

        self.options = Options()
        # Отключает флаг enable-automation в настройках браузера
        self.options.add_experimental_option("excludeSwitches", ["enable-automation"])
        # Отключает автоматическое расширение Selenium
        self.options.add_experimental_option('useAutomationExtension', False)
        # Отключает специальный флаг Blink, помечающий браузер как управляемый
        self.options.add_argument("--disable-blink-features=AutomationControlled")

        # Если нужно, можно включить фоновый режим.
        # self.options.add_argument("--headless=new")

        self.object_types: dict[str, ObjectType] = {
            "flat/studio": "flat",
            "room": "room",
            "house": "house",
            "land_plot": "land_plot",
            "garage": "garage",
            "other": "other"
        }

    def parse(
        self,
        parserConfig: ParserConfig
    ) -> tuple[bool, list[SiteParseData] | None]:

        offers_list: list[SiteParseData] = []
        driver = webdriver.Chrome(options=self.options)

        try:
            for category, url_template in refs.items():

                for page in range(1, parserConfig.max_page_iteration + 1):
                    page_url = url_template.format(page=page)

                    success, result = self._parsePage(
                        driver,
                        page_url,
                        category
                    )

                    if not success or result is None:
                        print(
                            f"[-] Avito: не удалось получить "
                            f"страницу {page}, категория {category}"
                        )

                        answer = input(
                            "Проверить страницу в браузере "
                            "и попробовать снова? [y/n]: "
                        ).lower()

                        if answer == "y":
                            webbrowser.open_new_tab(page_url)
                            input("После проверки нажмите Enter...")
                            success, result = self._parsePage(
                                driver,
                                page_url,
                                category
                            )

                        if not success or result is None:
                            break

                    offers_list.extend(result)

                    print(
                        f"[+] Avito: добавлено {len(result)} объявлений; "
                        f"категория={category}, страница={page}"
                    )

                    if len(result) == 0:
                        break

                    if page < parserConfig.max_page_iteration:
                        sleep(uniform(
                            parserConfig.min_iteration_time_span,
                            parserConfig.max_iteration_time_span
                        ))

            print(f"[+] Avito: всего собрано {len(offers_list)} объявлений")
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
        category: str
    ) -> tuple[bool, list[SiteParseData] | None]:

        try:
            driver.get(page_url)

            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, '[data-marker="item"]')
                )
            )

        except TimeoutException:
            print("[-] Avito: карточки не загрузились или изменилась разметка")
            return False, None

        soup = BeautifulSoup(driver.page_source, "html.parser")

        cards = self._find_cards(soup)
        results: list[SiteParseData] = []

        #
        for card in cards:
            item = self._extract_card_data(card, page_url, category)

            location_element = (
                card.select_one('[data-marker="item-address"]')
                or card.select_one('[data-marker="item-location"]')
            )

            location_text = (
                location_element.get_text(" ", strip=True)
                if location_element
                else ""
            ).lower()

            # Пропускаем объявления только при явно указанном другом городе.
            if location_text:
                first_part = location_text.split(",")[0].strip()

                if first_part.startswith("г. ") and "владивосток" not in first_part:
                    continue

            item.site = "Avito"
            results.append(item)
        #

        if not cards:
            return False, None

        return True, results

    def _find_cards(self, soup: BeautifulSoup) -> list[Tag]:
        return list(
            soup.select('[data-marker="item"]')
        )

    def _extract_card_data(
        self,
        card: Tag,
        page_url: str,
        category: str
    ) -> SiteParseData:

        title = card.select_one('[data-marker="item-title"]')

        #
        link = None

        if isinstance(title, Tag):
            if title.name == "a" and title.get("href"):
                link = title
            else:
                link = title.find_parent("a", href=True)

        if not isinstance(link, Tag):
            link = card.select_one("a[data-marker='item-title'][href]")

        url = page_url

        if isinstance(link, Tag):
            href = link.get("href", "")

            if isinstance(href, str) and href:
                url = (
                    "https://www.avito.ru" + href
                    if href.startswith("/")
                    else href
                )
        #

        name = title.get_text(" ", strip=True) if title else ""

        price_element = card.select_one('[data-marker="item-price"]')
        price = self._extract_price(price_element)

        description_element = card.select_one(
            '[data-marker="item-description"]'
        )

        description = (
            description_element.get_text(" ", strip=True)
            if description_element
            else ""
        )

        location_element = (
            card.select_one('[data-marker="item-address"]')
            or card.select_one('[data-marker="item-location"]')
        )

        location_text = (
            location_element.get_text(" ", strip=True)
            if location_element
            else ""
        )

        images = self._extract_card_images(card)

        floor, area, rooms_count = self._extract_property_details(name)

        return SiteParseData(
            site="Avito",
            url=url,
            name=name,
            subtitles="",
            description=description,
            price=price,
            object_type=self.object_types[category],
            imgs=images,
            residential_complex="",
            floor=floor,
            area=area,
            rooms_count=rooms_count,
            geo_label=self._extract_geo_labels(location_text)
        )

    def _extract_card_images(self, card: Tag) -> list[str]:
        result: list[str] = []

        for image in card.select("img"):
            src = image.get("src") or image.get("data-src")

            if isinstance(src, str) and src.startswith("http"):
                result.append(src)

        return list(dict.fromkeys(result))

    def _extract_price(self, price_element: Tag | None) -> int:
        if price_element is None:
            return 0

        digits = "".join(
            char
            for char in price_element.get_text(" ", strip=True)
            if char.isdigit()
        )

        return int(digits) if digits else 0

    def _extract_property_details(
        self,
        name: str
    ) -> tuple[int, float, int]:

        floor = 0
        area = 0.0
        rooms_count = 0

        area_match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*м²",
            name,
            re.IGNORECASE
        )

        if area_match:
            area = float(area_match.group(1).replace(",", "."))

        floor_match = re.search(
            r"(\d+)\s*/\s*\d+\s*эт",
            name,
            re.IGNORECASE
        )

        if floor_match:
            floor = int(floor_match.group(1))

        rooms_match = re.search(
            r"\b(\d+)\s*[-‑–]?\s*(?:к(?:\.|\b)|комн\.?|комнатн\w*)",
            name,
            re.IGNORECASE
        )

        if rooms_match:
            rooms_count = int(rooms_match.group(1))

        return floor, area, rooms_count

    def _extract_geo_labels(self, location: str) -> geoLabelDict:
        geo_data: geoLabelDict = {
            "region": "",
            "city": "",
            "district": "",
            "micro_district": "",
            "street": "",
            "house": ""
        }

        if not location:
            return geo_data

        parts = [
            part.strip()
            for part in location.split(",")
            if part.strip()
        ]

        for part in parts:
            if "приморский край" in part.lower():
                geo_data["region"] = part

            elif "владивосток" in part.lower():
                geo_data["city"] = part

        if len(parts) > 1:
            last_part = parts[-1]

            if re.search(r"\d", last_part):
                geo_data["house"] = last_part

        return geo_data