import realizations.cian_parser

cities = {"vladivostok": 4701, "moscow": 1}


if __name__ == "__main__":
    cian_parser = realizations.cian_parser.CianParser()

    res = cian_parser.parse(cities["vladivostok"])
                            
    if res is False:
        print("Error")

    with open("result.html", "w", encoding="utf-8") as file:
        file.write(str(res))