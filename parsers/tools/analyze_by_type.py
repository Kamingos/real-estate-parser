"""Заполненность полей yandex_result.json в разрезе типов объектов.

Позволяет отделить поля, которые физически отсутствуют у типа объявления,
от полей, которые парсер не извлекает ни у одного типа.

Запуск: uv run python tools/analyze_by_type.py
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

RESULT = Path(__file__).resolve().parent.parent / "yandex_result.json"

FIELDS = (
    "name",
    "description",
    "address",
    "latitude",
    "longitude",
    "price",
    "price_per_meter",
    "area",
    "rooms_count",
    "floor",
    "floors_count",
    "living_area",
    "kitchen_area",
    "ceiling_height",
    "bathroom",
    "balcony",
    "repairs",
    "finishing",
    "year_building",
    "building_status",
    "building_material",
    "building_type",
    "housing_type",
    "residential_complex",
    "developer",
    "seller_name",
    "seller_type",
    "land_type",
    "land_area",
    "garage_type",
    "commercial_purpose",
    "photos_count",
    "parameters",
    "imgs",
)

# Поля, которые в принципе применимы к типу объекта.
APPLICABLE = {
    "flat": {
        "rooms_count", "floor", "floors_count", "living_area", "kitchen_area",
        "ceiling_height", "bathroom", "balcony", "repairs", "finishing",
        "year_building", "building_status", "building_material", "building_type",
        "housing_type", "residential_complex", "developer",
    },
    "studio": {
        "floor", "floors_count", "living_area", "kitchen_area", "ceiling_height",
        "bathroom", "balcony", "repairs", "finishing", "year_building",
        "building_status", "building_material", "building_type", "housing_type",
        "residential_complex", "developer",
    },
    "room": {
        "rooms_count", "floor", "floors_count", "living_area", "ceiling_height",
        "bathroom", "balcony", "repairs", "finishing", "year_building",
        "building_status", "building_material", "building_type", "housing_type",
        "residential_complex", "developer",
    },
    "house": {
        "rooms_count", "floor", "floors_count", "living_area", "kitchen_area",
        "ceiling_height", "bathroom", "balcony", "repairs", "finishing",
        "year_building", "building_status", "building_material", "building_type",
        "housing_type", "residential_complex", "developer", "land_type",
        "land_area",
    },
    "land_plot": {"land_type", "land_area"},
    "garage": {"garage_type"},
    "other": {"commercial_purpose", "floor", "floors_count", "building_type"},
}

# Поля, которые есть на карточке любого объекта недвижимости.
UNIVERSAL = {
    "name", "description", "address", "latitude", "longitude", "price",
    "price_per_meter", "area", "seller_name", "seller_type", "photos_count",
    "parameters", "imgs",
}


def filled(value: object) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (list, dict)):
        return bool(value)
    if isinstance(value, (int, float)):
        return value != 0
    return True


def main() -> None:
    data = json.loads(RESULT.read_text(encoding="utf-8"))
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for row in data:
        groups[row["object_type"]].append(row)

    print(f"Всего записей: {len(data)}")
    print("Типы:", {key: len(value) for key, value in groups.items()})

    for object_type, rows in groups.items():
        total = len(rows)
        print(f"\n=== {object_type} ({total}) ===")
        applicable = APPLICABLE.get(object_type, set()) | UNIVERSAL

        for field in FIELDS:
            count = sum(1 for row in rows if filled(row.get(field)))
            mark = "OK " if count == total else ("-- " if field not in applicable else "!! ")
            print(f"  {mark}{field}: {count}/{total}")

        garbage = sum(
            1
            for row in rows
            if any(
                key in {"Санкт", "Ростов", "Спасск", "Проспект 100", "Фотография"}
                or key.startswith("+ ")
                or " в " in key
                for key in row["parameters"]
            )
        )
        print(f"  мусорные parameters: {garbage}/{total}")

    # Сводка: есть ли хоть один тип, где поле заполнено
    print("\n=== Поля, пустые у ВСЕХ типов (парсер не извлекает) ===")
    never = [
        field
        for field in FIELDS
        if all(not any(filled(row.get(field)) for row in rows) for rows in groups.values())
    ]
    print(", ".join(never) if never else "нет")

    print("\n=== Поля, заполненные хотя бы у одного типа ===")
    for field in FIELDS:
        per_type = {
            object_type: sum(1 for row in rows if filled(row.get(field)))
            for object_type, rows in groups.items()
        }
        if any(per_type.values()):
            print(f"  {field}: {per_type}")


if __name__ == "__main__":
    main()
