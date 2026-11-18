"""Показывает, какие данные реально есть в сохранённом HTML объявления.

Ищет контейнеры с данными (JSON.parse, application/json, offerId) и текстовые
блоки характеристик, чтобы понять: данных нет на странице или их не извлекает
парсер.

Запуск: uv run python tools/inspect_debug_payload.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HTML = Path(__file__).resolve().parent.parent / "yandex_offer_debug.html"

TEXTS = (
    "Характеристики",
    "Информация о доме",
    "О доме",
    "Застройщик",
    "Продавец",
    "Отделка",
    "Ремонт",
    "Санузел",
    "Балкон",
    "Площадь кухни",
    "Жилая площадь",
    "Год постройки",
    "Тип дома",
    "Материал стен",
    "Этаж",
)


def main() -> None:
    html = HTML.read_text(encoding="utf-8", errors="ignore")

    print("=== Текстовые блоки характеристик ===")
    for text in TEXTS:
        print(f"  {text!r}: {html.count(text)}")

    print("\n=== JSON.parse(...) ===")
    position = html.find("JSON.parse(")
    while position != -1:
        print("  ...", html[position : position + 200].replace("\n", " "))
        position = html.find("JSON.parse(", position + 1)

    print("\n=== Вхождения offerId ===")
    for match in list(re.finditer(r"offerId", html))[:11]:
        start = max(0, match.start() - 120)
        print("  ...", html[start : match.start() + 160].replace("\n", " "))
        print("  ---")

    print("\n=== <script type=application/json> ===")
    for index, block in enumerate(
        re.findall(
            r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
            html,
            re.DOTALL | re.IGNORECASE,
        ),
        start=1,
    ):
        print(f"\n  блок {index}, len={len(block)}")
        try:
            parsed = json.loads(block)
        except ValueError as error:
            print(f"    не JSON: {error}")
            print("    начало:", block[:500].replace("\n", " "))
            continue
        print("    тип:", type(parsed).__name__)
        print("    начало:", json.dumps(parsed, ensure_ascii=False)[:1500])


if __name__ == "__main__":
    main()
