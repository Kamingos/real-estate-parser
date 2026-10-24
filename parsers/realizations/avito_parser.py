from interfaces.parser_interfaces import IParcer

class AvitoParser(IParcer):
    def parse(self, city_id: int) -> bool|str:
        return ""

    def _parsePage(self, city_id: int, page: int) -> bool|str:
        return ""

