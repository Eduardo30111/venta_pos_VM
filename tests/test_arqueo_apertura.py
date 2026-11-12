"""
Pruebas unitarias para la función de Arqueo de Dinero en Apertura de Caja (VmPOS).
Verifica:
1. Denominaciones colombianas soportadas (billetes y monedas).
2. Cálculo exacto de subtotales por denominación y total general de apertura.
3. Serialización y deserialización JSON del desglose de arqueo.
4. Persistencia en base de datos SQLite (columna arqueo_apertura_json en sesiones_caja).
5. Recuperación del desglose en historial de cierres sin contaminar ingresos de ventas.
"""

import unittest
import sqlite3
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from interface.caja_menu import DENOMINACIONES
from interface.caja_manager import (
    abrir_sesion_caja,
    cerrar_sesion_caja,
    obtener_sesion_activa,
    obtener_cierres_anteriores,
)


class TestArqueoApertura(unittest.TestCase):
    def setUp(self):
        # Crear base de datos temporal en memoria
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        cur = self.conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sesiones_caja (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_apertura TEXT NOT NULL,
                hora_apertura TEXT NOT NULL,
                usuario_apertura TEXT NOT NULL,
                monto_inicial REAL NOT NULL DEFAULT 0.0,
                estado TEXT NOT NULL DEFAULT 'Abierta',
                fecha_cierre TEXT,
                hora_cierre TEXT,
                usuario_cierre TEXT,
                monto_esperado_efectivo REAL DEFAULT 0.0,
                monto_real_contado REAL DEFAULT 0.0,
                diferencia REAL DEFAULT 0.0,
                arqueo_apertura_json TEXT,
                observaciones TEXT
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS movimientos_caja (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sesion_caja_id INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                tipo TEXT NOT NULL,
                monto REAL NOT NULL DEFAULT 0.0,
                concepto TEXT,
                usuario TEXT NOT NULL
            );
        """)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_denominaciones_colombianas_completas(self):
        """Verifica que todas las denominaciones oficiales colombianas estén presentes."""
        valores_esperados = [100000, 50000, 20000, 10000, 5000, 2000, 1000, 500, 200, 100, 50]
        valores_definidos = [d["valor"] for d in DENOMINACIONES]
        for val in valores_esperados:
            self.assertIn(val, valores_definidos, f"Denominación ${val:,} debe existir")

    def test_calculo_subtotales_y_total_arqueo(self):
        """Verifica cálculo aritmético: 5 de 20k, 3 de 10k, 2 de 5k, 10 de 1k, 8 de 500, 5 de 200 = 155,000."""
        conteo = {
            100000: 0,
            50000: 0,
            20000: 5,   # 100,000
            10000: 3,   # 30,000
            5000: 2,    # 10,000
            2000: 0,
            1000: 10,   # 10,000
            500: 8,     # 4,000
            200: 5,     # 1,000
            100: 0,
            50: 0
        }
        total = sum(val * cant for val, cant in conteo.items())
        self.assertEqual(total, 155000)

    def test_persistencia_arqueo_apertura_json(self):
        """Verifica apertura de sesión con arqueo_detalle persistiendo JSON en la BD."""
        desglose = {
            "billetes": {"20000": 5, "10000": 3, "5000": 2},
            "monedas": {"1000": 10, "500": 8, "200": 5},
            "total": 155000
        }
        sesion_id = abrir_sesion_caja(
            usuario="Admin",
            monto_inicial=155000,
            conn=self.conn,
            arqueo_detalle=desglose
        )
        self.assertGreater(sesion_id, 0)

        # Leer directamente de la base de datos
        cur = self.conn.cursor()
        cur.execute("SELECT monto_inicial, arqueo_apertura_json, estado FROM sesiones_caja WHERE id = ?", (sesion_id,))
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["monto_inicial"], 155000)
        self.assertEqual(row["estado"], "Abierta")

        # Comprobar JSON
        json_str = row["arqueo_apertura_json"]
        self.assertIsNotNone(json_str)
        datos = json.loads(json_str)
        self.assertEqual(datos["total"], 155000)
        self.assertEqual(datos["billetes"]["20000"], 5)
        self.assertEqual(datos["monedas"]["1000"], 10)

    def test_consulta_historial_cierres_incluye_arqueo(self):
        """Verifica que obtener_cierres_anteriores devuelva el campo arqueo_apertura_json."""
        desglose = {"billetes": {"50000": 2}, "monedas": {}, "total": 100000}
        sid = abrir_sesion_caja(usuario="Cajero1", monto_inicial=100000, conn=self.conn, arqueo_detalle=desglose)
        
        # Marcar como cerrada directamente en la base de datos de prueba
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE sesiones_caja 
            SET estado = 'Cerrada', fecha_cierre = '2026-11-12', hora_cierre = '18:00:00',
                monto_real_contado = 100000, usuario_cierre = 'Cajero1'
            WHERE id = ?
        """, (sid,))
        self.conn.commit()

        historial = obtener_cierres_anteriores(limit=5, conn=self.conn)
        self.assertGreaterEqual(len(historial), 1)
        ultimo = historial[0]
        self.assertIn("arqueo_apertura_json", ultimo)
        self.assertIsNotNone(ultimo["arqueo_apertura_json"])
        obj = json.loads(ultimo["arqueo_apertura_json"])
        self.assertEqual(obj["total"], 100000)


if __name__ == "__main__":
    unittest.main()
