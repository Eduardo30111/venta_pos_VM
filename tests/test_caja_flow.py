import os
import sqlite3
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from interface.database_manager import inicializar_base_datos
from interface.caja_manager import abrir_sesion_caja, calcular_arqueo_sesion, obtener_sesion_activa, editar_venta_completa
from interface.ventas_menu import guardar_venta_sqlite


class CajaFlowTest(unittest.TestCase):
    def setUp(self):
        inicializar_base_datos()
        conn = sqlite3.connect('database/ventas.db')
        cur = conn.cursor()
        cur.execute('DELETE FROM movimientos_caja')
        cur.execute('DELETE FROM detalle_ventas')
        cur.execute('DELETE FROM ventas')
        cur.execute('DELETE FROM sesiones_caja')
        conn.commit()
        conn.close()

    def test_guardar_venta_no_lanza_database_locked(self):
        sesion_id = abrir_sesion_caja('admin', 100000)
        self.assertIsNotNone(sesion_id)
        self.assertEqual(obtener_sesion_activa()['id'], sesion_id)

        venta_id = guardar_venta_sqlite(
            '123',
            20000,
            'Efectivo',
            [{'item_codigo': 'P1', 'item_nombre': 'Prod', 'precio_vendido': 20000, 'cantidad': 1, 'subtotal': 20000}],
            'admin'
        )

        self.assertIsNotNone(venta_id)

    def test_editar_efectivo_a_transferencia_reversa_caja(self):
        sesion_id = abrir_sesion_caja('admin', 100000)
        venta_id = guardar_venta_sqlite(
            '123',
            20000,
            'Efectivo',
            [{'item_codigo': 'P2', 'item_nombre': 'Prod', 'precio_vendido': 20000, 'cantidad': 1, 'subtotal': 20000}],
            'admin'
        )

        editar_venta_completa(
            venta_id,
            'admin',
            'Transferencia',
            [{'codigo_producto': 'P2', 'nombre_producto': 'Prod', 'precio_unitario': 20000, 'cantidad': 1}],
            'Cliente pagó por transferencia'
        )

        arqueo = calcular_arqueo_sesion(sesion_id)
        self.assertEqual(arqueo['ventas_efectivo'], 20000.0)
        self.assertEqual(arqueo['ajustes'], -20000.0)
        self.assertEqual(arqueo['efectivo_esperado'], 100000.0)


if __name__ == '__main__':
    unittest.main()
