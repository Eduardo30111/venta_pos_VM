#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Suite: Fechas Contables vs Registro, Edición de Fechas y DINERO DE MÁS en Pagos Proveedores
Archivo: tests/test_proveedores_fechas_dinero_mas.py
"""

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface.database_manager import conectar_db, inicializar_base_datos
from interface.proveedores_manager import (
    recalcular_saldo_proveedor,
    liquidar_proveedor_db,
    actualizar_fecha_liquidacion_proveedor_db,
    registrar_dinero_de_mas_proveedor_db,
    obtener_historial_liquidaciones_proveedor,
    obtener_historial_ajustes_proveedor,
    normalizar_fecha,
    normalizar_hora
)


class TestProveedoresFechasDineroMas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inicializar_base_datos()
        import interface.proveedores_manager as pm
        pm.api = None
        try:
            from interface.sync_manager import sync_mgr
            sync_mgr._pausar_auto_disparo = True
        except Exception:
            pass

    def _limpiar(self):
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF;")
        cur.execute("DELETE FROM auditoria_liquidaciones WHERE proveedor_nombre LIKE 'PROV-TEST-%'")
        cur.execute("DELETE FROM ajustes_liquidaciones_proveedores WHERE proveedor_nombre LIKE 'PROV-TEST-%'")
        cur.execute("DELETE FROM liquidaciones_proveedores WHERE proveedor_nombre LIKE 'PROV-TEST-%'")
        cur.execute("DELETE FROM cuentas_por_pagar_proveedores WHERE proveedor_nombre LIKE 'PROV-TEST-%'")
        cur.execute("DELETE FROM gastos WHERE proveedor LIKE 'PROV-TEST-%' OR descripcion LIKE '%PROV-TEST-%'")
        cur.execute("DELETE FROM movimientos_caja WHERE descripcion LIKE '%PROV-TEST-%'")
        cur.execute("DELETE FROM movimientos_financieros WHERE concepto LIKE '%PROV-TEST-%'")
        cur.execute("DELETE FROM proveedores WHERE nombre LIKE 'PROV-TEST-%'")
        cur.execute("DELETE FROM ventas WHERE id_venta = 9901")
        conn.commit()
        conn.close()

    def _query(self, sql, params=()):
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute(sql, params)
        res = cur.fetchall()
        conn.close()
        return res

    def _query_one(self, sql, params=()):
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute(sql, params)
        res = cur.fetchone()
        conn.close()
        return res

    def setUp(self):
        self._limpiar()

        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF;")
        cur.execute("""
            INSERT OR REPLACE INTO ventas (id_venta, total_venta, metodo_pago, estado, fecha_venta, hora_venta, documento_cliente, operario)
            VALUES (9901, 250000.0, 'Efectivo', 'Completada', '2026-11-15', '10:00:00', '222222222222', 'AdminTest')
        """)
        cur.execute("""
            INSERT INTO proveedores (nombre, documento_nit, telefono, saldo_acumulado, estado)
            VALUES ('PROV-TEST-ANDES', 'NIT-900800700-1', '3109998877', 0.0, 'Activo')
        """)
        self.prov_id = cur.lastrowid
        self.prov_nombre = 'PROV-TEST-ANDES'

        cur.execute("""
            INSERT INTO cuentas_por_pagar_proveedores (
                proveedor_id, proveedor_nombre, id_venta, numero_venta,
                codigo_servicio, nombre_servicio, precio_venta, porcentaje_comision,
                monto_comision, monto_por_pagar, monto_pagado, saldo_pendiente,
                estado, fecha, hora, usuario
            ) VALUES (?, ?, 9901, 'V-009901', 'SRV-01', 'Servicio Técnico Especial', 250000.0, 20.0,
                      50000.0, 200000.0, 0.0, 200000.0, 'Pendiente', '2026-11-15', '10:00:00', 'AdminTest')
        """, (self.prov_id, self.prov_nombre))
        self.cxp_id = cur.lastrowid
        cur.execute("DELETE FROM ventas WHERE id_venta = 9901")
        conn.commit()
        conn.close()

        recalcular_saldo_proveedor(self.prov_id)

    def tearDown(self):
        self._limpiar()

    def test_01_liquidacion_fecha_contable_pasada_preserva_fecha_registro(self):
        """1. Liquidación con fecha contable en el pasado: afecta contabilidad en fecha_movimiento y preserva fecha_registro."""
        fecha_mov = "2026-11-20"
        hora_mov = "09:30:00"
        ahora_hoy = datetime.now().strftime("%Y-%m-%d")

        res = liquidar_proveedor_db(
            proveedor_id=self.prov_id,
            proveedor_nombre=self.prov_nombre,
            documento_nit="NIT-900800700-1",
            saldo_pendiente=200000.0,
            saldo_actual=200000.0,
            monto_abono=100000.0,
            metodo_pago="Efectivo",
            referencia_comprobante="REF-PAST-01",
            usuario_nombre="AdminTest",
            fecha_movimiento=fecha_mov,
            hora_movimiento=hora_mov,
            fecha=fecha_mov,
            hora=hora_mov
        )
        self.assertTrue(res.get("exito") or res.get("ok"), f"Fallo al liquidar: {res}")
        liq_id = res["id"]
        recibo = res["numero_recibo"]

        # Verificar datos en liquidaciones_proveedores
        row = self._query_one("""
            SELECT fecha, hora, fecha_registro, monto_liquidado, dinero_de_mas, monto_ajustado
            FROM liquidaciones_proveedores WHERE id = ?
        """, (liq_id,))
        self.assertIsNotNone(row)
        self.assertEqual(row[0], fecha_mov, "La fecha contable debe ser 2026-11-20")
        self.assertEqual(row[1], hora_mov, "La hora contable debe ser 09:30:00")
        self.assertTrue(str(row[2]).startswith(ahora_hoy), f"La fecha de registro debe ser hoy ({ahora_hoy}), valor: {row[2]}")
        self.assertEqual(float(row[3]), 100000.0)
        self.assertEqual(float(row[4]), 0.0)
        self.assertEqual(float(row[5]), 100000.0)

        # Verificar que el gasto contable se imputó al día del movimiento (2026-11-20), NO a hoy
        gasto_row = self._query_one("SELECT valor, fecha FROM gastos WHERE comprobante = ? AND proveedor = ?", (recibo, self.prov_nombre))
        self.assertIsNotNone(gasto_row, "Debe existir registro en gastos")
        self.assertEqual(gasto_row[1], fecha_mov, "El gasto debe estar fechado en 2026-11-20")
        self.assertEqual(float(gasto_row[0]), 100000.0)

        # Verificar que en movimientos_caja quedó registrado con la fecha del movimiento
        mc_row = self._query_one(
            "SELECT monto, fecha, tipo FROM movimientos_caja WHERE referencia_id = ? AND descripcion LIKE ?",
            (recibo, f"%{self.prov_nombre}%")
        )
        self.assertIsNotNone(mc_row, "Debe existir egreso en movimientos_caja")
        self.assertEqual(mc_row[1], fecha_mov)
        self.assertEqual(mc_row[2], "EGRESO")

    def test_02_editar_fecha_liquidacion_traslada_afectacion_contable(self):
        """2. Modificar fecha de liquidación: traslada gastos y caja a la nueva fecha, conservando fecha_registro."""
        res = liquidar_proveedor_db(
            proveedor_id=self.prov_id,
            proveedor_nombre=self.prov_nombre,
            saldo_pendiente=200000.0,
            saldo_actual=200000.0,
            monto_abono=80000.0,
            metodo_pago="Efectivo",
            usuario_nombre="AdminTest",
            fecha_movimiento="2026-11-20",
            hora_movimiento="14:00:00"
        )
        liq_id = res["id"]
        recibo = res["numero_recibo"]

        fecha_reg_original = self._query_one("SELECT fecha_registro FROM liquidaciones_proveedores WHERE id = ?", (liq_id,))[0]

        # Trasladar liquidación a 2026-11-18
        res_edit = actualizar_fecha_liquidacion_proveedor_db(
            liquidacion_id=liq_id,
            nueva_fecha="2026-11-18",
            nueva_hora="11:15:00",
            motivo="Pago realizado el miércoles 18",
            usuario="AuditorPOS"
        )
        self.assertTrue(res_edit.get("exito") or res_edit.get("ok"), f"Fallo al editar fecha: {res_edit}")

        # Comprobar que en liquidaciones_proveedores cambió la fecha contable
        row_mod = self._query_one("SELECT fecha, hora, fecha_registro FROM liquidaciones_proveedores WHERE id = ?", (liq_id,))
        self.assertEqual(row_mod[0], "2026-11-18", "La nueva fecha contable debe ser 2026-11-18")
        self.assertEqual(row_mod[1], "11:15:00", "La nueva hora contable debe ser 11:15:00")
        self.assertEqual(row_mod[2], fecha_reg_original, "La fecha de registro original DEBE PERMANECER INALTERADA")

        # Comprobar que el gasto se trasladó a 2026-11-18
        g_row = self._query_one("SELECT fecha, valor FROM gastos WHERE comprobante = ? AND proveedor = ?", (recibo, self.prov_nombre))
        self.assertEqual(g_row[0], "2026-11-18", "El gasto debe haber sido trasladado a 2026-11-18")
        self.assertEqual(float(g_row[1]), 80000.0, "El monto no debe alterarse")

        # Comprobar que movimientos_caja se trasladó a 2026-11-18
        mc_row = self._query_one("SELECT fecha, hora FROM movimientos_caja WHERE referencia_id = ?", (recibo,))
        self.assertEqual(mc_row[0], "2026-11-18")
        self.assertEqual(mc_row[1], "11:15:00")

        # Comprobar auditoría
        aud = self._query_one("""
            SELECT accion, fecha_anterior, fecha_nueva, usuario, motivo
            FROM auditoria_liquidaciones WHERE liquidacion_id = ?
        """, (liq_id,))
        self.assertIsNotNone(aud)
        self.assertEqual(aud[0], "EDITAR_FECHA")
        self.assertIn("2026-11-20", aud[1])
        self.assertIn("2026-11-18", aud[2])
        self.assertEqual(aud[3], "AuditorPOS")

    def test_03_dinero_de_mas_ajuste_contable_y_reapertura_lifo(self):
        """3. DINERO DE MÁS: reduce gastos con contra-asiento, repone caja física y restaura saldo proveedor en LIFO."""
        res_liq = liquidar_proveedor_db(
            proveedor_id=self.prov_id,
            proveedor_nombre=self.prov_nombre,
            saldo_pendiente=200000.0,
            saldo_actual=200000.0,
            monto_abono=100000.0,
            metodo_pago="Efectivo",
            usuario_nombre="AdminTest",
            fecha_movimiento="2026-11-21"
        )
        liq_id = res_liq["id"]
        recibo = res_liq["numero_recibo"]

        # El saldo pendiente del proveedor quedó en 100.000
        prov_post = recalcular_saldo_proveedor(self.prov_id)
        self.assertEqual(float(prov_post["saldo_pendiente"]), 100000.0)

        # Se detecta dinero de más por $35.000
        res_aj = registrar_dinero_de_mas_proveedor_db(
            liquidacion_id=liq_id,
            monto_sobrante=35000.0,
            motivo="Excedente de caja entregado de más",
            usuario="AuditorPOS",
            fecha_movimiento="2026-11-21"
        )
        self.assertTrue(res_aj.get("exito") or res_aj.get("ok"), f"Fallo en ajuste de dinero de más: {res_aj}")
        num_ajuste = res_aj["numero_ajuste"]

        # 1. Comprobar que en liquidaciones_proveedores se actualizaron dinero_de_mas y monto_ajustado
        l_row = self._query_one("SELECT monto_liquidado, dinero_de_mas, monto_ajustado FROM liquidaciones_proveedores WHERE id = ?", (liq_id,))
        self.assertEqual(float(l_row[0]), 100000.0, "El monto original de liquidación se conserva intacto")
        self.assertEqual(float(l_row[1]), 35000.0, "dinero_de_mas debe ser 35000.0")
        self.assertEqual(float(l_row[2]), 65000.0, "monto_ajustado neto debe ser 65000.0")

        # 2. Comprobar registro en ajustes_liquidaciones_proveedores
        aj_row = self._query_one("SELECT monto_ajuste, fecha_movimiento, usuario FROM ajustes_liquidaciones_proveedores WHERE numero_ajuste = ?", (num_ajuste,))
        self.assertIsNotNone(aj_row)
        self.assertEqual(float(aj_row[0]), 35000.0)
        self.assertEqual(aj_row[1], "2026-11-21")
        self.assertEqual(aj_row[2], "AuditorPOS")

        # 3. Comprobar contra-asiento en gastos (gasto negativo de -35.000 en 2026-11-21)
        cg_row = self._query_one("SELECT valor, fecha FROM gastos WHERE comprobante = ?", (num_ajuste,))
        self.assertIsNotNone(cg_row, "Debe existir contra-asiento en gastos")
        self.assertEqual(float(cg_row[0]), -35000.0, "El contra-asiento debe ser exactamente -35.000")
        self.assertEqual(cg_row[1], "2026-11-21")

        # 4. Comprobar saldo neto en gastos para ese proveedor: 100.000 - 35.000 = 65.000
        sum_gastos = float(self._query_one("SELECT SUM(valor) FROM gastos WHERE proveedor = ? AND fecha = '2026-11-21'", (self.prov_nombre,))[0] or 0.0)
        self.assertEqual(sum_gastos, 65000.0, "El total algebraico de gastos en 2026-11-21 debe ser 65.000")

        # 5. Comprobar reingreso a caja física ('AJUSTE' de +35.000)
        caja_aj = self._query_one("SELECT tipo, monto FROM movimientos_caja WHERE referencia_id = ?", (num_ajuste,))
        self.assertIsNotNone(caja_aj, "Debe existir reintegro en movimientos_caja")
        self.assertEqual(caja_aj[0], "AJUSTE")
        self.assertEqual(float(caja_aj[1]), 35000.0)

        # 6. Comprobar saldo del proveedor restaurado a 135.000 (100.000 + 35.000)
        saldo_prov = float(self._query_one("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (self.prov_id,))[0] or 0.0)
        self.assertEqual(saldo_prov, 135000.0, "El saldo del proveedor debe ser exactamente 135.000")

        # 7. Comprobar reapertura en cuentas_por_pagar_proveedores
        cxp_row = self._query_one("SELECT monto_pagado, saldo_pendiente FROM cuentas_por_pagar_proveedores WHERE id = ?", (self.cxp_id,))
        self.assertEqual(float(cxp_row[0]), 65000.0, "monto_pagado en CXP debe ser 65.000")
        self.assertEqual(float(cxp_row[1]), 135000.0, "saldo_pendiente en CXP debe ser 135.000")

    def test_04_validaciones_dinero_de_mas_limites_y_negativos(self):
        """4. Validaciones de DINERO DE MÁS: rechaza montos <= 0 o superiores al límite corregible."""
        res_liq = liquidar_proveedor_db(
            proveedor_id=self.prov_id,
            proveedor_nombre=self.prov_nombre,
            saldo_pendiente=200000.0,
            saldo_actual=200000.0,
            monto_abono=50000.0,
            metodo_pago="Efectivo",
            usuario_nombre="AdminTest"
        )
        liq_id = res_liq["id"]

        # Intento 1: Monto 0 o negativo
        res_neg = registrar_dinero_de_mas_proveedor_db(liq_id, monto_sobrante=0.0, motivo="Prueba 0")
        self.assertFalse(res_neg.get("exito"))
        self.assertIn("mayor a 0", res_neg.get("mensaje", "").lower())

        res_neg2 = registrar_dinero_de_mas_proveedor_db(liq_id, monto_sobrante=-15000.0, motivo="Prueba negativa")
        self.assertFalse(res_neg2.get("exito"))

        # Intento 2: Monto superior al saldo liquidado (50.001 > 50.000)
        res_exc = registrar_dinero_de_mas_proveedor_db(liq_id, monto_sobrante=50001.0, motivo="Excedente superior")
        self.assertFalse(res_exc.get("exito"))
        self.assertIn("supera", res_exc.get("mensaje", "").lower())

        # Ajuste válido de 20.000
        res_ok = registrar_dinero_de_mas_proveedor_db(liq_id, monto_sobrante=20000.0, motivo="Ajuste parte 1")
        self.assertTrue(res_ok.get("exito"))

        # Intento 3: Intentar ajustar 35.000 adicionales (solo quedan 30.000 corregibles)
        res_exc2 = registrar_dinero_de_mas_proveedor_db(liq_id, monto_sobrante=35000.0, motivo="Segundo ajuste excesivo")
        self.assertFalse(res_exc2.get("exito"))
        self.assertIn("supera", res_exc2.get("mensaje", "").lower())

    def test_05_historial_incluye_dinero_de_mas_y_netos(self):
        """5. Historial de liquidaciones reporta montos originales, dinero_de_mas y montos netos."""
        res_liq = liquidar_proveedor_db(
            proveedor_id=self.prov_id,
            proveedor_nombre=self.prov_nombre,
            saldo_pendiente=200000.0,
            saldo_actual=200000.0,
            monto_abono=60000.0,
            metodo_pago="Efectivo",
            usuario_nombre="AdminTest"
        )
        liq_id = res_liq["id"]
        registrar_dinero_de_mas_proveedor_db(liq_id, monto_sobrante=15000.0, motivo="Sobrante verificado")

        hist = obtener_historial_liquidaciones_proveedor()
        matching = [h for h in hist if h.get("id") == liq_id]
        self.assertTrue(len(matching) == 1)
        item = matching[0]

        self.assertEqual(float(item.get("monto_liquidado")), 60000.0)
        self.assertEqual(float(item.get("dinero_de_mas")), 15000.0)
        self.assertEqual(float(item.get("monto_neto")), 45000.0)

        # Historial de ajustes
        ajs = obtener_historial_ajustes_proveedor(liquidacion_id=liq_id)
        self.assertTrue(len(ajs) >= 1)
        self.assertEqual(float(ajs[0]["monto_ajuste"]), 15000.0)

    def test_06_normalizadores_fecha_y_hora(self):
        """6. Normalizadores robustos de fecha y hora para evitar errores de digitación."""
        self.assertEqual(normalizar_fecha("2026-11-20"), "2026-11-20")
        self.assertEqual(normalizar_fecha("20/11/2026"), "2026-11-20")
        self.assertEqual(normalizar_fecha("20-11-2026"), "2026-11-20")
        self.assertIsNone(normalizar_fecha("fecha-invalida"))

        self.assertEqual(normalizar_hora("08:30"), "08:30:00")
        self.assertEqual(normalizar_hora("18:45:10"), "18:45:10")

    def test_07_integridad_cierre_caja_historico(self):
        """7. Respeta y preserva la integridad de las sesiones de caja cerradas previamente."""
        # Crear una sesión de caja ya cerrada en 2026-11-19
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sesiones_caja (
                fecha_apertura, hora_apertura, usuario_apertura,
                fecha_cierre, hora_cierre, usuario_cierre,
                monto_inicial, monto_esperado_efectivo, monto_real_contado,
                diferencia, estado
            ) VALUES (
                '2026-11-19', '08:00:00', 'Cajero1',
                '2026-11-19', '20:00:00', 'Cajero1',
                100000.0, 550000.0, 550000.0, 0.0, 'Cerrada'
            )
        """)
        sesion_cerrada_id = cur.lastrowid
        conn.commit()
        conn.close()

        # Registrar liquidación en 2026-11-19
        res_liq = liquidar_proveedor_db(
            proveedor_id=self.prov_id,
            proveedor_nombre=self.prov_nombre,
            saldo_pendiente=200000.0,
            saldo_actual=200000.0,
            monto_abono=50000.0,
            metodo_pago="Efectivo",
            usuario_nombre="AdminTest",
            fecha_movimiento="2026-11-19"
        )
        self.assertTrue(res_liq.get("exito"))
        liq_id = res_liq["id"]

        # Verificar que la sesión de caja cerrada NO fue alterada ni forzada a 'Abierta'
        row_s = self._query_one("SELECT estado, monto_real_contado, fecha_cierre FROM sesiones_caja WHERE id = ?", (sesion_cerrada_id,))
        self.assertEqual(row_s[0], "Cerrada", "La sesión previa debe permanecer en estado 'Cerrada'")
        self.assertEqual(float(row_s[1]), 550000.0, "El arqueo de cierre original no debe ser mutado destructivamente")

        # Ajuste de dinero de más
        res_aj = registrar_dinero_de_mas_proveedor_db(
            liquidacion_id=liq_id,
            monto_sobrante=10000.0,
            motivo="Sobrante caja 19",
            usuario="AuditorPOS",
            fecha_movimiento="2026-11-19"
        )
        self.assertTrue(res_aj.get("exito"))

        # Verificar auditoría registrada
        aud = self._query_one("""
            SELECT accion, usuario FROM auditoria_liquidaciones
            WHERE liquidacion_id = ? AND accion = 'DINERO_DE_MAS'
        """, (liq_id,))
        self.assertIsNotNone(aud)
        self.assertEqual(aud[1], "AuditorPOS")


if __name__ == "__main__":
    unittest.main()
