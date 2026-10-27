from dataclasses import dataclass, field

@dataclass
class ParserConfig:
    # количество открываемых страниц 
    max_page_iteration: int

    # временной интервал между итерациями
    min_iteration_time_span: float
    max_iteration_time_span: float

    # настройки поиска парсера
    cities: dict[str,int]

    min_cost: int
    max_cost: int

    # не реализовано в парсере
    area_min: float 
    area_max: float

    rooms_count_min: int
    rooms_count_max: int

    floor_min: int # Этаж
    floor_max: int # Этаж



