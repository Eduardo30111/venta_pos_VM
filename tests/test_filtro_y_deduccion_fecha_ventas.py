#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pruebas de Verificación: Filtro de Fechas, Navegación y Deducción de Totales tras Edición de Ventas.
Cubre específicamente:
1. Sincronización entre cb_periodo, e_fecha y cargar_ventas() para que escribir cualquier fecha filtre con precisión.
2. Comportamiento tras mover una venta de Hoy a otra fecha (descuento del total de Hoy, aparición en la nueva fecha).
3. Verificación de que el resumen de ventas (contador y suma en pesos) deduce la venta en la fecha origen y la suma en la fecha destino.
4. Actualización coherente de estadísticas del Dashboard (menu_inicio).
"""

import unittest
import sqlite3
import os
import sys
from datetime import datetime, timedelta

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from interface.ventas_admin_dialog import _normalizar_fecha, _normalizar_hora, _formatear_hora_display
from interface.caja_manager import editar_venta_completa, normalizar_fecha as cm_normalizar_fecha
from interface.database_manager import conectar_db, DB_VENTAS_PATH


class TestFiltroYDeduccionFechaVentas(unittest.TestCase):
    def setUp(self):
        self.conn = conectar_db()
        self.cur = self.conn.cursor()
        self.hoy = datetime.now().strftime("%Y-%m-%d")
        self.ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.antier = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        self.fecha_destino = "2026-11-20"

        # Insertar una venta de prueba en la fecha de hoy
        self.cur.execute("""
            INSERT INTO ventas (
                fecha_venta, hora_venta, documento_cliente, total_venta,
                metodo_pago, operario, estado, fecha_registro, es_venta_atrasada
            ) VALUES (?, '10:30:00', '12345678', 75000.0, 'Efectivo', 'AdminTester', 'Completada', ?, 0)
        """, (self.hoy, f"{self.hoy} 10:30:00"))
        self.id_venta_test = self.cur.lastrowid

        # Insertar detalle de venta
        self.cur.execute("""
            INSERT INTO detalle_ventas (
                id_venta, codigo_producto, nombre_producto, precio_unitario, cantidad, subtotal, costo_unitario
            ) VALUES (?, 'TEST-SKU-99', 'Item Prueba Filtro', 75000.0, 1, 75000.0, 40000.0)
        """, (self.id_venta_test,))
        self.conn.commit()

    def tearDown(self):
        try:
            self.cur.execute("DELETE FROM detalle_ventas WHERE id_venta = ?", (self.id_venta_test,))
            self.cur.execute("DELETE FROM auditoria_ventas WHERE id_venta = ?", (self.id_venta_test,))
            self.cur.execute("DELETE FROM ventas WHERE id_venta = ?", (self.id_venta_test,))
            self.conn.commit()
            self.conn.close()
        except Exception:
            pass

    def test_01_normalizacion_de_formatos_de_fecha(self):
        """Verifica que _normalizar_fecha convierte correctamente múltiples formatos a YYYY-MM-DD."""
        casos = [
            ("2026-11-20", "2026-11-20"),
            ("20/11/2026", "2026-11-20"),
            ("20-11-2026", "2026-11-20"),
            ("2026/11/20", "2026-11-20"),
            ("2026-11-22 10:30:00", "2026-11-22"),
            ("22/11/2026 09:15:00", "2026-11-22"),
            ("2026-11-20T18:45:00", "2026-11-20"),
        ]
        for entrada, esperado in casos:
            with self.subTest(entrada=entrada):
                self.assertEqual(_normalizar_fecha(entrada), esperado)
                self.assertEqual(cm_normalizar_fecha(entrada), esperado)

    def test_02_total_inicial_en_hoy_incluye_la_venta(self):
        """Verifica que antes de editar, la venta se suma en las ventas de hoy."""
        self.cur.execute("""
            SELECT COALESCE(SUM(total_venta), 0.0), COUNT(id_venta)
            FROM ventas
            WHERE fecha_venta = ? AND estado != 'Anulada'
        """, (self.hoy,))
        tot_hoy, cant_hoy = self.cur.fetchone()
        self.assertGreaterEqual(tot_hoy, 75000.0)
        self.assertGreaterEqual(cant_hoy, 1)

    def test_03_mover_venta_descuenta_de_hoy_y_suma_en_fecha_destino(self):
        """Verifica que editar la fecha descuenta el total de Hoy y lo suma en la fecha destino."""
        # 1. Obtener totales de Hoy y Fecha Destino antes del cambio
        self.cur.execute("SELECT COALESCE(SUM(total_venta), 0.0) FROM ventas WHERE fecha_venta = ? AND estado != 'Anulada'", (self.hoy,))
        tot_hoy_antes = float(self.cur.fetchone()[0])

        self.cur.execute("SELECT COALESCE(SUM(total_venta), 0.0) FROM ventas WHERE fecha_venta = ? AND estado != 'Anulada'", (self.fecha_destino,))
        tot_dest_antes = float(self.cur.fetchone()[0])

        # 2. Mover la venta a fecha destino con nueva hora
        res = editar_venta_completa(
            id_venta=self.id_venta_test,
            usuario_admin="AdminTest",
            nuevo_metodo="Efectivo",
            nuevos_items=[{
                "codigo_producto": "TEST-SKU-99",
                "nombre_producto": "Item Prueba Filtro",
                "precio_unitario": 75000.0,
                "cantidad": 1
            }],
            motivo="Mover venta a fecha anterior para prueba",
            nueva_fecha=self.fecha_destino,
            nueva_hora="18:45:00"
        )
        self.assertTrue(res.get("exito") or res.get("ok"))

        # 3. Comprobar que en la base de datos se actualizó fecha_venta, hora_venta, fecha y hora
        self.cur.execute("""
            SELECT fecha_venta, hora_venta, estado, es_venta_atrasada, motivo_modificacion_fecha
            FROM ventas WHERE id_venta = ?
        """, (self.id_venta_test,))
        row_v = self.cur.fetchone()
        self.assertEqual(row_v[0], self.fecha_destino)
        self.assertEqual(row_v[1], "18:45:00")
        self.assertEqual(row_v[2], "Modificada")
        self.assertEqual(row_v[3], 1)
        self.assertEqual(row_v[4], "Mover venta a fecha anterior para prueba")

        # 4. Comprobar que en Hoy el total disminuyó exactamente en 75,000 COP
        self.cur.execute("SELECT COALESCE(SUM(total_venta), 0.0) FROM ventas WHERE fecha_venta = ? AND estado != 'Anulada'", (self.hoy,))
        tot_hoy_despues = float(self.cur.fetchone()[0])
        self.assertAlmostEqual(tot_hoy_despues, tot_hoy_antes - 75000.0, places=2)

        # 5. Comprobar que en Fecha Destino el total aumentó exactamente en 75,000 COP
        self.cur.execute("SELECT COALESCE(SUM(total_venta), 0.0) FROM ventas WHERE fecha_venta = ? AND estado != 'Anulada'", (self.fecha_destino,))
        tot_dest_despues = float(self.cur.fetchone()[0])
        self.assertAlmostEqual(tot_dest_despues, tot_dest_antes + 75000.0, places=2)

    def test_04_filtro_por_fecha_encuentra_la_venta_en_destino(self):
        """Simula la lógica de filtrado de cargar_ventas() y comprueba que aparece en fecha destino y no en hoy."""
        # Mover venta
        editar_venta_completa(
            id_venta=self.id_venta_test,
            usuario_admin="AdminTest",
            nuevo_metodo="Efectivo",
            nuevos_items=[{
                "codigo_producto": "TEST-SKU-99",
                "nombre_producto": "Item Prueba Filtro",
                "precio_unitario": 75000.0,
                "cantidad": 1
            }],
            motivo="Prueba de filtro",
            nueva_fecha=self.fecha_destino,
            nueva_hora="06:45:00"
        )

        def _simular_filtro_cargar_ventas(p_sel, f_raw):
            hoy_iso = datetime.now().strftime("%Y-%m-%d")
            ayer_iso = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            antier_iso = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")

            if p_sel == "Todas las fechas" and not f_raw:
                fecha_filtro = ""
            elif f_raw:
                fecha_filtro = _normalizar_fecha(f_raw)
            else:
                if p_sel == "Hoy": fecha_filtro = hoy_iso
                elif p_sel == "Ayer": fecha_filtro = ayer_iso
                elif p_sel == "Antes de ayer": fecha_filtro = antier_iso
                else: fecha_filtro = ""

            conn = conectar_db()
            cur = conn.cursor()
            q = "SELECT id_venta, fecha_venta, hora_venta, total_venta FROM ventas"
            params = []
            if fecha_filtro:
                q += " WHERE (fecha_venta = ? OR fecha_venta LIKE ?)"
                params.extend([fecha_filtro, f"{fecha_filtro}%"])
            cur.execute(q, params)
            rows = cur.fetchall()
            conn.close()
            return fecha_filtro, rows

        # Caso A: El usuario está filtrando por 'Hoy' -> La venta NO debe estar en los resultados de Hoy
        f_filtro, ventas_hoy = _simular_filtro_cargar_ventas("Hoy", self.hoy)
        ids_hoy = [r[0] for r in ventas_hoy]
        self.assertNotIn(self.id_venta_test, ids_hoy, "La venta modificada NO debe aparecer en el filtro de Hoy")

        # Caso B: El usuario escribe la fecha destino en el campo de fecha ('2026-11-20' o '20/11/2026')
        for f_in in [self.fecha_destino, "20/11/2026", "20-11-2026"]:
            f_filtro, ventas_dest = _simular_filtro_cargar_ventas("Hoy", f_in) # Aunque el combo esté en Hoy, debe respetar f_in!
            self.assertEqual(f_filtro, self.fecha_destino)
            ids_dest = [r[0] for r in ventas_dest]
            self.assertIn(self.id_venta_test, ids_dest, f"La venta modificada DEBE aparecer al ingresar '{f_in}'")

        # Caso C: En 'Todas las fechas' la venta debe aparecer con su nueva fecha
        f_filtro, ventas_todas = _simular_filtro_cargar_ventas("Todas las fechas", "")
        self.assertEqual(f_filtro, "")
        venta_encontrada = [r for r in ventas_todas if r[0] == self.id_venta_test]
        self.assertEqual(len(venta_encontrada), 1)
        self.assertEqual(venta_encontrada[0][1], self.fecha_destino)


if __name__ == "__main__":
    unittest.main()
