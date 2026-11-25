from __future__ import annotations

"""Конфигурация подключения к PostgreSQL.

Порядок поиска .env:
  1. --env-file (аргумент CLI)
  2. parsers/.env
  3. корень проекта ../.env
  4. переменные окружения

Переменные:
  DB_HOST, DB_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
  fallback: DB_NAME / DB_USER / DB_PASSWORD

Результат: DSN postgresql://user:password@host:port/db
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _mask_password(dsn: str) -> str:
    """Заменить пароль на *** в строке DSN."""
    return dsn.replace(os.getenv("POSTGRES_PASSWORD", "password"), "***", 1)


def _load_env_file(path: Path) -> None:
    """Загрузить переменные из .env файла."""
    if not path.is_file():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and value and key not in os.environ:
                os.environ[key] = value
    logger.info("Loaded .env from: %s", path)


def get_env_path() -> Path:
    """Определить путь к .env файлу."""
    parsers_env = Path("parsers") / ".env"
    if parsers_env.is_file():
        return parsers_env
    project_env = Path("..") / ".env"
    abs_project = project_env.resolve()
    if abs_project.is_file():
        return abs_project
    current_env = Path(".env")
    if current_env.is_file():
        return current_env
    return Path("")


def get_dsn() -> str:
    """Собрать DSN из переменных окружения / .env."""
    env_path = get_env_path()
    if env_path:
        _load_env_file(env_path)

    required = {
        "DB_HOST": os.getenv("DB_HOST") or os.getenv("DB_NAME"),
        "DB_PORT": os.getenv("DB_PORT") or os.getenv("DB_USER"),
        "POSTGRES_DB": os.getenv("POSTGRES_DB") or os.getenv("DB_PASSWORD"),
        "POSTGRES_USER": os.getenv("POSTGRES_USER") or os.getenv("DB_USER"),
        "POSTGRES_PASSWORD": os.getenv("POSTGRES_PASSWORD") or os.getenv("DB_PASSWORD"),
    }

    missing = [k for k, v in required.items() if not v]
    if missing:
        raise ValueError(
            f"Обязательные переменные не заданы: {', '.join(missing)}. "
            "Проверьте .env файл или переменные окружения."
        )

    host = required["DB_HOST"]
    port = required["DB_PORT"] or "5432"
    db = required["POSTGRES_DB"]
    user = required["POSTGRES_USER"]
    password = required["POSTGRES_PASSWORD"]

    dsn = f"postgresql://{user}:{password}@{host}:{port}/{db}"
    logger.debug("DSN assembled: %s", _mask_password(dsn))
    return dsn


def get_connection_params() -> dict:
    """Вернуть параметры подключения как словарь для psycopg."""
    return {
        "host": os.getenv("DB_HOST") or os.getenv("DB_NAME"),
        "port": int(os.getenv("DB_PORT") or os.getenv("DB_USER") or "5432"),
        "dbname": os.getenv("POSTGRES_DB") or os.getenv("DB_PASSWORD"),
        "user": os.getenv("POSTGRES_USER") or os.getenv("DB_USER"),
        "password": os.getenv("POSTGRES_PASSWORD") or os.getenv("DB_PASSWORD"),
    }