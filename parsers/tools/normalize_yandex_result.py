"""
Нормализация уже сохранённого yandex_result.json.

Повторно применяет к каждой записи fallback из заголовка (площадь,
комнаты, тип объекта), фильтрует фотографии и пересобирает модель через
YandexParser. Полезно, если парсер уже отработал, а исходный JSON был
получен старой версией (пустые area/rooms_count, мусорные imgs).

Запуск:
    uv run python tools/normalize_yandex_result.py --dry-run
    uv run python tools/normalize_yandex_result.py
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from realizations.yandex_parser import YandexParser  # noqa: E402


def normalize_record(
    record: dict[str, Any],
    parser: YandexParser,
) -> dict[str, Any] | None:
    """Возвращает нормализованную запись или None, если она невалидна."""
    url = str(record.get("url") or "")

    parser._apply_title_fallback(record)

    item = parser._build_item(record, url)

    if item is None or not parser._validate_item(item):
        return None

    return asdict(item)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Нормализовать сохранённый yandex_result.json",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=str(ROOT / "yandex_result.json"),
        help="путь к JSON-файлу (по умолчанию yandex_result.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="только показать статистику, не записывать файл",
    )
    args = parser.parse_args()

    path = Path(args.path)
    records = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(records, list):
        print("Ожидался JSON-массив записей")
        return 1

    yandex_parser = YandexParser()
    normalized: list[dict[str, Any]] = []
    dropped = 0

    for record in records:
        if not isinstance(record, dict):
            dropped += 1
            continue

        result = normalize_record(record, yandex_parser)

        if result is None:
            dropped += 1
        else:
            normalized.append(result)

    print(
        f"Всего: {len(records)}, нормализовано: {len(normalized)}, "
        f"отброшено: {dropped}"
    )

    if not args.dry_run:
        path.write_text(
            json.dumps(normalized, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Записан {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
