# Обзоры проекта

Набор документов с техническим разбором текущего состояния проекта интеграции объявлений
о недвижимости (Cian / Avito / Yandex Недвижимость).

| Документ | Содержание |
| --- | --- |
| [`REVIEW_STACK.md`](REVIEW_STACK.md) | Стек технологий: что заявлено в [`Stack.md`](Stack.md), что реально реализовано, риски и рекомендации |
| [`REVIEW_DATABASE.md`](REVIEW_DATABASE.md) | Разбор схемы PostgreSQL по [`init_db.sql`](postgres/init/init_db.sql): 24 таблицы, типизированный EAV, индексы, представление, дедупликация, риски |
| [`REVIEW_PARSERS.md`](REVIEW_PARSERS.md) | Разбор кода [`parsers/`](parsers): архитектура, три парсера, модели данных, слой загрузки в БД, тесты, проблемы и рекомендации |

Дополнительные исходные материалы:

- [`postgres/db_structure.txt`](postgres/db_structure.txt) — подробное описание структуры БД;
- [`parsers/README.md`](parsers/README.md) — README пакета парсеров;
- [`parsers/PROMPT_YANDEX_FIX.md`](parsers/PROMPT_YANDEX_FIX.md) — карта источников полей
  Яндекс Недвижимости (историческая диагностика);
- [`parsers/авито парсер статистика.txt`](parsers/авито%20парсер%20статистика.txt) — заполненность
  полей Avito по сохранённому JSON.

---

## Краткая сводка

### Что уже работает

- Схема PostgreSQL 16: справочники, ядро `properties`/`offers`, типизированный EAV с триггерами,
  полнотекстовые и триграммные индексы, витрина `v_property_search`.
- Три парсера на Python 3.13 + Selenium, единая модель данных и фабрика парсеров.
- Загрузчик JSON → PostgreSQL (`parsers/db/`, `db_migrator.py`) с UPSERT и нормализацией.
- Тесты без сетевого доступа и диагностические инструменты для Yandex.

### Чего не хватает

| Приоритет | Пробел |
| --- | --- |
| P0 | Нет скрипта дедупликации `properties`; `match_method` / `match_confidence` не заполняются |
| P0 | Backend — заглушка `Hello World`; путь проекта в [`Backend.slnx`](Backend.slnx) неверен |
| P1 | Нет Dockerfile для API/парсеров, нет Nginx, Kafka и data-processor |
| P1 | `--dry-run` загрузчика оставляет «фантомные» id в кэше |
| P1 | `get_or_create_*` вставляет справочники без обязательного `name` |
| P2 | Сырые коды Yandex (`YARD_STREET`, `lotType`, `NO_DECORATION`) попадают в БД без перевода |
| P2 | `feature_chips` дублируются в `parameters` и засоряют EAV |

### Как читать обзоры

1. Начните с [`REVIEW_STACK.md`](REVIEW_STACK.md) — общая картина и готовность слоёв.
2. Затем [`REVIEW_DATABASE.md`](REVIEW_DATABASE.md) — модель данных и правила загрузки.
3. Затем [`REVIEW_PARSERS.md`](REVIEW_PARSERS.md) — как устроен сбор и где узкие места.
