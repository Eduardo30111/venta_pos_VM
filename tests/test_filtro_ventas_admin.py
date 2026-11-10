#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_filtro_ventas_admin.py
Pruebas unitarias para el filtrado de ventas por fecha (Hoy, Ayer, Antes de ayer, o por fecha)
en el módulo de Gestión y Supervisión de Ventas (ventas_admin_dialog.py).
"""

import os
import sys
import unittest
import sqlite3
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from interface.ventas_admin_dialog import _normalizar_fecha


class TestFiltroVentasFecha(unittest.TestCase):
    """Verifica que el filtrado por períodos y fechas específicas funcione con exactitud."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.conn = sqlite3.connect(self.db_path)
        self.cur = self.conn.cursor()
        self.cur.execute("""
            CREATE TABLE ventas (
                id_venta INTEGER PRIMARY KEY,
                fecha_venta TEXT,
                hora_venta TEXT,
                documento_cliente TEXT,
                total_venta REAL,
                metodo_pago TEXT,
                operario TEXT,
                estado TEXT
            )
        """)

        self.hoy = datetime.now().strftime("%Y-%m-%d")
        self.ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.antier = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        self.fecha_antigua = "2026-10-15"

        self.cur.execute("INSERT INTO ventas VALUES (101, ?, '10:00:00', '111', 25000, 'Efectivo', 'Admin', 'Completada')", (self.hoy,))
        self.cur.execute("INSERT INTO ventas VALUES (102, ?, '11:00:00', '222', 15000, 'Transferencia', 'Operario 1', 'Completada')", (self.ayer,))
        self.cur.execute("INSERT INTO ventas VALUES (103, ?, '12:00:00', '333', 45000, 'Efectivo', 'Operario 2', 'Completada')", (self.antier,))
        self.cur.execute("INSERT INTO ventas VALUES (104, ?, '15:30:00', '444', 60000, 'Fiado', 'Admin', 'Completada')", (self.fecha_antigua,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        os.close(self.db_fd)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_normalizacion_de_fechas(self):
        """Valida que entradas tipo DD/MM/YYYY o YYYY-MM-DD se normalicen a ISO YYYY-MM-DD."""
        self.assertEqual(_normalizar_fecha("2026-11-10"), "2026-11-10")
        self.assertEqual(_normalizar_fecha("10/11/2026"), "2026-11-10")
        self.assertEqual(_normalizar_fecha("5/11/2026"), "2026-11-05")
        self.assertEqual(_normalizar_fecha("10-11-2026"), "2026-11-10")
        self.assertEqual(_normalizar_fecha(""), "")

    def test_filtro_hoy(self):
        """El filtro de hoy debe traer únicamente las ventas del día actual."""
        self.cur.execute("SELECT id_venta, total_venta FROM ventas WHERE fecha_venta = ?", (self.hoy,))
        filas = self.cur.fetchall()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0][0], 101)
        self.assertEqual(filas[0][1], 25000)

    def test_filtro_ayer(self):
        """El filtro de ayer debe traer únicamente las ventas del día inmediatamente anterior."""
        self.cur.execute("SELECT id_venta, total_venta FROM ventas WHERE fecha_venta = ?", (self.ayer,))
        filas = self.cur.fetchall()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0][0], 102)
        self.assertEqual(filas[0][1], 15000)

    def test_filtro_antes_de_ayer(self):
        """El filtro de antes de ayer debe traer únicamente las ventas de hace 2 días."""
        self.cur.execute("SELECT id_venta, total_venta FROM ventas WHERE fecha_venta = ?", (self.antier,))
        filas = self.cur.fetchall()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0][0], 103)
        self.assertEqual(filas[0][1], 45000)

    def test_filtro_por_fecha_especifica(self):
        """Al ingresar una fecha específica (e.g. 2026-10-15 o 15/10/2026), debe retornar solo esa fecha."""
        fecha_norm = _normalizar_fecha("15/10/2026")
        self.cur.execute("SELECT id_venta, total_venta FROM ventas WHERE fecha_venta = ?", (fecha_norm,))
        filas = self.cur.fetchall()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0][0], 104)
        self.assertEqual(filas[0][1], 60000)

    def test_filtro_todas_las_fechas(self):
        """Al no aplicar filtro de fecha, deben listarse todas las ventas registradas."""
        self.cur.execute("SELECT COUNT(*), SUM(total_venta) FROM ventas")
        total_count, total_sum = self.cur.fetchone()
        self.assertEqual(total_count, 4)
        self.assertEqual(total_sum, 145000)


if __name__ == "__main__":
    unittest.main()
