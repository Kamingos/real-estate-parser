import requests
import re

from bs4 import BeautifulSoup
from bs4.element import Tag
import webbrowser

from time import sleep
from random import uniform

from interfaces.parser_interfaces import IParcer
from model.site_parse_data_model import SiteParseData, geoLabelDict
from model.parser_config import ParserConfig


class CianParser(IParcer):
    def __init__(self) -> None:
        super().__init__()

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
        }

        self.url = "https://cian.ru/cat.php?deal_type=sale&engine_version=2&location%5B0%5D={city_id}&offer_type=flat&region={city_id}&p={page}&source=search_string"

    def parse(self, parserConfig: ParserConfig) -> tuple[bool, list[SiteParseData] | None]:

        offers_list: list[SiteParseData] = []

        for (city_key, city_value) in parserConfig.cities.items():
            for page in range(1, parserConfig.max_page_iteration + 1):
                success, result = self._parsePage(city_value, page)

                if not success or result is None:
                    print(f"[-] на странице {page}: not success: {not success}, result is None: {result is None}")

                    while True:
                        str = input("пройти каптчу и попробовать снова? [y/n]")

                        if (str == "y"):
                            webbrowser.open_new_tab(self.url.format(city_id=city_value, page=page))
                            input("Продолжить?")
                            page -= 1
                            break

                        if (str == "n"):
                            break

                    continue

                offers_list.extend(result)
                print(f"[+] cian parser: just appended {len(result)} offers from page {page}, city {city_key}")

                if (page < self.max_pages): sleep(uniform(parserConfig.min_iteration_time_span, parserConfig.max_iteration_time_span)) # Время ожидания между сессиями

        print(f"[+] cian parser: total {len(offers_list)} offers")
        return True, offers_list

    def _parsePage(self, city_id: int, page: int ) -> tuple[bool, list[SiteParseData] | None]:
        page_url = self.url.format(city_id=city_id, page=page)

        response = requests.get(
            page_url,
            headers=self.headers,
            timeout=10
        )
        response.raise_for_status()

        cards = self._find_cards(response.text)

        results = [
            self._extract_card_data(card, page_url) for card in cards
        ]

        for item in results:
            item.site = "Cian"

        if not results:
            return False, None

        return True, results

    def _find_cards(self, html: str) -> list[Tag]:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.find_all("article", attrs={"data-name": "CardComponent"})

        if not cards:
            print("GeoLabel:", len(soup.find_all(name = None, attrs={"data-name": "GeoLabel"})))
            print("MainPrice:", len(soup.find_all(name = None, attrs={"data-mark": "MainPrice"})))

        return list(cards)

    def _extract_card_data(self, card: Tag, page_url: str
    ) -> SiteParseData:
        link = card.find("a", attrs={"data-name": "TitleComponent"})

        if not isinstance(link, Tag):
            link = card.find("a", href=True)

        url = str(link.get("href", "")) if isinstance(link, Tag) else page_url

        title = card.find(name=None, attrs={"data-mark": "OfferTitle"})
        subtitle = card.find(name=None, attrs={"data-mark": "OfferSubtitle"})

        name = title.get_text(" ", strip=True) if title else ""
        additive_name = subtitle.get_text(" ", strip=True) if subtitle else ""

        floor, area, rooms_count = self._extract_property_details(
            name,
            additive_name
    )

        price = card.find(name = None, attrs={"data-mark": "MainPrice"})
        description = card.find("div", attrs={"data-name": "Description"})

        def is_jk_class(value: object) -> bool:
            if isinstance(value, list):
                return any(
                    isinstance(item, str) and "jk" in item.lower()
                    for item in value
                )

            if isinstance(value, str):
                return "jk" in value.lower()

            return False

        residential_complex = card.find("a", class_=is_jk_class)

        geo_labels = [
            item.get_text(" ", strip=True)
            for item in card.find_all(name = None, attrs={"data-name": "GeoLabel"})
        ]

        return SiteParseData(
            url=url,
            name=name,
            subtitles=additive_name,
            description=description.get_text(" ", strip=True) if description else "",
            price=self._extract_price(price if isinstance(price, Tag) else None),
            imgs=self._extract_card_images(card),
            residential_complex=(
                residential_complex.get_text(" ", strip=True)
                if residential_complex else ""
            ),
            geo_label=self._extract_geo_labels(geo_labels),
            floor=floor,
            area=area,
            rooms_count=rooms_count
        )

    def _extract_card_images(self, card: Tag) -> list[str]:
        gallery = card.find("div", attrs={"data-name": "Gallery"})

        if not isinstance(gallery, Tag):
            return []

        images = gallery.find_all("img")
        result: list[str] = []

        for image in images:
            src = image.get("src")

            if isinstance(src, str) and src.startswith("http"):
                result.append(src)

        return list(dict.fromkeys(result))

    def _extract_property_details(self, name: str, additive_name: str) -> tuple[int, float, int]:
        text = f"{name} {additive_name}"

        rooms_count = 0
        area = 0.0
        floor = 0

        # количество комнат: 2-комн., 3-х к. квартира
        rooms_match = re.search(
            r"(\d+)\s*(?:[-‑–]\s*)?(?:комн\.?|комнатн\w*|х\s*к\.?)",
            text,
            re.IGNORECASE
        )

        if rooms_match:
            rooms_count = int(rooms_match.group(1))

        # площадь: 50,5 м² или 75 м²
        area_match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*м²",
            text,
            re.IGNORECASE
        )

        if area_match:
            area = float(area_match.group(1).replace(",", "."))

        # этаж: 2/25 этаж или 14/17 этаж
        floor_match = re.search(
            r"(\d+)\s*/\s*\d+\s*этаж",
            text,
            re.IGNORECASE
        )

        if floor_match:
            floor = int(floor_match.group(1))

        return floor, area, rooms_count

    def _extract_price(self, price: Tag | None) -> int:
        if price is None:
            return 0

        digits = "".join(
            char for char in price.get_text("", strip=True)
            if char.isdigit()
        )

        return int(digits) if digits else 0

    def _extract_geo_labels(self, labels: list[str]) -> geoLabelDict:
        geo_data: geoLabelDict = {
            "region": "",
            "city": "",
            "district": "",
            "micro_district": "",
            "street": "",
            "house": ""
        }

        if len(labels) > 0:
            geo_data["region"] = labels[0]
        if len(labels) > 1:
            geo_data["city"] = labels[1]
        if len(labels) > 2:
            geo_data["district"] = labels[2]
        if len(labels) > 3:
            geo_data["micro_district"] = labels[3]
        if len(labels) > 4:
            geo_data["street"] = labels[4]
        if len(labels) > 5:
            geo_data["house"] = labels[5]

        return geo_data
