from typing import TypeVar

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from interfaces.parser_interfaces import IParcer
from model.site_parse_data_model import SiteParseData

T = TypeVar("T")


class CianParser(IParcer):
    def __init__(self) -> None:
        super().__init__()

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
        }

        self.url = "https://cian.ru/cat.php?deal_type=sale&engine_version=2&location%5B0%5D={city_id}&offer_type=flat&region={city_id}&p={page}&source=search_string"

        self.max_pages = 1

    def parse(self, city_id: int) -> tuple[bool, SiteParseData | None]:
        parsed_pages: list[SiteParseData | None] = []

        for page in range(1, self.max_pages + 1):
            success, result = self._parsePage(city_id, page)

            if not success:
                break

            parsed_pages.append(result)

        if parsed_pages:
            return True, parsed_pages[0]

        return False, SiteParseData(url="", imgs=[])

    def _parsePage(self, city_id: int, page: int) -> tuple[bool, SiteParseData | None]:
        page_url = self.url.format(city_id=city_id, page=page)

        response = requests.get(page_url, headers=self.headers)

        if response.status_code != 200:
            raise Exception("Failed to fetch the page")

        cards = self._find_cards(response.text)

        images: list[str] = []

        for card in cards:
            images.extend(self._extract_card_images(card))

        return True, SiteParseData(url=page_url, imgs=images)

    def _find_cards(self, html: str) -> list[Tag]:
        soup = BeautifulSoup(html, "html.parser")

        context = self._require(soup.find("div", id="frontend-serp"), "No context")

        for _ in range(2):
            context = self._require(context.find("div"), "No context")

        return context.find_all("article", attrs = {"data-name": "CardComponent"})

    def _extract_card_images(self, card: Tag) -> list[str]:
        link = self._require(card.find("a"), "No href")

        gallery = self._require(link.find("div", attrs = {"data-name": "Gallery"}), "No content")

        gallery_content = self._require(gallery.find("div"), "No content")

        images_container = self._require(gallery_content.find("ul"), "No content")

        images = images_container.find_all("img")

        if not images:
            raise Exception("No images")

        return [str(image.get("src")) for image in images]

    @staticmethod
    def _require(element: T | None, message: str) -> T:
        if element is None:
            raise Exception(message)

        return element

