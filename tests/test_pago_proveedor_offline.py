#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest
import os
import sqlite3
import tempfile
from interface.database_manager import inicializar_base_datos, conectar_db
from interface.proveedores_manager import (
    liquidar_proveedor_db,
    recalcular_saldo_proveedor,
    obtener_resumen_proveedores
)
from interface.sync_manager import sync_mgr


class TestPagoProveedorOffline(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.test_db_path = os.path.join(self.tmp_dir, "test_ventas.db")
        os.environ["VMPOS_DB_VENTAS"] = self.test_db_path
        inicializar_base_datos(self.test_db_path)

    def tearDown(self):
        try:
            if os.path.exists(self.test_db_path):
                os.remove(self.test_db_path)
            os.rmdir(self.tmp_dir)
        except Exception:
            pass

    def test_pago_proveedor_existente_con_saldo_legacy(self):
        """Prueba que un proveedor con saldo legacy puede liquidarse sin fallar."""
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO proveedores (id, nombre, documento_nit, saldo_acumulado, estado)
            VALUES (1, 'Omara Sierra', '32816084', 6200.0, 'Activo')
        """)
        conn.commit()

        # Liquidar abono parcial de 2000
        res = liquidar_proveedor_db(
            proveedor_id=1,
            proveedor_nombre='Omara Sierra',
            documento_nit='32816084',
            saldo_pendiente=6200.0,
            monto_abono=2000.0,
            metodo_pago='Efectivo',
            referencia_comprobante='REC-001',
            usuario_nombre='Administrador',
            notas='Abono parcial de prueba',
            conn=conn
        )
        self.assertTrue(res.get("exito"), f"Fallo al liquidar: {res}")
        self.assertEqual(res.get("monto_pagado"), 2000.0)
        self.assertEqual(res.get("saldo_restante"), 4200.0)

        # Liquidar el saldo restante (4200)
        res2 = liquidar_proveedor_db(
            proveedor_id=1,
            proveedor_nombre='Omara Sierra',
            documento_nit='32816084',
            saldo_pendiente=4200.0,
            monto_abono=4200.0,
            metodo_pago='Efectivo',
            conn=conn
        )
        self.assertTrue(res2.get("exito"))
        self.assertEqual(res2.get("saldo_restante"), 0.0)
        self.assertEqual(res2.get("tipo_pago"), "Total")
        conn.close()

    def test_auto_aprovisionamiento_proveedor_no_existente(self):
        """Prueba que si el proveedor no existía en la base local, se auto-aprovisiona y no arroja error 'no encontrado'."""
        conn = conectar_db()
        # ID 99 no existe en la base
        res = liquidar_proveedor_db(
            proveedor_id=99,
            proveedor_nombre='Proveedor Remoto Auto',
            documento_nit='900123456',
            saldo_pendiente=15000.0,
            monto_abono=15000.0,
            metodo_pago='Transferencia',
            conn=conn
        )
        self.assertTrue(res.get("exito"), f"Auto-aprovisionamiento falló: {res}")
        self.assertEqual(res.get("saldo_restante"), 0.0)

        # Verificar que quedó registrado en proveedores y liquidaciones
        cur = conn.cursor()
        cur.execute("SELECT nombre, estado FROM proveedores WHERE id = 99")
        p = cur.fetchone()
        self.assertIsNotNone(p)
        self.assertEqual(p[0], 'Proveedor Remoto Auto')

        cur.execute("SELECT COUNT(id) FROM liquidaciones_proveedores WHERE proveedor_id = 99")
        self.assertEqual(cur.fetchone()[0], 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
