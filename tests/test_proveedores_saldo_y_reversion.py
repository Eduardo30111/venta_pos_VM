#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Suite: Verificación de Generación y Reversión de Saldos de Proveedores (7 Pruebas Obligatorias)
Archivo: tests/test_proveedores_saldo_y_reversion.py
"""

import os
import sys
import sqlite3
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface.database_manager import conectar_db, inicializar_base_datos
from interface.proveedores_manager import (
    registrar_cxp_servicio_venta,
    revertir_cxp_por_venta_anulada,
    ajustar_cxp_por_edicion_venta,
    recalcular_saldo_proveedor,
    obtener_resumen_proveedores,
    liquidar_proveedor_db,
    obtener_detalle_cuentas_proveedor
)
from interface.caja_manager import anular_venta_completa, editar_venta_completa


class TestProveedoresSaldoYReversion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inicializar_base_datos()

    def setUp(self):
        self.conn = conectar_db()
        self.cur = self.conn.cursor()
        self.cur.execute("PRAGMA foreign_keys = OFF;")
        # Limpiar datos de prueba
        self.cur.execute("DELETE FROM cuentas_por_pagar_proveedores WHERE proveedor_nombre LIKE 'Omara Sierra%' AND proveedor_id != 1")
        self.cur.execute("DELETE FROM liquidaciones_proveedores WHERE proveedor_nombre LIKE 'Omara Sierra%' AND proveedor_id != 1")
        self.cur.execute("DELETE FROM detalle_ventas WHERE codigo_producto IN ('TEST-OMARA-01', 'TEST-GEN-01')")
        self.cur.execute("DELETE FROM ventas WHERE operario = 'TestRunner'")
        self.cur.execute("DELETE FROM productos WHERE codigo IN ('TEST-OMARA-01', 'TEST-GEN-01')")
        self.cur.execute("DELETE FROM proveedores WHERE nombre = 'Omara Sierra' AND id != 1")
        self.conn.commit()

        # Crear proveedor Omara Sierra
        self.cur.execute("""
            INSERT INTO proveedores (nombre, documento_nit, telefono, saldo_acumulado)
            VALUES ('Omara Sierra', '123456789', '3001234567', 0.0)
        """)
        self.prov_id = self.cur.lastrowid

        # Crear producto físico asociado a Omara Sierra: Precio $20.000, Costo $12.000
        self.cur.execute("""
            INSERT INTO productos (codigo, nombre, precio, costo, stock_vitrina, stock_bodega, stock, tipo_producto, proveedor_id, estado)
            VALUES ('TEST-OMARA-01', 'Cuaderno Omara', 20000.0, 12000.0, 50, 50, 100, 'Fisico', ?, 'Activo')
        """, (self.prov_id,))
        self.prod_id = self.cur.lastrowid

        # Crear producto genérico sin proveedor
        self.cur.execute("""
            INSERT INTO productos (codigo, nombre, precio, costo, stock_vitrina, stock_bodega, stock, tipo_producto, estado)
            VALUES ('TEST-GEN-01', 'Borrador Genérico', 2000.0, 800.0, 100, 0, 100, 'Fisico', 'Activo')
        """)
        self.prod_gen_id = self.cur.lastrowid

        self.conn.commit()

    def _crear_venta(self, total: float, metodo: str = "Efectivo", estado: str = "Completada") -> int:
        self.cur.execute("""
            INSERT INTO ventas (total_venta, metodo_pago, estado, fecha_venta, hora_venta, documento_cliente, operario)
            VALUES (?, ?, ?, '2026-11-09', '12:00:00', '222222222222', 'TestRunner')
        """, (total, metodo, estado))
        return self.cur.lastrowid

    def tearDown(self):
        if self.conn:
            self.cur.execute("PRAGMA foreign_keys = OFF;")
            self.cur.execute("DELETE FROM cuentas_por_pagar_proveedores WHERE proveedor_nombre LIKE 'Omara Sierra%' AND proveedor_id != 1")
            self.cur.execute("DELETE FROM liquidaciones_proveedores WHERE proveedor_nombre LIKE 'Omara Sierra%' AND proveedor_id != 1")
            self.cur.execute("DELETE FROM detalle_ventas WHERE codigo_producto IN ('TEST-OMARA-01', 'TEST-GEN-01')")
            self.cur.execute("DELETE FROM ventas WHERE operario = 'TestRunner'")
            self.cur.execute("DELETE FROM productos WHERE codigo IN ('TEST-OMARA-01', 'TEST-GEN-01')")
            self.cur.execute("DELETE FROM proveedores WHERE nombre = 'Omara Sierra' AND id != 1")
            self.conn.commit()
            self.conn.close()

    def test_01_venta_producto_proveedor_genera_cxp_y_saldo(self):
        """Prueba 1: Venta de 3 unidades @ $12.000 costo genera CXP de $36.000 COP y sube saldo a $36.000."""
        id_venta = self._crear_venta(60000.0)

        detalle_item = {
            "item_id": self.prod_id,
            "codigo_producto": "TEST-OMARA-01",
            "nombre_producto": "Cuaderno Omara",
            "cantidad": 3,
            "precio_vendido": 20000.0,
            "subtotal": 60000.0,
            "costo_unitario": 12000.0,
            "proveedor_id": self.prov_id
        }

        cxp = registrar_cxp_servicio_venta(
            id_venta=id_venta,
            detalle_item=detalle_item,
            operario_nombre="TestRunner",
            conn=self.conn
        )

        self.assertIsNotNone(cxp, "Debe generar registro en cuentas_por_pagar_proveedores")
        self.assertEqual(cxp["monto_por_pagar"], 36000.0, "La obligación debe ser 3 * 12.000 = $36.000 COP")
        self.assertEqual(cxp["proveedor_id"], self.prov_id)

        # Verificar saldo acumulado del proveedor
        recalcular_saldo_proveedor(self.prov_id, conn=self.conn)
        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (self.prov_id,))
        saldo = float(self.cur.fetchone()[0])
        self.assertEqual(saldo, 36000.0, "El saldo pendiente del proveedor debe ser exactamente $36.000 COP")

    def test_02_segunda_venta_acumula_saldo_correctamente(self):
        """Prueba 2: Segunda venta de 2 unidades suma $24.000 COP llevando el saldo total a $60.000 COP."""
        id_v1 = self._crear_venta(60000.0)
        registrar_cxp_servicio_venta(
            id_venta=id_v1,
            detalle_item={"item_id": self.prod_id, "codigo": "TEST-OMARA-01", "nombre": "Cuaderno Omara", "cantidad": 3, "subtotal": 60000.0, "costo": 12000.0},
            conn=self.conn
        )

        id_v2 = self._crear_venta(40000.0)
        registrar_cxp_servicio_venta(
            id_venta=id_v2,
            detalle_item={"item_id": self.prod_id, "codigo": "TEST-OMARA-01", "nombre": "Cuaderno Omara", "cantidad": 2, "subtotal": 40000.0, "costo": 12000.0},
            conn=self.conn
        )

        recalcular_saldo_proveedor(self.prov_id, conn=self.conn)
        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (self.prov_id,))
        saldo = float(self.cur.fetchone()[0])
        self.assertEqual(saldo, 60000.0, "El saldo acumulado debe ser $36.000 + $24.000 = $60.000 COP")

    def test_03_anulacion_total_revierte_cxp_y_descuenta_saldo(self):
        """Prueba 3: Anulación total de la venta 1 revierte $36.000 COP dejando saldo de $24.000 COP."""
        id_v1 = self._crear_venta(60000.0)
        registrar_cxp_servicio_venta(id_venta=id_v1, detalle_item={"codigo": "TEST-OMARA-01", "cantidad": 3, "subtotal": 60000.0, "costo": 12000.0}, conn=self.conn)

        id_v2 = self._crear_venta(40000.0)
        registrar_cxp_servicio_venta(id_venta=id_v2, detalle_item={"codigo": "TEST-OMARA-01", "cantidad": 2, "subtotal": 40000.0, "costo": 12000.0}, conn=self.conn)

        # Anular venta 1
        res_rev = revertir_cxp_por_venta_anulada(id_venta=id_v1, motivo="Prueba anulación", conn=self.conn)
        self.assertTrue(res_rev["ok"])
        self.assertGreater(res_rev["afectados"], 0)

        # Verificar estado de la CXP de la venta 1
        self.cur.execute("SELECT estado, saldo_pendiente FROM cuentas_por_pagar_proveedores WHERE id_venta = ?", (id_v1,))
        row_cxp = self.cur.fetchone()
        self.assertEqual(row_cxp[0], "Anulada", "La cuenta por pagar debe quedar marcada como 'Anulada'")
        self.assertEqual(float(row_cxp[1]), 0.0, "El saldo pendiente de la cuenta anulada debe ser 0.0")

        # Verificar saldo remanente del proveedor
        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (self.prov_id,))
        saldo = float(self.cur.fetchone()[0])
        self.assertEqual(saldo, 24000.0, "El saldo del proveedor debe reducirse exactamente a $24.000 COP")

    def test_04_doble_anulacion_es_idempotente(self):
        """Prueba 4: Intentar anular la misma venta por segunda vez no debe restar doble el saldo."""
        id_v1 = self._crear_venta(60000.0)
        registrar_cxp_servicio_venta(id_venta=id_v1, detalle_item={"codigo": "TEST-OMARA-01", "cantidad": 3, "subtotal": 60000.0, "costo": 12000.0}, conn=self.conn)

        # Primera anulación
        revertir_cxp_por_venta_anulada(id_venta=id_v1, conn=self.conn)
        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (self.prov_id,))
        saldo_despues_1 = float(self.cur.fetchone()[0])
        self.assertEqual(saldo_despues_1, 0.0)

        # Segunda anulación repetida (idempotencia)
        res_2 = revertir_cxp_por_venta_anulada(id_venta=id_v1, conn=self.conn)
        self.assertEqual(res_2["afectados"], 0, "No debe afectar ninguna fila en segunda anulación")

        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (self.prov_id,))
        saldo_despues_2 = float(self.cur.fetchone()[0])
        self.assertEqual(saldo_despues_2, 0.0, "El saldo debe permanecer inalterado en 0.0 COP")

    def test_05_devolucion_parcial_ajusta_saldo_coherentemente(self):
        """Prueba 5: Devolución parcial (5 vendidas, 2 devueltas -> 3 unidades, obligación baja a $36.000 COP)."""
        id_v = self._crear_venta(100000.0)
        registrar_cxp_servicio_venta(id_venta=id_v, detalle_item={"codigo": "TEST-OMARA-01", "cantidad": 5, "subtotal": 100000.0, "costo": 12000.0}, conn=self.conn)

        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (self.prov_id,))
        self.assertEqual(float(self.cur.fetchone()[0]), 60000.0, "Inicialmente 5 * $12.000 = $60.000 COP")

        # Devolución de 2 unidades -> quedan 3 unidades
        nuevos_items = [{
            "codigo_producto": "TEST-OMARA-01",
            "nombre_producto": "Cuaderno Omara",
            "cantidad": 3,
            "precio_unitario": 20000.0,
            "subtotal": 60000.0,
            "costo_unitario": 12000.0
        }]
        res_ajuste = ajustar_cxp_por_edicion_venta(id_venta=id_v, nuevos_detalles=nuevos_items, conn=self.conn)
        self.assertTrue(res_ajuste["ok"])

        # Verificar nuevo saldo del proveedor
        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (self.prov_id,))
        saldo_nuevo = float(self.cur.fetchone()[0])
        self.assertEqual(saldo_nuevo, 36000.0, "El saldo ajustado debe ser 3 * $12.000 = $36.000 COP")

    def test_06_anulacion_con_abono_previo_mantiene_trazabilidad(self):
        """Prueba 6: Proveedor con abono previo no pierde trazabilidad de liquidación al anular la venta."""
        id_v = self._crear_venta(60000.0)
        registrar_cxp_servicio_venta(id_venta=id_v, detalle_item={"codigo": "TEST-OMARA-01", "cantidad": 3, "subtotal": 60000.0, "costo": 12000.0}, conn=self.conn)

        # Realizar abono de $10.000 COP a Omara Sierra
        res_pago = liquidar_proveedor_db(
            proveedor_id=self.prov_id,
            monto=10000.0,
            metodo_pago="Efectivo",
            usuario="TestRunner",
            observaciones="Abono parcial de prueba",
            conn=self.conn
        )
        self.assertTrue(res_pago["exito"])

        # Saldo pendiente debe ser $36.000 - $10.000 = $26.000 COP
        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (self.prov_id,))
        saldo_abono = float(self.cur.fetchone()[0])
        self.assertEqual(saldo_abono, 26000.0)

        # Ahora se anula la venta original
        revertir_cxp_por_venta_anulada(id_venta=id_v, conn=self.conn)

        # El comprobante de liquidación histórica debe seguir intacto
        self.cur.execute("SELECT COUNT(*) FROM liquidaciones_proveedores WHERE proveedor_id = ?", (self.prov_id,))
        cant_liq = self.cur.fetchone()[0]
        self.assertEqual(cant_liq, 1, "El recibo de liquidación histórica NO debe borrarse")

        # El saldo pendiente se ajusta a 0.0 (no negativo)
        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (self.prov_id,))
        saldo_post = float(self.cur.fetchone()[0])
        self.assertEqual(saldo_post, 0.0)

    def test_07_productos_sin_proveedor_no_generan_cxp(self):
        """Prueba 7: Productos sin proveedor no generan registros de cuentas por pagar ni modifican saldos."""
        id_v = self._crear_venta(10000.0)

        detalle_gen = {
            "item_id": self.prod_gen_id,
            "codigo_producto": "TEST-GEN-01",
            "nombre_producto": "Borrador Genérico",
            "cantidad": 5,
            "subtotal": 10000.0,
            "costo_unitario": 800.0
        }

        cxp = registrar_cxp_servicio_venta(id_venta=id_v, detalle_item=detalle_gen, conn=self.conn)
        self.assertIsNone(cxp, "Un producto sin proveedor asignado debe retornar None")

        # Saldo de proveedores no debe sufrir cambios
        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (self.prov_id,))
        saldo = float(self.cur.fetchone()[0])
        self.assertEqual(saldo, 0.0)


if __name__ == "__main__":
    unittest.main()
