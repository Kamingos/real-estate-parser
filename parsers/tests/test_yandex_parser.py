"""Юнит-тесты парсера Яндекс Недвижимости (без реального браузера)."""

import builtins
import json

import pytest
from conftest import (
    OFFER_ID,
    OFFER_URL,
    SECOND_OFFER_ID,
    SECOND_OFFER_URL,
    make_config,
)
from selenium.common.exceptions import WebDriverException

from model.site_parse_data_model import YandexSiteParseData
from realizations import yandex_parser as yp
from realizations.yandex_parser import YandexParser


class FakeDriver:
    """Минимальная замена selenium Chrome для тестов."""

    def __init__(self, pages=None, captcha_first=False):
        self.pages = pages or {}
        self.current_url = ""
        self.page_source = ""
        self.quit_called = False
        self.get_calls = []
        self.timeout = None
        self._captcha_first = captcha_first
        self._served = 0

    def set_page_load_timeout(self, timeout):
        self.timeout = timeout

    def execute_cdp_cmd(self, *_args, **_kwargs):
        return None

    def execute_script(self, *_args, **_kwargs):
        return None

    def get(self, url):
        self.get_calls.append(url)
        self.current_url = url
        self._served += 1

        if self._captcha_first and self._served == 1:
            self.page_source = "<html>Are you not a robot?</html>"
            return

        self.page_source = self.pages.get(url, self.pages.get("*", ""))

    def quit(self):
        self.quit_called = True


class FlakyDriver(FakeDriver):
    """Драйвер, первые N вызовов get завершающиеся сетевой ошибкой."""

    def __init__(self, failures, html):
        super().__init__({"*": html})
        self.failures = failures
        self.calls = 0

    def get(self, url):
        self.calls += 1

        if self.calls <= self.failures:
            raise WebDriverException("network error")

        super().get(url)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Убирает реальные паузы и ожидание DOM в тестах."""
    monkeypatch.setattr(yp, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        YandexParser, "_wait_for_content", lambda *_args, **_kwargs: None
    )


def test_looks_like_captcha():
    assert yp._looks_like_captcha("<html>Are you not a robot?</html>")
    assert yp._looks_like_captcha(
        "<html>Подтвердите, что вы не робот</html>"
    )
    assert yp._looks_like_captcha("<html></html>", "https://showcaptcha.yandex.ru/x")
    assert not yp._looks_like_captcha(
        "<html><h1>2-комнатная квартира</h1></html>",
        "https://realty.yandex.ru/offer/1/",
    )


def test_looks_like_not_found():
    not_found_html = (
        "<html><head><title>Ошибка 404 - Страница не найдена</title></head>"
        "<body><h1>Не&nbsp;удалось открыть страницу</h1>"
        '<a href="/offer/4883053629432287180/">объявление</a></body></html>'
    )

    assert yp._looks_like_not_found(not_found_html)
    assert not yp._looks_like_not_found(
        "<html><head><title>Купить квартиру</title></head>"
        "<body><h1>Купить квартиру во Владивостоке</h1></body></html>"
    )


def test_load_page_returns_none_on_404(yandex_parser):
    not_found_html = (
        "<html><head><title>Ошибка 404 - Страница не найдена</title></head>"
        "<body><h1>Не&nbsp;удалось открыть страницу</h1></body></html>"
    )
    driver = FakeDriver({"*": not_found_html})

    assert yandex_parser._load_page(driver, OFFER_URL, 1, max_attempts=2) is None


def test_category_urls_exclude_dead_newbuilding_paths():
    templates = yp.CATEGORY_URLS["newbuilding"]

    assert any("kupit/kvartira/novostroyki" in template for template in templates)
    assert not any("kupit/novostroyka/" in template for template in templates)
    assert not any("/novostrojki/" in template for template in templates)


def test_normalization_helpers():
    assert yp._to_int("1 250 000 ₽") == 1250000
    assert yp._to_float("54,3 м²") == 54.3
    assert yp._normalize_currency("RUR") == "RUB"
    assert yp._normalize_currency("₽") == "RUB"
    assert yp._normalize_seller_type("AGENCY") == "Агентство"
    assert yp._normalize_seller_type("OWNER") == "Частное лицо"
    assert yp._normalize_area_unit("SQM") == "м²"
    assert yp._normalize_area_unit("SOTKA") == "сот."


def test_extract_listing_urls_from_state(yandex_parser, listing_state_html):
    urls = yandex_parser._extract_listing_urls(
        listing_state_html,
        "https://realty.yandex.ru/vladivostok/kupit/kvartira/?page=1",
    )

    assert urls == [
        "https://realty.yandex.ru/offer/1111111111111/",
        "https://realty.yandex.ru/offer/2222222222222/",
    ]


def test_extract_listing_urls_html_fallback(yandex_parser, listing_fallback_html):
    urls = yandex_parser._extract_listing_urls(
        listing_fallback_html,
        "https://realty.yandex.ru/vladivostok/kupit/kvartira/?page=1",
    )

    assert urls == [
        "https://realty.yandex.ru/offer/3333333333333/",
        "https://realty.yandex.ru/offer/4444444444444/",
    ]


def test_canonical_offer_url(yandex_parser):
    assert (
        yandex_parser._canonical_offer_url("/offer/1234567890123/?from=serp")
        == OFFER_URL
    )
    assert yandex_parser._canonical_offer_url("/vladivostok/kupit/kvartira/") is None
    assert (
        yandex_parser._canonical_offer_url("https://example.com/offer/1234567890123/")
        is None
    )


def test_parse_offer_from_initial_state(
    yandex_parser,
    offer_state_html,
):
    driver = FakeDriver({OFFER_URL: offer_state_html})

    item = yandex_parser._parse_offer_page(driver, OFFER_URL, 5, 1)

    assert isinstance(item, YandexSiteParseData)
    assert item.site == "Yandex"
    assert item.url == OFFER_URL
    assert item.external_id == OFFER_ID
    assert item.name == "2-комнатная квартира, 54,3 м²"
    assert item.category == "APARTMENT"
    assert item.object_type == "flat"
    assert item.housing_type == "вторичка"
    assert item.offer_article == "DNV-42"

    # Цена и условия сделки
    assert item.price == 9500000
    assert item.price_per_meter == round(9500000 / 54.3)
    assert item.currency == "RUB"
    assert item.deal_type == "sale"
    assert item.mortgage_possible is True
    assert item.sale_method == "FREE"

    # Характеристики
    assert item.area == 54.3
    assert item.area_unit == "м²"
    assert item.living_area == 31.2
    assert item.kitchen_area == 9.8
    assert item.rooms_count == 2
    assert item.floor == 5
    assert item.floors_count == 17
    assert item.ceiling_height == 2.75
    assert item.bathroom == "раздельный"
    assert item.balcony == "лоджия"
    assert item.window_view == "во двор"
    assert item.repairs == "чистовая"
    assert item.finishing == "чистовая"

    # Дом
    assert item.year_building == 2019
    assert item.building_status == "сдан"
    assert item.building_material == "монолит"
    assert item.entrances_count == 3
    assert item.elevators == ["пассажирский (2)", "грузовой (1)"]
    assert item.parking == "подземная"

    # ЖК и застройщик
    assert item.residential_complex == "ЖК «Тихий»"
    assert item.residential_complex_class == "комфорт"
    assert item.residential_complex_completion == "4 квартал 2024"
    assert item.developer == "СК Пример"
    assert item.developer_foundation_year == 2005
    assert item.developer_completed_buildings == 12
    assert item.developer_buildings_under_construction == 2

    # География
    assert item.geo_label == {
        "region": "Приморский край",
        "city": "Владивосток",
        "district": "Первореченский",
        "micro_district": "Снеговая падь",
        "street": "Снежная",
        "house": "12",
    }
    assert item.latitude == 43.2
    assert item.longitude == 131.9
    assert "Владивосток" in item.address

    # Продавец, фото, статистика
    assert item.seller_name == "Иван"
    assert item.seller_type == "Частное лицо"
    assert item.agency == "ИП Иванов"
    assert item.imgs == [
        "https://avatars.mds.yandex.net/get-realty/1/1.jpg",
        "https://avatars.mds.yandex.net/get-realty/1/2.jpg",
    ]
    assert item.photos_count == 2
    assert item.publish_date == "2026-11-01T10:00:00Z"
    assert item.update_date == "2026-11-10T10:00:00Z"
    assert item.views_count == 123
    assert item.badges == ["Хорошая цена"]
    assert item.nearby_infrastructure == ["школа", "парк"]

    # Сырые характеристики
    assert item.parameters == {"Ремонт": "евро", "Санузел": "раздельный"}
    assert "Ремонт: евро" in item.feature_chips

    # Участок
    assert item.land_area == 6.0
    assert item.land_area_unit == "сот."


def test_parse_offer_json_ld_fallback(yandex_parser, offer_jsonld_html):
    driver = FakeDriver({SECOND_OFFER_URL: offer_jsonld_html})

    item = yandex_parser._parse_offer_page(driver, SECOND_OFFER_URL, 5, 1)

    assert item is not None
    assert item.external_id == SECOND_OFFER_ID
    assert item.name == "1-комнатная квартира, 31,7 м²"
    assert item.price == 5814699
    assert item.currency == "RUB"
    assert item.area == 31.7
    assert item.area_unit == "м²"
    assert item.rooms_count == 1
    assert item.latitude == 43.11
    assert item.longitude == 131.88
    assert item.geo_label["city"] == "Владивосток"
    assert item.geo_label["region"] == "Приморский край"
    assert len(item.imgs) == 2


def test_parse_offer_html_fallback(yandex_parser, offer_plain_html):
    driver = FakeDriver({SECOND_OFFER_URL: offer_plain_html})

    item = yandex_parser._parse_offer_page(driver, SECOND_OFFER_URL, 5, 1)

    assert item is not None
    assert item.external_id == SECOND_OFFER_ID
    assert item.name == "Студия, 25 м²"
    assert item.price == 7200000
    assert item.description == "Уютная студия у парка"
    assert item.address == "Владивосток, Светланская, 5"
    assert item.floor == 7
    assert item.floors_count == 12
    assert item.area == 25.0
    assert item.year_building == 2021
    assert item.imgs == ["https://avatars.mds.yandex.net/get-realty/3/1.jpg"]
    assert item.breadcrumbs == ["Главная", "Недвижимость", "Квартиры"]


def test_parse_offer_without_sources_returns_none(yandex_parser):
    driver = FakeDriver({OFFER_URL: "<html><body></body></html>"})

    assert yandex_parser._parse_offer_page(driver, OFFER_URL, 5, 1) is None


def test_validate_item(yandex_parser):
    valid = YandexSiteParseData(
        site="Yandex",
        url=OFFER_URL,
        external_id=OFFER_ID,
        name="Квартира",
        price=1000,
    )
    assert yandex_parser._validate_item(valid) is True

    invalid = YandexSiteParseData(
        site="Yandex",
        url=OFFER_URL,
        external_id=OFFER_ID,
        name="Квартира",
        price=0,
    )
    assert yandex_parser._validate_item(invalid) is False

    clipped = YandexSiteParseData(
        site="Yandex",
        url=OFFER_URL,
        external_id=OFFER_ID,
        name="Квартира",
        price=1000,
        area=-5.0,
        floor=-1,
    )
    assert yandex_parser._validate_item(clipped) is True
    assert clipped.area == 0.0
    assert clipped.floor == 0


def test_collect_offer_urls_pagination(yandex_parser, monkeypatch):
    pages = {
        1: ["https://realty.yandex.ru/offer/1111111111111/"],
        2: ["https://realty.yandex.ru/offer/2222222222222/"],
        3: [],
    }
    calls = []

    def fake_parse_listing(driver, page_url, page_wait, max_retries):
        page = int(page_url.rsplit("page=", 1)[-1])
        calls.append(page)
        return True, pages[page]

    monkeypatch.setattr(yandex_parser, "_parse_listing_page", fake_parse_listing)

    urls = yandex_parser._collect_offer_urls(
        driver=FakeDriver(),
        city_slug="vladivostok",
        rgid=585430,
        category="flat",
        max_pages=5,
        page_wait=1,
        min_delay=0.0,
        max_delay=0.0,
        max_retries=1,
    )

    assert calls == [1, 2, 3]
    assert urls == [
        "https://realty.yandex.ru/offer/1111111111111/",
        "https://realty.yandex.ru/offer/2222222222222/",
    ]


def test_collect_offer_urls_falls_back_to_next_template(yandex_parser, monkeypatch):
    """Первый URL-кандидат отдал 404 — парсер должен попробовать следующий."""
    ok_url = "https://realty.yandex.ru/offer/3333333333333/"
    calls = []

    def fake_parse_listing(driver, page_url, page_wait, max_retries):
        calls.append(page_url)

        if "novostroyki" in page_url:
            return False, []

        return True, [ok_url]

    monkeypatch.setattr(yandex_parser, "_parse_listing_page", fake_parse_listing)

    urls = yandex_parser._collect_offer_urls(
        driver=FakeDriver(),
        city_slug="vladivostok",
        rgid=585430,
        category="newbuilding",
        max_pages=1,
        page_wait=1,
        min_delay=0.0,
        max_delay=0.0,
        max_retries=1,
    )

    assert urls == [ok_url]
    assert len(calls) == 2
    assert "novostrojka" in calls[1]


def test_load_page_retries_with_backoff(yandex_parser, monkeypatch):
    sleeps = []
    monkeypatch.setattr(yp, "sleep", lambda seconds: sleeps.append(seconds))

    html = "<html><h1>Квартира</h1></html>"
    driver = FlakyDriver(failures=2, html=html)

    result = yandex_parser._load_page(driver, OFFER_URL, 1, max_attempts=3)

    assert result == html
    assert driver.calls == 3
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]


def test_load_page_handles_captcha(yandex_parser, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(builtins, "input", lambda _prompt="": "")

    html = "<html><h1>Квартира</h1></html>"
    driver = FakeDriver({"*": html}, captcha_first=True)

    result = yandex_parser._load_page(driver, OFFER_URL, 1, max_attempts=2)

    assert result == html
    assert (tmp_path / "yandex_captcha_debug.html").exists()


def test_parse_pipeline_deduplicates_and_quits(yandex_parser, monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(
        yp.webdriver, "Chrome", lambda **_kwargs: driver
    )

    collect_calls = []

    def fake_collect(**kwargs):
        collect_calls.append(kwargs["category"])
        return [OFFER_URL]

    item = YandexSiteParseData(
        site="Yandex",
        url=OFFER_URL,
        external_id=OFFER_ID,
        name="Квартира",
        price=1000,
    )

    monkeypatch.setattr(yandex_parser, "_collect_offer_urls", fake_collect)
    monkeypatch.setattr(
        yandex_parser, "_parse_offer_page", lambda *_args, **_kwargs: item
    )

    success, result = yandex_parser.parse(make_config())

    assert success is True
    assert result == [item]
    assert driver.quit_called is True
    assert len(collect_calls) == len(yandex_parser.categories)


def test_title_fallback_fills_area_rooms_and_type(yandex_parser):
    html = (
        "<html><body>"
        "<h1>43 м², 1-комнатная квартира</h1>"
        '<div data-testid="offer-price">10 900 000 ₽</div>'
        "</body></html>"
    )
    driver = FakeDriver({OFFER_URL: html})

    item = yandex_parser._parse_offer_page(driver, OFFER_URL, 5, 1)

    assert item is not None
    assert item.name == "43 м², 1-комнатная квартира"
    assert item.price == 10900000
    assert item.area == 43.0
    assert item.area_unit == "м²"
    assert item.rooms_count == 1
    assert item.object_type == "flat"
    assert item.category == "APARTMENT"
    assert item.price_per_meter == round(10900000 / 43)


def test_title_fallback_for_land_plot(yandex_parser):
    html = (
        "<html><body>"
        "<h1>10 соток, участок</h1>"
        '<div data-testid="offer-price">500 000 ₽</div>'
        "</body></html>"
    )
    driver = FakeDriver({OFFER_URL: html})

    item = yandex_parser._parse_offer_page(driver, OFFER_URL, 5, 1)

    assert item is not None
    assert item.object_type == "land_plot"
    assert item.area == 10.0
    assert item.land_area == 10.0
    assert item.area_unit == "сот."
    assert item.price_unit == "сот."
    assert item.price_per_meter == 50000


def test_title_fallback_prefers_land_area(yandex_parser):
    html = (
        "<html><body>"
        "<h1>12,3 м² дом, 12 соток участок</h1>"
        '<div data-testid="offer-price">1 200 000 ₽</div>'
        "</body></html>"
    )
    driver = FakeDriver({OFFER_URL: html})

    item = yandex_parser._parse_offer_page(driver, OFFER_URL, 5, 1)

    assert item is not None
    assert item.object_type == "land_plot"
    assert item.area == 12.0
    assert item.land_area == 12.0
    assert item.area_unit == "сот."
    assert item.price_unit == "сот."


def test_filter_photo_urls_removes_interface_images(yandex_parser):
    urls = [
        "https://s.realty.yandex.net/build-static/app.webp",
        "https://avatars.mds.yandex.net/get-vertis-journal/1/cover.jpg",
        "https://avatars.mds.yandex.net/get-realty/1/1.jpg",
        "//avatars.mds.yandex.net/get-altay/2/2.jpg",
        "https://avatars.mds.yandex.net/get-realty/1/icon.svg",
        "https://example.com/photo.jpg",
    ]

    assert yandex_parser._filter_photo_urls(urls) == [
        "https://avatars.mds.yandex.net/get-realty/1/1.jpg",
        "https://avatars.mds.yandex.net/get-altay/2/2.jpg",
    ]


def test_extract_initial_state_from_next_data(yandex_parser):
    state = {
        "props": {
            "pageProps": {
                "offer": {
                    "offerId": OFFER_ID,
                    "title": "1-комнатная квартира, 31,7 м²",
                }
            }
        }
    }
    html = (
        "<html><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(state, ensure_ascii=False)}"
        "</script></body></html>"
    )

    assert yandex_parser._extract_initial_state(html) == state


def test_extract_initial_state_from_json_parse(yandex_parser):
    state = {"offer": {"offerId": OFFER_ID, "title": "Квартира"}}
    html = (
        "<html><body><script>"
        "window.__INITIAL_STATE__ = "
        f"JSON.parse({json.dumps(json.dumps(state, ensure_ascii=False))});"
        "</script></body></html>"
    )

    assert yandex_parser._extract_initial_state(html) == state


def test_validate_item_rejects_residential_without_area(yandex_parser):
    item = YandexSiteParseData(
        site="Yandex",
        url=OFFER_URL,
        external_id=OFFER_ID,
        name="Квартира",
        price=1000,
        object_type="flat",
    )

    assert yandex_parser._validate_item(item) is False


def test_extract_initial_state_from_initial_state_script(yandex_parser):
    state = {
        "offerCard": {
            "card": {"offerId": OFFER_ID, "description": "DNV-01-02"}
        }
    }
    html = (
        "<html><body>"
        '<script id="initial_state_script">'
        f"window.INITIAL_STATE = {json.dumps(state, ensure_ascii=False)};"
        "</script></body></html>"
    )

    assert yandex_parser._extract_initial_state(html) == state


def test_pick_offer_returns_none_for_alien_card(yandex_parser):
    state = {
        "offerCard": {
            "card": {"offerId": SECOND_OFFER_ID},
            "relatedOffersData": {"offers": [{"offerId": SECOND_OFFER_ID}]},
        }
    }

    assert yandex_parser._pick_offer(state, OFFER_URL) is None


def test_related_offers_data_is_not_used(yandex_parser):
    target = {
        "offerId": OFFER_ID,
        "offerCategory": "APARTMENT",
        "description": "Целевое объявление",
        "price": {"value": 1000000, "currency": "RUR"},
        "area": {"value": 40.0, "unit": "SQUARE_METER"},
        "roomsTotal": 1,
        "floorsOffered": [3],
        "floorsTotal": 10,
        "newBuilding": False,
        "author": {"name": "Продавец", "category": "OWNER"},
        "location": {"address": "Владивосток, улица Тестовая, 1"},
        "totalImages": 2,
        "mainImages": [
            "//avatars.mds.yandex.net/get-realty-offers/1/main"
        ],
    }
    alien = {
        "offerId": SECOND_OFFER_ID,
        "offerCategory": "APARTMENT",
        "description": "Чужое объявление",
        "price": {"value": 9999999, "currency": "RUR"},
        "area": {"value": 99.0, "unit": "SQUARE_METER"},
        "roomsTotal": 9,
        "floorsOffered": [9],
        "floorsTotal": 99,
    }
    state = {
        "offerCard": {
            "card": target,
            "relatedOffersData": {"offers": [alien]},
        },
        "breadcrumbs": [],
    }
    html = (
        "<html><body>"
        '<script id="initial_state_script">'
        f"window.INITIAL_STATE = {json.dumps(state, ensure_ascii=False)};"
        "</script>"
        "<h1>1-комнатная квартира, 40 м²</h1>"
        "</body></html>"
    )

    item = yandex_parser._parse_offer_page(
        FakeDriver({OFFER_URL: html}), OFFER_URL, 5, 1
    )

    assert item is not None
    assert item.external_id == OFFER_ID
    assert item.description == "Целевое объявление"
    assert item.price == 1000000
    assert item.area == 40.0
    assert item.rooms_count == 1
    assert item.floor == 3
