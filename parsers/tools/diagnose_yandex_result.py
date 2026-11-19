"""Диагностика yandex_result.json и отладочного HTML страницы объявления.

Запуск: uv run python tools/diagnose_yandex_result.py
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

RESULT = Path(__file__).resolve().parent.parent / "yandex_result.json"
DEBUG_HTML = Path(__file__).resolve().parent.parent / "yandex_offer_debug.html"


def main() -> None:
    data = json.loads(RESULT.read_text(encoding="utf-8"))

    print(f"Записей: {len(data)}")

    # --- Заполненность полей ---
    def filled(value: object) -> bool:
        if value is None or value == "":
            return False
        if isinstance(value, (list, dict)):
            return bool(value)
        if isinstance(value, (int, float)):
            return value != 0
        return True

    total = len(data)
    stats = [
        (key, sum(1 for row in data if filled(row.get(key))))
        for key in data[0]
    ]
    stats.sort(key=lambda item: item[1])

    print("\nПолностью пустые поля (0 записей):")
    empty = [key for key, count in stats if count == 0]
    print(", ".join(empty) if empty else "нет")

    print("\nЧастично заполненные поля:")
    for key, count in stats:
        if 0 < count < total:
            print(f"  {key}: {count}/{total}")

    # --- Гео ---
    geo_filled = sum(1 for row in data if any(row["geo_label"].values()))
    print(f"\ngeo_label заполнен: {geo_filled}/{total}")

    # --- Типы ---
    print("\nobject_type:", dict(collections.Counter(r["object_type"] for r in data)))
    print("category:", dict(collections.Counter(r["category"] for r in data)))
    print(
        "housing_type:",
        dict(collections.Counter(r["housing_type"] for r in data)),
    )

    # --- parameters ---
    print("\nКлючи parameters (топ-20):")
    keys = collections.Counter()
    for row in data:
        keys.update(row["parameters"].keys())
    for key, count in keys.most_common(20):
        print(f"  {key!r}: {count}")

    print(
        "\nКоличество параметров на запись:",
        dict(collections.Counter(len(r["parameters"]) for r in data)),
    )

    print("\nПример parameters (первые 3 записи):")
    for row in data[:3]:
        print(f"  {row['url']} -> {row['parameters']}")

    # --- Дубли ---
    ids = [r["external_id"] for r in data]
    urls = [r["url"] for r in data]
    print(
        f"\nУникальных external_id: {len(set(ids))}/{len(ids)}, "
        f"уникальных url: {len(set(urls))}/{len(urls)}"
    )

    # --- Отладочный HTML ---
    if not DEBUG_HTML.exists():
        return

    html = DEBUG_HTML.read_text(encoding="utf-8", errors="ignore")
    print(f"\nОтладочный HTML: {DEBUG_HTML.name}, {len(html)} символов")

    markers = [
        "window.__INITIAL_STATE__",
        "__NEXT_DATA__",
        "__PRELOADED_STATE__",
        "JSON.parse(",
        "initialState",
        "application/ld+json",
        "application/json",
        '"offerId"',
        "data-testid=\"offer-price\"",
    ]
    for marker in markers:
        print(f"  {marker!r}: {html.count(marker)}")

    ld_blocks = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    print(f"\nJSON-LD блоков: {len(ld_blocks)}")
    for index, block in enumerate(ld_blocks, start=1):
        try:
            parsed = json.loads(block)
        except ValueError as error:
            print(f"  блок {index}: не JSON ({error}), len={len(block)}")
            continue
        print(
            f"  блок {index}: keys={list(parsed)[:10]}, "
            f"@type={parsed.get('@type')!r}"
        )
        for key in ("name", "description", "address", "offers", "floorSize", "sku"):
            if key in parsed:
                value = parsed[key]
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)[:300]
                print(f"    {key}: {str(value)[:300]}")

    json_scripts = re.findall(
        r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    print(f"\n<script type=application/json> блоков: {len(json_scripts)}")
    for index, block in enumerate(json_scripts, start=1):
        try:
            parsed = json.loads(block)
        except ValueError as error:
            print(f"  блок {index}: не JSON ({error}), len={len(block)}")
            continue
        print(f"  блок {index}: type={type(parsed).__name__}, len={len(block)}")
        if isinstance(parsed, dict):
            print(f"    keys={list(parsed)[:15]}")


if __name__ == "__main__":
    main()
