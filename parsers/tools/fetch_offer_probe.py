"""Проверка страниц объявлений разных типов: какие данные есть в HTML.

Скачивает страницы обычным HTTP-запросом (без Selenium) и показывает,
присутствуют ли на них JSON-LD/@graph и ключевые поля. Нужно, чтобы понять,
отсутствуют ли данные у отдельных типов объявлений или их не извлекает парсер.

Запуск: uv run python tools/fetch_offer_probe.py
"""

from __future__ import annotations

import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

OUT_DIR = Path(__file__).resolve().parent.parent / "probe"

URLS = {
    "flat": "https://realty.yandex.ru/offer/661250810916136822/",
    "land_plot": "https://realty.yandex.ru/offer/791384472904661505/",
    "garage": "https://realty.yandex.ru/offer/1690625618449158916/",
    "commercial": "https://realty.yandex.ru/offer/1716619693416161772/",
    "room": "https://realty.yandex.ru/offer/2493327959330238398/",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CAPTCHA_MARKERS = ("showcaptcha", "smartcaptcha", "подтвердите, что вы не робот")


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="ignore")


def ld_graph_nodes(html: str) -> list[dict]:
    nodes: list[dict] = []
    for block in re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        try:
            parsed = json.loads(block)
        except ValueError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("@graph"), list):
            nodes.extend(item for item in parsed["@graph"] if isinstance(item, dict))
        elif isinstance(parsed, dict):
            nodes.append(parsed)
    return nodes


def describe(label: str, url: str) -> None:
    print(f"\n=== {label}: {url} ===")
    try:
        html = fetch(url)
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"  запрос не удался: {error}")
        return

    print(f"  размер HTML: {len(html)}")
    lowered = html[:50000].casefold()
    if any(marker in lowered for marker in CAPTCHA_MARKERS):
        print("  !!! отдана капча/заглушка, данные проверить нельзя")
        return

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"{label}.html").write_text(html, encoding="utf-8")

    nodes = ld_graph_nodes(html)
    print(f"  JSON-LD узлов (с раскрытием @graph): {len(nodes)}")

    for node in nodes:
        node_type = node.get("@type")
        if node_type in ("Product", "Apartment", "House", "Offer", "RealEstateListing"):
            keys = [
                key
                for key in (
                    "name", "description", "address", "geo", "floorLevel",
                    "floorSize", "numberOfRooms", "offers", "sku", "price",
                )
                if key in node
            ]
            print(f"    {node_type}: {keys}")

    for marker in (
        "window.__INITIAL_STATE__",
        "__NEXT_DATA__",
        "offerId",
        "data-testid=\"offer-facts\"",
        "OfferFacts",
        "itemprop=\"description\"",
    ):
        print(f"    {marker!r}: {html.count(marker)}")


def main() -> None:
    for index, (label, url) in enumerate(URLS.items()):
        describe(label, url)
        if index < len(URLS) - 1:
            time.sleep(3)


if __name__ == "__main__":
    main()
