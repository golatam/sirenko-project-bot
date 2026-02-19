"""Управление подключением к SQLite и миграциями."""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Database:
    """Асинхронная обёртка над aiosqlite с поддержкой миграций."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Открыть соединение и применить миграции."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._run_migrations()
        logger.info("БД подключена: %s", self.db_path)

    async def close(self) -> None:
        """Закрыть соединение."""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("БД закрыта")

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("БД не подключена. Вызовите connect() сначала.")
        return self._db

    async def _run_migrations(self) -> None:
        """Применить SQL-миграции из папки migrations/ по порядку."""
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        cursor = await self.db.execute("SELECT MAX(version) FROM schema_version")
        row = await cursor.fetchone()
        current_version = row[0] if row[0] is not None else 0

        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        for migration_file in migration_files:
            version = int(migration_file.stem.split("_")[0])
            if version <= current_version:
                continue
            logger.info("Применяю миграцию %s", migration_file.name)
            sql = migration_file.read_text()
            await self.db.executescript(sql)
            await self.db.execute(
                "INSERT OR REPLACE INTO schema_version (version) VALUES (?)", (version,)
            )
            await self.db.commit()

        logger.info("Миграции применены, версия схемы: %d", current_version)

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        return await self.db.execute(sql, params)

    async def executemany(self, sql: str, params_list: list[tuple]) -> aiosqlite.Cursor:
        return await self.db.executemany(sql, params_list)

    async def fetchone(self, sql: str, params: tuple = ()) -> aiosqlite.Row | None:
        cursor = await self.db.execute(sql, params)
        return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        cursor = await self.db.execute(sql, params)
        return await cursor.fetchall()

    async def commit(self) -> None:
        await self.db.commit()
