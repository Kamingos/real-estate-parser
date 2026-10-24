import requests

from bs4 import BeautifulSoup

from interfaces.parser_interfaces import IParcer

class CianParser(IParcer):
    def __init__(self) -> None:
        super().__init__()

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
        }

        self.url = "https://cian.ru/cat.php?deal_type=sale&engine_version=2&location%5B0%5D={city_id}&offer_type=flat&region={city_id}&p={page}&source=search_string"

        self.max_pages = 100

    def _parsePage(self, city_id: int, page: int) -> bool|str:
        response = requests.get(self.url.format(city_id=city_id, page=page), headers=self.headers)
    
        if response.status_code != 200:
            return False

        text_html = response.text

        soap = BeautifulSoup(text_html, "html.parser")

        context = soap.find("div", id="frontend-serp")

        if context is None: return False
        
        context = context.find("div")

        if context is None: return False

        context = context.find("div")

        if context is None: return False

        context = context.find("div", class_="x31de4314--dc3fb1--wrapper")

        if context is None: return False

        return str(context)

    def parse(self, city_id: int) -> bool|str:

        list_of_pages = []
        
        for page in range(1, self.max_pages + 1):
            res = self._parsePage(city_id, page)

            if res is False:
                break

            # list_of_pages.append(res)


        return False
    

