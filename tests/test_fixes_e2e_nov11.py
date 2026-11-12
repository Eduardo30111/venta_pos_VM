#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Suite E2E: Verificación de Proveedores CXP, Edición de Ventas y Pagos Mixtos
Fecha: 11 de Noviembre de 2026
"""

import os
import sys
import unittest
import sqlite3
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface.database_manager import conectar_db, inicializar_base_datos
from interface.inventario_manager import upsert_articulo_sqlite, obtener_articulo_por_codigo
from interface.proveedores_manager import (
    registrar_cxp_servicio_venta,
    obtener_resumen_proveedores,
    obtener_detalle_cuentas_proveedor,
    liquidar_proveedor_db,
    revertir_cxp_por_venta_anulada,
    recalcular_saldo_proveedor,
    sincronizar_cxp_retroactivas
)
from interface.caja_manager import (
    editar_venta_completa,
    anular_venta_completa,
    calcular_arqueo_sesion
)
from interface.ventas_menu import guardar_venta_sqlite
from server.schemas.venta import EditarVentaRequest, EditarVentaItemRequest
from server.schemas.inventario import ArticuloCatalogoCreate, ArticuloCatalogoUpdate


class TestFixesE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inicializar_base_datos()

    def setUp(self):
        self.conn = conectar_db()
        self.cur = self.conn.cursor()
        self.cur.execute("PRAGMA foreign_keys = OFF;")
        
        # Limpieza previa de entorno de pruebas
        self.cur.execute("DELETE FROM cuentas_por_pagar_proveedores WHERE proveedor_id = 999 OR proveedor_nombre LIKE 'Test Omara%'")
        self.cur.execute("DELETE FROM liquidaciones_proveedores WHERE proveedor_id = 999 OR proveedor_nombre LIKE 'Test Omara%'")
        self.cur.execute("DELETE FROM productos WHERE codigo IN ('TEST-OMARA-FIX', 'TEST-MIX-01', 'TEST-EDIT-01')")
        self.cur.execute("DELETE FROM detalle_ventas WHERE codigo_producto IN ('TEST-OMARA-FIX', 'TEST-MIX-01', 'TEST-EDIT-01')")
        self.cur.execute("DELETE FROM proveedores WHERE id = 999 OR nombre LIKE 'Test Omara%'")
        self.cur.execute("DELETE FROM clientes WHERE id = 999 OR nombre LIKE 'Cliente Test Mixto%'")
        
        # Insertar proveedor de prueba con ID 999
        self.cur.execute("""
            INSERT OR REPLACE INTO proveedores (id, nombre, documento_nit, telefono, saldo_acumulado)
            VALUES (999, 'Test Omara Sierra', '93998484', '3001234567', 0.0)
        """)
        
        # Insertar cliente de prueba con ID 999
        self.cur.execute("""
            INSERT OR REPLACE INTO clientes (id, cedula, nombre, telefono, limite_credito, saldo_pendiente, permite_fiado, estado, fecha_registro)
            VALUES (999, '99999999', 'Cliente Test Mixto', '3109876543', 500000.0, 0.0, 1, 'Activo', '2026-11-11 00:00:00')
        """)
        
        self.conn.commit()

    def tearDown(self):
        try:
            conn = conectar_db()
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys = OFF;")
            cur.execute("DELETE FROM cuentas_por_pagar_proveedores WHERE proveedor_id = 999 OR proveedor_nombre LIKE 'Test Omara%'")
            cur.execute("DELETE FROM liquidaciones_proveedores WHERE proveedor_id = 999 OR proveedor_nombre LIKE 'Test Omara%'")
            cur.execute("DELETE FROM productos WHERE codigo IN ('TEST-OMARA-FIX', 'TEST-MIX-01', 'TEST-EDIT-01')")
            cur.execute("DELETE FROM proveedores WHERE id = 999")
            cur.execute("DELETE FROM clientes WHERE id = 999")
            conn.commit()
            conn.close()
        except Exception:
            pass
        finally:
            try:
                self.conn.close()
            except Exception:
                pass

    # =========================================================================
    # 1. PRUEBA: NORMALIZACIÓN DE PROVEEDOR (ej: "1 - omara" o "999 - Test Omara")
    # =========================================================================
    def test_01_normalizacion_proveedor_articulo(self):
        """Verifica que el formato de combobox '999 - Test Omara' se normalice a entero 999."""
        # Test schema FastAPI Pydantic
        art_req = ArticuloCatalogoCreate(
            codigo="TEST-OMARA-FIX",
            nombre="Impresion Test Omara",
            precio_venta=1700.0,
            tipo="Servicio",
            proveedor_id="999 - Test Omara Sierra"
        )
        self.assertEqual(art_req.proveedor_id, 999, "El schema debe convertir '999 - Test Omara Sierra' a int 999")

        # Test guardado en SQLite local vía inventario_manager
        art_dict = {
            "codigo": "TEST-OMARA-FIX",
            "nombre": "Impresion Test Omara",
            "categoria": "Servicios",
            "tipo": "Servicio",
            "precio_venta": 1700.0,
            "costo": 0.0,
            "stock_vitrina": 100.0,
            "stock_bodega": 0.0,
            "proveedor_id": "999 - Test Omara Sierra",
            "comision_porcentaje": 0.0
        }
        res = upsert_articulo_sqlite(art_dict)
        self.assertTrue(res, "upsert_articulo_sqlite debe guardar el artículo exitosamente")

        art_db = obtener_articulo_por_codigo("TEST-OMARA-FIX")
        self.assertIsNotNone(art_db)
        self.assertEqual(art_db.get("proveedor_id"), 999, "En la base de datos proveedor_id debe ser 999")

    # =========================================================================
    # 2. PRUEBA: REGISTRO DE CXP, ACTUALIZACIÓN DE SALDO Y LIQUIDACIÓN FIFO
    # =========================================================================
    def test_02_cxp_saldo_y_liquidacion_fifo(self):
        """Verifica la generación de CXP ($3.400 en dos impresiones), abono de $1.400 y pago total de $2.000."""
        # Asegurar producto creado
        art_dict = {
            "codigo": "TEST-OMARA-FIX",
            "nombre": "Impresion Test Omara",
            "categoria": "Servicios",
            "tipo": "Servicio",
            "precio_venta": 1700.0,
            "costo": 0.0,
            "stock_vitrina": 100.0,
            "stock_bodega": 0.0,
            "proveedor_id": "999 - Test Omara Sierra",
            "comision_porcentaje": 0.0
        }
        upsert_articulo_sqlite(art_dict)

        # 1. Registrar 2 ventas con el producto de Omara (2 impresiones de $1.700 = $3.400)
        items_v1 = [{"codigo": "TEST-OMARA-FIX", "nombre": "Impresion Test Omara", "cantidad": 1, "precio": 1700.0, "proveedor_id": 999}]
        v1_id = guardar_venta_sqlite(
            doc_cliente="Consumidor Final",
            total=1700.0,
            metodo_pago="Efectivo",
            detalles=items_v1,
            operario_nombre="admin"
        )
        self.assertIsNotNone(v1_id)

        items_v2 = [{"codigo": "TEST-OMARA-FIX", "nombre": "Impresion Test Omara", "cantidad": 1, "precio": 1700.0, "proveedor_id": 999}]
        v2_id = guardar_venta_sqlite(
            doc_cliente="Consumidor Final",
            total=1700.0,
            metodo_pago="Efectivo",
            detalles=items_v2,
            operario_nombre="admin"
        )
        self.assertIsNotNone(v2_id)

        # 2. Verificar que el saldo acumulado sea exactamente $3.400
        recalcular_saldo_proveedor(999)
        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = 999")
        saldo = float(self.cur.fetchone()[0] or 0.0)
        self.assertEqual(saldo, 3400.0, f"El saldo pendiente debe ser 3.400, obtenido: {saldo}")

        # 3. Verificar que la tabla de CXP tenga los 2 registros
        cxps = obtener_detalle_cuentas_proveedor(999)
        self.assertEqual(len(cxps), 2, f"Deben existir 2 cuentas por pagar, encontradas: {len(cxps)}")
        total_por_pagar = sum(float(c.get("monto_por_pagar", c.get("saldo_pendiente", 0.0))) for c in cxps)
        self.assertEqual(total_por_pagar, 3400.0)

        # 4. Abono parcial de $1.400 COP
        res_abono = liquidar_proveedor_db(
            proveedor_id=999,
            monto_liquidado=1400.0,
            medio_pago="Efectivo",
            cajero="admin",
            notas="Abono parcial de prueba"
        )
        self.assertTrue(res_abono.get("exito"), "El abono de 1.400 debe ser exitoso")

        # Verificar saldo remanente: $3.400 - $1.400 = $2.000 COP
        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = 999")
        saldo_post_abono = float(self.cur.fetchone()[0] or 0.0)
        self.assertEqual(saldo_post_abono, 2000.0, f"El saldo después del abono debe ser 2.000, obtenido: {saldo_post_abono}")

        # 5. Liquidación restante de $2.000 COP
        res_liq_final = liquidar_proveedor_db(
            proveedor_id=999,
            monto_liquidado=2000.0,
            medio_pago="Efectivo",
            cajero="admin",
            notas="Liquidación saldo restante"
        )
        self.assertTrue(res_liq_final.get("exito"), "La liquidación final debe ser exitosa")

        # Verificar saldo final en 0
        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = 999")
        saldo_final = float(self.cur.fetchone()[0] or 0.0)
        self.assertEqual(saldo_final, 0.0, f"El saldo final debe quedar en 0 COP, obtenido: {saldo_final}")

    # =========================================================================
    # 3. PRUEBA: REVERSIÓN DE OBLIGACIÓN AL ANULAR VENTA
    # =========================================================================
    def test_03_anulacion_venta_revierte_cxp(self):
        """Verifica que anular una venta no liquidada reversa el saldo del proveedor a 0."""
        # Asegurar producto creado
        art_dict = {
            "codigo": "TEST-OMARA-FIX",
            "nombre": "Impresion Test Omara",
            "categoria": "Servicios",
            "tipo": "Servicio",
            "precio_venta": 1700.0,
            "costo": 0.0,
            "stock_vitrina": 100.0,
            "stock_bodega": 0.0,
            "proveedor_id": "999 - Test Omara Sierra",
            "comision_porcentaje": 0.0
        }
        upsert_articulo_sqlite(art_dict)

        # 1. Registrar venta con el producto de Omara ($1.700)
        items = [{"codigo": "TEST-OMARA-FIX", "nombre": "Impresion Test Omara", "cantidad": 1, "precio": 1700.0, "proveedor_id": 999}]
        v_id = guardar_venta_sqlite(
            doc_cliente="Consumidor Final",
            total=1700.0,
            metodo_pago="Efectivo",
            detalles=items,
            operario_nombre="admin"
        )
        self.assertIsNotNone(v_id)

        # Saldo debe ser 1.700
        recalcular_saldo_proveedor(999)
        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = 999")
        saldo = float(self.cur.fetchone()[0] or 0.0)
        self.assertEqual(saldo, 1700.0)

        # 2. Anular la venta
        res = anular_venta_completa(v_id, motivo="Anulación de prueba", usuario="admin")
        self.assertTrue(res.get("exito"), f"La anulación debe ser exitosa: {res}")

        # 3. Saldo debe volver a 0
        self.cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = 999")
        saldo_post = float(self.cur.fetchone()[0] or 0.0)
        self.assertEqual(saldo_post, 0.0, f"El saldo después de anular debe ser 0, obtenido: {saldo_post}")

        # CXP debe estar en estado 'Anulada'
        self.cur.execute("SELECT estado FROM cuentas_por_pagar_proveedores WHERE id_venta = ?", (v_id,))
        row = self.cur.fetchone()
        self.assertEqual(row[0], "Anulada")

    # =========================================================================
    # 4. PRUEBA: EDICIÓN DE VENTA (SCHEMA VALIDATOR Y AUDITORÍA)
    # =========================================================================
    def test_04_editar_venta_schema_y_auditoria(self):
        """Verifica que el schema FastAPI acepte los nombres de campos del cliente y registre auditoría."""
        # 1. Test validadores del Schema Pydantic
        payload_cliente = {
            "nuevo_metodo": "Transferencia",
            "motivo": "Corrección de prueba",
            "nuevos_items": [
                {
                    "codigo": "TEST-EDIT-01",
                    "nombre": "Cuaderno 100h",
                    "cantidad": 2,
                    "precio": 5000.0
                }
            ]
        }
        # Debe instanciar EditarVentaRequest sin error de validación 422
        req = EditarVentaRequest(**payload_cliente)
        self.assertEqual(req.nuevo_metodo, "Transferencia")
        self.assertEqual(req.motivo, "Corrección de prueba")
        self.assertEqual(len(req.nuevos_items), 1)
        self.assertEqual(req.nuevos_items[0].codigo_producto, "TEST-EDIT-01")
        self.assertEqual(req.nuevos_items[0].precio_unitario, 5000.0)

        # 2. Crear una venta real en base de datos para editarla
        items_orig = [{"codigo": "TEST-EDIT-01", "nombre": "Cuaderno 100h", "cantidad": 1, "precio": 5000.0}]
        v_id = guardar_venta_sqlite(
            doc_cliente="Consumidor Final",
            total=5000.0,
            metodo_pago="Efectivo",
            detalles=items_orig,
            operario_nombre="admin"
        )
        self.assertIsNotNone(v_id)

        # 3. Ejecutar edición completa
        nuevos_items = [{"codigo_producto": "TEST-EDIT-01", "nombre_producto": "Cuaderno 100h", "cantidad": 3, "precio_unitario": 5000.0}]
        res = editar_venta_completa(
            id_venta=v_id,
            nuevo_metodo="Transferencia",
            nuevos_items=nuevos_items,
            motivo="Cliente solicitó 2 unidades más y pagó por transferencia",
            usuario="admin"
        )
        self.assertTrue(res.get("exito"), f"La edición de venta debe ser exitosa: {res}")

        # 4. Verificar nuevo total de la venta en base de datos: 3 * 5000 = 15.000
        self.cur.execute("SELECT total_venta, metodo_pago FROM ventas WHERE id_venta = ?", (v_id,))
        v_row = self.cur.fetchone()
        self.assertEqual(float(v_row[0]), 15000.0)
        self.assertEqual(v_row[1], "Transferencia")

        # 5. Verificar registro en auditoría
        self.cur.execute("SELECT valor_anterior, valor_nuevo, motivo FROM auditoria_ventas WHERE id_venta = ?", (v_id,))
        aud_row = self.cur.fetchone()
        self.assertIsNotNone(aud_row, "Debe existir un registro en auditoria_ventas")
        self.assertEqual(float(aud_row[0]), 5000.0)
        self.assertEqual(float(aud_row[1]), 15000.0)

    # =========================================================================
    # 5. PRUEBA: PAGOS MIXTOS (EFECTIVO + TRANSFERENCIA + FIADO)
    # =========================================================================
    def test_05_pagos_mixtos_contabilidad_y_reversion(self):
        """Verifica una venta con pago mixto ($50k efectivo, $30k transf, $20k fiado = $100k)."""
        items_mix = [{"codigo": "TEST-MIX-01", "nombre": "Articulo Mixto", "cantidad": 1, "precio": 100000.0}]
        pagos_detalle = [
            {"metodo": "Efectivo", "monto": 50000.0},
            {"metodo": "Transferencia", "monto": 30000.0},
            {"metodo": "Fiado", "monto": 20000.0}
        ]

        # 1. Guardar venta mixta
        v_id = guardar_venta_sqlite(
            doc_cliente="99999999",
            total=100000.0,
            metodo_pago="Mixto",
            detalles=items_mix,
            operario_nombre="admin",
            cliente_id=999,
            pagos=pagos_detalle
        )
        self.assertIsNotNone(v_id)

        # 2. Verificar que pagos_venta guardó los 3 desgloses
        self.cur.execute("SELECT metodo_pago, monto FROM pagos_venta WHERE id_venta = ? ORDER BY monto DESC", (v_id,))
        rows = self.cur.fetchall()
        self.assertEqual(len(rows), 3, "Deben existir 3 desgloses en pagos_venta")
        self.assertEqual(rows[0], ("Efectivo", 50000.0))
        self.assertEqual(rows[1], ("Transferencia", 30000.0))
        self.assertEqual(rows[2], ("Fiado", 20000.0))

        # 3. Verificar que el saldo del cliente se actualizó por el monto fiado ($20.000)
        self.cur.execute("SELECT saldo_pendiente FROM clientes WHERE id = 999")
        saldo_cli = float(self.cur.fetchone()[0] or 0.0)
        self.assertEqual(saldo_cli, 20000.0, f"El saldo del cliente debe ser 20.000, obtenido: {saldo_cli}")

        # 4. Verificar arqueo de sesión (debe computar $50k efectivo y $30k transferencia)
        arqueo = calcular_arqueo_sesion()
        self.assertGreaterEqual(arqueo.get("ventas_efectivo", 0.0), 50000.0)
        self.assertGreaterEqual(arqueo.get("ventas_transferencia", 0.0), 30000.0)

        # 5. Anular la venta mixta y comprobar reversión en efectivo, banco y cartera
        res = anular_venta_completa(v_id, motivo="Anulación de prueba mixta", usuario="admin")
        self.assertTrue(res.get("exito"), f"La anulación mixta debe ser exitosa: {res}")

        # Saldo del cliente debe haber revertido a 0
        self.cur.execute("SELECT saldo_pendiente FROM clientes WHERE id = 999")
        saldo_cli_rev = float(self.cur.fetchone()[0] or 0.0)
        self.assertEqual(saldo_cli_rev, 0.0, f"El saldo fiado del cliente debe quedar en 0 tras anular, obtenido: {saldo_cli_rev}")


if __name__ == "__main__":
    unittest.main()
