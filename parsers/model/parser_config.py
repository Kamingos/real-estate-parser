from dataclasses import dataclass


@dataclass
class ParserConfig:
    # количество открываемых страниц 
    max_page_iteration: int

    # временной интервал между итерациями
    min_iteration_time_span: float
    max_iteration_time_span: float

    # настройки поиска парсера
    cities: dict[str,int]


    # не реализовано • не реализовано • не реализовано • не реализовано • не реализовано • не реализовано • не реализовано
    min_cost: int
    max_cost: int

    # не реализовано в парсере
    area_min: float 
    area_max: float

    rooms_count_min: int
    rooms_count_max: int

    floor_min: int # Этаж
    floor_max: int # Этаж

    # Параметры сетевого взаимодействия.
    # Добавлены со значениями по умолчанию, чтобы существующие конфигурации
    # Cian/Avito продолжали работать без изменений.
    max_retries: int = 3        # число повторных попыток загрузки страницы
    page_wait_time: int = 10    # ожидание загрузки страницы, секунды
    headless: bool = False      # запуск браузера без окна



