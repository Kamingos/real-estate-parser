"""
Общие фикстуры и билдеры тестовых данных.

HTML/JSON-фикстуры синтетические: они смоделированы по структуре страниц
Яндекс Недвижимости (window.__INITIAL_STATE__, JSON-LD, data-testid),
потому что живой запрос к realty.yandex.ru закрыт SmartCaptcha.
"""

import json
import sys
from pathlib import Path

import pytest

# Пакеты проекта лежат в каталоге parsers/, поэтому добавляем его в sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.parser_config import ParserConfig  # noqa: E402

OFFER_ID = "1234567890123"
OFFER_URL = f"https://realty.yandex.ru/offer/{OFFER_ID}/"

SECOND_OFFER_ID = "9876543210123"
SECOND_OFFER_URL = f"https://realty.yandex.ru/offer/{SECOND_OFFER_ID}/"

# Объявление в формате JSON состояния страницы Яндекса
OFFER = {
    "offerId": OFFER_ID,
    "category": "APARTMENT",
    "type": "SELL",
    "title": "2-комнатная квартира, 54,3 м²",
    "subtitle": "Владивосток, Первореченский район",
    "description": "Продаётся квартира. Артикул DNV-42.",
    "flatType": "APARTMENT",
    "price": {"value": 9500000, "currency": "RUR"},
    "area": {"value": 54.3, "unit": "SQM"},
    "livingArea": {"value": 31.2, "unit": "SQM"},
    "kitchenArea": {"value": 9.8, "unit": "SQM"},
    "roomsCount": 2,
    "floor": 5,
    "floorsCount": 17,
    "ceilingHeight": 2.75,
    "bathroomUnit": "SEPARATE",
    "balcony": [{"type": "LOGGIA"}],
    "windowView": "во двор",
    "repair": "FINE",
    "finishing": "FINE",
    "mortgage": True,
    "saleType": "FREE",
    "building": {
        "year": 2019,
        "status": "BUILT",
        "material": "MONOLITH",
        "floorsCount": 17,
        "entrancesCount": 3,
        "elevators": [
            {"type": "PASSENGER", "count": 2},
            {"type": "CARGO", "count": 1},
        ],
        "parking": "подземная",
        "newBuilding": False,
    },
    "newBuilding": {
        "name": "ЖК «Тихий»",
        "class": "комфорт",
        "completionDate": "4 квартал 2024",
        "developerName": "СК Пример",
    },
    "developer": {
        "name": "СК Пример",
        "foundationYear": 2005,
        "completedBuildings": 12,
        "buildingsUnderConstruction": 2,
    },
    "address": {
        "region": "Приморский край",
        "locality": "Владивосток",
        "district": "Первореченский",
        "microDistrict": "Снеговая падь",
        "street": "Снежная",
        "house": "12",
    },
    "coordinates": {"lat": 43.2, "lon": 131.9},
    "photos": [
        {"fullUrl": "https://avatars.mds.yandex.net/get-realty/1/1.jpg"},
        {"url": "//avatars.mds.yandex.net/get-realty/1/2.jpg"},
    ],
    "seller": {"name": "Иван", "type": "OWNER", "agency": "ИП Иванов"},
    "creationDate": "2026-11-01T10:00:00Z",
    "updateDate": "2026-11-10T10:00:00Z",
    "viewsCount": {"total": 123},
    "badges": ["Хорошая цена"],
    "features": {"Ремонт": "евро", "Санузел": "раздельный"},
    "nearbyInfrastructure": ["школа", "парк"],
    "landArea": {"value": 6.0, "unit": "SOTKA"},
}


def state_html(state: dict) -> str:
    """Собирает HTML-страницу со встроенным JSON состояния."""
    payload = json.dumps(state, ensure_ascii=False)
    return (
        "<html><head></head><body>"
        f"<script>window.__INITIAL_STATE__ = {payload};</script>"
        "<h1>Тестовая страница</h1>"
        "</body></html>"
    )


def make_config(**overrides) -> ParserConfig:
    """Создаёт ParserConfig с тестовыми значениями по умолчанию."""
    params = {
        "max_page_iteration": 1,
        "min_iteration_time_span": 0.0,
        "max_iteration_time_span": 0.0,
        "cities": {"vladivostok": 585430},
        "min_cost": 0,
        "max_cost": 10_000_000,
        "area_min": 0.0,
        "area_max": 100.0,
        "rooms_count_min": 0,
        "rooms_count_max": 10,
        "floor_min": 0,
        "floor_max": 100,
    }
    params.update(overrides)
    return ParserConfig(**params)


@pytest.fixture
def yandex_parser():
    """Экземпляр парсера Яндекса."""
    from realizations.yandex_parser import YandexParser

    return YandexParser()


@pytest.fixture
def offer_state_html() -> str:
    """Страница объявления с JSON состоянием."""
    return state_html(
        {
            "offer": OFFER,
            "offers": {"entities": {OFFER_ID: OFFER}},
        }
    )


@pytest.fixture
def listing_state_html() -> str:
    """Страница списка объявлений с JSON состоянием."""
    return state_html(
        {
            "offers": {
                "entities": {
                    "1111111111111": {
                        "offerId": "1111111111111",
                        "category": "APARTMENT",
                    },
                    "2222222222222": {
                        "offerId": "2222222222222",
                        "category": "HOUSE",
                    },
                },
                "pagination": {"totalPages": 1},
            }
        }
    )


@pytest.fixture
def listing_fallback_html() -> str:
    """Страница списка без JSON состояния (ссылки в HTML)."""
    return (
        "<html><body>"
        '<a href="/offer/3333333333333/?from=serp">Объявление 1</a>'
        '<a href="/offer/3333333333333/?from=serp">Дубликат</a>'
        '<a href="https://realty.yandex.ru/offer/4444444444444/">Объявление 2</a>'
        '<a href="/vladivostok/kupit/kvartira/">Не объявление</a>'
        "</body></html>"
    )


@pytest.fixture
def offer_jsonld_html() -> str:
    """Страница объявления только с JSON-LD разметкой."""
    payload = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "1-комнатная квартира, 31,7 м²",
        "description": "Светлая квартира рядом с морем",
        "sku": SECOND_OFFER_ID,
        "image": [
            "https://avatars.mds.yandex.net/get-realty/2/1.jpg",
            "https://avatars.mds.yandex.net/get-realty/2/2.jpg",
        ],
        "offers": {
            "@type": "Offer",
            "price": "5814699",
            "priceCurrency": "RUR",
            "availableAtOrFrom": {
                "address": {
                    "addressRegion": "Приморский край",
                    "addressLocality": "Владивосток",
                    "streetAddress": "Светланская, 1",
                },
                "geo": {"latitude": "43.11", "longitude": "131.88"},
            },
        },
        "floorSize": {"value": "31.7", "unitCode": "SQM"},
        "numberOfRooms": "1",
    }

    return (
        "<html><head>"
        '<script type="application/ld+json">'
        f"{json.dumps(payload, ensure_ascii=False)}"
        "</script></head>"
        "<body><h1>1-комнатная квартира, 31,7 м²</h1></body></html>"
    )


@pytest.fixture
def offer_plain_html() -> str:
    """Страница объявления только с HTML-разметкой (без JSON)."""
    return (
        "<html><head>"
        f'<link rel="canonical" href="https://realty.yandex.ru/offer/{SECOND_OFFER_ID}/">'
        "</head><body>"
        "<h1>Студия, 25 м²</h1>"
        '<div data-testid="offer-price">7 200 000 ₽</div>'
        '<div data-testid="offer-description">Уютная студия у парка</div>'
        '<div data-testid="offer-address">Владивосток, Светланская, 5</div>'
        '<div data-testid="breadcrumbs">'
        "<a>Главная</a><a>Недвижимость</a><a>Квартиры</a>"
        "</div>"
        '<img src="https://avatars.mds.yandex.net/get-realty/3/1.jpg">'
        '<img src="https://example.com/logo.png">'
        "<ul>"
        "<li><span>Этаж</span> 7 из 12</li>"
        "<li><span>Общая площадь</span> 25 м²</li>"
        "<li><span>Количество комнат</span> студия</li>"
        "<li><span>Год постройки</span> 2021</li>"
        "</ul>"
        "</body></html>"
    )
