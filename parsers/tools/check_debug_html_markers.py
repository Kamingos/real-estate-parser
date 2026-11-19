"""Проверка маркеров в сохранённом HTML страницы объявления."""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HTML = Path(__file__).resolve().parent.parent / "yandex_offer_debug.html"

MARKERS = (
    "Санкт-Петербург",
    "Ростов-на-Дону",
    "Спасск-Дальний",
    "100-летия Владивостока",
    'data-testid="offer-facts"',
    "OfferFacts",
    "offer-features",
    'data-testid="offer-description"',
    'itemprop="description"',
    'itemprop="address"',
    "floorLevel",
    "numberOfRooms",
    '"Этаж"',
    "Этажей в доме",
    "Площадь кухни",
    "Жилая площадь",
    "Тип дома",
    "Год постройки",
)


def main() -> None:
    html = HTML.read_text(encoding="utf-8", errors="ignore")

    for marker in MARKERS:
        print(f"{marker!r}: {html.count(marker)}")

    print("\nКонтекст 'Санкт-Петербург':")
    position = html.find("Санкт-Петербург")
    print(html[max(0, position - 300) : position + 100])


if __name__ == "__main__":
    main()
