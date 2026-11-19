# Задача: починить извлечение данных в парсере Яндекс Недвижимости

## Контекст проекта

- Рабочая папка: `parsers/` (проект `c:/Users/Evgeniy/Desktop/DB/project_1/parsers`)
- Стек: Python, `uv`, Selenium (Chrome), BeautifulSoup, dataclasses
- Запуск: `cd parsers && uv run main.py --site yandex`
- Результат: `parsers/yandex_result.json` — список объектов `YandexSiteParseData` (82 поля)
- Модель: [`YandexSiteParseData`](model/site_parse_data_model.py:244)
- Парсер: [`yandex_parser.py`](realizations/yandex_parser.py:1) (~3580 строк)
- Не ломать `avito_parser.py` / `cian_parser.py` и формат их JSON.

## Симптомы (текущий результат)

- 120 объявлений, 120 уникальных `external_id` и `url` — сбор ссылок работает корректно.
- Заполнено ~18 из 82 полей: `site`, `url`, `external_id`, `name`, `category`, `object_type`, `breadcrumbs`, `price`, `price_per_meter`, `price_unit`, `currency`, `deal_type`, `area`, `area_unit`, `imgs`, `photos_count`, `parameters`, `geo_label` (объект есть, но все 6 полей пустые).
- Частично: `rooms_count` 34/120, `land_area`/`land_area_unit` 40/120 (только участки).
- Пусто у всех 120: `description`, `address`, `latitude`, `longitude`, `floor`, `floors_count`, `living_area`, `kitchen_area`, `ceiling_height`, `bathroom`, `balcony`, `window_view`, `repairs`, `finishing`, `year_building`, `building_status`, `building_material`, `building_type`, `completion_date`, `floors_range`, `entrances_count`, `apartments_count`, `elevators`, `parking`, `garbage_chute`, `heating`, `water_supply`, `sewerage`, `electricity`, `gas`, `internet`, `telephone`, `sauna`, `land_type`, `garage_type`, `commercial_purpose`, `entrance_type`, `residential_complex*`, `developer*`, `seller_*`, `publish_date`, `update_date`, `views_count`, `badges`, `feature_chips`.
- `parameters` содержит ложные пары: `{"Санкт": "Петербург", "Ростов": "на-Дону", "Спасск": "Дальний", "Проспект 100": "летия Владивостока"}` — парсится футер страницы.
- `imgs` содержит дубли `/minicard` и `builder_logo_info`; `photos_count = len(imgs)`, поэтому завышен (46, 44, 90, 110, 122, 128).
- В логе: `JSON состояния не найден ... Найденные маркеры: application/json, JSON.parse(`.

## Причина 1 (главная): неверный маркер контейнера состояния

Страница содержит `<script id="initial_state_script">window.INITIAL_STATE = {...}</script>`.

В [`INITIAL_STATE_MARKERS`](realizations/yandex_parser.py:275) перечислены `window.__INITIAL_STATE__`, `window.__INITIAL_STATE`, `window._initialState`, `window.initialState`, `window.__PRELOADED_STATE__`, `window.__NEXT_DATA__`, `window.__NUXT__`, `window.__APOLLO_STATE__`, но **нет** `window.INITIAL_STATE`. Поэтому [`_extract_initial_state()`](realizations/yandex_parser.py:1170) возвращает `None`, и [`_apply_state()`](realizations/yandex_parser.py:1486) не вызывается вообще.

Что сделать:

1. Добавить `window.INITIAL_STATE` в маркеры.
2. Надёжнее — быстрый путь: найти `<script id="initial_state_script">`, взять его содержимое, снять префикс `window.INITIAL_STATE = ` и завершающую `;`, затем `json.loads`. Если не получилось — использовать существующий универсальный разбор.
3. Убедиться, что `_decode_state_at()` корректно обрабатывает префикс `" = "` (он уже strip-ает ` \t\r\n=:(;`).

## Причина 2 (критично): ловушка `relatedOffersData`

В состоянии:

- `offerCard.card` — нужный оффер (97 ключей);
- `offerCard.relatedOffersData.offers` — 10 рекомендаций (единственный непустой блок `offers`).

[`_iter_state_offers()`](realizations/yandex_parser.py:1367) через `_deep_find(state, ("offers",))` найдёт именно рекомендации, а [`_pick_offer()`](realizations/yandex_parser.py:1461) при отсутствии совпадения по id вернёт `candidates[0]` — то есть **чужое объявление**. После добавления маркера без этой защиты поля заполнятся данными другого оффера.

Требования:

- В `_iter_state_offers` / `_pick_offer` первым делом брать `state["offerCard"]["card"]` и проверять `offerId == id из URL`.
- Убрать fallback `candidates[0]` либо разрешать его только при совпадении id.
- Если целевой оффер не найден — логировать warning и возвращать `None`, а не данные рекомендации.
- Добавить в `_build_item`/`_validate_item` проверку: `external_id` совпадает с id из URL.

## Причина 3: несовпадение имён ключей состояния

| Источник в `offerCard.card` | Поле модели | Примечание |
|---|---|---|
| `offerId` | `external_id` | |
| `description` | `description` | полный текст, начинается с артикула `DNV-07-01-02-003-003` |
| `offerCategory` (`APARTMENT`/`LOT`/`GARAGE`/`COMMERCIAL`/`ROOMS`) | `category` | |
| `offerType` (`SELL`) | `deal_type` | |
| `flatType` (`NEW_FLAT`) | `housing_type` | `NEW_FLAT` → «новостройка», `SECONDARY`/`FLAT` → «вторичка» |
| `roomsTotal` | `rooms_count` | сейчас ищется `roomsCount`/`rooms` |
| `floorsOffered` (`[2]`) | `floor` | брать первый элемент |
| `floorsTotal` (`17`) | `floors_count` | `floorsTotal` уже есть в `_deep_find` |
| `area` `{value: 41.9, unit: SQUARE_METER}` | `area`, `area_unit` | добавить нормализацию `SQUARE_METER` → `м²` |
| `livingSpace` `{value: 19}` | `living_area` | сейчас ищется `livingArea` |
| `house.bathroomUnit` (`SEPARATED`) | `bathroom` | `BATHROOM_LABELS` знает `separated` |
| `house.windowView` (`YARD`) | `window_view` | нужен словарь: `YARD` → «во двор», `STREET` → «на улицу» и т. п. |
| `building.builtYear` (`2027`), `builtQuarter` (`3`) | `year_building`, `completion_date` | |
| `building.buildingState` (`UNFINISHED`) | `building_status` | `UNFINISHED` → «строится», `BUILT` → «сдан» |
| `building.parkingType` (`OPEN`) | `parking` | `OPEN` → «открытая», `CLOSED` → «закрытая», `UNDERGROUND` → «подземная» |
| `building.siteDisplayName` / `siteName` | `residential_complex` | `ЖК «ДОМ на Востоке»` |
| `building.heatingType` | `heating` | игнорировать `UNKNOWN` |
| `offerCard.siteCard.fullName` | `residential_complex` (fallback) | |
| `offerCard.siteCard.developer.name` | `developer` | |
| `offerCard.siteCard.developer.statistic.finished.houses` | `developer_completed_buildings` | |
| `offerCard.siteCard.developer.statistic.unfinished.houses` | `developer_buildings_under_construction` | |
| `newBuilding` (`true`, bool) | `housing_type` | сейчас `_apply_state` ждёт dict → теряется |
| `author.name` / `organization` | `seller_name` | |
| `author.category` (`DEVELOPER`) | `seller_type` | через `SELLER_TYPE_LABELS` |
| `author.organization` | `agency` | |
| `author.creationDate` | `seller_experience` | «на сервисе с …» |
| `price.value` | `price` | |
| `price.currency` (`RUR`) | `currency` | → `RUB` |
| `price.valuePerPart` (`195076`) | `price_per_meter` | |
| `price.unitPerPart` (`SQUARE_METER`) | `price_unit` | |
| `tags` `[{id, title}]` | `feature_chips`, `parameters` | `title` в список; не брать из футера |
| `totalImages` (`7`) | `photos_count` | |
| `mainImages` / `appLargeImages` | `imgs` | списки протокол-относительных строк `//avatars...` |
| `creationDate` | `publish_date` | |
| `updateDate` | `update_date` | |
| `views` (`3`) | `views_count` | |
| `dealStatus` (`PRIMARY_SALE`) | `sale_method` | «первичная продажа» |
| `keyHandoverDate` / `commissioningDateIndexValue` (`20273` = 2027 Q3) | `completion_date` | |
| `location.address` | `address` | `Владивосток, жилой комплекс Дом на Востоке, 7к1` |
| `location.structuredAddress.component[]` | `geo_label` | см. ниже |
| `breadcrumbs` (top-level, `[{link, title}]`) | `breadcrumbs` | последний элемент содержит «2/17 этаж» |

Маппинг `structuredAddress.component[]` по `regionType`:

- `SUBJECT_FEDERATION` → `region`
- `CITY` → `city`
- `SUBJECT_FEDERATION_DISTRICT` → `district`
- `CITY_DISTRICT` → `micro_district`
- `STREET` → `street`
- `HOUSE` → `house`

`offer_article`: описание начинается с артикула `DNV-07-01-02-003-003` без слова «артикул», поэтому текущий [`_article_from_text()`](realizations/yandex_parser.py:3438) его не найдёт. Добавить распознавание первого токена вида `[A-Z]{2,}-\d...`.

## Причина 4: JSON-LD `@graph` не разбирается

В HTML 3 блока `application/ld+json`. Третий: `{"@context": ..., "@graph": [Product, RealEstateListing, Apartment, Offer]}`.

[`_apply_json_ld()`](realizations/yandex_parser.py:2171) читает только верхний уровень узла, поэтому `@graph` игнорируется. Нужно разворачивать `@graph` и `mainEntity`/`itemOffered` и брать:

- `Product`: `name`, `description`, `image`, `offers.price`, `offers.priceCurrency`, `sku`, `category`;
- `Apartment`: `address` (`PostalAddress`: `addressCountry`, `addressRegion`, `addressLocality`, `streetAddress`), `floorLevel`, `floorSize{value, unitCode}`, `geo{latitude, longitude}`, `numberOfRooms`;
- `Offer`: `price`, `priceCurrency`.

Использовать как fallback; в первую очередь это единственный источник `latitude`/`longitude` (в `offerCard.card` координат нет).

## Причина 5: мусорные `parameters`

[`_extract_li_parameters()`](realizations/yandex_parser.py:2441) обходит **все** `<li>`, включая футер (`CacheFooterLinksSections__link`), а [`_split_parameter_text()`](realizations/yandex_parser.py:2553) режет строку по `[:\-—–]`. Поэтому «Санкт-Петербург» → `"Санкт": "Петербург"`.

Нужно:

- ограничить выборку реальными блоками характеристик: `OfferCardDetailsFeatures__feature`, `OfferCardFeature__text`, `OfferCardBuildingFeatures__feature`, `OfferCardDevBadge__name`, `[data-testid*="offer-fact"]` (если появится);
- убрать `-` из разделителей (оставить `:` и `—`);
- отбрасывать label из чёрного списка: `Санкт`, `Ростов`, `Спасск`, `Проспект 100`, `Фотография`, `Главная`, `Назад`, `Подробнее`;
- `parameters` заполнять из `tags` (title), а не из футера.

## Причина 6: `imgs` и `photos_count`

[`_filter_photo_urls()`](realizations/yandex_parser.py:2891) пропускает `/minicard` (дубли того же фото) и `builder_logo_info` (логотип застройщика).

Нужно:

- исключать URL с `/minicard` и `builder_logo_info` (и `get-realty-content`, если это не фото объявления);
- брать `appLargeImages`/`mainImages` из состояния (7 уникальных URL);
- `photos_count` = `totalImages` из состояния, иначе число уникальных `imgs`.

## Типовые особенности (не «исправлять», но учесть)

- Для `land_plot` отсутствие `rooms_count`, `floor`, `floors_count`, `kitchen_area`, `bathroom`, `balcony` — нормально.
- Применимые, но сейчас пустые: `land_type` (участок), `garage_type` (гараж), `commercial_purpose` (коммерция), `rooms_in_flat` (комната; в HTML есть «1 комната в 5-к квартире»).
- Для студии `rooms_count = None` — нормально.

## Критерии приёмки

После `uv run main.py --site yandex` на 120 объявлениях:

1. В логе нет `JSON состояния не найден`.
2. `description` 120/120 (непустой; для новостройки содержит артикул).
3. `address` 120/120, `geo_label.region` и `geo_label.city` 120/120, `latitude`/`longitude` > 0 хотя бы для квартир и домов.
4. `floor` > 0 и `floors_count` > 0 у `flat`/`room` (включая новостройки).
5. `seller_name` 120/120, `seller_type` заполнен.
6. `residential_complex` непустой у объявлений с ЖК; `developer` — у новостроек.
7. `year_building`/`completion_date` заполнены там, где данные есть.
8. `parameters` не содержит ключей `Санкт`, `Ростов`, `Спасск`, `Проспект 100`, `Фотография` и обрывков значений.
9. `imgs` без `/minicard` и `builder_logo_info`; `photos_count == totalImages` (7 для тестового объявления), а не 46.
10. Нет записей с данными другого `offerId`: `external_id` совпадает с id из URL, а `description`/`name` соответствуют площади и комнатам заголовка.
11. `uv run python tools/analyze_by_type.py` и `uv run python tools/diagnose_yandex_result.py` показывают заполнение; полностью пустыми остаются только объективно неприменимые поля.

## Как проверять

```bash
cd parsers
uv run python tools/dump_initial_state.py       # состояние парсится, есть offerCard.card
uv run python tools/check_state_structure.py    # берётся card, а не relatedOffersData
uv run python tools/analyze_by_type.py          # заполненность по типам
uv run python tools/diagnose_yandex_result.py   # общая заполненность
uv run python -m pytest tests/test_yandex_parser.py -q
```

Тестовый HTML: `parsers/yandex_offer_debug.html` (квартира `661250810916136822`, 2.6 МБ, содержит `window.INITIAL_STATE`, JSON-LD `@graph`, блоки `OfferCardFeature__text`).

## Ограничения

- Не менять формат полей JSON (обратная совместимость с текущим `yandex_result.json`).
- Не трогать парсеры Avito и Cian.
- Не хардкодить конкретный `offerId`, город или число объявлений.
- Обычный HTTP-запрос к Яндекс Недвижимости отдаёт капчу (~14 КБ заглушки), поэтому проверять только через Selenium.
- Если поле физически отсутствует в данных — оставлять пустое значение, не падать и не подставлять чужие данные.
- Сохранить текущее логирование заполненности по каждому объявлению.

## Ожидаемый отчёт

- Список изменений с указанием файла и строк.
- Таблица «поле → источник» (state / JSON-LD / HTML).
- Результаты прогона: заполненность до и после, отсутствие мусора в `parameters`, корректный `photos_count`.
- Отдельно перечислить поля, которых нет в данных Яндекса, не выдавая их за баг.
