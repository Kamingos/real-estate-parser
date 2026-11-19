"""Показывает точные формы вложенных структур оффера в INITIAL_STATE.

Нужно для корректного маппинга полей в парсере (адрес, изображения, теги,
автор, цена, дом).

Запуск: uv run python tools/dump_state_shapes.py
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
    raw = re.sub(r"^window\.INITIAL_STATE\s*=\s*", "", match.group(1).strip())
    return json.loads(raw.rstrip().rstrip(";"))


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


def show(label: str, value: Any, limit: int = 1200) -> None:
    print(f"\n--- {label} ({type(value).__name__}) ---")
    text = json.dumps(value, ensure_ascii=False)
    print(text[:limit])


def main() -> None:
    state = load_state(HTML.read_text(encoding="utf-8", errors="ignore"))
    if state is None:
        return
    offer = find_offer(state, TARGET_ID)
    if offer is None:
        print("оффер не найден")
        return

    location = offer.get("location") or {}
    show("location", location)

    print("\n--- location.structuredAddress.component ---")
    components = (location.get("structuredAddress") or {}).get("component") or []
    for component in components:
        print(
            f"  regionType={component.get('regionType')!r} "
            f"value={component.get('value')!r}"
        )

    for key in (
        "mainImages", "fullImages", "origImages", "appLargeImages",
        "minicardImages", "photoPreviews", "yandexMapsPictures",
    ):
        value = offer.get(key)
        if isinstance(value, list) and value:
            show(f"{key}[0]", value[0])
            show(f"{key} len", len(value))
        else:
            print(f"\n--- {key}: {type(value).__name__} ---")

    show("price", offer.get("price"))
    show("author", offer.get("author"))
    show("building", offer.get("building"))
    show("house", offer.get("house"))
    show("tags[0:3]", (offer.get("tags") or [])[:3])
    show("views", offer.get("views"))
    show("offerLinks", offer.get("offerLinks"))
    show("breadcrumbs (top-level)", (state.get("breadcrumbs") or [])[:8])
    show("offerCard.siteCard", (state.get("offerCard") or {}).get("siteCard"))


if __name__ == "__main__":
    main()
