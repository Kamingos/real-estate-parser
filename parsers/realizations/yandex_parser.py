from interfaces.parser_interfaces import IParcer
from abc import ABC, abstractmethod
from typing import Any

from model.parser_config import ParserConfig

class IParcer(ABC):
    def parse(self, parserConfig: ParserConfig) -> tuple[bool, list[Any] | None]:
        ...