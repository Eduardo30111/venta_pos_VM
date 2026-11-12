#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_fix_venta_arqueo_column.py
Verifica la migración y auto-recuperación de la columna `arqueo_apertura_json` y `created_at`
en `sesiones_caja` para que no bloquee ni falle el registro de ventas en el Servidor Central.
"""

import unittest
import sqlite3
import tempfile
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from server.database import _migrar_archivo_sqlite_directo
except ImportError:
    _migrar_archivo_sqlite_directo = None


class TestFixVentaArqueoColumn(unittest.TestCase):

    def setUp(self):
        if _migrar_archivo_sqlite_directo is None:
            self.skipTest("SQLAlchemy no disponible en este entorno de pruebas.")
        self.temp_dir = tempfile.mkdtemp(prefix="vmpos_test_col_")
        self.db_path = os.path.join(self.temp_dir, "test_server.db")

        # Simular una base de datos antigua donde sesiones_caja NO tiene arqueo_apertura_json
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE sesiones_caja (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_apertura TEXT NOT NULL,
                hora_apertura TEXT NOT NULL,
                usuario_apertura TEXT NOT NULL,
                monto_inicial REAL DEFAULT 0.0,
                estado TEXT DEFAULT 'Abierta'
            );
        """)
        cur.execute("""
            CREATE TABLE proveedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL
            );
        """)
        cur.execute("""
            INSERT INTO sesiones_caja (fecha_apertura, hora_apertura, usuario_apertura, estado)
            VALUES ('2026-11-12', '14:00:00', 'Admin', 'Abierta');
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            os.rmdir(self.temp_dir)
        except Exception:
            pass

    def test_migracion_directa_agrega_columnas_faltantes(self):
        """Verifica que _migrar_archivo_sqlite_directo agregue arqueo_apertura_json y demás campos necesarios."""
        url = f"sqlite+aiosqlite:///{self.db_path}"
        _migrar_archivo_sqlite_directo(url)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(sesiones_caja)")
        cols_caja = [r[1] for r in cur.fetchall()]

        self.assertIn("arqueo_apertura_json", cols_caja, "Debe existir arqueo_apertura_json en sesiones_caja")
        self.assertIn("created_at", cols_caja, "Debe existir created_at en sesiones_caja")
        self.assertIn("monto_transferencias_esperado", cols_caja)
        self.assertIn("diferencia_banco", cols_caja)

        cur.execute("PRAGMA table_info(proveedores)")
        cols_prov = [r[1] for r in cur.fetchall()]
        self.assertIn("documento_nit", cols_prov, "Debe existir documento_nit en proveedores")
        self.assertIn("estado", cols_prov, "Debe existir estado en proveedores")
        conn.close()


if __name__ == "__main__":
    unittest.main()
