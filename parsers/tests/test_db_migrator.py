from __future__ import annotations

"""Тесты для parsers/db/ — без подключения к БД."""

from db.normalize import (
    build_location_dict,
    get_value_type,
    normalize_area,
    normalize_bool_value,
    normalize_ceiling_height,
    normalize_deal_type,
    normalize_housing_type,
    normalize_int_field,
    normalize_object_type,
    normalize_price,
    normalize_price_per_meter,
    normalize_rooms_count,
    normalize_site,
    slugify,
    translit,
    unique_slug,
)


class TestNormalizeSite:
    def test_avito(self):
        assert normalize_site("Avito", "") == "avito"

    def test_cian(self):
        assert normalize_site("ЦИАН", "") == "cian"
        assert normalize_site("Cian", "") == "cian"

    def test_yandex(self):
        assert normalize_site("Яндекс", "") == "yandex"
        assert normalize_site("Yandex", "") == "yandex"

    def test_domain_fallback(self):
        assert normalize_site("", "https://avito.ru/offer/123") == "avito"
        assert normalize_site("", "https://realty.yandex.ru/offer/456") == "yandex"


class TestNormalizeObjectType:
    def test_flat(self):
        assert normalize_object_type("flat") == "flat"
        assert normalize_object_type("квартира") == "flat"

    def test_room(self):
        assert normalize_object_type("room") == "room"
        assert normalize_object_type("комната") == "room"

    def test_studio(self):
        assert normalize_object_type("studio") == "studio"
        assert normalize_object_type("студия") == "studio"

    def test_house(self):
        assert normalize_object_type("house") == "house"
        assert normalize_object_type("дом") == "house"

    def test_land_plot(self):
        assert normalize_object_type("land_plot") == "land_plot"
        assert normalize_object_type("участок") == "land_plot"

    def test_garage(self):
        assert normalize_object_type("garage") == "garage"
        assert normalize_object_type("гараж") == "garage"

    def test_other(self):
        assert normalize_object_type("") == "other"
        assert normalize_object_type("unknown") == "other"


class TestNormalizeHousingType:
    def test_new_building(self):
        assert normalize_housing_type("новостройка") == "new_building"

    def test_secondary(self):
        assert normalize_housing_type("вторичка") == "secondary"

    def test_none(self):
        assert normalize_housing_type("") is None
        assert normalize_housing_type(None) is None


class TestNormalizeDealType:
    def test_sale(self):
        assert normalize_deal_type("sale") == "sale"
        assert normalize_deal_type("продажа") == "sale"

    def test_rent(self):
        assert normalize_deal_type("rent") == "rent"
        assert normalize_deal_type("аренда") == "rent"

    def test_empty(self):
        assert normalize_deal_type("") == "sale"


class TestNormalizeRoomsCount:
    def test_int(self):
        assert normalize_rooms_count(2) == 2

    def test_string_number(self):
        assert normalize_rooms_count("3") == 3

    def test_studio(self):
        assert normalize_rooms_count("студия") is None
        assert normalize_rooms_count("свободная планировка") is None

    def test_empty(self):
        assert normalize_rooms_count(None) is None
        assert normalize_rooms_count("") is None

    def test_zero(self):
        assert normalize_rooms_count(0) is None


class TestNormalizeCeilingHeight:
    def test_normal(self):
        assert normalize_ceiling_height(2.8) == 2.8

    def test_cm_conversion(self):
        assert normalize_ceiling_height(287.0) == 2.87

    def test_negative(self):
        assert normalize_ceiling_height(-1.0) is None

    def test_empty(self):
        assert normalize_ceiling_height(None) is None


class TestNumericFields:
    def test_normalize_area(self):
        assert normalize_area(54.3) == 54.3
        assert normalize_area(-1.0) is None
        assert normalize_area(None) is None

    def test_normalize_int_field(self):
        assert normalize_int_field(5) == 5
        assert normalize_int_field(-1) is None

    def test_normalize_price(self):
        assert normalize_price(1000000) == 1000000
        assert normalize_price(-100) is None

    def test_normalize_price_per_meter(self):
        assert normalize_price_per_meter(50000) == 50000
        assert normalize_price_per_meter(-100) is None


class TestNormalizeBool:
    def test_true(self):
        assert normalize_bool_value(True) is True
        assert normalize_bool_value("True") is True
        assert normalize_bool_value("да") is True

    def test_false(self):
        assert normalize_bool_value(False) is False
        assert normalize_bool_value("False") is False
        assert normalize_bool_value("нет") is False

    def test_empty(self):
        assert normalize_bool_value(None) is None
        assert normalize_bool_value("") is None


class TestGetValueType:
    def test_text(self):
        vt, val = get_value_type("key", "hello")
        assert vt == "text"
        assert val == "hello"

    def test_number(self):
        vt, val = get_value_type("key", "123")
        assert vt == "number"
        assert val == 123.0

    def test_bool_true(self):
        vt, val = get_value_type("key", "да")
        assert vt == "bool"
        assert val is True

    def test_empty(self):
        vt, val = get_value_type("key", "")
        assert vt == "text"
        assert val == ""


class TestSlugify:
    def test_latin(self):
        result = slugify("bathroom")
        assert result == "bathroom"

    def test_cyrillic(self):
        result = slugify("Санузел")
        assert result == "sanuzel"

    def test_long_slug(self):
        long_name = "a" * 100
        result = slugify(long_name)
        assert len(result) <= 64

    def test_special_chars(self):
        result = slugify("Водоснабжение (холодное)")
        assert "vodosnabzhenie" in result


class TestUniqueSlug:
    def test_unique(self):
        existing = set()
        result = unique_slug("bathroom", existing)
        assert result == "bathroom"
        assert "bathroom" not in existing

    def test_duplicate(self):
        existing = {"bathroom"}
        suffixes = {}
        result = unique_slug("bathroom", existing, suffixes)
        assert result == "bathroom_1"


class TestTranslit:
    def test_hello(self):
        assert translit("привет") == "privet"

    def test_mixed(self):
        result = translit("Квартира 5а")
        assert "kvartira" in result


class TestBuildLocationDict:
    def test_from_geo_label(self):
        data = {
            "geo_label": {
                "region": "Приморский край",
                "city": "Владивосток",
                "district": "",
                "micro_district": "",
                "street": "Улицы Литовской",
                "house": "10",
            },
            "address": "Владивосток, Улицы Литовской, 10",
            "latitude": 43.1,
            "longitude": 131.8,
        }
        loc = build_location_dict(data)
        assert loc["city"] == "Владивосток"
        assert loc["house"] == "10"
        assert loc["latitude"] == 43.1

    def test_missing_geo_label(self):
        data = {
            "address": "Москва, Тверская, 1",
            "latitude": None,
            "longitude": None,
        }
        loc = build_location_dict(data)
        assert loc["city"] == ""
        assert loc["address"] == "Москва, Тверская, 1"