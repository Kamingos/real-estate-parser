# Обзор базы данных

Обзор схемы PostgreSQL по файлам [`postgres/init/init_db.sql`](postgres/init/init_db.sql),
[`postgres/db_structure.txt`](postgres/db_structure.txt) и
[`postgres/init/init_api_user_db.sql`](postgres/init/init_api_user_db.sql).

---

## 1. Назначение и общая идея

Интеграционная БД объявлений о недвижимости собирает данные трёх источников
(**Cian**, **Avito**, **Yandex Недвижимость**) в единую модель:

```text
один физический объект (properties)  ←──  много объявлений (offers) с разных сайтов
```

Ключевые принципы:

- частые и «стабильные» поля — типизированные колонки;
- редкие и сайт-специфичные характеристики — типизированный EAV (6 таблиц);
- списки (бейджи, инфраструктура, лифты, хлебные крошки) — теги;
- вместо `CHECK` на значения — таблицы-справочники;
- неизвестное значение — `NULL` (исключение: строковые поля `locations` — `''`);
- даты (`publish_date`, `update_date`, `completion_date`) хранятся **строками**, как их отдают парсеры;
- история цен не ведётся: одна строка `offers` = последнее состояние объявления.

Объём: **24 таблицы**, **1 представление**, **2 функции**, расширение `pg_trgm`.

---

## 2. Слои схемы

### 2.1 Справочники

| Таблица | Содержимое |
| --- | --- |
| `sites` | `cian`, `avito`, `yandex` |
| `object_types` | `flat`, `room`, `studio`, `house`, `land_plot`, `garage`, `other` |
| `housing_types` | `new_building`, `secondary` |
| `deal_types` | `sale`, `rent` |
| `tag_types` | 10 типов: `badge`, `feature_chip`, `infrastructure`, `promotion`, `courtyard`, `elevator`, `breadcrumb`, `rc_building_type`, `rc_parking`, `rc_finishing` |
| `attribute_categories` | `flat`, `engineering`, `land`, `accessibility`, `site_data` |
| `attribute_definitions` | 30 предзаполненных атрибутов с `value_type` (`text` / `number` / `bool`) и `unit` |
| `tags` | значения тегов, `UNIQUE (tag_type_id, name)` |

Все справочники (кроме `attribute_definitions` и `tags`) имеют форму
`id SMALLSERIAL PRIMARY KEY, code VARCHAR(32) UNIQUE NOT NULL, name VARCHAR(128) NOT NULL`.

`attribute_definitions` дополнительно ограничен
`CHECK (value_type IN ('text','number','bool'))` — это единственный «жёсткий» `CHECK` в схеме.

### 2.2 Сущности предметной области

| Таблица | Назначение | Особенности |
| --- | --- | --- |
| `locations` | плоский адрес + координаты | все строковые поля `NOT NULL DEFAULT ''`; `UNIQUE(region, city, district, micro_district, street, house)` |
| `developers` | застройщики | `name UNIQUE` |
| `residential_complexes` | ЖК | `UNIQUE NULLS NOT DISTINCT (name, developer_id)` |
| `buildings` | дом/корпус | `floors_count` (этажность) хранится **только здесь** |
| `sellers` | продавцы/риелторы | `UNIQUE NULLS NOT DISTINCT (site_id, name)` |

### 2.3 Ядро

| Таблица | Роль |
| --- | --- |
| `properties` | уникальный объект после дедупликации |
| `offers` | объявление конкретного сайта |
| `offer_images` | фотографии объявления (`position` задаёт порядок) |
| `offer_tags` | M:N `offers ↔ tags` |
| `offer_legal_info` | юридические сведения, 1:1 к `offers` (в основном Cian) |

`properties` содержит `object_type_id NOT NULL`, опциональные `housing_type_id`, `building_id`,
`location_id`, а также `area`, `living_area`, `kitchen_area`, `rooms_count`, `floor`,
`ceiling_height`, `cadastral_number`, `canonical_name`, `description`.

`offers` содержит `UNIQUE (site_id, external_id)` — это ключ UPSERT. `property_id` **допускает NULL**
(объявление ещё не сопоставлено). Даты — `VARCHAR(64)`, `parsed_at` — `TIMESTAMPTZ NOT NULL DEFAULT now()`.

### 2.4 Типизированный EAV

Шесть таблиц с одинаковой структурой «владелец + атрибут + значение»:

| Таблица | Владелец | Тип значения |
| --- | --- | --- |
| `property_attributes_text` | `property_id` | `TEXT` |
| `property_attributes_number` | `property_id` | `NUMERIC` |
| `property_attributes_bool` | `property_id` | `BOOLEAN` |
| `offer_attributes_text` | `offer_id` | `TEXT` |
| `offer_attributes_number` | `offer_id` | `NUMERIC` |
| `offer_attributes_bool` | `offer_id` | `BOOLEAN` |

Первичный ключ — пара `(owner_id, attribute_id)`, то есть у объекта не может быть двух значений
одного атрибута. На каждой таблице висит триггер `BEFORE INSERT OR UPDATE`, вызывающий
`fn_check_attribute_value_type('text'|'number'|'bool')`.

**Почему так, а не одна таблица с `value_text/value_number/value_bool`:** нет NULL-колонок,
тип гарантируется СУБД, индексы по узким типам работают эффективнее.

---

## 3. Функции и триггеры

### 3.1 `fn_normalize_address()`

[`init_db.sql:87-111`](postgres/init/init_db.sql:87) — `IMMUTABLE PARALLEL SAFE` функция:

1. склеивает компоненты адреса через пробел и приводит к нижнему регистру;
2. унифицирует сокращения: `ул.` → `улица`, `д.` → `дом`, `пр-т/пр-кт` → `проспект`;
3. удаляет пунктуацию;
4. схлопывает пробелы и делает `trim`.

Важная деталь: границы слов заданы явными классами символов (`[^a-zа-яё0-9]`), потому что
`\b` в PostgreSQL — это backspace, а `\y`/`\m` зависят от локали для кириллицы. Это корректное
решение, зафиксированное в [`db_structure.txt`](postgres/db_structure.txt:386).

### 3.2 `fn_check_attribute_value_type()`

[`init_db.sql:269-293`](postgres/init/init_db.sql:269) проверяет три условия:

1. атрибут существует в `attribute_definitions`;
2. `attribute_definitions.value_type` совпадает с типом таблицы (`TG_ARGV[0]`);
3. `NEW.value` не `NULL`.

Это защита от «числовой атрибут записали в текстовую таблицу» и от рассинхронизации загрузчика
со справочником. Загрузчик обязан выбирать EAV-таблицу по `value_type`.

---

## 4. Индексы

| Группа | Индексы |
| --- | --- |
| EAV | `ix_pat/oat_attr_val` по `(attribute_id, left(value,255))`; `ix_pan/oan_attr_val` по `(attribute_id, value)`; `ix_pab/oab_attr_val` |
| `offers` | `UNIQUE(site_id, external_id)`, `(property_id, price)`, `seller_id`, `deal_type_id`, `price`, `parsed_at` |
| Полнотекстовый поиск | GIN `to_tsvector('russian', coalesce(name,'')||' '||coalesce(description,''))` на `offers`; аналогично на `properties` (`canonical_name` + `description`) |
| `properties` | `object_type_id`, `housing_type_id`, `building_id`, `location_id`, `area`, `rooms_count`, `floor`, `cadastral_number`; GIN trgm по `canonical_name` |
| `locations` | `(city, district)`, `(street, house)`, GiST по `point(longitude, latitude)`, GIN trgm по `address`, GIN trgm по выражению `fn_normalize_address(...)` |
| Прочее | `buildings(location_id)`, `buildings(residential_complex_id)`, `offer_images(offer_id, position)`, `offer_tags(tag_id)`, `attribute_definitions(category_id)` |

Важное правило из [`db_structure.txt`](postgres/db_structure.txt:306): для текстового EAV-поиска
условие должно повторять выражение индекса — `WHERE attribute_id = ? AND left(value, 255) = ?`,
иначе индекс не сработает.

---

## 5. Представление `v_property_search`

[`init_db.sql:435-457`](postgres/init/init_db.sql:435) — витрина для веб-приложения:

- `property_id`, `canonical_name`, `object_type_id`, `area`, `rooms_count`, `floor`, `location_id`;
- `image_url` — коррелированный подзапрос: первое фото (`ORDER BY position, id LIMIT 1`)
  **среди всех объявлений объекта**, а не одного произвольного;
- `search_vector` — выражение `to_tsvector('russian', canonical_name || ' ' || description)`;
- `min_price` (`MIN(o.price)`) и `offers_count` (`COUNT(o.id)`) через `LEFT JOIN offers ... GROUP BY p.id`.

Ограничения:

- представление **не индексируется**, поэтому для больших объёмов поиск нужно выполнять по
  `properties`/`offers` с их GIN-индексами, а не по view;
- `GROUP BY p.id` корректен, так как `id` — первичный ключ (функциональная зависимость остальных
  колонок `properties`).

---

## 6. Стартовые данные

[`init_db.sql:463-530`](postgres/init/init_db.sql:463):

| Справочник | Количество |
| --- | --- |
| `sites` | 3 |
| `object_types` | 7 |
| `housing_types` | 2 |
| `deal_types` | 2 |
| `tag_types` | 10 |
| `attribute_categories` | 5 |
| `attribute_definitions` | 30 |

Атрибуты распределены по категориям: `flat` (8), `engineering` (8), `land` (10),
`accessibility` (2), `site_data` (2).

---

## 7. Поток загрузки и дедупликации

### 7.1 Загрузка одного объявления

Порядок шагов (реализован в [`parsers/db/loader.py`](parsers/db/loader.py)):

1. `sites` — по `code`;
2. `locations` — UPSERT по шести компонентам адреса;
3. `developers` → `residential_complexes` → `buildings`;
4. `sellers` — по `(site_id, name)` c `IS NOT DISTINCT FROM`;
5. `properties` — создаётся **предварительная** запись под объявление;
6. `offers` — UPSERT по `(site_id, external_id)`, `property_id` = предварительный объект;
7. `offer_images` — `DELETE` по `offer_id`, затем `INSERT` с `position`;
8. `offer_tags` — `DELETE` по `offer_id`, затем `INSERT`;
9. `offer_legal_info` — только если есть хотя бы одно значение;
10. `property_attributes_*` — `DELETE` по `property_id`, затем `INSERT`;
11. `offer_attributes_*` — `DELETE` по `offer_id`, затем `INSERT`; сырые `parameters`
    маппятся на известные коды или создают новый атрибут в категории `site_data`.

Повторный парсинг: `offers` обновляется по `UNIQUE(site_id, external_id)`, `parsed_at = now()`.

### 7.2 Дедупликация (задумано)

`dedup_key` в схеме отсутствует намеренно и вычисляется на лету:

```text
md5(address_normalized | object_type_id | floor | rooms_count | round(area))
```

Критерии по убыванию надёжности:

| Метод | Условие | `match_confidence` |
| --- | --- | --- |
| `cadastral` | одинаковый непустой `cadastral_number` | 1.000 |
| `exact_key` | одинаковый `dedup_key` и `|area1 − area2| ≤ 0.5 м²` | 0.95 |
| `fuzzy_address` | `similarity(address_normalized) ≥ 0.85`, совпадают тип/этаж/комнаты, `|Δarea| ≤ 0.5` | значение similarity |

Для `land_plot` и `garage` этаж и комнаты не используются. «Выжившая» `property` выбирается
по числу заполненных полей; у остальных перепривязываются `offers.property_id`, переносятся
недостающие значения и атрибуты, опустевшие `properties` удаляются.

**Фактически скрипт дедупликации в репозитории отсутствует** — см. раздел 9.

---

## 8. Права доступа

[`init_api_user_db.sql`](postgres/init/init_api_user_db.sql) создаёт роль `API` (`LOGIN`, без
`SUPERUSER`/`CREATEROLE`) и выдаёт:

- `USAGE` на схему `public`;
- `SELECT, INSERT, UPDATE, DELETE` на все таблицы;
- `USAGE, SELECT` на все последовательности;
- `ALTER DEFAULT PRIVILEGES` на будущие таблицы/последовательности.

Для backend этого достаточно. Замечание: роль имеет `CREATEDB`, что для прикладного API избыточно.

---

## 9. Замечания и риски

| Приоритет | Замечание | Влияние |
| --- | --- | --- |
| P0 | Скрипта дедупликации нет; `match_method` / `match_confidence` никем не заполняются | `properties` фактически равны `offers`, объединения объектов нет |
| P0 | `property_attributes_*` перезаписываются (`DELETE` по `property_id`) при загрузке **каждого** объявления | после объединения объектов загрузка второго объявления удалит атрибуты первого |
| P1 | `locations`: все поля `NOT NULL DEFAULT ''`, поэтому объявления без адреса схлопываются в одну строку `('', '', '', '', '', '')` | общая «пустая» локация, к которой прилипают координаты первого объявления (`COALESCE` не перезаписывает) |
| P1 | [`db_structure.txt`](postgres/db_structure.txt:4) ссылается на `migrations/001_3nf.sql`, `002`, `003_fixes.sql`, которых в репозитории нет | невозможно применить исправления к уже созданной БД |
| P1 | `publish_date`, `update_date`, `completion_date` — строки | нельзя корректно сортировать/фильтровать по дате в SQL |
| P2 | `v_property_search` не индексируется и содержит `GROUP BY` по всем объявлениям | деградация на больших объёмах |
| P2 | Нет `UNIQUE` на `offers.url` | возможны дубли URL с разными `external_id` |
| P2 | `tags.name` сравнивается побайтово | «Балкон» и «балкон» станут разными тегами |
| P2 | Нет `CHECK` на `price >= 0`, `area > 0` | мусорные значения пройдут (осознанный компромисс) |
| P2 | `buildings` дедуплицируется в загрузчике по `(location_id, residential_complex_id, building_section, year_building)` | возможны ложные склейки/дубли при неполных данных |

---

## 10. Рекомендации

1. **Реализовать скрипт дедупликации** отдельным модулем (`parsers/dedup/`) с отчётом качества:
   доля пар ниже порога, ручная выборка пар, число объединений по каждому методу.
2. **Изменить стратегию записи `property_attributes_*`**: не удалять всё, а обновлять
   `ON CONFLICT (property_id, attribute_id) DO UPDATE`; удаление выполнять только при
   пересоздании объекта.
3. **Ввести отдельную «неизвестную» локацию** (`id` для пустого адреса) либо не создавать
   `locations` при полностью пустом адресе (`location_id = NULL`).
4. **Вернуть миграции** в репозиторий (`postgres/migrations/`) и описать порядок применения,
   иначе `db_structure.txt` вводит в заблуждение.
5. Для сортировки по датам добавить хотя бы `offers.parsed_at` (уже есть) и, при необходимости,
   вычисляемые `DATE`-колонки/индексы по выражениям.
6. Для веб-поиска использовать прямые запросы к `properties`/`offers` с GIN-индексами,
   а `v_property_search` оставить как удобную витрину для карточки/списка с ограничением `LIMIT`.
