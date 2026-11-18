"""Разбирает window.INITIAL_STATE из сохранённого HTML и показывает данные оффера.

Нужно, чтобы убедиться: полные данные объявления есть в HTML, но парсер
не находит контейнер (ищет window.__INITIAL_STATE__, а на странице
window.INITIAL_STATE).

Запуск: uv run python tools/dump_initial_state.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8")

HTML = Path(__file__).resolve().parent.parent / "yandex_offer_debug.html"
TARGET_ID = "661250810916136822"


def load_state(html: str) -> dict | None:
    match = re.search(
        r'<script[^>]*id=["\']initial_state_script["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None

    raw = match.group(1).strip()
    raw = re.sub(r"^window\.INITIAL_STATE\s*=\s*", "", raw)
    raw = raw.rstrip().rstrip(";")

    try:
        return json.loads(raw)
    except ValueError as error:
        print("Не удалось разобрать INITIAL_STATE:", error)
        return None


def find_offer(node: Any, target: str) -> dict | None:
    queue: list[Any] = [node]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            if str(current.get("offerId")) == target:
                return current
            queue.extend(current.values())
        elif isinstance(current, list):
            queue.extend(current)
    return None


def preview(value: Any, limit: int = 400) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text[:limit]


def main() -> None:
    html = HTML.read_text(encoding="utf-8", errors="ignore")
    state = load_state(html)
    if state is None:
        return

    print("Верхние ключи INITIAL_STATE:", list(state)[:30])

    offer = find_offer(state, TARGET_ID)
    if offer is None:
        print("Оффер не найден в состоянии")
        return

    print(f"\nОффер {TARGET_ID}: ключей {len(offer)}")
    print("Ключи:", sorted(offer))

    for key in (
        "title", "description", "category", "offerCategory", "offerType", "flatType",
        "roomsCount", "roomsTotal", "floor", "floorsOffered", "floorsTotal",
        "floorsCount", "area", "livingArea", "livingSpace", "kitchenArea",
        "ceilingHeight", "bathroomUnit", "balcony", "repair", "renovation",
        "address", "location", "coordinates", "building", "house", "apartment",
        "newBuilding", "seller", "author", "price", "tags", "features", "photos",
        "totalImages", "creationDate", "updateDate", "views", "viewsCount",
        "dealStatus", "keyHandoverDate", "commissioningDateIndexValue",
    ):
        if key in offer:
            print(f"\n  {key}: {preview(offer[key])}")

    # Ищем, где ещё встречается target в состоянии (например, отдельная сущность карточки)
    print("\n=== Дополнительные вхождения offerId в состоянии ===")
    raw_state = json.dumps(state, ensure_ascii=False)
    for match in list(re.finditer(re.escape(TARGET_ID), raw_state))[:5]:
        start = max(0, match.start() - 200)
        print("  ...", raw_state[start : match.start() + 200], "\n  ---")


if __name__ == "__main__":
    main()
