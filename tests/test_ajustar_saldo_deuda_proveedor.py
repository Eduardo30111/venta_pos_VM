#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pruebas de integridad para la función administrativa:
AJUSTAR DEUDA / CORREGIR SALDO DE PROVEEDORES (VmPOS)
Archivo: tests/test_ajustar_saldo_deuda_proveedor.py
"""

import unittest
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface.database_manager import conectar_db, inicializar_base_datos
from interface.proveedores_manager import (
    recalcular_saldo_proveedor,
    ajustar_saldo_deuda_proveedor_db,
    obtener_historial_ajustes_saldos_proveedor,
    obtener_detalle_proveedor_completo
)
from interface.usuarios_db import conectar_usuarios_db, crear_tablas_iniciales


class TestAjustarSaldoDeudaProveedor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inicializar_base_datos()
        try:
            crear_tablas_iniciales()
        except Exception:
            pass
        import interface.proveedores_manager as pm
        pm.api = None
        try:
            from interface.sync_manager import sync_mgr
            sync_mgr._pausar_auto_disparo = True
        except Exception:
            pass

    def setUp(self):
        self._limpiar()
        self.prov_id = 9988
        self.prov_nombre = "PROV-TEST-AJUSTE-9988"
        self.admin_user = "admin_ajuste_test"
        self.admin_pass = "TestAdminPass123!"

        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF;")

        # Asegurar usuario administrador para pruebas en usuarios.db
        import hashlib
        conn_u = conectar_usuarios_db()
        cur_u = conn_u.cursor()
        cur_u.execute("DELETE FROM usuarios WHERE usuario = ?", (self.admin_user,))
        p_hash = hashlib.sha256(self.admin_pass.encode("utf-8")).hexdigest()
        cur_u.execute("""
            INSERT INTO usuarios (usuario, nombre, apellidos, password, rol, estado)
            VALUES (?, 'Admin', 'Test', ?, 'Administrador', 'Activo')
        """, (self.admin_user, p_hash))
        conn_u.commit()
        conn_u.close()

        # Crear proveedor con deuda inicial simulada de $6.400 COP
        # Ventas: 91.700 COP, Pagado: 85.300 COP, Pendiente: 6.400 COP
        cur.execute("""
            INSERT OR REPLACE INTO proveedores (id, nombre, documento_nit, saldo_acumulado, total_ventas, total_pagado)
            VALUES (?, ?, '900123456', 6400.0, 91700.0, 85300.0)
        """, (self.prov_id, self.prov_nombre))

        # Crear cuentas por pagar que suman exactamente 6.400 COP pendientes
        cur.execute("""
            INSERT INTO cuentas_por_pagar_proveedores (
                proveedor_id, proveedor_nombre, id_venta, codigo_servicio, nombre_servicio,
                precio_venta, monto_por_pagar, monto_pagado, saldo_pendiente, estado, fecha, hora
            ) VALUES (?, ?, 7701, 'SRV-01', 'Servicio A', 50000.0, 50000.0, 50000.0, 0.0, 'Pagada', '2026-11-20', '10:00:00')
        """, (self.prov_id, self.prov_nombre))
        cur.execute("""
            INSERT INTO cuentas_por_pagar_proveedores (
                proveedor_id, proveedor_nombre, id_venta, codigo_servicio, nombre_servicio,
                precio_venta, monto_por_pagar, monto_pagado, saldo_pendiente, estado, fecha, hora
            ) VALUES (?, ?, 7702, 'SRV-02', 'Servicio B', 41700.0, 41700.0, 35300.0, 6400.0, 'Abonada', '2026-11-21', '11:00:00')
        """, (self.prov_id, self.prov_nombre))

        conn.commit()
        conn.close()

    def tearDown(self):
        self._limpiar()

    def _limpiar(self):
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF;")
        cur.execute("DELETE FROM ajustes_saldos_proveedores WHERE proveedor_id = 9988 OR proveedor_nombre LIKE 'PROV-TEST-AJUSTE-%'")
        cur.execute("DELETE FROM cuentas_por_pagar_proveedores WHERE proveedor_id = 9988 OR proveedor_nombre LIKE 'PROV-TEST-AJUSTE-%'")
        cur.execute("DELETE FROM liquidaciones_proveedores WHERE proveedor_id = 9988 OR proveedor_nombre LIKE 'PROV-TEST-AJUSTE-%'")
        cur.execute("DELETE FROM auditoria_liquidaciones WHERE proveedor_id = 9988 OR proveedor_nombre LIKE 'PROV-TEST-AJUSTE-%'")
        cur.execute("DELETE FROM proveedores WHERE id = 9988 OR nombre LIKE 'PROV-TEST-AJUSTE-%'")
        conn.commit()
        conn.close()

        conn_u = conectar_usuarios_db()
        cur_u = conn_u.cursor()
        cur_u.execute("DELETE FROM usuarios WHERE usuario = 'admin_ajuste_test'")
        conn_u.commit()
        conn_u.close()

    def test_01_seguridad_contrasena_incorrecta(self):
        """1. Rechaza la operación si la contraseña de administrador es incorrecta."""
        res = ajustar_saldo_deuda_proveedor_db(
            proveedor_id=self.prov_id,
            tipo_ajuste="AJUSTAR_A_CERO",
            nuevo_saldo=0.0,
            motivo="Corrección de error de liquidación",
            usuario_admin=self.admin_user,
            password_admin="PasswordErronea999"
        )
        self.assertFalse(res.get("exito"), "Debe rechazar la operación por clave incorrecta")
        self.assertIn("Acceso Denegado", res.get("mensaje", ""))

    def test_02_validacion_motivo_obligatorio(self):
        """2. Rechaza la operación si el motivo está vacío o es menor a 5 caracteres."""
        res = ajustar_saldo_deuda_proveedor_db(
            proveedor_id=self.prov_id,
            tipo_ajuste="AJUSTAR_A_CERO",
            nuevo_saldo=0.0,
            motivo="abc",
            usuario_admin=self.admin_user,
            password_admin=self.admin_pass
        )
        self.assertFalse(res.get("exito"), "Debe exigir motivo de mínimo 5 caracteres")
        self.assertIn("motivo", res.get("mensaje", "").lower())

    def test_03_ajustar_deuda_a_cero_caso_real_6400(self):
        """3. Caso concreto: Proveedor con 6.400 COP pendientes pasa a $0 COP sin generar egresos en caja."""
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM gastos WHERE concepto LIKE '%Ajuste%'")
        gastos_antes = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM movimientos_caja WHERE tipo = 'EGRESO'")
        egresos_caja_antes = cur.fetchone()[0]
        conn.close()

        # Ejecutar ajuste administrativo a cero
        res = ajustar_saldo_deuda_proveedor_db(
            proveedor_id=self.prov_id,
            tipo_ajuste="AJUSTAR_A_CERO",
            nuevo_saldo=0.0,
            motivo="Corrección administrativa de saldo por desfase de liquidación previa",
            usuario_admin=self.admin_user,
            password_admin=self.admin_pass
        )
        self.assertTrue(res.get("exito"), f"El ajuste a cero debe ser exitoso: {res}")
        self.assertEqual(res.get("saldo_anterior"), 6400.0)
        self.assertEqual(res.get("saldo_final"), 0.0)
        self.assertEqual(res.get("monto_ajuste"), 6400.0)

        # Verificar persistencia en base de datos
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("SELECT saldo_acumulado, total_ventas, total_pagado FROM proveedores WHERE id = ?", (self.prov_id,))
        p_row = cur.fetchone()
        self.assertEqual(float(p_row[0]), 0.0, "Saldo acumulado debe ser 0.0 COP")
        self.assertEqual(float(p_row[1]), 91700.0, "Total de ventas debe mantenerse intacto (91.700 COP)")
        self.assertEqual(float(p_row[2]), 85300.0, "Total pagado debe mantenerse intacto (85.300 COP)")

        # Verificar que cuentas por pagar quedaron saldadas a 0.0
        cur.execute("SELECT SUM(saldo_pendiente) FROM cuentas_por_pagar_proveedores WHERE proveedor_id = ? AND estado != 'Anulada'", (self.prov_id,))
        sum_pend = float(cur.fetchone()[0] or 0.0)
        self.assertEqual(sum_pend, 0.0, "La suma de saldos pendientes en cuentas_por_pagar debe ser 0.0")

        # Verificar que NO se crearon egresos falsos en caja física
        cur.execute("SELECT COUNT(*) FROM movimientos_caja WHERE tipo = 'EGRESO'")
        egresos_caja_despues = cur.fetchone()[0]
        self.assertEqual(egresos_caja_despues, egresos_caja_antes, "NO debe inventar egresos en efectivo en caja física")

        # Verificar que se registró en la tabla de auditoría de ajustes
        cur.execute("SELECT numero_ajuste, saldo_anterior, monto_ajuste, saldo_final, usuario FROM ajustes_saldos_proveedores WHERE proveedor_id = ?", (self.prov_id,))
        aj_row = cur.fetchone()
        self.assertIsNotNone(aj_row, "Debe existir registro en ajustes_saldos_proveedores")
        self.assertEqual(float(aj_row[1]), 6400.0)
        self.assertEqual(float(aj_row[2]), 6400.0)
        self.assertEqual(float(aj_row[3]), 0.0)
        self.assertEqual(aj_row[4], self.admin_user)

        # Recalcular saldo nuevamente para confirmar que es inmune a recálculos futuros
        rec = recalcular_saldo_proveedor(self.prov_id, conn=conn)
        self.assertEqual(rec["saldo_pendiente"], 0.0, "Recálculo futuro debe arrojar exactamente 0.0 COP")
        conn.close()

    def test_04_ajustar_a_valor_especifico(self):
        """4. Ajustar saldo a un valor específico (de 6.400 a 2.000 COP)."""
        res = ajustar_saldo_deuda_proveedor_db(
            proveedor_id=self.prov_id,
            tipo_ajuste="VALOR_ESPECIFICO",
            nuevo_saldo=2000.0,
            motivo="Ajuste parcial por nota de crédito externa",
            usuario_admin=self.admin_user,
            password_admin=self.admin_pass
        )
        self.assertTrue(res.get("exito"), f"El ajuste específico debe ser exitoso: {res}")
        self.assertEqual(res.get("saldo_anterior"), 6400.0)
        self.assertEqual(res.get("saldo_final"), 2000.0)
        self.assertEqual(res.get("monto_ajuste"), 4400.0)

        # Verificar recálculo
        rec = recalcular_saldo_proveedor(self.prov_id)
        self.assertEqual(rec["saldo_pendiente"], 2000.0)

    def test_05_historial_y_resumen_completo(self):
        """5. Consulta de ficha completa e historial de ajustes administrativos."""
        # Aplicar un ajuste previo
        ajustar_saldo_deuda_proveedor_db(
            proveedor_id=self.prov_id,
            tipo_ajuste="AJUSTAR_A_CERO",
            nuevo_saldo=0.0,
            motivo="Ajuste para probar historial",
            usuario_admin=self.admin_user,
            password_admin=self.admin_pass
        )

        hist_aj = obtener_historial_ajustes_saldos_proveedor(self.prov_id)
        self.assertTrue(len(hist_aj) >= 1, "Debe retornar al menos un ajuste administrativo registrado")
        self.assertEqual(hist_aj[0]["saldo_final"], 0.0)

        detalle = obtener_detalle_proveedor_completo(self.prov_id)
        self.assertIsNotNone(detalle)
        self.assertEqual(detalle["nombre"], self.prov_nombre)
        self.assertEqual(detalle["saldo_pendiente"], 0.0)
        self.assertEqual(detalle["total_ventas"], 91700.0)
        self.assertEqual(detalle["total_pagado"], 85300.0)
        self.assertTrue(len(detalle["historial_ajustes"]) >= 1)


if __name__ == "__main__":
    unittest.main()
