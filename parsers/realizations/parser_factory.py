"""
Фабрика парсеров источников.

Единая точка создания парсеров по имени сайта. Точки запуска (main.py,
будущий data-processor/Kafka) не должны импортировать конкретные классы:
достаточно ``create_parser("yandex")``.

Чтобы добавить новый источник, достаточно реализовать класс-наследник
IParcer и добавить его в PARSER_REGISTRY.
"""

from interfaces.parser_interfaces import IParcer
from realizations.avito_parser import AvitoParser
from realizations.cian_parser import CianParser
from realizations.yandex_parser import YandexParser

# Каноническое имя источника -> класс парсера
PARSER_REGISTRY: dict[str, type[IParcer]] = {
    "avito": AvitoParser,
    "cian": CianParser,
    "yandex": YandexParser,
}

# Дополнительные имена/домены источников
PARSER_ALIASES: dict[str, str] = {
    "avito.ru": "avito",
    "www.avito.ru": "avito",
    "авито": "avito",
    "cian.ru": "cian",
    "www.cian.ru": "cian",
    "циан": "cian",
    "yandex.ru": "yandex",
    "realty.yandex.ru": "yandex",
    "yandex_realty": "yandex",
    "яндекс": "yandex",
    "яндекс недвижимость": "yandex",
}


def normalize_site_name(site: str) -> str:
    """Приводит имя источника к каноническому виду."""
    key = (site or "").strip().casefold()

    return PARSER_ALIASES.get(key, key)


def available_sites() -> list[str]:
    """Возвращает список доступных источников (канонические имена)."""
    return sorted(PARSER_REGISTRY)


def create_parser(site: str) -> IParcer:
    """
    Создаёт парсер по имени источника.

    :param site: имя источника (avito/cian/yandex или алиас)
    :raises ValueError: если источник неизвестен
    """
    key = normalize_site_name(site)

    parser_class = PARSER_REGISTRY.get(key)

    if parser_class is None:
        raise ValueError(
            f"Неизвестный источник '{site}'. "
            f"Доступные источники: {', '.join(available_sites())}"
        )

    return parser_class()
