"""Показывает структуру INITIAL_STATE: где карточка оффера и какие есть блоки offers.

Нужно, чтобы понять, не подхватит ли парсер рекомендации вместо нужного
объявления после добавления маркера window.INITIAL_STATE.

Запуск: uv run python tools/check_state_structure.py
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

FOUND_PATHS: list[str] = []


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


def walk(node: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            current_path = path + (str(key),)
            if key == "offers":
                size = len(value) if isinstance(value, (list, dict)) else "?"
                print(
                    f"  ключ 'offers' по пути {'.'.join(current_path)}: "
                    f"{type(value).__name__} len={size}"
                )
            if str(node.get("offerId")) == TARGET_ID:
                FOUND_PATHS.append(".".join(path) or "<root>")
                return
            walk(value, current_path)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            walk(value, path + (f"[{index}]",))


def main() -> None:
    state = load_state(HTML.read_text(encoding="utf-8", errors="ignore"))
    if state is None:
        return

    print("=== Блоки offers в состоянии ===")
    walk(state)

    print("\n=== Пути к целевому офферу ===")
    for item in FOUND_PATHS:
        print("  ", item)

    print("\n=== offerCard ===")
    card = state.get("offerCard")
    print("  тип:", type(card).__name__)
    if isinstance(card, dict):
        print("  ключи:", list(card)[:40])
        for key, value in card.items():
            if isinstance(value, dict) and str(value.get("offerId")) == TARGET_ID:
                print(f"  карточка оффера найдена в offerCard.{key}")
            if isinstance(value, list) and value and isinstance(value[0], dict):
                print(f"  offerCard.{key}: список из {len(value)}")


if __name__ == "__main__":
    main()
