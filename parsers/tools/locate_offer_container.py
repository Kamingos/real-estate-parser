"""Ищет фактический контейнер данных объявления и разметку характеристик.

Запуск: uv run python tools/locate_offer_container.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HTML = Path(__file__).resolve().parent.parent / "yandex_offer_debug.html"


def show_context(html: str, needle: str, radius: int = 350, limit: int = 3) -> None:
    print(f"\n=== {needle!r} ===")
    position = html.find(needle)
    shown = 0
    while position != -1 and shown < limit:
        start = max(0, position - radius)
        snippet = html[start : position + radius]
        print("  ...", re.sub(r"\s+", " ", snippet), "\n  ---")
        position = html.find(needle, position + 1)
        shown += 1


def script_before(html: str, position: int) -> tuple[str, int]:
    start = html.rfind("<script", 0, position)
    if start == -1:
        return "", -1
    end = html.find(">", start)
    return html[start : end + 1], start


def main() -> None:
    html = HTML.read_text(encoding="utf-8", errors="ignore")

    marker = '"card":{"offerId"'
    position = html.find(marker)
    print(f"Позиция {marker!r}: {position}")

    if position != -1:
        tag, start = script_before(html, position)
        print(f"Ближайший <script> перед данными: {tag[:400]}")
        print("Начало содержимого скрипта:")
        print("  ", re.sub(r"\s+", " ", html[start : start + 700]))

    # Какие глобальные переменные/идентификаторы объявлены в скриптах
    print("\n=== Присваивания window.* / var в скриптах ===")
    assignments = re.findall(
        r"(?:window\.[A-Za-z0-9_$]+|var\s+[A-Za-z0-9_$]+)\s*=\s*\{",
        html,
    )
    for item in list(dict.fromkeys(assignments))[:30]:
        print("  ", item)

    # Идентификаторы script-тегов
    print("\n=== <script id=...> ===")
    for item in list(dict.fromkeys(re.findall(r'<script[^>]*\bid=["\']([^"\']+)["\']', html))):
        print("  ", item)

    show_context(html, "Характеристики")
    show_context(html, "Санузел")
    show_context(html, "Балкон")
    show_context(html, "Застройщик")


if __name__ == "__main__":
    main()
