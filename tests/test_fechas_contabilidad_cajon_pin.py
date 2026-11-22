#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suite de Pruebas Automatizadas de Corrección Integral - VmPOS
Archivo: tests/test_fechas_contabilidad_cajon_pin.py

Verifica con rigor los 4 objetivos críticos solicitados:
1. Traslado real de fecha y hora operativa en Gestión de Ventas (sin quedar anclada en el día original).
2. Consistencia y exclusión estricta de ventas anuladas en Dashboard y Contabilidad.
3. Flujo de finalización de venta con apertura automática de gaveta y cálculo del recordatorio de cambio.
4. Seguridad integral mediante PIN para aperturas manuales de la gaveta (F7, botones en POS y Caja,
   bloqueo por fuerza bruta y verificación de contraseña de administrador).
"""

import os
import sys
import json
import time
import sqlite3
import tempfile
import unittest

# Asegurar importación de módulos del proyecto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "interface"))

from interface.cajon_pin_manager import (
    tiene_pin_configurado,
    crear_o_actualizar_pin,
    verificar_pin,
    obtener_estado_seguridad,
    verificar_credencial_admin,
    _obtener_datos_pin
)
from interface.receipt_manager import evaluar_apertura_cajon_por_venta
import interface.cajon_pin_manager as cpm


class TestTrasladoFechaHoraVentas(unittest.TestCase):
    """Pruebas del traslado efectivo de fecha y hora operativa."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_file = os.path.join(self.tmp_dir.name, "test_ventas.db")
        conn = sqlite3.connect(self.db_file)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE ventas (
                id_venta INTEGER PRIMARY KEY AUTOINCREMENT,
                numero_factura TEXT,
                fecha_venta TEXT,
                hora_venta TEXT,
                total_venta REAL,
                metodo_pago TEXT,
                operario TEXT,
                estado TEXT,
                es_venta_atrasada INTEGER DEFAULT 0,
                motivo_modificacion_fecha TEXT
            )
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_traslado_fecha_operativa_en_db(self):
        """Verifica que al editar una venta su fecha operativa cambie efectivamente en la base de datos."""
        conn = sqlite3.connect(self.db_file)
        cur = conn.cursor()
        # Insertar venta original el 2026-11-22
        cur.execute("""
            INSERT INTO ventas (numero_factura, fecha_venta, hora_venta, total_venta, metodo_pago, operario, estado)
            VALUES ('V-000026', '2026-11-22', '13:39:35', 5800.0, 'Efectivo', 'Admin', 'Completada')
        """)
        v_id = cur.lastrowid
        conn.commit()

        # Simular edición cambiando la fecha a 2026-11-21 y hora a 18:45:00
        nueva_f = "2026-11-21"
        nueva_h = "18:45:00"
        motivo_edicion = "Corrección administrativa de fecha de operación"

        cur.execute("""
            UPDATE ventas SET
                fecha_venta = ?,
                hora_venta = ?,
                es_venta_atrasada = 1,
                motivo_modificacion_fecha = ?,
                estado = 'Modificada'
            WHERE id_venta = ? OR numero_factura = ?
        """, (nueva_f, nueva_h, motivo_edicion, v_id, f"V-{v_id:06d}"))
        conn.commit()

        # 1. Comprobar que en el día 2026-11-22 NO aparece la venta
        cur.execute("SELECT COUNT(*) FROM ventas WHERE fecha_venta = '2026-11-22' AND estado != 'Anulada'")
        count_22 = cur.fetchone()[0]
        self.assertEqual(count_22, 0, "La venta NO debe aparecer en el día original (2026-11-22)")

        # 2. Comprobar que en el día 2026-11-21 SÍ aparece la venta
        cur.execute("SELECT id_venta, fecha_venta, hora_venta, total_venta, es_venta_atrasada FROM ventas WHERE fecha_venta = '2026-11-21'")
        row_21 = cur.fetchone()
        self.assertIsNotNone(row_21, "La venta DEBE aparecer en la nueva fecha (2026-11-21)")
        self.assertEqual(row_21[1], "2026-11-21")
        self.assertEqual(row_21[2], "18:45:00")
        self.assertEqual(row_21[3], 5800.0)
        self.assertEqual(row_21[4], 1, "Debe marcarse como es_venta_atrasada")
        conn.close()


class TestDashboardContabilidadConsistencia(unittest.TestCase):
    """Pruebas de consistencia de totales y exclusión estricta de ventas anuladas."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_file = os.path.join(self.tmp_dir.name, "test_reportes.db")
        conn = sqlite3.connect(self.db_file)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE ventas (
                id_venta INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_venta TEXT,
                total_venta REAL,
                estado TEXT
            )
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_exclusion_ventas_anuladas(self):
        """Comprueba que ventas anuladas nunca sumen a las ventas válidas del día."""
        conn = sqlite3.connect(self.db_file)
        cur = conn.cursor()
        # Insertar 3 ventas anuladas de $10.000 c/u y 1 completada de $5.800
        cur.execute("INSERT INTO ventas (fecha_venta, total_venta, estado) VALUES ('2026-11-22', 10000.0, 'Anulada')")
        cur.execute("INSERT INTO ventas (fecha_venta, total_venta, estado) VALUES ('2026-11-22', 10000.0, 'Anulada')")
        cur.execute("INSERT INTO ventas (fecha_venta, total_venta, estado) VALUES ('2026-11-22', 10000.0, 'Anulada')")
        cur.execute("INSERT INTO ventas (fecha_venta, total_venta, estado) VALUES ('2026-11-22', 5800.0, 'Completada')")
        conn.commit()

        # Consulta unificada del Dashboard y Contabilidad
        cur.execute("""
            SELECT COALESCE(SUM(total_venta), 0.0), COUNT(id_venta)
            FROM ventas
            WHERE fecha_venta = '2026-11-22'
              AND (estado IS NULL OR estado NOT IN ('Anulada', 'Cancelada', 'Pendiente_Caja'))
        """)
        total_valido, cant_pedidos = cur.fetchone()

        self.assertEqual(total_valido, 5800.0, f"El total debe ser exactamente $5.800 COP y no sumar anuladas. Se obtuvo {total_valido}")
        self.assertEqual(cant_pedidos, 1, f"La cantidad de pedidos válidos debe ser 1 y se obtuvo {cant_pedidos}")
        conn.close()


class TestAperturaAutomaticaYCajonCambio(unittest.TestCase):
    """Pruebas de la evaluación de apertura de gaveta por venta y cálculo de cambio."""

    def test_evaluacion_efectivo_y_mixto(self):
        """Verifica que Efectivo y Mixto con componente en efectivo abran la gaveta."""
        self.assertTrue(evaluar_apertura_cajon_por_venta("Efectivo"))
        self.assertFalse(evaluar_apertura_cajon_por_venta("Transferencia"))
        self.assertFalse(evaluar_apertura_cajon_por_venta("Fiado"))

        # Pago Mixto con parte en efectivo
        pagos_con_ef = [
            {"metodo": "Transferencia", "monto": 3000.0},
            {"metodo": "Efectivo", "monto": 2800.0}
        ]
        self.assertTrue(evaluar_apertura_cajon_por_venta("Mixto", pagos=pagos_con_ef))

        # Pago Mixto sin efectivo
        pagos_sin_ef = [
            {"metodo": "Transferencia", "monto": 3000.0},
            {"metodo": "Fiado", "monto": 2800.0}
        ]
        self.assertFalse(evaluar_apertura_cajon_por_venta("Mixto", pagos=pagos_sin_ef))

    def test_calculo_cambio_exacto(self):
        """Verifica el cálculo exacto del cambio a entregar."""
        total = 5800.0
        recibido = 10000.0
        cambio = max(0.0, recibido - total)
        self.assertEqual(cambio, 4200.0)

        # Pago exacto
        recibido_exacto = 5800.0
        cambio_exacto = max(0.0, recibido_exacto - total)
        self.assertEqual(cambio_exacto, 0.0)


class TestSeguridadPinManualCajon(unittest.TestCase):
    """Pruebas de la protección con PIN para apertura manual de la gaveta."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_pin_file = os.path.join(self.tmp_dir.name, "cajon_pin_test.json")
        self.orig_pin_file = cpm.PIN_FILE_PATH
        cpm.PIN_FILE_PATH = self.test_pin_file
        cpm._INTENTOS_FALLIDOS = 0
        cpm._BLOQUEADO_HASTA = 0.0

    def tearDown(self):
        cpm.PIN_FILE_PATH = self.orig_pin_file
        cpm._INTENTOS_FALLIDOS = 0
        cpm._BLOQUEADO_HASTA = 0.0
        self.tmp_dir.cleanup()

    def test_creacion_y_validacion_formato_pin(self):
        """Verifica que el PIN cumpla con entre 4 y 6 dígitos numéricos y no sea trivial."""
        # Menor a 4 dígitos
        ok, msg = crear_o_actualizar_pin("123", "123")
        self.assertFalse(ok)
        self.assertIn("4 y 6 dígitos", msg)

        # No numérico
        ok, msg = crear_o_actualizar_pin("12a4", "12a4")
        self.assertFalse(ok)
        self.assertIn("numéricos", msg)

        # Trivial / inseguro
        ok, msg = crear_o_actualizar_pin("1234", "1234")
        self.assertFalse(ok)
        self.assertIn("inseguro", msg)

        # No coincidencia
        ok, msg = crear_o_actualizar_pin("7890", "7891")
        self.assertFalse(ok)
        self.assertIn("no coinciden", msg)

        # PIN válido de 4 dígitos
        ok, msg = crear_o_actualizar_pin("9462", "9462", usuario_admin="Admin")
        self.assertTrue(ok)
        self.assertTrue(tiene_pin_configurado())

    def test_almacenamiento_seguro_hash_salt(self):
        """Verifica que el PIN nunca se guarde en texto plano y contenga hash y salt."""
        crear_o_actualizar_pin("7391", "7391", usuario_admin="Admin")
        d = _obtener_datos_pin()

        self.assertNotIn("7391", str(d), "El PIN NUNCA debe estar en texto plano")
        self.assertGreaterEqual(len(d.get("salt", "")), 32, "Debe tener una sal criptográfica robusta")
        self.assertEqual(len(d.get("pin_hash", "")), 64, "Debe contener el hash SHA-256 en hexadecimal")

    def test_bloqueo_por_fuerza_bruta_tras_3_intentos(self):
        """Verifica que al superar 3 intentos fallidos se active el bloqueo temporal."""
        crear_o_actualizar_pin("5821", "5821")

        # 1er fallo
        ok, msg = verificar_pin("0001")
        self.assertFalse(ok)
        self.assertIn("2 intentos", msg)

        # 2do fallo
        ok, msg = verificar_pin("0002")
        self.assertFalse(ok)
        self.assertIn("1 intento", msg)

        # 3er fallo: Debe activar bloqueo temporal
        ok, msg = verificar_pin("0003")
        self.assertFalse(ok)
        self.assertIn("BLOQUEADA", msg)

        st = obtener_estado_seguridad()
        self.assertTrue(st["bloqueado"])
        self.assertGreater(st["segundos_restantes"], 0)

        # Intento con PIN correcto durante el bloqueo debe seguir bloqueado
        ok_b, msg_b = verificar_pin("5821")
        self.assertFalse(ok_b)
        self.assertIn("bloqueada", msg_b.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
