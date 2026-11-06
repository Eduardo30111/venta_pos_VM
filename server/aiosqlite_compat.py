#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: server/aiosqlite_compat.py
Provee compatibilidad nativa con el dialecto `sqlite+aiosqlite` de SQLAlchemy
usando la librería estándar `sqlite3` y un hilo trabajador dedicado cuando
el paquete externo `aiosqlite` no está instalado en el entorno.
"""

import sys
import queue
import sqlite3
import asyncio
import threading
import types
from functools import partial


def asegurar_aiosqlite():
    try:
        import aiosqlite  # noqa: F401
        return
    except ImportError:
        pass

    mod = types.ModuleType("aiosqlite")
    for attr in (
        "DatabaseError",
        "Error",
        "IntegrityError",
        "NotSupportedError",
        "OperationalError",
        "ProgrammingError",
        "sqlite_version",
        "sqlite_version_info",
        "Row",
    ):
        setattr(mod, attr, getattr(sqlite3, attr, None))

    class _CompatCursor:
        def __init__(self, conn_wrapper, raw_cursor):
            self._conn = conn_wrapper
            self._cursor = raw_cursor

        @property
        def description(self):
            return self._cursor.description

        @property
        def lastrowid(self):
            return self._cursor.lastrowid

        @property
        def rowcount(self):
            return self._cursor.rowcount

        async def execute(self, sql, parameters=None):
            if parameters is None:
                await self._conn._execute_in_thread(self._cursor.execute, sql)
            else:
                await self._conn._execute_in_thread(self._cursor.execute, sql, parameters)
            return self

        async def executemany(self, sql, seq_of_parameters):
            await self._conn._execute_in_thread(self._cursor.executemany, sql, seq_of_parameters)
            return self

        async def fetchall(self):
            return await self._conn._execute_in_thread(self._cursor.fetchall)

        async def fetchone(self):
            return await self._conn._execute_in_thread(self._cursor.fetchone)

        async def fetchmany(self, size=None):
            if size is None:
                return await self._conn._execute_in_thread(self._cursor.fetchmany)
            return await self._conn._execute_in_thread(self._cursor.fetchmany, size)

        async def close(self):
            await self._conn._execute_in_thread(self._cursor.close)

    class _CompatConnection:
        def __init__(self, connector):
            self._connector = connector
            self._conn = None
            self._tx = queue.Queue()
            self._thread = None
            self._running = True
            self.daemon = True

        def _worker(self):
            while self._running:
                item = self._tx.get()
                if item is None:
                    break
                future, func = item
                try:
                    result = func()
                    if not future.cancelled():
                        future.get_loop().call_soon_threadsafe(future.set_result, result)
                except BaseException as exc:
                    if not future.cancelled():
                        future.get_loop().call_soon_threadsafe(future.set_exception, exc)

        async def _execute_in_thread(self, fn, *args, **kwargs):
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            self._tx.put_nowait((fut, partial(fn, *args, **kwargs)))
            return await fut

        async def _connect(self):
            if self._thread is None:
                self._thread = threading.Thread(target=self._worker, daemon=True)
                self._thread.start()
            self._conn = await self._execute_in_thread(self._connector)
            return self

        def __await__(self):
            return self._connect().__await__()

        @property
        def isolation_level(self):
            return self._conn.isolation_level if self._conn else None

        @isolation_level.setter
        def isolation_level(self, val):
            if self._conn is not None:
                self._conn.isolation_level = val

        async def cursor(self):
            raw_cur = await self._execute_in_thread(self._conn.cursor)
            return _CompatCursor(self, raw_cur)

        async def execute(self, sql, parameters=None):
            cur = await self.cursor()
            await cur.execute(sql, parameters)
            return cur

        async def commit(self):
            await self._execute_in_thread(self._conn.commit)

        async def rollback(self):
            await self._execute_in_thread(self._conn.rollback)

        async def create_function(self, *args, **kwargs):
            await self._execute_in_thread(self._conn.create_function, *args, **kwargs)

        async def close(self):
            if not self._running:
                return
            try:
                if self._conn is not None:
                    await self._execute_in_thread(self._conn.close)
            finally:
                self._running = False
                self._tx.put_nowait(None)

    def connect(database, **kwargs):
        kwargs.setdefault("check_same_thread", False)
        return _CompatConnection(lambda: sqlite3.connect(database, **kwargs))

    mod.connect = connect
    sys.modules["aiosqlite"] = mod
