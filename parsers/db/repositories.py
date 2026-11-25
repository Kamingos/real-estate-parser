from __future__ import annotations

"""Справочники и сущности БД с кэшем в памяти.

Кэшируются: sites, object_types, housing_types, deal_types, tag_types,
attribute_categories, attribute_definitions (code -> id, value_type).

Методы для locations, developers, residential_complexes, buildings,
sellers, tags, attribute_definitions — INSERT ... ON CONFLICT DO UPDATE.
"""

import logging
from typing import Optional

import psycopg

logger = logging.getLogger(__name__)


class MemoryCache:
    """Кэш в памяти для справочников."""

    def __init__(self) -> None:
        self.sites: dict[str, int] = {}
        self.object_types: dict[str, int] = {}
        self.housing_types: dict[str, int] = {}
        self.deal_types: dict[str, int] = {}
        self.tag_types: dict[str, int] = {}
        self.attribute_categories: dict[str, int] = {}
        self.attribute_definitions: dict[str, dict] = {}

    def clear(self) -> None:
        attrs_to_clear = [
            "sites", "object_types", "housing_types", "deal_types",
            "tag_types", "attribute_categories", "attribute_definitions",
        ]
        for attr in attrs_to_clear:
            val = getattr(self, attr)
            if isinstance(val, dict):
                val.clear()


def _ensure_cache(conn: psycopg.Connection) -> MemoryCache:
    """Загрузить кэш из БД, если пуст."""
    return MemoryCache()


def _load_cache(conn: psycopg.Connection, cache: MemoryCache) -> None:
    """Загрузить справочники из БД в кэш."""
    if cache.sites:
        return

    with conn.cursor() as cur:
        cur.execute("SELECT id, code FROM sites")
        for row in cur.fetchall():
            cache.sites[row[1]] = row[0]

        cur.execute("SELECT id, code FROM object_types")
        for row in cur.fetchall():
            cache.object_types[row[1]] = row[0]

        cur.execute("SELECT id, code FROM housing_types")
        for row in cur.fetchall():
            cache.housing_types[row[1]] = row[0]

        cur.execute("SELECT id, code FROM deal_types")
        for row in cur.fetchall():
            cache.deal_types[row[1]] = row[0]

        cur.execute("SELECT id, code FROM tag_types")
        for row in cur.fetchall():
            cache.tag_types[row[1]] = row[0]

        cur.execute("SELECT id, code FROM attribute_categories")
        for row in cur.fetchall():
            cache.attribute_categories[row[1]] = row[0]

        cur.execute("SELECT id, code, value_type, category_id FROM attribute_definitions")
        for row in cur.fetchall():
            cache.attribute_definitions[row[1]] = {
                "id": row[0],
                "value_type": row[2],
                "category_id": row[3],
            }


def get_or_create_site(conn: psycopg.Connection, cache: MemoryCache, code: str) -> int:
    """Найти или создать site по code."""
    if code in cache.sites:
        return cache.sites[code]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sites (code) VALUES (%s) ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code "
            "RETURNING id",
            (code,),
        )
        site_id = cur.fetchone()[0]
        cache.sites[code] = site_id
        return site_id


def get_or_create_object_type(conn: psycopg.Connection, cache: MemoryCache, code: str) -> int:
    """Найти или создать object_type по code."""
    if code in cache.object_types:
        return cache.object_types[code]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO object_types (code) VALUES (%s) ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code "
            "RETURNING id",
            (code,),
        )
        ot_id = cur.fetchone()[0]
        cache.object_types[code] = ot_id
        return ot_id


def get_or_create_housing_type(conn: psycopg.Connection, cache: MemoryCache, code: Optional[str]) -> Optional[int]:
    """Найти или создать housing_type по code."""
    if code is None:
        return None
    if code in cache.housing_types:
        return cache.housing_types[code]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO housing_types (code) VALUES (%s) ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code "
            "RETURNING id",
            (code,),
        )
        ht_id = cur.fetchone()[0]
        cache.housing_types[code] = ht_id
        return ht_id


def get_or_create_deal_type(conn: psycopg.Connection, cache: MemoryCache, code: str) -> int:
    """Найти или создать deal_type по code."""
    if code in cache.deal_types:
        return cache.deal_types[code]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO deal_types (code) VALUES (%s) ON CONFLICT (code) DO UPDATE SET code = EXCLUDED.code "
            "RETURNING id",
            (code,),
        )
        dt_id = cur.fetchone()[0]
        cache.deal_types[code] = dt_id
        return dt_id


def upsert_location(
    conn: psycopg.Connection,
    region: str,
    city: str,
    district: str,
    micro_district: str,
    street: str,
    house: str,
    address: str,
    latitude: Optional[float],
    longitude: Optional[float],
) -> int:
    """INSERT ... ON CONFLICT (region, city, district, micro_district, street, house) DO UPDATE."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO locations (region, city, district, micro_district, street, house, address, latitude, longitude)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (region, city, district, micro_district, street, house)
               DO UPDATE SET
                   address = EXCLUDED.address,
                   latitude = COALESCE(EXCLUDED.latitude, locations.latitude),
                   longitude = COALESCE(EXCLUDED.longitude, locations.longitude)
               RETURNING id""",
            (region, city, district, micro_district, street, house, address, latitude, longitude),
        )
        return cur.fetchone()[0]


def get_or_create_developer(
    conn: psycopg.Connection,
    name: str,
    foundation_year: Optional[int] = None,
    rating: Optional[float] = None,
    reviews_count: Optional[int] = None,
    completed_buildings: Optional[int] = None,
    buildings_under_construction: Optional[int] = None,
    residential_complexes_count: Optional[int] = None,
    description: Optional[str] = None,
) -> int:
    """Найти или создать developer по name."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO developers (name, foundation_year, rating, reviews_count,
                 completed_buildings, buildings_under_construction, residential_complexes_count, description)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (name) DO UPDATE SET
                   foundation_year = COALESCE(EXCLUDED.foundation_year, developers.foundation_year),
                   rating = COALESCE(EXCLUDED.rating, developers.rating),
                   reviews_count = COALESCE(EXCLUDED.reviews_count, developers.reviews_count),
                   completed_buildings = COALESCE(EXCLUDED.completed_buildings, developers.completed_buildings),
                   buildings_under_construction = COALESCE(EXCLUDED.buildings_under_construction, developers.buildings_under_construction),
                   residential_complexes_count = COALESCE(EXCLUDED.residential_complexes_count, developers.residential_complexes_count),
                   description = COALESCE(EXCLUDED.description, developers.description)
               RETURNING id""",
            (name, foundation_year, rating, reviews_count, completed_buildings,
             buildings_under_construction, residential_complexes_count, description),
        )
        return cur.fetchone()[0]


def upsert_residential_complex(
    conn: psycopg.Connection,
    name: str,
    developer_id: Optional[int],
    class_: Optional[str] = None,
    type_: Optional[str] = None,
    completion: Optional[str] = None,
    buildings_count: Optional[int] = None,
) -> int:
    """Найти или создать residential_complex по (name, developer_id)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id FROM residential_complexes
               WHERE name = %s AND developer_id IS NOT DISTINCT FROM %s""",
            (name, developer_id),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            """INSERT INTO residential_complexes (name, developer_id, class, type, completion, buildings_count)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (name, developer_id, class_, type_, completion, buildings_count),
        )
        return cur.fetchone()[0]


def upsert_building(
    conn: psycopg.Connection,
    location_id: int,
    residential_complex_id: Optional[int],
    year_building: Optional[int] = None,
    building_status: Optional[str] = None,
    building_material: Optional[str] = None,
    building_type: Optional[str] = None,
    building_section: Optional[str] = None,
    floors_material: Optional[str] = None,
    floors_count: Optional[int] = None,
    floors_range: Optional[str] = None,
    entrances_count: Optional[int] = None,
    apartments_count: Optional[int] = None,
    completion_date: Optional[str] = None,
    parking: Optional[str] = None,
    heating: Optional[str] = None,
    concierge: Optional[bool] = None,
    barrier: Optional[bool] = None,
    emergency: Optional[bool] = None,
    ramp: Optional[bool] = None,
    garbage_chute: Optional[bool] = None,
) -> int:
    """Найти или создать building."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id FROM buildings
               WHERE location_id = %s
                 AND residential_complex_id IS NOT DISTINCT FROM %s
                 AND building_section IS NOT DISTINCT FROM %s
                 AND year_building IS NOT DISTINCT FROM %s""",
            (location_id, residential_complex_id, building_section, year_building),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            """INSERT INTO buildings (
                location_id, residential_complex_id, year_building, building_status,
                building_material, building_type, building_section, floors_material, floors_count,
                floors_range, entrances_count, apartments_count, completion_date, parking, heating,
                concierge, barrier, emergency, ramp, garbage_chute)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (location_id, residential_complex_id, year_building, building_status,
             building_material, building_type, building_section, floors_material, floors_count,
             floors_range, entrances_count, apartments_count, completion_date, parking, heating,
             concierge, barrier, emergency, ramp, garbage_chute),
        )
        return cur.fetchone()[0]


def upsert_seller(
    conn: psycopg.Connection,
    site_id: int,
    name: Optional[str],
    contact_person: Optional[str] = None,
    seller_type: Optional[str] = None,
    agency: Optional[str] = None,
    rating: Optional[float] = None,
    reviews_count: Optional[int] = None,
    registered_year: Optional[int] = None,
    ads_count: Optional[int] = None,
    experience: Optional[str] = None,
    documents_verified: Optional[bool] = None,
) -> int:
    """Найти или создать seller по (site_id, name)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id FROM sellers
               WHERE site_id = %s AND name IS NOT DISTINCT FROM %s""",
            (site_id, name),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute(
            """INSERT INTO sellers (site_id, name, contact_person, seller_type, agency,
               rating, reviews_count, registered_year, ads_count, experience, documents_verified)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (site_id, name, contact_person, seller_type, agency, rating,
             reviews_count, registered_year, ads_count, experience, documents_verified),
        )
        return cur.fetchone()[0]


def get_or_create_tag(
    conn: psycopg.Connection,
    tag_type_code: str,
    name: str,
) -> int:
    """INSERT ... ON CONFLICT (tag_type_id, name) DO NOTHING, затем SELECT id."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM tag_types WHERE code = %s", (tag_type_code,))
        row = cur.fetchone()
        if not row:
            logger.warning("tag_type '%s' not found", tag_type_code)
            return -1
        tag_type_id = row[0]
        cur.execute(
            "INSERT INTO tags (tag_type_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING id",
            (tag_type_id, name),
        )
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("SELECT id FROM tags WHERE tag_type_id = %s AND name = %s", (tag_type_id, name))
        row = cur.fetchone()
        return row[0] if row else -1


def upsert_attribute_definition(
    conn: psycopg.Connection,
    category_code: str,
    code: str,
    name: str,
    value_type: str = "text",
) -> tuple[int, str]:
    """Найти или создать attribute_definition."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, value_type FROM attribute_definitions WHERE code = %s", (code,))
        row = cur.fetchone()
        if row:
            return (row[0], row[1])
        cur.execute("SELECT id FROM attribute_categories WHERE code = %s", (category_code,))
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO attribute_categories (code, name) VALUES ('site_data', 'Данные сайта') RETURNING id",
            )
            cat_id = cur.fetchone()[0]
        else:
            cat_id = row[0]
        cur.execute(
            """INSERT INTO attribute_definitions (category_id, code, name, value_type)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (code) DO NOTHING
               RETURNING id, value_type""",
            (cat_id, code, name, value_type),
        )
        row = cur.fetchone()
        if row:
            return (row[0], row[1])
        cur.execute("SELECT id, value_type FROM attribute_definitions WHERE code = %s", (code,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (-1, value_type)