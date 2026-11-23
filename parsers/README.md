# Парсеры объявлений недвижимости

Пакет содержит три парсера источников (Avito, Cian, Яндекс Недвижимость),
общую модель данных, конфигурацию и фабрику парсеров.

## Структура

```
parsers/
├── main.py                          # точка запуска (CLI)
├── interfaces/
│   └── parser_interfaces.py         # IParcer: parse(config) -> (success, items)
├── model/
│   ├── parser_config.py             # ParserConfig (общая конфигурация)
│   └── site_parse_data_model.py     # Cian/Avito/YandexSiteParseData
├── realizations/
│   ├── avito_parser.py              # AvitoParser
│   ├── cian_parser.py               # CianParser
│   ├── yandex_parser.py             # YandexParser
│   └── parser_factory.py            # реестр и create_parser()
└── tests/                           # pytest: юнит, интеграционные, регрессия
```

## Общая схема работы

1. Парсер постранично обходит выдачу и собирает ссылки на объявления.
2. Для каждой ссылки открывается страница объявления (Selenium + Chrome)
   и из неё извлекаются поля соответствующей модели.
3. Проблемное объявление пропускается с записью в лог, процесс не
   останавливается.

Общие соглашения для всех парсеров:

- `parse(parserConfig) -> tuple[bool, list[...] | None]`;
- `Options.page_load_strategy = "eager"`, stealth-настройки браузера;
- задержки между запросами из `ParserConfig` (`min_iteration_time_span`,
  `max_iteration_time_span`), при нулях — безопасные значения по умолчанию;
- повторные попытки с backoff, обработка капчи/антибот-заглушки;
- логирование через `logging.getLogger("<site>_parser")`.

## Запуск

```bash
cd parsers

# по умолчанию — Avito (как раньше)
python main.py

# только Яндекс Недвижимость
python main.py --site yandex

# все источники
python main.py --site all

# переопределение параметров
python main.py --site yandex --pages 2 --min-delay 3 --max-delay 6 \
    --output-dir out --headless
```

Результат сохраняется в `<site>_result.json` (список словарей модели).

## Конфигурация

`ParserConfig` (`model/parser_config.py`):

| Поле | Назначение |
| --- | --- |
| `max_page_iteration` | число страниц выдачи на категорию |
| `min_iteration_time_span`, `max_iteration_time_span` | пауза между запросами, сек |
| `cities` | для Cian — `город -> city_id`; для Яндекса — `slug -> rgid` |
| `max_retries` | число повторных попыток загрузки страницы (по умолчанию 3) |
| `page_wait_time` | ожидание загрузки страницы, сек (по умолчанию 10) |
| `headless` | запуск браузера без окна |

`min_cost`, `max_cost`, `area_*`, `rooms_count_*`, `floor_*` пока не
используются ни одним парсером (помечены в коде как «не реализовано»).

## Яндекс Недвижимость

### Источник данных

Прямой HTTP-запрос к `realty.yandex.ru` возвращает SmartCaptcha, поэтому
данные берутся из DOM после загрузки страницы в браузере. Приоритет
источников:

1. JSON состояния страницы — поддерживаются `window.__INITIAL_STATE__`,
   `__PRELOADED_STATE__`, `__NEXT_DATA__`, `__NUXT__`,
   `__APOLLO_STATE__`, `JSON.parse("...")` и
   `<script type="application/json">` (`offers.entities`, `offer`);
2. JSON-LD (`<script type="application/ld+json">`, `Product`/`Offer`);
3. HTML-разметка (`data-testid`, `itemprop`, `dl/dt/dd`, ссылки
   `/offer/<id>/`, галерея);
4. fallback из заголовка объявления: площадь, комнаты и тип объекта
   (`43 м², 1-комнатная квартира`, `10 соток, участок`,
   `машиноместо`, `9,1 м², комната`).

Если JSON состояния не найден, HTML первой страницы объявления
сохраняется в `yandex_offer_debug.html` — по нему можно определить
актуальный контейнер данных.

### Категории и типы объектов

| Категория URL | `object_type` |
| --- | --- |
| `kupit/kvartira` | `flat` |
| `kupit/kvartira/novostroyki` (резерв — каталог ЖК `kupit/novostrojka`) | `flat` + `housing_type = новостройка` |
| `kupit/dom` | `house` |
| `kupit/uchastok` | `land_plot` |
| `kupit/garazh` | `garage` |
| `kupit/kommercheskaya-nedvizhimost` | `other` |
| `kupit/komnata` (резерв: `search/?category=ROOMS`) | `room` |

Для категорий с исторически менявшимся URL задано несколько
кандидатов: парсер пробует их по очереди и закрепляет рабочий вариант.
Студия определяется по `flatType`/`roomsCount`/заголовку.

Адреса `kupit/novostroyka` и `novostrojki` отдают страницу 404 — их
использовать нельзя. Страница 404 распознаётся по тексту заглушки
(«Ошибка 404», «Страница не найдена», «Не удалось открыть страницу»)
и не считается валидной выдачей, даже если содержит отдельные ссылки
`/offer/<id>/` из блока рекомендаций.

### Маппинг полей (`YandexSiteParseData`)

| Поле модели | Источник Яндекса |
| --- | --- |
| `site` | всегда `"Yandex"` |
| `url` | канонический `https://realty.yandex.ru/offer/<id>/` |
| `external_id` | `offer.offerId` / `id` / JSON-LD `sku` / id из URL |
| `name`, `subtitles`, `description` | `title`/`name`, `subtitle`/`shortDescription`, `description` |
| `offer_article` | `offerArticle`/`article`/`vendorCode` или «Артикул …» из описания |
| `category` | `offer.category` (`APARTMENT`, `HOUSE`, `LOT`, …) |
| `object_type` | категория объявления + URL + признак студии |
| `housing_type` | `isNewBuilding` / `building.newBuilding` / блок `newBuilding` |
| `breadcrumbs` | `offer.breadcrumbs` или `[data-testid="breadcrumbs"]` |
| `price` | `price.value` (или `price`) |
| `price_per_meter` | `pricePerSquareMeter` либо `price / area` |
| `currency` | `price.currency` (`RUR`/`RUB`/`₽` → `RUB`) |
| `deal_type` | `offer.type` (`SELL` → `sale`, `RENT` → `rent`) |
| `deal_conditions`, `sale_method` | `dealConditions`/`bargainTerms`, `saleType`/`saleMethod` |
| `mortgage_possible` | `mortgage`/`mortgageAllowed` |
| `area`, `living_area`, `kitchen_area` | `area`/`totalArea`, `livingArea`, `kitchenArea` (`{"value","unit"}`) |
| `area_unit`, `price_unit` | `unit` (`SQM` → `м²`, `SOTKA` → `сот.`) |
| `rooms_count`, `rooms_in_flat` | `roomsCount`/`rooms`, `roomsInFlat` |
| `floor`, `floors_count` | `floor`, `floorsCount`/`building.floorsCount` |
| `ceiling_height` | `ceilingHeight` |
| `bathroom`, `balcony`, `window_view` | `bathroomUnit` (`SEPARATE` → раздельный), `balcony`/`loggia`, `windowView` |
| `repairs`, `finishing` | `repair`/`renovation`, `finishing`/`decoration` (`FINE` → чистовая) |
| `year_building`, `building_status` | `building.year`, `building.status` (`BUILT` → сдан) |
| `building_material`, `building_type` | `building.material` (`MONOLITH` → монолит), `building.type` |
| `completion_date`, `floors_range` | `completionDate`/`deadline`, `floorsRange` |
| `entrances_count`, `apartments_count` | `building.entrancesCount`, `building.apartmentsCount` |
| `elevators` | `building.elevators` (`[{"type","count"}]` → «пассажирский (2)») |
| `parking`, `garbage_chute` | `parking`, `garbageChute` |
| `heating`, `water_supply`, `sewerage`, `electricity`, `gas` | одноимённые блоки |
| `internet`, `telephone`, `sauna` | `internet`, `telephone`, `sauna` |
| `land_type`, `land_area`, `land_area_unit` | `landType`, `landArea` (`{"value","unit"}`) |
| `garage_type`, `commercial_purpose`, `entrance_type` | `garageType`, `commercialPurpose`/`purpose`, `entranceType` |
| `residential_complex`, `residential_complex_class`, `residential_complex_completion` | `newBuilding.name`, `newBuilding.class`, `newBuilding.completionDate` |
| `developer`, `developer_*` | `developer.name`/`newBuilding.developerName`, `foundationYear`, `completedBuildings`, `buildingsUnderConstruction` |
| `geo_label`, `address` | `address`/`location` (`region`, `locality`, `district`, `microDistrict`, `street`, `house`) |
| `latitude`, `longitude` | `coordinates.lat/lon` или JSON-LD `geo` |
| `nearby_infrastructure` | `nearbyInfrastructure` |
| `seller_name`, `seller_type`, `agency`, `seller_experience` | `seller`/`author` (`AGENCY` → Агентство, `OWNER` → Частное лицо) |
| `imgs`, `photos_count` | `photos[].fullUrl/url`, JSON-LD `image`, `img[src/data-src/srcset]`; остаются только `avatars.mds.yandex.net/get-realty` и `get-altay` |
| `publish_date`, `update_date` | `creationDate`, `updateDate` |
| `views_count`, `badges`, `feature_chips` | `viewsCount`, `badges`, `features` |
| `parameters` | `features` как словарь «название → значение» |

### Нормализация и валидация

- числа: «1 250 000 ₽» → `1250000`, «54,3 м²» → `54.3`;
- коды Яндекса переводятся в читаемые подписи (`SQM` → `м²`,
  `MONOLITH` → `монолит`, `OWNER` → Частное лицо);
- обязательные поля объявления: `url`, `external_id`, `name`, `price > 0`;
- для жилых объектов (`flat`, `studio`, `room`, `house`) обязательна
  `area > 0`, для участка — `area`/`land_area > 0`; записи без площади
  отбрасываются, а не пишутся молча;
- по каждому объявлению в лог пишется доля заполненности ключевых полей;
- отрицательные площади/этажи обрезаются до 0, некорректные
  `rooms_count` сбрасываются в `None`;
- несоответствия (этаж больше этажности, сумма жилой и кухонной площади
  больше общей) логируются, но объявление сохраняется;
- дубликаты отбрасываются по `url` (на этапе сбора ссылок) и по
  `external_id` (на этапе разбора).

### Ограничения

- Яндекс блокирует автоматические запросы SmartCaptcha. При обнаружении
  капчи парсер останавливается и ждёт решения капчи в открытом браузере
  (Enter — продолжить, `n` — пропустить). HTML капчи сохраняется в
  `yandex_captcha_debug.html`.
- Селекторы и ключи JSON могут меняться; поэтому используются четыре
  источника данных, нечёткий поиск ключей (`_deep_find`) и несколько
  контейнеров состояния.
- `rgid` городов задаётся вручную в `main.py` (`yandexConfig.cities`).
  Значение `585430` — Владивосток (используется для поиска комнат).

### Нормализация уже собранного JSON

Если `yandex_result.json` был получен старой версией парсера, его можно
нормализовать без повторного обхода сайта:

```bash
uv run python tools/normalize_yandex_result.py --dry-run
uv run python tools/normalize_yandex_result.py
```

Скрипт применяет fallback из заголовка, фильтрует фотографии,
пересобирает модель и отбрасывает невалидные записи.

## Тесты и линтер

```bash
cd parsers

uv run --group dev pytest -q
uv run --group dev ruff check realizations/yandex_parser.py \
    realizations/parser_factory.py main.py tests
```

Тесты не обращаются к сети: Selenium-драйвер и паузы подменяются,
HTML/JSON-фикстуры синтетические и смоделированы по структуре страниц
Яндекса. Покрыты маппинг полей, fallback-источники, пагинация,
дедупликация, retry/backoff, обработка капчи, фабрика, точка запуска и
регрессия Avito/Cian.

## 3НФ и вычисляемые поля

### Типизированный EAV

Вместо одной таблицы `property_attributes`/`offer_attributes` со столбцами
`value_text`/`value_number`/`value_bool` используются 6 отдельных таблиц:

| Таблица | Назначение |
| --- | --- |
| `property_attributes_text` | Характеристики property — текст |
| `property_attributes_number` | Характеристики property — число |
| `property_attributes_bool` | Характеристики property — bool |
| `offer_attributes_text` | Характеристики offer — текст |
| `offer_attributes_number` | Характеристики offer — число |
| `offer_attributes_bool` | Характеристики offer — bool |

Триггер `fn_check_attribute_value_type()` не позволяет вставить значение
не того типа, что указан в `attribute_definitions.value_type`.

**Почему так:**
- Типизация на уровне таблиц — СУБД гарантирует целостность данных.
- Нет NULL-колонок — каждая строка содержит только одно значение.
- Индексы по узким типам (`NUMERIC`, `BOOLEAN`) работают быстрее.

### Вычисляемые поля

| Поле | Статус |
| --- | --- |
| `locations.address_normalized` | Удалён. Функция `fn_normalize_address(region, city, district, micro_district, street, house)` + GIN-индекс по выражению. |
| `properties.dedup_key` | Удалён. Формула: `md5(fn_normalize_address(...) || object_type_id || floor || rooms_count || round(area))`. Вычисляется на лету скриптом дедупликации. |
| `properties.image_url` | Удалён. Главное фото: `SELECT url FROM offer_images WHERE offer_id IN (...) ORDER BY position, id LIMIT 1`. |
| `properties.search_vector` / `offers.search_vector` | Удалены. GIN-индексы по выражению `to_tsvector('russian', coalesce(name,'')||' '||coalesce(description,''))`. |

### Загрузка в БД

Пакет `parsers/db/` содержит загрузчик JSON → PostgreSQL:

```bash
# Загрузить все файлы
uv run python db/db_migrator.py

# Только Avito, 10 объявлений
uv run python db/db_migrator.py --site avito --limit 10

# Dry-run (без коммита)
uv run python db/db_migrator.py --dry-run
```

Конфигурация подключения — `.env` в корне проекта:
```
DB_HOST=localhost
DB_PORT=5433
POSTGRES_DB=db
POSTGRES_USER=user
POSTGRES_PASSWORD=password
```
