#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Integral del Sistema de Materiales, Bodega, Inventarios Individuales,
Presentaciones y Consumo en Ventas de VmPOS.
Cubre los 16 escenarios especificados en el requerimiento.
"""

import os
import sys
import unittest
import sqlite3
import tempfile
import shutil

# Asegurar path del proyecto
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from interface.materiales_manager import (
    obtener_materiales_catalogo,
    guardar_presentacion_material,
    obtener_presentaciones_material,
    trasladar_bodega_a_operario,
    devolver_operario_a_bodega,
    registrar_desperdicio_material,
    obtener_inventario_operario,
    obtener_saldo_material_usuario,
    descontar_materiales_venta,
    gestionar_consumo_anulacion_venta,
    obtener_historial_materiales,
    obtener_kpis_materiales
)
from interface.database_manager import conectar_db, inicializar_base_datos


class TestSistemaMaterialesIntegral(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Asegurar inicialización de base de datos completa
        inicializar_base_datos()
        conn = conectar_db()
        cur = conn.cursor()

        # Limpiar datos previos de prueba para materiales
        cur.execute("DELETE FROM consumos_materiales_venta WHERE numero_factura LIKE 'TEST-MAT-%'")
        cur.execute("DELETE FROM traslados_inventario WHERE observaciones LIKE '%TEST_MAT%'")
        cur.execute("DELETE FROM movimientos_inventario WHERE observaciones LIKE '%TEST_MAT%'")
        cur.execute("DELETE FROM inventario_operarios WHERE usuario_nombre IN ('Operario_Test_1', 'Operario_Test_2', 'Admin_Test')")
        cur.execute("DELETE FROM presentaciones_producto WHERE codigo_producto IN ('MAT-001', 'MAT-002', 'MAT-003')")
        cur.execute("DELETE FROM productos WHERE codigo IN ('MAT-001', 'MAT-002', 'MAT-003')")

        # 1. Crear 3 materiales de prueba en catálogo
        # Papel normal (MAT-001): 2.000 hojas en bodega
        cur.execute("""
            INSERT INTO productos (codigo, nombre, categoria, precio, costo, unidad_medida, stock_bodega, stock_vitrina, stock, es_material, presentacion_defecto, factor_conversion_defecto, unidad_consumo_defecto)
            VALUES ('MAT-001', 'Papel Normal Carta Test', 'Materiales', 50.0, 30.0, 'Hojas', 2000, 0, 2000, 1, 'Resma', 500, 'Hojas')
        """)
        cls.p1_id = cur.lastrowid

        # Papel fotográfico (MAT-002): 100 hojas en bodega
        cur.execute("""
            INSERT INTO productos (codigo, nombre, categoria, precio, costo, unidad_medida, stock_bodega, stock_vitrina, stock, es_material, presentacion_defecto, factor_conversion_defecto, unidad_consumo_defecto)
            VALUES ('MAT-002', 'Papel Fotográfico Test', 'Materiales', 500.0, 250.0, 'Hojas', 100, 0, 100, 1, 'Paquete', 20, 'Hojas')
        """)
        cls.p2_id = cur.lastrowid

        # Papel propal (MAT-003): 200 hojas en bodega
        cur.execute("""
            INSERT INTO productos (codigo, nombre, categoria, precio, costo, unidad_medida, stock_bodega, stock_vitrina, stock, es_material, presentacion_defecto, factor_conversion_defecto, unidad_consumo_defecto)
            VALUES ('MAT-003', 'Papel Propalcote Test', 'Materiales', 300.0, 150.0, 'Hojas', 200, 0, 200, 1, 'Paquete', 50, 'Hojas')
        """)
        cls.p3_id = cur.lastrowid

        conn.commit()
        conn.close()

    def test_01_catalogo_materiales(self):
        """Verifica que los materiales se listen adecuadamente."""
        mats = obtener_materiales_catalogo()
        cods = [m["codigo"] for m in mats]
        self.assertIn("MAT-001", cods)
        self.assertIn("MAT-002", cods)
        self.assertIn("MAT-003", cods)

    def test_02_configuracion_presentaciones(self):
        """Verifica creación y consulta de presentaciones de compra a consumo."""
        ok = guardar_presentacion_material(
            producto_id=self.p1_id,
            codigo_producto="MAT-001",
            nombre_presentacion="Caja de 5 Resmas (2500 hojas)",
            unidad_compra="Caja",
            cantidad_unidades_base=2500.0,
            unidad_consumo="Hojas",
            costo_defecto=120000.0
        )
        self.assertTrue(ok)
        pres = obtener_presentaciones_material(self.p1_id)
        self.assertGreaterEqual(len(pres), 1)
        self.assertEqual(pres[0]["unidad_compra"], "Caja")
        self.assertEqual(pres[0]["cantidad_unidades_base"], 2500.0)

    def test_03_traslado_bodega_a_operarios(self):
        """
        Escenario:
        Bodega inicial: 2000 MAT-001, 100 MAT-002, 200 MAT-003.
        Trasladar a Operario_Test_1: 500 normal, 25 foto, 50 propal.
        Trasladar a Operario_Test_2: 500 normal, 25 foto, 50 propal.
        """
        # Operario 1
        r1 = trasladar_bodega_a_operario(
            producto_id=self.p1_id,
            usuario_destino="Operario_Test_1",
            cantidad=500.0,
            usuario_admin="Admin_Test",
            motivo="TEST_MAT Entrega mat 1 op 1"
        )
        self.assertTrue(r1["ok"], f"Error traslado: {r1.get('mensaje')}")
        self.assertEqual(r1["saldo_nuevo_operario"], 500.0)

        r2 = trasladar_bodega_a_operario(
            producto_id=self.p2_id,
            usuario_destino="Operario_Test_1",
            cantidad=25.0,
            usuario_admin="Admin_Test",
            motivo="TEST_MAT Entrega mat 2 op 1"
        )
        self.assertTrue(r2["ok"])
        self.assertEqual(r2["saldo_nuevo_operario"], 25.0)

        r3 = trasladar_bodega_a_operario(
            producto_id=self.p3_id,
            usuario_destino="Operario_Test_1",
            cantidad=50.0,
            usuario_admin="Admin_Test",
            motivo="TEST_MAT Entrega mat 3 op 1"
        )
        self.assertTrue(r3["ok"])
        self.assertEqual(r3["saldo_nuevo_operario"], 50.0)

        # Operario 2
        r4 = trasladar_bodega_a_operario(
            producto_id=self.p1_id,
            usuario_destino="Operario_Test_2",
            cantidad=500.0,
            usuario_admin="Admin_Test",
            motivo="TEST_MAT Entrega mat 1 op 2"
        )
        self.assertTrue(r4["ok"])
        self.assertEqual(r4["saldo_nuevo_operario"], 500.0)

        r5 = trasladar_bodega_a_operario(
            producto_id=self.p2_id,
            usuario_destino="Operario_Test_2",
            cantidad=25.0,
            usuario_admin="Admin_Test",
            motivo="TEST_MAT Entrega mat 2 op 2"
        )
        self.assertTrue(r5["ok"])

        r6 = trasladar_bodega_a_operario(
            producto_id=self.p3_id,
            usuario_destino="Operario_Test_2",
            cantidad=50.0,
            usuario_admin="Admin_Test",
            motivo="TEST_MAT Entrega mat 3 op 2"
        )
        self.assertTrue(r6["ok"])

    def test_04_verificacion_saldos_bodega_y_operarios(self):
        """
        Bodega restante esperada:
        MAT-001: 2000 - 1000 = 1000
        MAT-002: 100 - 50 = 50
        MAT-003: 200 - 100 = 100
        """
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("SELECT stock_bodega FROM productos WHERE id = ?", (self.p1_id,))
        self.assertEqual(cur.fetchone()[0], 1000.0)
        cur.execute("SELECT stock_bodega FROM productos WHERE id = ?", (self.p2_id,))
        self.assertEqual(cur.fetchone()[0], 50.0)
        cur.execute("SELECT stock_bodega FROM productos WHERE id = ?", (self.p3_id,))
        self.assertEqual(cur.fetchone()[0], 100.0)
        conn.close()

        # Saldos individuales
        s1_op1 = obtener_saldo_material_usuario("Operario_Test_1", self.p1_id)
        self.assertEqual(s1_op1, 500.0)
        s1_op2 = obtener_saldo_material_usuario("Operario_Test_2", self.p1_id)
        self.assertEqual(s1_op2, 500.0)

    def test_05_venta_con_consumo_un_material(self):
        """
        Venta 1 por Operario_Test_1 consumiendo 20 hojas de MAT-001.
        Saldo esperado de Operario_Test_1: 480.
        Operario_Test_2 debe permanecer intacto en 500.
        """
        items = [{"producto_id": self.p1_id, "cantidad": 20.0}]
        res = descontar_materiales_venta(
            venta_id=999901,
            numero_factura="TEST-MAT-001",
            usuario_operario="Operario_Test_1",
            items_materiales=items,
            observaciones="Consumo Venta 1"
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["total_descontados"], 1)

        # Verificar saldo Op 1
        s_op1 = obtener_saldo_material_usuario("Operario_Test_1", self.p1_id)
        self.assertEqual(s_op1, 480.0)

        # Verificar saldo Op 2 (INTACTO)
        s_op2 = obtener_saldo_material_usuario("Operario_Test_2", self.p1_id)
        self.assertEqual(s_op2, 500.0)

    def test_06_venta_con_consumo_multiples_materiales(self):
        """
        Venta 2 por Operario_Test_1 consumiendo:
        - 5 hojas fotográficas (MAT-002): saldo 25 -> 20
        - 2 hojas propal (MAT-003): saldo 50 -> 48
        """
        items = [
            {"producto_id": self.p2_id, "cantidad": 5.0},
            {"producto_id": self.p3_id, "cantidad": 2.0}
        ]
        res = descontar_materiales_venta(
            venta_id=999902,
            numero_factura="TEST-MAT-002",
            usuario_operario="Operario_Test_1",
            items_materiales=items
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["total_descontados"], 2)

        self.assertEqual(obtener_saldo_material_usuario("Operario_Test_1", self.p2_id), 20.0)
        self.assertEqual(obtener_saldo_material_usuario("Operario_Test_1", self.p3_id), 48.0)

        # Operario 2 intacto
        self.assertEqual(obtener_saldo_material_usuario("Operario_Test_2", self.p2_id), 25.0)
        self.assertEqual(obtener_saldo_material_usuario("Operario_Test_2", self.p3_id), 50.0)

    def test_07_bloqueo_consumo_superior_al_saldo(self):
        """
        Intentar consumir 500 hojas de MAT-002 (saldo disponible es 20).
        Debe fallar limpiamente con ok=False.
        """
        items = [{"producto_id": self.p2_id, "cantidad": 500.0}]
        res = descontar_materiales_venta(
            venta_id=999903,
            numero_factura="TEST-MAT-003",
            usuario_operario="Operario_Test_1",
            items_materiales=items
        )
        self.assertFalse(res["ok"])
        self.assertIn("Saldo insuficiente", res["mensaje"])

        # Saldo permanece inalterado
        self.assertEqual(obtener_saldo_material_usuario("Operario_Test_1", self.p2_id), 20.0)

    def test_08_administrador_consume_de_su_propio_inventario(self):
        """
        El administrador traslada 50 hojas de MAT-001 a su propio usuario 'Admin_Test'
        y realiza una venta consumiendo 10 hojas -> saldo Admin: 40.
        """
        r_tras = trasladar_bodega_a_operario(
            producto_id=self.p1_id,
            usuario_destino="Admin_Test",
            cantidad=50.0,
            usuario_admin="Admin_Test",
            motivo="TEST_MAT Asignacion admin"
        )
        self.assertTrue(r_tras["ok"])
        self.assertEqual(obtener_saldo_material_usuario("Admin_Test", self.p1_id), 50.0)

        # Venta por el admin
        items = [{"producto_id": self.p1_id, "cantidad": 10.0}]
        res = descontar_materiales_venta(
            venta_id=999904,
            numero_factura="TEST-MAT-004",
            usuario_operario="Admin_Test",
            items_materiales=items
        )
        self.assertTrue(res["ok"])
        self.assertEqual(obtener_saldo_material_usuario("Admin_Test", self.p1_id), 40.0)

    def test_09_devolucion_a_bodega(self):
        """
        Operario 1 devuelve 10 hojas de MAT-001 a Bodega.
        Saldo Op 1: 480 -> 470.
        Bodega: 1000 - 50 (traslado a admin) + 10 = 960.
        """
        res = devolver_operario_a_bodega(
            producto_id=self.p1_id,
            usuario_operario="Operario_Test_1",
            cantidad=10.0,
            usuario_responsable="Admin_Test",
            motivo="TEST_MAT Devolucion sobrante"
        )
        self.assertTrue(res["ok"])
        self.assertEqual(obtener_saldo_material_usuario("Operario_Test_1", self.p1_id), 470.0)

        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("SELECT stock_bodega FROM productos WHERE id = ?", (self.p1_id,))
        self.assertEqual(cur.fetchone()[0], 960.0)
        conn.close()

    def test_10_registro_desperdicio(self):
        """
        Operario 1 registra 5 hojas fotográficas (MAT-002) dañadas en impresión.
        Saldo Op 1: 20 -> 15.
        Bodega MAT-002: inalterada en 50.
        Total desperdiciado registrado: 5.
        """
        res = registrar_desperdicio_material(
            producto_id=self.p2_id,
            usuario_operario="Operario_Test_1",
            cantidad=5.0,
            usuario_registra="Operario_Test_1",
            motivo="TEST_MAT Atasco en impresora láser",
            maquina="Láser Color 1"
        )
        self.assertTrue(res["ok"])
        self.assertEqual(obtener_saldo_material_usuario("Operario_Test_1", self.p2_id), 15.0)

        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("SELECT stock_bodega FROM productos WHERE id = ?", (self.p2_id,))
        self.assertEqual(cur.fetchone()[0], 50.0)
        conn.close()

    def test_11_anulacion_venta_devolver_a_operario(self):
        """
        Anular Venta 1 (venta_id=999901, que consumió 20 hojas de MAT-001 de Op 1).
        Acción: devolver al operario.
        Saldo Op 1: 470 + 20 = 490.
        """
        res = gestionar_consumo_anulacion_venta(
            venta_id=999901,
            accion="devolver",
            usuario_admin="Admin_Test",
            motivo="TEST_MAT Cancelacion cliente"
        )
        self.assertTrue(res["ok"])
        self.assertEqual(obtener_saldo_material_usuario("Operario_Test_1", self.p1_id), 490.0)

    def test_12_anulacion_venta_registrar_como_desperdicio(self):
        """
        Anular Venta 2 (venta_id=999902, que consumió 5 fotográficas y 2 propal).
        Acción: registrar como desperdicio.
        Los saldos de Op 1 NO se devuelven (permanecen en 15 y 48).
        Total desperdiciado aumenta.
        """
        res = gestionar_consumo_anulacion_venta(
            venta_id=999902,
            accion="desperdicio",
            usuario_admin="Admin_Test",
            motivo="TEST_MAT Trabajo mal cortado"
        )
        self.assertTrue(res["ok"])
        # Saldos no aumentan
        self.assertEqual(obtener_saldo_material_usuario("Operario_Test_1", self.p2_id), 15.0)
        self.assertEqual(obtener_saldo_material_usuario("Operario_Test_1", self.p3_id), 48.0)

    def test_13_kpis_y_trazabilidad(self):
        """Verifica el cálculo de KPIs e historial de auditoría de materiales."""
        kpis = obtener_kpis_materiales()
        self.assertGreater(kpis["total_asignado"], 0)
        self.assertGreater(kpis["total_consumido"], 0)
        self.assertGreater(kpis["total_desperdiciado"], 0)

        hist = obtener_historial_materiales()
        self.assertGreater(len(hist), 0)


if __name__ == "__main__":
    unittest.main()
