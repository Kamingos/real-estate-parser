import json

from realizations.cian_parser import CianParser
from model.parser_config import ParserConfig

from dataclasses import asdict

cities = {"vladivostok": 4701, "moscow": 1}


if __name__ == "__main__":
    # General
    
    # Cian
    cian_parser = CianParser()

    cianConfig = ParserConfig(
        max_page_iteration=6,
        min_iteration_time_span=0,
        max_iteration_time_span=0,
        cities = {"vladivostok": 4701, "moscow": 1},
        min_cost = 0,
        max_cost = 10_000_000,
        area_min = 0,
        area_max = 100,
        rooms_count_min = 0,
        rooms_count_max = 10,
        floor_min = 0,
        floor_max = 100
        )

    success, result = cian_parser.parse(cianConfig)

    if not success or result is None:
        print(f"Error: not success: {not success}, result is None: {result is None}")
        raise SystemExit(1)

    with open("result.json", "w", encoding="utf-8") as file:
        json.dump([asdict(item) for item in result], file, indent=4, ensure_ascii=False)
