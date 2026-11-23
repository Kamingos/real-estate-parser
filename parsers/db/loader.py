from __future__ import annotations

"""Загрузка одного объявления из JSON в PostgreSQL (3НФ схема).

Принимает словарь (один элемент JSON-массива парсера).
Выполняет все шаги по загрузке в одной транзакции.
"""

import logging
from typing import Any

import psycopg

from .normalize import (
    build_building_dict,
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
)
from .repositories import (
    MemoryCache,
    get_or_create_deal_type,
    get_or_create_developer,
    get_or_create_housing_type,
    get_or_create_object_type,
    get_or_create_site,
    get_or_create_tag,
    upsert_attribute_definition,
    upsert_building,
    upsert_location,
    upsert_residential_complex,
    upsert_seller,
)

logger = logging.getLogger(__name__)


# Маппинг русских лейблов на известные EAV-коды
RUSSIAN_LABEL_MAP: dict[str, str] = {
    "санузел": "bathroom",
    "балкон": "balcony",
    "вид из окон": "window_view",
    "ремонт": "repairs",
    "отделка": "finishing",
    "мебель": "furniture",
    "продаётся с мебелью": "sell_with_furniture",
    "комнат в квартире": "rooms_in_flat",
    "водоснабжение": "water_supply",
    "канализация": "sewerage",
    "газ": "gas",
    "электричество": "electricity",
    "интернет и тв": "internet_tv",
    "интернет": "internet",
    "телефон": "telephone",
    "сауна": "sauna",
    "категория земель": "land_category",
    "тип участка": "land_type",
    "площадь участка": "land_area",
    "единица площади участка": "land_area_unit",
    "тип гаража": "garage_type",
    "охрана": "security",
    "для отдыха": "recreation",
    "терраса или веранда": "terrace",
    "назначение помещения": "commercial_purpose",
    "тип входа": "entrance_type",
    "ширина входной двери": "entrance_door_width",
    "ширина межкомнатных дверей": "interior_doors_width",
    "единица площади": "area_unit",
    "количество комнат (как на сайте)": "rooms_count_raw",
    "тип дома": "building_material",
}


def _normalize_parameters_label(label: str) -> str:
    """Перевести русский лейбл на известный EAV-код или создать новый."""
    if not label:
        return slugify("unknown")
    lower = label.lower().strip()
    if lower in RUSSIAN_LABEL_MAP:
        return RUSSIAN_LABEL_MAP[lower]
    return slugify(label)


def load_offer(conn: psycopg.Connection, data: dict[str, Any], cache: MemoryCache, dry_run: bool = False) -> dict[str, int]:
    """Загрузить одно объявление из JSON в PostgreSQL."""
    stats: dict[str, int] = {
        "inserted": 0, "updated": 0, "skipped": 0, "errors": 0,
    }

    site_raw = data.get("site", "")
    url = data.get("url", "")
    site_code = normalize_site(site_raw, url)
    site_id = get_or_create_site(conn, cache, site_code)

    deal_type_raw = data.get("deal_type", "sale")
    deal_type_code = normalize_deal_type(deal_type_raw)
    deal_type_id = get_or_create_deal_type(conn, cache, deal_type_code)

    # 2. location
    location_dict = build_location_dict(data)
    location_id = upsert_location(
        conn,
        location_dict["region"],
        location_dict["city"],
        location_dict["district"],
        location_dict["micro_district"],
        location_dict["street"],
        location_dict["house"],
        location_dict["address"],
        location_dict["latitude"],
        location_dict["longitude"],
    )

    # 3. developers -> residential_complexes -> buildings
    building_id = None
    developer_name = data.get("developer", "")
    rc_name = data.get("residential_complex", "")

    if developer_name or rc_name:
        developer_id = None
        if developer_name:
            developer_id = get_or_create_developer(
                conn, developer_name,
                foundation_year=data.get("developer_foundation_year") or None,
                rating=data.get("developer_rating") or None,
                reviews_count=data.get("developer_reviews_count") or None,
                completed_buildings=data.get("developer_completed_buildings") or None,
                buildings_under_construction=data.get("developer_buildings_under_construction") or None,
                residential_complexes_count=data.get("developer_residential_complexes") or None,
                description=data.get("developer_description") or None,
            )

        if rc_name:
            rc_id = upsert_residential_complex(
                conn, rc_name, developer_id,
                class_=data.get("residential_complex_class"),
                type_=data.get("residential_complex_type"),
                completion=data.get("residential_complex_completion"),
                buildings_count=data.get("residential_complex_buildings_count") or None,
            )
            building_data = build_building_dict(data)
            if not building_data.get("completion_date") and data.get("residential_complex_completion"):
                building_data["completion_date"] = data["residential_complex_completion"]
            building_id = upsert_building(
                conn, location_id, rc_id,
                **{k: v for k, v in building_data.items() if v is not None},
            )

    # 4. seller
    seller_name = data.get("seller_name") or data.get("rieltor")
    seller_id = None
    if seller_name:
        seller_id = upsert_seller(
            conn, site_id, seller_name,
            contact_person=data.get("contact_person"),
            seller_type=data.get("seller_type"),
            agency=data.get("agency"),
            rating=data.get("seller_rating") or None,
            reviews_count=data.get("seller_reviews_count") or None,
            registered_year=data.get("seller_registered_year") or None,
            ads_count=data.get("seller_ads_count") or None,
            experience=data.get("seller_experience"),
            documents_verified=data.get("seller_documents_verified") or None,
        )

    # 5. properties
    canonical_name = (data.get("name", "") or "")[:512]
    object_type_code = normalize_object_type(data.get("object_type", "other"))
    object_type_id = get_or_create_object_type(conn, cache, object_type_code)
    housing_type_code = normalize_housing_type(data.get("housing_type", ""))
    housing_type_id = get_or_create_housing_type(conn, cache, housing_type_code)

    external_id = data.get("external_id", "")
    rooms_count_raw = normalize_rooms_count(data.get("rooms_count"))
    ceiling_height_raw = normalize_ceiling_height(data.get("ceiling_height"))
    area_raw = normalize_area(data.get("area"))
    living_area_raw = normalize_area(data.get("living_area"))
    kitchen_area_raw = normalize_area(data.get("kitchen_area"))
    floor_raw = normalize_int_field(data.get("floor"))
    cadastral_number = data.get("cadastral_number") or None

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, property_id FROM offers WHERE site_id = %s AND external_id = %s",
            (site_id, external_id),
        )
        existing = cur.fetchone()

    if existing and existing[1] is not None:
        property_id = existing[1]
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE properties SET
                    canonical_name = COALESCE(%s, canonical_name),
                    description = COALESCE(%s, description),
                    object_type_id = COALESCE(%s, object_type_id),
                    housing_type_id = COALESCE(%s, housing_type_id),
                    building_id = COALESCE(%s, building_id),
                    location_id = COALESCE(%s, location_id),
                    area = COALESCE(%s, area),
                    living_area = COALESCE(%s, living_area),
                    kitchen_area = COALESCE(%s, kitchen_area),
                    rooms_count = COALESCE(%s, rooms_count),
                    floor = COALESCE(%s, floor),
                    ceiling_height = COALESCE(%s, ceiling_height),
                    cadastral_number = COALESCE(%s, cadastral_number)
                 WHERE id = %s""",
                (
                    canonical_name, data.get("description"),
                    object_type_id, housing_type_id, building_id, location_id,
                    area_raw, living_area_raw, kitchen_area_raw,
                    rooms_count_raw, floor_raw, ceiling_height_raw,
                    cadastral_number, property_id,
                ),
            )
            stats["updated"] += 1
    else:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO properties (
                    canonical_name, description, object_type_id, housing_type_id,
                    building_id, location_id, area, living_area, kitchen_area,
                    rooms_count, floor, ceiling_height, cadastral_number)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    canonical_name, data.get("description"),
                    object_type_id, housing_type_id, building_id, location_id,
                    area_raw, living_area_raw, kitchen_area_raw,
                    rooms_count_raw, floor_raw, ceiling_height_raw,
                    cadastral_number,
                ),
            )
            property_id = cur.fetchone()[0]
            stats["inserted"] += 1

    # 6. offers: UPSERT
    price_raw = normalize_price(data.get("price"))
    price_per_meter_raw = normalize_price_per_meter(data.get("price_per_meter"))
    offer_article = data.get("offer_article")
    category = data.get("category")
    currency = data.get("currency", "RUB") or "RUB"
    price_unit = data.get("price_unit", "м²") or "м²"

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO offers (
                property_id, site_id, seller_id, deal_type_id, external_id, url,
                name, subtitles, description, offer_article, category,
                price, price_per_meter, price_unit, currency,
                deal_conditions, mortgage_possible, sale_method, participation_type,
                publish_date, update_date, views_count, views_today, photos_count,
                is_verified, parsed_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
               ON CONFLICT (site_id, external_id)
               DO UPDATE SET
                   property_id = COALESCE(EXCLUDED.property_id, offers.property_id),
                   seller_id = COALESCE(EXCLUDED.seller_id, offers.seller_id),
                   deal_type_id = COALESCE(EXCLUDED.deal_type_id, offers.deal_type_id),
                   url = EXCLUDED.url,
                   name = COALESCE(EXCLUDED.name, offers.name),
                   subtitles = COALESCE(EXCLUDED.subtitles, offers.subtitles),
                   description = COALESCE(EXCLUDED.description, offers.description),
                   offer_article = COALESCE(EXCLUDED.offer_article, offers.offer_article),
                   category = COALESCE(EXCLUDED.category, offers.category),
                   price = COALESCE(EXCLUDED.price, offers.price),
                   price_per_meter = COALESCE(EXCLUDED.price_per_meter, offers.price_per_meter),
                   price_unit = COALESCE(EXCLUDED.price_unit, offers.price_unit),
                   currency = COALESCE(EXCLUDED.currency, offers.currency),
                   deal_conditions = COALESCE(EXCLUDED.deal_conditions, offers.deal_conditions),
                   mortgage_possible = COALESCE(EXCLUDED.mortgage_possible, offers.mortgage_possible),
                   sale_method = COALESCE(EXCLUDED.sale_method, offers.sale_method),
                   participation_type = COALESCE(EXCLUDED.participation_type, offers.participation_type),
                   publish_date = COALESCE(EXCLUDED.publish_date, offers.publish_date),
                   update_date = COALESCE(EXCLUDED.update_date, offers.update_date),
                   views_count = COALESCE(EXCLUDED.views_count, offers.views_count),
                   views_today = COALESCE(EXCLUDED.views_today, offers.views_today),
                   photos_count = COALESCE(EXCLUDED.photos_count, offers.photos_count),
                   is_verified = COALESCE(EXCLUDED.is_verified, offers.is_verified),
                   parsed_at = now()
               RETURNING id""",
            (
                property_id, site_id, seller_id, deal_type_id, external_id, url,
                data.get("name"), data.get("subtitles"), data.get("description"),
                offer_article, category,
                price_raw, price_per_meter_raw, price_unit, currency,
                data.get("deal_conditions"),
                normalize_bool_value(data.get("mortgage_possible")),
                data.get("sale_method"), data.get("participation_type"),
                data.get("publish_date"), data.get("update_date"),
                data.get("views_count") or 0,
                data.get("views_today") or 0,
                data.get("photos_count") or 0,
                normalize_bool_value(data.get("is_verified")),
            ),
        )
        offer_id = cur.fetchone()[0]

    if existing and not existing[1]:
        stats["inserted"] += 1
    elif existing and existing[1]:
        stats["updated"] += 1
    else:
        stats["inserted"] += 1

    # 7. offer_images
    imgs = data.get("imgs") or []
    with conn.cursor() as cur:
        cur.execute("DELETE FROM offer_images WHERE offer_id = %s", (offer_id,))
        for idx, img_url in enumerate(imgs):
            cur.execute(
                "INSERT INTO offer_images (offer_id, url, position) VALUES (%s, %s, %s)",
                (offer_id, img_url, idx),
            )
        stats["inserted"] += len(imgs)

    # 8. offer_tags
    tag_mappings = {
        "badges": "badge",
        "feature_chips": "feature_chip",
        "nearby_infrastructure": "infrastructure",
        "courtyard": "courtyard",
        "elevators": "elevator",
        "breadcrumbs": "breadcrumb",
        "residential_complex_building_types": "rc_building_type",
        "residential_complex_parking": "rc_parking",
        "residential_complex_finishing": "rc_finishing",
        "residential_complex_promotions": "promotion",
    }

    with conn.cursor() as cur:
        cur.execute("DELETE FROM offer_tags WHERE offer_id = %s", (offer_id,))
        for list_key, tag_type_code in tag_mappings.items():
            tag_list = data.get(list_key) or []
            for tag_name in tag_list:
                tag_id = get_or_create_tag(conn, tag_type_code, str(tag_name))
                if tag_id > 0:
                    cur.execute(
                        "INSERT INTO offer_tags (offer_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (offer_id, tag_id),
                    )
                    stats["inserted"] += 1

    # 9. offer_legal_info
    rosreestr = normalize_bool_value(data.get("rosreestr_verified"))
    ownership_type = data.get("ownership_type")
    owners_count = data.get("owners_count")
    encumbrances = data.get("encumbrances")
    minors = normalize_bool_value(data.get("minors_owners"))
    maternity = normalize_bool_value(data.get("maternity_capital_used"))

    has_legal = any(v is not None for v in [rosreestr, ownership_type, owners_count,
                                            encumbrances, minors, maternity])
    if has_legal:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO offer_legal_info (offer_id, rosreestr_verified, ownership_type,
                   owners_count, encumbrances, minors_owners, maternity_capital_used)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (offer_id) DO UPDATE SET
                       rosreestr_verified = COALESCE(EXCLUDED.rosreestr_verified, offer_legal_info.rosreestr_verified),
                       ownership_type = COALESCE(EXCLUDED.ownership_type, offer_legal_info.ownership_type),
                       owners_count = COALESCE(EXCLUDED.owners_count, offer_legal_info.owners_count),
                       encumbrances = COALESCE(EXCLUDED.encumbrances, offer_legal_info.encumbrances),
                       minors_owners = COALESCE(EXCLUDED.minors_owners, offer_legal_info.minors_owners),
                       maternity_capital_used = COALESCE(EXCLUDED.maternity_capital_used, offer_legal_info.maternity_capital_used)""",
                (offer_id, rosreestr, ownership_type, owners_count, encumbrances, minors, maternity),
            )
        stats["inserted"] += 1

    # 10. property_attributes_*
    _insert_property_attributes(conn, property_id, data)

    # 11. offer_attributes_*
    _insert_offer_attributes(conn, offer_id, data)

    return stats


def _insert_property_attributes(
    conn: psycopg.Connection,
    property_id: int,
    data: dict[str, Any],
) -> None:
    """Вставить property_attributes_*."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM property_attributes_text WHERE property_id = %s", (property_id,))
        cur.execute("DELETE FROM property_attributes_number WHERE property_id = %s", (property_id,))
        cur.execute("DELETE FROM property_attributes_bool WHERE property_id = %s", (property_id,))

    flat_text = {
        "bathroom": data.get("bathroom"),
        "balcony": data.get("balcony"),
        "window_view": data.get("window_view"),
        "repairs": data.get("repairs"),
        "finishing": data.get("finishing"),
        "furniture": data.get("furniture"),
    }
    flat_bool = {
        "sell_with_furniture": data.get("sell_with_furniture"),
    }
    flat_number = {
        "rooms_in_flat": data.get("rooms_in_flat"),
    }

    with conn.cursor() as cur:
        for code, val in flat_text.items():
            if val is not None and val != "":
                attr_id, _ = upsert_attribute_definition(conn, "flat", code, code, "text")
                cur.execute(
                    "INSERT INTO property_attributes_text (property_id, attribute_id, value) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (property_id, attr_id, str(val)),
                )
        for code, val in flat_bool.items():
            if val is not None:
                attr_id, _ = upsert_attribute_definition(conn, "flat", code, code, "bool")
                cur.execute(
                    "INSERT INTO property_attributes_bool (property_id, attribute_id, value) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (property_id, attr_id, bool(val)),
                )
        for code, val in flat_number.items():
            if val is not None:
                attr_id, _ = upsert_attribute_definition(conn, "flat", code, code, "number")
                cur.execute(
                    "INSERT INTO property_attributes_number (property_id, attribute_id, value) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (property_id, attr_id, val),
                )


def _insert_offer_attributes(
    conn: psycopg.Connection,
    offer_id: int,
    data: dict[str, Any],
) -> None:
    """Вставить offer_attributes_* из сырых parameters."""
    parameters = data.get("parameters", {})
    if not parameters:
        return

    with conn.cursor() as cur:
        cur.execute("DELETE FROM offer_attributes_text WHERE offer_id = %s", (offer_id,))
        cur.execute("DELETE FROM offer_attributes_number WHERE offer_id = %s", (offer_id,))
        cur.execute("DELETE FROM offer_attributes_bool WHERE offer_id = %s", (offer_id,))

    for key, val in parameters.items():
        if val is None or val == "":
            continue
        attr_code = _normalize_parameters_label(key)
        val_type, normalized = get_value_type(key, val)
        with conn.cursor() as cur:
            attr_id, _ = upsert_attribute_definition(conn, "site_data", attr_code, str(key), val_type)
            if val_type == "text":
                cur.execute(
                    "INSERT INTO offer_attributes_text (offer_id, attribute_id, value) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (offer_id, attr_id, str(normalized)),
                )
            elif val_type == "number":
                cur.execute(
                    "INSERT INTO offer_attributes_number (offer_id, attribute_id, value) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (offer_id, attr_id, normalized),
                )
            elif val_type == "bool":
                cur.execute(
                    "INSERT INTO offer_attributes_bool (offer_id, attribute_id, value) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (offer_id, attr_id, normalized),
                )