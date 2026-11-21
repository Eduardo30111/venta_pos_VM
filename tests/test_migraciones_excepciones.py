#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pruebas de verificación para control de excepciones en migraciones de base de datos:
- Comprobación de que errores benignos (duplicate column / already exists) no interrumpen la ejecución.
- Comprobación de que errores críticos (sintaxis corrupta, tablas inexistentes o fallos fatales)
  lanzan excepciones controladas en lugar de ser silenciados con simples advertencias.
"""

import unittest
import os
import tempfile
import sqlite3

from interface.database_manager import _safe_alter_column, _safe_update
from server.database import _is_benign_ddl_error, MigrationError


class TestMigracionesExcepciones(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_file.close()
        self.conn = sqlite3.connect(self.temp_file.name)
        self.cur = self.conn.cursor()
        self.cur.execute("CREATE TABLE test_tabla (id INTEGER PRIMARY KEY, valor TEXT)")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)

    def test_01_benign_ddl_column_duplicate(self):
        """Verifica que añadir una columna existente sea benigno y se tolere."""
        # Agregar columna por primera vez
        _safe_alter_column(self.cur, "ALTER TABLE test_tabla ADD COLUMN nueva_col TEXT DEFAULT ''", "test_col")
        self.conn.commit()

        # Intentar agregarla de nuevo: no debe lanzar excepción
        try:
            _safe_alter_column(self.cur, "ALTER TABLE test_tabla ADD COLUMN nueva_col TEXT DEFAULT ''", "test_col")
        except Exception as e:
            self.fail(f"_safe_alter_column falló con error benigno de columna duplicada: {e}")

    def test_02_fatal_ddl_syntax_error(self):
        """Verifica que un error de sintaxis o tabla inválida en DDL lance RuntimeError fatal."""
        with self.assertRaises(RuntimeError):
            _safe_alter_column(self.cur, "ALTER TABLE tabla_inexistente ADD COLUMN col TEXT", "test_fatal")

    def test_03_fatal_update_error(self):
        """Verifica que un UPDATE sobre tabla inexistente lance RuntimeError fatal."""
        with self.assertRaises(RuntimeError):
            _safe_update(self.cur, "UPDATE tabla_que_no_existe SET x = 1", "test_update_fatal")

    def test_04_server_migration_error_helper(self):
        """Verifica la clasificación de errores DDL en el motor del servidor."""
        err_benigno = sqlite3.OperationalError("duplicate column name: idempotency_key")
        self.assertTrue(_is_benign_ddl_error(err_benigno))

        err_fatal = sqlite3.OperationalError("near 'INVALID_SQL': syntax error")
        self.assertFalse(_is_benign_ddl_error(err_fatal))


if __name__ == "__main__":
    unittest.main()
