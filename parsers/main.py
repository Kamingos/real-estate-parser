import json
from dataclasses import asdict

import realizations.cian_parser

cities = {"vladivostok": 4701, "moscow": 1}


if __name__ == "__main__":
    cian_parser = realizations.cian_parser.CianParser()

    success, result = cian_parser.parse(cities["vladivostok"])

    if not success or result is None:
        print("Error")
        raise SystemExit(1)

    with open("result.json", "w", encoding="utf-8") as file:
        json.dump(asdict(result), file, indent=4, ensure_ascii=False)
