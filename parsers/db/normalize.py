from __future__ import annotations

"""Маппинги и нормализация полей из JSON парсеров в поля БД.

site: Avito/Cian/Yandex -> sites.code
object_type, housing_type, deal_type
rooms_count (Avito строка -> int или None)
ceiling_height (Yandex см -> м, если > 10)
area/living_area/kitchen_area/price/price_per_meter: float/int
value_type маппинг: text/number/bool
slug для новых EAV-кодов: транслит + [a-z0-9_]+
"""

import re
from typing import Any, Optional

# --- site ---
SITE_CODE_MAP: dict[str, str] = {
    "Avito": "avito",
    "Avtito": "avito",
    "ЦИАН": "cian",
    "Cian": "cian",
    "CIAN": "cian",
    "Яндекс": "yandex",
    "Yandex": "yandex",
    "YANDEX": "yandex",
    "Яндекс Недвижимость": "yandex",
}

DOMAIN_TO_SITE: dict[str, str] = {
    "avito.ru": "avito",
    "cian.ru": "cian",
    "realty.yandex.ru": "yandex",
    "yandex.ru": "yandex",
}


def normalize_site(site_raw: str, url: str = "") -> str:
    """Вернуть sites.code."""
    if site_raw in SITE_CODE_MAP:
        return SITE_CODE_MAP[site_raw]
    for domain, code in DOMAIN_TO_SITE.items():
        if domain in url:
            return code
    return "avito"


# --- object_type ---
VALID_OBJECT_TYPES = {"flat", "room", "studio", "house", "land_plot", "garage", "other"}

OBJECT_TYPE_MAP: dict[str, str] = {
    "flat": "flat",
    "квартира": "flat",
    "apartment": "flat",
    "room": "room",
    "комната": "room",
    "studio": "studio",
    "студия": "studio",
    "house": "house",
    "дом": "house",
    "land_plot": "land_plot",
    "участок": "land_plot",
    "garage": "garage",
    "гараж": "garage",
    "garage_place": "garage",
    "машиноместо": "garage",
    "other": "other",
    "коммерция": "other",
    "commercial": "other",
}


def normalize_object_type(raw: str) -> str:
    """Вернуть валидный object_type code."""
    if not raw:
        return "other"
    lower = raw.lower().strip()
    if lower in VALID_OBJECT_TYPES:
        return lower
    if lower in OBJECT_TYPE_MAP:
        return OBJECT_TYPE_MAP[lower]
    return "other"


# --- housing_type ---
HOUSING_TYPE_MAP: dict[str, str] = {
    "новостройка": "new_building",
    "new_building": "new_building",
    "вторичка": "secondary",
    "вторичный": "secondary",
    "secondary": "secondary",
    "вторович": "secondary",
}


def normalize_housing_type(raw: str) -> Optional[str]:
    """Вернуть housing_type code или None."""
    if not raw:
        return None
    lower = raw.lower().strip()
    if lower in ("new_building", "новостройка"):
        return "new_building"
    if lower in ("secondary", "вторичка", "вторичный"):
        return "secondary"
    return None


# --- deal_type ---
DEAL_TYPE_MAP: dict[str, str] = {
    "sale": "sale",
    "продажа": "sale",
    "продаж": "sale",
    "rent": "rent",
    "аренда": "rent",
    "аренд": "rent",
}


def normalize_deal_type(raw: str) -> str:
    """Вернуть deal_type code, fallback 'sale'."""
    if not raw:
        return "sale"
    lower = raw.lower().strip()
    if lower in DEAL_TYPE_MAP:
        return DEAL_TYPE_MAP[lower]
    if "аренд" in lower or "rent" in lower:
        return "rent"
    return "sale"


# --- rooms_count (Avito: строка) ---
def normalize_rooms_count(raw: Any) -> Optional[int]:
    """Avito: «2» -> 2, «студия»/«свободная планировка» -> None."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, float):
        return int(raw) if raw > 0 else None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
        try:
            val = int(raw)
            return val if val > 0 else None
        except ValueError:
            pass
        try:
            val = float(raw)
            iv = int(val)
            return iv if iv > 0 else None
        except ValueError:
            pass
        lower = raw.lower()
        if "студия" in lower or "свободн" in lower or "планировк" in lower:
            return None
    return None


# --- ceiling_height (Yandex: см -> м если > 10) ---
def normalize_ceiling_height(raw: Any) -> Optional[float]:
    """Yandex может отдавать сантиметры (287.0) -> 2.87, если > 10."""
    if raw is None:
        return None
    try:
        val = float(raw)
    except (ValueError, TypeError):
        return None
    if val <= 0:
        return None
    if val > 10:
        val = val / 100.0
    if val > 30:
        return None
    return round(val, 2)


# --- numeric fields ---
def normalize_area(raw: Any) -> Optional[float]:
    """float, отрицательные -> None."""
    if raw is None:
        return None
    try:
        val = float(raw)
    except (ValueError, TypeError):
        return None
    return val if val > 0 else None


def normalize_int_field(raw: Any) -> Optional[int]:
    """int, отрицательные -> None."""
    if raw is None:
        return None
    try:
        val = int(raw)
    except (ValueError, TypeError):
        return None
    return val if val >= 0 else None


def normalize_price(raw: Any) -> Optional[int]:
    """float/int, отрицательные -> None. Возвращаем int."""
    if raw is None:
        return None
    try:
        val = float(raw)
    except (ValueError, TypeError):
        return None
    return int(val) if val > 0 else None


def normalize_price_per_meter(raw: Any) -> Optional[int]:
    """float/int, отрицательные -> 0."""
    if raw is None:
        return None
    try:
        val = float(raw)
    except (ValueError, TypeError):
        return None
    return int(val) if val > 0 else None


# --- value_type маппинг ---
BOOL_TRUE = {"true", "да", "yes", "1", "yes"}
BOOL_FALSE = {"false", "нет", "no", "0", "no"}


def normalize_bool_value(raw: Any) -> Optional[bool]:
    """«True»/«False»/«да»/«нет» -> bool, None -> None."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    lower = str(raw).lower().strip()
    if lower in BOOL_TRUE:
        return True
    if lower in BOOL_FALSE:
        return False
    return None


def get_value_type(raw_key: str, raw_value: Any) -> tuple[str, Any]:
    """Определить тип значения и нормализовать.

    Возвращает (value_type, normalized_value).
    value_type: 'text', 'number', 'bool'
    """
    if raw_value is None or raw_value == "":
        return ("text", "")

    if isinstance(raw_value, bool):
        return ("bool", raw_value)

    str_val = str(raw_value).strip().lower()
    if str_val in BOOL_TRUE or str_val in BOOL_FALSE:
        return ("bool", normalize_bool_value(raw_value))

    try:
        num = float(raw_value)
        if str(num) == str_val or str(num) == str(float(raw_value)):
            return ("number", num)
    except (ValueError, TypeError):
        pass

    return ("text", str(raw_value))


# --- slug для новых EAV-кодов ---
CYRILLIC_MAP = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd',
    'е': 'e', 'ё': 'yo', 'ж': 'zh', 'з': 'z', 'и': 'i',
    'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n',
    'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't',
    'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch',
    'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '',
    'э': 'e', 'ю': 'yu', 'я': 'ya',
}


def translit(text: str) -> str:
    """Транслитерация кириллицы."""
    result = []
    for ch in text.lower():
        if ch in CYRILLIC_MAP:
            result.append(CYRILLIC_MAP[ch])
        elif ch.isascii() and (ch.isalnum() or ch in ('_', '-')):
            result.append(ch)
        elif ch.isdigit() or ch in ('_', '-'):
            result.append(ch)
        else:
            result.append('_')
    return ''.join(result)


def slugify(key: str) -> str:
    """Сделать slug: транслит + [a-z0-9_]+, максимум 64 символа."""
    s = translit(key)
    s = re.sub(r'[^a-z0-9_]+', '_', s)
    s = s.strip('_')
    if len(s) > 64:
        s = s[:64]
        s = s.rstrip('_')
    return s


def unique_slug(slug: str, existing: set[str], suffixes: dict[str, int] | None = None) -> str:
    """Уникализировать slug: _2, _3..."""
    if suffixes is None:
        suffixes = {}
    if slug not in existing:
        return slug
    counter = suffixes.get(slug, 0) + 1
    suffixes[slug] = counter
    base = slug
    while f"{base}_{counter}" in existing:
        counter += 1
    result = f"{slug}_{counter}"
    return result[:64].rstrip('_')


# --- address components ---
def normalize_address_component(val: Any) -> str:
    """Привести компонент адреса к '' вместо None."""
    if val is None:
        return ""
    s = str(val).strip()
    return s if s else ""


# --- location dict builder ---
def build_location_dict(data: dict) -> dict:
    """Собрать location из geo_label или address."""
    geo = data.get("geo_label") or {}
    return {
        "region": normalize_address_component(geo.get("region")),
        "city": normalize_address_component(geo.get("city")),
        "district": normalize_address_component(geo.get("district")),
        "micro_district": normalize_address_component(geo.get("micro_district")),
        "street": normalize_address_component(geo.get("street")),
        "house": normalize_address_component(geo.get("house")),
        "address": normalize_address_component(data.get("address")),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
    }


# --- building fields ---
BUILDING_FIELDS = [
    "year_building", "building_status", "building_material", "building_type",
    "building_section", "floors_material", "floors_count", "floors_range",
    "entrances_count", "apartments_count", "completion_date", "parking",
    "heating", "concierge", "barrier", "emergency", "ramp", "garbage_chute",
]


def build_building_dict(data: dict) -> dict:
    """Собрать данные дома из JSON."""
    result: dict[str, Any] = {}
    for field in BUILDING_FIELDS:
        val = data.get(field)
        if field in ("concierge", "barrier", "emergency", "ramp", "garbage_chute"):
            result[field] = normalize_bool_value(val)
        else:
            result[field] = val if val else None
    return result