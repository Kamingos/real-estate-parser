import json

from realizations.cian_parser import CianParser
from realizations.avito_parser import AvitoParser
from model.parser_config import ParserConfig

from dataclasses import asdict

cities = {"vladivostok": 4701, "moscow": 1}

# configs
cianConfig = ParserConfig(
        max_page_iteration=1,
        min_iteration_time_span=0,
        max_iteration_time_span=0,
        cities = {"vladivostok": 4701, "moscow": 1},
        min_cost = 0, # не реализовано
        max_cost = 10_000_000, # не реализовано
        area_min = 0, # не реализовано
        area_max = 100, # не реализовано
        rooms_count_min = 0, # не реализовано
        rooms_count_max = 10, # не реализовано
        floor_min = 0, # не реализовано
        floor_max = 100 # не реализовано
        )

avitoCofig = ParserConfig(
        max_page_iteration=1,
        min_iteration_time_span=0,
        max_iteration_time_span=0,
        cities = {},
        min_cost = 0, # не реализовано
        max_cost = 10_000_000, # не реализовано
        area_min = 0, # не реализовано
        area_max = 100, # не реализовано
        rooms_count_min = 0, # не реализовано
        rooms_count_max = 10, # не реализовано
        floor_min = 0, # не реализовано
        floor_max = 100 # не реализовано
        )

def DoCian():
    # Cian
    cian_parser = CianParser()

    success, result = cian_parser.parse(cianConfig)

    if not success or result is None:
        print(f"Error Cian: not success: {not success}, result is None: {result is None}")
        raise SystemExit(1)

    with open("cian_result.json", "w", encoding="utf-8") as file:
        json.dump([asdict(item) for item in result], file, indent=4, ensure_ascii=False)

def DoAvito():
    # Cian
    cian_parser = AvitoParser()

    success, result = cian_parser.parse(avitoCofig)

    if not success or result is None:
        print(f"Error Avito: not success: {not success}, result is None: {result is None}")
        raise SystemExit(1)

    with open("avito_result.json", "w", encoding="utf-8") as file:
        json.dump([asdict(item) for item in result], file, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    
    # General
    
    DoCian()