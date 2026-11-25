# Обзор кода парсеров (`parsers/`)

Обзор пакета [`parsers/`](parsers) по файлам [`main.py`](parsers/main.py),
[`interfaces/parser_interfaces.py`](parsers/interfaces/parser_interfaces.py),
[`model/parser_config.py`](parsers/model/parser_config.py),
[`model/site_parse_data_model.py`](parsers/model/site_parse_data_model.py),
[`realizations/`](parsers/realizations), [`db/`](parsers/db), [`db_migrator.py`](parsers/db_migrator.py),
[`tests/`](parsers/tests), [`tools/`](parsers/tools).

---

## 1. Структура пакета

| Файл | Строк | Роль |
| --- | --- | --- |
| [`main.py`](parsers/main.py) | ~228 | CLI: выбор источника, переопределение параметров, сохранение JSON |
| [`interfaces/parser_interfaces.py`](parsers/interfaces/parser_interfaces.py) | 13 | Абстрактный контракт `IParcer` |
| [`model/parser_config.py`](parsers/model/parser_config.py) | 40 | `ParserConfig` — общая конфигурация |
| [`model/site_parse_data_model.py`](parsers/model/site_parse_data_model.py) | 363 | Три dataclass-модели результатов |
| [`realizations/avito_parser.py`](parsers/realizations/avito_parser.py) | ~1907 | Парсер Avito |
| [`realizations/cian_parser.py`](parsers/realizations/cian_parser.py) | ~1443 | Парсер Cian |
| [`realizations/yandex_parser.py`](parsers/realizations/yandex_parser.py) | ~4227 | Парсер Яндекс Недвижимости |
| [`realizations/parser_factory.py`](parsers/realizations/parser_factory.py) | 53 | Реестр и `create_parser()` |
| [`db/config.py`](parsers/db/config.py) | ~102 | Поиск `.env`, сборка DSN |
| [`db/normalize.py`](parsers/db/normalize.py) | ~368 | Нормализация полей JSON → БД |
| [`db/repositories.py`](parsers/db/repositories.py) | ~383 | Справочники и UPSERT-операции, кэш |
| [`db/loader.py`](parsers/db/loader.py) | ~508 | Загрузка одного объявления в БД |
| [`db_migrator.py`](parsers/db_migrator.py) | ~212 | CLI-загрузчик JSON-файлов в PostgreSQL |
| [`tests/`](parsers/tests) | ~1121 | Юнит/интеграционные/регрессионные тесты |
| [`tools/`](parsers/tools) | ~700 | Диагностика Yandex и нормализация готового JSON |

---

## 2. Архитектура

```mermaid
flowchart TD
    CLI[main.py] --> F[parser_factory.create_parser]
    F --> A[AvitoParser]
    F --> C[CianParser]
    F --> Y[YandexParser]
    A --> M1[AvitoSiteParseData]
    C --> M2[CianSiteParseData]
    Y --> M3[YandexSiteParseData]
    M1 --> J[JSON *_result.json]
    M2 --> J
    M3 --> J
    J --> DM[db_migrator.py]
    DM --> L[db.loader.load_offer]
    L --> DB[(PostgreSQL)]
```

### 2.1 Контракт

```python
class IParcer(ABC):
    @abstractmethod
    def parse(self, parserConfig: ParserConfig) -> tuple[bool, list[Any] | None]: ...
```

Задуманный контракт: `(True, [элементы])` при успехе (возможен пустой список),
`(False, None)` — если источник недоступен и данные не собраны.

### 2.2 Конфигурация

[`ParserConfig`](parsers/model/parser_config.py:4) содержит:

- `max_page_iteration` — число страниц выдачи;
- `min_iteration_time_span` / `max_iteration_time_span` — паузы между запросами;
- `cities` — для Cian `город → city_id`, для Yandex `slug → rgid`;
- `max_retries`, `page_wait_time`, `headless` — сетевые параметры (со значениями по умолчанию);
- `min_cost`, `max_cost`, `area_min/max`, `rooms_count_min/max`, `floor_min/max` —
  **объявлены, но ни одним парсером не используются** (в коде помечены «не реализовано»).

### 2.3 Фабрика

[`parser_factory.py`](parsers/realizations/parser_factory.py) хранит `PARSER_REGISTRY`
(`avito`, `cian`, `yandex`) и алиасы (`авито`, `циан`, `яндекс`, домены). `create_parser(site)`
нормализует имя и возвращает экземпляр. Добавление источника — одна запись в реестре.

### 2.4 Точка запуска

[`main.py`](parsers/main.py) задаёт три конфигурации (`avitoCofig`, `cianConfig`, `yandexConfig`)
и CLI:

```bash
python main.py                      # avito по умолчанию
python main.py --site yandex
python main.py --site all
python main.py --site yandex --pages 2 --min-delay 3 --max-delay 6 \
    --output-dir out --headless
```

Результат сохраняется в `<site>_result.json` через `asdict()`.

---

## 3. Модели данных

Три dataclass-модели в [`site_parse_data_model.py`](parsers/model/site_parse_data_model.py):

| Модель | Особенности |
| --- | --- |
| `CianSiteParseData` | ~80 полей; `rooms_count: int \| None`, `floor: int`; юридический блок (`rosreestr_verified`, `ownership_type`, `owners_count`, …) |
| `AvitoSiteParseData` | ~80 полей; **`rooms_count: str`** (значения «2», «студия», «свободная планировка»); `courtyard`, `contact_person`, координаты |
| `YandexSiteParseData` | ~85 полей; `category`, `offer_article`, `rooms_in_flat`, `area_unit`, `floors_range`, `apartments_count`, `garbage_chute`, `internet/telephone/sauna` |

Общее для всех: `site`, `url`, `external_id`, `name`, `description`, `price`, `object_type`,
`geo_label` (TypedDict из шести строк), `imgs`, `parameters` (сырой словарь характеристик).

Несогласованность типов (`rooms_count` — `str` у Avito и `int | None` у остальных,
`ceiling_height` в см у Yandex) компенсируется слоем нормализации БД, но затрудняет
межсайтовую обработку в самих парсерах.

---

## 4. Общий конвейер парсеров

Все три парсера работают по одной схеме:

1. **Сбор ссылок.** Постраничный обход выдачи (Selenium + Chrome), дедупликация URL в `seen_urls`.
2. **Разбор карточки.** Открытие страницы объявления, извлечение полей, запись в dataclass.
3. **Пауза.** `sleep(uniform(min_delay, max_delay))` между запросами.
4. **Возврат.** Список моделей, сохранение в JSON вызывающей стороной.

Общие механизмы:

| Механизм | Реализация |
| --- | --- |
| Stealth | `excludeSwitches: enable-automation`, `useAutomationExtension: False`, `--disable-blink-features=AutomationControlled`, подмена `navigator.webdriver` через CDP |
| Стратегия загрузки | `page_load_strategy = "eager"`, `set_page_load_timeout` |
| Задержки | из `ParserConfig`, при нулях — безопасные значения по умолчанию |
| Ошибки | `TimeoutException` / `WebDriverException` логируются, объявление пропускается |
| Логирование | `logging.getLogger("<site>_parser")` |
| Капча | детектирование по тексту/URL, ожидание решения пользователем |

---

## 5. Avito

[`avito_parser.py`](parsers/realizations/avito_parser.py)

**Источники данных:** только HTML-разметка с `data-marker` (встраиваемого JSON на странице нет),
координаты — из `data-map-lat` / `data-map-lon`, адрес — обратное геокодирование через **DaData**.

**Категории** (`self.refs`): `flat/studio`, `room`, `house`, `land_plot`, `garage`, `other` —
жёстко заданные URL выдачи Владивостока с параметром `p={page}`.

**Особенности:**

- `parse()` собирает карточки списка, затем открывает каждую страницу;
- если страница объявления не распарсилась, объявление **всё равно попадает в результат**
  с данными карточки ([`avito_parser.py:355-362`](parsers/realizations/avito_parser.py:355));
- `_warn_unfilled_fields()` сверяет поля модели с подписями `item-params` и предупреждает
  о незаполненных;
- `_detect_object_type()`, `_parse_rooms_from_title()`, `_parse_property_from_title()` —
  резервные эвристики из заголовка;
- DaData инициализируется опционально из `dadadata_token.txt`; при отсутствии токена адрес
  просто остаётся пустым.

**Качество по сохранённому JSON** (из [`авито парсер статистика.txt`](parsers/авито%20парсер%20статистика.txt)):
100% — `site`, `url`, `name`, `price`, `object_type`, `floor`, `area`, `price_per_meter`,
`currency`, `deal_type`, координаты, `views_count`; 45.8% — `rooms_count`; 36.1% — `subtitles`;
18.1% — `residential_complex`; **0% — `balcony`**; 8.7% — `sale_method`.

---

## 6. Cian

[`cian_parser.py`](parsers/realizations/cian_parser.py)

**Источники данных (по приоритету):**

1. JSON состояния объявления: блок `"offerData"` в конфиге микрофронтенда `frontend-offer-card`
   (маркер `OFFER_DATA_MARKER_RE`), резерв — `window._offerJson`;
2. HTML-разметка — если JSON недоступен.

**Сбор ссылок:** только ссылки, данные карточек не используются. URL выдачи —
`https://cian.ru/cat.php?...&offer_type=flat...` с `city_id` из `ParserConfig.cities`
(`vladivostok: 4701`, `moscow: 1`). То есть **Cian собирает только квартиры**.

**Особенности:**

- `_extract_offer_json()` ищет `"offerData": {` и декодирует сбалансированный JSON;
- `_build_item_from_json()` заполняет модель, `_fill_missing_from_html()` дозаполняет пустые поля;
- словари `BATHROOM_LABELS`, `WINDOW_VIEW_LABELS`, `ELEVATOR_TYPE_LABELS` переводят коды в подписи;
- при неудачной загрузке списка — **интерактивный** `input()` с предложением решить капчу
  ([`cian_parser.py:412-421`](parsers/realizations/cian_parser.py:412));
- юридический блок (`offer_legal_info`) — самый полный именно у Cian.

---

## 7. Yandex Недвижимость

[`yandex_parser.py`](parsers/realizations/yandex_parser.py) — самый крупный и сложный парсер.

**Источники данных (по приоритету):**

1. JSON состояния страницы (`window.INITIAL_STATE`, `__INITIAL_STATE__`, `__PRELOADED_STATE__`,
   `__NEXT_DATA__`, `__NUXT__`, `__APOLLO_STATE__`, `JSON.parse(...)`, `<script type="application/json">`);
2. JSON-LD (`@graph`, `Product`, `Apartment`, `Offer`) — в первую очередь для координат;
3. HTML (`data-testid`, `itemprop`, ссылки `/offer/<id>/`, галерея);
4. fallback из заголовка (площадь, комнаты, тип объекта).

**Категории:** `flat`, `newbuilding`, `house`, `land_plot`, `garage`, `commercial`, `room`.
Для нестабильных URL задано несколько кандидатов; рабочий шаблон закрепляется после первой страницы.

**Особенности:**

- защита от «ловушки» `relatedOffersData`: целевой оффер ищется по `offerId` из URL
  (`_pick_offer`, `_iter_state_offers`, `_collect_offer_dicts`);
- `_validate_item()` отбрасывает записи без обязательных полей и без площади;
- дедупликация по `external_id` (`seen_ids`) в дополнение к `seen_urls`;
- повторные попытки с backoff (`max_retries`), паузы больше, чем у Cian/Avito;
- при отсутствии JSON состояния один раз сохраняется `yandex_offer_debug.html`;
- SmartCaptcha: парсер останавливается и ждёт решения в браузере;
- `headless` включается через `ParserConfig.headless`.

**Исторический документ:** [`PROMPT_YANDEX_FIX.md`](parsers/PROMPT_YANDEX_FIX.md) описывает
диагностику старой версии парсера. Часть проблем уже закрыта (маркер `INITIAL_STATE`,
разворачивание `@graph`, выбор `offerCard.card`), но файл полезен как карта источников полей.

---

## 8. Слой загрузки в PostgreSQL

### 8.1 `db/config.py`

Порядок поиска `.env`: аргумент CLI → `parsers/.env` → `../.env` → текущий каталог.
`get_dsn()` собирает `postgresql://user:password@host:port/db`, пароль маскируется в логах.

### 8.2 `db/normalize.py`

Маппинги и нормализация:

- `site` → `sites.code` (по имени и по домену URL);
- `object_type`, `housing_type`, `deal_type` — словари синонимов;
- `rooms_count`: Avito «2» → `2`, «студия»/«свободная планировка» → `None`;
- `ceiling_height`: Yandex сантиметры (`287.0`) → `2.87`, если значение > 10;
- `area`, `living_area`, `kitchen_area`, `price`, `price_per_meter` — числа, отрицательные → `None`;
- `get_value_type()` — определяет `text` / `number` / `bool` для EAV;
- `slugify()` — транслитерация кириллицы и `[a-z0-9_]`, максимум 64 символа.

### 8.3 `db/repositories.py`

`MemoryCache` кэширует справочники (`sites`, `object_types`, `housing_types`, `deal_types`,
`tag_types`, `attribute_categories`, `attribute_definitions`). Функции:
`get_or_create_*`, `upsert_location`, `get_or_create_developer`, `upsert_residential_complex`,
`upsert_building`, `upsert_seller`, `get_or_create_tag`, `upsert_attribute_definition`.

### 8.4 `db/loader.py`

`load_offer(conn, data, cache, dry_run=False)` выполняет 11 шагов загрузки в одной транзакции
(см. [`REVIEW_DATABASE.md`](REVIEW_DATABASE.md), раздел 7.1). Ключевые решения:

- `properties` создаётся **предварительно** под каждое объявление (дедупликация — отдельный этап);
- `offers` — `INSERT ... ON CONFLICT (site_id, external_id) DO UPDATE` с `COALESCE`, чтобы
  не затирать уже заполненные поля пустыми;
- `RUSSIAN_LABEL_MAP` переводит русские подписи `parameters` на известные EAV-коды;
- `_resolve_attribute()` согласует тип значения с `attribute_definitions.value_type`
  (при конфликте создаёт `code_<type>`), что защищает от падения триггера.

### 8.5 `db_migrator.py`

CLI: `--file`, `--site`, `--limit`, `--dry-run`, `--skip-errors`, `--env-file`, `--verbose`.
По умолчанию читает `avito_result.json`, `cian_result.json`, `yandex_result.json`.
Транзакция на объявление: `commit` при успехе, `rollback` при ошибке; при `--skip-errors`
процесс продолжается.

---

## 9. Тесты и инструменты

- [`tests/conftest.py`](parsers/tests/conftest.py) — фикстуры, подмена Selenium и задержек.
- [`tests/test_yandex_parser.py`](parsers/tests/test_yandex_parser.py) — маппинг полей, fallback-источники,
  пагинация, дедупликация, retry/backoff, капча.
- [`tests/test_integration.py`](parsers/tests/test_integration.py) — фабрика, `main`, регрессия Avito/Cian.
- [`tests/test_db_migrator.py`](parsers/tests/test_db_migrator.py) — загрузчик БД.
- `tools/`: `dump_initial_state.py`, `check_state_structure.py`, `dump_state_shapes.py`,
  `analyze_by_type.py`, `diagnose_yandex_result.py`, `normalize_yandex_result.py`,
  `fetch_offer_probe.py`, `locate_offer_container.py`, `inspect_debug_payload.py`,
  `check_debug_html_markers.py`.

Тесты не обращаются к сети — это правильное решение для CI.

---

## 10. Сильные стороны

1. **Единый интерфейс и фабрика** — источники взаимозаменяемы.
2. **Многоуровневые источники данных** у Cian и Yandex (JSON → JSON-LD → HTML → заголовок),
   что повышает устойчивость к изменениям вёрстки.
3. **Явная обработка капчи и антибота**, логирование и продолжение работы при ошибках.
4. **Нормализация в отдельном слое** (`db/normalize.py`), а не в парсерах.
5. **UPSERT-загрузка** с `COALESCE` — повторный парсинг не обнуляет данные.
6. **Диагностические инструменты** для Yandex и подробный `README`.

---

## 11. Проблемы и риски

| Приоритет | Проблема | Где | Следствие |
| --- | --- | --- | --- |
| P0 | `get_or_create_site/object_type/housing_type/deal_type` делают `INSERT (code)` при `name NOT NULL` | [`repositories.py:87-146`](parsers/db/repositories.py:87) | падение при появлении нового кода (сейчас скрыто предзаполненными справочниками) |
| P0 | `--dry-run` делает `rollback` каждого объявления, но `MemoryCache` сохраняет id откатанных строк | [`db_migrator.py:171-180`](parsers/db_migrator.py:171) | последующие объявления могут ссылаться на несуществующие id → FK-ошибки |
| P1 | `get_dsn()` при отсутствии переменных подставляет не то: `DB_PORT ← DB_USER`, `POSTGRES_DB ← DB_PASSWORD` | [`config.py:68-74`](parsers/db/config.py:68) | неверный DSN и запутанные ошибки конфигурации |
| P1 | `property_attributes_*` удаляются по `property_id` при загрузке каждого объявления | [`loader.py:399-401`](parsers/db/loader.py:399) | конфликт с будущей дедупликацией (общий `property` у нескольких `offers`) |
| P1 | `parse()` у Avito и Cian всегда возвращает `True`, даже если ничего не собрано | `avito_parser.py`, `cian_parser.py` | контракт `(False, None)` не соблюдается, вызывающая сторона не узнает о сбое |
| P1 | Cian использует блокирующий `input()` при капче | [`cian_parser.py:412`](parsers/realizations/cian_parser.py:412) | невозможно запустить в headless/CI без ручного вмешательства |
| P1 | Нет дедупликации `properties` | — | `properties` ≈ `offers`, `match_method`/`match_confidence` пусты |
| P2 | Yandex пишет в модель сырые коды: `window_view="YARD_STREET"`, `building_type="buildingType"`, `land_type="lotType"`, `garage_type="garageType"`, `bathroom="bathroomUnit"`, `repairs="renovation"`, `finishing="NO_DECORATION"`, `building_status="HAND_OVER"` | [`yandex_result.json`](parsers/yandex_result.json) | мусор в `buildings` и EAV; нужна нормализация кодов |
| P2 | `feature_chips` дублируются в `parameters` как пары «слово → слово» (`{"бетон": "бетон"}`) | `yandex_parser.py` | загрузчик создаёт десятки бесполезных `attribute_definitions` |
| P2 | `ceiling_height` Yandex в сантиметрах (`287.0`) | `yandex_result.json` | сырой JSON несовместим с Avito/Cian (`2.87`); исправляется только в БД |
| P2 | `rooms_count` Avito — строка, у остальных — число | `site_parse_data_model.py` | лишние ветвления в потребителях |
| P2 | Фильтры `min_cost`/`max_cost`/`area_*`/`rooms_*`/`floor_*` не реализованы | `ParserConfig` | конфигурация вводит в заблуждение |
| P2 | `stats["inserted"]` в загрузчике увеличивается на число фото/тегов | [`loader.py:327`](parsers/db/loader.py:327), [`loader.py:354`](parsers/db/loader.py:354) | итоговая статистика завышена и не отражает число объявлений |
| P2 | `_ensure_cache()` — заглушка, всегда создаёт новый кэш | [`repositories.py:43`](parsers/db/repositories.py:43) | мёртвый код |
| P2 | Жёстко заданные города и категории (Avito — только Владивосток, Cian — только квартиры) | `avito_parser.py`, `cian_parser.py` | ограниченный охват без правки кода |
| P2 | `yandex_parser.py` ~4.2 тыс. строк, десятки приватных методов | `yandex_parser.py` | сложно сопровождать и тестировать точечно |

---

## 12. Рекомендации

**P0 — исправить до расширения функциональности**

1. В `get_or_create_*` передавать `name` (например, `name = code`) либо добавить `DEFAULT` в схему.
2. Переписать `--dry-run`: либо один общий `ROLLBACK` в конце, либо сбрасывать `MemoryCache`
   после каждого отката.
3. Реализовать модуль дедупликации и заполнение `match_method` / `match_confidence`.

**P1 — качество и надёжность**

4. Привести `parse()` к контракту: возвращать `(False, None)`, если не собрано ни одной записи
   и источник был недоступен.
5. Заменить `input()` на настраиваемый режим ожидания капчи (таймаут + флаг «пропустить»).
6. Исправить fallback-маппинг в `get_dsn()` и добавить валидацию числового `DB_PORT`.
7. Перейти от `DELETE`+`INSERT` к `UPSERT` для `property_attributes_*`.

**P2 — чистота данных**

8. Добавить словари нормализации кодов Yandex (`windowView`, `buildingType`, `lotType`,
   `garageType`, `bathroomUnit`, `repair`, `finishing`, `buildingState`) — по образцу
   `BATHROOM_LABELS` у Cian.
9. Не дублировать `feature_chips` в `parameters`; для EAV использовать только реальные
   характеристики «название: значение».
10. Приводить `ceiling_height` к метрам в парсере, а не только в загрузчике.
11. Унифицировать `rooms_count` к `int | None` во всех моделях.
12. Разделить `stats` на `offers_inserted` и `related_rows_inserted`.
13. Разбить `yandex_parser.py` на модули: `state.py`, `json_ld.py`, `html.py`, `mapping.py`.

---

## 13. Запуск и проверка

```bash
cd parsers

# сбор данных
uv run main.py --site avito
uv run main.py --site cian
uv run main.py --site yandex --pages 2 --min-delay 3 --max-delay 6

# тесты и линтер (без сети)
uv run --group dev pytest -q
uv run --group dev ruff check realizations main.py tests

# загрузка в PostgreSQL
uv run python db_migrator.py --dry-run
uv run python db_migrator.py --site avito --limit 10
uv run python db_migrator.py
```

Конфигурация подключения — `.env` в корне проекта (см. [`.env.example`](.env.example)).
Для загрузки нужна поднятая БД: `docker compose up -d postgres`.
