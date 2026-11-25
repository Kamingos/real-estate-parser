-- =====================================================================
-- Интеграционная БД: объявления о недвижимости (Cian / Avito / Yandex)
-- PostgreSQL 15+ (3НФ, типизированный EAV, UNIQUE NULLS NOT DISTINCT)
-- =====================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- =====================================================
-- 1. СПРАВОЧНИКИ
-- =====================================================

CREATE TABLE sites (
    id    SMALLSERIAL PRIMARY KEY,
    code  VARCHAR(32)  NOT NULL UNIQUE,
    name  VARCHAR(128) NOT NULL
);

CREATE TABLE object_types (
    id    SMALLSERIAL PRIMARY KEY,
    code  VARCHAR(32)  NOT NULL UNIQUE,
    name  VARCHAR(128) NOT NULL
);

CREATE TABLE housing_types (
    id    SMALLSERIAL PRIMARY KEY,
    code  VARCHAR(32)  NOT NULL UNIQUE,
    name  VARCHAR(128) NOT NULL
);

CREATE TABLE deal_types (
    id    SMALLSERIAL PRIMARY KEY,
    code  VARCHAR(32)  NOT NULL UNIQUE,
    name  VARCHAR(128) NOT NULL
);

CREATE TABLE tag_types (
    id    SMALLSERIAL PRIMARY KEY,
    code  VARCHAR(32)  NOT NULL UNIQUE,
    name  VARCHAR(128) NOT NULL
);

CREATE TABLE attribute_categories (
    id    SMALLSERIAL PRIMARY KEY,
    code  VARCHAR(32)  NOT NULL UNIQUE,
    name  VARCHAR(128) NOT NULL
);

CREATE TABLE attribute_definitions (
    id           SERIAL PRIMARY KEY,
    category_id  SMALLINT     REFERENCES attribute_categories(id),
    code         VARCHAR(64)  NOT NULL UNIQUE,
    name         VARCHAR(255) NOT NULL,
    value_type   VARCHAR(16)  NOT NULL DEFAULT 'text',  -- text / number / bool
    unit         VARCHAR(32)
);

CREATE TABLE tags (
    id           SERIAL PRIMARY KEY,
    tag_type_id  SMALLINT     NOT NULL REFERENCES tag_types(id),
    name         VARCHAR(512) NOT NULL,
    UNIQUE (tag_type_id, name)
);

-- =====================================================
-- 2. СУЩНОСТИ ПРЕДМЕТНОЙ ОБЛАСТИ
-- =====================================================

CREATE TABLE locations (
    id                  BIGSERIAL PRIMARY KEY,
    region              VARCHAR(255) NOT NULL DEFAULT '',
    city                VARCHAR(255) NOT NULL DEFAULT '',
    district            VARCHAR(255) NOT NULL DEFAULT '',
    micro_district      VARCHAR(255) NOT NULL DEFAULT '',
    street              VARCHAR(255) NOT NULL DEFAULT '',
    house               VARCHAR(64)  NOT NULL DEFAULT '',
    address             TEXT         NOT NULL DEFAULT '',
    latitude            DOUBLE PRECISION,
    longitude           DOUBLE PRECISION,
    UNIQUE (region, city, district, micro_district, street, house)
);

-- Функция нормализации адреса: нижний регистр, унификация сокращений,
-- удаление пунктуации, схлопывание пробелов.
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
    -- Унификация сокращений
    result := regexp_replace(result, '\bул\.\b', 'улица', 'gi');
    result := regexp_replace(result, '\buлица\b', 'улица', 'gi');
    result := regexp_replace(result, '\bd\.\b', 'дом', 'gi');
    result := regexp_replace(result, '\bдом\b', 'дом', 'gi');
    result := regexp_replace(result, '\bпр-т\b', 'проспект', 'gi');
    result := regexp_replace(result, '\bпроспект\b', 'проспект', 'gi');
    -- Удаление пунктуации
    result := regexp_replace(result, '[^a-zа-яё0-9 ]+', ' ');
    -- Схлопывание пробелов и trim
    result := trim(regexp_replace(result, ' {2,}', ' ', 'g'));
    RETURN result;
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE; -- <-- ИСПРАВЛЕНО ЗДЕСЬ

CREATE TABLE developers (
    id                              SERIAL PRIMARY KEY,
    name                            VARCHAR(255) NOT NULL UNIQUE,
    foundation_year                 INT,
    rating                          NUMERIC(3,2),
    reviews_count                   INT,
    completed_buildings             INT,
    buildings_under_construction    INT,
    residential_complexes_count     INT,
    description                     TEXT
);

CREATE TABLE residential_complexes (
    id               SERIAL PRIMARY KEY,
    developer_id     INT REFERENCES developers(id),
    name             VARCHAR(255) NOT NULL,
    class            VARCHAR(64),
    type             VARCHAR(64),
    completion       VARCHAR(128),
    buildings_count  INT
);

-- PostgreSQL 15+: UNIQUE NULLS NOT DISTINCT
DROP INDEX IF EXISTS ux_rc_name_developer;
ALTER TABLE residential_complexes
    ADD CONSTRAINT ux_rc_name_developer UNIQUE NULLS NOT DISTINCT (name, developer_id);

CREATE TABLE buildings (
    id                      BIGSERIAL PRIMARY KEY,
    location_id             BIGINT REFERENCES locations(id),
    residential_complex_id  INT    REFERENCES residential_complexes(id),
    year_building           INT,
    building_status         VARCHAR(128),
    building_material       VARCHAR(128),
    building_type           VARCHAR(255),
    building_section        VARCHAR(128),
    floors_material         VARCHAR(128),
    floors_count            INT,
    floors_range            VARCHAR(64),
    entrances_count         INT,
    apartments_count        INT,
    completion_date         VARCHAR(128),
    parking                 VARCHAR(255),
    heating                 VARCHAR(255),
    concierge               BOOLEAN,
    barrier                 BOOLEAN,
    emergency               BOOLEAN,
    ramp                    BOOLEAN,
    garbage_chute           BOOLEAN
);

CREATE TABLE sellers (
    id                  BIGSERIAL PRIMARY KEY,
    site_id             SMALLINT NOT NULL REFERENCES sites(id),
    name                VARCHAR(255),   -- seller_name (Avito/Yandex) или rieltor (Cian)
    contact_person      VARCHAR(255),
    seller_type         VARCHAR(64),
    agency              VARCHAR(255),
    rating              NUMERIC(3,2),
    reviews_count       INT,
    registered_year     INT,
    ads_count           INT,
    experience          VARCHAR(255),
    documents_verified  BOOLEAN
);

-- UNIQUE NULLS NOT DISTINCT для sellers
ALTER TABLE sellers
    ADD CONSTRAINT ux_sellers_site_name UNIQUE NULLS NOT DISTINCT (site_id, name);

-- =====================================================
-- 3. ЯДРО: properties / offers / attributes
-- =====================================================

CREATE TABLE properties (
    id               BIGSERIAL PRIMARY KEY,
    canonical_name   VARCHAR(512),       -- формирует скрипт дедупликации
    description      TEXT,
    object_type_id   SMALLINT NOT NULL REFERENCES object_types(id),
    housing_type_id  SMALLINT REFERENCES housing_types(id),
    building_id      BIGINT   REFERENCES buildings(id),
    location_id      BIGINT   REFERENCES locations(id),
    area             NUMERIC(10,2),
    living_area      NUMERIC(10,2),
    kitchen_area     NUMERIC(10,2),
    rooms_count      INT,
    floor            INT,
    ceiling_height   NUMERIC(5,2),
    cadastral_number VARCHAR(64)
    -- dedup_key удалён: ключ вычисляется на лету скриптом дедупликации
    -- search_vector удалён: GIN-индекс по выражению см. ниже
);

CREATE TABLE offers (
    id                 BIGSERIAL PRIMARY KEY,
    property_id        BIGINT REFERENCES properties(id),   -- NULL допустим (объявление не сопоставлено)
    site_id            SMALLINT NOT NULL REFERENCES sites(id),
    seller_id          BIGINT   REFERENCES sellers(id),
    deal_type_id       SMALLINT REFERENCES deal_types(id),
    external_id        VARCHAR(128) NOT NULL,
    url                TEXT NOT NULL,
    name               VARCHAR(512),
    subtitles          TEXT,
    description        TEXT,
    offer_article      VARCHAR(128),
    category           VARCHAR(64),
    price              BIGINT,
    price_per_meter    BIGINT,
    price_unit         VARCHAR(16) DEFAULT 'м²',
    currency           VARCHAR(8)  NOT NULL DEFAULT 'RUB',
    deal_conditions    TEXT,
    mortgage_possible  BOOLEAN,
    sale_method        VARCHAR(128),
    participation_type VARCHAR(128),
    publish_date       VARCHAR(64),
    update_date        VARCHAR(64),
    views_count        INT,
    views_today        INT,
    photos_count       INT,
    is_verified        BOOLEAN,
    parsed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    match_method       VARCHAR(32),        -- cadastral / exact_key / fuzzy_address (метод дедупликации)
    match_confidence   NUMERIC(4,3),       -- 0.000 .. 1.000 (для оценки ложных срабатываний)
    -- search_vector удалён: GIN-индекс по выражению см. ниже
    UNIQUE (site_id, external_id)
);

CREATE TABLE offer_images (
    id        BIGSERIAL PRIMARY KEY,
    offer_id  BIGINT NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    url       TEXT   NOT NULL,
    position INT NOT NULL DEFAULT 0
);

CREATE TABLE offer_tags (
    offer_id  BIGINT NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    tag_id    INT    NOT NULL REFERENCES tags(id),
    PRIMARY KEY (offer_id, tag_id)
);

CREATE TABLE offer_legal_info (
    offer_id                BIGINT PRIMARY KEY REFERENCES offers(id) ON DELETE CASCADE,
    rosreestr_verified      BOOLEAN,
    ownership_type          VARCHAR(128),
    owners_count            INT,
    encumbrances            TEXT,
    minors_owners           BOOLEAN,
    maternity_capital_used  BOOLEAN
);

-- =====================================================
-- 4. ТИПИЗИРОВАННЫЙ EAV (замена property_attributes / offer_attributes)
-- =====================================================

-- Триггерная функция для проверки соответствия типа значения
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

-- property_attributes_text
CREATE TABLE property_attributes_text (
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    attribute_id INT NOT NULL REFERENCES attribute_definitions(id),
    value TEXT NOT NULL,
    PRIMARY KEY (property_id, attribute_id)
);
CREATE TRIGGER trg_pat_type_check
    BEFORE INSERT OR UPDATE ON property_attributes_text
    FOR EACH ROW EXECUTE FUNCTION fn_check_attribute_value_type('text');

-- property_attributes_number
CREATE TABLE property_attributes_number (
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    attribute_id INT NOT NULL REFERENCES attribute_definitions(id),
    value NUMERIC NOT NULL,
    PRIMARY KEY (property_id, attribute_id)
);
CREATE TRIGGER trg_pan_type_check
    BEFORE INSERT OR UPDATE ON property_attributes_number
    FOR EACH ROW EXECUTE FUNCTION fn_check_attribute_value_type('number');

-- property_attributes_bool
CREATE TABLE property_attributes_bool (
    property_id BIGINT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    attribute_id INT NOT NULL REFERENCES attribute_definitions(id),
    value BOOLEAN NOT NULL,
    PRIMARY KEY (property_id, attribute_id)
);
CREATE TRIGGER trg_pab_type_check
    BEFORE INSERT OR UPDATE ON property_attributes_bool
    FOR EACH ROW EXECUTE FUNCTION fn_check_attribute_value_type('bool');

-- offer_attributes_text
CREATE TABLE offer_attributes_text (
    offer_id BIGINT NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    attribute_id INT NOT NULL REFERENCES attribute_definitions(id),
    value TEXT NOT NULL,
    PRIMARY KEY (offer_id, attribute_id)
);
CREATE TRIGGER tgt_oat_type_check
    BEFORE INSERT OR UPDATE ON offer_attributes_text
    FOR EACH ROW EXECUTE FUNCTION fn_check_attribute_value_type('text');

-- offer_attributes_number
CREATE TABLE offer_attributes_number (
    offer_id BIGINT NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    attribute_id INT NOT NULL REFERENCES attribute_definitions(id),
    value NUMERIC NOT NULL,
    PRIMARY KEY (offer_id, attribute_id)
);
CREATE TRIGGER tgt_oan_type_check
    BEFORE INSERT OR UPDATE ON offer_attributes_number
    FOR EACH ROW EXECUTE FUNCTION fn_check_attribute_value_type('number');

-- offer_attributes_bool
CREATE TABLE offer_attributes_bool (
    offer_id BIGINT NOT NULL REFERENCES offers(id) ON DELETE CASCADE,
    attribute_id INT NOT NULL REFERENCES attribute_definitions(id),
    value BOOLEAN NOT NULL,
    PRIMARY KEY (offer_id, attribute_id)
);
CREATE TRIGGER tgt_oab_type_check
    BEFORE INSERT OR UPDATE ON offer_attributes_bool
    FOR EACH ROW EXECUTE FUNCTION fn_check_attribute_value_type('bool');

-- =====================================================
-- 5. ИНДЕКСЫ
-- =====================================================

-- EAV текстовые: поиск по атрибуту + префикс значения
CREATE INDEX ix_pat_attr_val ON property_attributes_text (attribute_id, left(value, 255));
CREATE INDEX ix_oat_attr_val ON offer_attributes_text (attribute_id, left(value, 255));

-- EAV числовые: поиск по атрибуту
CREATE INDEX ix_pan_attr_val ON property_attributes_number (attribute_id, value);
CREATE INDEX ix_oan_attr_val ON offer_attributes_number (attribute_id, value);

-- EAV булевы: поиск по атрибуту
CREATE INDEX ix_pab_attr_val ON property_attributes_bool (attribute_id, value);
CREATE INDEX ix_oab_attr_val ON offer_attributes_bool (attribute_id, value);

-- offers
CREATE INDEX ix_offers_property_price ON offers (property_id, price);
CREATE INDEX ix_offers_seller         ON offers (seller_id);
CREATE INDEX ix_offers_deal_type      ON offers (deal_type_id);
CREATE INDEX ix_offers_price          ON offers (price);
CREATE INDEX ix_offers_parsed_at      ON offers (parsed_at);

-- GIN-индекс по выражению для offers (to_tsvector)
CREATE INDEX ix_offers_search_fts ON offers USING gin (
    to_tsvector('russian'::regconfig,
        coalesce(name, '') || ' ' || coalesce(description, ''))
);

-- properties
CREATE INDEX ix_properties_object_type ON properties (object_type_id);
CREATE INDEX ix_properties_housing     ON properties (housing_type_id);
CREATE INDEX ix_properties_building    ON properties (building_id);
CREATE INDEX ix_properties_location    ON properties (location_id);
CREATE INDEX ix_properties_area        ON properties (area);
CREATE INDEX ix_properties_rooms       ON properties (rooms_count);
CREATE INDEX ix_properties_floor       ON properties (floor);
CREATE INDEX ix_properties_cadastral   ON properties (cadastral_number);
CREATE INDEX ix_properties_name_trgm   ON properties USING gin (canonical_name gin_trgm_ops);

-- GIN-индекс по выражению для properties (to_tsvector)
CREATE INDEX ix_properties_search_fts ON properties USING gin (
    to_tsvector('russian'::regconfig,
        coalesce(canonical_name, '') || ' ' || coalesce(description, ''))
);

-- locations: GIN trigram по выражению fn_normalize_address
CREATE INDEX ix_locations_addrnorm_expr ON locations USING gin (
    fn_normalize_address(region, city, district, micro_district, street, house) gin_trgm_ops
);
-- Индексы по обычным полям
CREATE INDEX ix_locations_city_district ON locations (city, district);
CREATE INDEX ix_locations_street_house  ON locations (street, house);
CREATE INDEX ix_locations_geo           ON locations USING gist (point(longitude, latitude));
CREATE INDEX ix_locations_address_trgm  ON locations USING gin (address gin_trgm_ops);

-- buildings / ЖК / продавцы
CREATE INDEX ix_buildings_location ON buildings (location_id);
CREATE INDEX ix_buildings_rc       ON buildings (residential_complex_id);
CREATE INDEX ix_sellers_site_name  ON sellers (site_id);

-- offer_images
CREATE INDEX ix_offer_images_offer ON offer_images (offer_id, position);
CREATE INDEX ix_offer_images_pos   ON offer_images (offer_id, position);

-- вспомогательные
CREATE INDEX ix_offer_tags_tag     ON offer_tags (tag_id);
CREATE INDEX ix_attr_def_category  ON attribute_definitions (category_id);

-- =====================================================
-- 6. ПРЕДСТАВЛЕНИЕ ДЛЯ ПОИСКА В ВЕБ-ПРИЛОЖЕНИИ
-- =====================================================
-- v_property_search: image_url берётся подзапросом по offer_images
-- (ORDER BY position, id LIMIT 1), search_vector — выражение to_tsvector.
-- ПРИМЕЧАНИЕ: view не индексируется. Поиск по тексту идёт по индексам
-- ix_properties_search_fts и ix_offers_search_fts.
CREATE OR REPLACE VIEW v_property_search AS
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

-- =====================================================
-- 7. СТАРТОВЫЕ ДАННЫЕ СПРАВОЧНИКОВ
-- =====================================================

INSERT INTO sites (code, name) VALUES
 ('cian','ЦИАН'), ('avito','Авито'), ('yandex','Яндекс Недвижимость');

INSERT INTO object_types (code, name) VALUES
 ('flat','Квартира'), ('room','Комната'), ('studio','Студия'),
 ('house','Дом'), ('land_plot','Земельный участок'),
 ('garage','Гараж'), ('other','Другое');

INSERT INTO housing_types (code, name) VALUES
 ('new_building','Новостройка'), ('secondary','Вторичка');

INSERT INTO deal_types (code, name) VALUES
 ('sale','Продажа'), ('rent','Аренда');

INSERT INTO tag_types (code, name) VALUES
 ('badge','Бейджи объявления'),
 ('feature_chip','Характеристики-чипы'),
 ('infrastructure','Инфраструктура рядом'),
 ('promotion','Акции ЖК'),
 ('courtyard','Двор'),
 ('elevator','Лифты'),
 ('breadcrumb','Хлебные крошки'),
 ('rc_building_type','Типы корпусов ЖК'),
 ('rc_parking','Парковка ЖК'),
 ('rc_finishing','Отделка ЖК');

INSERT INTO attribute_categories (code, name) VALUES
 ('flat','Квартира / помещение'),
 ('engineering','Инженерия и коммуникации'),
 ('land','Участок, гараж, коммерция'),
 ('accessibility','Доступная среда'),
 ('site_data','Данные сайта');

INSERT INTO attribute_definitions (category_id, code, name, value_type, unit)
SELECT c.id, v.code, v.name, v.value_type, v.unit
FROM (VALUES
 ('flat','bathroom','Санузел','text',NULL),
 ('flat','balcony','Балкон','text',NULL),
 ('flat','window_view','Вид из окон','text',NULL),
 ('flat','repairs','Ремонт','text',NULL),
 ('flat','finishing','Отделка','text',NULL),
 ('flat','sell_with_furniture','Продаётся с мебелью','bool',NULL),
 ('flat','furniture','Мебель','text',NULL),
 ('flat','rooms_in_flat','Комнат в квартире','number',NULL),
 ('engineering','water_supply','Водоснабжение','text',NULL),
 ('engineering','sewerage','Канализация','text',NULL),
 ('engineering','gas','Газ','text',NULL),
 ('engineering','electricity','Электричество','text',NULL),
 ('engineering','internet_tv','Интернет и ТВ','text',NULL),
 ('engineering','internet','Интернет','bool',NULL),
 ('engineering','telephone','Телефон','bool',NULL),
 ('engineering','sauna','Сауна','bool',NULL),
 ('land','land_category','Категория земель','text',NULL),
 ('land','land_type','Тип участка','text',NULL),
 ('land','land_area','Площадь участка','number',NULL),
 ('land','land_area_unit','Единица площади участка','text',NULL),
 ('land','garage_type','Тип гаража','text',NULL),
 ('land','security','Охрана','text',NULL),
 ('land','recreation','Для отдыха','text',NULL),
 ('land','terrace','Терраса или веранда','text',NULL),
 ('land','commercial_purpose','Назначение помещения','text',NULL),
 ('land','entrance_type','Тип входа','text',NULL),
 ('accessibility','entrance_door_width','Ширина входной двери','text',NULL),
 ('accessibility','interior_doors_width','Ширина межкомнатных дверей','text',NULL),
 ('site_data','area_unit','Единица площади','text',NULL),
 ('site_data','rooms_count_raw','Количество комнат (как на сайте)','text',NULL)
) AS v(cat, code, name, value_type, unit)
JOIN attribute_categories c ON c.code = v.cat;

COMMIT;
