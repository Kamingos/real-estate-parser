from abc import ABC, abstractmethod
from typing import Any

from model.parser_config import ParserConfig

class IParcer(ABC):
    # Каждый парсер возвращает свой тип данных
    # (CianSiteParseData / AvitoSiteParseData), поэтому список типизирован как Any.
    @abstractmethod
    def parse(self, parserConfig: ParserConfig) -> tuple[bool, list[Any] | None]:
        pass
