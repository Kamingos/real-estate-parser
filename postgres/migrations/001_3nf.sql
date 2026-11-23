-- =====================================================================
-- Миграция 001: Приведение схемы к 3НФ
-- Старая EAV (property_attributes / offer_attributes со value_text/number/bool)
-- -> Новая типизированная EAV (6 отдельных таблиц)
-- =====================================================================
-- Идемпотентная: можно запускать повторно (IF EXISTS / IF NOT EXISTS).
-- Все изменения в одной транзакции.
-- =====================================================================

BEGIN;

-- =====================================================
-- 1. Функции
-- =====================================================

CREATE OR REPLACE FUNCTION fn_normalize_address(
    region TEXT, city TEXT, district TEXT,
    micro_district TEXT, street TEXT, house TEXT
) RETURNS TEXT AS $$
DECLARE
    result TEXT;
BEGIN
    result := lower(coalesce(region, '') || ' ' ||
                    coalesce(city, '') || ' ' ||
                    coalesce(district, '') || ' ' ||
                    coalesce(micro_district, '') || ' ' ||
                    coalesce(street, '') || ' ' ||
                    coalesce(house, ''));
    result := regexp_replace(result, '\bул\.\b', 'улица', 'gi');
    result := regexp_replace(result, '\buлица\b', 'улица', 'gi');
    result := regexp_replace(result, '\bd\.\b', 'дом', 'gi');
    result := regexp_replace(result, '\bдом\b', 'дом', 'gi');
    result := regexp_replace(result, '\bпр-т\b', 'проспект', 'gi');
    result := regexp_replace(result, '\bпроспект\b', 'проспект', 'gi');
    result := regexp_replace(result, '[^a-zа-яё0-9 ]+', ' ');
    result := trim(regexp_replace(result, ' {2,}', ' ', 'g'));
    RETURN result;
END;
$$ LANGUAGE IMMUTABLE PARALLEL SAFE;

CREATE OR REPLACE FUNCTION fn_check_attribute_value_type()
RETURNS TRIGGER AS $$
BEGIN
    DECLARE
        expected_type TEXT;
    BEGIN
        SELECT ad.value_type INTO expected_type
        FROM attribute_definitions ad
        WHERE ad.id = NEW.attribute_id;

        IF TG_ARGV[0] = 'text' AND NEW.value_text IS NULL THEN
            RAISE EXCEPTION 'value_text is NULL but attribute % expects text', NEW.attribute_id;
        END IF;
        IF TG_ARGV[0] = 'number' AND NEW.value_number IS NULL THEN
            RAISE EXCEPTION 'value_number is NULL but attribute % expects number', NEW.attribute_id;
        END IF;
        IF TG_ARGV[0] = 'bool' AND NEW.value_bool IS NULL THEN
            RAISE EXCEPTION 'value_bool is NULL but attribute % expects bool', NEW.attribute_id;
        END IF;

        RETURN NEW;
    END;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- 2. Создать 6 типизированных EAV-таблиц
-- =====================================================

CREATE TABLE IF NOT EXISTS property_attributes_text (
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    attribute_id INT NOT NULL REFERENCES attribute_definitions(id),
    value TEXT NOT NULL,
    PRIMARY KEY (property_id, attribute_id)
);
CREATE TRIGGER trg_pat_type_check
    BEFORE INSERT OR UPDATE ON property_attributes_text
    FOR EACH ROW EXECUTE FUNCTION fn_check_attribute_value_type('text');

CREATE TABLE IF NOT EXISTS property_attributes_number (
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    attribute_id INT NOT NULL REFERENCES attribute_definitions(id),
    value NUMERIC NOT NULL,
    PRIMARY KEY (property_id, attribute_id)
);
CREATE TRIGGER trg_pan_type_check
    BEFORE INSERT OR UPDATE ON property_attributes_number
    FOR EACH ROW EXECUTE FUNCTION fn_check_attribute_value_type('number');

CREATE TABLE IF NOT EXISTS property_attributes_bool (
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    attribute_id INT NOT NULL REFERENCES attribute_definitions(id),
    value BOOLEAN NOT NULL,
    PRIMARY KEY (property_id, attribute_id)
);
CREATE TRIGGER trg_pab_type_check
    BEFORE INSERT OR UPDATE ON property_attributes_bool
    FOR EACH ROW EXECUTE FUNCTION fn_check_attribute_value_type('bool');

CREATE TABLE IF NOT EXISTS offer_attributes_text (
    offer_id BIGINT NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    attribute_id INT NOT NULL REFERENCES attribute_definitions(id),
    value TEXT NOT NULL,
    PRIMARY KEY (offer_id, attribute_id)
);
CREATE TRIGGER tgt_oat_type_check
    BEFORE INSERT OR UPDATE ON offer_attributes_text
    FOR EACH ROW EXECUTE FUNCTION fn_check_attribute_value_type('text');

CREATE TABLE IF NOT EXISTS offer_attributes_number (
    offer_id BIGINT NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    attribute_id INT NOT NULL REFERENCES attribute_definitions(id),
    value NUMERIC NOT NULL,
    PRIMARY KEY (offer_id, attribute_id)
);
CREATE TRIGGER tgt_oan_type_check
    BEFORE INSERT OR UPDATE ON offer_attributes_number
    FOR EACH ROW EXECUTE FUNCTION fn_check_attribute_value_type('number');

CREATE TABLE IF NOT EXISTS offer_attributes_bool (
    offer_id BIGINT NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    attribute_id INT NOT NULL REFERENCES attribute_definitions(id),
    value BOOLEAN NOT NULL,
    PRIMARY KEY (offer_id, attribute_id)
);
CREATE TRIGGER tgt_oab_type_check
    BEFORE INSERT OR UPDATE ON offer_attributes_bool
    FOR EACH ROW EXECUTE FUNCTION fn_check_attribute_value_type('bool');

-- =====================================================
-- 3. Перенести данные из старых таблиц в новые
-- =====================================================

INSERT INTO property_attributes_text (property_id, attribute_id, value)
SELECT pa.property_id, pa.attribute_id, pa.value_text
FROM property_attributes pa
JOIN attribute_definitions ad ON ad.id = pa.attribute_id
WHERE pa.value_text IS NOT NULL AND ad.value_type = 'text'
ON CONFLICT DO NOTHING;

INSERT INTO property_attributes_number (property_id, attribute_id, value)
SELECT pa.property_id, pa.attribute_id, pa.value_number
FROM property_attributes pa
JOIN attribute_definitions ad ON ad.id = pa.attribute_id
WHERE pa.value_number IS NOT NULL AND ad.value_type = 'number'
ON CONFLICT DO NOTHING;

INSERT INTO property_attributes_bool (property_id, attribute_id, value)
SELECT pa.property_id, pa.attribute_id, pa.value_bool
FROM property_attributes pa
JOIN attribute_definitions ad ON ad.id = pa.attribute_id
WHERE pa.value_bool IS NOT NULL AND ad.value_type = 'bool'
ON CONFLICT DO NOTHING;

INSERT INTO offer_attributes_text (offer_id, attribute_id, value)
SELECT oa.offer_id, oa.attribute_id, oa.value_text
FROM offer_attributes oa
JOIN attribute_definitions ad ON ad.id = oa.attribute_id
WHERE oa.value_text IS NOT NULL AND ad.value_type = 'text'
ON CONFLICT DO NOTHING;

INSERT INTO offer_attributes_number (offer_id, attribute_id, value)
SELECT oa.offer_id, oa.attribute_id, oa.value_number
FROM offer_attributes oa
JOIN attribute_definitions ad ON ad.id = oa.attribute_id
WHERE oa.value_number IS NOT NULL AND ad.value_type = 'number'
ON CONFLICT DO NOTHING;

INSERT INTO offer_attributes_bool (offer_id, attribute_id, value)
SELECT oa.offer_id, oa.attribute_id, oa.value_bool
FROM offer_attributes oa
JOIN attribute_definitions ad ON ad.id = oa.attribute_id
WHERE oa.value_bool IS NOT NULL AND ad.value_type = 'bool'
ON CONFLICT DO NOTHING;

DROP TABLE IF EXISTS property_attributes;
DROP TABLE IF EXISTS offer_attributes;

-- =====================================================
-- 4. Удалить производственные колонки
-- =====================================================

ALTER TABLE locations DROP COLUMN IF EXISTS address_normalized;
ALTER TABLE properties DROP COLUMN IF EXISTS dedup_key;
ALTER TABLE properties DROP COLUMN IF EXISTS image_url;
ALTER TABLE properties DROP COLUMN IF EXISTS search_vector;
ALTER TABLE offers DROP COLUMN IF EXISTS search_vector;

-- =====================================================
-- 5. offer_images: добавить position, backfill
-- =====================================================

ALTER TABLE offer_images ADD COLUMN IF NOT EXISTS position INT NOT NULL DEFAULT 0;

DO $$
DECLARE
    updated INT;
BEGIN
    UPDATE offer_images oi SET position = subq.pos
    FROM (
        SELECT id, row_number() OVER (PARTITION BY offer_id ORDER BY id) - 1 AS pos
        FROM offer_images
    ) subq
    WHERE oi.id = subq.id;
    GET DIAGNOSTICS updated = ROW_COUNT;
    RAISE NOTICE 'offer_images position backfilled: % rows', updated;
END $$;

-- =====================================================
-- 6. Пересоздать уникальные ограничения, индексы, view
-- =====================================================

ALTER TABLE residential_complexes DROP CONSTRAINT IF EXISTS ux_rc_name_developer;
ALTER TABLE residential_complexes
    ADD CONSTRAINT ux_rc_name_developer UNIQUE NULLS NOT DISTINCT (name, developer_id);

ALTER TABLE sellers DROP CONSTRAINT IF EXISTS ux_sellers_site_name;
ALTER TABLE sellers
    ADD CONSTRAINT ux_sellers_site_name UNIQUE NULLS NOT DISTINCT (site_id, name);

CREATE INDEX IF NOT EXISTS ix_pat_attr_val ON property_attributes_text (attribute_id, left(value, 255));
CREATE INDEX IF NOT EXISTS ix_oat_attr_val ON offer_attributes_text (attribute_id, left(value, 255));
CREATE INDEX IF NOT EXISTS ix_pan_attr_val ON property_attributes_number (attribute_id, value);
CREATE INDEX IF NOT EXISTS ix_oan_attr_val ON offer_attributes_number (attribute_id, value);
CREATE INDEX IF NOT EXISTS ix_pab_attr_val ON property_attributes_bool (attribute_id, value);
CREATE INDEX IF NOT EXISTS ix_oab_attr_val ON offer_attributes_bool (attribute_id, value);

CREATE INDEX IF NOT EXISTS ix_offers_search_fts ON offers USING gin (
    to_tsvector('russian'::regconfig,
        coalesce(name, '') || ' ' || coalesce(description, ''))
);

CREATE INDEX IF NOT EXISTS ix_properties_search_fts ON properties USING gin (
    to_tsvector('russian'::regconfig,
        coalesce(canonical_name, '') || ' ' || coalesce(description, ''))
);

CREATE INDEX IF NOT EXISTS ix_locations_addrnorm_expr ON locations USING gin (
    fn_normalize_address(region, city, district, micro_district, street, house) gin_trgm_ops
);

CREATE INDEX IF NOT EXISTS ix_offer_images_offer ON offer_images (offer_id, position);

DROP VIEW IF EXISTS v_property_search;
CREATE VIEW v_property_search AS
SELECT p.id            AS property_id,
       p.canonical_name,
       (SELECT oi.url
        FROM offer_images oi
        WHERE oi.offer_id IN (
            SELECT o.id FROM offers o WHERE o.property_id = p.id
            ORDER BY oi.position, oi.id LIMIT 1
        )
        LIMIT 1
       ) AS image_url,
       p.object_type_id,
       p.area,
       p.rooms_count,
       p.floor,
       p.location_id,
       to_tsvector('russian'::regconfig,
            coalesce(p.canonical_name, '') || ' ' || coalesce(p.description, ''))
           AS search_vector,
       MIN(o.price)    AS min_price,
       COUNT(o.id)     AS offers_count
FROM properties p
LEFT JOIN offers o ON o.property_id = p.id
GROUP BY p.id;

COMMIT;