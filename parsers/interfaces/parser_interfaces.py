from abc import ABC, abstractmethod

from model.site_parse_data_model import SiteParseData

class IParcer(ABC): 
    @abstractmethod
    def parse(self, city_id: int) -> tuple[bool, SiteParseData | None]:
        pass

    @abstractmethod
    def _parsePage(self, city_id: int, page: int) -> tuple[bool, SiteParseData | None]:
        pass


    