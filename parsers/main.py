"""
Точка запуска парсеров источников недвижимости.

Запуск:
    python main.py                     # поведение по умолчанию (avito)
    python main.py --site yandex       # только Яндекс Недвижимость
    python main.py --site all          # все источники
    python main.py --site yandex --pages 2 --min-delay 3 --max-delay 6

Парсеры создаются через фабрику realizations.parser_factory, поэтому
новый источник подключается одной строкой в реестре фабрики.
"""

import argparse
import json
import logging
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from model.parser_config import ParserConfig
from realizations.parser_factory import available_sites, create_parser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("main")

cities = {"vladivostok": 4701, "moscow": 1}

# configs
cianConfig = ParserConfig(
    max_page_iteration=1,
    min_iteration_time_span=0,
    max_iteration_time_span=0,
    cities={"vladivostok": 4701, "moscow": 1},
    min_cost=0,  # не реализовано
    max_cost=10_000_000,  # не реализовано
    area_min=0,  # не реализовано
    area_max=100,  # не реализовано
    rooms_count_min=0,  # не реализовано
    rooms_count_max=10,  # не реализовано
    floor_min=0,  # не реализовано
    floor_max=100,  # не реализовано
)

avitoCofig = ParserConfig(
    max_page_iteration=1,
    min_iteration_time_span=0,
    max_iteration_time_span=0,
    cities={},
    min_cost=0,  # не реализовано
    max_cost=10_000_000,  # не реализовано
    area_min=0,  # не реализовано
    area_max=100,  # не реализовано
    rooms_count_min=0,  # не реализовано
    rooms_count_max=10,  # не реализовано
    floor_min=0,  # не реализовано
    floor_max=100,  # не реализовано
)

# Для Яндекса ключ словаря cities — slug города в URL, значение — rgid,
# используемый в поиске комнат.
yandexConfig = ParserConfig(
    max_page_iteration=1,
    min_iteration_time_span=0,
    max_iteration_time_span=0,
    cities={"vladivostok": 585430},
    min_cost=0,  # не реализовано
    max_cost=10_000_000,  # не реализовано
    area_min=0,  # не реализовано
    area_max=100,  # не реализовано
    rooms_count_min=0,  # не реализовано
    rooms_count_max=10,  # не реализовано
    floor_min=0,  # не реализовано
    floor_max=100,  # не реализовано
)

PARSER_CONFIGS: dict[str, ParserConfig] = {
    "avito": avitoCofig,
    "cian": cianConfig,
    "yandex": yandexConfig,
}


def _save_result(
    filename: str,
    result: list[Any],
    output_dir: str | Path = ".",
) -> Path:
    """Сохраняет результаты парсера в JSON и возвращает путь к файлу."""
    path = Path(output_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(
            [asdict(item) for item in result],
            file,
            indent=4,
            ensure_ascii=False,
        )

    return path


def _run_parser(
    site: str,
    config: ParserConfig,
    output_dir: str | Path = ".",
) -> Path:
    """Создаёт парсер через фабрику, запускает его и сохраняет результат."""
    parser = create_parser(site)

    success, result = parser.parse(config)

    if not success or result is None:
        logger.error(
            "Error %s: not success: %s, result is None: %s",
            site,
            not success,
            result is None,
        )
        raise SystemExit(1)

    path = _save_result(f"{site}_result.json", result, output_dir)

    logger.info("Результат %s сохранён в %s (%d записей)", site, path, len(result))

    return path


def DoCian(output_dir: str | Path = ".") -> Path:
    """Совместимая обёртка запуска парсера Cian."""
    return _run_parser("cian", cianConfig, output_dir)


def DoAvito(output_dir: str | Path = ".") -> Path:
    """Совместимая обёртка запуска парсера Avito."""
    return _run_parser("avito", avitoCofig, output_dir)


def DoYandex(output_dir: str | Path = ".") -> Path:
    """Запуск парсера Яндекс Недвижимости."""
    return _run_parser("yandex", yandexConfig, output_dir)


def _build_parser() -> argparse.ArgumentParser:
    """Создаёт CLI-парсер аргументов запуска."""
    parser = argparse.ArgumentParser(
        description="Парсеры объявлений недвижимости (Avito, Cian, Yandex)",
    )
    parser.add_argument(
        "--site",
        choices=[*available_sites(), "all"],
        default="yandex",
        help="источник данных (по умолчанию yandex)",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=None,
        help="переопределить max_page_iteration",
    )
    parser.add_argument(
        "--min-delay",
        type=float,
        default=None,
        help="минимальная пауза между запросами, секунды",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=None,
        help="максимальная пауза между запросами, секунды",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="каталог для файлов <site>_result.json",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="запустить браузер без окна",
    )

    return parser


def _config_with_overrides(
    config: ParserConfig,
    args: argparse.Namespace,
) -> ParserConfig:
    """Возвращает копию конфигурации с учётом аргументов командной строки."""
    changes: dict[str, Any] = {}

    if args.pages is not None:
        changes["max_page_iteration"] = max(1, args.pages)

    if args.min_delay is not None:
        changes["min_iteration_time_span"] = max(0.0, args.min_delay)

    if args.max_delay is not None:
        changes["max_iteration_time_span"] = max(0.0, args.max_delay)

    if args.headless:
        changes["headless"] = True

    return replace(config, **changes) if changes else config


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    args = _build_parser().parse_args(argv)

    sites = available_sites() if args.site == "all" else [args.site]

    for site in sites:
        config = _config_with_overrides(PARSER_CONFIGS[site], args)
        _run_parser(site, config, args.output_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
