from abc import ABC, abstractmethod
from typing import Any

from model.parser_config import ParserConfig


class IParcer(ABC):
    # Каждый парсер возвращает свой тип данных
    # (CianSiteParseData / AvitoSiteParseData / YandexSiteParseData),
    # поэтому список типизирован как Any.
    #
    # Контракт: (True, [элементы]) при успешном проходе (возможно пустой
    # список), (False, None) — если источник недоступен и данные не собраны.
    @abstractmethod
    def parse(self, parserConfig: ParserConfig) -> tuple[bool, list[Any] | None]:
        pass
