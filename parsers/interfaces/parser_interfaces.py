from abc import ABC, abstractmethod

from model.site_parse_data_model import SiteParseData
from model.parser_config import ParserConfig

class IParcer(ABC): 
    @abstractmethod
    def parse(self, parserConfig: ParserConfig) -> tuple[bool, list[SiteParseData] | None]:
        pass

    @abstractmethod
    def _parsePage(self, city_id: int, page: int) -> tuple[bool, list[SiteParseData] | None]:
        pass


    