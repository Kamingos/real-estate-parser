#!/usr/bin/env python3
"""CLI для загрузки JSON-объявлений в PostgreSQL.

Аргументы:
  --file PATH       JSON-файлы для загрузки (можно несколько)
  --site avito|cian|yandex  Фильтр по сайту
  --limit N         Максимум объявлений для загрузки
  --dry-run         Выполнить всё, но сделать ROLLBACK в конце
  --skip-errors     Не прерываться на ошибках, логировать и продолжать
  --env-file PATH   Путь к .env файлу
  --verbose         Подробный лог

По умолчанию файлы: parsers/avito_result.json, cian_result.json, yandex_result.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import psycopg

from db.config import get_dsn
from db.loader import load_offer
from db.repositories import MemoryCache, _load_cache

logger = logging.getLogger(__name__)

DEFAULT_FILES = [
    "avito_result.json",
    "cian_result.json",
    "yandex_result.json",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JSON -> PostgreSQL loader (3НФ схема)")
    parser.add_argument(
        "--file", nargs="+", default=[],
        help="JSON-файлы для загрузки",
    )
    parser.add_argument(
        "--site", choices=["avito", "cian", "yandex"],
        help="Фильтр по сайту",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Максимум объявлений (0 = все)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Выполнить всё, но сделать ROLLBACK в конце",
    )
    parser.add_argument(
        "--skip-errors", action="store_true",
        help="Не прерываться на ошибках",
    )
    parser.add_argument(
        "--env-file", type=str, default=None,
        help="Путь к .env файлу",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Подробный лог",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.env_file:
        env_path = Path(args.env_file)
        if env_path.is_file():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("\"'")
                    if key and value and key not in os.environ:
                        os.environ[key] = value

    files = args.file if args.file else DEFAULT_FILES
    resolved_files = []
    for f in files:
        p = Path(f)
        if not p.is_absolute():
            candidate = Path(__file__).parent / f
            if candidate.is_file():
                p = candidate
        if p.is_file():
            resolved_files.append(p)
        else:
            logger.warning("Файл не найден: %s", f)

    if not resolved_files:
        logger.error("Файлы для загрузки не найдены: %s", resolved_files)
        sys.exit(1)

    try:
        dsn = get_dsn()
    except ValueError as e:
        logger.error("Ошибка конфигурации: %s", e)
        sys.exit(1)

    cache = MemoryCache()
    total_stats: dict[str, int] = {
        "inserted": 0, "updated": 0, "skipped": 0, "errors": 0,
    }
    count = 0
    is_dry_run = args.dry_run

    try:
        conn = psycopg.connect(dsn, autocommit=False)
    except psycopg.OperationalError as e:
        logger.error("Не удалось подключиться к БД: %s", e)
        sys.exit(1)

    stop = False

    try:
        _load_cache(conn, cache)

        for filepath in resolved_files:
            if stop:
                break
            logger.info("Читаю файл: %s", filepath)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except json.JSONDecodeError as e:
                logger.error("Ошибка парсинга JSON: %s", e)
                continue

            if not isinstance(data, list):
                logger.error("Ожидается массив JSON, получено: %s", type(data))
                continue

            for item in data:
                if not isinstance(item, dict):
                    continue

                if args.site:
                    site_code = item.get("site", "")
                    site_url = item.get("url", "")
                    from db.normalize import normalize_site
                    if normalize_site(site_code, site_url) != args.site:
                        continue

                if args.limit and count >= args.limit:
                    logger.info("Достигнут лимит: %d", args.limit)
                    stop = True
                    break

                count += 1

                try:
                    # psycopg при autocommit=False сам открывает транзакцию
                    stats = load_offer(conn, item, cache, dry_run=is_dry_run)
                    for k, v in stats.items():
                        total_stats[k] = total_stats.get(k, 0) + v
                    if is_dry_run:
                        conn.rollback()
                        logger.debug("Rollback для объявления #%d", count)
                    else:
                        conn.commit()
                except Exception as e:
                    logger.error("Ошибка при загрузке объявления #%d: %s", count, e)
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    total_stats["errors"] += 1
                    if not args.skip_errors:
                        logger.error("Прерываю выполнение (--skip-errors не указан)")
                        stop = True
                        break

        logger.info("=" * 60)
        logger.info("ИТОГОВАЯ СТАТИСТИКА:")
        logger.info("  Обработано объявлений: %d", count)
        logger.info("  Вставлено: %d", total_stats.get("inserted", 0))
        logger.info("  Обновлено: %d", total_stats.get("updated", 0))
        logger.info("  Ошибки: %d", total_stats.get("errors", 0))
        logger.info("=" * 60)

        if is_dry_run:
            logger.info("DRY RUN: все изменения откатаны (ROLLBACK)")

    except Exception as e:
        logger.error("Критическая ошибка: %s", e)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()