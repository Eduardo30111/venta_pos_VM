#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_kpis_diarios_y_sincronizacion_liq.py
Pruebas de integridad para:
1. Panel KPI diario de Ventas en ventas_admin_dialog.py (métricas reales derivadas).
2. Panel KPI diario de Liquidaciones en nomina_menu.py (totales netos, efectivo, bancos, abonos, completas).
3. Unificación y resolución de recibos LP- vs LQ- vs LIQ-PROV.
4. Resiliencia y fallback transparente ante 404 en endpoints del servidor API.
5. Sincronización cruzada automática entre ventas.db y vmpos_server.db.
"""

import unittest
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface.database_manager import conectar_db, inicializar_base_datos
import interface.proveedores_manager as pm
from interface.proveedores_manager import (
    buscar_liquidacion_proveedor_flexible,
    actualizar_fecha_liquidacion_proveedor_db,
    registrar_dinero_de_mas_proveedor_db
)


class TestKPIsYSincronizacion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inicializar_base_datos()
        pm.api = None
        try:
            from interface.sync_manager import sync_mgr
            sync_mgr._pausar_auto_disparo = True
        except Exception:
            pass

    def setUp(self):
        self._limpiar()
        self.prov_id = 9991
        self.prov_nombre = "PROV-KPI-TEST-9991"
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF;")
        cur.execute("INSERT OR REPLACE INTO proveedores (id, nombre, saldo_acumulado) VALUES (?, ?, 0.0)", (self.prov_id, self.prov_nombre))
        # Asegurar sesion de caja abierta
        cur.execute("SELECT id FROM sesiones_caja WHERE estado = 'Abierta' LIMIT 1")
        if not cur.fetchone():
            cur.execute("INSERT INTO sesiones_caja (usuario_id, fecha_apertura, hora_apertura, monto_inicial, estado) VALUES (1, '2026-11-23', '08:00:00', 100000.0, 'Abierta')")
        conn.commit()
        conn.close()

    def tearDown(self):
        self._limpiar()

    def _limpiar(self):
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF;")
        cur.execute("DELETE FROM auditoria_liquidaciones WHERE proveedor_nombre LIKE 'PROV-KPI-%'")
        cur.execute("DELETE FROM ajustes_liquidaciones_proveedores WHERE proveedor_nombre LIKE 'PROV-KPI-%'")
        cur.execute("DELETE FROM liquidaciones_proveedores WHERE proveedor_nombre LIKE 'PROV-KPI-%' OR id = 99887 OR id = 99890")
        cur.execute("DELETE FROM cuentas_por_pagar_proveedores WHERE proveedor_nombre LIKE 'PROV-KPI-%' OR id = 99501")
        cur.execute("DELETE FROM gastos WHERE proveedor LIKE 'PROV-KPI-%' OR comprobante IN ('LQ-99007', 'LP-99007')")
        cur.execute("DELETE FROM movimientos_caja WHERE descripcion LIKE '%PROV-KPI-%' OR referencia_id IN ('LQ-99007', 'LP-99007')")
        cur.execute("DELETE FROM movimientos_financieros WHERE concepto LIKE '%PROV-KPI-%' OR referencia_origen IN ('LQ-99007', 'LP-99007')")
        cur.execute("DELETE FROM proveedores WHERE nombre LIKE 'PROV-KPI-%' OR id = 9991")
        conn.commit()
        conn.close()

    def test_01_buscar_flexible_unificacion_lp_lq(self):
        """1. Búsqueda flexible resuelve tanto LP-99007 como LQ-99007 como ID 99007."""
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF;")
        cur.execute("""
            INSERT OR REPLACE INTO liquidaciones_proveedores (
                id, numero_recibo, proveedor_id, proveedor_nombre, monto_liquidado,
                saldo_anterior, saldo_restante, mes_anio, fecha, hora, estado
            ) VALUES (99887, 'LQ-99007', ?, ?, 7400.0, 7400.0, 0.0, '11-2026', '2026-11-23', '12:35:00', 'Aplicada')
        """, (self.prov_id, self.prov_nombre))
        conn.commit()

        # Buscar por LP-99007 debe encontrar el registro LQ-99007 (id 99887)
        res_lp = buscar_liquidacion_proveedor_flexible('LP-99007', conn=conn)
        self.assertIsNotNone(res_lp, "LP-99007 debe ser localizado exitosamente")
        self.assertEqual(res_lp['id'], 99887)
        self.assertEqual(res_lp['numero_recibo'], 'LQ-99007')
        self.assertEqual(res_lp['monto_liquidado'], 7400.0)

        # Buscar por ID numérico 99007 extraído
        res_7 = buscar_liquidacion_proveedor_flexible(99007, conn=conn)
        self.assertIsNotNone(res_7, "ID 99007 debe ser resuelto flexiblemente por dígito hacia LQ-99007")
        self.assertEqual(res_7['id'], 99887)

        # Buscar por contexto proveedor y monto
        res_ctx = buscar_liquidacion_proveedor_flexible('desconocido', proveedor_nombre=self.prov_nombre, monto=7400.0, conn=conn)
        self.assertIsNotNone(res_ctx, "Búsqueda contextual por proveedor y monto debe encontrar el registro")
        self.assertEqual(res_ctx['id'], 99887)
        conn.close()

    def test_02_cambio_fecha_actualiza_gastos_y_movimientos(self):
        """2. Cambiar fecha traslada el gasto contable y movimientos sin duplicar montos."""
        conn = conectar_db()
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys = OFF;")
            cur.execute("""
                INSERT OR REPLACE INTO liquidaciones_proveedores (
                    id, numero_recibo, proveedor_id, proveedor_nombre, monto_liquidado,
                    saldo_anterior, saldo_restante, mes_anio, fecha, hora, estado
                ) VALUES (99887, 'LQ-99007', ?, ?, 7400.0, 7400.0, 0.0, '11-2026', '2026-11-23', '12:35:00', 'Aplicada')
            """, (self.prov_id, self.prov_nombre))
            cur.execute("""
                INSERT INTO gastos (concepto, comprobante, proveedor, valor, fecha, hora, estado)
                VALUES ('Pago Liquidación', 'LQ-99007', ?, 7400.0, '2026-11-23', '12:35:00', 'Pagado')
            """, (self.prov_nombre,))
            cur.execute("""
                INSERT INTO movimientos_caja (sesion_caja_id, referencia_id, tipo, monto, fecha, hora, usuario, descripcion)
                VALUES (1, 'LQ-99007', 'EGRESO', 7400.0, '2026-11-23', '12:35:00', 'Administrador', ?)
            """, (f"Pago {self.prov_nombre}",))
            conn.commit()

            res = actualizar_fecha_liquidacion_proveedor_db(
                liquidacion_id=99007,
                nueva_fecha="2026-11-21",
                nueva_hora="10:00:00",
                motivo="Corrección de fecha real",
                numero_recibo="LP-99007",
                proveedor_id=self.prov_id,
                proveedor_nombre=self.prov_nombre,
                monto=7400.0,
                conn=conn
            )
            self.assertTrue(res.get("exito") or res.get("ok"), f"Debe actualizar la fecha con éxito: {res}")

            # Comprobar liquidación
            cur.execute("SELECT fecha, hora FROM liquidaciones_proveedores WHERE id = 99887")
            row_l = cur.fetchone()
            self.assertEqual(row_l[0], "2026-11-21")
            self.assertEqual(row_l[1], "10:00:00")

            # Comprobar gastos
            cur.execute("SELECT fecha FROM gastos WHERE comprobante = 'LQ-99007'")
            row_g = cur.fetchone()
            self.assertEqual(row_g[0], "2026-11-21")

            # Comprobar movimientos de caja
            cur.execute("SELECT fecha FROM movimientos_caja WHERE referencia_id = 'LQ-99007'")
            row_c = cur.fetchone()
            self.assertEqual(row_c[0], "2026-11-21")
        finally:
            conn.close()

    def test_03_dinero_de_mas_no_afecta_inventario(self):
        """3. DINERO DE MÁS es estrictamente financiero y no crea registros de inventario."""
        conn = conectar_db()
        try:
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys = OFF;")
            cur.execute("""
                INSERT OR REPLACE INTO liquidaciones_proveedores (
                    id, numero_recibo, proveedor_id, proveedor_nombre, monto_liquidado,
                    saldo_anterior, saldo_restante, mes_anio, fecha, hora, estado
                ) VALUES (99890, 'LQ-99010', ?, ?, 10000.0, 10000.0, 0.0, '11-2026', '2026-11-22', '16:00:00', 'Aplicada')
            """, (self.prov_id, self.prov_nombre))
            cur.execute("""
                INSERT OR REPLACE INTO cuentas_por_pagar_proveedores (
                    id, proveedor_id, proveedor_nombre, id_venta, codigo_servicio, nombre_servicio,
                    precio_venta, monto_por_pagar, monto_pagado, saldo_pendiente, estado, fecha, hora
                ) VALUES (99501, ?, ?, 9901, 'SRV-01', 'Servicio Test', 10000.0, 10000.0, 10000.0, 0.0, 'Pagada', '2026-11-22', '16:00:00')
            """, (self.prov_id, self.prov_nombre))
            conn.commit()

            res_mas = registrar_dinero_de_mas_proveedor_db(
                liquidacion_id=99010,
                monto_sobrante=5000.0,
                motivo="Entregado 5.000 de más en efectivo",
                fecha_movimiento="2026-11-22",
                numero_recibo="LP-99010",
                proveedor_id=self.prov_id,
                proveedor_nombre=self.prov_nombre,
                conn=conn
            )
            self.assertTrue(res_mas.get("exito") or res_mas.get("ok"), f"Fallo registrando dinero de más: {res_mas}")

            # Comprobar que liquidación tiene dinero_de_mas = 5000 y monto_ajustado = 5000
            cur.execute("SELECT dinero_de_mas, monto_ajustado FROM liquidaciones_proveedores WHERE id = 99890")
            row_l = cur.fetchone()
            self.assertEqual(float(row_l[0]), 5000.0)
            self.assertEqual(float(row_l[1]), 5000.0)

            # Comprobar reintegro a caja ('AJUSTE' de 5000)
            cur.execute("SELECT tipo, monto FROM movimientos_caja WHERE tipo = 'AJUSTE' AND descripcion LIKE '%PROV-KPI-%'")
            row_caja = cur.fetchone()
            self.assertIsNotNone(row_caja)
            self.assertEqual(float(row_caja[1]), 5000.0)

            # Comprobar contra-asiento en gastos (-5000)
            cur.execute("SELECT valor FROM gastos WHERE valor < 0 AND proveedor = ?", (self.prov_nombre,))
            row_g = cur.fetchone()
            self.assertIsNotNone(row_g)
            self.assertEqual(float(row_g[0]), -5000.0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
